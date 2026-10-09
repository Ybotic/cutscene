import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from backend.services.captions import write_ass_file
from backend.services.tracking import calculate_dynamic_crop, track_subject
from backend.settings import settings


class VideoEditorError(RuntimeError):
    pass


def _run_ffmpeg(
    args: list[str], check_cancelled: Callable[[], None] | None = None
) -> None:
    with tempfile.TemporaryFile(mode="w+t") as stderr_file:
        try:
            process = subprocess.Popen(
                [settings.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error", *args],
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                text=True,
            )
        except FileNotFoundError as exc:
            raise VideoEditorError("FFmpeg is not installed or is not on PATH.") from exc
        try:
            while process.poll() is None:
                if check_cancelled is not None:
                    try:
                        check_cancelled()
                    except Exception:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise
                time.sleep(0.25)
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        stderr_file.seek(0)
        stderr = stderr_file.read()
    if process.returncode != 0:
        detail = stderr.strip().splitlines()[-1:] or ["unknown FFmpeg error"]
        raise VideoEditorError(f"FFmpeg failed: {detail[0]}")


def render_clip(
    source: Path,
    transcript: dict,
    start: float,
    end: float,
    output_path: Path,
    subtitle_path: Path,
    *,
    gameplay_asset: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
    record_timing: Callable[[str, float], None] | None = None,
) -> None:
    write_ass_file(transcript, start, end, subtitle_path)
    duration = max(1.0, end - start)
    escaped_subtitle_path = subtitle_path.as_posix().replace(":", "\\:")
    subtitle_filter = f"subtitles={escaped_subtitle_path}"
    tracking_started = time.perf_counter()
    tracking = track_subject(str(source), start, end)
    if record_timing:
        record_timing("tracking", time.perf_counter() - tracking_started)
    dimensions = (int(tracking.get("width", 0)), int(tracking.get("height", 0)))
    if not all(dimensions):
        dimensions = _video_dimensions(source)
    main_height = 1248 if gameplay_asset else 1920
    crop = calculate_dynamic_crop(
        tracking, dimensions, output_dimensions=(1080, main_height), duration=duration
    )
    crop_filter = (
        f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']},"
        f"scale=1080:{main_height}:flags=lanczos,setsar=1"
    )
    if gameplay_asset:
        video_filter = (
            f"[0:v]{crop_filter}[main];"
            "[1:v]scale=1080:672:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=1080:672,setsar=1[game];"
            f"[main][game]vstack=inputs=2,{subtitle_filter}[outv]"
        )
        filter_args = ["-filter_complex", video_filter, "-map", "[outv]", "-map", "0:a?"]
        inputs = [
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source),
            "-stream_loop",
            "-1",
            "-i",
            str(gameplay_asset),
        ]
    else:
        video_filter = f"{crop_filter},{subtitle_filter}"
        filter_args = ["-vf", video_filter]
        inputs = ["-ss", f"{start:.3f}", "-i", str(source)]
    try:
        _run_ffmpeg(
            [
                *inputs,
                "-t",
                f"{duration:.3f}",
                *filter_args,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output_path),
            ],
            check_cancelled=check_cancelled,
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def _video_dimensions(source: Path) -> tuple[int, int]:
    try:
        result = subprocess.run(
            [
                settings.ffmpeg_binary.replace("ffmpeg", "ffprobe"),
                "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=width,height", "-of", "json", str(source),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(result.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        raise VideoEditorError("Could not determine the source video dimensions.")
