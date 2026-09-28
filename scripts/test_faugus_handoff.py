"""The Epic-only Faugus handoff preserves a relaunched Windows client."""

import os
import subprocess
import sys
import time
import unittest

from dpad_epic_handoff import epic_process_running, wait_for_epic_exit


class Process:
    def __init__(self, name, marker):
        self._name = name
        self._marker = marker

    def name(self):
        return self._name

    def environ(self):
        return {"FAUGUSID": self._marker}


class EpicHandoffTests(unittest.TestCase):
    def test_only_managed_epic_windows_keep_runner_alive(self):
        self.assertTrue(epic_process_running([Process("EpicGamesLaunc", "dpad-epic")]))
        self.assertTrue(epic_process_running([Process("EpicGamesUpdat", "dpad-epic")]))
        self.assertFalse(epic_process_running([Process("EpicGamesLaunc", "another-game")]))
        self.assertFalse(epic_process_running([Process("wineserver", "dpad-epic")]))

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
