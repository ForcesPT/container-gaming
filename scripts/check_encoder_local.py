#!/usr/bin/env python3
"""Account-free local packaged CUDA/NVENC probe; never pulls or calls a provider.

This cannot qualify compositor capture, WebRTC, audio, login or Shared isolation.
Use a new absolute evidence directory and an exact local immutable image ID.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

PROBE = r'''import ctypes,hashlib,json
import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
cuda=ctypes.CDLL('libcuda.so.1')
version=Gst.version()
factory='nvcudah264enc' if version[0]==1 and 20<version[1]<=24 else 'nvh264enc'
decoder=next((name for name in ['avdec_h264','nvcudah264dec','nvh264dec','openh264dec'] if Gst.ElementFactory.find(name)),None)
if decoder is None:raise RuntimeError('No packaged H.264 decoder available for frame verification')
settings=' preset=p4 tune=ultra-low-latency' if version[0]==1 and version[1]>22 else ' preset=low-latency-hq'
counts={'encodedFrames':0,'encodedBytes':0,'decodedFrames':0}
frames=set()
pipeline=Gst.parse_launch('videotestsrc pattern=ball num-buffers=60 ! '
 'video/x-raw,width=1280,height=720,framerate=30/1 ! videoconvert ! video/x-raw,format=RGBx ! '
 'cudaupload ! cudaconvert ! video/x-raw(memory:CUDAMemory),format=NV12 ! '+factory+settings+
 ' ! h264parse ! video/x-h264,alignment=au,stream-format=byte-stream ! identity name=encoded ! '
 +decoder+' ! videoconvert ! video/x-raw,format=RGB ! appsink name=decoded sync=false emit-signals=true')
def encoded(_pad,info):
 buffer=info.get_buffer()
 if buffer:
  counts['encodedFrames']+=1;counts['encodedBytes']+=buffer.get_size()
 return Gst.PadProbeReturn.OK
def decoded(sink):
 sample=sink.emit('pull-sample')
 if sample is None:return Gst.FlowReturn.ERROR
 buffer=sample.get_buffer();ok,mapping=buffer.map(Gst.MapFlags.READ)
 if not ok:return Gst.FlowReturn.ERROR
 try:
  counts['decodedFrames']+=1;frames.add(hashlib.sha256(mapping.data).hexdigest())
 finally:buffer.unmap(mapping)
 return Gst.FlowReturn.OK
pipeline.get_by_name('encoded').get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER,encoded)
pipeline.get_by_name('decoded').connect('new-sample',decoded)
try:
 if pipeline.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('GPU pipeline did not enter PLAYING')
 message=pipeline.get_bus().timed_pop_filtered(30*Gst.SECOND,Gst.MessageType.ERROR|Gst.MessageType.EOS)
 if message is None:raise RuntimeError('GPU pipeline did not complete')
 if message.type==Gst.MessageType.ERROR:raise RuntimeError(str(message.parse_error()[0]))
 assert counts['encodedFrames']==counts['decodedFrames']==60 and counts['encodedBytes']>0 and len(frames)>1,(decoder,counts)
 print(json.dumps({'status':'encoded-and-decoded','gstreamerVersion':list(version),'encoder':factory,'decoder':decoder,
  **counts,'distinctDecodedFrames':len(frames),'resolution':[1280,720],'fps':30,
  'cudaEglRegistrationSymbolPresent':hasattr(cuda,'cuGraphicsEGLRegisterImage')}))
finally:pipeline.set_state(Gst.State.NULL)
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    compile(PROBE,'encoder-probe','exec')
    harness_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',args.image):parser.error('Exact local image ID required')
    if not args.output.is_absolute():parser.error('Absolute evidence directory required')
    out=args.output;out.mkdir(exist_ok=False)
    def run(command,timeout=30):
        return subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout)
    inspection=run(['docker','image','inspect',args.image]);inspection.check_returncode()
    image=json.loads(inspection.stdout)[0]
    assert image['Id']==args.image
    probe=out/'probe.py';probe.write_text(PROBE,encoding='utf8',newline='\n')
    name='dpad-local-encoder-'+uuid.uuid4().hex
    identity=None;result=None;cleaned=False
    try:
        created=run(['docker','create','--pull=never','--name',name,'--label','com.dpadplay.local-qualification='+name,
          '--network','none','--gpus','all','--cpus','2','--memory','2g','--pids-limit','256','--user','1000:1000',
          '-e','NVIDIA_DRIVER_CAPABILITIES=compute,video,utility','-e','GST_DEBUG=1',
          '--mount','type=bind,src='+str(out)+',dst=/fixture,readonly','--entrypoint','/bin/bash',args.image,
          '-c','. /opt/gstreamer/gst-env && python3 /fixture/probe.py'])
        created.check_returncode();identity=created.stdout.strip()
        assert re.fullmatch('[a-f0-9]{64}',identity)
        checked=run(['docker','inspect',identity]);checked.check_returncode();container=json.loads(checked.stdout)[0]
        assert container['Image']==args.image and container['Config']['Labels']['com.dpadplay.local-qualification']==name
        result=run(['docker','start','--attach',identity],timeout=60)
        (out/'pipeline.log').write_text(result.stdout+result.stderr,encoding='utf8')
    finally:
        if identity:
            removed=run(['docker','rm','-f','-v',identity]);removed.check_returncode()
            cleaned=run(['docker','inspect',identity]).returncode!=0
            assert cleaned
    receipt={'status':'passed' if result and result.returncode==0 else 'blocked',
      'imageId':args.image,'imageSourceRevision':image['Config'].get('Labels',{}).get('org.opencontainers.image.revision'),
      'probeSha256':hashlib.sha256(probe.read_bytes()).hexdigest(),
      'harnessSha256':harness_hash,
      'accountUsed':False,'testNetwork':'none','fixtureUser':'1000:1000','fixtureRemoved':cleaned,
      'nativeCompositorQualified':False,'webRtcQualified':False,'audioQualified':False,
      'cloudSaveQualified':False,'sharedIsolationQualified':False,'productionChanged':False,'paidResourcesCreated':0}
    if result and result.returncode==0:
        receipt['pipeline']=json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{')))
    assert harness_hash==hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'Probe harness changed during qualification'
    (out/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf8')
    print(json.dumps(receipt,indent=2))
    if receipt['status']!='passed':raise SystemExit(1)

if __name__=='__main__':main()
