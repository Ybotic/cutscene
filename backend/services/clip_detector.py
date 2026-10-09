import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.settings import settings
from backend.services.video_context import sample_candidate_frames


logger = logging.getLogger(__name__)


class ClipDetectionError(RuntimeError):
    pass


@dataclass
class CandidateClip:
    start: float
    end: float
    title: str
    reason: str
    score: int


def _transcript_for_prompt(transcript: dict[str, Any]) -> str:
    return "\n".join(
        f"[{segment['start']:.2f}-{segment['end']:.2f}] {segment['text']}"
        for segment in transcript["segments"]
    )


def find_best_clips(
    transcript: dict[str, Any], source_path: Path | None = None
) -> list[CandidateClip]:
    if not settings.openrouter_api_key:
        raise ClipDetectionError("OPENROUTER_API_KEY is not configured.")

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "AI Clipper",
            },
        )
        response = client.chat.completions.create(
            model=settings.openrouter_model,
            temperature=0.3,
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": True}},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You select high-potential short-form video moments. "
                        "Return only valid JSON with a clips array. Find exactly 5 "
                        "non-overlapping candidates when possible. Each should be "
                        "20 to 60 seconds, include enough setup and payoff, and use "
                        "timestamps from the transcript. Rank score from 0 to 100."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Choose moments with hooks, surprising statements, jokes, "
                        "emotion, useful insights, conflict, stories, reactions, "
                        "or satisfying answers. Avoid contextless fragments. You may "
                        "start a few seconds before the key line.\n\n"
                        "Required shape: {\"clips\":[{\"start\": number, "
                        "\"end\": number, \"title\": string, \"reason\": string, "
                        "\"score\": number}]}\n\n"
                        f"Transcript:\n{_transcript_for_prompt(transcript)}"
                    ),
                },
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except ClipDetectionError:
        raise
    except Exception as exc:
        raise ClipDetectionError(f"The AI clip analysis failed: {exc}") from exc

    max_time = max(float(segment["end"]) for segment in transcript["segments"])
    candidates = []
    for item in payload.get("clips", []):
        try:
            start = max(0.0, float(item["start"]))
            end = min(max_time, float(item["end"]))
            if end <= start or end - start < 10 or end - start > 75:
                continue
            candidates.append(
                CandidateClip(
                    start=start,
                    end=end,
                    title=str(item.get("title", "Untitled moment"))[:120],
                    reason=str(item.get("reason", "Strong short-form moment."))[:300],
                    score=max(0, min(100, int(item.get("score", 0)))),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    candidates.sort(key=lambda clip: clip.score, reverse=True)
    selected = []
    for candidate in candidates:
        if any(
            candidate.start < chosen.end and candidate.end > chosen.start
            for chosen in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) == 5:
            break

    if len(selected) < 3:
        raise ClipDetectionError(
            "The AI returned fewer than 3 usable moments. Try a video with more spoken content."
        )
    if source_path is not None:
        _rerank_visually(client, selected, source_path)
    return selected


def _rerank_visually(client: Any, candidates: list[CandidateClip], source_path: Path) -> None:
    samples = sample_candidate_frames(str(source_path), candidates)
    if not samples:
        return

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Rank these candidate clips for short-form visual quality. Prefer a clear, "
                "relevant subject, expressive action, scene variety, and visuals that support "
                "the transcript. Penalize black frames, static slides, and visuals unrelated "
                "to the spoken moment. Candidate frame samples are in time order; a marked "
                "scene change means consecutive samples differ visually. Return JSON with "
                "a candidates array containing id, visual_score (0-100), and visual_reason."
            ),
        }
    ]
    for item in samples:
        clip = candidates[item["candidate_id"] - 1]
        content.append(
            {
                "type": "text",
                "text": (
                    f"Candidate {item['candidate_id']}: {clip.start:.1f}-{clip.end:.1f}s; "
                    f"title={clip.title!r}; transcript assessment={clip.reason!r}"
                ),
            }
        )
        for frame in item["frames"]:
            change = "scene change" if frame["scene_change"] else "same scene"
            content.extend(
                [
                    {"type": "text", "text": f"Frame at {frame['time']:.1f}s ({change})"},
                    {
                        "type": "image_url",
                        "image_url": {"url": frame["data_url"]},
                    },
                ]
            )

    try:
        response = client.chat.completions.create(
            model=settings.openrouter_model,
            temperature=0.2,
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": True}},
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        by_id = {
            int(item["id"]): item
            for item in payload.get("candidates", [])
            if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        }
        for candidate_id, clip in enumerate(candidates, start=1):
            item = by_id.get(candidate_id)
            if not item:
                continue
            visual_score = max(0, min(100, int(item.get("visual_score", clip.score))))
            clip.score = round(clip.score * 0.7 + visual_score * 0.3)
            visual_reason = str(item.get("visual_reason", "")).strip()
            if visual_reason:
                clip.reason = f"{clip.reason} Visual: {visual_reason}"[:300]
        candidates.sort(key=lambda clip: clip.score, reverse=True)
    except Exception as exc:
        # Visual review is opportunistic; transcript-based candidates remain usable.
        logger.warning("Visual clip ranking failed; keeping transcript ranking: %s", exc)
