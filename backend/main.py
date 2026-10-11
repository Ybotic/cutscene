import mimetypes
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.job_store import JobStore
from backend.models import GenerateRequest, JobStatus, ReviewRequest
from backend.services.downloader import DownloadError, validate_youtube_url
from backend.services.email_notifications import email_is_configured
from backend.settings import settings


app = FastAPI(title="AI Clipper API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
job_store = JobStore(settings.data_dir / "jobs.sqlite3")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def public_config() -> dict[str, bool]:
    return {"email_notifications_available": email_is_configured()}


@app.post("/api/generate")
def generate(request: GenerateRequest) -> dict[str, str]:
    try:
        validate_youtube_url(request.youtube_url)
    except DownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.notification_email and not email_is_configured():
        raise HTTPException(
            status_code=400,
            detail="Email notifications are not configured on this backend.",
        )
    gameplay_files = {
        "subway_surfer": "subway_surfer.mp4",
        "minecraft_parkour": "minecraft_parkour.mp4",
    }
    gameplay_filename = gameplay_files.get(request.attention_gameplay)
    if gameplay_filename and not (settings.gameplay_dir / gameplay_filename).is_file():
        raise HTTPException(
            status_code=400,
            detail=f"Gameplay asset is missing: assets/gameplay/{gameplay_filename}.",
        )

    job_id = uuid.uuid4().hex
    accepted = job_store.create(
        job_id,
        request.youtube_url,
        request.attention_gameplay,
        requested_clip_count=request.clip_count,
        max_active=max(1, settings.max_queued_jobs),
        notification_email=request.notification_email,
    )
    if not accepted:
        raise HTTPException(
            status_code=429,
            detail="The processing queue is full. Try again later.",
        )
    return {"job_id": job_id}


@app.post("/api/jobs/{job_id}/render")
def render_reviewed_clips(job_id: str, request: ReviewRequest) -> dict[str, str]:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job["status"] != "review":
        raise HTTPException(status_code=409, detail="This job is not waiting for clip review.")

    candidates = {item["id"]: item for item in job["candidates"]}
    edits = [clip.model_dump() for clip in request.clips]
    selected_ids = [item["candidate_id"] for item in edits]
    if len(set(selected_ids)) != len(selected_ids) or any(
        candidate_id not in candidates for candidate_id in selected_ids
    ):
        raise HTTPException(
            status_code=400, detail="Choose different candidates from the listed moments."
        )
    if len(edits) > job["requested_clip_count"]:
        raise HTTPException(
            status_code=400,
            detail=f"You requested no more than {job['requested_clip_count']} clips.",
        )
    source_duration = max(
        (float(candidate.get("source_duration", 0)) for candidate in job["candidates"]),
        default=0.0,
    )
    if any(
        item["end"] > (source_duration or settings.max_video_seconds)
        for item in edits
    ):
        raise HTTPException(status_code=400, detail="Clip times exceed the source video duration.")
    ordered = sorted(edits, key=lambda item: item["start"])
    if any(left["end"] > right["start"] for left, right in zip(ordered, ordered[1:])):
        raise HTTPException(status_code=400, detail="Selected clips must not overlap.")

    selected = []
    for edit in edits:
        candidate = candidates[edit["candidate_id"]]
        selected.append(
            {
                **candidate,
                **edit,
                "reason": candidate["reason"],
                "score": candidate["score"],
            }
        )
    if not job_store.queue_reviewed_render(job_id, selected):
        raise HTTPException(status_code=409, detail="This job has already left the review step.")
    return {"job_id": job_id, "status": "render_queued"}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, str]:
    status = job_store.request_cancel(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if status == "cancelled":
        shutil.rmtree(settings.temp_dir / job_id, ignore_errors=True)
        shutil.rmtree(settings.output_dir / job_id, ignore_errors=True)
    return {"job_id": job_id, "status": status}


@app.get("/api/status/{job_id}", response_model=JobStatus)
def status(job_id: str) -> JobStatus:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatus(**job)


@app.get("/api/source/{job_id}")
def source_file(job_id: str) -> FileResponse:
    if len(job_id) != 32 or any(character not in "0123456789abcdef" for character in job_id):
        raise HTTPException(status_code=400, detail="Invalid job id.")
    job = job_store.get(job_id)
    if not job or job["status"] != "review":
        raise HTTPException(status_code=404, detail="Review source is not available.")
    sources = sorted((settings.temp_dir / job_id).glob("source.*"))
    if not sources:
        raise HTTPException(status_code=404, detail="Source video not found.")
    source = sources[0]
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    return FileResponse(source, media_type=media_type)


@app.get("/api/clips/{job_id}/{filename}")
def clip_file(job_id: str, filename: str) -> FileResponse:
    if (
        len(job_id) != 32
        or any(character not in "0123456789abcdef" for character in job_id)
        or Path(filename).name != filename
        or not filename.endswith(".mp4")
    ):
        raise HTTPException(status_code=400, detail="Invalid clip filename.")
    path = settings.output_dir / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found.")
    return FileResponse(path, media_type="video/mp4", filename=filename)
