import unittest

from douyin_live_marker.config import parse_config
from douyin_live_marker.pipeline import ManagedProcess, make_biliup_command, parse_optional_started_at, process_ended_pipeline


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
                    "args": ["server", "--bind", "127.0.0.1"],
                },
            }
        )

        self.assertEqual(
            make_biliup_command(config, "biliup.config.toml"),
            ["biliup", "server", "--bind", "127.0.0.1"],
        )

    def test_parse_optional_started_at_auto(self):
        self.assertIsNone(parse_optional_started_at("auto"))
        self.assertIsNone(parse_optional_started_at(None))

    def test_biliup_exit_ends_pipeline_even_when_successful(self):
        process = type("Process", (), {"returncode": 0})()

        self.assertTrue(process_ended_pipeline(ManagedProcess("biliup", process)))

    def test_dycast_clean_exit_does_not_end_pipeline(self):
        process = type("Process", (), {"returncode": 0})()

        self.assertFalse(process_ended_pipeline(ManagedProcess("dycast", process)))

    def test_non_biliup_exit_does_not_end_pipeline(self):
        process = type("Process", (), {"returncode": 1})()

        self.assertFalse(process_ended_pipeline(ManagedProcess("dycast", process)))
