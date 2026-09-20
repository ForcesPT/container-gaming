"""Opt-in real upstream test: DPAD_SELKIES_WHEEL points at pinned 1.6.2."""
import argparse
import asyncio
import base64
import hashlib
import importlib.util
import os
import socket
import ssl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WHEEL = os.environ.get('DPAD_SELKIES_WHEEL')
GATEWAY = os.environ.get('DPAD_GUEST_TLS_GATEWAY')

@unittest.skipUnless(WHEEL, 'requires explicit pinned Selkies wheel and websockets<14')
class SelkiesUnixTest(unittest.IsolatedAsyncioTestCase):
    async def test_actual_server_and_local_client_use_unix_only(self):
        await self.exercise(False)

    @unittest.skipUnless(GATEWAY, 'requires explicit host gateway from worker revision 501c5a4')
    async def test_authenticated_wss_through_host_gateway(self):
        await self.exercise(True)

    async def exercise(self, tls):
        import websockets
        from websockets.exceptions import InvalidStatusCode
        with tempfile.TemporaryDirectory(prefix='dpad-selkies-') as directory:
            root = Path(directory)
            assert WHEEL is not None
            wheel = Path(WHEEL)
            self.assertEqual(hashlib.sha256(wheel.read_bytes()).hexdigest(), 'f426ae093853492ecf857609efd4c9bd2141b24c619118561e42220927554eee')
            with zipfile.ZipFile(wheel) as archive:
                for name in ('signalling_web.py', 'webrtc_signalling.py'):
                    (root/name).write_bytes(archive.read('selkies_gstreamer/'+name))
            patcher = ROOT/'scripts/dpad-patch-selkies-unix'
            if patcher.exists():
                patch = await asyncio.create_subprocess_exec(sys.executable, str(patcher), str(root))
                self.assertEqual(await asyncio.wait_for(patch.wait(), 5), 0)
            def load(name):
                spec = importlib.util.spec_from_file_location(name, root/(name+'.py'))
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
            server_module = load('signalling_web')
            client_module = load('webrtc_signalling')
            socket_path = str(root/'signal.sock')
            previous = os.environ.get('DPAD_SIGNAL_UNIX_SOCKET')
            os.environ['DPAD_SIGNAL_UNIX_SOCKET'] = socket_path
            options = argparse.Namespace(addr='127.0.0.1', port=0, keepalive_timeout=30,
                cert_restart=False, enable_https=False, https_cert='', https_key='', health='/health',
                web_root=str(root/'web'), turn_shared_secret='', turn_host='', turn_port=3478,
                turn_protocol='udp', turn_tls=False, turn_auth_header_name='', stun_host='', stun_port=19302,
                enable_basic_auth=True, basic_auth_user='fixture', basic_auth_password='local-fixture',
                rtc_config='{}', rtc_config_file='')
            server = server_module.WebRTCSimpleServer(asyncio.get_running_loop(), options)
            task = asyncio.create_task(server.run())
            client = None
            gateway = None
            try:
                for _ in range(100):
                    if server.server is not None or task.done(): break
                    await asyncio.sleep(0.01)
                if task.done(): await task
                listeners = [(item.family.name, item.getsockname()) for item in server.server.sockets]
                print('Selkies listeners:', listeners, flush=True)
                self.assertTrue(Path(socket_path).is_socket(), 'Selkies opened TCP instead of its private Unix socket')
                self.assertTrue(listeners)
                self.assertTrue(all(item.family == socket.AF_UNIX for item in server.server.sockets), listeners)
                with self.assertRaises(InvalidStatusCode) as denied:
                    async with websockets.unix_connect(socket_path, uri='ws://localhost/ws'):
                        self.fail('unauthenticated upgrade accepted')
                self.assertEqual(denied.exception.status_code, 401)
                print('Unix unauthenticated upgrade: HTTP 401', flush=True)
                client = client_module.WebRTCSignalling('ws://127.0.0.1:1/ws', 17, 18,
                    enable_basic_auth=True, basic_auth_user='fixture', basic_auth_password='local-fixture')
                await asyncio.wait_for(client.connect(), 2)
                self.assertEqual(await asyncio.wait_for(client.conn.recv(), 2), 'HELLO')
                auth = base64.b64encode(b'fixture:local-fixture').decode()
                connect = lambda headers: websockets.unix_connect(socket_path, uri='ws://localhost/ws', extra_headers=headers)
                if tls:
                    self.assertEqual(hashlib.sha256(Path(GATEWAY).read_bytes()).hexdigest(), '1e5ef5a3421630f231c76e29e286d790754a32155aebea16df49447da58392d8')
                    async def openssl(*args):
                        child = await asyncio.create_subprocess_exec('openssl', *args, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self.assertEqual(await child.wait(), 0)
                    await openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key', '-out', 'ca.pem', '-days', '1', '-subj', '/CN=Fixture CA')
                    await openssl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'leaf.key', '-out', 'leaf.csr', '-subj', '/CN=Fixture')
                    (root/'extensions').write_text('basicConstraints=critical,CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:fixture.guest.dpadplay.internal\n')
                    await openssl('x509', '-req', '-in', 'leaf.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial', '-out', 'leaf.pem', '-days', '1', '-extfile', 'extensions')
                    (root/'leaf.key').chmod(0o600)
                    with socket.socket() as probe:
                        probe.bind(('127.0.0.1', 0))
                        port = probe.getsockname()[1]
                    configuration = dict(cert=str(root/'leaf.pem'), key=str(root/'leaf.key'), ca=str(root/'ca.pem'), serverName='fixture.guest.dpadplay.internal', unixSocket=socket_path, host='127.0.0.1', port=port)
                    (root/'gateway.json').write_text(json.dumps(configuration))
                    (root/'gateway.json').chmod(0o600)
                    gateway = await asyncio.create_subprocess_exec(sys.executable, str(GATEWAY), str(root/'gateway.json'))
                    context = ssl.create_default_context(cafile=str(root/'ca.pem'))
                    connect = lambda headers: websockets.connect(f'wss://127.0.0.1:{port}/ws', ssl=context, server_hostname='fixture.guest.dpadplay.internal', extra_headers=headers)
                    for attempt in range(100):
                        try:
                            async with connect({}): self.fail('unauthenticated TLS upgrade accepted')
                        except ConnectionRefusedError:
                            await asyncio.sleep(0.02)
                        except InvalidStatusCode as error:
                            self.assertEqual(error.status_code, 401)
                            print('Verified WSS unauthenticated upgrade: HTTP 401', flush=True)
                            break
                    else: self.fail('gateway did not become ready')
                async with connect({'Authorization':'Basic '+auth}) as browser:
                    await browser.send('HELLO 18')
                    self.assertEqual(await browser.recv(), 'HELLO')
                    await client.setup_call()
                    self.assertEqual((await client.conn.recv()).strip(), 'SESSION_OK')
                    await client.conn.send('fixture-offer')
                    self.assertEqual(await asyncio.wait_for(browser.recv(), 2), 'fixture-offer')
                    print(('Verified WSS -> host gateway -> Unix Selkies' if tls else 'Unix Selkies') + ': authenticated HELLO / SESSION_OK / offer relay passed', flush=True)
            finally:
                if client and client.conn: await client.conn.close()
                if gateway and gateway.returncode is None:
                    gateway.terminate()
                    await asyncio.wait_for(gateway.wait(), 5)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if previous is None: os.environ.pop('DPAD_SIGNAL_UNIX_SOCKET', None)
                else: os.environ['DPAD_SIGNAL_UNIX_SOCKET'] = previous

if __name__ == '__main__': unittest.main()
