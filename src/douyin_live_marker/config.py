from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import shlex
import tomllib


@dataclass(frozen=True)
class StreamerConfig:
    name: str
    url: str


@dataclass(frozen=True)
class MarkerConfig:
    keywords: list[str] = field(default_factory=list)
    danmaku_window_seconds: int = 30
    danmaku_threshold: int = 80
    danmaku_cooldown_seconds: int = 30
    gift_value_threshold: int = 1000
    pre_buffer_seconds: int = 15
    post_buffer_seconds: int = 45
    output_json: str = "markers.json"
    output_csv: str = "markers.csv"


@dataclass(frozen=True)
class BiliupConfig:
    enabled: bool = True
    command: str = "biliup"
    config_path: str = "biliup.config.toml"
    output_dir: str = "recordings"


@dataclass(frozen=True)
class DycastConfig:
    enabled: bool = True
    command: list[str] = field(default_factory=list)
    cwd: str | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    events_output: str = "events.jsonl"
    streamer: str | None = None
    skip_gift_repeats: bool = True


@dataclass(frozen=True)
class AppConfig:
    streamers: list[StreamerConfig]
    marker: MarkerConfig = field(default_factory=MarkerConfig)
    biliup: BiliupConfig = field(default_factory=BiliupConfig)
    dycast: DycastConfig = field(default_factory=DycastConfig)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> AppConfig:
    streamers_raw = raw.get("streamers", [])
    if not isinstance(streamers_raw, list) or not streamers_raw:
        raise ValueError("config must contain at least one [[streamers]] entry")

    streamers = []
    for item in streamers_raw:
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            raise ValueError("each streamer must have non-empty name and url")
        streamers.append(StreamerConfig(name=name, url=url))

    marker_raw = raw.get("marker", {})
    marker = MarkerConfig(
        keywords=[str(value) for value in marker_raw.get("keywords", [])],
        danmaku_window_seconds=int(marker_raw.get("danmaku_window_seconds", 30)),
        danmaku_threshold=int(marker_raw.get("danmaku_threshold", 80)),
        danmaku_cooldown_seconds=int(marker_raw.get("danmaku_cooldown_seconds", 30)),
        gift_value_threshold=int(marker_raw.get("gift_value_threshold", 1000)),
        pre_buffer_seconds=int(marker_raw.get("pre_buffer_seconds", 15)),
        post_buffer_seconds=int(marker_raw.get("post_buffer_seconds", 45)),
        output_json=str(marker_raw.get("output_json", "markers.json")),
        output_csv=str(marker_raw.get("output_csv", "markers.csv")),
    )

    biliup_raw = raw.get("biliup", {})
    biliup = BiliupConfig(
        enabled=bool(biliup_raw.get("enabled", True)),
        command=str(biliup_raw.get("command", "biliup")),
        config_path=str(biliup_raw.get("config_path", "biliup.config.toml")),
        output_dir=str(biliup_raw.get("output_dir", "recordings")),
    )

    dycast_raw = raw.get("dycast", {})
    dycast = DycastConfig(
        enabled=bool(dycast_raw.get("enabled", True)),
        command=_parse_command(dycast_raw.get("command", [])),
        cwd=_optional_str(dycast_raw.get("cwd")),
        host=str(dycast_raw.get("host", "127.0.0.1")),
        port=int(dycast_raw.get("port", 8765)),
        events_output=str(dycast_raw.get("events_output", "events.jsonl")),
        streamer=_optional_str(dycast_raw.get("streamer")),
        skip_gift_repeats=bool(dycast_raw.get("skip_gift_repeats", True)),
    )

    validate_marker_config(marker)
    validate_dycast_config(dycast)
    return AppConfig(streamers=streamers, marker=marker, biliup=biliup, dycast=dycast)


def validate_marker_config(marker: MarkerConfig) -> None:
    if marker.danmaku_window_seconds <= 0:
        raise ValueError("danmaku_window_seconds must be positive")
    if marker.danmaku_threshold <= 0:
        raise ValueError("danmaku_threshold must be positive")
    if marker.danmaku_cooldown_seconds < 0:
        raise ValueError("danmaku_cooldown_seconds cannot be negative")
    if marker.gift_value_threshold < 0:
        raise ValueError("gift_value_threshold cannot be negative")
    if marker.pre_buffer_seconds < 0 or marker.post_buffer_seconds < 0:
        raise ValueError("marker buffers cannot be negative")


def validate_dycast_config(dycast: DycastConfig) -> None:
    if not dycast.host:
        raise ValueError("dycast host cannot be empty")
    if dycast.port <= 0 or dycast.port > 65535:
        raise ValueError("dycast port must be between 1 and 65535")
    if not dycast.events_output:
        raise ValueError("dycast events_output cannot be empty")


def _parse_command(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    raise ValueError("command must be a string or list of strings")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sample_config() -> str:
    return """# Douyin live recording marker config.
[[streamers]]
name = "example_streamer"
url = "https://live.douyin.com/000000000000"

[marker]
keywords = ["名场面", "来了", "抽奖"]
danmaku_window_seconds = 30
danmaku_threshold = 80
danmaku_cooldown_seconds = 30
gift_value_threshold = 1000
pre_buffer_seconds = 15
post_buffer_seconds = 45
output_json = "markers.json"
output_csv = "markers.csv"

[biliup]
enabled = true
command = "biliup"
config_path = "biliup.config.toml"
output_dir = "recordings"

[dycast]
enabled = true
# Fill this with the command that starts your local dycast checkout.
# Example: command = ["npm", "run", "dev"]
command = []
cwd = ""
host = "127.0.0.1"
port = 8765
events_output = "events.jsonl"
streamer = "example_streamer"
skip_gift_repeats = true
"""
