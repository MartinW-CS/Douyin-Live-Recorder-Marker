from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Iterable

from .events import LiveEvent, event_to_json_dict, parse_event_line
from .markers import Marker


def read_jsonl_events(path: str | Path) -> Iterable[LiveEvent]:
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            try:
                event = parse_event_line(line)
            except Exception as exc:
                raise ValueError(f"failed to parse event line {line_number}: {exc}") from exc
            if event is not None:
                yield event


def follow_jsonl_events(path: str | Path, poll_seconds: float = 1.0) -> Iterable[LiveEvent]:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as fh:
        while True:
            line = fh.readline()
            if not line:
                time.sleep(poll_seconds)
                continue
            event = parse_event_line(line)
            if event is not None:
                yield event


def append_event_jsonl(path: str | Path, event: LiveEvent) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event_to_json_dict(event), ensure_ascii=False) + "\n")


def write_markers_json(path: str | Path, markers: list[Marker]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "markers": [marker.to_dict() for marker in markers],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_markers_csv(path: str | Path, markers: list[Marker]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "type",
        "timestamp",
        "video_offset_seconds",
        "start_offset_seconds",
        "end_offset_seconds",
        "reason",
        "trigger",
        "score",
        "streamer",
        "user",
        "event_time",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for marker in markers:
            writer.writerow(marker.to_dict())
