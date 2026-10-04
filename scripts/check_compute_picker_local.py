#!/usr/bin/env python3
"""Build/test a private cached Compute picker successor; never publish or start a VM."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='forcespt/dpadcloud-gaming:official-stores-ge117-canary-20261001-69d9f44'
BASE_ID='sha256:93fef1d0839b8b88c8f04dadc8abbf493746f9b44036535b626d97a782e62fe1'
FILES=['main.js','renderer.js','index.html','styles.css','store_lifecycle.cjs']
def run(args,**kwargs):
    p=subprocess.run(args,cwd=ROOT,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**kwargs)
    if p.returncode: raise RuntimeError(p.stdout[-12000:])
    return p.stdout
def image(tag): return json.loads(run(['docker','image','inspect',tag]))[0]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--adapter',default='dpadplay/picker-adapter:local-20261004');ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if not re.fullmatch(r'dpadplay/picker-adapter:[a-z0-9-]+',args.adapter):raise ValueError('local adapter tag required')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    baseline=run(['git','rev-parse','HEAD']).strip();before={f:sha(ROOT/'launcher/src'/f) for f in FILES}
    base=image(BASE);adapter=image(args.adapter)
    if base['Id']!=BASE_ID: raise ValueError('cached Compute identity mismatch')
    tag='dpadplay/compute:picker-local-20261004'
    (out/'build.log').write_text(run(['docker','build','--pull=false','--network','none','-f','Dockerfile.compute-picker',
      '--build-arg','COMPUTE_IMAGE='+BASE,'--build-arg','PICKER_BUILD_IMAGE='+args.adapter,
      '--build-arg','DPAD_SOURCE_REVISION='+baseline,'-t',tag,'.']))
    candidate=image(tag);iid=candidate['Id']
    if candidate['RootFS']['Layers'][:len(base['RootFS']['Layers'])]!=base['RootFS']['Layers']:raise ValueError('Compute base changed')
    if candidate['Config']['Env']!=base['Config']['Env'] or candidate['Config']['Entrypoint']!=base['Config']['Entrypoint']:raise ValueError('runtime contract changed')
    fixture=out/'package-check.cjs';fixture.write_text("""const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const expected=JSON.parse(process.env.DPAD_PICKER_EXPECTED),src='/opt/dpadcloud/launcher/resources/app.asar/src/';
for(const [name,hash] of Object.entries(expected))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(src+name)).digest('hex'),hash,name);
assert.equal(typeof require(src+'epic_reopen.cjs').reopenManagedEpic,'function');
require('/opt/dpadcloud/launcher/resources/app.asar/node_modules/koffi');
console.log(JSON.stringify({packagedSourcesMatch:true,epicReopenPreserved:true,nativeKoffiImported:true,uid:process.getuid()}));
""")
    common=['docker','run','--rm','--pull','never','--network','none','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges',
      '--tmpfs','/tmp:rw,nosuid,nodev,mode=1777','--mount','type=bind,src='+str(out)+',dst=/fixture,readonly',
      '--mount','type=bind,src='+str(ROOT/'scripts/test_picker_startup.cjs')+',dst=/fixture/test_picker_startup.cjs,readonly',
      '-e','ELECTRON_RUN_AS_NODE=1','-e','DPAD_PICKER_TEST_SOURCE=/opt/dpadcloud/launcher/resources/app.asar/src',
      '--entrypoint','/opt/dpadcloud/launcher/dpad-launcher']
    package=run(common[:-2]+['-e','DPAD_PICKER_EXPECTED='+json.dumps(before)]+common[-2:]+[iid,'/fixture/package-check.cjs'])
    (out/'package.log').write_text(package)
    result=run(common+[iid,'/fixture/test_picker_startup.cjs']);(out/'behavior.log').write_text(result)
    if not re.search(r'(?:#|ℹ) pass 8',result) or not re.search(r'(?:#|ℹ) fail 0',result):raise ValueError('behavior suite did not pass')
    if before!={f:sha(ROOT/'launcher/src'/f) for f in FILES} or baseline!=run(['git','rev-parse','HEAD']).strip():raise ValueError('source changed during checks')
    lock=run(['docker','run','--rm','--pull','never','--network','none','--entrypoint','sha256sum',adapter['Id'],'/work/package-lock.json']).split()[0]
    receipt={'status':'packaged-compute-picker-qualified-locally','sourceBaseline':baseline,'sourceFiles':before,'computeBase':BASE_ID,
      'adapterImage':adapter['Id'],'packagerLockSha256':lock,'imageId':iid,'behaviorTests':8,'packagedSourcesMatch':True,
      'nativeKoffiImported':True,'epicReopenPreserved':True,'runtimeContractAndBasePreserved':True,'testNetwork':'none','testUser':'1000:1000',
      'productionChanged':False,'paidResourcesCreated':0,'allDisposableContainersRemoved':True,'realStoreAccountAcceptance':False,'nativeMediaQualified':False}
    (out/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n');print('Packaged Compute picker: 8 behavioral cases, source integrity and native import passed; receipt saved.')
if __name__=='__main__':main()
