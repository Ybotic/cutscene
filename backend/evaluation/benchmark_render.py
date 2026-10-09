"""Compare serial and bounded-parallel FFmpeg clip rendering on a local source."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.services.video_editor import render_clip


def _parse_range(value: str) -> tuple[float, float]:
    try:
        start_text, end_text = value.split(":", maxsplit=1)
        start, end = float(start_text), float(end_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use START:END seconds, for example 10:40") from exc
    if start < 0 or end <= start:
        raise argparse.ArgumentTypeError("Each range must have a positive duration")
    return start, end


def _render_ranges(source: Path, ranges: list[tuple[float, float]], workers: int) -> float:
    with tempfile.TemporaryDirectory(prefix="clipper-render-benchmark-") as directory:
        output_dir = Path(directory)

        def render(index: int, clip_range: tuple[float, float]) -> None:
            start, end = clip_range
            render_clip(
                source,
                {"segments": []},
                start,
                end,
                output_dir / f"clip_{index}.mp4",
                output_dir / f"clip_{index}.ass",
            )

        started = time.perf_counter()
        if workers == 1:
            for index, clip_range in enumerate(ranges, start=1):
                render(index, clip_range)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(render, index, clip_range)
                    for index, clip_range in enumerate(ranges, start=1)
                ]
                for future in futures:
                    future.result()
        return time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Local source video used for the benchmark")
    parser.add_argument(
        "--range",
        dest="ranges",
        type=_parse_range,
        action="append",
        required=True,
        help="Clip range in seconds (repeat exactly three times)",
    )
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("Source video does not exist")
    if len(args.ranges) != 3:
        parser.error("Provide three --range values to match a normal render job")

    serial = _render_ranges(args.source, args.ranges, 1)
    parallel = _render_ranges(args.source, args.ranges, 2)
    print(
        json.dumps(
            {
                "serial_workers": 1,
                "serial_seconds": round(serial, 3),
                "parallel_workers": 2,
                "parallel_seconds": round(parallel, 3),
                "parallel_speedup": round(serial / parallel, 3) if parallel else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
