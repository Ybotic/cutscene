"""Persistent SQLite queue worker. Run with ``python -m backend.worker``."""

from __future__ import annotations

import logging
import shutil
import signal
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from backend.job_store import JobStore
from backend.pipeline import prepare_job, render_selected
from backend.services.email_notifications import send_job_notification
from backend.services.transcription import _get_model
from backend.settings import settings


logger = logging.getLogger(__name__)
job_store = JobStore(settings.data_dir / "jobs.sqlite3")


class JobCancelled(Exception):
    pass


def _check_cancelled(job_id: str) -> None:
    if job_store.is_cancel_requested(job_id):
        raise JobCancelled("Processing was cancelled.")


def _set_stage(job_id: str, status: str, message: str) -> None:
    job_store.update(job_id, status=status, message=message)


def _record_timing(job_id: str, name: str, seconds: float) -> None:
    job_store.add_timing(job_id, name, seconds)
    logger.info("job=%s stage=%s elapsed_seconds=%.3f", job_id, name, seconds)


def _is_retryable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "timeout",
            "temporarily",
            "connection",
            "rate limit",
            "429",
            "502",
            "503",
            "504",
            "server error",
        )
    )


def _cleanup_job_files(job_id: str) -> None:
    shutil.rmtree(settings.temp_dir / job_id, ignore_errors=True)
    shutil.rmtree(settings.output_dir / job_id, ignore_errors=True)


def _send_email_notification(
    job_id: str,
    *,
    clips: list[dict] | None = None,
    error: str | None = None,
) -> None:
    job = job_store.get(job_id)
    recipient = job.get("notification_email") if job else None
    if not recipient:
        return
    try:
        send_job_notification(recipient, job_id, clips=clips, error=error)
    except Exception:
        logger.exception("job=%s completion email could not be sent", job_id)


def process_job(job_id: str) -> None:
    for attempt in range(max(0, settings.max_job_retries) + 1):
        job = job_store.get(job_id)
        if job is None:
            return
        job_dir = settings.temp_dir / job_id
        try:
            _check_cancelled(job_id)
            if job["selected"]:
                clips = render_selected(
                    job_id,
                    job["selected"],
                    job_dir,
                    settings.output_dir,
                    job["attention_gameplay"],
                    lambda status, message: _set_stage(job_id, status, message),
                    lambda name, seconds: _record_timing(job_id, name, seconds),
                    lambda: _check_cancelled(job_id),
                )
                job_store.update(
                    job_id, status="finished", message="Finished", clips=clips, error=None
                )
                shutil.rmtree(job_dir, ignore_errors=True)
                _send_email_notification(job_id, clips=clips)
                return

            # Preparation restarts cleanly after a transient failure or worker restart.
            shutil.rmtree(job_dir, ignore_errors=True)
            job_dir.mkdir(parents=True, exist_ok=True)
            candidates = prepare_job(
                job["youtube_url"],
                job["attention_gameplay"],
                job_dir,
                lambda status, message: _set_stage(job_id, status, message),
                lambda name, seconds: _record_timing(job_id, name, seconds),
                lambda: _check_cancelled(job_id),
                clip_count=job["requested_clip_count"],
            )
            _check_cancelled(job_id)
            if len(candidates) < job["requested_clip_count"]:
                review_message = (
                    f"AI found {len(candidates)} of {job['requested_clip_count']} "
                    "requested moments. Choose from the available clips, then render."
                )
            else:
                review_message = (
                    f"Found {len(candidates)} moments. Choose the clips to render."
                )
            job_store.update(
                job_id,
                status="review",
                message=review_message,
                candidates=candidates,
                error=None,
            )
            return
        except JobCancelled:
            _cleanup_job_files(job_id)
            job_store.update(
                job_id,
                status="cancelled",
                message="Processing cancelled",
                error=None,
                cancel_requested=True,
            )
            return
        except Exception as exc:
            if job_store.is_cancel_requested(job_id):
                _cleanup_job_files(job_id)
                job_store.update(
                    job_id,
                    status="cancelled",
                    message="Processing cancelled",
                    error=None,
                )
                return
            current = job_store.get(job_id) or job
            retrying = attempt < settings.max_job_retries and _is_retryable(exc)
            if retrying:
                logger.warning(
                    "job=%s attempt=%s retryable_failure=%s", job_id, attempt + 1, exc
                )
                status = "aligning" if current["selected"] else "downloading"
                job_store.update(
                    job_id,
                    status=status,
                    message=f"Temporary processing error; retrying ({attempt + 1})",
                    error=None,
                    attempts=current["attempts"] + 1,
                )
                if not current["selected"]:
                    shutil.rmtree(job_dir, ignore_errors=True)
                time.sleep(min(2**attempt, 5))
                continue
            logger.exception("job=%s failed", job_id)
            _cleanup_job_files(job_id)
            job_store.update(
                job_id,
                status="failed",
                message="Processing failed",
                error=str(exc)[:1000],
            )
            _send_email_notification(job_id, error=str(exc)[:1000])
            return


def _cleanup_expired_jobs() -> None:
    retention_seconds = max(1, settings.job_retention_days) * 24 * 60 * 60
    expired = job_store.expired_job_ids(time.time() - retention_seconds)
    for job_id in expired:
        _cleanup_job_files(job_id)
    job_store.delete_jobs(expired)


def _warm_whisper() -> None:
    try:
        _get_model()
        logger.info("Whisper model warmed successfully")
    except Exception:
        logger.exception("Whisper warmup failed; it will load when a job starts")


def run_worker() -> None:
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    _cleanup_expired_jobs()
    job_store.recover_interrupted()
    threading.Thread(target=_warm_whisper, name="whisper-warmup", daemon=True).start()

    max_workers = max(1, settings.max_concurrent_jobs)
    running: dict[Future, str] = {}
    next_cleanup = time.monotonic() + 6 * 60 * 60
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while not stop_event.is_set():
            for future, job_id in list(running.items()):
                if not future.done():
                    continue
                try:
                    future.result()
                except Exception:
                    logger.exception("Unhandled worker error for job=%s", job_id)
                    _cleanup_job_files(job_id)
                    job_store.update(
                        job_id,
                        status="failed",
                        message="Worker failed unexpectedly",
                        error="The worker encountered an unexpected error.",
                    )
                running.pop(future, None)

            while len(running) < max_workers:
                job = job_store.claim_next_job()
                if job is None:
                    break
                future = executor.submit(process_job, job["job_id"])
                running[future] = job["job_id"]

            if time.monotonic() >= next_cleanup:
                try:
                    _cleanup_expired_jobs()
                except Exception:
                    logger.exception("Job retention cleanup failed")
                next_cleanup = time.monotonic() + 6 * 60 * 60
            stop_event.wait(0.5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
