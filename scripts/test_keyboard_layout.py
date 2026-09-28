"""Keyboard layout selector: safe state changes and rollback without a compositor."""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).with_name("dpad-keyboard-layout")
LOADER = importlib.machinery.SourceFileLoader("dpad_keyboard_layout", str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
KEYBOARD = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(KEYBOARD)


class KeyboardLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("DPAD_TEST_TEMP_DIR"))
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        KEYBOARD.RULES = root / "evdev.lst"
        KEYBOARD.RULES.write_text(
            "! model\n pc105 Generic\n! layout\n us English (US)\n pt Portuguese (Portugal)\n br Portuguese (Brazil)\n"
        )
        KEYBOARD.CONFIG = root / "home/.config/dpadplay/keyboard.env"
        self.uid = mock.patch.object(KEYBOARD.os, "geteuid", return_value=os.geteuid() if hasattr(os, "geteuid") else 0, create=True)
        self.uid.start()
        self.addCleanup(self.uid.stop)
        self.desktop = mock.patch.dict(os.environ, {"DPAD_DESKTOP_CLIENT": "labwc", "LABWC_PID": "123"})
        self.desktop.start()
        self.addCleanup(self.desktop.stop)

    def test_searchable_layout_catalog_and_persistent_switch(self):
        available = KEYBOARD.layouts()
        self.assertEqual(available["pt"], "Portuguese (Portugal)")
        self.assertEqual(KEYBOARD.DISPLAY_NAMES["pt"], "Portuguese (Portugal)")
        KEYBOARD.initialize()
        self.assertEqual(KEYBOARD.current(available), "us")
        with mock.patch.object(KEYBOARD.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as reconfigure:
            KEYBOARD.apply("pt", available)
        self.assertEqual(KEYBOARD.current(available), "pt")
        self.assertEqual(KEYBOARD.CONFIG.read_text(), "XKB_DEFAULT_LAYOUT=pt\n")
        reconfigure.assert_called_once()
        self.assertEqual(reconfigure.call_args.args[0], ["labwc", "--reconfigure"])
        KEYBOARD.initialize()
        self.assertEqual(KEYBOARD.current(available), "pt")

    def test_reconfigure_failure_restores_previous_layout(self):
        available = KEYBOARD.layouts()
        KEYBOARD.initialize()
        with mock.patch.object(KEYBOARD.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, "refused"):
                KEYBOARD.apply("pt", available)
        self.assertEqual(KEYBOARD.current(available), "us")

    def test_symlink_and_unknown_layout_are_rejected(self):
        available = KEYBOARD.layouts()
        KEYBOARD.CONFIG.parent.mkdir(parents=True)
        target = Path(self.temp.name) / "target"
        target.write_text("sentinel")
        KEYBOARD.CONFIG.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "untrusted"):
            KEYBOARD.apply("pt", available)
        self.assertEqual(target.read_text(), "sentinel")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            KEYBOARD.apply("not-a-layout", available)


if __name__ == "__main__":
    unittest.main()
