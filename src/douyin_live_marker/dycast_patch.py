from __future__ import annotations

from pathlib import Path


PATCH_MARKER = "// douyin-live-marker auto-connect patch"


def ensure_dycast_auto_connect(dycast_dir: str | Path) -> bool:
    view_path = Path(dycast_dir) / "src" / "views" / "IndexView.vue"
    if not view_path.exists():
        raise FileNotFoundError(f"dycast IndexView.vue not found: {view_path}")

    text = view_path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        return False

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
  if (room) connectLive();
  if (relay) {{
    const relayDelay = Number(params.get('relayDelay') || '2500');
    window.setTimeout(() => relayCast(), relayDelay);
  }}
}});
""".format(marker=PATCH_MARKER)
    if insert_after not in text:
        raise RuntimeError("could not locate dycast patch insertion point")
    text = text.replace(insert_after, insert_after + patch)
    view_path.write_text(text, encoding="utf-8")
    return True
