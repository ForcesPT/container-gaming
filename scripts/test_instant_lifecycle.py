import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
import dpad_instant_lifecycle as lifecycle

SESSION='11111111-1111-4111-8111-111111111111'
RELEASE='22222222-2222-4222-8222-222222222222'

class LifecycleTests(unittest.TestCase):
    def test_cleanup_is_exact_and_does_not_call_unsafe_slot_stop(self):
        engine=Mock()
        engine.list_containers.side_effect=[[dict(Id='a'*64,Names=['/dpad-slot-0'])],[]]
        engine.inspect.return_value=dict(Id='a'*64,Config={'Labels':{'dpad.instant.session':SESSION,'dpad.instant.release':RELEASE}},Mounts=[])
        lifecycle.cleanup(engine,SESSION,RELEASE,0)
        engine.remove.assert_called_once_with('a'*64)
    def test_mismatched_owner_and_failed_removal_do_not_confirm_cleanup(self):
        engine=Mock()
        engine.list_containers.return_value=[dict(Id='a'*64,Names=['/dpad-slot-0'])]
        engine.inspect.return_value=dict(Id='a'*64,Config={'Labels':{'dpad.instant.session':'other','dpad.instant.release':RELEASE}},Mounts=[])
        with self.assertRaises(ValueError): lifecycle.cleanup(engine,SESSION,RELEASE,0)
        engine.remove.assert_not_called()
        engine.inspect.return_value['Config']['Labels']['dpad.instant.session']=SESSION
        with self.assertRaises(ValueError): lifecycle.cleanup(engine,SESSION,RELEASE,0)
    def test_engine_failure_is_not_absence_and_named_volumes_are_not_deleted(self):
        engine=Mock()
        engine.list_containers.side_effect=RuntimeError('daemon unavailable')
        with self.assertRaises(RuntimeError): lifecycle.cleanup(engine,SESSION,RELEASE,0)
        engine.list_containers.side_effect=None
        engine.list_containers.return_value=[dict(Id='a'*64,Names=['/dpad-slot-0'])]
        engine.inspect.return_value=dict(Id='a'*64,Config={'Labels':{'dpad.instant.session':SESSION,'dpad.instant.release':RELEASE}},Mounts=[{'Type':'volume','Name':'customer-library'}])
        with self.assertRaises(ValueError): lifecycle.cleanup(engine,SESSION,RELEASE,0)
        engine.remove.assert_not_called()

    def test_readiness_requires_registration_success_and_exact_launcher_process(self):
        engine=Mock()
        engine.inspect.return_value={'Id':'a'*64,'State':{'Running':True},'Config':{'Labels':{'dpad.instant.session':SESSION,'dpad.instant.release':RELEASE}}}
        lifecycle.check_ready(engine,SESSION,RELEASE,0)
        command=engine.command.call_args.args[-1]
        self.assertIn('^DPAD_INSTANT_INSTALLATION ',command)
        self.assertIn('pgrep -x dpad-launcher',command)
        self.assertNotIn('pgrep -f',command)
        engine.inspect.return_value['State']['Running']=False
        with self.assertRaises(ValueError): lifecycle.check_ready(engine,SESSION,RELEASE,0)

    def test_launch_and_cleanup_cli_share_the_slot_fence(self):
        import subprocess,sys,json,base64,time
        helper=Path(lifecycle.__file__).resolve()
        request=dict(sessionId=SESSION,releaseId=RELEASE,slot=0,expiresAt=int(time.time())+120,image='forcespt/dpadcloud-gaming@sha256:'+'a'*64)
        encoded=base64.b64encode(json.dumps(request).encode()).decode()
        with tempfile.TemporaryDirectory() as tmp:
            docker=Path(tmp)/'docker'; launcher=Path(tmp)/'launcher'
            record=dict(Id='a'*64,Name='/dpad-slot-0',Config={'Labels':{'dpad.instant.session':SESSION,'dpad.instant.release':RELEASE}},Mounts=[],State={'Running':True})
            docker.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\np=Path("/run/engine")\na=sys.argv[1]\nif a=="ps": print("a"*64 if p.exists() else "")\nelif a=="inspect": print('+repr(json.dumps([record]))+')\nelif a=="rm": p.unlink()\nelif a!="exec": sys.exit(1)\n');docker.chmod(0o755)
            launcher.write_text('#!'+sys.executable+'\nfrom pathlib import Path\nPath("/run/engine").touch()\n');launcher.chmod(0o755)
            script='import subprocess,json; from pathlib import Path; helper='+repr(str(helper))+'; request='+repr(encoded)+'; python='+repr(sys.executable)+'; subprocess.run([python,"-I",helper,"launch",request,"fixture-password","1920","1080","60"],check=True); subprocess.run([python,"-I",helper,"cleanup",'+repr(SESSION)+','+repr(RELEASE)+',"0"],check=True); assert not Path("/run/dpad-instant/requests/'+SESSION+'.json").exists()'
            cmd=['bwrap','--unshare-user','--uid','0','--gid','0','--tmpfs','/','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--ro-bind','/home','/home','--ro-bind','/etc','/etc','--proc','/proc','--dev','/dev','--dir','/run','--ro-bind',str(helper.parent),str(helper.parent),'--tmpfs','/usr/bin','--tmpfs','/usr/local/bin','--ro-bind',str(docker),'/usr/bin/docker','--ro-bind',str(launcher),'/usr/local/bin/dpad-launch-session',sys.executable,'-c',script]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('runtime_ready',result.stdout)

    def test_root_cli_cleanup_in_isolated_namespace_and_unprivileged_refusal(self):
        import subprocess,sys
        helper=Path(lifecycle.__file__).resolve()
        args=['cleanup',SESSION,RELEASE,'0']
        denied=subprocess.run([sys.executable,'-I',str(helper),*args],capture_output=True,text=True)
        self.assertNotEqual(denied.returncode,0)
        with tempfile.TemporaryDirectory() as tmp:
            docker=Path(tmp)/'docker'
            docker.write_text('#!'+sys.executable+'\nimport sys\nsys.exit(0 if sys.argv[1]=="ps" else 1)\n');docker.chmod(0o755)
            cmd=['bwrap','--unshare-user','--uid','0','--gid','0','--tmpfs','/','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--ro-bind','/home','/home','--ro-bind','/etc','/etc','--proc','/proc','--dev','/dev','--dir','/run','--ro-bind',str(helper.parent),str(helper.parent),'--tmpfs','/usr/bin','--ro-bind',str(docker),'/usr/bin/docker',sys.executable,'-I',str(helper),*args]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('cleanup_confirmed',result.stdout)

    def test_expired_host_deadline_never_starts_an_engine_command(self):
        run=Mock()
        with self.assertRaises(TimeoutError): lifecycle.Engine(run,deadline=0).list_containers()
        run.assert_not_called()

    def test_engine_adapter_checks_exit_and_parses_exact_id_inspection(self):
        from types import SimpleNamespace
        calls=[]
        def run(args, **kwargs):
            calls.append(args)
            if args[1:3]==['ps','-aq']: return SimpleNamespace(stdout='a'*64+'\n')
            if args[1]=='inspect': return SimpleNamespace(stdout='[{"Id":"'+('a'*64)+'","Name":"/dpad-slot-0","Config":{"Labels":{}}}]')
            return SimpleNamespace(stdout='')
        engine=lifecycle.Engine(run)
        self.assertEqual(engine.list_containers()[0]['Names'],['/dpad-slot-0'])
        engine.remove('a'*64)
        self.assertEqual(calls[-1],['/usr/bin/docker','rm','-f','-v','a'*64])

    def test_trusted_request_is_private_idempotent_and_never_overwritten(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'request.json'
            request={'sessionId':SESSION,'releaseId':RELEASE,'slot':0}
            lifecycle.write_request(path,request)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            lifecycle.write_request(path,request)
            with self.assertRaises(ValueError): lifecycle.write_request(path,{**request,'releaseId':SESSION})
            self.assertEqual(json.loads(path.read_text()),request)
            path.unlink(); path.symlink_to(Path(tmp)/'elsewhere')
            with self.assertRaises((ValueError,OSError)): lifecycle.write_request(path,request)

if __name__=='__main__':unittest.main()
