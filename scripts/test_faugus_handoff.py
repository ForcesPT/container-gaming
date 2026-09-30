"""The Epic-only Faugus handoff preserves a relaunched Windows client."""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
import tempfile

from dpad_epic_handoff import epic_process_running, wait_for_epic_exit


class Process:
    def __init__(self, name, marker, prefix='', exe='', uid=None):
        self._name = name
        self._marker = marker
        self._prefix, self._exe = prefix, exe
        self._uid = os.geteuid() if uid is None else uid

    def uids(self):
        return SimpleNamespace(effective=self._uid)

    def name(self):
        return self._name

    def environ(self):
        return {"FAUGUSID": self._marker, 'WINEPREFIX': self._prefix}

    def cmdline(self):
        return [self._exe]


class EpicHandoffTests(unittest.TestCase):
    def test_only_managed_epic_windows_keep_runner_alive(self):
        self.assertTrue(epic_process_running([Process("EpicGamesLaunc", "dpad-epic")]))
        self.assertTrue(epic_process_running([Process("EpicGamesUpdat", "dpad-epic")]))
        self.assertFalse(epic_process_running([Process("EpicGamesLaunc", "another-game")]))
        self.assertFalse(epic_process_running([Process("wineserver", "dpad-epic")]))
        self.assertFalse(epic_process_running([Process("EpicGamesLaunc", "dpad-epic", uid=os.geteuid() + 1)]))

    def test_renamed_client_is_preserved_but_game_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'epic-games'
            prefix.mkdir(mode=0o700)
            (prefix / 'pfx').symlink_to(prefix, target_is_directory=True)
            executable = str(prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe')
            process = Process('GameThread', 'dpad-epic', str(prefix / 'pfx') + '/', executable)
            self.assertTrue(epic_process_running([process]))
            process._exe = '/game/ABZU.exe'
            self.assertFalse(epic_process_running([process]))

    def test_relaunch_resets_quiet_period_before_cleanup(self):
        now = [0]
        done_at = []

        def active():
            return now[0] in (0, 1, 5, 6)

        wait_for_epic_exit(
            lambda: done_at.append(now[0]), quiet_seconds=3, interval=1,
            active=active, clock=lambda: now[0], sleep=lambda amount: now.__setitem__(0, now[0] + amount),
        )
        self.assertEqual(done_at, [10])

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux /proc")
    def test_real_marked_linux_process_is_visible(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import ctypes,time; ctypes.CDLL(None).prctl(15,b'EpicGamesLaunc',0,0,0); time.sleep(3)"],
            env={**os.environ, "FAUGUSID": "dpad-epic"},
        )
        try:
            for _ in range(20):
                if epic_process_running():
                    break
                time.sleep(0.05)
            else:
                self.fail("Faugus did not find the marked Epic handoff process")
        finally:
            process.terminate()
            process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
