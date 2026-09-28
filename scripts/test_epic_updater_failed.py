"""Bounded updater-log detection used by the Faugus canary retry."""
import os
from pathlib import Path
import tempfile
import time
import unittest

from dpad_epic_updater_failed import failed


class UpdaterFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.temp.name)
        self.logs = self.prefix / 'drive_c/users/steamuser/AppData/Local/EpicGamesLauncher/Saved/Logs'
        self.logs.mkdir(parents=True)
        self.started = time.time_ns()

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_service_failure_is_detected(self):
        (self.logs / 'EpicGamesUpdater-one.log').write_text(
            'Application finished with code 8 (StartServiceFailed)\n')
        self.assertTrue(failed(self.prefix, self.started))

    def test_prior_failure_does_not_reopen_normal_exit(self):
        path = self.logs / 'EpicGamesUpdater-one.log'
        path.write_text('Application finished with code 8 (StartServiceFailed)\n')
        os.utime(path, ns=(self.started - 5_000_000_000, self.started - 5_000_000_000))
        self.assertFalse(failed(self.prefix, self.started))

    def test_other_exit_and_symlink_are_ignored(self):
        (self.logs / 'EpicGamesUpdater-success.log').write_text(
            'Application finished with code 0 (Success)\n')
        target = self.prefix / 'untrusted.log'
        target.write_text('Application finished with code 8 (StartServiceFailed)\n')
        (self.logs / 'EpicGamesUpdater-link.log').symlink_to(target)
        self.assertFalse(failed(self.prefix, self.started))


if __name__ == '__main__':
    unittest.main()
