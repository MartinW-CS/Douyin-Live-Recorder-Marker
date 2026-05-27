from __future__ import annotations

from pathlib import Path


PATCH_MARKER = "// douyin-live-marker auto-connect patch"


def ensure_dycast_auto_connect(dycast_dir: str | Path) -> bool:
    view_path = Path(dycast_dir) / "src" / "views" / "IndexView.vue"
    if not view_path.exists():
        raise FileNotFoundError(f"dycast IndexView.vue not found: {view_path}")

    text = view_path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        text = remove_existing_patch(text)

    text = text.replace(
        "import { ref, useTemplateRef } from 'vue';",
        "import { nextTick, onMounted, ref, useTemplateRef } from 'vue';",
    )
    insert_after = """const openFeedDialog = function () {
  fdVisible.value = true;
};
"""
    patch = """

{marker}
onMounted(async () => {{
  const params = new URLSearchParams(window.location.search);
  if (params.get('auto') !== '1') return;
  const room = params.get('room') || '';
  const relay = params.get('relay') || '';
  if (room) roomNum.value = room;
  if (relay) relayUrl.value = relay;
  await nextTick();
  if (relay) {{
    const relayDelay = Number(params.get('relayDelay') || '500');
    window.setTimeout(() => relayCast(), relayDelay);
  }}
  if (room) {{
    const roomDelay = Number(params.get('roomDelay') || '1500');
    window.setTimeout(() => connectLive(), roomDelay);
    const connectTimeout = Number(params.get('connectTimeout') || '20000');
    window.setTimeout(() => {{
      if (connectStatus.value === 0) {{
        addConsoleMessage('弹幕连接超时：视频录制可能仍在进行，但弹幕/礼物标记暂时不可用');
        SkMessage.warning('弹幕连接超时，视频录制不受影响');
        setRoomInputStatus(false);
      }}
    }}, connectTimeout);
  }}
}});
""".format(marker=PATCH_MARKER)
    if insert_after not in text:
        raise RuntimeError("could not locate dycast patch insertion point")
    text = text.replace(insert_after, insert_after + patch)
    view_path.write_text(text, encoding="utf-8")
    return True


def remove_existing_patch(text: str) -> str:
    start = text.find(PATCH_MARKER)
    if start < 0:
        return text
    mounted = text.find("onMounted(async () => {", start)
    if mounted < 0:
        return text
    end_marker = "});"
    end = text.find(end_marker, mounted)
    if end < 0:
        return text
    return text[:start].rstrip() + "\n" + text[end + len(end_marker) :].lstrip()
