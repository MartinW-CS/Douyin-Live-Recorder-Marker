from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from .analyzer import MarkerAnalyzer
from .biliup import run_biliup, write_biliup_config
from .collectors.dycast import collect_dycast_to_jsonl
from .config import load_config, sample_config
from .events import parse_timestamp
from .io import follow_jsonl_events, read_jsonl_events, write_markers_csv, write_markers_json
from .pipeline import PipelineOptions, parse_optional_started_at, run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-marker",
        description="Record Douyin live streams with biliup and generate highlight markers.",
    )
    subparsers = parser.add_subparsers(required=True)

    init_parser = subparsers.add_parser("init-config", help="write a sample config.toml")
    init_parser.add_argument("-o", "--output", default="config.toml")
    init_parser.set_defaults(func=cmd_init_config)

    biliup_parser = subparsers.add_parser("write-biliup-config", help="generate biliup config")
    biliup_parser.add_argument("-c", "--config", default="config.toml")
    biliup_parser.add_argument("-o", "--output")
    biliup_parser.set_defaults(func=cmd_write_biliup_config)

    record_parser = subparsers.add_parser("record", help="generate biliup config and start biliup")
    record_parser.add_argument("-c", "--config", default="config.toml")
    record_parser.set_defaults(func=cmd_record)

    analyze_parser = subparsers.add_parser("analyze", help="analyze JSONL events into markers")
    analyze_parser.add_argument("-c", "--config", default="config.toml")
    analyze_parser.add_argument("-i", "--input", required=True, help="JSONL event file")
    analyze_parser.add_argument("--started-at", required=True, help="recording start time")
    analyze_parser.add_argument("--json-output")
    analyze_parser.add_argument("--csv-output")
    analyze_parser.set_defaults(func=cmd_analyze)

    watch_parser = subparsers.add_parser("watch", help="follow JSONL events and update markers")
    watch_parser.add_argument("-c", "--config", default="config.toml")
    watch_parser.add_argument("-i", "--input", required=True, help="JSONL event file")
    watch_parser.add_argument("--started-at", required=True, help="recording start time")
    watch_parser.add_argument("--json-output")
    watch_parser.add_argument("--csv-output")
    watch_parser.add_argument("--poll-seconds", type=float, default=1.0)
    watch_parser.set_defaults(func=cmd_watch)

    collect_dycast_parser = subparsers.add_parser(
        "collect-dycast",
        help="receive dycast WebSocket forwarded messages and write JSONL events",
    )
    collect_dycast_parser.add_argument("--host", default="127.0.0.1")
    collect_dycast_parser.add_argument("--port", type=int, default=8765)
    collect_dycast_parser.add_argument("-o", "--output", default="events.jsonl")
    collect_dycast_parser.add_argument("--streamer")
    collect_dycast_parser.add_argument(
        "--include-gift-repeats",
        action="store_true",
        help="keep repeated dycast gift messages instead of dropping repeatEnd != 0",
    )
    collect_dycast_parser.set_defaults(func=cmd_collect_dycast)

    run_parser = subparsers.add_parser(
        "run-pipeline",
        help="start biliup, dycast, dycast event collection, and marker generation",
    )
    run_parser.add_argument("-c", "--config", default="config.toml")
    run_parser.add_argument("--started-at", default="auto", help="ISO time or auto")
    run_parser.add_argument("--events-output")
    run_parser.add_argument("--json-output")
    run_parser.add_argument("--csv-output")
    run_parser.add_argument("--streamer")
    run_parser.add_argument("--no-biliup", action="store_true")
    run_parser.add_argument("--no-dycast", action="store_true")
    run_parser.set_defaults(func=cmd_run_pipeline)

    return parser


def cmd_init_config(args: argparse.Namespace) -> int:
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing file: {output}")
    output.write_text(sample_config(), encoding="utf-8")
    print(f"wrote {output}")
    return 0


def cmd_write_biliup_config(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    output_path = write_biliup_config(config, args.output)
    print(f"wrote {output_path}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    output_path = write_biliup_config(config)
    metadata_path = write_recording_metadata(config, output_path)
    print(f"wrote recording metadata to {metadata_path}")
    print(f"starting biliup with {output_path}")
    return run_biliup(config, output_path)


def cmd_analyze(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    started_at = parse_timestamp(args.started_at)
    analyzer = MarkerAnalyzer(config.marker, started_at)
    markers = []
    for event in read_jsonl_events(args.input):
        if event.timestamp < started_at:
            continue
        markers.extend(analyzer.process(event))

    json_output = args.json_output or config.marker.output_json
    csv_output = args.csv_output or config.marker.output_csv
    write_markers_json(json_output, markers)
    write_markers_csv(csv_output, markers)
    print(
        f"analyzed {args.input}; wrote {len(markers)} markers to "
        f"{json_output} and {csv_output}"
    )
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    started_at = parse_timestamp(args.started_at)
    analyzer = MarkerAnalyzer(config.marker, started_at)
    markers = []
    json_output = args.json_output or config.marker.output_json
    csv_output = args.csv_output or config.marker.output_csv
    print(f"watching {args.input}; press Ctrl-C to stop")
    try:
        for event in follow_jsonl_events(args.input, args.poll_seconds):
            if event.timestamp < started_at:
                continue
            new_markers = analyzer.process(event)
            if not new_markers:
                continue
            markers.extend(new_markers)
            write_markers_json(json_output, markers)
            write_markers_csv(csv_output, markers)
            print(f"wrote {len(markers)} markers to {json_output} and {csv_output}")
    except KeyboardInterrupt:
        print("stopped")
    return 0


def cmd_collect_dycast(args: argparse.Namespace) -> int:
    print(
        f"listening for dycast messages on ws://{args.host}:{args.port}; "
        f"writing events to {args.output}"
    )
    try:
        asyncio.run(
            collect_dycast_to_jsonl(
                host=args.host,
                port=args.port,
                output=args.output,
                streamer=args.streamer,
                skip_gift_repeats=not args.include_gift_repeats,
            )
        )
    except KeyboardInterrupt:
        print("stopped")
    return 0


def cmd_run_pipeline(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    options = PipelineOptions(
        started_at=parse_optional_started_at(args.started_at),
        events_output=args.events_output,
        json_output=args.json_output,
        csv_output=args.csv_output,
        streamer=args.streamer,
        start_biliup=not args.no_biliup,
        start_dycast=not args.no_dycast,
    )
    try:
        asyncio.run(run_pipeline(config, options))
    except KeyboardInterrupt:
        print("stopped")
    return 0


def write_recording_metadata(config, biliup_config_path: Path) -> Path:
    output_dir = Path(config.biliup.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    metadata = {
        "version": 1,
        "recording_started_at": started_at.isoformat(),
        "biliup_config_path": str(biliup_config_path),
        "streamers": [
            {
                "name": streamer.name,
                "url": streamer.url,
            }
            for streamer in config.streamers
        ],
    }
    metadata_path = output_dir / "recording-session.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata_path


if __name__ == "__main__":
    raise SystemExit(main())
