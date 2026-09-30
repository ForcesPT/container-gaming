import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile

spec = importlib.util.spec_from_file_location('resume', Path(__file__).with_name('dpad_epic_resume.py'))
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)
PREFIX = '/private/prefixes/epic-games'
EXE = PREFIX + '/drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe'


class Process:
    def __init__(self, uid=None, name='EpicGamesLaun', prefix=PREFIX, marker='dpad-epic', exe=EXE, args=()):
        self.uid = os.geteuid() if uid is None else uid
        self.process_name, self.prefix, self.marker, self.exe = name, prefix, marker, exe
        self.args = args
    def uids(self): return SimpleNamespace(effective=self.uid)
    def name(self): return self.process_name
    def environ(self): return {'FAUGUSID': self.marker, 'WINEPREFIX': self.prefix}
    def cmdline(self): return [self.exe, *self.args]


class ResumeTests(unittest.TestCase):
    def test_exact_client(self):
        self.assertTrue(resume.managed_client_running(PREFIX, [Process()]))
    def test_windows_path(self):
        self.assertTrue(resume.managed_client_running(PREFIX, [Process(exe=r'C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe')]))
    def test_unreal_name_and_umu_prefix_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / 'epic-games'
            prefix.mkdir(mode=0o700)
            (prefix / 'pfx').symlink_to(prefix, target_is_directory=True)
            executable = str(prefix / 'drive_c/Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe')
            process = Process(name='GameThread', prefix=str(prefix / 'pfx') + '/', exe=executable)
            self.assertTrue(resume.managed_client_running(str(prefix), [process]))
            (prefix / 'pfx').unlink()
            (prefix / 'pfx').symlink_to(Path(temporary), target_is_directory=True)
            self.assertFalse(resume.managed_client_running(str(prefix), [process]))
    def test_updater_commandlet_and_umu_helpers_cannot_restore(self):
        for process in (Process(name='GameThread', args=('-Commandlet=selfupdateinstall',)),
                        Process(name='python3'), Process(name='pressure-vessel-wrap'),
                        Process(name='GameThread', exe='/game/ABZU.exe')):
            self.assertFalse(resume.managed_client_running(PREFIX, [process]))
    def test_other_session_user_updater_or_command_is_not_a_client(self):
        for process in (Process(uid=os.geteuid() + 1), Process(prefix='/other'),
                        Process(marker='other'), Process(name='EpicGamesUpda'),
                        Process(exe='/tmp/EpicGamesLauncher.exe')):
            self.assertFalse(resume.managed_client_running(PREFIX, [process]))
    def test_process_exit_race(self):
        process = Process()
        def gone(): raise resume.psutil.NoSuchProcess(42)
        process.environ = gone
        self.assertFalse(resume.managed_client_running(PREFIX, [process]))


if __name__ == '__main__': unittest.main()
