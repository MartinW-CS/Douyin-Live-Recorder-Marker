from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from .markers import Marker

VIDEO_SUFFIXES = {".flv", ".mp4", ".mkv", ".ts"}


def write_paired_marker_exports(recordings_dir: str | Path, markers: list[Marker]) -> list[Path]:
    video_path = latest_video_file(recordings_dir)
    if video_path is None:
        return []

    output_paths = [
        video_path.with_suffix(".markers.json"),
        video_path.with_suffix(".markers.csv"),
        video_path.with_suffix(".markers.fcpxml"),
        video_path.with_suffix(".premiere_markers.csv"),
    ]
    write_paired_json(output_paths[0], video_path, markers)
    write_paired_csv(output_paths[1], markers)
    write_paired_fcpxml(output_paths[2], video_path, markers)
    write_premiere_csv(output_paths[3], markers)
    return output_paths


def latest_video_file(recordings_dir: str | Path) -> Path | None:
    directory = Path(recordings_dir)
    if not directory.exists():
        return None
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES and path.stat().st_size > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def write_paired_json(path: Path, video_path: Path, markers: list[Marker]) -> None:
    payload = {
        "version": 1,
        "video_file": str(video_path),
        "markers": [marker.to_dict() for marker in markers],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_paired_csv(path: Path, markers: list[Marker]) -> None:
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
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for marker in markers:
            writer.writerow(marker.to_dict())


def write_premiere_csv(path: Path, markers: list[Marker], fps: int = 30) -> None:
    fieldnames = ["Name", "Description", "In", "Out", "Duration", "Marker Type"]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for marker in markers:
            writer.writerow(
                {
                    "Name": marker.reason,
                    "Description": marker.trigger,
                    "In": seconds_to_timecode(marker.start_offset_seconds, fps),
                    "Out": seconds_to_timecode(marker.end_offset_seconds, fps),
                    "Duration": seconds_to_timecode(
                        max(0.0, marker.end_offset_seconds - marker.start_offset_seconds),
                        fps,
                    ),
                    "Marker Type": "Comment",
                }
            )


def write_paired_fcpxml(path: Path, video_path: Path, markers: list[Marker]) -> None:
    duration = max([marker.end_offset_seconds for marker in markers] + [1.0])
    asset_duration = fcpx_time(duration + 1)
    video_url = "file://" + quote(str(video_path.resolve()))
    marker_xml = "\n".join(
        (
            f'            <marker start="{fcpx_time(marker.video_offset_seconds)}" '
            f'duration="1/30s" value="{escape(marker.reason, quote=True)}" '
            f'note="{escape(marker.trigger, quote=True)}"/>'
        )
        for marker in markers
    )
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<!DOCTYPE fcpxml>',
                '<fcpxml version="1.10">',
                "  <resources>",
                f'    <asset id="r1" name="{escape(video_path.name, quote=True)}" start="0s" duration="{asset_duration}" hasVideo="1">',
                f'      <media-rep kind="original-media" src="{video_url}"/>',
                "    </asset>",
                "  </resources>",
                "  <library>",
                '    <event name="Douyin Live Markers">',
                f'      <project name="{escape(video_path.stem, quote=True)}">',
                f'        <sequence duration="{asset_duration}">',
                "          <spine>",
                f'            <asset-clip name="{escape(video_path.stem, quote=True)}" ref="r1" offset="0s" start="0s" duration="{asset_duration}">',
                marker_xml,
                "            </asset-clip>",
                "          </spine>",
                "        </sequence>",
                "      </project>",
                "    </event>",
                "  </library>",
                "</fcpxml>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def seconds_to_timecode(seconds: float, fps: int = 30) -> str:
    total_frames = round(max(0.0, seconds) * fps)
    frames = total_frames % fps
    total_seconds = total_frames // fps
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def fcpx_time(seconds: float) -> str:
    millis = round(max(0.0, seconds) * 1000)
    if millis % 1000 == 0:
        return f"{millis // 1000}s"
    return f"{millis}/1000s"
