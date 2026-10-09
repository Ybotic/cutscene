"""Best-effort face tracking and smooth FFmpeg crop generation."""

from __future__ import annotations

import math
from typing import Any


def track_subject(video_path: str, start: float = 0.0, end: float | None = None) -> dict[str, Any]:
    """Sample a clip for prominent faces. Returns an empty result when tracking is unreliable."""
    try:
        import cv2

        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            return {}
        try:
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if frame_count else 0.0
            clip_end = min(end if end is not None else duration, duration)
            if width <= 0 or height <= 0 or clip_end <= start:
                return {}

            detector = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            profile_detector = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_profileface.xml"
            )
            if detector.empty() and profile_detector.empty():
                return {}
            samples: list[dict[str, float]] = []
            previous_face = None
            sample_times = _sample_times(start, clip_end)
            for timestamp in sample_times:
                capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                ok, frame = capture.read()
                if not ok:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                scale = min(1.0, 960 / max(width, height))
                if scale < 1.0:
                    gray = cv2.resize(
                        gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                    )
                gray = cv2.equalizeHist(gray)
                min_face_size = max(12, int(32 * scale))
                detected = []
                if not detector.empty():
                    detected = list(
                        detector.detectMultiScale(
                            gray,
                            scaleFactor=1.1,
                            minNeighbors=5,
                            minSize=(min_face_size, min_face_size),
                        )
                    )
                if not detected and not profile_detector.empty():
                    detected = _detect_profile_faces(
                        cv2, profile_detector, gray, min_face_size
                    )
                faces = [
                    tuple(int(round(value / scale)) for value in face)
                    for face in detected
                ]
                face = _select_consistent_face(faces, previous_face)
                if face is None:
                    continue
                previous_face = face
                x, y, face_width, face_height = face
                samples.append(
                    {
                        "time": timestamp - start,
                        "x": float(x + face_width / 2),
                        "y": float(y + face_height / 2),
                        "face_width": float(face_width),
                        "face_height": float(face_height),
                    }
                )
        finally:
            capture.release()

        # Sparse accidental detections should never push a crop away from center.
        if len(samples) < 2 or len(samples) / max(1, len(sample_times)) < 0.12:
            return {"width": width, "height": height, "samples": []}
        return {"width": width, "height": height, "samples": samples}
    except Exception:
        # Vision is optional at render time: a failed detector means a center crop.
        return {}


def _detect_profile_faces(cv2: Any, detector: Any, gray: Any, min_face_size: int) -> list[Any]:
    """Try both profile orientations after frontal detection misses a sample."""
    options = {
        "scaleFactor": 1.1,
        "minNeighbors": 4,
        "minSize": (min_face_size, min_face_size),
    }
    faces = list(detector.detectMultiScale(gray, **options))
    flipped_width = gray.shape[1]
    flipped = detector.detectMultiScale(cv2.flip(gray, 1), **options)
    faces.extend(
        (flipped_width - x - width, y, width, height)
        for x, y, width, height in flipped
    )
    return faces


def _select_consistent_face(
    faces: Any,
    previous: tuple[float, float, float, float] | None,
) -> tuple[int, int, int, int] | None:
    """Prefer the face near the previous detection to avoid jumping between people."""
    boxes = [
        tuple(int(value) for value in face)
        for face in faces
        if len(face) >= 4 and int(face[2]) > 0 and int(face[3]) > 0
    ]
    if not boxes:
        return None
    if previous is None:
        return max(boxes, key=lambda face: face[2] * face[3])

    previous_x, previous_y, previous_width, previous_height = previous
    previous_center_x = previous_x + previous_width / 2
    previous_center_y = previous_y + previous_height / 2
    previous_size = math.sqrt(previous_width * previous_height)

    def association_score(face: tuple[int, int, int, int]) -> float:
        x, y, face_width, face_height = face
        center_x = x + face_width / 2
        center_y = y + face_height / 2
        size = math.sqrt(face_width * face_height)
        distance = math.hypot(center_x - previous_center_x, center_y - previous_center_y)
        scale_change = abs(math.log(size / max(previous_size, 1.0)))
        return distance / max(size, previous_size, 1.0) + 0.5 * scale_change

    nearest = min(boxes, key=association_score)
    if association_score(nearest) <= 4.0:
        return nearest
    return max(boxes, key=lambda face: face[2] * face[3])


def calculate_dynamic_crop(
    tracking_data: dict[str, Any], video_dimensions: tuple[int, int],
    output_dimensions: tuple[int, int] = (1080, 1920),
    duration: float = 0.0,
) -> dict[str, Any]:
    """Return crop geometry and a smooth x/y expression, or centered geometry on fallback."""
    width, height = video_dimensions
    out_width, out_height = output_dimensions
    aspect = out_width / out_height
    if width <= 0 or height <= 0:
        return {}
    if width / height > aspect:
        crop_height = height
        crop_width = min(width, int(round(height * aspect)))
    else:
        crop_width = width
        crop_height = min(height, int(round(width / aspect)))
    max_x, max_y = width - crop_width, height - crop_height
    center_x, center_y = max_x / 2, max_y / 2
    samples = tracking_data.get("samples", []) if tracking_data else []
    points: list[tuple[float, float, float]] = []
    if samples and len(samples) >= 2:
        for sample in samples:
            # Leave breathing room around the face; expanded boxes don't alter crop size,
            # they bias the center so the face remains away from the crop edge.
            pad_x = min(crop_width * 0.12, sample.get("face_width", 0) * 0.35)
            pad_y = min(crop_height * 0.12, sample.get("face_height", 0) * 0.55)
            subject_x = sample["x"]
            subject_y = sample["y"] - pad_y * 0.15
            x = min(max_x, max(0.0, subject_x - crop_width / 2)) if max_x else 0.0
            y = min(max_y, max(0.0, subject_y - crop_height / 2)) if max_y else 0.0
            points.append((sample["time"], x, y))
        points = _smooth(points)
    return {
        "width": crop_width,
        "height": crop_height,
        "x": _position_expression(points, 1, center_x, duration, max_x),
        "y": _position_expression(points, 2, center_y, duration, max_y),
        "tracked": bool(points),
    }


def _sample_times(start: float, end: float) -> list[float]:
    duration = end - start
    # Around one sample per second keeps CPU usage low while following broad movement.
    count = max(2, min(180, int(math.ceil(duration)) + 1))
    if count == 2:
        return [start, end - 0.01]
    return [start + duration * index / (count - 1) for index in range(count)]


def _smooth(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    result = []
    for index, (timestamp, _, _) in enumerate(points):
        neighborhood = points[max(0, index - 2): index + 3]
        result.append(
            (
                timestamp,
                sum(point[1] for point in neighborhood) / len(neighborhood),
                sum(point[2] for point in neighborhood) / len(neighborhood),
            )
        )
    return result


def _position_expression(
    points: list[tuple[float, float, float]], axis: int, center: float,
    duration: float, maximum: float,
) -> str:
    if not points or maximum <= 0:
        return f"{center:.2f}"
    values = [(point[0], min(maximum, max(0.0, point[axis]))) for point in points]
    if all(abs(value - values[0][1]) < 0.5 for _, value in values):
        return f"{values[0][1]:.2f}"
    expression = f"{values[-1][1]:.2f}"
    for index in range(len(values) - 2, -1, -1):
        t0, v0 = values[index]
        t1, v1 = values[index + 1]
        span = max(0.001, t1 - t0)
        linear = f"({v0:.2f}+({v1-v0:.2f})*(t-{t0:.3f})/{span:.3f})"
        expression = f"if(lt(t\\,{t1:.3f})\\,{linear}\\,{expression})"
    first_time, first_value = values[0]
    if first_time > 0:
        expression = f"if(lt(t\\,{first_time:.3f})\\,{first_value:.2f}\\,{expression})"
    return expression
