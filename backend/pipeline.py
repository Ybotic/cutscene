import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from backend.constants import DEFAULT_CLIP_COUNT
from backend.services.clip_detector import find_best_clips
from backend.services.captions import replace_caption_text
from backend.services.caption_translation import transliterate_hindi_captions
from backend.services.downloader import download_video
from backend.services.transcription import transcribe, transcribe_range
from backend.services.video_editor import render_clip
from backend.settings import settings


Update = Callable[[str, str], None]
RecordTiming = Callable[[str, float], None]
CheckCancelled = Callable[[], None]


def prepare_job(
    youtube_url: str,
    attention_gameplay: str,
    job_dir: Path,
    update: Update,
    record_timing: RecordTiming,
    check_cancelled: CheckCancelled,
    clip_count: int = DEFAULT_CLIP_COUNT,
) -> list[dict[str, Any]]:
    """Download, transcribe coarsely, and return candidates for user review."""
    check_cancelled()
    _gameplay_asset(attention_gameplay)
    update("downloading", "Checking video and downloading up to 1080p")
    source = _timed(
        "download",
        record_timing,
        lambda: download_video(
            youtube_url,
            job_dir,
            check_cancelled=check_cancelled,
            update=update,
        ),
    )

    check_cancelled()
    update("transcribing", "Transcribing audio (word alignment follows clip selection)")
    transcript_path = job_dir / "transcript.json"
    transcript = _timed(
        "transcription",
        record_timing,
        lambda: transcribe(source, transcript_path, word_timestamps=False),
    )

    check_cancelled()
    update("finding_moments", "Finding moments from speech and sampled video frames")
    candidates = _timed(
        "clip_selection",
        record_timing,
        lambda: find_best_clips(transcript, source, clip_count=clip_count),
    )
    metadata_path = job_dir / "source_metadata.json"
    source_duration = (
        float(json.loads(metadata_path.read_text(encoding="utf-8")).get("duration") or 0)
        if metadata_path.is_file()
        else 0.0
    )
    if source_duration <= 0:
        source_duration = max(float(segment["end"]) for segment in transcript["segments"])
    return [
        {
            "id": index,
            "title": clip.title,
            "reason": clip.reason,
            "score": clip.score,
            "start": clip.start,
            "end": clip.end,
            "caption_text": _caption_text(transcript, clip.start, clip.end),
            "source_duration": source_duration,
        }
        for index, clip in enumerate(candidates, start=1)
    ]


def render_selected(
    job_id: str,
    selected: list[dict[str, Any]],
    job_dir: Path,
    output_dir: Path,
    attention_gameplay: str,
    update: Update,
    record_timing: RecordTiming,
    check_cancelled: CheckCancelled,
) -> list[dict[str, Any]]:
    """Word-align only reviewed clips, then render with bounded concurrency."""
    check_cancelled()
    source = _source_path(job_dir)
    transcript_path = job_dir / "transcript.json"
    if not transcript_path.is_file():
        raise RuntimeError("The saved transcript is missing; regenerate the candidates.")
    coarse_transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    gameplay_asset = _gameplay_asset(attention_gameplay)
    caption_texts = {
        index: str(edit.get("caption_text", ""))
        for index, edit in enumerate(selected, start=1)
    }
    update(
        "aligning",
        "Detecting Hindi captions and creating Hinglish when detected",
    )
    translated_captions = _timed(
        "caption_transliteration",
        record_timing,
        lambda: transliterate_hindi_captions(
            caption_texts,
            coarse_transcript.get("language"),
        ),
    )

    aligned: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, edit in enumerate(selected, start=1):
        check_cancelled()
        update("aligning", f"Aligning captions for clip {index} of {len(selected)}")
        detailed = _timed(
            f"word_alignment_clip_{index}",
            record_timing,
            lambda edit=edit: transcribe_range(
                source, float(edit["start"]), float(edit["end"]), job_dir
            ),
        )
        caption_text = translated_captions.get(index, edit.get("caption_text"))
        if caption_text is not None:
            detailed = replace_caption_text(
                detailed,
                str(caption_text),
                float(edit["start"]),
                float(edit["end"]),
            )
        aligned.append((index, edit, detailed))

    job_output = output_dir / job_id
    job_output.mkdir(parents=True, exist_ok=True)

    def render_one(
        item: tuple[int, dict[str, Any], dict[str, Any]],
    ) -> dict[str, Any]:
        index, edit, clip_transcript = item
        check_cancelled()
        output_path = job_output / f"clip_{index}.mp4"
        subtitle_path = job_dir / f"clip_{index}.ass"
        started = time.perf_counter()
        render_clip(
            source,
            clip_transcript,
            float(edit["start"]),
            float(edit["end"]),
            output_path,
            subtitle_path,
            gameplay_asset=gameplay_asset,
            check_cancelled=check_cancelled,
            record_timing=lambda name, duration: record_timing(
                f"clip_{index}_{name}", duration
            ),
        )
        record_timing(f"render_clip_{index}", time.perf_counter() - started)
        return {
            "id": index,
            "title": str(edit["title"])[:120],
            "reason": str(edit.get("reason", "User-selected moment."))[:300],
            "score": max(0, min(100, int(edit.get("score", 0)))),
            "start": float(edit["start"]),
            "end": float(edit["end"]),
            "url": f"/api/clips/{job_id}/clip_{index}.mp4",
        }

    update("rendering", f"Rendering {len(aligned)} reviewed clips")
    results: list[dict[str, Any] | None] = [None] * len(aligned)
    workers = max(1, min(settings.render_workers, len(aligned)))
    render_batch_started = time.perf_counter()
    if workers == 1:
        for item in aligned:
            result = render_one(item)
            results[item[0] - 1] = result
            update("rendering", f"Rendered clip {item[0]} of {len(aligned)}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(render_one, item): item for item in aligned}
            for future in as_completed(futures):
                item = futures[future]
                results[item[0] - 1] = future.result()
                update("rendering", f"Rendered clip {item[0]} of {len(aligned)}")
    record_timing("render_batch_wall", time.perf_counter() - render_batch_started)

    check_cancelled()
    return [result for result in results if result is not None]


def _source_path(job_dir: Path) -> Path:
    sources = sorted(job_dir.glob("source.*"))
    if not sources:
        raise RuntimeError("The downloaded source video is missing.")
    return sources[0]


def _caption_text(transcript: dict[str, Any], start: float, end: float) -> str:
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in transcript.get("segments", [])
        if float(segment["end"]) > start and float(segment["start"]) < end
    ).strip()


def _timed(name: str, record_timing: RecordTiming, operation: Callable[[], Any]) -> Any:
    started = time.perf_counter()
    try:
        return operation()
    finally:
        record_timing(name, time.perf_counter() - started)


def _gameplay_asset(selection: str) -> Path | None:
    if selection == "none":
        return None
    filenames = {
        "subway_surfer": "subway_surfer.mp4",
        "minecraft_parkour": "minecraft_parkour.mp4",
    }
    filename = filenames.get(selection)
    if filename is None:
        raise ValueError("Unsupported attention gameplay selection.")
    asset = settings.gameplay_dir / filename
    if not asset.is_file():
        raise FileNotFoundError(
            f"Gameplay asset is missing: assets/gameplay/{filename}. Add the video locally and try again."
        )
    return asset
