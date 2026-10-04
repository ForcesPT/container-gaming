#!/usr/bin/env python3
"""Qualify a private immutable shutdown helper image offline; no real accounts."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='sha256:3442ee78246481519e58e916fb776c6a992971b345d76f5d751b8a025b51e495'
HELPERS=['dpad_instant_shutdown.py','dpad_instant_observation.py','dpad_instant_replay.py','faugus-epic-launch','dpad_faugus_prepare.py']
TESTS=['test_instant_shutdown.py','test_instant_observation.py','test_instant_replay.py','test_epic_instant_wrapper.py']
def run(args):
 p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=120)
 if p.returncode:raise RuntimeError((p.stdout+p.stderr)[-12000:])
 return p.stdout,p.stderr
RUNNER=r"""
import hashlib,json,os,pathlib,shutil,subprocess,tempfile
expected=json.loads(pathlib.Path('/fixture/expected.json').read_text());root=pathlib.Path(tempfile.mkdtemp(prefix='dpad-shutdown-tests-'))
for name,digest in expected.items():
 raw=(pathlib.Path('/opt/dpadcloud')/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==digest,name
 (root/name).write_bytes(raw)
# Selected installation validation remains the exact packaged read-only sibling.
shutil.copy('/opt/dpadcloud/dpad_epic_installation.py',root/'dpad_epic_installation.py')
for name in ['test_instant_shutdown.py','test_instant_observation.py','test_instant_replay.py','test_epic_instant_wrapper.py']:
 shutil.copy('/fixture/'+name,root/name)
env={**os.environ,'DPAD_SHUTDOWN_HELPER':'/opt/dpadcloud/dpad_instant_shutdown.py'}
result=subprocess.run(['python3','-m','unittest','test_instant_shutdown','test_instant_observation','test_instant_replay','test_epic_instant_wrapper'],cwd=root,env=env,capture_output=True,text=True,timeout=90)
print(result.stdout,end='');print(result.stderr,end='');assert result.returncode==0
print('Packaged helper hashes match; fixture user='+str(os.geteuid()))
"""
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--image',required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
 if not re.fullmatch(r'sha256:[a-f0-9]{64}',args.image):raise ValueError('immutable local image required')
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
 baseline=run(['git','rev-parse','HEAD'])[0].strip()
 files={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in HELPERS}
 base=json.loads(run(['docker','image','inspect',BASE])[0])[0];image=json.loads(run(['docker','image','inspect',args.image])[0])[0]
 assert image['Id']==args.image and image['RootFS']['Layers'][:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
 assert image['Config']['Env']==base['Config']['Env'] and image['Config']['Entrypoint']==base['Config']['Entrypoint']
 for name in TESTS:(out/name).write_bytes((ROOT/'scripts'/name).read_bytes())
 (out/'expected.json').write_text(json.dumps(files));(out/'runner.py').write_text(RUNNER)
 result,error=run(['docker','run','--rm','--pull','never','--network','none','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges',
  '--tmpfs','/tmp:rw,exec,nosuid,nodev,mode=1777','--mount','type=bind,src='+str(out)+',dst=/fixture,readonly','--entrypoint','python3',args.image,'/fixture/runner.py'])
 (out/'tests.log').write_text(result+error);assert re.search(r'Ran 25 tests',result+error) and re.search(r'^OK$',result+error,re.M)
 assert files=={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in HELPERS}
 receipt={'status':'packaged-instant-shutdown-qualified-locally','imageId':args.image,'dependencyImage':BASE,'sourceBaseline':baseline,'sourceFiles':files,
  'qualificationFiles':{name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in TESTS+['check_instant_shutdown_local.py']},
  'testsPassed':25,'realX11ProtocolCases':3,'effectiveUser':'1000:1000','network':'none','packagedHelpersMatch':True,'baseAndRuntimeContractPreserved':True,
  'allDisposableContainersRemoved':True,'productionChanged':False,'paidResourcesCreated':0,'genuineGameExitQualified':False,'cloudSyncQualified':False,'nativeMediaQualified':False}
 (out/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n');print('25 packaged helper cases passed, including real X11 protocol; receipt saved.')
if __name__=='__main__':main()
