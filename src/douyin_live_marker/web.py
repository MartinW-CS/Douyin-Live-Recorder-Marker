from __future__ import annotations

from dataclasses import replace
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

from aiohttp import web

from .config import AppConfig, BiliupConfig, DycastConfig, MarkerConfig, StreamerConfig
from .dycast_patch import ensure_dycast_auto_connect
from .pipeline import PipelineOptions, run_pipeline

SETTINGS_PATH = Path(".douyin-recorder-ui.json")


class UiState:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.status = "idle"
        self.message = "Ready"
        self.config: AppConfig | None = None
        self.options: PipelineOptions | None = None
        self.dycast_url: str | None = None


def create_app() -> web.Application:
    app = web.Application()
    state = UiState()
    app["state"] = state
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/settings", settings)
    app.router.add_post("/api/choose-dir", choose_dir)
    app.router.add_post("/api/start", start)
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
    if not streamer or not url or not save_dir:
        return web.json_response({"ok": False, "error": "streamer, url and saveDir are required"}, status=400)
    save_ui_settings({"streamer": streamer, "url": url, "saveDir": save_dir})

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
    if not re.fullmatch(r"[0-9]{8,20}", room):
        return web.json_response(
            {
                "ok": False,
                "error": "could not resolve a dycast room number from the Douyin URL",
            },
            status=400,
        )
    dycast_url = (
        "http://127.0.0.1:5173/"
        f"?auto=1&room={quote(room)}&relay={quote(relay_url)}"
    )
    config = build_runtime_config(streamer, url, save_path, dycast_dir)
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
    return web.json_response({"ok": True, "dycastUrl": dycast_url})


async def stop(request: web.Request) -> web.Response:
    state: UiState = request.app["state"]
    if state.task is not None and not state.task.done():
        state.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await state.task
    state.status = "stopped"
    state.message = "Stopped"
    return web.json_response({"ok": True})


async def run_pipeline_with_state(state: UiState, config: AppConfig, options: PipelineOptions) -> None:
    try:
        state.status = "recording"
        state.message = "Recording pipeline is running"
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


def build_runtime_config(streamer: str, url: str, save_dir: Path, dycast_dir: Path) -> AppConfig:
    return AppConfig(
        streamers=[StreamerConfig(name=streamer, url=url)],
        marker=MarkerConfig(
            keywords=["名场面", "来了", "抽奖"],
            output_json=str(save_dir / "markers.json"),
            output_csv=str(save_dir / "markers.csv"),
        ),
        biliup=BiliupConfig(
            enabled=True,
            command=".venv/bin/biliup",
            args=["server", "--bind", "127.0.0.1", "--port", "19159"],
            config_path=str(save_dir / "biliup.config.toml"),
            output_dir=str(save_dir / "recordings"),
        ),
        dycast=DycastConfig(
            enabled=True,
            command=["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
            cwd=str(dycast_dir),
            host="127.0.0.1",
            port=8765,
            events_output=str(save_dir / "events.jsonl"),
            streamer=streamer,
            skip_gift_repeats=True,
        ),
    )


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
    reflow = re.search(r"/douyin/webcast/reflow/([0-9]{8,20})", text)
    if reflow:
        return reflow.group(1)
    if re.fullmatch(r"[0-9]{8,20}", text):
        return text
    if "live.douyin.com/" in text:
        return text.rstrip("/").split("/")[-1].split("?")[0]
    if "v.douyin.com/" in text:
        request = Request(
            text,
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
        except HTTPError as exc:
            final_url = exc.url
        final = re.search(r"live\.douyin\.com/([0-9]{8,12})", final_url)
        if final:
            return final.group(1)
        final_reflow = re.search(r"/douyin/webcast/reflow/([0-9]{8,20})", final_url)
        if final_reflow:
            return final_reflow.group(1)
        return final_url.rstrip("/").split("/")[-1].split("?")[0]
    return text


def load_ui_settings() -> dict[str, str]:
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
    }


def save_ui_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def render_index(settings: dict[str, str]) -> str:
    return (
        INDEX_HTML.replace("__STREAMER__", html.escape(settings.get("streamer", ""), quote=True))
        .replace("__URL__", html.escape(settings.get("url", ""), quote=True))
        .replace("__SAVE_DIR__", html.escape(settings.get("saveDir", ""), quote=True))
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
        "starting": "正在启动 biliup、dycast 和高光标记器。",
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
    }


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>抖音直播录制高光标记</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f6f8; color: #1f2937; }
    .shell { max-width: 1120px; margin: 0 auto; padding: 28px; }
    h1 { font-size: 26px; margin: 0 0 20px; letter-spacing: 0; }
    .layout { display: grid; grid-template-columns: 360px 1fr; gap: 20px; align-items: start; }
    form, .panel { background: #fff; border: 1px solid #d7dde4; border-radius: 8px; padding: 18px; }
    label { display: block; font-size: 13px; color: #526070; margin: 14px 0 6px; }
    input { width: 100%; box-sizing: border-box; border: 1px solid #bac4cf; border-radius: 6px; padding: 10px 11px; font-size: 14px; }
    button { border: 0; border-radius: 6px; padding: 10px 14px; font-size: 14px; cursor: pointer; }
    .primary { background: #1769aa; color: #fff; }
    .secondary { background: #e8edf2; color: #26323f; }
    .actions, .path-row { display: flex; gap: 10px; }
    .path-row input { flex: 1; }
    .path-row button { flex-shrink: 0; }
    .actions { margin-top: 18px; }
    .status { background: #101820; color: #d7f8e3; padding: 12px; border-radius: 6px; min-height: 74px; }
    .status-title { display: flex; align-items: center; gap: 8px; font-weight: 700; }
    .status-dot { width: 9px; height: 9px; border-radius: 999px; background: #9aa7b1; display: inline-block; }
    .status-dot.recording { background: #2fb344; }
    .status-dot.starting { background: #f59f00; }
    .status-dot.stopped { background: #9aa7b1; }
    .status-dot.error { background: #e03131; }
    .status-detail { margin-top: 8px; font-size: 13px; line-height: 1.45; color: #c8d8ce; }
    iframe { width: 100%; height: 680px; border: 1px solid #d7dde4; border-radius: 8px; background: #fff; }
    .hint { font-size: 13px; color: #64748b; line-height: 1.5; }
  </style>
</head>
<body>
  <main class="shell">
    <h1>抖音直播录制高光标记</h1>
    <div class="layout">
      <form id="startForm">
        <label for="streamer">主播名字</label>
        <input id="streamer" name="streamer" value="__STREAMER__" autocomplete="off" required />
        <label for="url">直播 URL</label>
        <input id="url" name="url" value="__URL__" required />
        <label for="saveDir">保存到电脑的位置</label>
        <div class="path-row">
          <input id="saveDir" name="saveDir" value="__SAVE_DIR__" required />
          <button class="secondary" id="chooseDirBtn" type="button">选择位置</button>
        </div>
        <div class="actions">
          <button class="primary" type="submit">启动录制</button>
          <button class="secondary" id="stopBtn" type="button">停止</button>
        </div>
        <p class="hint">启动后会自动运行 biliup、dycast 和高光标记器。dycast 页面会自动带入房间和转发地址。</p>
        <div class="status" id="status">
          <div class="status-title"><span class="status-dot" id="statusDot"></span><span id="statusLabel">未启动</span></div>
          <div class="status-detail" id="statusDetail">还没有启动录制。填写信息后点击“启动录制”。</div>
        </div>
      </form>
      <section class="panel">
        <iframe id="dycastFrame" title="dycast"></iframe>
      </section>
    </div>
  </main>
  <script>
    const form = document.getElementById('startForm');
    const statusEl = document.getElementById('status');
    const statusDot = document.getElementById('statusDot');
    const statusLabel = document.getElementById('statusLabel');
    const statusDetail = document.getElementById('statusDetail');
    const frame = document.getElementById('dycastFrame');
    const streamerInput = document.getElementById('streamer');
    const urlInput = document.getElementById('url');
    const saveDirInput = document.getElementById('saveDir');
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
    function renderStatus(status, label, detail) {
      statusDot.className = `status-dot ${status || ''}`;
      statusLabel.textContent = label || '未知';
      statusDetail.textContent = detail || '';
    }
    document.getElementById('chooseDirBtn').addEventListener('click', async () => {
      renderStatus('starting', '选择保存位置', '正在打开系统文件夹选择窗口。');
      const { ok, body } = await requestJson('POST', '/api/choose-dir');
      if (!ok || !body.ok) {
        renderStatus('idle', '未启动', body.error || '已取消选择保存位置。');
        return;
      }
      saveDirInput.value = body.path;
      renderStatus('idle', '保存位置已选择', body.path);
    });
    form.addEventListener('submit', async ev => {
      ev.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      renderStatus('starting', '启动中', '正在启动 biliup、dycast 和高光标记器。');
      const { ok, body } = await requestJson('POST', '/api/start', data);
      if (!ok || !body.ok) {
        renderStatus('error', '出错', body.error || '启动失败。');
        return;
      }
      frame.src = body.dycastUrl;
      renderStatus('recording', '录制中', '录制流水线已启动。请确认右侧 dycast 页面已连接直播间。');
    });
    document.getElementById('stopBtn').addEventListener('click', async () => {
      await requestJson('POST', '/api/stop');
      renderStatus('stopped', '已停止', '录制流水线已停止。');
    });
    setInterval(async () => {
      const { ok, body } = await requestJson('GET', '/api/status');
      if (ok) renderStatus(body.status, body.label, body.detail || body.message);
    }, 1500);
  </script>
</body>
</html>
"""
