# Offline quality evaluation

Use a small, consented set of videos and annotate the moments and subject framing that a human editor would choose. Do not put video or transcript content in this repository; use opaque source IDs and keep any private media outside version control.

Copy `annotations.example.json`, replace the illustrative values with human annotations and actual system output, then run:

```bash
python -m backend.evaluation.metrics path/to/annotations.json
```

The report includes best temporal intersection-over-union and recall at 0.5 IoU for selected moments, correlation between model scores and human candidate ratings, mean caption-boundary timing error, and normalized subject-center error. Add several examples from different source types, including multi-person, profile-view, movement-heavy, and no-visible-face videos before treating the measurements as representative.

To compare sequential and two-worker rendering on representative ranges from a local source, run:

```bash
python -m backend.evaluation.benchmark_render /path/to/source.mp4 \
  --range 120:155 --range 480:520 --range 900:940
```

Run this on the actual deployment hardware. Set `RENDER_WORKERS=2` only if the parallel result is consistently faster and stays within its CPU/memory budget; the default remains one worker.

To compare Whisper models on a local source, run one model per subprocess so model memory is released between runs. A corrected transcript can be provided to report word error rate:

```bash
python -m backend.evaluation.benchmark_whisper /path/to/source.mp4 \
  --device cuda --model base --model turbo --reference /path/to/corrected-transcript.txt
```

Use `--device cpu` and include `--model tiny` when evaluating a CPU-only host. Add `--word-timestamps` to measure the detailed alignment pass separately.
