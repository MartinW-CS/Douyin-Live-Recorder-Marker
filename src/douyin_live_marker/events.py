from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
import json

EventType = Literal["danmaku", "gift"]


@dataclass(frozen=True)
class LiveEvent:
    type: EventType
    timestamp: datetime
    streamer: str | None = None
    user: str | None = None
    content: str | None = None
    gift_name: str | None = None
    gift_value: int = 0
    raw: dict[str, Any] | None = None


def parse_event_line(line: str) -> LiveEvent | None:
    text = line.strip()
    if not text:
        return None
    raw = json.loads(text)
    event_type = raw.get("type")
    if event_type not in {"danmaku", "gift"}:
        raise ValueError(f"unsupported event type: {event_type!r}")

    timestamp = parse_timestamp(raw.get("timestamp"))
    return LiveEvent(
        type=event_type,
        timestamp=timestamp,
        streamer=_optional_str(raw.get("streamer")),
        user=_optional_str(raw.get("user")),
        content=_optional_str(raw.get("content") or raw.get("text")),
        gift_name=_optional_str(raw.get("gift_name") or raw.get("gift")),
        gift_value=int(raw.get("gift_value") or raw.get("value") or 0),
        raw=raw,
    )


def parse_timestamp(value: Any) -> datetime:
    if value is None:
        raise ValueError("event timestamp is required")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str):
        raise ValueError("timestamp must be ISO string or unix seconds")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
