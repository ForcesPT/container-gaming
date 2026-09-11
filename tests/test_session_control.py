"""Local behavioral tests: real guest process; Docker/mounts are explicit shims."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get('DPAD_SESSION_CONTROL_SCRIPT', ROOT / 'scripts/dpad-session-control'))
OLD = str(uuid.UUID(int=1))
NEW = str(uuid.UUID(int=2))
CID = 'a' * 64

SHIM = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['FIXTURE']); name=Path(sys.argv[0]).name; args=sys.argv[1:]
s=json.loads((p/'native.json').read_text())
def save(): (p/'native.json').write_text(json.dumps(s))
if name=='docker':
 if args[0]=='ps':
  if s['present']: print('dpad-slot-0')
 elif args[:2]==['container','ls']:
  if s.get('unavailable'): sys.exit(1)
  if s['present']: print(s['id'])
 elif args[0]=='inspect':
  if not s['present']: sys.exit(1)
  if '--format' in args:
   print('/mnt/dpad-vol/fixture' if s['mounted'] else '')
  else: print(json.dumps([{'Id':s['id'],'Name':'/dpad-slot-0','Config':{'Labels':{'com.dpadplay.session':s['session']}},'Mounts':([{'Destination':'/mnt/dpad-library','Source':'/mnt/dpad-vol/fixture'}] if s['mounted'] else [])}]))
 elif args[0]=='rm':
  s['removed'].append(args[-1]); save()
  if s.get('refused'): sys.exit(1)
  s['present']=False; save()
 elif args[0]=='logs': print('DPAD_READY local-fixture')
 elif args[0]=='run':
  s['present']=True; s['session']=args[args.index('--label')+1].split('=',1)[1]; save()
 else: sys.exit(2)
elif name=='findmnt':
 print(json.dumps({'filesystems':[{'target':'/'}]+([{'target':'/mnt/dpad-vol/fixture'}] if s['mounted'] else [])}))
elif name=='umount':
 if s.get('gate_unmount'):
  import time
  (p/'unmount-started').touch()
  while not (p/'allow-unmount').exists(): time.sleep(0.01)
 if s.get('busy'): sys.exit(1)
 s['mounted']=False; save(); (p/'unmount-finished').touch()
elif name=='rmdir': pass
else: sys.exit(2)
'''

class SessionControl(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name); self.state=self.path/'state'; self.state.mkdir(mode=0o700)
  self.env={**os.environ,'FIXTURE':str(self.path),'DPAD_SESSION_STATE_DIR':str(self.state),'PATH':str(self.path)+':'+os.environ['PATH']}
  for name in ['docker','findmnt','umount','rmdir']:
   file=self.path/name; file.write_text(SHIM); file.chmod(0o700)
  entry=self.path/'dpad-launch-session'; entry.write_text(SCRIPT.read_text()); entry.chmod(0o700)
  self.write_native(session=OLD)
 def write_native(self,**changes):
  value=dict(id=CID,present=True,session=OLD,mounted=False,removed=[]); value.update(changes)
  (self.path/'native.json').write_text(json.dumps(value))
 def native(self): return json.loads((self.path/'native.json').read_text())
 def record(self,session=OLD,mount=None):
  (self.state/f'{session}.json').write_text(json.dumps({'session':session,'slot':0,'mount':mount,'phase':'active'}))
 def run_control(self,*args):
  if args[0] == 'stop' and self.env.get('DPAD_SESSION_STOP_COMMAND'):
   return subprocess.run(['/bin/bash','-c',self.env['DPAD_SESSION_STOP_COMMAND']],env=self.env,capture_output=True,text=True,timeout=10)
  interpreter = '/bin/bash' if SCRIPT.name == 'dpad-launch-session' else 'python3'
  return subprocess.run([interpreter,str(SCRIPT),*args],env=self.env,capture_output=True,text=True,timeout=10)
 def test_legacy_commands_without_session_identity_are_rejected(self):
  for args in [('stop','0'),('launch','0','none','none','fixture-password','fixture-image')]:
   result=subprocess.run(['python3',str(SCRIPT),*args],env=self.env,capture_output=True,text=True,timeout=10)
   self.assertNotEqual(result.returncode,0)
   self.assertTrue(self.native()['present'])
   self.assertEqual(self.native()['removed'],[])
 def test_unlabelled_legacy_container_cannot_be_certified(self):
  self.write_native(session=None)
  result=self.run_control('stop','0',OLD)
  self.assertNotEqual(result.returncode,0)
  self.assertTrue(self.native()['present'])
  self.assertEqual(self.native()['removed'],[])
 def test_delayed_stop_does_not_delete_replacement(self):
  self.record(); self.write_native(session=NEW)
  self.run_control('stop','0',OLD)
  self.assertTrue(self.native()['present'],'stale stop removed successor container')
  self.assertEqual(self.native()['removed'],[])
 def test_failed_removal_is_not_success(self):
  self.record(); self.write_native(refused=True)
  result=self.run_control('stop','0',OLD)
  self.assertNotEqual(result.returncode,0,'failed removal falsely acknowledged')
  self.assertTrue(self.native()['present'])
 def test_failed_unmount_is_not_success(self):
  self.record(mount='/mnt/dpad-vol/fixture'); self.write_native(mounted=True,busy=True)
  result=self.run_control('stop','0',OLD)
  self.assertNotEqual(result.returncode,0,'busy library falsely acknowledged')
  self.assertTrue(self.native()['mounted'])
 def test_exact_stop_uses_immutable_id(self):
  self.record()
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertEqual(self.native()['removed'],[CID])
 def test_cancel_before_launch_leaves_durable_tombstone(self):
  self.write_native(present=False)
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  marker=json.loads((self.state/f'{OLD}.json').read_text())
  self.assertEqual(marker['phase'],'stopped')
  result=self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD)
  self.assertNotEqual(result.returncode,0)
  self.assertFalse(self.native()['present'])
 def backend(self, gated=False):
  backend=self.path/'backend'
  backend.write_text('#!/bin/bash\nset -e\nprintf started > "$FIXTURE/backend-started"\n'+
   ('while [ ! -e "$FIXTURE/allow-launch" ]; do sleep 0.02; done\n' if gated else '')+
   'docker run -d --name dpad-slot-0 fixture-image\nprintf finished > "$FIXTURE/backend-finished"\n')
  self.env['DPAD_SESSION_BACKEND']=str(backend)
 def test_launch_labels_and_duplicate_cannot_replace(self):
  self.backend(); self.write_native(present=False)
  result=self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(self.native()['session'],OLD)
  self.assertNotEqual(self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD).returncode,0)
  self.assertEqual(self.native()['removed'],[])
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertEqual(self.native()['removed'],[CID])
 def test_actual_pinned_launcher_receives_session_label(self):
  # Execute the complete maintained Bash artifact, not the minimal gated backend.
  # Only ephemeral launch: all Docker actions still go to the local shim.
  self.env['DPAD_SESSION_BACKEND']=os.environ.get('DPAD_SESSION_BACKEND_FIXTURE',str(ROOT/'scripts/dpad-launch-session'))
  self.write_native(present=False)
  result=self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(self.native()['session'],OLD)
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
 def test_stopped_replay_cannot_touch_successor(self):
  self.record(); self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  self.write_native(session=NEW)
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertTrue(self.native()['present']); self.assertEqual(self.native()['removed'],[])
 def test_unmount_retry_keeps_obligation_after_container_is_gone(self):
  self.record(mount='/mnt/dpad-vol/fixture'); self.write_native(mounted=True,busy=True)
  self.assertNotEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertFalse(self.native()['present'])
  state=self.native(); state['busy']=False; (self.path/'native.json').write_text(json.dumps(state))
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertFalse(self.native()['mounted'])
 def test_child_holds_execution_lock_after_controller_death(self):
  import fcntl
  import time
  self.backend(gated=True); self.write_native(present=False)
  launch=subprocess.Popen(['python3',str(SCRIPT),'launch','0','none','none','fixture-password','fixture-image',OLD],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  stop=None
  try:
   deadline=time.monotonic()+5
   while not (self.path/'backend-started').exists() and time.monotonic()<deadline: time.sleep(0.01)
   self.assertTrue((self.path/'backend-started').exists())
   launch.kill(); launch.wait(timeout=3)
   with (self.state/'execution.lock').open('r+') as stream:
    with self.assertRaises(BlockingIOError): fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
   stop=subprocess.Popen(['python3',str(SCRIPT),'stop','0',OLD],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   # The child still owns the real lock; releasing the fixture gate lets its
   # labeled launch finish BEFORE stop can inspect/remove that incarnation.
   (self.path/'allow-launch').touch()
   self.assertEqual(stop.wait(timeout=5),0)
   self.assertTrue((self.path/'backend-finished').exists())
   self.assertFalse(self.native()['present']); self.assertEqual(self.native()['removed'],[CID])
   self.assertEqual(json.loads((self.state/f'{OLD}.json').read_text())['phase'],'stopped')
  finally:
   (self.path/'allow-launch').touch()
   if launch.poll() is None: launch.terminate(); launch.wait(timeout=5)
   if stop is not None and stop.poll() is None: stop.terminate(); stop.wait(timeout=5)
 def test_unmount_holds_lock_after_controller_death(self):
  import fcntl
  import time
  self.record(mount='/mnt/dpad-vol/fixture'); self.write_native(mounted=True,gate_unmount=True)
  process=subprocess.Popen(['python3',str(SCRIPT),'stop','0',OLD],env=self.env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   deadline=time.monotonic()+5
   while not (self.path/'unmount-started').exists() and time.monotonic()<deadline: time.sleep(0.01)
   self.assertTrue((self.path/'unmount-started').exists())
   process.kill(); process.wait(timeout=3)
   with (self.state/'execution.lock').open('r+') as stream:
    with self.assertRaises(BlockingIOError): fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  finally:
   (self.path/'allow-unmount').touch()
   if process.poll() is None: process.terminate(); process.wait(timeout=5)
   deadline=time.monotonic()+5
   while not (self.path/'unmount-finished').exists() and time.monotonic()<deadline: time.sleep(0.01)
   self.assertTrue((self.path/'unmount-finished').exists())
 def test_unavailable_inventory_is_not_absence(self):
  self.record(); self.write_native(unavailable=True)
  self.assertNotEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertTrue(self.native()['present'])

if __name__=='__main__': unittest.main()
