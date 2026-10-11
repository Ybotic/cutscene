from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.constants import DEFAULT_CLIP_COUNT, MAX_CLIP_COUNT


Stage = Literal[
    "queued",
    "downloading",
    "transcribing",
    "finding_moments",
    "review",
    "render_queued",
    "aligning",
    "rendering",
    "finished",
    "failed",
    "cancelled",
]


class GenerateRequest(BaseModel):
    youtube_url: str = Field(min_length=1)
    clip_count: int = Field(default=DEFAULT_CLIP_COUNT, ge=1, le=MAX_CLIP_COUNT)
    attention_gameplay: Literal["none", "subway_surfer", "minecraft_parkour"] = "none"
    notification_email: str | None = Field(
        default=None,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


class ClipResult(BaseModel):
    id: int
    title: str
    reason: str
    score: int
    start: float
    end: float
    url: str


class ClipCandidate(BaseModel):
    id: int
    title: str
    reason: str
    score: int
    start: float
    end: float
    caption_text: str = ""


class ClipEdit(BaseModel):
    candidate_id: int
    title: str = Field(min_length=1, max_length=120)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    caption_text: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def end_must_follow_start(self):
        if self.end <= self.start:
            raise ValueError("Clip end must be after clip start.")
        if self.end - self.start < 10 or self.end - self.start > 75:
            raise ValueError("Clips must be between 10 and 75 seconds long.")
        return self


class ReviewRequest(BaseModel):
    clips: list[ClipEdit] = Field(min_length=1, max_length=MAX_CLIP_COUNT)


class JobStatus(BaseModel):
    job_id: str
    requested_clip_count: int = DEFAULT_CLIP_COUNT
    status: Stage
    message: str
    clips: list[ClipResult] = Field(default_factory=list)
    candidates: list[ClipCandidate] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    progress: int = 0
    error: str | None = None
