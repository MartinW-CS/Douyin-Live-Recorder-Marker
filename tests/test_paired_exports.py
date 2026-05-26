from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from douyin_live_marker.markers import Marker
from douyin_live_marker.paired_exports import (
    fcpx_time,
    latest_video_file,
    seconds_to_timecode,
    write_paired_marker_exports,
)


class PairedExportTests(unittest.TestCase):
    def test_latest_video_file_ignores_empty_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "empty.flv").write_bytes(b"")
            video = directory / "live.flv"
            video.write_bytes(b"video")

            self.assertEqual(latest_video_file(directory), video)

    def test_write_paired_marker_exports_uses_video_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            video = directory / "主播-2026-05-26.flv"
            video.write_bytes(b"video")
            marker = Marker(
                type="keyword_hit",
                timestamp="00:00:10",
                video_offset_seconds=10,
                start_offset_seconds=0,
                end_offset_seconds=55,
                reason="keyword hit: 高能",
                trigger="高能",
                score=1,
                streamer="主播",
                user="user",
                event_time=datetime.now(timezone.utc).isoformat(),
            )

            outputs = write_paired_marker_exports(directory, [marker])

            self.assertEqual(
                {path.name for path in outputs},
                {
                    "主播-2026-05-26.markers.json",
                    "主播-2026-05-26.markers.csv",
                    "主播-2026-05-26.markers.fcpxml",
                    "主播-2026-05-26.premiere_markers.csv",
                },
            )
            self.assertIn(str(video), (directory / "主播-2026-05-26.markers.json").read_text(encoding="utf-8"))
            fcpxml_path = directory / "主播-2026-05-26.markers.fcpxml"
            self.assertIn("<marker", fcpxml_path.read_text(encoding="utf-8"))
            ET.parse(fcpxml_path)
            self.assertIn("00:00:55:00", (directory / "主播-2026-05-26.premiere_markers.csv").read_text(encoding="utf-8-sig"))

    def test_time_formats(self):
        self.assertEqual(seconds_to_timecode(65.5, fps=30), "00:01:05:15")
        self.assertEqual(fcpx_time(10), "10s")
        self.assertEqual(fcpx_time(10.25), "10250/1000s")
