from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import asyncio
import contextlib
import html
import json
import re
import ssl
import sys

from aiohttp import web

from .config import AppConfig, BiliupConfig, DycastConfig, MarkerConfig, StreamerConfig
from .dycast_patch import ensure_dycast_auto_connect
from .pipeline import PipelineOptions, run_pipeline

SETTINGS_PATH = Path(".douyin-recorder-ui.json")


class UiState:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.readiness_task: asyncio.Task | None = None
        self.auto_running = False
        self.auto_tasks: dict[str, asyncio.Task] = {}
        self.jobs: dict[str, AutoJob] = {}
        self.dycast_process: asyncio.subprocess.Process | None = None
        self.status = "idle"
        self.message = "Ready"
        self.config: AppConfig | None = None
        self.options: PipelineOptions | None = None
        self.dycast_url: str | None = None


@dataclass
class AutoJob:
    id: str
    name: str
    url: str
    save_dir: str
    keywords_text: str
    relay_port: int
    status: str = "idle"
    message: str = "未启动"
    dycast_url: str | None = None
    room_url: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "saveDir": self.save_dir,
            "keywords": self.keywords_text,
            "relayPort": self.relay_port,
            "status": self.status,
            "label": auto_status_label(self.status),
            "message": self.message,
            "dycastUrl": self.dycast_url,
            "roomUrl": self.room_url,
            "lastError": self.last_error,
        }


def create_app() -> web.Application:
    app = web.Application()
    state = UiState()
    app["state"] = state
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/settings", settings)
    app.router.add_post("/api/choose-dir", choose_dir)
    app.router.add_post("/api/start", start)
    app.router.add_post("/api/start-auto", start_auto)
    app.router.add_post("/api/stop", stop)
    return app


async def run_ui(host: str, port: int) -> None:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"UI running at http://{host}:{port}")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


async def index(request: web.Request) -> web.Response:
    return web.Response(text=render_index(load_ui_settings()), content_type="text/html")


async def status(request: web.Request) -> web.Response:
    state: UiState = request.app["state"]
    return web.json_response(status_payload(state))


async def settings(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "settings": load_ui_settings()})


async def choose_dir(request: web.Request) -> web.Response:
    script = 'POSIX path of (choose folder with prompt "选择直播录制保存位置")'
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() or "folder selection cancelled"
        return web.json_response({"ok": False, "error": message}, status=400)
    path = stdout.decode("utf-8", errors="replace").strip()
    return web.json_response({"ok": True, "path": path})


async def start(request: web.Request) -> web.Response:
    state: UiState = request.app["state"]
    if state.task is not None and not state.task.done():
        return web.json_response({"ok": False, "error": "pipeline already running"}, status=409)

    payload = await request.json()
    streamer = str(payload.get("streamer") or "").strip()
    url = sanitize_douyin_url(str(payload.get("url") or ""))
    save_dir = str(payload.get("saveDir") or "").strip()
    keywords_text = str(payload.get("keywords") or "")
    keywords = parse_keywords(keywords_text)
    if not streamer or not url or not save_dir:
        return web.json_response({"ok": False, "error": "streamer, url and saveDir are required"}, status=400)
    save_ui_settings({"streamer": streamer, "url": url, "saveDir": save_dir, "keywords": keywords_text})

    save_path = Path(save_dir).expanduser().resolve()
    save_path.mkdir(parents=True, exist_ok=True)
    dycast_dir = Path(payload.get("dycastDir") or "vendor/dycast")
    ensure_dycast_auto_connect(dycast_dir)

    relay_url = "ws://127.0.0.1:8765"
    try:
        room = await asyncio.to_thread(extract_douyin_room, url)
    except Exception as exc:
        return web.json_response(
            {
                "ok": False,
                "error": (
                    "无法从抖音链接解析房间号。请确认链接可访问，"
                    "或直接粘贴 live.douyin.com 的直播间链接。"
                ),
                "detail": str(exc),
            },
            status=400,
        )
    if not re.fullmatch(r"[0-9]{8,12}", room):
        return web.json_response(
            {
                "ok": False,
                "error": "could not resolve a dycast room number from the Douyin URL",
                "detail": "dycast needs the short room number used by live.douyin.com, not the long reflow room_id",
            },
            status=400,
        )
    dycast_url = (
        "http://127.0.0.1:5173/"
        f"?auto=1&room={quote(room)}&relay={quote(relay_url)}"
    )
    recording_url = f"https://live.douyin.com/{room}"
    config = build_runtime_config(streamer, recording_url, save_path, dycast_dir, keywords)
    options = PipelineOptions(
        streamer=streamer,
        save_dir=str(save_path),
    )
    state.status = "starting"
    state.message = "Starting pipeline"
    state.config = config
    state.options = options
    state.dycast_url = dycast_url
    state.task = asyncio.create_task(run_pipeline_with_state(state, config, options))
    state.readiness_task = asyncio.create_task(mark_recording_when_ready(state))
    return web.json_response({"ok": True, "dycastUrl": dycast_url})


async def start_auto(request: web.Request) -> web.Response:
    state: UiState = request.app["state"]
    if state.auto_running:
        return web.json_response({"ok": False, "error": "auto recording is already running"}, status=409)

    payload = await request.json()
    entries = parse_streamer_entries(payload.get("streamers"))
    if not entries:
        return web.json_response({"ok": False, "error": "at least one streamer is required"}, status=400)

    dycast_dir = Path(payload.get("dycastDir") or "vendor/dycast")
    ensure_dycast_auto_connect(dycast_dir)
    save_ui_settings({"streamers": entries})

    state.auto_running = True
    state.status = "recording"
    state.message = "自动录制守护已启动"
    state.jobs = {}
    state.auto_tasks = {}
    state.dycast_process = await start_dycast_process(dycast_dir)

    for index, entry in enumerate(entries):
        job = AutoJob(
            id=f"streamer-{index + 1}",
            name=entry["name"],
            url=entry["url"],
            save_dir=entry["saveDir"],
            keywords_text=entry["keywords"],
            relay_port=8765 + index,
        )
        state.jobs[job.id] = job
        state.auto_tasks[job.id] = asyncio.create_task(run_auto_job(state, job))

    return web.json_response({"ok": True, "jobs": [job.to_dict() for job in state.jobs.values()]})


async def stop(request: web.Request) -> web.Response:
    state: UiState = request.app["state"]
    await stop_auto_state(state)
    if state.task is not None and not state.task.done():
        state.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.task
    if state.readiness_task is not None and not state.readiness_task.done():
        state.readiness_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.readiness_task
    state.status = "stopped"
    state.message = "Stopped"
    return web.json_response({"ok": True})


async def stop_auto_state(state: UiState) -> None:
    if state.auto_tasks:
        for task in state.auto_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.auto_tasks.values(), return_exceptions=True)
        state.auto_tasks = {}
    if state.dycast_process is not None and state.dycast_process.returncode is None:
        state.dycast_process.terminate()
        try:
            await asyncio.wait_for(state.dycast_process.wait(), timeout=5)
        except TimeoutError:
            state.dycast_process.kill()
            await state.dycast_process.wait()
    state.dycast_process = None
    state.auto_running = False
    for job in state.jobs.values():
        if job.status not in {"error", "stopped"}:
            job.status = "stopped"
            job.message = "已停止"


async def run_pipeline_with_state(state: UiState, config: AppConfig, options: PipelineOptions) -> None:
    try:
        await run_pipeline(config, options)
    except asyncio.CancelledError:
        state.status = "stopped"
        state.message = "Stopped"
        raise
    except Exception as exc:
        state.status = "error"
        state.message = str(exc)
    else:
        state.status = "stopped"
        state.message = "Stopped"


async def start_dycast_process(dycast_dir: Path) -> asyncio.subprocess.Process:
    process = await asyncio.create_subprocess_exec(
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
        cwd=str(dycast_dir),
    )
    print("started dycast shared server: npm run dev -- --host 127.0.0.1 --port 5173")
    return process


async def run_auto_job(state: UiState, job: AutoJob) -> None:
    poll_seconds = 30
    try:
        while state.auto_running:
            job.status = "checking"
            job.message = "正在检测直播状态"
            try:
                room = await asyncio.to_thread(extract_douyin_room, job.url)
                if not re.fullmatch(r"[0-9]{8,12}", room):
                    raise ValueError("无法解析 live.douyin.com 短房间号")
                save_path = Path(job.save_dir).expanduser().resolve()
                save_path.mkdir(parents=True, exist_ok=True)
                room_url = f"https://live.douyin.com/{room}"
                job.room_url = room_url
                job.dycast_url = (
                    "http://127.0.0.1:5173/"
                    f"?auto=1&room={quote(room)}&relay={quote(f'ws://127.0.0.1:{job.relay_port}')}"
                )
                config = build_runtime_config(
                    job.name,
                    room_url,
                    save_path,
                    Path("vendor/dycast"),
                    parse_keywords(job.keywords_text),
                    dycast_port=job.relay_port,
                    dycast_enabled=True,
                )
                options = PipelineOptions(
                    streamer=job.name,
                    save_dir=str(save_path),
                    start_dycast=False,
                )
                job.status = "recording"
                job.message = "检测到开播，正在录制"
                await run_pipeline(config, options)
                job.status = "waiting"
                job.message = f"录制已结束，{poll_seconds} 秒后继续检测"
                job.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.status = "waiting"
                job.message = f"未开播或录制已结束，{poll_seconds} 秒后重试"
                job.last_error = str(exc)
            await asyncio.sleep(poll_seconds)
    except asyncio.CancelledError:
        job.status = "stopped"
        job.message = "已停止"
        raise


async def mark_recording_when_ready(state: UiState) -> None:
    try:
        for _ in range(60):
            if state.task is None or state.task.done():
                return
            dycast_ready = await can_connect("127.0.0.1", 5173)
            recorder_running = state.task is not None and not state.task.done()
            if dycast_ready and recorder_running:
                state.status = "recording"
                state.message = "Recording pipeline is running"
                return
            await asyncio.sleep(0.5)
        if state.status == "starting":
            state.message = "Still waiting for biliup and dycast to become ready"
    except asyncio.CancelledError:
        raise


async def can_connect(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.3)
    except OSError:
        return False
    except TimeoutError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


def build_runtime_config(
    streamer: str,
    url: str,
    save_dir: Path,
    dycast_dir: Path,
    keywords: list[str] | None = None,
    dycast_port: int = 8765,
    dycast_enabled: bool = True,
) -> AppConfig:
    return AppConfig(
        streamers=[StreamerConfig(name=streamer, url=url)],
        marker=MarkerConfig(
            keywords=keywords if keywords is not None else default_keywords(),
            output_json=str(save_dir / "markers.json"),
            output_csv=str(save_dir / "markers.csv"),
        ),
        biliup=BiliupConfig(
            enabled=True,
            command=sys.executable,
            args=[
                "-m",
                "douyin_live_marker.biliup_recorder",
                "--streamer",
                streamer,
                "--url",
                url,
                "--output-dir",
                str(save_dir / "recordings"),
            ],
            config_path=str(save_dir / "biliup.config.toml"),
            output_dir=str(save_dir / "recordings"),
        ),
        dycast=DycastConfig(
            enabled=dycast_enabled,
            command=["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
            cwd=str(dycast_dir),
            host="127.0.0.1",
            port=dycast_port,
            events_output=str(save_dir / "events.jsonl"),
            streamer=streamer,
            skip_gift_repeats=True,
        ),
    )


def default_keywords() -> list[str]:
    return ["名场面", "来了", "抽奖"]


def parse_keywords(value: str) -> list[str]:
    keywords: list[str] = []
    seen = set()
    for item in re.split(r"[\s,，、;；]+", value):
        keyword = item.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
    return keywords


def parse_streamer_entries(raw_entries: object) -> list[dict[str, str]]:
    if not isinstance(raw_entries, list):
        return []
    entries: list[dict[str, str]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("streamer") or "").strip()
        url = sanitize_douyin_url(str(raw.get("url") or ""))
        save_dir = str(raw.get("saveDir") or "").strip()
        keywords = str(raw.get("keywords") or "，".join(default_keywords())).strip()
        if not name or not url or not save_dir:
            continue
        entries.append({"name": name, "url": url, "saveDir": save_dir, "keywords": keywords})
    return entries


def sanitize_douyin_url(value: str) -> str:
    text = value.strip()
    match = re.search(r"https?://\S+", text)
    if not match:
        return text
    return match.group(0).rstrip("，,。.;；")


def extract_douyin_room(url: str) -> str:
    text = sanitize_douyin_url(url)
    direct = re.search(r"live\.douyin\.com/([0-9]{8,12})", text)
    if direct:
        return direct.group(1)
    reflow = re.search(r"/douyin/webcast/reflow/[0-9]{8,20}", text)
    if reflow:
        body = fetch_douyin_page(text)[1]
        web_rid = extract_web_rid(body)
        if web_rid:
            return web_rid
        raise ValueError("reflow link did not expose a live.douyin.com webRid")
    if re.fullmatch(r"[0-9]{8,12}", text):
        return text
    if "live.douyin.com/" in text:
        return text.rstrip("/").split("/")[-1].split("?")[0]
    if "v.douyin.com/" in text:
        final_url, body = fetch_douyin_page(text)
        final = re.search(r"live\.douyin\.com/([0-9]{8,12})", final_url)
        if final:
            return final.group(1)
        web_rid = extract_web_rid(body)
        if web_rid:
            return web_rid
        raise ValueError(f"could not find live.douyin.com webRid in redirected page: {final_url}")
    return text


def fetch_douyin_page(url: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
            )
        },
    )
    context = ssl._create_unverified_context()
    try:
        with urlopen(request, timeout=10, context=context) as response:
            final_url = response.geturl()
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        final_url = exc.url
        body = exc.read().decode("utf-8", errors="replace")
    return final_url, body


def extract_web_rid(text: str) -> str | None:
    decoded = html.unescape(text)
    patterns = (
        r'webRid\\?":\\?"([0-9]{8,12})',
        r'web_rid\\?":\\?"([0-9]{8,12})',
        r'web_rid=([0-9]{8,12})',
    )
    for pattern in patterns:
        match = re.search(pattern, decoded)
        if match:
            return match.group(1)
    return None


def load_ui_settings() -> dict[str, object]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        "streamer": str(raw.get("streamer") or ""),
        "url": str(raw.get("url") or ""),
        "saveDir": str(raw.get("saveDir") or ""),
        "keywords": str(raw.get("keywords") or ""),
        "streamers": raw.get("streamers") if isinstance(raw.get("streamers"), list) else [],
    }


def save_ui_settings(settings: dict[str, object]) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def render_index(settings: dict[str, object]) -> str:
    settings_json = json.dumps(settings, ensure_ascii=False).replace("</", "<\\/")
    return (
        INDEX_HTML.replace("__SETTINGS_JSON__", settings_json)
        .replace("__STREAMER__", html.escape(str(settings.get("streamer", "")), quote=True))
        .replace("__URL__", html.escape(str(settings.get("url", "")), quote=True))
        .replace("__SAVE_DIR__", html.escape(str(settings.get("saveDir", "")), quote=True))
        .replace("__KEYWORDS__", html.escape(str(settings.get("keywords") or "，".join(default_keywords()))))
    )


def status_payload(state: UiState) -> dict[str, object]:
    running = state.task is not None and not state.task.done()
    label_map = {
        "idle": "未启动",
        "starting": "启动中",
        "recording": "录制中",
        "running": "录制中",
        "stopped": "已停止",
        "error": "出错",
    }
    detail_map = {
        "idle": "还没有启动录制。填写信息后点击“启动录制”。",
        "starting": "正在启动 biliup、dycast 和高光标记器。右侧页面可能需要几秒钟才能加载。",
        "recording": "录制流水线正在运行。请确认右侧 dycast 页面已连接直播间。",
        "running": "录制流水线正在运行。请确认右侧 dycast 页面已连接直播间。",
        "stopped": "录制流水线已停止。",
        "error": "启动或运行过程中出现错误。",
    }
    label = label_map.get(state.status, state.status)
    detail = detail_map.get(state.status, state.message)
    return {
        "status": state.status,
        "label": label,
        "detail": detail,
        "message": state.message,
        "dycastUrl": state.dycast_url,
        "running": running,
        "autoRunning": state.auto_running,
        "jobs": [job.to_dict() for job in state.jobs.values()],
    }


def auto_status_label(status: str) -> str:
    return {
        "idle": "未启动",
        "checking": "检测中",
        "waiting": "等待开播",
        "recording": "录制中",
        "stopped": "已停止",
        "error": "出错",
    }.get(status, status)


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>抖音直播自动录制</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f5f7fa; color: #1f2937; }
    .shell { max-width: 1320px; margin: 0 auto; padding: 24px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    h1 { font-size: 24px; margin: 0; letter-spacing: 0; }
    .toolbar { display: flex; gap: 10px; flex-wrap: wrap; }
    button { border: 0; border-radius: 6px; padding: 10px 14px; font-size: 14px; cursor: pointer; white-space: nowrap; }
    .primary { background: #1769aa; color: #fff; }
    .danger { background: #e03131; color: #fff; }
    .secondary { background: #e8edf2; color: #26323f; }
    .layout { display: grid; grid-template-columns: minmax(520px, 0.9fr) minmax(420px, 1.1fr); gap: 18px; align-items: start; }
    .panel { background: #fff; border: 1px solid #d7dde4; border-radius: 8px; padding: 16px; }
    .panel-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
    .panel-title h2 { font-size: 16px; margin: 0; }
    .streamer-list { display: grid; gap: 12px; }
    .streamer-card { border: 1px solid #d7dde4; border-radius: 8px; padding: 12px; background: #fbfcfd; }
    .streamer-head { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 10px; }
    .streamer-head strong { font-size: 14px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    label { display: block; font-size: 12px; color: #526070; margin: 0 0 5px; }
    input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #bac4cf; border-radius: 6px; padding: 9px 10px; font-size: 14px; font-family: inherit; background: #fff; }
    textarea { min-height: 64px; resize: vertical; line-height: 1.4; }
    .full { grid-column: 1 / -1; }
    .path-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .hint { font-size: 12px; color: #64748b; line-height: 1.45; margin: 10px 0 0; }
    .status-list { display: grid; gap: 10px; }
    .job { border: 1px solid #d7dde4; border-radius: 8px; padding: 12px; background: #fff; }
    .job-top { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
    .pill { display: inline-flex; align-items: center; gap: 7px; border-radius: 999px; background: #eef2f6; padding: 5px 9px; font-size: 12px; color: #394657; }
    .dot { width: 8px; height: 8px; border-radius: 999px; background: #9aa7b1; }
    .dot.recording { background: #2fb344; }
    .dot.checking { background: #f59f00; }
    .dot.waiting { background: #748ffc; }
    .dot.error { background: #e03131; }
    .job-message { margin-top: 8px; font-size: 13px; color: #526070; line-height: 1.45; }
    iframe { width: 100%; height: 260px; border: 1px solid #d7dde4; border-radius: 8px; background: #fff; margin-top: 10px; }
    .empty { border: 1px dashed #bac4cf; border-radius: 8px; padding: 24px; text-align: center; color: #64748b; background: #fbfcfd; }
    @media (max-width: 960px) {
      .layout { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <div class="topbar">
      <div>
        <h1>抖音直播自动录制</h1>
        <p class="hint">多主播无人值守：检测开播后自动录制，保存视频、弹幕事件和高光标记。</p>
      </div>
      <div class="toolbar">
        <button class="secondary" id="addStreamerBtn" type="button">添加主播</button>
        <button class="primary" id="startAutoBtn" type="button">启动自动录制</button>
        <button class="danger" id="stopBtn" type="button">停止全部</button>
      </div>
    </div>
    <div class="layout">
      <section class="panel">
        <div class="panel-title">
          <h2>主播列表</h2>
          <span class="pill" id="summaryPill"><span class="dot" id="summaryDot"></span><span id="summaryText">未启动</span></span>
        </div>
        <div class="streamer-list" id="streamerList"></div>
        <p class="hint">每个主播使用独立保存目录。多个关键词可用空格、逗号或换行分隔。</p>
      </section>
      <section class="panel">
        <div class="panel-title">
          <h2>运行状态</h2>
        </div>
        <div class="status-list" id="statusList">
          <div class="empty">启动后这里会显示每个主播的检测、录制和 dycast 连接状态。</div>
        </div>
      </section>
    </div>
  </main>
  <script id="initialSettings" type="application/json">__SETTINGS_JSON__</script>
  <script>
    const defaultKeywords = '名场面，来了，抽奖';
    const initialSettings = JSON.parse(document.getElementById('initialSettings').textContent || '{}');
    const streamerList = document.getElementById('streamerList');
    const statusList = document.getElementById('statusList');
    const summaryText = document.getElementById('summaryText');
    const summaryDot = document.getElementById('summaryDot');
    let activePathInput = null;

    function requestJson(method, url, data) {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(method, url);
        xhr.setRequestHeader('content-type', 'application/json');
        xhr.onload = () => {
          let body = {};
          try { body = JSON.parse(xhr.responseText || '{}'); } catch (err) {}
          resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, body });
        };
        xhr.onerror = () => reject(new Error('Network request failed'));
        xhr.send(data ? JSON.stringify(data) : undefined);
      });
    }

    function seedStreamers() {
      if (Array.isArray(initialSettings.streamers) && initialSettings.streamers.length) {
        return initialSettings.streamers;
      }
      if (initialSettings.streamer || initialSettings.url || initialSettings.saveDir) {
        return [{
          name: initialSettings.streamer || '',
          url: initialSettings.url || '',
          saveDir: initialSettings.saveDir || '',
          keywords: initialSettings.keywords || defaultKeywords
        }];
      }
      return [{ name: '', url: '', saveDir: '', keywords: defaultKeywords }];
    }

    function addStreamer(values = {}) {
      const index = streamerList.children.length + 1;
      const card = document.createElement('div');
      card.className = 'streamer-card';
      card.innerHTML = `
        <div class="streamer-head">
          <strong>主播 ${index}</strong>
          <button class="secondary remove-btn" type="button">移除</button>
        </div>
        <div class="grid">
          <div>
            <label>主播名字</label>
            <input name="name" autocomplete="off" required>
          </div>
          <div>
            <label>直播 URL</label>
            <input name="url" required>
          </div>
          <div class="full">
            <label>保存到电脑的位置</label>
            <div class="path-row">
              <input name="saveDir" required>
              <button class="secondary choose-btn" type="button">选择位置</button>
            </div>
          </div>
          <div class="full">
            <label>高光关键词</label>
            <textarea name="keywords"></textarea>
          </div>
        </div>`;
      card.querySelector('[name="name"]').value = values.name || values.streamer || '';
      card.querySelector('[name="url"]').value = values.url || '';
      card.querySelector('[name="saveDir"]').value = values.saveDir || '';
      card.querySelector('[name="keywords"]').value = values.keywords || defaultKeywords;
      card.querySelector('.remove-btn').addEventListener('click', () => {
        if (streamerList.children.length > 1) card.remove();
      });
      card.querySelector('.choose-btn').addEventListener('click', async () => {
        activePathInput = card.querySelector('[name="saveDir"]');
        const { ok, body } = await requestJson('POST', '/api/choose-dir');
        if (ok && body.ok && activePathInput) activePathInput.value = body.path;
      });
      streamerList.appendChild(card);
    }

    function collectStreamers() {
      return [...streamerList.querySelectorAll('.streamer-card')].map(card => ({
        name: card.querySelector('[name="name"]').value.trim(),
        url: card.querySelector('[name="url"]').value.trim(),
        saveDir: card.querySelector('[name="saveDir"]').value.trim(),
        keywords: card.querySelector('[name="keywords"]').value.trim()
      })).filter(item => item.name && item.url && item.saveDir);
    }

    function renderStatus(body) {
      summaryText.textContent = body.autoRunning ? '自动录制运行中' : (body.label || '未启动');
      summaryDot.className = `dot ${body.autoRunning ? 'recording' : body.status || ''}`;
      if (!body.jobs || !body.jobs.length) {
        statusList.innerHTML = '<div class="empty">启动后这里会显示每个主播的检测、录制和 dycast 连接状态。</div>';
        return;
      }
      statusList.innerHTML = '';
      for (const job of body.jobs) {
        const item = document.createElement('div');
        item.className = 'job';
        item.innerHTML = `
          <div class="job-top">
            <strong>${escapeHtml(job.name)}</strong>
            <span class="pill"><span class="dot ${job.status}"></span>${escapeHtml(job.label || job.status)}</span>
          </div>
          <div class="job-message">${escapeHtml(job.message || '')}</div>
          ${job.lastError ? `<div class="job-message">最近信息：${escapeHtml(job.lastError)}</div>` : ''}
          ${job.dycastUrl ? `<iframe src="${escapeAttr(job.dycastUrl)}" title="${escapeAttr(job.name)} dycast"></iframe>` : ''}`;
        statusList.appendChild(item);
      }
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
    }
    function escapeAttr(value) {
      return escapeHtml(value);
    }

    document.getElementById('addStreamerBtn').addEventListener('click', () => addStreamer());
    document.getElementById('startAutoBtn').addEventListener('click', async () => {
      const streamers = collectStreamers();
      if (!streamers.length) {
        alert('至少填写一个主播、直播 URL 和保存位置。');
        return;
      }
      const { ok, body } = await requestJson('POST', '/api/start-auto', { streamers });
      if (!ok || !body.ok) alert(body.error || '启动失败');
      await pollStatus();
    });
    document.getElementById('stopBtn').addEventListener('click', async () => {
      await requestJson('POST', '/api/stop');
      await pollStatus();
    });

    async function pollStatus() {
      const { ok, body } = await requestJson('GET', '/api/status');
      if (ok) renderStatus(body);
    }

    seedStreamers().forEach(addStreamer);
    pollStatus();
    setInterval(pollStatus, 1500);
  </script>
</body>
</html>
"""
