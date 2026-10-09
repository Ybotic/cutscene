# AI Clipper Improvement Plan

This plan tracks implementation of the product, speed, tracking, and reliability improvements discussed so far. Most application changes are implemented; hardware benchmarks and real human annotations still need representative videos and the target host.

## Done

- [x] Add a quiet completion sound, enabled by default, with a user-facing toggle. It plays once when processing finishes while the page is open.
- [x] Reduce high-resolution frames before face detection to lower tracking overhead.
- [x] Keep the crop focused on the same nearby face across samples rather than choosing the largest detected face independently each time.
- [x] Add tests for face selection continuity and keep existing crop tests passing.
- [x] Give optional gameplay 40% of the vertical composition and source video 60%.
- [x] Automatically detect Hindi and render its captions as Hinglish without requiring a user setting.

## Phase 1 — Measure and reduce processing time

- [x] Record elapsed time for download, transcription, clip selection, selected-range word alignment, tracking, and rendering. Timings persist with each job and are shown in the UI and worker logs.
- [ ] Benchmark Whisper configurations with `backend.evaluation.benchmark_whisper`; run on the target host and a representative source, optionally with corrected text to measure WER.
- [x] Add a preflight duration/size check and a configurable download height limit (1080p by default).
- [x] Use two-pass transcription: a coarse full-video transcript finds moments, then word-level timings are generated only for the selected clips.
- [ ] Run `backend.evaluation.benchmark_render` on the target host. `RENDER_WORKERS` is bounded/configurable and defaults to 1 until two-worker performance is measured.
- [x] Warm Whisper asynchronously in the worker process at startup.

## Phase 2 — Improve clip quality and give users control

- [x] Add a review step before final rendering. Users can preview candidates, choose three, adjust start/end times, edit titles, and correct captions.
- [x] Improve moment selection with sampled video frames and scene-change hints sent with the transcript to the vision-capable OpenRouter model.
- [x] Automatically detect Hindi and render captions as Roman-script Hinglish; leave non-Hindi captions unchanged.
- [ ] Collect and label a small, consented human-rated video set. Evaluation schemas and scripts are in `backend/evaluation/`; the example annotations are illustrative only.

## Phase 3 — Improve tracking quality

- [ ] Evaluate tracking on labeled examples covering multiple speakers, profile views, small faces, movement, and no-visible-face footage.
- [x] Extend lightweight Haar tracking to profile views, associate detections between frames, downscale detector input, and retain centered-crop fallback.
- [ ] Add speaker/active-speaker identification so the crop can follow the person speaking rather than the most visually prominent face.
- [x] Smooth crop movement and keep crop coordinates bounded. Include tracking-center error in the offline evaluation tool.

## Phase 4 — Make processing resilient

- [x] Replace in-memory state with SQLite job records and a separate persistent queue worker. Interrupted preparation/render jobs are recovered after worker restart.
- [x] Bound worker and render concurrency; retry recognized transient failures and support cancellation during download/render and between stages.
- [x] Check source metadata and duration before downloading the full video.
- [x] Retain completed results for a configurable period and periodically clean expired source/output files and records.
- [x] Expose progress, stage timings, and failure messages in the UI and logs.

## Optional follow-up — Email notifications

- [x] Add optional SMTP completion/failure email. The form exposes email collection only when SMTP is configured; browser sound remains available without email setup.

## Suggested order

1. Run the Whisper and render benchmark tools on the actual backend host and tune model/concurrency settings.
2. Collect a small human-labeled corpus and use the evaluation report to tune selection, captions, and crops.
3. Evaluate active-speaker tracking once representative labeled footage is available.
4. Move from the single-host SQLite queue/local disk to managed storage and distributed workers if usage outgrows one backend host.
