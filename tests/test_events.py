from datetime import timezone
import unittest

from douyin_live_marker.events import parse_event_line, parse_timestamp


class EventTests(unittest.TestCase):
    def test_parse_jsonl_event_with_iso_timestamp(self):
        event = parse_event_line(
            '{"type":"danmaku","timestamp":"2026-05-25T20:00:10Z","content":"hello"}'
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.type, "danmaku")
        self.assertEqual(event.content, "hello")
        self.assertEqual(event.timestamp.tzinfo, timezone.utc)

    def test_parse_unix_timestamp(self):
        parsed = parse_timestamp(1)

        self.assertEqual(parsed.isoformat(), "1970-01-01T00:00:01+00:00")
