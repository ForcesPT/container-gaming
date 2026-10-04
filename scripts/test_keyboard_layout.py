"""Keyboard layout selector: safe state changes and rollback without a compositor."""

import importlib.machinery
import importlib.util
import os
import socket
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE = Path(os.environ.get('DPAD_TEST_KEYBOARD_SELECTOR',str(Path(__file__).with_name("dpad-keyboard-layout"))))
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

    def test_timeout_restores_saved_layout_and_removes_temporary_files(self):
        available = KEYBOARD.layouts()
        KEYBOARD.initialize()
        original = KEYBOARD.CONFIG.read_bytes()
        with mock.patch.object(KEYBOARD.subprocess, "run", side_effect=subprocess.TimeoutExpired('labwc', 5)):
            with self.assertRaises(subprocess.TimeoutExpired):
                KEYBOARD.apply("pt", available)
        self.assertEqual(KEYBOARD.CONFIG.read_bytes(), original)
        self.assertEqual(KEYBOARD.current(available), "us")
        self.assertEqual(list(KEYBOARD.CONFIG.parent.iterdir()), [KEYBOARD.CONFIG])

    def test_missing_compositor_does_not_leave_a_new_layout_saved(self):
        with mock.patch.object(KEYBOARD.subprocess, "run", side_effect=FileNotFoundError('labwc')):
            with self.assertRaises(FileNotFoundError):
                KEYBOARD.apply("pt", KEYBOARD.layouts())
        self.assertFalse(KEYBOARD.CONFIG.exists())
        self.assertEqual(list(KEYBOARD.CONFIG.parent.iterdir()), [])

    def sway_socket(self):
        path=Path(self.temp.name)/'sway.sock'
        connection=socket.socket(socket.AF_UNIX)
        connection.bind(str(path));path.chmod(0o600)
        self.addCleanup(connection.close)
        return path

    def test_sway_uses_owned_socket_and_checks_command_acknowledgement(self):
        path=self.sway_socket();available=KEYBOARD.layouts()
        with mock.patch.dict(os.environ,{'DPAD_DESKTOP_CLIENT':'sway','SWAYSOCK':str(path)}), \
                mock.patch.object(KEYBOARD.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'[{"success":true}]')) as run:
            KEYBOARD.apply('pt',available)
        self.assertEqual(KEYBOARD.current(available),'pt')
        self.assertEqual(run.call_args.args[0],['swaymsg','-s',str(path),'-t','command','input type:keyboard xkb_layout pt'])

    def test_sway_partial_or_ambiguous_failure_restores_state_and_reapplies_old_layout(self):
        path=self.sway_socket();available=KEYBOARD.layouts();KEYBOARD.initialize()
        for response in ['[{"success":false}]','[]','{"success":true}','[{"success":1}]','invalid']:
            with mock.patch.dict(os.environ,{'DPAD_DESKTOP_CLIENT':'sway','SWAYSOCK':str(path)}), \
                    mock.patch.object(KEYBOARD.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,response),
                        subprocess.CompletedProcess([],0,'[{"success":true}]')]) as run:
                with self.assertRaises((ValueError,RuntimeError)):KEYBOARD.apply('pt',available)
            self.assertEqual(KEYBOARD.current(available),'us')
            self.assertEqual(run.call_args.args[0][-1],'input type:keyboard xkb_layout us')
            self.assertEqual(run.call_count,2)

    def test_sway_redirected_or_non_socket_state_never_writes_or_reconfigures(self):
        available=KEYBOARD.layouts();socket_path=self.sway_socket()
        redirected=Path(self.temp.name)/'redirected.sock';redirected.symlink_to(socket_path)
        for path in [redirected,KEYBOARD.RULES]:
            with mock.patch.dict(os.environ,{'DPAD_DESKTOP_CLIENT':'sway','SWAYSOCK':str(path)}),mock.patch.object(KEYBOARD.subprocess,'run') as run:
                with self.assertRaises(ValueError):KEYBOARD.apply('pt',available)
                run.assert_not_called()
                self.assertFalse(KEYBOARD.CONFIG.exists())


if __name__ == "__main__":
    unittest.main()
