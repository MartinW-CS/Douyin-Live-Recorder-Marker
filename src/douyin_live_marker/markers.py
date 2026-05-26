from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Literal

MarkerType = Literal["danmaku_spike", "keyword_hit", "gift_hit"]


@dataclass(frozen=True)
class Marker:
    type: MarkerType
    timestamp: str
    video_offset_seconds: float
    start_offset_seconds: float
    end_offset_seconds: float
    reason: str
    trigger: str
    score: float
    streamer: str | None = None
    user: str | None = None
    event_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_marker(
    marker_type: MarkerType,
    event_time: datetime,
    recording_started_at: datetime,
    pre_buffer_seconds: int,
    post_buffer_seconds: int,
    reason: str,
    trigger: str,
    score: float,
    streamer: str | None = None,
    user: str | None = None,
) -> Marker:
    offset = max(0.0, (event_time - recording_started_at).total_seconds())
    start = max(0.0, offset - pre_buffer_seconds)
    end = offset + post_buffer_seconds
    return Marker(
        type=marker_type,
        timestamp=_format_seconds(offset),
        video_offset_seconds=round(offset, 3),
        start_offset_seconds=round(start, 3),
        end_offset_seconds=round(end, 3),
        reason=reason,
        trigger=trigger,
        score=round(score, 3),
        streamer=streamer,
        user=user,
        event_time=event_time.isoformat(),
    )


def _format_seconds(total_seconds: float) -> str:
    total = int(total_seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
