import unittest
from unittest.mock import Mock, patch

from backend.worker import process_job


class WorkerClipCountTests(unittest.TestCase):
    def test_worker_passes_requested_count_and_reports_partial_candidates(self):
        job = {
            "job_id": "job-1",
            "status": "queued",
            "selected": [],
            "requested_clip_count": 5,
            "attempts": 0,
            "attention_gameplay": "none",
            "youtube_url": "https://youtu.be/example",
        }
        store = Mock()
        store.get.return_value = job
        store.is_cancel_requested.return_value = False
        candidates = [{"id": 1}, {"id": 2}]

        with (
            patch("backend.worker.job_store", store),
            patch("backend.worker.prepare_job", return_value=candidates) as prepare,
        ):
            process_job("job-1")

        prepare.assert_called_once()
        self.assertEqual(prepare.call_args.kwargs["clip_count"], 5)
        update = store.update.call_args.kwargs
        self.assertEqual(update["candidates"], candidates)
        self.assertIn("AI found 2 of 5", update["message"])


if __name__ == "__main__":
    unittest.main()
