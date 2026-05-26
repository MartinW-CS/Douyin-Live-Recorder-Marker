from datetime import timezone
import json
import unittest

from douyin_live_marker.collectors.dycast import normalize_dycast_message


class DycastCollectorTests(unittest.TestCase):
    def test_normalizes_chat_message(self):
        events = normalize_dycast_message(
            json.dumps(
                {
                    "method": "WebcastChatMessage",
                    "timestamp": "2026-05-25T20:00:10Z",
                    "user": {"name": "alice"},
                    "content": "名场面来了",
                },
                ensure_ascii=False,
            ),
            streamer="demo",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "danmaku")
        self.assertEqual(events[0].streamer, "demo")
        self.assertEqual(events[0].user, "alice")
        self.assertEqual(events[0].content, "名场面来了")
        self.assertEqual(events[0].timestamp.tzinfo, timezone.utc)

    def test_normalizes_gift_message_value(self):
        events = normalize_dycast_message(
            {
                "method": "WebcastGiftMessage",
                "timestamp": "2026-05-25T20:00:30Z",
                "user": {"name": "bob"},
                "gift": {"name": "嘉年华", "price": 3000, "count": 2, "repeatEnd": 0},
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "gift")
        self.assertEqual(events[0].gift_name, "嘉年华")
        self.assertEqual(events[0].gift_value, 6000)

    def test_skips_repeated_gift_by_default(self):
        events = normalize_dycast_message(
            {
                "method": "WebcastGiftMessage",
                "timestamp": "2026-05-25T20:00:30Z",
                "gift": {"name": "礼物", "price": 10, "count": 1, "repeatEnd": 1},
            }
        )

        self.assertEqual(events, [])
