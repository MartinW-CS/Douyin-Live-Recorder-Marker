from pathlib import Path
import unittest

from douyin_live_marker.web import (
    UiState,
    build_runtime_config,
    extract_douyin_room,
    extract_web_rid,
    load_ui_settings,
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
            }
        )

        self.assertIn('value="主播"', html)
        self.assertIn('value="https://live.douyin.com/123456789"', html)
        self.assertIn('value="/tmp/live"', html)
