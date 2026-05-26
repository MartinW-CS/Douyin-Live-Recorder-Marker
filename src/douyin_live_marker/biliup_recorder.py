from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import asyncio
import logging
import re
import signal
import sys
import threading

import requests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one Douyin room through biliup's Douyin plugin.")
    parser.add_argument("--streamer", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--segment-time", default="01:00:00")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return asyncio.run(record(args.streamer, args.url, Path(args.output_dir), args.segment_time))
    except KeyboardInterrupt:
        return 130


async def record(streamer: str, url: str, output_dir: Path, segment_time: str) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    # biliup imports its async HTTP client at module import time, so import it
    # from inside a running event loop.
    from biliup.plugins.douyin import Douyin

    config = {
        "streamers": {streamer: {}},
        "filename_prefix": str(output_dir / "{streamer}-%Y-%m-%dT%H_%M_%S-{title}"),
        "downloader": "stream-gears",
        "segment_time": segment_time,
        "douyin_danmaku": False,
    }
    recorder = Douyin(streamer, url, config)
    is_live = await recorder.acheck_stream()
    if not is_live:
        print(f"biliup recorder: stream is not live or could not be opened: {url}", file=sys.stderr)
        return 2

    print(f"biliup recorder: recording {streamer} from {url} to {output_dir}")
    output_path = build_output_path(output_dir, streamer, recorder.room_title)
    stream_to_file(recorder.raw_stream_url, recorder.stream_headers, output_path)
    return 0


def build_output_path(output_dir: Path, streamer: str, title: str | None) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%dT%H_%M_%S")
    parts = [streamer, stamp]
    if title:
        parts.append(title)
    return output_dir / f"{safe_filename('-'.join(parts))}.flv"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", value).strip(" .")
    return cleaned or "recording"


def stream_to_file(url: str, headers: dict[str, str], output_path: Path) -> None:
    stop_event = threading.Event()

    def stop(_signum, _frame):
        stop_event.set()

    previous_sigterm = signal.signal(signal.SIGTERM, stop)
    previous_sigint = signal.signal(signal.SIGINT, stop)
    try:
        with requests.get(url, headers=headers, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            print(f"biliup recorder: writing video to {output_path}")
            with output_path.open("ab") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if stop_event.is_set():
                        break
                    if not chunk:
                        continue
                    file.write(chunk)
                    file.flush()
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


if __name__ == "__main__":
    raise SystemExit(main())
