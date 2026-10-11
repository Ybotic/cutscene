import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend import main


class ClipCountApiTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.client = TestClient(main.app)
        self.store_patch = patch.object(main, "job_store", self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)

    @staticmethod
    def _candidate(candidate_id):
        return {
            "id": candidate_id,
            "title": f"Moment {candidate_id}",
            "reason": "A good moment",
            "score": 90,
            "start": candidate_id * 20,
            "end": candidate_id * 20 + 15,
            "source_duration": 200,
        }

    @staticmethod
    def _edit(candidate_id):
        start = candidate_id * 20
        return {
            "candidate_id": candidate_id,
            "title": f"Moment {candidate_id}",
            "start": start,
            "end": start + 15,
            "caption_text": "A moment",
        }

    def test_generate_persists_requested_count(self):
        self.store.create.return_value = True

        response = self.client.post(
            "/api/generate",
            json={"youtube_url": "https://youtu.be/example", "clip_count": 5},
        )

        self.assertEqual(response.status_code, 200)
        self.store.create.assert_called_once()
        self.assertEqual(
            self.store.create.call_args.kwargs["requested_clip_count"], 5
        )

    def test_generate_rejects_counts_above_five(self):
        response = self.client.post(
            "/api/generate",
            json={"youtube_url": "https://youtu.be/example", "clip_count": 6},
        )

        self.assertEqual(response.status_code, 422)
        self.store.create.assert_not_called()

    def test_review_accepts_fewer_candidates_than_requested(self):
        self.store.get.return_value = {
            "status": "review",
            "requested_clip_count": 5,
            "candidates": [self._candidate(1)],
        }
        self.store.queue_reviewed_render.return_value = True

        response = self.client.post(
            "/api/jobs/job-1/render", json={"clips": [self._edit(1)]}
        )

        self.assertEqual(response.status_code, 200)
        selected = self.store.queue_reviewed_render.call_args.args[1]
        self.assertEqual(len(selected), 1)

    def test_review_rejects_more_clips_than_requested(self):
        self.store.get.return_value = {
            "status": "review",
            "requested_clip_count": 1,
            "candidates": [self._candidate(1), self._candidate(2)],
        }

        response = self.client.post(
            "/api/jobs/job-1/render",
            json={"clips": [self._edit(1), self._edit(2)]},
        )

        self.assertEqual(response.status_code, 400)
        self.store.queue_reviewed_render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
