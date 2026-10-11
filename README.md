# AI Clipper

Run AI Clipper on your own computer. Paste a YouTube URL in the local web app to generate and edit three vertical clips with captions.

## How it works

```text
Browser → Next.js web app (localhost:3000) → FastAPI (localhost:8000)
                                                    ↓
                                             SQLite job queue
                                                    ↓
                                         Local background worker
                                    yt-dlp · Whisper · FFmpeg
                                                    ↓
                                      Clips saved on your computer

                         Worker uses OpenRouter for clip suggestions
```

The app and video processing run locally, and Whisper can use an NVIDIA GPU. YouTube downloads and OpenRouter clip suggestions require an internet connection, so processing is local but not fully offline.

## Requirements

- Docker with Docker Compose
- An [OpenRouter API key](https://openrouter.ai/)
- For GPU mode: an NVIDIA GPU, its driver, and NVIDIA Container Toolkit configured for Docker

The included GPU setup uses CUDA with Whisper. Other setups can use CPU mode.

## Start the app

From the project directory, create the environment file:

```bash
cp .env.example .env
```

Open `.env` and set `OPENROUTER_API_KEY`. `WHISPER_DEVICE=auto` uses CUDA when Docker can see the GPU, otherwise it falls back to CPU.

Start with NVIDIA GPU support:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

Open [http://localhost:3000](http://localhost:3000) in your browser. To launch it from another terminal:

```bash
# Linux
xdg-open http://localhost:3000

# macOS
open http://localhost:3000
```

On Windows PowerShell, run `Start-Process http://localhost:3000`.

To run without an NVIDIA GPU, use:

```bash
docker compose up --build -d
```

The first build downloads the application dependencies; the first run also downloads the Whisper model. To view logs, run `docker compose logs -f`. To stop the app, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down
```

Job records and generated files are stored in the local `data/`, `temp/`, and `output/` directories.
