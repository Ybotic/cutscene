"""Lightweight sampled visual context for AI clip ranking."""

from __future__ import annotations

import base64
from typing import Any


def sample_candidate_frames(
    video_path: str,
    candidates: list[Any],
    *,
    max_dimension: int = 512,
) -> list[dict[str, Any]]:
    """Sample three small JPEGs per candidate and flag large visual changes."""
    try:
        import cv2

        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            return []
        try:
            samples = []
            for candidate_id, candidate in enumerate(candidates, start=1):
                duration = max(0.0, float(candidate.end) - float(candidate.start))
                candidate_samples = []
                previous_histogram = None
                for fraction in (0.12, 0.5, 0.88):
                    timestamp = float(candidate.start) + duration * fraction
                    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                    ok, frame = capture.read()
                    if not ok:
                        continue
                    height, width = frame.shape[:2]
                    scale = min(1.0, max_dimension / max(width, height))
                    if scale < 1.0:
                        frame = cv2.resize(
                            frame,
                            None,
                            fx=scale,
                            fy=scale,
                            interpolation=cv2.INTER_AREA,
                        )
                    histogram = cv2.calcHist(
                        [cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)],
                        [0, 1],
                        None,
                        [16, 16],
                        [0, 180, 0, 256],
                    )
                    cv2.normalize(histogram, histogram)
                    scene_change = (
                        previous_histogram is not None
                        and cv2.compareHist(
                            previous_histogram, histogram, cv2.HISTCMP_CORREL
                        )
                        < 0.45
                    )
                    previous_histogram = histogram
                    encoded_ok, encoded = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65]
                    )
                    if not encoded_ok:
                        continue
                    data_url = "data:image/jpeg;base64," + base64.b64encode(
                        encoded.tobytes()
                    ).decode("ascii")
                    candidate_samples.append(
                        {
                            "time": timestamp,
                            "scene_change": scene_change,
                            "data_url": data_url,
                        }
                    )
                if candidate_samples:
                    samples.append(
                        {"candidate_id": candidate_id, "frames": candidate_samples}
                    )
            return samples
        finally:
            capture.release()
    except Exception:
        return []
