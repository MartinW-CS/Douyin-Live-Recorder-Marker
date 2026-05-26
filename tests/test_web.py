import unittest

from douyin_live_marker.web import extract_douyin_room


class WebTests(unittest.TestCase):
    def test_extract_room_from_live_url(self):
        self.assertEqual(
            extract_douyin_room("https://live.douyin.com/123456789?foo=bar"),
            "123456789",
        )

    def test_extract_room_from_plain_room_number(self):
        self.assertEqual(extract_douyin_room("123456789"), "123456789")
