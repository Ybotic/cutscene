"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

type Clip = {
  id: number;
  title: string;
  reason: string;
  score: number;
  start: number;
  end: number;
  url: string;
};

type Candidate = {
  id: number;
  title: string;
  reason: string;
  score: number;
  start: number;
  end: number;
  caption_text: string;
};

type CandidateEdit = Pick<Candidate, "title" | "start" | "end" | "caption_text">;

type Job = {
  job_id: string;
  requested_clip_count?: number;
  status: string;
  message: string;
  clips: Clip[];
  candidates?: Candidate[];
  timings?: Record<string, number>;
  progress?: number;
  error?: string | null;
};

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const stages = [
  ["downloading", "Download source"],
  ["transcribing", "Transcribe audio"],
  ["finding_moments", "Find best moments"],
  ["review", "Review moments"],
  ["render_queued", "Queue render"],
  ["aligning", "Align captions"],
  ["rendering", "Render clips"],
];

function formatTime(seconds: number) {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0")}`;
}

function playCompletionSound(audioContext: AudioContext | null) {
  if (!audioContext || audioContext.state !== "running") return;

  const now = audioContext.currentTime;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.type = "sine";
  oscillator.frequency.setValueAtTime(660, now);
  oscillator.frequency.setValueAtTime(880, now + 0.12);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.07, now + 0.025);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.38);
  oscillator.connect(gain);
  gain.connect(audioContext.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.4);
}

function CandidatePreview({ src, start, end }: { src: string; start: number; end: number }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (loaded && videoRef.current) videoRef.current.currentTime = start;
  }, [loaded, start]);
  return (
    <video
      ref={videoRef}
      controls
      playsInline
      preload="metadata"
      className="aspect-video w-full bg-ink object-contain"
      src={src}
      onLoadedMetadata={() => {
        setLoaded(true);
        if (videoRef.current) videoRef.current.currentTime = start;
      }}
      onTimeUpdate={() => {
        if (videoRef.current && videoRef.current.currentTime >= end) {
          videoRef.current.pause();
        }
      }}
    />
  );
}

function TimingDetails({ timings }: { timings?: Record<string, number> }) {
  if (!timings || Object.keys(timings).length === 0) return null;
  return (
    <details className="mt-4 font-body text-[10px] text-ink/45">
      <summary className="cursor-pointer uppercase tracking-[0.12em]">Processing timings</summary>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {Object.entries(timings).map(([name, seconds]) => (
          <li key={name}>{name.replaceAll("_", " ")}: {seconds.toFixed(1)}s</li>
        ))}
      </ul>
    </details>
  );
}

export default function Home() {
  const [url, setUrl] = useState("");
  const [clipCount, setClipCount] = useState(3);
  const [attentionGameplay, setAttentionGameplay] = useState("none");
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [completionSoundEnabled, setCompletionSoundEnabled] = useState(true);
  const [emailNotificationsAvailable, setEmailNotificationsAvailable] = useState(false);
  const [notificationEmail, setNotificationEmail] = useState("");
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<number[]>([]);
  const [candidateEdits, setCandidateEdits] = useState<Record<number, CandidateEdit>>({});
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const audioContextRef = useRef<AudioContext | null>(null);
  const notifiedJobIdRef = useRef<string | null>(null);

  useEffect(() => {
    fetch(`${apiUrl}/api/config`)
      .then((response) => (response.ok ? response.json() : null))
      .then((config) => setEmailNotificationsAvailable(Boolean(config?.email_notifications_available)))
      .catch(() => setEmailNotificationsAvailable(false));
  }, []);

  useEffect(() => {
    if (job?.status !== "finished" || notifiedJobIdRef.current === job.job_id) return;
    notifiedJobIdRef.current = job.job_id;
    if (completionSoundEnabled) playCompletionSound(audioContextRef.current);
  }, [job, completionSoundEnabled]);

  useEffect(() => {
    if (job?.status !== "review" || !job.candidates) return;
    setSelectedCandidateIds(job.candidates.slice(0, 3).map((candidate) => candidate.id));
    setCandidateEdits(
      Object.fromEntries(
        job.candidates.map((candidate) => [candidate.id, {
          title: candidate.title,
          start: candidate.start,
          end: candidate.end,
          caption_text: candidate.caption_text,
        }]),
      ),
    );
  }, [job?.job_id, job?.status]);

  useEffect(() => {
    if (!job || ["finished", "failed", "review", "cancelled"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${apiUrl}/api/status/${job.job_id}`);
        if (!response.ok) throw new Error("Could not read processing status.");
        setJob(await response.json());
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "Status request failed.");
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job]);

  const activeStage = useMemo(() => stages.findIndex(([id]) => id === job?.status), [job?.status]);

  function unlockCompletionSound() {
    if (typeof window === "undefined" || !window.AudioContext) return;
    audioContextRef.current ??= new window.AudioContext();
    void audioContextRef.current.resume().catch(() => undefined);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setJob(null);
    setSubmitting(true);
    if (completionSoundEnabled) unlockCompletionSound();
    try {
      const response = await fetch(`${apiUrl}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          youtube_url: url.trim(),
          clip_count: clipCount,
          attention_gameplay: attentionGameplay,
          notification_email: emailNotificationsAvailable ? notificationEmail.trim() || null : null,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not start this job.");
      setJob({ job_id: data.job_id, status: "queued", message: "Queued", clips: [] });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not start this job.");
    } finally {
      setSubmitting(false);
    }
  }

  function toggleCandidate(candidateId: number) {
    setSelectedCandidateIds((selected) =>
      selected.includes(candidateId)
        ? selected.filter((id) => id !== candidateId)
        : selected.length < 3
          ? [...selected, candidateId]
          : selected,
    );
  }

  function updateCandidate(candidateId: number, patch: Partial<CandidateEdit>) {
    setCandidateEdits((edits) => ({
      ...edits,
      [candidateId]: { ...edits[candidateId], ...patch },
    }));
  }

  async function submitReview() {
    if (!job || selectedCandidateIds.length !== 3) return;
    setReviewSubmitting(true);
    setError("");
    try {
      const response = await fetch(`${apiUrl}/api/jobs/${job.job_id}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clips: selectedCandidateIds.map((candidateId) => ({
            candidate_id: candidateId,
            ...candidateEdits[candidateId],
          })),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not queue the reviewed clips.");
      setJob({ ...job, status: "render_queued", message: "Your reviewed clips are queued for rendering." });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not queue the reviewed clips.");
    } finally {
      setReviewSubmitting(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    try {
      const response = await fetch(`${apiUrl}/api/jobs/${job.job_id}/cancel`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not cancel this job.");
      setJob({ ...job, status: data.status, message: data.status === "cancelled" ? "Processing cancelled" : "Cancellation requested" });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not cancel this job.");
    }
  }

  return (
    <main className="grain min-h-screen overflow-hidden">
      <div className="mx-auto max-w-6xl px-5 py-6 sm:px-8 sm:py-10">
        <nav className="flex items-center justify-between border-b border-ink/15 pb-5">
          <div className="flex items-center gap-3 font-display text-sm font-bold tracking-tight">
            <span className="grid h-8 w-8 place-items-center bg-ink text-paper">A</span>
            AI CLIPPER
          </div>
          <span className="font-body text-[10px] uppercase tracking-[0.22em] text-ink/50">MVP / 001</span>
        </nav>

        <section className="grid gap-12 pb-20 pt-16 lg:grid-cols-[1fr_400px] lg:items-end lg:pt-24">
          <div>
            <p className="mb-6 font-body text-xs uppercase tracking-[0.28em] text-coral">Long form in. Short form out.</p>
            <h1 className="max-w-3xl font-display text-6xl font-bold leading-[0.91] tracking-[-0.07em] sm:text-8xl">
              Find the <span className="text-coral">moment.</span>
            </h1>
            <p className="mt-8 max-w-xl font-body text-sm leading-7 text-ink/65 sm:text-base">
              Turn long videos into ready-to-post Shorts and Reels. AI finds the story, frames it vertically, and captions every word.
            </p>
          </div>

          <form onSubmit={submit} className="relative bg-ink p-5 text-paper shadow-card sm:p-7">
            <div className="absolute right-0 top-0 h-3 w-3 bg-lime" />
            <label htmlFor="youtube-url" className="font-body text-[10px] uppercase tracking-[0.2em] text-paper/55">Source video</label>
            <input
              id="youtube-url"
              type="url"
              required
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="Paste a YouTube URL"
              className="mt-4 w-full border-b border-paper/30 bg-transparent py-3 font-body text-sm outline-none placeholder:text-paper/35 focus:border-lime"
            />
            <label htmlFor="clip-count" className="mt-6 block font-body text-[10px] uppercase tracking-[0.2em] text-paper/55">Number of clips (1–5)</label>
            <select
              id="clip-count"
              value={clipCount}
              onChange={(event) => setClipCount(Number(event.target.value))}
              className="mt-3 w-full border-b border-paper/30 bg-ink py-3 font-body text-sm text-paper outline-none focus:border-lime"
            >
              {[1, 2, 3, 4, 5].map((count) => (
                <option key={count} value={count}>{count} {count === 1 ? "clip" : "clips"}</option>
              ))}
            </select>
            <label htmlFor="attention-gameplay" className="mt-6 block font-body text-[10px] uppercase tracking-[0.2em] text-paper/55">Attention Gameplay</label>
            <select
              id="attention-gameplay"
              value={attentionGameplay}
              onChange={(event) => setAttentionGameplay(event.target.value)}
              className="mt-3 w-full border-b border-paper/30 bg-ink py-3 font-body text-sm text-paper outline-none focus:border-lime"
            >
              <option value="none">None</option>
              <option value="subway_surfer">Subway Surfers</option>
              <option value="minecraft_parkour">Minecraft Parkour</option>
            </select>
            {emailNotificationsAvailable && (
              <label htmlFor="notification-email" className="mt-5 block font-body text-[10px] uppercase tracking-[0.2em] text-paper/55">
                Email when finished (optional)
                <input
                  id="notification-email"
                  type="email"
                  value={notificationEmail}
                  onChange={(event) => setNotificationEmail(event.target.value)}
                  placeholder="you@example.com"
                  className="mt-2 w-full border-b border-paper/30 bg-transparent py-3 font-body text-sm normal-case tracking-normal text-paper outline-none placeholder:text-paper/35 focus:border-lime"
                />
              </label>
            )}
            <label className="mt-5 flex cursor-pointer items-center gap-3 font-body text-xs text-paper/75">
              <input
                type="checkbox"
                checked={completionSoundEnabled}
                onChange={(event) => {
                  const enabled = event.target.checked;
                  setCompletionSoundEnabled(enabled);
                  if (enabled) unlockCompletionSound();
                }}
                className="h-4 w-4 accent-lime"
              />
              <span>Play a soft sound when clips are ready</span>
            </label>
            <p className="ml-7 mt-1 font-body text-[10px] text-paper/40">This only works while this page is open.</p>
            <button disabled={submitting} className="mt-7 flex w-full items-center justify-between bg-lime px-4 py-4 font-body text-xs font-bold uppercase tracking-[0.14em] text-ink transition hover:bg-white disabled:cursor-wait disabled:opacity-60">
              {submitting ? "Starting..." : "Generate clips"}
              <span className="text-lg leading-none">-&gt;</span>
            </button>
            <p className="mt-4 font-body text-[10px] leading-5 text-paper/40">Up to {clipCount} vertical MP4s / word-timed captions / AI selected</p>
          </form>
        </section>

        {error && <div className="mb-10 border-l-4 border-coral bg-coral/10 px-5 py-4 font-body text-xs text-ink">{error}</div>}

        {job && !["finished", "review"].includes(job.status) && (
          <section className="mb-20 border-y border-ink/15 py-8">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
              <div>
                <p className="font-body text-[10px] uppercase tracking-[0.2em] text-ink/45">Processing job</p>
                <h2 className="mt-2 font-display text-3xl font-bold tracking-[-0.04em]">{job.status === "failed" ? "Something went wrong" : job.message}</h2>
                {job.error && <p className="mt-2 max-w-2xl font-body text-xs leading-6 text-coral">{job.error}</p>}
              </div>
              {!['failed', 'cancelled'].includes(job.status) && <div className="loader h-3 w-3 bg-coral" />}
            </div>
            {job.status !== "failed" && job.status !== "cancelled" && (
              <>
                <div className="mt-6 h-1.5 overflow-hidden bg-ink/10">
                  <div className="h-full bg-coral transition-all" style={{ width: `${job.progress ?? 0}%` }} />
                </div>
                <div className="mt-8 grid gap-2 sm:grid-cols-4 lg:grid-cols-7">
                  {stages.map(([id, label], index) => (
                    <div key={id} className="flex items-center gap-2 font-body text-[10px] uppercase tracking-[0.08em]">
                      <span className={`h-2 w-2 shrink-0 ${index <= activeStage ? "bg-coral" : "bg-ink/15"}`} />
                      <span className={index <= activeStage ? "text-ink" : "text-ink/35"}>{label}</span>
                    </div>
                  ))}
                </div>
                <TimingDetails timings={job.timings} />
                <button type="button" onClick={cancelJob} className="mt-5 border-b border-ink/30 pb-1 font-body text-[10px] font-bold uppercase tracking-[0.12em] text-ink/55 hover:text-coral">
                  Cancel processing
                </button>
              </>
            )}
          </section>
        )}

        {job?.status === "review" && (
          <section className="mb-20 border-y border-ink/15 py-8">
            <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
              <div>
                <p className="font-body text-[10px] uppercase tracking-[0.2em] text-coral">Review before rendering</p>
                <h2 className="mt-2 font-display text-3xl font-bold tracking-[-0.04em]">Choose three moments.</h2>
                <p className="mt-2 font-body text-xs leading-5 text-ink/55">Preview each source section, adjust its timing and title, and correct the caption text.</p>
              </div>
              <span className="font-body text-xs text-ink/45">{selectedCandidateIds.length} / 3 selected</span>
            </div>
            <TimingDetails timings={job.timings} />
            <div className="grid gap-6 lg:grid-cols-2">
              {(job.candidates ?? []).map((candidate) => {
                const edit = candidateEdits[candidate.id] ?? candidate;
                const selected = selectedCandidateIds.includes(candidate.id);
                return (
                  <article key={candidate.id} className={`border p-4 ${selected ? "border-coral bg-white/50" : "border-ink/15"}`}>
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div>
                        <p className="font-body text-[10px] uppercase tracking-[0.14em] text-coral">Candidate {candidate.id} · {candidate.score}/100</p>
                        <p className="mt-1 font-body text-xs leading-5 text-ink/55">{candidate.reason}</p>
                      </div>
                      <label className="flex shrink-0 items-center gap-2 font-body text-[10px] font-bold uppercase tracking-[0.1em]">
                        <input type="checkbox" checked={selected} disabled={!selected && selectedCandidateIds.length >= 3} onChange={() => toggleCandidate(candidate.id)} className="h-4 w-4 accent-coral" />
                        Use
                      </label>
                    </div>
                    <CandidatePreview key={`${job.job_id}-${candidate.id}`} src={`${apiUrl}/api/source/${job.job_id}`} start={Number(edit.start)} end={Number(edit.end)} />
                    <div className="mt-4 grid grid-cols-2 gap-3">
                      <label className="font-body text-[10px] uppercase tracking-[0.12em] text-ink/50">
                        Start (seconds)
                        <input type="number" min="0" step="0.1" value={edit.start} onChange={(event) => updateCandidate(candidate.id, { start: Number(event.target.value) })} className="mt-1 w-full border-b border-ink/20 bg-transparent py-2 text-sm text-ink outline-none focus:border-coral" />
                      </label>
                      <label className="font-body text-[10px] uppercase tracking-[0.12em] text-ink/50">
                        End (seconds)
                        <input type="number" min="0" step="0.1" value={edit.end} onChange={(event) => updateCandidate(candidate.id, { end: Number(event.target.value) })} className="mt-1 w-full border-b border-ink/20 bg-transparent py-2 text-sm text-ink outline-none focus:border-coral" />
                      </label>
                    </div>
                    <label className="mt-4 block font-body text-[10px] uppercase tracking-[0.12em] text-ink/50">
                      Clip title
                      <input value={edit.title} maxLength={120} onChange={(event) => updateCandidate(candidate.id, { title: event.target.value })} className="mt-1 w-full border-b border-ink/20 bg-transparent py-2 text-sm text-ink outline-none focus:border-coral" />
                    </label>
                    <label className="mt-4 block font-body text-[10px] uppercase tracking-[0.12em] text-ink/50">
                      Caption text
                      <textarea rows={3} maxLength={3000} value={edit.caption_text} onChange={(event) => updateCandidate(candidate.id, { caption_text: event.target.value })} className="mt-1 w-full border border-ink/15 bg-transparent p-2 text-xs leading-5 text-ink outline-none focus:border-coral" />
                    </label>
                  </article>
                );
              })}
            </div>
            <div className="mt-7 flex flex-wrap items-center gap-4">
              <button type="button" disabled={selectedCandidateIds.length !== 3 || reviewSubmitting} onClick={submitReview} className="bg-ink px-5 py-3 font-body text-xs font-bold uppercase tracking-[0.12em] text-paper transition hover:bg-coral disabled:cursor-not-allowed disabled:opacity-40">
                {reviewSubmitting ? "Queueing..." : "Render selected clips →"}
              </button>
              <button type="button" onClick={cancelJob} className="font-body text-[10px] font-bold uppercase tracking-[0.12em] text-ink/50 hover:text-coral">Cancel job</button>
            </div>
          </section>
        )}

        {job?.status === "finished" && (
          <section className="pb-24">
            <div className="mb-8 flex items-end justify-between border-b border-ink/15 pb-5">
              <div>
                <p className="font-body text-[10px] uppercase tracking-[0.2em] text-coral">Your edit is ready</p>
                <h2 className="mt-2 font-display text-4xl font-bold tracking-[-0.05em]">Three moments worth posting.</h2>
              </div>
              <span className="hidden font-body text-xs text-ink/45 sm:block">1080 x 1920 / MP4</span>
            </div>
            <TimingDetails timings={job.timings} />
            <div className="grid gap-8 md:grid-cols-3">
              {job.clips.map((clip) => (
                <article key={clip.id} className="group">
                  <div className="clip-player relative overflow-hidden bg-ink shadow-card">
                    <video controls controlsList="nofullscreen" playsInline preload="metadata" className="aspect-[9/16] w-full object-contain" src={`${apiUrl}${clip.url}`} />
                    <span className="absolute left-3 top-3 bg-lime px-2 py-1 font-body text-[10px] font-bold text-ink">{clip.score}/100</span>
                    <button
                      type="button"
                      aria-label="View clip in 9:16 fullscreen"
                      onClick={async (event) => {
                        const player = event.currentTarget.closest<HTMLElement>(".clip-player");
                        if (!player) return;
                        if (document.fullscreenElement === player) {
                          await document.exitFullscreen();
                        } else {
                          await player.requestFullscreen();
                        }
                      }}
                      className="absolute right-3 top-3 bg-ink/80 px-2 py-1 font-body text-[10px] font-bold uppercase tracking-[0.1em] text-paper transition hover:bg-ink"
                    >
                      Fullscreen
                    </button>
                  </div>
                  <div className="pt-5">
                    <div className="flex items-start justify-between gap-4">
                      <h3 className="font-display text-xl font-bold leading-tight tracking-[-0.03em]">{clip.title}</h3>
                      <span className="shrink-0 font-body text-[10px] text-ink/45">{formatTime(clip.start)}</span>
                    </div>
                    <p className="mt-3 min-h-12 font-body text-xs leading-5 text-ink/55">{clip.reason}</p>
                    <a href={`${apiUrl}${clip.url}`} download={`clip_${clip.id}.mp4`} className="mt-5 inline-flex border-b-2 border-ink pb-1 font-body text-[10px] font-bold uppercase tracking-[0.14em] transition hover:border-coral hover:text-coral">Download MP4 -&gt;</a>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        <footer className="flex justify-between border-t border-ink/15 py-5 font-body text-[10px] uppercase tracking-[0.15em] text-ink/40">
          <span>AI-assisted editing</span>
          <span>Built for the scroll</span>
        </footer>
      </div>
    </main>
  );
}
