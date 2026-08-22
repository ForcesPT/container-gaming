#!/usr/bin/env python3
"""Behavioral tests for desktop config publication and IPC compatibility."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "scripts" / "dpad-publish-desktop-config"
COMPAT = ROOT / "scripts" / "swaymsg-desktop-compat"
TOGGLE = ROOT / "scripts" / "launcher-toggle"


class DesktopRuntimeHelpersTests(unittest.TestCase):
    def run_cmd(self, *args: str, env: dict[str, str] | None = None, check: bool = True):
        return subprocess.run(args, text=True, capture_output=True, env=env, check=check)

    def test_sway_config_is_published_as_a_complete_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            self.run_cmd(str(PUBLISHER), "sway", "/opt/dpadcloud/launcher-shell", "1920", "1080", env=env)
            config = Path(tmp, "sway.config")
            self.assertTrue(config.is_file())
            text = config.read_text()
            self.assertIn("output * mode --custom 1920x1080", text)
            self.assertIn("exec /opt/dpadcloud/launcher-shell", text)
            self.assertFalse(Path(tmp, "sway.config.tmp").exists())

    def test_labwc_config_and_autostart_are_published_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            self.run_cmd(str(PUBLISHER), "labwc", "/opt/dpadcloud/launcher-shell", "1920", "1080", env=env)
            current = Path(tmp, "labwc-current")
            self.assertTrue(current.is_symlink())
            config_dir = current.resolve()
            self.assertEqual(ET.parse(config_dir / "rc.xml").getroot().tag, "labwc_config")
            self.assertEqual((config_dir / "autostart").read_text(), "/opt/dpadcloud/launcher-shell &\n")
            self.assertFalse((config_dir / "rc.xml.tmp").exists())
            self.assertFalse((config_dir / "autostart.tmp").exists())

    def test_publication_failure_is_nonzero_and_does_not_publish(self):
        env = {**os.environ, "DPAD_RUNTIME_DIR": "/proc/dpadcloud-test-forbidden"}
        result = self.run_cmd(
            str(PUBLISHER), "labwc", "/opt/dpadcloud/launcher-shell", "1920", "1080",
            env=env, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(Path("/proc/dpadcloud-test-forbidden/labwc-current").exists())

    def test_atomic_rename_collision_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp, "sway.config")
            destination.mkdir()
            (destination / "sentinel").write_text("keep")
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            result = self.run_cmd(
                str(PUBLISHER), "sway", "/opt/dpadcloud/launcher-shell", "1920", "1080",
                env=env, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((destination / "sentinel").read_text(), "keep")
            self.assertFalse(Path(tmp, "sway.config.tmp").exists())

    def test_labwc_atomic_switch_collision_leaves_no_partial_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp, "labwc-current")
            current.mkdir()
            (current / "sentinel").write_text("keep")
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            result = self.run_cmd(
                str(PUBLISHER), "labwc", "/opt/dpadcloud/launcher-shell", "1920", "1080",
                env=env, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((current / "sentinel").read_text(), "keep")
            self.assertEqual(list(Path(tmp).glob("labwc.gen.*")), [])
            self.assertEqual(list(Path(tmp).glob("labwc-current.tmp.*")), [])

    def test_labwc_republication_switches_one_generation_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            self.run_cmd(str(PUBLISHER), "labwc", "/opt/dpadcloud/launcher-shell", "1920", "1080", env=env)
            current = Path(tmp, "labwc-current")
            first_target = os.readlink(current)
            self.run_cmd(str(PUBLISHER), "labwc", "/opt/dpadcloud/launcher-shell-v2", "1920", "1080", env=env)
            second_target = os.readlink(current)
            self.assertNotEqual(first_target, second_target)
            self.assertEqual((current.resolve() / "autostart").read_text(), "/opt/dpadcloud/launcher-shell-v2 &\n")
            self.assertFalse(Path(tmp, first_target).exists())

    def test_concurrent_labwc_publications_leave_a_live_complete_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            for iteration in range(10):
                processes = [
                    subprocess.Popen(
                        [str(PUBLISHER), "labwc", f"/opt/dpadcloud/launcher-shell-{iteration}-{index}", "1920", "1080"],
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                    )
                    for index in range(2)
                ]
                results = [process.communicate(timeout=10) for process in processes]
                self.assertEqual([process.returncode for process in processes], [0, 0], results)
                current = Path(tmp, "labwc-current")
                self.assertTrue(current.is_symlink())
                generation = current.resolve(strict=True)
                self.assertEqual(ET.parse(generation / "rc.xml").getroot().tag, "labwc_config")
                self.assertTrue((generation / "autostart").is_file())

    def test_invalid_desktop_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "DPAD_RUNTIME_DIR": tmp}
            result = self.run_cmd(str(PUBLISHER), "unknown", "shell", "1", "1", env=env, check=False)
            self.assertNotEqual(result.returncode, 0)

    def test_sway_mode_delegates_to_real_swaymsg(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "real.log")
            real = Path(tmp, "swaymsg")
            real.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
            real.chmod(0o755)
            env = {**os.environ, "DPAD_DESKTOP_CLIENT": "sway", "DPAD_REAL_SWAYMSG": str(real)}
            self.run_cmd(str(COMPAT), "-t", "get_tree", env=env)
            self.assertEqual(log.read_text().strip(), "-t get_tree")

    def test_labwc_get_tree_filters_launcher_and_reports_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp, "wlrctl")
            fake.write_text("#!/bin/sh\nif [ \"$*\" = 'toplevel list' ]; then\n  printf '%s\\n' 'com.dpadplay.launcher: DpadPlay' 'steam: Steam'\nfi\n")
            fake.chmod(0o755)
            env = {**os.environ, "DPAD_DESKTOP_CLIENT": "labwc", "DPAD_WLRCTL": str(fake), "XDG_RUNTIME_DIR": "/run/user/1000"}
            result = self.run_cmd(str(COMPAT), "-s", "/run/user/1000/sway-ipc.labwc-compat.sock", "-t", "get_tree", env=env)
            tree = json.loads(result.stdout)
            self.assertEqual([node["name"] for node in tree["nodes"]], ["Steam"])

    def test_labwc_translates_hide_restore_and_fullscreen(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "wlrctl.log")
            fake = Path(tmp, "wlrctl")
            fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
            fake.chmod(0o755)
            env = {**os.environ, "DPAD_DESKTOP_CLIENT": "labwc", "DPAD_WLRCTL": str(fake), "XDG_RUNTIME_DIR": "/run/user/1000"}
            marker = "/run/user/1000/sway-ipc.labwc-compat.sock"
            self.run_cmd(str(COMPAT), "-s", marker, "[title=DpadPlay]", "move", "container", "to", "scratchpad", env=env)
            self.run_cmd(str(COMPAT), "-s", marker, "scratchpad", "show", env=env)
            self.run_cmd(str(COMPAT), "-s", marker, "[title=DpadPlay]", "fullscreen", "enable", env=env)
            self.assertEqual(log.read_text().splitlines(), [
                "window minimize title:DpadPlay",
                "window focus title:DpadPlay",
                "window fullscreen title:DpadPlay",
            ])

    def test_labwc_rejects_extended_or_malformed_swaymsg_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "wlrctl.log")
            fake = Path(tmp, "wlrctl")
            fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
            fake.chmod(0o755)
            env = {**os.environ, "DPAD_DESKTOP_CLIENT": "labwc", "DPAD_WLRCTL": str(fake), "XDG_RUNTIME_DIR": "/run/user/1000"}
            marker = "/run/user/1000/sway-ipc.labwc-compat.sock"
            bad_commands = [
                ("-s", marker, "-t", "get_tree", "extra"),
                ("-s", marker, "bogus", "move", "container", "to", "scratchpad", "extra"),
                ("-s", marker, "[title=DpadPlay]", "fullscreen", "enable", "extra"),
                ("-s", "/wrong/marker.sock", "-t", "get_tree"),
                ("-t", "get_tree"),
            ]
            for args in bad_commands:
                result = self.run_cmd(str(COMPAT), *args, env=env, check=False)
                self.assertNotEqual(result.returncode, 0)
            self.assertFalse(log.exists())

    def test_launcher_toggle_focuses_existing_launcher_under_labwc(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "wlrctl.log")
            fake_wlrctl = Path(tmp, "wlrctl")
            fake_wlrctl.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n")
            fake_wlrctl.chmod(0o755)
            fake_pgrep = Path(tmp, "pgrep")
            fake_pgrep.write_text("#!/bin/sh\nexit 0\n")
            fake_pgrep.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{tmp}:{os.environ['PATH']}",
                "DPAD_DESKTOP_CLIENT": "labwc",
                "DPAD_WLRCTL": str(fake_wlrctl),
            }
            self.run_cmd("bash", str(TOGGLE), env=env)
            self.assertEqual(log.read_text().splitlines(), [
                "window focus title:DpadPlay",
                "window fullscreen title:DpadPlay",
            ])

    def test_launcher_toggle_uses_app_id_for_focus_and_fullscreen_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, "wlrctl.log")
            fake_wlrctl = Path(tmp, "wlrctl")
            fake_wlrctl.write_text(
                f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\n"
                "[ \"$*\" != 'window focus title:DpadPlay' ]\n"
            )
            fake_wlrctl.chmod(0o755)
            fake_pgrep = Path(tmp, "pgrep")
            fake_pgrep.write_text("#!/bin/sh\nexit 0\n")
            fake_pgrep.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{tmp}:{os.environ['PATH']}",
                "DPAD_DESKTOP_CLIENT": "labwc",
                "DPAD_WLRCTL": str(fake_wlrctl),
            }
            self.run_cmd("bash", str(TOGGLE), env=env)
            self.assertEqual(log.read_text().splitlines(), [
                "window focus title:DpadPlay",
                "window focus app_id:com.dpadplay.launcher",
                "window fullscreen app_id:com.dpadplay.launcher",
            ])


if __name__ == "__main__":
    unittest.main()
