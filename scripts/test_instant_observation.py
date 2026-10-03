import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('observation', Path(__file__).with_name('dpad_instant_observation.py'))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class Process:
    def __init__(self, prefix, exe='C:\\DpadPlay\\Games\\Artifact\\bin\\Game.exe', uid=None, marker='dpad-epic', name='GameThread'):
        self.prefix, self.exe, self.marker, self.process_name = str(prefix), exe, marker, name
        self.uid = os.geteuid() if uid is None else uid
    def uids(self): return SimpleNamespace(effective=self.uid)
    def name(self): return self.process_name
    def environ(self): return {'FAUGUSID': self.marker, 'WINEPREFIX': self.prefix}
    def cmdline(self): return [self.exe, 'synthetic-private-argument-never-exported']


class ObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prefix = self.root / 'prefix'; self.prefix.mkdir(mode=0o700)
        self.binding = {'app': 'Artifact', 'executable': 'bin/Game.exe', 'version': 'installed-1'}

    def test_exact_windows_unix_and_overlay_paths(self):
        for exe in ('C:\\DpadPlay\\Games\\Artifact\\bin\\Game.exe',
                    str(self.prefix / 'drive_c/DpadPlay/Games/Artifact/bin/Game.exe'),
                    '/opt/dpad-instant/official-game/bin/Game.exe'):
            self.assertTrue(observer.selected_game_running(self.binding, self.prefix, [Process(self.prefix, exe)]))

    def test_client_other_game_prefix_user_and_marker_are_not_selected(self):
        for process in (Process(self.prefix, 'C:\\Program Files\\EpicGamesLauncher.exe'),
                        Process(self.prefix, 'C:\\DpadPlay\\Games\\Other\\bin\\Game.exe'),
                        Process(self.root / 'other'), Process(self.prefix, uid=os.geteuid()+1),
                        Process(self.prefix, marker='another-session')):
            self.assertFalse(observer.selected_game_running(self.binding, self.prefix, [process]))

    def test_safe_umu_alias_and_truncated_wine_name(self):
        (self.prefix / 'pfx').symlink_to(self.prefix, target_is_directory=True)
        self.assertTrue(observer.selected_game_running(self.binding, self.prefix, [Process(str(self.prefix / 'pfx')+'/',name='game.exe')]))
        (self.prefix / 'pfx').unlink(); (self.prefix / 'pfx').symlink_to(self.root)
        self.assertFalse(observer.selected_game_running(self.binding, self.prefix, [Process(self.prefix / 'pfx')]))

    def test_unreadable_candidate_is_unknown(self):
        process = Process(self.prefix)
        def denied(): raise observer.psutil.AccessDenied(42)
        process.environ = denied
        self.assertIsNone(observer.selected_game_running(self.binding, self.prefix, [process]))

    def test_real_proc_observation_and_process_exit(self):
        # Real Linux /proc/UID/environment interface, with a disposable process
        # double. This is not Wine/gameplay or native GPU qualification.
        code = "import ctypes,sys;ctypes.CDLL(None).prctl(15,b'GameThread',0,0,0);print('ready',flush=True);sys.stdin.read()"
        child = subprocess.Popen([sys.executable, '-c', code, 'C:\\DpadPlay\\Games\\Artifact\\bin\\Game.exe'],
            env={**os.environ,'WINEPREFIX':str(self.prefix),'FAUGUSID':'dpad-epic'},
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            self.assertTrue(observer.selected_game_running(self.binding,self.prefix,[observer.psutil.Process(child.pid)]))
        finally:
            child.communicate(timeout=5)
        self.assertFalse(observer.selected_game_running(self.binding,self.prefix,[]))

    def test_prefix_redirects_and_unsafe_executable_fail(self):
        alias = self.root / 'alias'; alias.symlink_to(self.prefix)
        with self.assertRaises(ValueError): observer.selected_game_running(self.binding, alias, [])
        with self.assertRaises(ValueError): observer.selected_game_running({**self.binding,'executable':'../Game.exe'},self.prefix,[])

    def test_selected_update_record_exports_only_a_boolean(self):
        path = self.prefix / 'drive_c/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/Guid.item'
        path.parent.mkdir(parents=True)
        capsule = {'item': {'InstallationGuid': 'Guid'}}
        for version, expected in [('installed-1',False),('available-2',True),('bad\nprivate',None)]:
            path.write_text(json.dumps({'AppName':'Artifact','AppVersionString':version,'AccountId':'synthetic-not-exported'}))
            path.chmod(0o600)
            self.assertIs(observer.selected_update_hint(self.binding,self.prefix,capsule),expected)
        path.unlink(); path.symlink_to(self.root / 'private')
        self.assertIsNone(observer.selected_update_hint(self.binding,self.prefix,capsule))

    def test_exit_needs_seen_game_and_continuous_quiet_period(self):
        state = observer.GameState()
        self.assertEqual(state.observe(False,1000),'waiting')
        self.assertEqual(state.observe(True,1001),'running')
        self.assertEqual(state.observe(False,1002),'running')
        self.assertEqual(state.observe(None,1017),'unknown')
        self.assertEqual(state.observe(False,1018),'unknown')
        self.assertEqual(state.observe(False,1033),'exited')
        self.assertEqual(state.observe(True,1034),'running')
        self.assertEqual(state.cycle,2)
        state.observe(False,1035);state.observe(False,1050);state.observe(None,1051);state.observe(True,1052)
        self.assertEqual(state.cycle,3,'a lost sample after exit must not merge two play cycles')

if __name__ == '__main__': unittest.main()
