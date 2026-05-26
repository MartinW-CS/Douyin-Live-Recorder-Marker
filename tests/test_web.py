import unittest

from douyin_live_marker.web import UiState, extract_douyin_room, load_ui_settings, render_index, sanitize_douyin_url, status_payload


class WebTests(unittest.TestCase):
    def test_extract_room_from_live_url(self):
        self.assertEqual(
            extract_douyin_room("https://live.douyin.com/123456789?foo=bar"),
            "123456789",
        )

    def test_extract_room_from_plain_room_number(self):
        self.assertEqual(extract_douyin_room("123456789"), "123456789")

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
