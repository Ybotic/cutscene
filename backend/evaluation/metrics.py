"""Compute simple offline metrics from manually reviewed JSON annotations."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def temporal_iou(left: dict[str, float], right: dict[str, float]) -> float:
    intersection = max(0.0, min(left["end"], right["end"]) - max(left["start"], right["start"]))
    union = max(left["end"], right["end"]) - min(left["start"], right["start"])
    return intersection / union if union > 0 else 0.0


def evaluate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    best_ious = []
    score_rating_pairs = []
    caption_errors = []
    tracking_errors = []
    for sample in samples:
        predicted = sample.get("predicted_clips", [])
        for reference in sample.get("human_clips", []):
            best_ious.append(
                max((temporal_iou(reference, clip) for clip in predicted), default=0.0)
            )
        for rating in sample.get("candidate_ratings", []):
            score_rating_pairs.append((float(rating["score"]), float(rating["rating"])))
        for word in sample.get("caption_timings", []):
            caption_errors.extend(
                [
                    abs(word["reference_start"] - word["predicted_start"]),
                    abs(word["reference_end"] - word["predicted_end"]),
                ]
            )
        tracking = sample.get("tracking", {})
        predicted_points = tracking.get("predicted", [])
        for reference_point in tracking.get("reference", []):
            if not predicted_points:
                tracking_errors.append(1.0)
                continue
            nearest = min(
                predicted_points,
                key=lambda point: abs(point["time"] - reference_point["time"]),
            )
            tracking_errors.append(
                (
                    (nearest["x_norm"] - reference_point["x_norm"]) ** 2
                    + (nearest["y_norm"] - reference_point["y_norm"]) ** 2
                )
                ** 0.5
            )

    return {
        "source_count": len(samples),
        "human_clip_count": len(best_ious),
        "mean_best_temporal_iou": _mean(best_ious),
        "recall_at_iou_0_5": (
            sum(iou >= 0.5 for iou in best_ious) / len(best_ious) if best_ious else 0.0
        ),
        "candidate_score_rating_correlation": _pearson(score_rating_pairs),
        "caption_boundary_mae_seconds": _mean(caption_errors),
        "tracking_center_error_norm": _mean(tracking_errors),
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _pearson(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 2:
        return 0.0
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = (variance_x * variance_y) ** 0.5
    return round(covariance / denominator, 4) if denominator else 0.0


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m backend.evaluation.metrics annotations.json")
    annotation_path = Path(sys.argv[1])
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    report = evaluate(annotations.get("samples", []))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
