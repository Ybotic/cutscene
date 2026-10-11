import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.services.clip_detector import ClipDetectionError, find_best_clips


class ClipDetectorTests(unittest.TestCase):
    def setUp(self):
        self.transcript = {"segments": [{"start": 0, "end": 100, "text": "speech"}]}
        self.payload = {
            "clips": [
                {"start": 10, "end": 25, "title": "First", "score": 90},
                {"start": 12, "end": 28, "title": "Overlap", "score": 80},
                {"start": 30, "end": 45, "title": "Second", "score": 70},
                {"start": 50, "end": 55, "title": "Too short", "score": 100},
            ]
        }

    def _run_detector(self, clip_count):
        completion = Mock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(self.payload))
                    )
                ]
            )
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=completion))
        )
        openai_module = SimpleNamespace(OpenAI=Mock(return_value=client))
        settings = SimpleNamespace(
            openrouter_api_key="test-key", openrouter_model="test-model"
        )
        with (
            patch("backend.services.clip_detector.settings", settings),
            patch.dict(sys.modules, {"openai": openai_module}),
        ):
            results = find_best_clips(self.transcript, clip_count=clip_count)
        return results, completion

    def test_returns_all_usable_moments_when_fewer_than_requested(self):
        results, _ = self._run_detector(5)

        self.assertEqual([clip.title for clip in results], ["First", "Second"])

    def test_truncates_candidates_to_the_requested_count(self):
        results, completion = self._run_detector(1)

        self.assertEqual([clip.title for clip in results], ["First"])
        prompt = completion.call_args.kwargs["messages"][0]["content"]
        self.assertIn("up to 1 non-overlapping candidates", prompt)
        self.assertIn(
            "no more than 1 clip",
            completion.call_args.kwargs["messages"][1]["content"],
        )

    def test_no_usable_candidate_returns_clear_error(self):
        self.payload = {"clips": [{"start": 1, "end": 5, "score": 100}]}

        with self.assertRaisesRegex(ClipDetectionError, "could not find a usable"):
            self._run_detector(5)

    def test_empty_transcript_does_not_call_external_model(self):
        with self.assertRaisesRegex(ClipDetectionError, "no usable speech"):
            find_best_clips({"segments": []}, clip_count=5)

    def test_rejects_counts_above_supported_limit(self):
        with self.assertRaises(ValueError):
            find_best_clips(self.transcript, clip_count=6)


if __name__ == "__main__":
    unittest.main()
