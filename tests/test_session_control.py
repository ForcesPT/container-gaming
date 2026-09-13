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
  else: print(json.dumps([{'Id':s['id'],'Name':'/dpad-slot-0','State':{'Running':s.get('running',True)},'Config':{'Labels':{'com.dpadplay.session':s['session']}},'Mounts':([{'Destination':'/mnt/dpad-library','Source':'/mnt/dpad-vol/fixture'}] if s['mounted'] else [])}]))
 elif args[0]=='rm':
  s['removed'].append(args[-1]); save()
  if s.get('refused'): sys.exit(1)
  s['present']=False; save()
 elif args[0]=='logs': print('DPAD_READY local-fixture')
 elif args[0]=='run':
  s['present']=True; s['args']=args; s['session']=args[args.index('--label')+1].split('=',1)[1]; save()
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
elif name=='systemctl':
 s.setdefault('unit_actions',[]).append(args); save()
 if args[0] in ('start','restart'): s['unit_active']=True; save()
 elif args[0]=='stop':
  if s.get('unit_stop_refused'): sys.exit(1)
  s['unit_active']=False; save()
 elif args[0]=='show': print('active' if s.get('unit_active') else 'inactive')
 else: sys.exit(2)
elif name=='rmdir': pass
else: sys.exit(2)
'''

class SessionControl(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name); self.state=self.path/'state'; self.state.mkdir(mode=0o700)
  self.env={**os.environ,'FIXTURE':str(self.path),'DPAD_SESSION_STATE_DIR':str(self.state),'PATH':str(self.path)+':'+os.environ['PATH']}
  for name in ['docker','findmnt','umount','rmdir','systemctl']:
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
 def test_tls_csr_keeps_one_private_host_key_outside_the_session_mount(self):
  self.record()
  path=self.state/f'{OLD}.json'; record=json.loads(path.read_text()); record['container']=CID; path.write_text(json.dumps(record))
  result=self.run_control('tls-csr','0',OLD)
  self.assertEqual(result.returncode,0,'the maintained controller must prepare a host-custodied CSR')
  response=json.loads(result.stdout)
  verified=subprocess.run(['openssl','req','-verify','-noout'],input=response['csr'],text=True,capture_output=True)
  self.assertEqual(verified.returncode,0)
  key=self.state/'guest-tls.key'
  self.assertEqual(key.stat().st_mode & 0o777,0o600)
  self.assertNotIn('PRIVATE KEY',result.stdout+result.stderr)
  replay=self.run_control('tls-csr','0',OLD)
  self.assertEqual(replay.returncode,0)
  self.assertEqual(json.loads(replay.stdout)['publicKey'],response['publicKey'])
  self.assertEqual(self.native()['removed'],[])
 def test_tls_install_validates_certificate_and_binds_session_configuration(self):
  import base64,hashlib
  self.record()
  path=self.state/f'{OLD}.json'; record=json.loads(path.read_text()); record['container']=CID; path.write_text(json.dumps(record))
  prepared=self.run_control('tls-csr','0',OLD); self.assertEqual(prepared.returncode,0)
  csr=json.loads(prepared.stdout); (self.path/'guest.csr').write_text(csr['csr'])
  name=f'{uuid.uuid4()}.{uuid.uuid4()}.{uuid.uuid4()}.guest.dpadplay.internal'
  def openssl(*args): return subprocess.run(['openssl',*args],cwd=self.path,check=True,capture_output=True)
  openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Local install fixture CA','-addext','basicConstraints=critical,CA:TRUE','-keyout','ca.key','-out','ca.pem')
  (self.path/'extensions').write_text(f'basicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:{name}\n')
  openssl('x509','-req','-in','guest.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial','1','-days','1','-extfile','extensions','-out','guest.pem')
  der=subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=csr['publicKey'].encode(),capture_output=True,check=True).stdout
  payload={'issuanceId':str(uuid.uuid4()),'serverName':name,'certificatePem':(self.path/'guest.pem').read_text(),'issuerCertificatePem':(self.path/'ca.pem').read_text(),'spkiSha256':base64.b64encode(hashlib.sha256(der).digest()).decode()}
  encoded=base64.b64encode(json.dumps(payload).encode()).decode()
  installed=self.run_control('tls-install','0',encoded,OLD)
  self.assertEqual(installed.returncode,0,'a verified issued leaf must install without exposing the host key')
  config_path=self.state/f'{OLD}.tls.json'; config=json.loads(config_path.read_text())
  self.assertEqual(config['sessionId'],OLD); self.assertEqual(config['containerId'],CID)
  self.assertEqual(config['unixSocket'],str(self.state/f'{OLD}.signal/stream.sock'))
  self.assertEqual(config['port'],16100); self.assertEqual(config['serverName'],name)
  self.assertEqual(config['key'],str(self.state/'guest-tls.key'))
  self.assertEqual(Path(config['cert']).read_text(),payload['certificatePem'])
  self.assertEqual(config_path.stat().st_mode & 0o777,0o600)
  self.assertEqual(self.run_control('tls-start','0',OLD).returncode,0)
  self.assertNotIn('PRIVATE KEY',installed.stdout+installed.stderr)
  original=config_path.read_text()
  for override in ({'spkiSha256':base64.b64encode(b'x'*32).decode()}, {'serverName':f'{uuid.uuid4()}.'+'.'.join(name.split('.')[1:])}, {'certificatePem':'not a certificate'}):
   bad=base64.b64encode(json.dumps({**payload,**override}).encode()).decode()
   self.assertNotEqual(self.run_control('tls-install','0',bad,OLD).returncode,0)
   self.assertEqual(config_path.read_text(),original,'failed validation must leave active configuration unchanged')
  openssl('x509','-req','-in','guest.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial','2','-days','1','-extfile','extensions','-out','renewed.pem')
  payload['issuanceId']=str(uuid.uuid4()); payload['certificatePem']=(self.path/'renewed.pem').read_text()
  encoded=base64.b64encode(json.dumps(payload).encode()).decode()
  self.assertEqual(self.run_control('tls-install','0',encoded,OLD).returncode,0)
  self.assertEqual(self.run_control('tls-start','0',OLD).returncode,0)
  self.assertIn(['restart',f'dpad-guest-tls@{OLD}.service'],self.native()['unit_actions'],'new certificates must actually replace the running TLS context')
  previous=self.native()['unit_actions'].count(['restart',f'dpad-guest-tls@{OLD}.service'])
  self.assertEqual(self.run_control('tls-start','0',OLD).returncode,0)
  self.assertEqual(self.native()['unit_actions'].count(['restart',f'dpad-guest-tls@{OLD}.service']),previous,'identical activation replay must not restart connections')

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
 def test_actual_launcher_gets_only_its_session_signaling_directory(self):
  self.env['DPAD_SESSION_BACKEND']=str(ROOT/'scripts/dpad-launch-session')
  self.write_native(present=False)
  result=self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD)
  self.assertEqual(result.returncode,0,result.stderr)
  args=self.native()['args']
  signal=self.state/(OLD+'.signal')
  self.assertIn('type=bind,src='+str(signal)+',dst=/run/dpad-signaling',args)
  self.assertIn('DPAD_SIGNAL_UNIX_SOCKET=/run/dpad-signaling/stream.sock',args)
  self.assertTrue(signal.is_dir())
  self.assertEqual(self.state.stat().st_mode & 0o777,0o700)
  self.assertFalse(any('guest.key' in arg or 'ca.key' in arg for arg in args))
 def tls_config(self,session=OLD,slot=0):
  config=dict(sessionId=session,containerId=CID,unixSocket=str(self.state/(session+'.signal')/'stream.sock'),port=16100+slot)
  path=self.state/(OLD+'.tls.json');path.write_text(json.dumps(config));path.chmod(0o600)
 def test_tls_start_rejects_other_session_configuration(self):
  self.backend(); self.write_native(present=False)
  self.assertEqual(self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD).returncode,0)
  self.tls_config(session=NEW)
  self.assertNotEqual(self.run_control('tls-start','0',OLD).returncode,0)
  self.assertEqual(self.native().get('unit_actions',[]),[])
 def test_tls_start_is_bound_to_exact_active_container(self):
  self.backend(); self.write_native(present=False)
  self.assertEqual(self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD).returncode,0)
  self.tls_config()
  result=self.run_control('tls-start','0',OLD)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(self.native()['unit_actions'][0],['start','dpad-guest-tls@'+OLD+'.service'])
  record=json.loads((self.state/(OLD+'.json')).read_text())
  self.assertEqual(record['gatewayUnit'],'dpad-guest-tls@'+OLD+'.service')
  self.assertEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertFalse(self.native()['unit_active'])
  self.assertNotEqual(self.run_control('tls-start','0',OLD).returncode,0)
 def test_tls_start_rejects_externally_stopped_container(self):
  self.backend(); self.write_native(present=False)
  self.assertEqual(self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD).returncode,0)
  self.write_native(running=False)
  self.assertNotEqual(self.run_control('tls-start','0',OLD).returncode,0)
  self.assertEqual(self.native().get('unit_actions',[]),[])
 def test_tls_stop_failure_preserves_cleanup_obligation(self):
  self.backend(); self.write_native(present=False)
  self.assertEqual(self.run_control('launch','0','none','none','fixture-password','fixture-image',OLD).returncode,0)
  self.tls_config()
  self.assertEqual(self.run_control('tls-start','0',OLD).returncode,0)
  native=self.native(); native['unit_stop_refused']=True
  (self.path/'native.json').write_text(json.dumps(native))
  self.assertNotEqual(self.run_control('stop','0',OLD).returncode,0)
  self.assertTrue(self.native()['present'])
  self.assertTrue(self.native()['unit_active'])
  record=json.loads((self.state/(OLD+'.json')).read_text())
  self.assertEqual(record['phase'],'stopping')
  self.assertIn('gatewayUnit',record)
 @unittest.skipUnless(os.environ.get('DPAD_TEST_USER_SYSTEMD') == '1', 'explicit local user-systemd acceptance')
 def test_real_user_systemd_gateway_start_and_stop(self):
  import base64,hashlib,socket,socketserver,ssl,threading,time
  session=str(uuid.uuid4()); unit='dpad-guest-tls@'+session+'.service'
  name=f'{uuid.uuid4()}.{uuid.uuid4()}.{uuid.uuid4()}.guest.dpadplay.internal'
  self.addCleanup(lambda: subprocess.run(['/usr/bin/systemctl','--user','stop',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
  self.backend(); self.write_native(present=False)
  self.assertEqual(self.run_control('launch','0','none','none','fixture-password','fixture-image',session).returncode,0)
  prepared=self.run_control('tls-csr','0',session);self.assertEqual(prepared.returncode,0)
  csr=json.loads(prepared.stdout);(self.path/'leaf.csr').write_text(csr['csr'])
  der=subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=csr['publicKey'].encode(),capture_output=True,check=True).stdout
  def openssl(*args):
   subprocess.run(['openssl',*args],cwd=self.path,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  openssl('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.pem','-days','1','-subj','/CN=Fixture','-addext','basicConstraints=critical,CA:TRUE')
  (self.path/'ext').write_text(f'basicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:{name}\n')
  openssl('x509','-req','-in','leaf.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial','1','-out','leaf.pem','-days','1','-extfile','ext')
  sock=str(self.state/(session+'.signal')/'stream.sock')
  class Backend(socketserver.BaseRequestHandler):
   def handle(self):
    self.request.recv(4096)
    self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
  server=socketserver.UnixStreamServer(sock,Backend)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  with socket.socket() as probe: probe.bind(('127.0.0.1',16100))
  cfg=self.state/(session+'.tls.json')
  def install(certificate):
   payload={'issuanceId':str(uuid.uuid4()),'serverName':name,'certificatePem':certificate,'issuerCertificatePem':(self.path/'ca.pem').read_text(),'spkiSha256':base64.b64encode(hashlib.sha256(der).digest()).decode()}
   result=self.run_control('tls-install','0',base64.b64encode(json.dumps(payload).encode()).decode(),session)
   self.assertEqual(result.returncode,0,result.stderr)
   config=json.loads(cfg.read_text());self.assertEqual(config['key'],str(self.state/'guest-tls.key'))
   # Test-only destination narrowing; never expose the fixture on public interfaces.
   config['host']='127.0.0.1';cfg.write_text(json.dumps(config));cfg.chmod(0o600)
  install((self.path/'leaf.pem').read_text())
  wrapper=self.path/'systemctl'
  wrapper.write_text('#!/usr/bin/env python3\nimport subprocess,sys\na=sys.argv[1:]\n'+
   'assert a[-1] == '+repr(unit)+'\n'+
   'if a[0] == "start":\n r=subprocess.run('+repr(['/usr/bin/systemd-run','--user','--quiet','--collect','--unit='+unit,'--property=Type=exec','--property=Restart=no','--property=KillMode=control-group','--property=UMask=0077','/usr/bin/python3',str(ROOT/'scripts/dpad-guest-tls'),str(cfg)])+')\n'+
   'else:\n r=subprocess.run(["/usr/bin/systemctl","--user",*a])\nsys.exit(r.returncode)\n')
  wrapper.chmod(0o700)
  context=ssl.create_default_context(cafile=str(self.path/'ca.pem'))
  def verify(certificate):
   deadline=time.monotonic()+5
   while True:
    try:
     with socket.create_connection(('127.0.0.1',16100),timeout=1) as raw:
      with context.wrap_socket(raw,server_hostname=name) as client:
       self.assertEqual(client.getpeercert(binary_form=True),ssl.PEM_cert_to_DER_cert(certificate))
       client.sendall(b'GET / HTTP/1.1\r\nHost: fixture\r\n\r\n')
       self.assertIn(b'200 OK',client.recv(4096))
     break
    except (ConnectionRefusedError,ConnectionResetError):
     if time.monotonic()>deadline: raise
     time.sleep(0.02)
  result=self.run_control('tls-start','0',session);self.assertEqual(result.returncode,0,result.stderr)
  verify((self.path/'leaf.pem').read_text())
  openssl('x509','-req','-in','leaf.csr','-CA','ca.pem','-CAkey','ca.key','-set_serial','2','-out','renewed.pem','-days','1','-extfile','ext')
  install((self.path/'renewed.pem').read_text())
  result=self.run_control('tls-start','0',session);self.assertEqual(result.returncode,0,result.stderr)
  verify((self.path/'renewed.pem').read_text())
  result=self.run_control('stop','0',session);self.assertEqual(result.returncode,0,result.stderr)
  self.assertFalse(self.native()['present'])
  with self.assertRaises(ConnectionRefusedError): socket.create_connection(('127.0.0.1',16100),timeout=1)
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
