from pathlib import Path
import unittest

from douyin_live_marker.web import (
    UiState,
    build_runtime_config,
    extract_douyin_room,
    extract_web_rid,
    load_ui_settings,
    parse_keywords,
    parse_streamer_entries,
    render_index,
    sanitize_douyin_url,
    status_payload,
)
from douyin_live_marker.biliup_recorder import safe_filename


class WebTests(unittest.TestCase):
    def test_extract_room_from_live_url(self):
        self.assertEqual(
            extract_douyin_room("https://live.douyin.com/123456789?foo=bar"),
            "123456789",
        )

    def test_extract_room_from_plain_room_number(self):
        self.assertEqual(extract_douyin_room("123456789"), "123456789")

    def test_extract_plain_long_reflow_room_id_is_not_a_dycast_room(self):
        self.assertEqual(extract_douyin_room("1234567890123"), "1234567890123")

    def test_extract_web_rid_from_reflow_html(self):
        self.assertEqual(
            extract_web_rid(r'...\"webRid\":\"645268872452\",\"desensitizedNickname\"...'),
            "645268872452",
        )

    def test_runtime_config_uses_biliup_recorder_module(self):
        config = build_runtime_config("demo", "https://live.douyin.com/123456789", Path("/tmp/out"), Path("/tmp/dycast"))

        self.assertIn("douyin_live_marker.biliup_recorder", config.biliup.args)
        self.assertIn("/tmp/out/recordings", config.biliup.args)

    def test_runtime_config_uses_custom_keywords(self):
        config = build_runtime_config(
            "demo",
            "https://live.douyin.com/123456789",
            Path("/tmp/out"),
            Path("/tmp/dycast"),
            ["高能", "来了"],
        )

        self.assertEqual(config.marker.keywords, ["高能", "来了"])

    def test_runtime_config_uses_custom_gift_threshold(self):
        config = build_runtime_config(
            "demo",
            "https://live.douyin.com/123456789",
            Path("/tmp/out"),
            Path("/tmp/dycast"),
            ["高能"],
            gift_value_threshold=3000,
        )

        self.assertEqual(config.marker.gift_value_threshold, 3000)

    def test_parse_keywords_splits_and_deduplicates(self):
        self.assertEqual(parse_keywords("高能,来了\n抽奖  高能，名场面"), ["高能", "来了", "抽奖", "名场面"])

    def test_parse_streamer_entries_keeps_complete_rows(self):
        self.assertEqual(
            parse_streamer_entries(
                [
                    {
                        "name": "a",
                        "url": "https://live.douyin.com/123456789",
                        "saveDir": "/tmp/a",
                        "keywords": "高能",
                        "giftValueThreshold": "3000",
                    },
                    {"name": "", "url": "https://live.douyin.com/1", "saveDir": "/tmp/b"},
                ]
            ),
            [
                {
                    "name": "a",
                    "url": "https://live.douyin.com/123456789",
                    "saveDir": "/tmp/a",
                    "keywords": "高能",
                    "giftValueThreshold": "3000",
                }
            ],
        )

    def test_recorder_safe_filename_removes_path_separators(self):
        self.assertEqual(safe_filename('主播/标题:测试?'), "主播_标题_测试_")

    def test_sanitize_douyin_share_text(self):
        self.assertEqual(
            sanitize_douyin_url("https://v.douyin.com/L52PfolswRs/ 9@5.com"),
            "https://v.douyin.com/L52PfolswRs/",
        )

    def test_status_payload_idle_is_not_recording(self):
        state = UiState()
        payload = status_payload(state)

        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["label"], "未启动")
        self.assertFalse(payload["running"])

    def test_missing_settings_returns_empty(self):
        self.assertIsInstance(load_ui_settings(), dict)

    def test_render_index_uses_saved_values(self):
        html = render_index(
            {
                "streamer": "主播",
                "url": "https://live.douyin.com/123456789",
                "saveDir": "/tmp/live",
                "keywords": "高能，抽奖",
                "giftValueThreshold": 3000,
            }
        )

        self.assertIn('"streamer": "主播"', html)
        self.assertIn('"url": "https://live.douyin.com/123456789"', html)
        self.assertIn('"saveDir": "/tmp/live"', html)
        self.assertIn("高能，抽奖", html)
        self.assertIn('"giftValueThreshold": 3000', html)
