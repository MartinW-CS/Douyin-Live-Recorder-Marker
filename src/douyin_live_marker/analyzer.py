from __future__ import annotations

from collections import deque
from datetime import datetime

from .config import MarkerConfig
from .events import LiveEvent
from .markers import Marker, make_marker


class MarkerAnalyzer:
    def __init__(self, config: MarkerConfig, recording_started_at: datetime):
        self.config = config
        self.recording_started_at = recording_started_at
        self._danmaku_times: deque[datetime] = deque()
        self._last_spike_at: datetime | None = None
        self._keywords = [keyword.lower() for keyword in config.keywords if keyword]

    def process(self, event: LiveEvent) -> list[Marker]:
        markers: list[Marker] = []
        if event.type == "danmaku":
            markers.extend(self._process_danmaku(event))
        elif event.type == "gift":
            markers.extend(self._process_gift(event))
        return markers

    def _process_danmaku(self, event: LiveEvent) -> list[Marker]:
        markers: list[Marker] = []
        content = event.content or ""
        content_lower = content.lower()

        for keyword in self._keywords:
            if keyword in content_lower:
                markers.append(
                    make_marker(
                        "keyword_hit",
                        event.timestamp,
                        self.recording_started_at,
                        self.config.pre_buffer_seconds,
                        self.config.post_buffer_seconds,
                        reason=f"keyword matched: {keyword}",
                        trigger=content,
                        score=1.0,
                        streamer=event.streamer,
                        user=event.user,
                    )
                )

        self._danmaku_times.append(event.timestamp)
        window_seconds = self.config.danmaku_window_seconds
        while self._danmaku_times:
            age = (event.timestamp - self._danmaku_times[0]).total_seconds()
            if age <= window_seconds:
                break
            self._danmaku_times.popleft()

        count = len(self._danmaku_times)
        if count >= self.config.danmaku_threshold and self._spike_ready(event.timestamp):
            self._last_spike_at = event.timestamp
            markers.append(
                make_marker(
                    "danmaku_spike",
                    event.timestamp,
                    self.recording_started_at,
                    self.config.pre_buffer_seconds,
                    self.config.post_buffer_seconds,
                    reason=f"{count} danmaku events in {window_seconds}s",
                    trigger=str(count),
                    score=count / self.config.danmaku_threshold,
                    streamer=event.streamer,
                    user=event.user,
                )
            )
        return markers

    def _process_gift(self, event: LiveEvent) -> list[Marker]:
        if event.gift_value < self.config.gift_value_threshold:
            return []
        trigger = event.gift_name or "gift"
        return [
            make_marker(
                "gift_hit",
                event.timestamp,
                self.recording_started_at,
                self.config.pre_buffer_seconds,
                self.config.post_buffer_seconds,
                reason=f"gift value {event.gift_value} >= {self.config.gift_value_threshold}",
                trigger=trigger,
                score=event.gift_value / max(1, self.config.gift_value_threshold),
                streamer=event.streamer,
                user=event.user,
            )
        ]

    def _spike_ready(self, now: datetime) -> bool:
        if self._last_spike_at is None:
            return True
        elapsed = (now - self._last_spike_at).total_seconds()
        return elapsed >= self.config.danmaku_cooldown_seconds
