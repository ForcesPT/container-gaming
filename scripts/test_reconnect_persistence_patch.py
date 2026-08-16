#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "patch_wayland_display_persistent.py"

PRISTINE_STOP = '''    fn stop(&self) -> Result<(), gst::ErrorMessage> {
        let mut state = self.state.lock().unwrap();
        if let Some(state) = state.take() {
            let subscriber = Registry::default().with(GstLayer);
            tracing::subscriber::with_default(subscriber, || drop(state.display));
        }
        Ok(())
    }
'''


class PersistentWaylandDisplayPatchTests(unittest.TestCase):
    def test_stop_keeps_compositor_alive_until_element_drop(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "imp.rs"
            target.write_text(PRISTINE_STOP)
            result = subprocess.run(
                ["python3", str(PATCHER), str(target)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            patched = target.read_text()
            self.assertIn("DPAD: preserve the compositor across WebRTC peer disconnects", patched)
            self.assertNotIn("state.take()", patched)
            self.assertIn("self.state.lock().unwrap()", patched)

    def test_docker_build_applies_patch_before_compiling_plugin(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        copy_line = "COPY scripts/patch_wayland_display_persistent.py /tmp/patch_wayland_display_persistent.py"
        apply_line = "python3 /tmp/patch_wayland_display_persistent.py /tmp/gwd/gst-plugin-wayland-display/src/waylandsrc/imp.rs"
        self.assertIn(copy_line, dockerfile)
        self.assertIn(apply_line, dockerfile)
        self.assertLess(dockerfile.index(apply_line), dockerfile.index("cargo cinstall"))

    def test_patch_rejects_unexpected_pinned_source(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "imp.rs"
            target.write_text("fn stop_changed_upstream() {}\n")
            result = subprocess.run(
                ["python3", str(PATCHER), str(target)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected pinned stop() source not found", result.stderr)

    def test_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "imp.rs"
            target.write_text(PRISTINE_STOP)
            first = subprocess.run(
                ["python3", str(PATCHER), str(target)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            once = target.read_text()
            second = subprocess.run(
                ["python3", str(PATCHER), str(target)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(target.read_text(), once)


if __name__ == "__main__":
    unittest.main()
