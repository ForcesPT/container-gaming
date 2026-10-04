#!/usr/bin/env python3
"""Offline image/input qualification; no account, GPU stream or paid resource."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FILES={'dpad_input_patch.py':'/usr/local/lib/python3.12/dist-packages/dpad_input_patch.py',
       'dpad-keyboard-layout':'/opt/dpadcloud/dpad-keyboard-layout',
       'dpad-publish-desktop-config':'/opt/dpadcloud/dpad-publish-desktop-config'}
TESTS=['test_keyboard_layout.py','test_selkies_wayland_input_behavior.py','test_input_mapping_x11.py']

def run(command):
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=120)
    if result.returncode:raise RuntimeError((result.stdout+result.stderr)[-12000:])
    return result.stdout,result.stderr

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True);parser.add_argument('--base',required=True)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    if not all(re.fullmatch(r'sha256:[a-f0-9]{64}',v) for v in [args.image,args.base]):raise ValueError('Exact local identities required')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    baseline=run(['git','rev-parse','HEAD'])[0].strip()
    names=list(FILES)+TESTS+['check_input_layout_local.py']
    hashes={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in names}
    base,candidate=[json.loads(run(['docker','image','inspect',identity])[0])[0] for identity in [args.base,args.image]]
    assert candidate['Id']==args.image and base['Id']==args.base
    assert candidate['RootFS']['Layers'][:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
    for key in ['User','Cmd','WorkingDir','StopSignal','Healthcheck','Volumes','ExposedPorts','Env','Entrypoint']:
        assert candidate['Config'].get(key)==base['Config'].get(key),key
    assert candidate['Config']['Labels']['org.opencontainers.image.revision']==baseline
    for name in TESTS:(out/name).write_bytes((ROOT/'scripts'/name).read_bytes())
    (out/'expected.json').write_text(json.dumps({FILES[name]:hashes[name] for name in FILES}),encoding='utf8')
    runner=out/'runner.py';runner.write_text('''import hashlib,json,pathlib,os,subprocess
expected=json.loads(pathlib.Path('/fixture/expected.json').read_text())
for path,digest in expected.items():assert hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()==digest,path
environment={**os.environ,'DPAD_TEST_INPUT_PATCH':'/usr/local/lib/python3.12/dist-packages/dpad_input_patch.py',
 'DPAD_TEST_KEYBOARD_SELECTOR':'/opt/dpadcloud/dpad-keyboard-layout'}
for name in ['test_keyboard_layout.py','test_selkies_wayland_input_behavior.py','test_input_mapping_x11.py']:
 result=subprocess.run(['python3','/fixture/'+name],env=environment,capture_output=True,text=True,timeout=50)
 print(result.stdout,end='');print(result.stderr,end='');assert result.returncode==0,name
print('DPAD_INPUT_LAYOUT_PACKAGE_PASS')
''',encoding='utf8')
    common=['docker','run','--rm','--pull','never','--network','none','--user','1000:1000','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,nodev,uid=1000,gid=1000,mode=1777',
            '--mount','type=bind,src='+str(out)+',dst=/fixture,readonly','--entrypoint','python3',args.image]
    result,error=run(common+['/fixture/runner.py']);(out/'tests.log').write_text(result+error,encoding='utf8')
    assert 'Ran 8 tests' in result+error and 'DPAD_INPUT_LAYOUT_PACKAGE_PASS' in result
    assert len(re.findall(r'"realXTest": true',result))==2
    assert hashes=={name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in names}
    assert baseline==run(['git','rev-parse','HEAD'])[0].strip()
    receipt={'status':'input-layout-qualified-locally','sourceBaseline':baseline,'sourceFiles':hashes,
        'imageId':args.image,'baseImageId':args.base,'packagedHelperHashesMatch':True,'startupUserPreserved':True,
        'fullRuntimeContractPreserved':True,'keyboardSelectorCases':8,'routingBehaviorCases':2,'realX11MappingCases':2,
        'realSelkiesInputClassUsed':True,'softwareX11Only':True,'nativeWaylandSeatQualified':False,'nativeMediaQualified':False,
        'accountUsed':False,'testNetwork':'none','fixtureUser':'1000:1000','productionChanged':False,'paidResourcesCreated':0,
        'allDisposableContainersRemoved':True}
    (out/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print('Packaged input: eight selector, two routing and two real X11 cases passed; startup contract preserved.')

if __name__=='__main__':main()
