"""Small persistent SQLite store for local-MVP jobs and timings."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class JobStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    youtube_url TEXT NOT NULL,
                    attention_gameplay TEXT NOT NULL,
                    notification_email TEXT,
                    caption_language TEXT NOT NULL DEFAULT 'auto',
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    clips_json TEXT NOT NULL DEFAULT '[]',
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    selected_json TEXT NOT NULL DEFAULT '[]',
                    timings_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(jobs)")
            }
            if "notification_email" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN notification_email TEXT")
            if "caption_language" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN caption_language TEXT NOT NULL DEFAULT 'auto'"
                )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create(
        self,
        job_id: str,
        youtube_url: str,
        attention_gameplay: str,
        *,
        max_active: int | None = None,
        notification_email: str | None = None,
        caption_language: str = "auto",
    ) -> bool:
        now = time.time()
        with self._lock, self._connect() as connection:
            if max_active is not None:
                connection.execute("BEGIN IMMEDIATE")
                active = connection.execute(
                    "SELECT COUNT(*) AS count FROM jobs WHERE status NOT IN ('finished', 'failed', 'cancelled')"
                ).fetchone()["count"]
                if int(active) >= max_active:
                    return False
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, youtube_url, attention_gameplay, notification_email, caption_language,
                    status, message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', 'Queued for processing', ?, ?)
                """,
                (
                    job_id,
                    youtube_url,
                    attention_gameplay,
                    notification_email,
                    caption_language,
                    now,
                    now,
                ),
            )
        return True

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._to_dict(row) if row else None

    def update(self, job_id: str, **values: Any) -> None:
        allowed = {
            "status",
            "message",
            "clips",
            "candidates",
            "selected",
            "error",
            "cancel_requested",
            "attempts",
        }
        columns = []
        parameters: list[Any] = []
        json_fields = {
            "clips": "clips_json",
            "candidates": "candidates_json",
            "selected": "selected_json",
        }
        for key, value in values.items():
            if key not in allowed:
                raise ValueError(f"Unsupported job field: {key}")
            column = json_fields.get(key, key)
            if key in json_fields:
                value = json.dumps(value, ensure_ascii=False)
            elif key == "cancel_requested":
                value = int(bool(value))
            columns.append(f"{column} = ?")
            parameters.append(value)
        if not columns:
            return
        columns.append("updated_at = ?")
        parameters.extend((time.time(), job_id))
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(columns)} WHERE job_id = ?", parameters
            )

    def add_timing(self, job_id: str, name: str, seconds: float) -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT timings_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if not row:
                return
            timings = json.loads(row["timings_json"] or "{}")
            timings[name] = round(float(seconds), 3)
            connection.execute(
                "UPDATE jobs SET timings_json = ?, updated_at = ? WHERE job_id = ?",
                (json.dumps(timings), time.time(), job_id),
            )

    def queue_reviewed_render(
        self, job_id: str, selected: list[dict[str, Any]]
    ) -> bool:
        with self._lock, self._connect() as connection:
            result = connection.execute(
                """
                UPDATE jobs
                SET selected_json = ?, status = 'render_queued',
                    message = 'Your reviewed clips are queued for rendering.',
                    error = NULL, updated_at = ?
                WHERE job_id = ? AND status = 'review'
                """,
                (json.dumps(selected, ensure_ascii=False), time.time(), job_id),
            )
        return result.rowcount == 1

    def claim_next_job(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            while True:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status IN ('queued', 'render_queued')
                    ORDER BY created_at LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    return None
                if row["cancel_requested"]:
                    connection.execute(
                        "UPDATE jobs SET status = 'cancelled', message = 'Processing cancelled', updated_at = ? WHERE job_id = ?",
                        (time.time(), row["job_id"]),
                    )
                    continue
                claimed_status = "downloading" if row["status"] == "queued" else "aligning"
                connection.execute(
                    "UPDATE jobs SET status = ?, message = 'Worker picked up the job', updated_at = ? WHERE job_id = ?",
                    (claimed_status, time.time(), row["job_id"]),
                )
                claimed = connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)
                ).fetchone()
                return self._to_dict(claimed)

    def request_cancel(self, job_id: str) -> str | None:
        immediate_statuses = ("queued", "render_queued", "review")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            status = row["status"]
            if status in {"finished", "failed", "cancelled"}:
                return status
            if status in immediate_statuses:
                connection.execute(
                    "UPDATE jobs SET status = 'cancelled', message = 'Processing cancelled', cancel_requested = 1, updated_at = ? WHERE job_id = ?",
                    (time.time(), job_id),
                )
                return "cancelled"
            connection.execute(
                "UPDATE jobs SET message = 'Cancellation requested', cancel_requested = 1, updated_at = ? WHERE job_id = ?",
                (time.time(), job_id),
            )
            return "cancelling"

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return bool(row["cancel_requested"]) if row else True

    def count_active(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM jobs
                WHERE status NOT IN ('finished', 'failed', 'cancelled')
                """
            ).fetchone()
        return int(row["count"])

    def list_statuses(self, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY created_at",
                statuses,
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    def recover_interrupted(self) -> list[dict[str, Any]]:
        """Requeue interrupted work; prepared render jobs reuse their saved source."""
        active = (
            "downloading",
            "transcribing",
            "finding_moments",
            "aligning",
            "rendering",
        )
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status IN (?,?,?,?,?)",
                active,
            ).fetchall()
            for row in rows:
                has_candidates = row["candidates_json"] not in (None, "[]")
                next_status = "render_queued" if row["selected_json"] not in (None, "[]") else "queued"
                if not has_candidates and next_status == "render_queued":
                    next_status = "queued"
                connection.execute(
                    "UPDATE jobs SET status = ?, message = ?, updated_at = ? WHERE job_id = ?",
                    (next_status, "Resuming after backend restart", time.time(), row["job_id"]),
                )
            queued = connection.execute(
                "SELECT * FROM jobs WHERE status IN ('queued', 'render_queued') ORDER BY created_at"
            ).fetchall()
        return [self._to_dict(row) for row in queued]

    def expired_job_ids(self, older_than: float) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id FROM jobs
                WHERE status IN ('finished', 'failed', 'cancelled', 'review') AND updated_at < ?
                """,
                (older_than,),
            ).fetchall()
        return [row["job_id"] for row in rows]

    def delete_jobs(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                "DELETE FROM jobs WHERE job_id = ?",
                [(job_id,) for job_id in job_ids],
            )

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
        status = row["status"]
        progress = {
            "queued": 0,
            "downloading": 10,
            "transcribing": 30,
            "finding_moments": 55,
            "review": 65,
            "render_queued": 65,
            "aligning": 72,
            "rendering": 85,
            "finished": 100,
            "failed": 100,
            "cancelled": 100,
        }.get(status, 0)
        return {
            "job_id": row["job_id"],
            "youtube_url": row["youtube_url"],
            "attention_gameplay": row["attention_gameplay"],
            "caption_language": row["caption_language"],
            "notification_email": row["notification_email"],
            "status": status,
            "message": row["message"],
            "clips": json.loads(row["clips_json"] or "[]"),
            "candidates": json.loads(row["candidates_json"] or "[]"),
            "selected": json.loads(row["selected_json"] or "[]"),
            "timings": json.loads(row["timings_json"] or "{}"),
            "error": row["error"],
            "progress": progress,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "cancel_requested": bool(row["cancel_requested"]),
            "attempts": row["attempts"],
        }
