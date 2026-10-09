import json
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlparse

from backend.settings import settings


class DownloadError(RuntimeError):
    pass


def validate_youtube_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or hostname not in {
        "youtube.com",
        "m.youtube.com",
        "youtu.be",
    }:
        raise DownloadError("Please enter a valid YouTube URL.")


def download_video(
    url: str,
    job_dir: Path,
    *,
    check_cancelled: Callable[[], None] | None = None,
    update: Callable[[str, str], None] | None = None,
) -> Path:
    validate_youtube_url(url)

    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloadError("yt-dlp is not installed on the backend.") from exc

    output_template = str(job_dir / "source.%(ext)s")
    height = max(144, settings.max_download_height)
    last_progress = -5

    def progress_hook(data: dict) -> None:
        nonlocal last_progress
        if check_cancelled is not None:
            check_cancelled()
        if update is None or data.get("status") != "downloading":
            return
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes", 0)
        if total:
            percent = min(100, int(downloaded * 100 / total))
            if percent - last_progress >= 5:
                update("downloading", f"Downloading video ({percent}%)")
                last_progress = percent

    options = {
        "format": f"bv*[height<={height}]+ba/b[height<={height}]/worst[height<={height}]",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "max_filesize": 2 * 1024 * 1024 * 1024,
        "progress_hooks": [progress_hook],
    }
    if Path(settings.ffmpeg_binary).is_file():
        options["ffmpeg_location"] = str(Path(settings.ffmpeg_binary).parent)

    try:
        with yt_dlp.YoutubeDL(options) as client:
            # Resolve metadata first so over-length/oversize videos are rejected
            # before spending time and disk space on the full download.
            info = client.extract_info(url, download=False)
            duration = info.get("duration")
            if info.get("is_live") or info.get("is_upcoming"):
                raise DownloadError("Live and upcoming streams are not supported.")
            if duration and duration > settings.max_video_seconds:
                limit_minutes = max(1, settings.max_video_seconds // 60)
                raise DownloadError(
                    f"This video is longer than the {limit_minutes}-minute limit."
                )
            size = info.get("filesize") or info.get("filesize_approx")
            if size and size > 2 * 1024 * 1024 * 1024:
                raise DownloadError("This video is larger than the 2 GB download limit.")
            if check_cancelled is not None:
                check_cancelled()
            client.process_ie_result(info, download=True)
            (job_dir / "source_metadata.json").write_text(
                json.dumps({"duration": duration}), encoding="utf-8"
            )
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(f"Could not download the video: {exc}") from exc

    videos = sorted(job_dir.glob("source.*"))
    if not videos:
        raise DownloadError("The download completed without producing a video file.")
    return videos[0]
