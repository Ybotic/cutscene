# AI Clipper

Turn a YouTube video into three vertical clips with captions. The app uses a Next.js frontend, a FastAPI backend, a background worker, FFmpeg, Whisper, and OpenRouter.

## Architecture

```text
Browser → Next.js frontend (Vercel) → FastAPI API (VPS)
                                         ↓
                                  SQLite job queue
                                         ↓
                                  Background worker
                           yt-dlp · Whisper · OpenRouter · FFmpeg
                                         ↓
                         Persistent job files and rendered clips
```

The frontend submits jobs to the API. The worker processes them separately, and the API returns progress and serves the finished clips. The API, worker, SQLite database, and files live on one persistent server.

## Run locally

You need Docker with Docker Compose and an [OpenRouter API key](https://openrouter.ai/).

```bash
cp .env.example .env
```

Add your key as `OPENROUTER_API_KEY` in `.env`, then run:

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The API is available at [http://localhost:8000](http://localhost:8000).

## Deploy

The frontend can run on Vercel. The API and worker need an always-on server: they process video with FFmpeg and Whisper, which are not a good fit for Vercel serverless functions. A small Linux VPS with Docker and persistent disk is a straightforward option. CPU works; a GPU can speed up processing.

### 1. Deploy the backend and worker

On the VPS, clone the repo, create `.env` from `.env.example`, and set:

```env
OPENROUTER_API_KEY=your-key
FRONTEND_ORIGIN=https://your-app.vercel.app
PUBLIC_API_ORIGIN=https://api.example.com
```

Point `api.example.com` to the VPS and configure an HTTPS reverse proxy to the app on port `8000`. Then start the API and worker:

```bash
docker compose up -d --build backend worker
```

Keep the server's `data/`, `temp/`, and `output/` directories on persistent disk; they hold job records and video files.

### 2. Deploy the frontend on Vercel

Import the repository in Vercel, set **Root Directory** to `frontend`, and add this environment variable before deploying:

```env
NEXT_PUBLIC_API_URL=https://api.example.com
```

If you use a custom Vercel domain, update `FRONTEND_ORIGIN` in the backend's `.env` to match it, then restart the backend. `NEXT_PUBLIC_API_URL` is set at build time.

Check that `https://api.example.com/api/health` responds after deployment.

> This project currently has no user authentication and uses a single-server SQLite queue. Add access control before opening it to the public.
