import unittest

from douyin_live_marker.config import parse_config


class ConfigTests(unittest.TestCase):
    def test_parse_minimal_config(self):
        config = parse_config(
            {
                "streamers": [
                    {
                        "name": "demo",
                        "url": "https://live.douyin.com/123",
                    }
                ]
            }
        )

        self.assertEqual(config.streamers[0].name, "demo")
        self.assertEqual(config.marker.danmaku_window_seconds, 30)
        self.assertEqual(config.biliup.args, ["server"])

    def test_parse_dycast_config_command(self):
        config = parse_config(
            {
                "streamers": [
                    {
                        "name": "demo",
                        "url": "https://live.douyin.com/123",
                    }
                ],
                "dycast": {
                    "command": ["npm", "run", "dev"],
                    "cwd": "/tmp/dycast",
                    "port": 9000,
                },
            }
        )

        self.assertEqual(config.dycast.command, ["npm", "run", "dev"])
        self.assertEqual(config.dycast.cwd, "/tmp/dycast")
        self.assertEqual(config.dycast.port, 9000)
