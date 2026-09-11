import pathlib,subprocess,tempfile,unittest
SCRIPT=pathlib.Path(__file__).with_name('build-apt-https.sh')
class HttpsTest(unittest.TestCase):
 def test_sources_and_strict_update(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=pathlib.Path(tmp);(p/'sources.list.d').mkdir();(p/'apt.conf.d').mkdir()
   source=p/'sources.list.d/ubuntu.sources'
   source.write_text('URIs: http://archive.ubuntu.com/ubuntu/ http://security.ubuntu.com/ubuntu/\nSigned-By: /key\n')
   nvidia=p/'sources.list.d/cuda.list';nvidia.write_text('deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64 /\n')
   before=nvidia.read_text()
   result=subprocess.run(['sh',str(SCRIPT),str(p)],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertNotIn('http://',source.read_text());self.assertIn('Signed-By: /key',source.read_text())
   self.assertEqual(nvidia.read_text(),before)
   config=(p/'apt.conf.d/80dpad-build-network').read_text()
   self.assertIn('APT::Update::Error-Mode "any";',config)
   self.assertIn('Acquire::https::Timeout "30";',config)
   self.assertNotIn('Verify-Peer',config)
 def test_every_independent_stage_configures_https_before_apt(self):
  dockerfile=SCRIPT.parent.parent/'Dockerfile'
  stages=dockerfile.read_text().split('FROM ')[1:]
  for stage in stages:
   if stage.startswith('base AS '):continue
   self.assertIn('RUN sh /tmp/build-apt-https.sh',stage)
   self.assertLess(stage.index('RUN sh /tmp/build-apt-https.sh'),stage.index('apt-get update'))
if __name__=='__main__':unittest.main()
