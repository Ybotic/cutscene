# AI Clipper

AI Clipper turns a YouTube video into three ready-to-post vertical Shorts/Reels. It downloads a source capped at the configured resolution, finds speech and visual highlights, lets the user review and edit candidates, then renders 9:16 MP4s with word-timed captions.

## Architecture

```text
frontend/                 Next.js + TypeScript + Tailwind UI
backend/main.py           FastAPI API and job lifecycle
backend/job_store.py      Persistent SQLite job queue, records, and timings
backend/worker.py         Separate queue worker with bounded concurrency
backend/pipeline.py       Preparation, review, alignment, and render orchestration
backend/services/
  downloader.py            YouTube acquisition and URL validation
  transcription.py         Whisper transcript and selected-clip word alignment
  clip_detector.py         Structured OpenRouter text/visual clip selection
  video_context.py         Small sampled frames and scene-change hints
  captions.py              ASS caption generation
  tracking.py              Best-effort face tracking and smooth crop data
  video_editor.py          FFmpeg crop, gameplay composition, encode, and captions
assets/gameplay/           Optional local attention gameplay videos
temp/                      Per-job source/transcript scratch files
output/                    Completed job MP4s
data/                      Persistent SQLite job database
```

The API endpoints include:

- `POST /api/generate` with `{ "youtube_url": "...", "attention_gameplay": "none" }`
- `GET /api/status/{job_id}` for processing state, candidates, stage timings, and finished clip metadata
- `POST /api/jobs/{job_id}/render` with three reviewed clip edits
- `POST /api/jobs/{job_id}/cancel` to cancel an active or review job
- `GET /api/source/{job_id}` to preview the source while the job is waiting for review
- `GET /api/clips/{job_id}/clip_1.mp4` for a rendered file
- `GET /api/config` for frontend-safe optional feature configuration

Jobs are stored in SQLite under `data/jobs.sqlite3` and claimed by a separate bounded worker process. After a worker restart, interrupted preparation jobs restart from the download step and interrupted rendering jobs are re-queued. This is persistent single-host processing, not a distributed worker system.

## Prerequisites

- Python 3.11 (recommended; the included Dockerfile uses 3.11)
- Node.js 18.17 or newer and npm
- FFmpeg available on `PATH`, including the `subtitles` filter
- An OpenRouter API key
- A machine with enough disk space for downloaded videos and enough memory for Whisper

Install FFmpeg:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get update && sudo apt-get install ffmpeg
```

`openai-whisper` also relies on the FFmpeg executable to read video audio.

## Local Setup

From the project root:

```bash
cp .env.example .env
# Set OPENROUTER_API_KEY in .env

# Python 3.11 is recommended. uv can install it without system sudo access.
uv python install 3.11
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python --index-url https://download.pytorch.org/whl/cu128 torch
uv pip install --python .venv/bin/python setuptools==69.5.1 wheel==0.45.1
uv pip install --python .venv/bin/python --no-build-isolation -r backend/requirements.txt
source .venv/bin/activate

cd frontend
npm install
```

If FFmpeg is not installed system-wide, set `FFMPEG_BINARY` to its absolute path
in `.env`. The application also auto-detects `./.tools/bin/ffmpeg`.

Run the backend in one terminal:

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

Run the worker in a second terminal:

```bash
source .venv/bin/activate
python -m backend.worker
```

Run the frontend in a third terminal:

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), paste a YouTube URL, and select **Generate clips**.

Optional attention gameplay is selected in the generation form. To enable an option,
place a suitably licensed video at `assets/gameplay/subway_surfer.mp4` or
`assets/gameplay/minecraft_parkour.mp4`. Assets are never downloaded automatically.

The worker warms the configured Whisper model in the background at startup; the first run also downloads the model if needed. `WHISPER_MODEL=base` is a reasonable local MVP default; `tiny` is faster on CPU with lower accuracy, while `turbo` can be a good speed/quality option on a compatible GPU. The full source is transcribed without word alignment first; detailed word timings are computed only for the three clips selected for rendering.

## Docker

Docker packages FFmpeg and runs the API and persistent queue worker separately. Create `.env` first, set `OPENROUTER_API_KEY`, then run the CPU-compatible setup:

```bash
docker compose up --build
```

For an NVIDIA GPU worker, use the GPU Compose override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

The frontend is at `http://localhost:3000` and the API is at `http://localhost:8000`. `NEXT_PUBLIC_API_URL` is embedded into the frontend during its Docker build; for a hosted deployment, set it to the publicly reachable HTTPS API origin and rebuild the frontend image. The API and worker share bind-mounted `temp/`, `output/`, and `data/` directories so job records and generated files persist across container restarts. Whisper and PyTorch can make the backend image large and may require additional memory.

## Processing Pipeline

1. The API validates the URL and persists a job in SQLite; the separate worker claims it from the persistent queue.
2. `yt-dlp` checks duration and size metadata before downloading, then selects a source at or below `MAX_DOWNLOAD_HEIGHT` (1080p by default).
3. Whisper transcribes the full audio without word-level alignment, avoiding alignment work for sections that will not be used.
4. OpenRouter receives the transcript and returns up to five structured candidates. OpenCV samples three small frames per candidate; the vision-capable model uses those frames and scene-change hints to rerank candidates. If visual ranking fails, transcript-ranked candidates remain available.
5. The user previews the source around each candidate, chooses three, adjusts start/end/title, and edits caption text.
6. Whisper generates word timestamps only for the selected ranges. OpenCV tracks faces using downscaled frames and temporal association; crop movement is smoothed, with a centered fallback when tracking is uncertain. Active-speaker identification is not implemented.
7. FFmpeg renders the selected clips. Rendering is sequential by default; `RENDER_WORKERS` can be raised to benchmark bounded parallel rendering on the deployment hardware.
8. When selected, a local gameplay video is looped silently in the lower 35% while source video and its audio remain intact in the upper 65%.
9. The caption service maps timed words into short ASS events. Job status returns progress, stage timings, clip metadata, and download URLs.

The transcript and sampled candidate frames are sent to OpenRouter for clip selection; the full source video is not sent to OpenRouter. The browser completion sound is available by default. An email field appears only when SMTP delivery is configured, and its address is retained with the job until normal retention cleanup.

## Environment Variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | Required for clip selection | none |
| `OPENROUTER_MODEL` | OpenRouter model for clip selection | `openai/gpt-6-luna` |
| `WHISPER_MODEL` | Whisper model name | `base` |
| `WHISPER_DEVICE` | Whisper device: `auto`, `cuda`, or `cpu` | `auto` |
| `MAX_VIDEO_SECONDS` | Download duration limit | `7200` |
| `MAX_DOWNLOAD_HEIGHT` | Maximum source video height | `1080` |
| `MAX_CONCURRENT_JOBS` | Worker-process concurrency; keep low on a single GPU | `1` |
| `MAX_QUEUED_JOBS` | Maximum nonterminal jobs, including jobs awaiting review | `8` |
| `MAX_JOB_RETRIES` | Retries for recognized transient errors | `1` |
| `JOB_RETENTION_DAYS` | Retention period for completed/failed job files | `7` |
| `RENDER_WORKERS` | Maximum simultaneous clip renders within one job | `1` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Optional SMTP delivery for completion/failure emails | disabled unless host and sender are set |
| `SMTP_STARTTLS` | Use STARTTLS for SMTP | `true` |
| `PUBLIC_API_ORIGIN` | Public backend origin used in emailed clip links | `http://localhost:8000` |
| `FRONTEND_ORIGIN` | Allowed browser origin | `http://localhost:3000` |
| `NEXT_PUBLIC_API_URL` | Public frontend API origin (embedded at build time) | `http://localhost:8000` |
| `FFMPEG_BINARY` | Optional FFmpeg executable path | auto-detected local binary or `ffmpeg` |

Email notifications stay hidden in the UI until `SMTP_HOST` and `SMTP_FROM` are configured. For hosted deployments, set `PUBLIC_API_ORIGIN` to the public HTTPS API origin so links in completion emails are usable.

## Known Limitations

- The SQLite database and worker queue are local to one backend host. Run one worker process and set `MAX_CONCURRENT_JOBS` for bounded parallel jobs; this is not a distributed queue or cloud storage. The API has no authentication or per-user job ownership.
- Completed outputs live on the backend's local persistent volume until retention cleanup removes them.
- Tracking uses frontal/profile Haar face detection and temporal association; it does not identify active speakers. Uncertain detections use a center crop.
- Caption emphasis is grouped word-timed text rather than per-word karaoke highlighting.
- Whisper and FFmpeg must be installed and available to the process/container.
- Some videos may be unavailable because of region, age, login, or YouTube download restrictions.
- OpenRouter model availability and pricing depend on the selected provider/model; visual ranking falls back to transcript ranking if the visual request fails.
- The evaluation schema and scripts are included, but the example annotations are illustrative. A representative human-rated video set still needs to be collected and labeled.

## Future Improvements

Active-speaker identification, alternate caption styles, hooks/B-roll, automatic zooms, background blur, additional aspect ratios, direct publishing, accounts, cloud storage/workers, analytics, and performance-based clip learning can be added behind the isolated services later.
