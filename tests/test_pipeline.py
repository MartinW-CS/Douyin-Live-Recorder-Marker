import unittest

from douyin_live_marker.config import parse_config
from douyin_live_marker.pipeline import make_biliup_command, parse_optional_started_at


class PipelineTests(unittest.TestCase):
    def test_make_biliup_command(self):
        config = parse_config(
            {
                "streamers": [
                    {
                        "name": "demo",
                        "url": "https://live.douyin.com/123",
                    }
                ],
                "biliup": {
                    "command": "biliup",
                },
            }
        )

        self.assertEqual(
            make_biliup_command(config, "biliup.config.toml"),
            ["biliup", "--config", "biliup.config.toml", "start"],
        )

    def test_parse_optional_started_at_auto(self):
        self.assertIsNone(parse_optional_started_at("auto"))
        self.assertIsNone(parse_optional_started_at(None))
