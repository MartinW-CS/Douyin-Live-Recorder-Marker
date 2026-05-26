from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import asyncio
import json

from douyin_live_marker.collectors.base import EventCollector
from douyin_live_marker.events import LiveEvent, parse_timestamp
from douyin_live_marker.io import append_event_jsonl

CHAT_METHODS = {
    "WebcastChatMessage",
    "WebcastEmojiChatMessage",
}
GIFT_METHODS = {
    "WebcastGiftMessage",
}


class DycastWebSocketServerCollector(EventCollector):
    def __init__(
        self,
        host: str,
        port: int,
        streamer: str | None = None,
        skip_gift_repeats: bool = True,
    ):
        self.host = host
        self.port = port
        self.streamer = streamer
        self.skip_gift_repeats = skip_gift_repeats
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue()

    async def collect(self) -> AsyncIterator[LiveEvent]:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "collect-dycast requires the 'websockets' package. "
                "Install the project with `pip install -e .`."
            ) from exc

        async def handler(websocket):
            async for message in websocket:
                for event in normalize_dycast_message(
                    message,
                    streamer=self.streamer,
                    skip_gift_repeats=self.skip_gift_repeats,
                ):
                    await self._queue.put(event)

        async with websockets.serve(handler, self.host, self.port):
            while True:
                yield await self._queue.get()


def normalize_dycast_message(
    message: str | bytes | dict[str, Any],
    streamer: str | None = None,
    skip_gift_repeats: bool = True,
) -> list[LiveEvent]:
    payload = _load_payload(message)
    items = payload if isinstance(payload, list) else [payload]
    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        event = _normalize_one(item, streamer, skip_gift_repeats)
        if event is not None:
            events.append(event)
    return events


async def collect_dycast_to_jsonl(
    host: str,
    port: int,
    output: str | Path,
    streamer: str | None = None,
    skip_gift_repeats: bool = True,
) -> None:
    collector = DycastWebSocketServerCollector(
        host=host,
        port=port,
        streamer=streamer,
        skip_gift_repeats=skip_gift_repeats,
    )
    async for event in collector.collect():
        append_event_jsonl(output, event)
        print(f"event {event.type} written to {output}", flush=True)


def _normalize_one(
    raw: dict[str, Any],
    streamer: str | None,
    skip_gift_repeats: bool,
) -> LiveEvent | None:
    method = _optional_str(raw.get("method") or raw.get("type"))
    timestamp = _extract_timestamp(raw)
    user = _extract_user_name(raw.get("user"))
    room = raw.get("room")
    room_streamer = _optional_str(room.get("nickname")) if isinstance(room, dict) else None
    event_streamer = streamer or room_streamer

    if method in CHAT_METHODS or (raw.get("content") and not raw.get("gift")):
        content = _optional_str(raw.get("content"))
        if not content:
            return None
        return LiveEvent(
            type="danmaku",
            timestamp=timestamp,
            streamer=event_streamer,
            user=user,
            content=content,
            raw=raw,
        )

    gift = raw.get("gift")
    if method in GIFT_METHODS or isinstance(gift, dict):
        if not isinstance(gift, dict):
            gift = {}
        repeat_end = _int_or_none(gift.get("repeatEnd") or gift.get("repeat_end"))
        if skip_gift_repeats and repeat_end not in {None, 0}:
            return None
        gift_name = _optional_str(gift.get("name") or raw.get("gift_name"))
        price = _int_or_none(gift.get("price") or gift.get("diamond_count")) or 0
        count = _int_or_none(gift.get("count") or gift.get("repeat_count") or gift.get("combo_count")) or 1
        return LiveEvent(
            type="gift",
            timestamp=timestamp,
            streamer=event_streamer,
            user=user,
            gift_name=gift_name,
            gift_value=price * count,
            raw=raw,
        )

    return None


def _load_payload(message: str | bytes | dict[str, Any]) -> Any:
    if isinstance(message, dict):
        return message
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    return json.loads(message)


def _extract_timestamp(raw: dict[str, Any]) -> datetime:
    for key in ("timestamp", "time", "createTime", "create_time"):
        value = raw.get(key)
        if value is not None:
            try:
                return parse_timestamp(value)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def _extract_user_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _optional_str(value.get("name") or value.get("nickname") or value.get("id"))
    return _optional_str(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
