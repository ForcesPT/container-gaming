import ctypes as c
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest

path=Path(os.environ.get('DPAD_SHUTDOWN_HELPER',str(Path(__file__).with_name('dpad_instant_shutdown.py'))))
spec=importlib.util.spec_from_file_location('shutdown',path);shutdown=importlib.util.module_from_spec(spec);spec.loader.exec_module(shutdown)
observation=shutdown.sibling('dpad_instant_observation')

class Process:
    def __init__(self,prefix,pid=47,uid=None,created=None):self.prefix=prefix;self.pid=pid;self.uid=os.geteuid() if uid is None else uid;self.created=iter(created or [1,1])
    def name(self):return 'GameThread'
    def uids(self):return SimpleNamespace(effective=self.uid)
    def environ(self):return {'FAUGUSID':'dpad-epic','WINEPREFIX':str(self.prefix)}
    def cmdline(self):return ['C:/DpadPlay/Games/Artifact/bin/Game.exe','fixture-private-value']
    def create_time(self):return next(self.created)

class Desktop:
    def __init__(self,pids):self.pids=pids;self.sent=[]
    def windows(self):return list(self.pids)
    def pid(self,window):return self.pids[window]
    def request_close(self,window,pid,current):
        if not current():return False
        self.sent.append((window,pid));return True

class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.prefix=Path(self.tmp.name);self.prefix.chmod(0o700)
        self.binding={'app':'Artifact','executable':'bin/Game.exe'}
    def request(self,desktop,processes):
        inventory={process.pid:process for process in processes}
        return shutdown.request_exit(self.binding,self.prefix,observation,desktop,processes,lambda pid:inventory[pid])
    def test_only_exact_selected_private_process_window_receives_request(self):
        desktop=Desktop({11:47,12:48,13:49})
        self.assertTrue(self.request(desktop,[Process(self.prefix),Process(self.prefix,48,os.geteuid()+1)]));self.assertEqual(desktop.sent,[(11,47)])
    def test_missing_pid_does_not_fall_back_to_title_or_foreground_window(self):
        desktop=Desktop({11:None});self.assertFalse(self.request(desktop,[Process(self.prefix)]));self.assertEqual(desktop.sent,[])
    def test_reused_process_is_rechecked_before_request(self):
        desktop=Desktop({11:47});self.assertFalse(self.request(desktop,[Process(self.prefix,created=[1,2])]));self.assertEqual(desktop.sent,[])
    def test_other_prefix_and_game_never_receive_request(self):
        desktop=Desktop({11:47});process=Process(Path('/other/private/prefix'))
        self.assertFalse(self.request(desktop,[process]));self.assertEqual(desktop.sent,[])
    def test_unreadable_candidate_remains_unknown_without_process_kill(self):
        desktop=Desktop({11:47});process=Process(self.prefix)
        def unavailable():raise observation.psutil.AccessDenied(47)
        process.environ=unavailable;self.assertFalse(self.request(desktop,[process]));self.assertEqual(desktop.sent,[])

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(shutil.which('Xvfb'),'real X11 fixture requires installed Xvfb')
        self.server=subprocess.Popen(['Xvfb',':91','-screen','0','800x600x24','-nolisten','tcp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(self.server.wait);self.addCleanup(self.server.terminate)
        deadline=time.monotonic()+5
        while True:
            try:self.desktop=shutdown.X11(':91');break
            except ValueError:
                if time.monotonic()>=deadline:raise
                time.sleep(.05)
        self.addCleanup(self.desktop.close);x=self.desktop.x
        for name,result,args in [
            ('XCreateSimpleWindow',c.c_ulong,[c.c_void_p,c.c_ulong,c.c_int,c.c_int,c.c_uint,c.c_uint,c.c_uint,c.c_ulong,c.c_ulong]),
            ('XSetWMProtocols',c.c_int,[c.c_void_p,c.c_ulong,c.POINTER(c.c_ulong),c.c_int]),
            ('XChangeProperty',c.c_int,[c.c_void_p,c.c_ulong,c.c_ulong,c.c_ulong,c.c_int,c.c_int,c.POINTER(c.c_ubyte),c.c_int]),
            ('XPending',c.c_int,[c.c_void_p]),('XNextEvent',c.c_int,[c.c_void_p,c.POINTER(shutdown.Event)]),
            ('XSync',c.c_int,[c.c_void_p,c.c_int]),
        ]:
            fn=getattr(x,name);fn.restype=result;fn.argtypes=args
        self.root=x.XDefaultRootWindow(self.desktop.display)
    def window(self,pid,protocol=True):
        d=self.desktop;x=d.x;window=x.XCreateSimpleWindow(d.display,self.root,0,0,100,100,0,0,0)
        value=(c.c_ulong*1)(pid);x.XChangeProperty(d.display,window,d.pid_atom,d.cardinal,32,0,c.cast(value,c.POINTER(c.c_ubyte)),1)
        if protocol:x.XSetWMProtocols(d.display,window,(c.c_ulong*1)(d.delete),1)
        x.XSync(d.display,False);return window
    def test_real_x11_delivers_wm_delete_without_destroying_either_window(self):
        d=self.desktop;window=self.window(47);peer=self.window(48)
        self.assertTrue(d.request_close(window,47,lambda:True));d.x.XSync(d.display,False)
        event=shutdown.Event();self.assertGreater(d.x.XPending(d.display),0);d.x.XNextEvent(d.display,c.byref(event))
        self.assertEqual(event.client.type,33);self.assertEqual(event.client.message_type,d.protocols)
        self.assertEqual(event.client.data.longs[0],d.delete);self.assertEqual(event.client.window,window)
        self.assertIn(window,d.windows());self.assertIn(peer,d.windows())
    def test_pid_protocol_and_current_process_fences_send_no_event(self):
        d=self.desktop;window=self.window(47);unsupported=self.window(48,False)
        self.assertFalse(d.request_close(window,48,lambda:True));self.assertFalse(d.request_close(window,47,lambda:False))
        self.assertFalse(d.request_close(unsupported,48,lambda:True));d.x.XSync(d.display,False)
        self.assertEqual(d.x.XPending(d.display),0)
    def test_fresh_real_process_identity_and_x11_request_work_together(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);prefix=Path(temporary.name);prefix.chmod(0o700)
        env={**os.environ,'FAUGUSID':'dpad-epic','WINEPREFIX':str(prefix)}
        child=subprocess.Popen(['python3','-c','import ctypes,time;ctypes.CDLL(None).prctl(15,b"GameThread",0,0,0);time.sleep(30)',
            'C:/DpadPlay/Games/Artifact/bin/Game.exe'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait);self.addCleanup(child.terminate)
        deadline=time.monotonic()+5
        process=observation.psutil.Process(child.pid)
        while process.name()!='GameThread':
            self.assertLess(time.monotonic(),deadline);time.sleep(.02)
        window=self.window(child.pid)
        self.assertTrue(shutdown.request_exit({'app':'Artifact','executable':'bin/Game.exe'},prefix,observation,self.desktop,[process]))
        self.desktop.x.XSync(self.desktop.display,False);event=shutdown.Event()
        self.assertGreater(self.desktop.x.XPending(self.desktop.display),0);self.desktop.x.XNextEvent(self.desktop.display,c.byref(event))
        self.assertEqual(event.client.window,window);self.assertEqual(event.client.data.longs[0],self.desktop.delete)

if __name__=='__main__':unittest.main()
