from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import asyncio
import json

from .analyzer import MarkerAnalyzer
from .biliup import write_biliup_config
from .collectors.dycast import DycastWebSocketServerCollector
from .config import AppConfig
from .events import parse_timestamp
from .io import append_event_jsonl, write_markers_csv, write_markers_json


@dataclass(frozen=True)
class PipelineOptions:
    started_at: datetime | None = None
    events_output: str | None = None
    json_output: str | None = None
    csv_output: str | None = None
    streamer: str | None = None
    start_biliup: bool = True
    start_dycast: bool = True


@dataclass
class ManagedProcess:
    name: str
    process: asyncio.subprocess.Process


async def run_pipeline(config: AppConfig, options: PipelineOptions) -> None:
    started_at = options.started_at or datetime.now(timezone.utc)
    events_output = options.events_output or config.dycast.events_output
    json_output = options.json_output or config.marker.output_json
    csv_output = options.csv_output or config.marker.output_csv
    streamer = options.streamer or config.dycast.streamer or config.streamers[0].name

    biliup_config_path = write_biliup_config(config)
    metadata_path = write_pipeline_metadata(config, biliup_config_path, started_at, events_output)
    print(f"recording start time: {started_at.isoformat()}")
    print(f"wrote pipeline metadata to {metadata_path}")

    processes: list[ManagedProcess] = []
    try:
        if options.start_biliup and config.biliup.enabled:
            processes.append(
                await start_process(
                    "biliup",
                    make_biliup_command(config, biliup_config_path),
                )
            )
        if options.start_dycast and config.dycast.enabled:
            if config.dycast.command:
                processes.append(
                    await start_process(
                        "dycast",
                        config.dycast.command,
                        cwd=config.dycast.cwd,
                    )
                )
            else:
                print("dycast command is empty; start dycast manually")

        analyzer = MarkerAnalyzer(config.marker, started_at)
        collector = DycastWebSocketServerCollector(
            host=config.dycast.host,
            port=config.dycast.port,
            streamer=streamer,
            skip_gift_repeats=config.dycast.skip_gift_repeats,
        )
        markers = []
        print(
            f"listening for dycast on ws://{config.dycast.host}:{config.dycast.port}; "
            f"writing events to {events_output}"
        )
        await ensure_processes_still_running(processes)
        async for event in collector.collect():
            await ensure_processes_still_running(processes)
            append_event_jsonl(events_output, event)
            if event.timestamp < started_at:
                continue
            new_markers = analyzer.process(event)
            if not new_markers:
                continue
            markers.extend(new_markers)
            write_markers_json(json_output, markers)
            write_markers_csv(csv_output, markers)
            print(f"wrote {len(markers)} markers to {json_output} and {csv_output}")
    finally:
        await stop_processes(processes)


def make_biliup_command(config: AppConfig, biliup_config_path: str | Path) -> list[str]:
    return [config.biliup.command, *config.biliup.args]


async def start_process(
    name: str,
    command: list[str],
    cwd: str | None = None,
) -> ManagedProcess:
    if not command:
        raise ValueError(f"{name} command cannot be empty")
    process = await asyncio.create_subprocess_exec(*command, cwd=cwd or None)
    print(f"started {name}: {' '.join(command)}")
    return ManagedProcess(name=name, process=process)


async def ensure_processes_still_running(processes: list[ManagedProcess]) -> None:
    await asyncio.sleep(0.2)
    failed = [
        managed
        for managed in processes
        if managed.process.returncode not in {None, 0}
    ]
    if failed:
        details = ", ".join(
            f"{managed.name} exited with {managed.process.returncode}" for managed in failed
        )
        raise RuntimeError(details)


async def stop_processes(processes: list[ManagedProcess]) -> None:
    for managed in reversed(processes):
        if managed.process.returncode is not None:
            continue
        print(f"stopping {managed.name}")
        managed.process.terminate()
    if not processes:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(*(managed.process.wait() for managed in processes)),
            timeout=5,
        )
    except TimeoutError:
        for managed in processes:
            if managed.process.returncode is None:
                print(f"killing {managed.name}")
                managed.process.kill()
        await asyncio.gather(*(managed.process.wait() for managed in processes))


def write_pipeline_metadata(
    config: AppConfig,
    biliup_config_path: Path,
    started_at: datetime,
    events_output: str,
) -> Path:
    output_dir = Path(config.biliup.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "version": 1,
        "recording_started_at": started_at.isoformat(),
        "biliup_config_path": str(biliup_config_path),
        "dycast_forward_url": f"ws://{config.dycast.host}:{config.dycast.port}",
        "events_output": events_output,
        "streamers": [
            {
                "name": streamer.name,
                "url": streamer.url,
            }
            for streamer in config.streamers
        ],
    }
    metadata_path = output_dir / "pipeline-session.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata_path


def parse_optional_started_at(value: str | None) -> datetime | None:
    if not value or value == "auto":
        return None
    return parse_timestamp(value)
