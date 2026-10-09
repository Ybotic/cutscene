import unittest

from backend.evaluation.metrics import evaluate, temporal_iou
from backend.evaluation.benchmark_whisper import _word_error_rate


class EvaluationMetricTests(unittest.TestCase):
    def test_word_error_rate_counts_substitutions(self):
        self.assertAlmostEqual(_word_error_rate("one two three", "one too three"), 1 / 3)

    def test_temporal_iou_measures_overlap(self):
        self.assertAlmostEqual(
            temporal_iou({"start": 0, "end": 10}, {"start": 5, "end": 15}),
            1 / 3,
        )

    def test_report_summarizes_clip_caption_and_tracking_quality(self):
        report = evaluate(
            [
                {
                    "human_clips": [{"start": 10, "end": 20, "rating": 5}],
                    "predicted_clips": [{"start": 11, "end": 21, "score": 90}],
                    "candidate_ratings": [
                        {"score": 90, "rating": 5},
                        {"score": 60, "rating": 2},
                    ],
                    "caption_timings": [
                        {
                            "reference_start": 2.0,
                            "predicted_start": 2.2,
                            "reference_end": 2.5,
                            "predicted_end": 2.6,
                        }
                    ],
                    "tracking": {
                        "reference": [{"time": 0, "x_norm": 0.5, "y_norm": 0.5}],
                        "predicted": [{"time": 0, "x_norm": 0.6, "y_norm": 0.5}],
                    },
                }
            ]
        )
        self.assertEqual(report["source_count"], 1)
        self.assertEqual(report["recall_at_iou_0_5"], 1.0)
        self.assertEqual(report["candidate_score_rating_correlation"], 1.0)
        self.assertEqual(report["caption_boundary_mae_seconds"], 0.15)
        self.assertEqual(report["tracking_center_error_norm"], 0.1)


if __name__ == "__main__":
    unittest.main()
