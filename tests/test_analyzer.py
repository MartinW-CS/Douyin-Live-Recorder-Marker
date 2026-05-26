from datetime import datetime, timedelta, timezone
import unittest

from douyin_live_marker.analyzer import MarkerAnalyzer
from douyin_live_marker.config import MarkerConfig
from douyin_live_marker.events import LiveEvent


class AnalyzerTests(unittest.TestCase):
    def test_keyword_hit_creates_marker(self):
        started = datetime(2026, 5, 25, 20, 0, tzinfo=timezone.utc)
        analyzer = MarkerAnalyzer(
            MarkerConfig(keywords=["名场面"]),
            recording_started_at=started,
        )

        markers = analyzer.process(
            LiveEvent(
                type="danmaku",
                timestamp=started + timedelta(seconds=10),
                content="这段是名场面",
                user="alice",
            )
        )

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].type, "keyword_hit")
        self.assertEqual(markers[0].timestamp, "00:00:10")
        self.assertEqual(markers[0].start_offset_seconds, 0)
        self.assertEqual(markers[0].end_offset_seconds, 55)

    def test_danmaku_spike_uses_window_and_cooldown(self):
        started = datetime(2026, 5, 25, 20, 0, tzinfo=timezone.utc)
        analyzer = MarkerAnalyzer(
            MarkerConfig(
                danmaku_window_seconds=10,
                danmaku_threshold=3,
                danmaku_cooldown_seconds=10,
            ),
            recording_started_at=started,
        )

        all_markers = []
        for second in [1, 2, 3, 4]:
            all_markers.extend(
                analyzer.process(
                    LiveEvent(
                        type="danmaku",
                        timestamp=started + timedelta(seconds=second),
                        content=f"msg {second}",
                    )
                )
            )

        self.assertEqual([marker.type for marker in all_markers], ["danmaku_spike"])
        self.assertEqual(all_markers[0].trigger, "3")

    def test_large_gift_creates_marker(self):
        started = datetime(2026, 5, 25, 20, 0, tzinfo=timezone.utc)
        analyzer = MarkerAnalyzer(
            MarkerConfig(gift_value_threshold=1000),
            recording_started_at=started,
        )

        markers = analyzer.process(
            LiveEvent(
                type="gift",
                timestamp=started + timedelta(seconds=30),
                gift_name="big gift",
                gift_value=3000,
            )
        )

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].type, "gift_hit")
        self.assertEqual(markers[0].score, 3)
