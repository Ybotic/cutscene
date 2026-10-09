import tempfile
import unittest
from pathlib import Path

from backend.job_store import JobStore


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp_dir.name) / "jobs.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persists_job_fields_and_stage_timings(self):
        self.store.create("job-1", "https://youtu.be/example", "none")
        self.store.update(
            "job-1",
            status="review",
            message="Review candidates",
            candidates=[{"id": 1, "title": "A moment"}],
        )
        self.store.add_timing("job-1", "transcription", 12.3456)

        job = self.store.get("job-1")
        self.assertEqual(job["status"], "review")
        self.assertEqual(job["candidates"][0]["id"], 1)
        self.assertEqual(job["timings"]["transcription"], 12.346)
        self.assertEqual(job["progress"], 65)

    def test_interrupted_render_is_requeued_after_restart(self):
        self.store.create("job-2", "https://youtu.be/example", "none")
        self.store.update(
            "job-2",
            status="rendering",
            candidates=[{"id": 1}],
            selected=[{"candidate_id": 1}],
        )

        recovered = self.store.recover_interrupted()

        self.assertEqual([job["job_id"] for job in recovered], ["job-2"])
        self.assertEqual(recovered[0]["status"], "render_queued")

    def test_review_jobs_count_toward_queue_limit(self):
        self.store.create("job-3", "https://youtu.be/example", "none")
        self.store.update("job-3", status="review")
        self.assertEqual(self.store.count_active(), 1)

    def test_optional_notification_address_is_persisted(self):
        self.store.create(
            "job-email",
            "https://youtu.be/example",
            "none",
            notification_email="creator@example.com",
        )
        self.assertEqual(
            self.store.get("job-email")["notification_email"], "creator@example.com"
        )

    def test_review_can_only_be_queued_for_render_once(self):
        self.store.create("job-4", "https://youtu.be/example", "none")
        self.store.update("job-4", status="review")
        selected = [{"candidate_id": 1}]

        self.assertTrue(self.store.queue_reviewed_render("job-4", selected))
        self.assertFalse(self.store.queue_reviewed_render("job-4", selected))
        self.assertEqual(self.store.get("job-4")["status"], "render_queued")

    def test_queue_capacity_is_reserved_atomically(self):
        self.assertTrue(
            self.store.create("job-5", "https://youtu.be/one", "none", max_active=1)
        )
        self.assertFalse(
            self.store.create("job-6", "https://youtu.be/two", "none", max_active=1)
        )

    def test_worker_atomically_claims_jobs_from_persistent_queue(self):
        self.store.create("job-7", "https://youtu.be/example", "none")

        claimed = self.store.claim_next_job()

        self.assertEqual(claimed["job_id"], "job-7")
        self.assertEqual(claimed["status"], "downloading")
        self.assertIsNone(self.store.claim_next_job())

    def test_cancelled_queued_job_is_not_claimed(self):
        self.store.create("job-8", "https://youtu.be/example", "none")

        self.assertEqual(self.store.request_cancel("job-8"), "cancelled")
        self.assertIsNone(self.store.claim_next_job())
        self.assertEqual(self.store.get("job-8")["status"], "cancelled")

    def test_active_job_cancellation_is_flagged_for_worker(self):
        self.store.create("job-9", "https://youtu.be/example", "none")
        self.store.claim_next_job()

        self.assertEqual(self.store.request_cancel("job-9"), "cancelling")
        self.assertTrue(self.store.is_cancel_requested("job-9"))


if __name__ == "__main__":
    unittest.main()
