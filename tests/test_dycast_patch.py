from pathlib import Path
import tempfile
import unittest

from douyin_live_marker.dycast_patch import PATCH_MARKER, ensure_dycast_auto_connect


BASE_VIEW = """<script setup lang="ts">
import { ref, useTemplateRef } from 'vue';

const openFeedDialog = function () {
  fdVisible.value = true;
};
</script>
"""


class DycastPatchTests(unittest.TestCase):
    def test_patch_connects_relay_before_room_and_adds_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            view_path = Path(tmp) / "src" / "views" / "IndexView.vue"
            view_path.parent.mkdir(parents=True)
            view_path.write_text(BASE_VIEW, encoding="utf-8")

            self.assertTrue(ensure_dycast_auto_connect(tmp))
            text = view_path.read_text(encoding="utf-8")

            self.assertIn(PATCH_MARKER, text)
            self.assertLess(text.index("relayCast()"), text.index("connectLive()"))
            self.assertIn("弹幕连接超时", text)

    def test_patch_replaces_existing_patch_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            view_path = Path(tmp) / "src" / "views" / "IndexView.vue"
            view_path.parent.mkdir(parents=True)
            view_path.write_text(BASE_VIEW, encoding="utf-8")

            ensure_dycast_auto_connect(tmp)
            ensure_dycast_auto_connect(tmp)
            text = view_path.read_text(encoding="utf-8")

            self.assertEqual(text.count(PATCH_MARKER), 1)
