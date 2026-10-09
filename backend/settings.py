from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-6-luna")
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "auto")
    max_video_seconds: int = int(os.getenv("MAX_VIDEO_SECONDS", "7200"))
    max_download_height: int = int(os.getenv("MAX_DOWNLOAD_HEIGHT", "1080"))
    max_concurrent_jobs: int = int(os.getenv("MAX_CONCURRENT_JOBS", "1"))
    max_queued_jobs: int = int(os.getenv("MAX_QUEUED_JOBS", "8"))
    max_job_retries: int = int(os.getenv("MAX_JOB_RETRIES", "1"))
    job_retention_days: int = int(os.getenv("JOB_RETENTION_DAYS", "7"))
    render_workers: int = int(os.getenv("RENDER_WORKERS", "1"))
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_starttls: bool = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
    public_api_origin: str = os.getenv("PUBLIC_API_ORIGIN", "http://localhost:8000")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    ffmpeg_binary: str = os.getenv(
        "FFMPEG_BINARY",
        str(ROOT_DIR / ".tools" / "bin" / "ffmpeg")
        if (ROOT_DIR / ".tools" / "bin" / "ffmpeg").is_file()
        else "ffmpeg",
    )
    temp_dir: Path = ROOT_DIR / "temp"
    output_dir: Path = ROOT_DIR / "output"
    data_dir: Path = ROOT_DIR / "data"
    gameplay_dir: Path = ROOT_DIR / "assets" / "gameplay"


settings = Settings()
settings.temp_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.data_dir.mkdir(parents=True, exist_ok=True)

if settings.ffmpeg_binary != "ffmpeg":
    ffmpeg_dir = str(Path(settings.ffmpeg_binary).resolve().parent)
    os.environ["PATH"] = os.pathsep.join(
        part for part in (ffmpeg_dir, os.environ.get("PATH", "")) if part
    )
