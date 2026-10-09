import json
import subprocess
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.settings import settings


class TranscriptionError(RuntimeError):
    pass


_model = None
_model_lock = Lock()


def _patch_whisper_timing() -> None:
    import whisper.timing as timing

    if getattr(timing, "_clipper_timing_patched", False):
        return

    original_median_filter = timing.median_filter
    original_dtw = timing.dtw

    def median_filter_compat(x, filter_width):
        try:
            return original_median_filter(x, filter_width)
        except TypeError:
            return x.unfold(-1, filter_width, 1).sort()[0][..., filter_width // 2]

    def dtw_compat(x):
        try:
            return original_dtw(x)
        except TypeError:
            return timing.dtw_cpu(x.double().cpu().numpy())

    timing.median_filter = median_filter_compat
    timing.dtw = dtw_compat
    timing._clipper_timing_patched = True


def _get_device() -> str:
    try:
        import torch
    except Exception as exc:
        raise TranscriptionError(f"Could not load PyTorch: {exc}") from exc

    configured = settings.whisper_device.strip().lower()
    if configured == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if configured == "cuda" and not torch.cuda.is_available():
        raise TranscriptionError(
            "WHISPER_DEVICE=cuda was requested, but CUDA is not available."
        )
    return configured


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            try:
                import whisper

                device = _get_device()
                if device == "cuda":
                    _patch_whisper_timing()
                print(f"Loading Whisper {settings.whisper_model} on {device}")
                _model = whisper.load_model(settings.whisper_model, device=device)
            except Exception as exc:
                if isinstance(exc, TranscriptionError):
                    raise
                raise TranscriptionError(f"Could not load Whisper: {exc}") from exc
    return _model


def transcribe(
    video_path: Path,
    transcript_path: Path,
    *,
    word_timestamps: bool = True,
) -> dict[str, Any]:
    transcript = _transcribe_file(video_path, word_timestamps=word_timestamps)
    transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    return transcript


def transcribe_range(
    video_path: Path,
    start: float,
    end: float,
    scratch_dir: Path,
) -> dict[str, Any]:
    """Generate word timings only for a selected range and return source-time stamps."""
    duration = end - start
    if start < 0 or duration <= 0:
        raise TranscriptionError("The selected clip range is invalid.")
    audio_path = scratch_dir / f"alignment_{uuid4().hex}.wav"
    try:
        try:
            process = subprocess.run(
                [
                    settings.ffmpeg_binary,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{start:.3f}",
                    "-i",
                    str(video_path),
                    "-t",
                    f"{duration:.3f}",
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(audio_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise TranscriptionError("FFmpeg could not prepare clip audio.") from exc
        if process.returncode != 0:
            raise TranscriptionError("FFmpeg could not prepare clip audio.")
        transcript = _transcribe_file(audio_path, word_timestamps=True)
        for segment in transcript["segments"]:
            segment["start"] += start
            segment["end"] += start
            for word in segment["words"]:
                word["start"] += start
                word["end"] += start
        return transcript
    finally:
        audio_path.unlink(missing_ok=True)


def _transcribe_file(video_path: Path, *, word_timestamps: bool) -> dict[str, Any]:
    try:
        result = _get_model().transcribe(
            str(video_path), word_timestamps=word_timestamps, verbose=False
        )
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    segments = []
    for segment in result.get("segments", []):
        words = [
            {
                "word": str(word.get("word", "")).strip(),
                "start": float(word.get("start", segment["start"])),
                "end": float(word.get("end", segment["end"])),
            }
            for word in segment.get("words", [])
            if str(word.get("word", "")).strip()
        ]
        segments.append(
            {
                "start": float(segment["start"]),
                "end": float(segment["end"]),
                "text": str(segment.get("text", "")).strip(),
                "words": words,
            }
        )

    if not segments:
        raise TranscriptionError("The video did not contain usable speech.")

    return {"segments": segments}
