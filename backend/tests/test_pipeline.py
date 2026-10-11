import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.pipeline import prepare_job
from backend.services.clip_detector import CandidateClip


class PrepareJobTests(unittest.TestCase):
    def test_requested_count_is_passed_to_ai_clip_detector(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir)
            source = job_dir / "source.mp4"
            metadata = job_dir / "source_metadata.json"
            metadata.write_text(json.dumps({"duration": 120}), encoding="utf-8")
            transcript = {
                "language": "en",
                "segments": [{"start": 10, "end": 25, "text": "A moment"}],
            }
            candidates = [CandidateClip(10, 25, "Moment", "Reason", 90)]

            with (
                patch("backend.pipeline._gameplay_asset"),
                patch("backend.pipeline.download_video", return_value=source),
                patch("backend.pipeline.transcribe", return_value=transcript),
                patch("backend.pipeline.find_best_clips", return_value=candidates) as finder,
                patch(
                    "backend.pipeline._timed",
                    side_effect=lambda _name, _record, operation: operation(),
                ),
            ):
                result = prepare_job(
                    "https://youtu.be/example",
                    "none",
                    job_dir,
                    lambda *_: None,
                    lambda *_: None,
                    lambda: None,
                    clip_count=5,
                )

            finder.assert_called_once_with(transcript, source, clip_count=5)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["source_duration"], 120)


if __name__ == "__main__":
    unittest.main()
