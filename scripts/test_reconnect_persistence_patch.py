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

    def test_entrypoint_removes_stale_wayland_sockets_before_each_selkies_process(self):
        entrypoint = (ROOT / "entrypoint.sh").read_text()
        helper = "_dpad_clean_wayland_sockets()"
        initial_cleanup_call = "\n    _dpad_clean_wayland_sockets\n"
        relaunch_cleanup_call = "\n            _dpad_clean_wayland_sockets\n"
        first_launch = 'as_user "$(build_selkies_cmd)" >>/tmp/selkies.log 2>&1 &'
        relaunch_warning = "selkies-gstreamer died — restarting compositor and desktop"

        self.assertIn(helper, entrypoint)
        helper_body = entrypoint[entrypoint.index(helper):entrypoint.index(helper) + 500]
        self.assertIn('"${XDG_RUNTIME_DIR}"/wayland-[0-9]*', helper_body)
        self.assertIn('/run/dpadcloud/sway-client.log', helper_body)
        self.assertIn('/run/dpadcloud/labwc-client.log', helper_body)

        self.assertEqual(entrypoint.count(initial_cleanup_call), 1)
        self.assertEqual(entrypoint.count(relaunch_cleanup_call), 1)
        first_cleanup = entrypoint.index(initial_cleanup_call, entrypoint.index("build_selkies_cmd()"))
        first_launch_index = entrypoint.index(first_launch)
        self.assertLess(first_cleanup, first_launch_index)

        relaunch_index = entrypoint.index(relaunch_warning)
        second_cleanup = entrypoint.index(relaunch_cleanup_call, relaunch_index)
        second_launch = entrypoint.index(first_launch, first_launch_index + 1)
        self.assertLess(second_cleanup, second_launch)

    def test_gpu_wait_retries_only_process_absence(self):
        gpu_test = (ROOT / "scripts" / "test_reconnect_persistence_gpu.py").read_text()
        self.assertIn("class ProcessNotReady", gpu_test)
        self.assertNotIn("def wait_sway", gpu_test)
        wait_start = gpu_test.index("def wait_process_identity")
        wait_end = gpu_test.index("\ndef ", wait_start + 1)
        wait_body = gpu_test[wait_start:wait_end]
        self.assertIn("except ProcessNotReady:", wait_body)
        self.assertNotIn("except AssertionError:", wait_body)


if __name__ == "__main__":
    unittest.main()
