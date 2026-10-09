"""Benchmark local Whisper models on a source video and optional transcript."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


_WORKER = r"""
import json, sys, time
from pathlib import Path
from backend.services.transcription import transcribe
source, output = Path(sys.argv[1]), Path(sys.argv[2])
word_timestamps = sys.argv[3] == "true"
started = time.perf_counter()
transcript = transcribe(source, output, word_timestamps=word_timestamps)
text = " ".join(segment["text"] for segment in transcript["segments"])
print("BENCHMARK_RESULT=" + json.dumps({"seconds": time.perf_counter() - started, "text": text}))
"""


def _word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = reference.lower().split()
    hypothesis_words = hypothesis.lower().split()
    previous = list(range(len(hypothesis_words) + 1))
    for index, reference_word in enumerate(reference_words, start=1):
        current = [index]
        for column, hypothesis_word in enumerate(hypothesis_words, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (reference_word != hypothesis_word),
                )
            )
        previous = current
    return previous[-1] / max(1, len(reference_words))


def benchmark(
    source: Path,
    models: list[str],
    device: str,
    word_timestamps: bool,
    reference: str | None,
) -> list[dict[str, Any]]:
    results = []
    for model in models:
        environment = os.environ.copy()
        environment["WHISPER_MODEL"] = model
        environment["WHISPER_DEVICE"] = device
        with tempfile.TemporaryDirectory(prefix="clipper-whisper-benchmark-") as directory:
            transcript_path = Path(directory) / "transcript.json"
            process = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _WORKER,
                    str(source),
                    str(transcript_path),
                    str(word_timestamps).lower(),
                ],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            marker = next(
                (line for line in reversed(process.stdout.splitlines()) if line.startswith("BENCHMARK_RESULT=")),
                None,
            )
            if process.returncode != 0 or marker is None:
                results.append(
                    {
                        "model": model,
                        "error": (process.stderr or process.stdout)[-1000:],
                    }
                )
                continue
            result = json.loads(marker.removeprefix("BENCHMARK_RESULT="))
            entry = {"model": model, "seconds": round(result["seconds"], 3)}
            if reference is not None:
                entry["word_error_rate"] = round(
                    _word_error_rate(reference, result["text"]), 4
                )
            results.append(entry)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--model", dest="models", action="append", required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--reference", type=Path, help="Optional manually corrected transcript")
    parser.add_argument("--word-timestamps", action="store_true")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("Source video does not exist")
    reference = (
        args.reference.read_text(encoding="utf-8") if args.reference is not None else None
    )
    print(
        json.dumps(
            benchmark(args.source, args.models, args.device, args.word_timestamps, reference),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
