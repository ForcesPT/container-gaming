import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/dpad-guest-tls'

class GatewayTest(unittest.TestCase):
    def test_https_reaches_only_the_configured_unix_backend(self):
        self.exchange()

    def test_unix_symlink_cannot_redirect_credentials(self):
        self.exchange(symlink=True)

    def test_readable_private_key_prevents_startup(self):
        self.exchange(readable_key=True)

    def test_wrong_certificate_identity_prevents_startup(self):
        self.exchange(wrong_identity=True)

    def test_expired_certificate_stops_the_listener(self):
        self.exchange(short_lease=True)

    def test_wss_upgrade_and_bidirectional_binary_frames(self):
        self.exchange(websocket=True)

    def test_expiry_terminates_established_wss(self):
        self.exchange(short_lease=True, websocket=True)

    def test_exposed_configuration_prevents_startup(self):
        self.exchange(exposed_config=True)

    def test_parent_symlink_cannot_redirect_credentials(self):
        self.exchange(parent_symlink=True)

    def test_socket_replacement_cannot_inherit_existing_gateway(self):
        self.exchange(replace_socket=True)

    def exchange(self, replace_socket=False, parent_symlink=False, symlink=False, readable_key=False, wrong_identity=False, short_lease=False, websocket=False, exposed_config=False):
        with tempfile.TemporaryDirectory(prefix='dpad-tls-') as directory:
            root = Path(directory)
            def openssl(*args):
                subprocess.run(['openssl', *args], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            name = 'fixture.guest.dpadplay.internal'
            openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key', '-out', 'ca.pem', '-days', '1', '-subj', '/CN=Fixture CA')
            openssl('req', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'guest.key', '-out', 'guest.csr', '-subj', '/CN=Fixture')
            (root / 'extensions').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:' + name + '\n')
            openssl('x509', '-req', '-in', 'guest.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial', '-out', 'guest.pem', '-days', '1', '-extfile', 'extensions')
            if short_lease:
                (root / 'index').write_text('')
                (root / 'serial').write_text('01\n')
                (root / 'ca.conf').write_text('[ca]\ndefault_ca=issuer\n[issuer]\ndatabase=index\nserial=serial\nnew_certs_dir=.\nprivate_key=ca.key\ncertificate=ca.pem\ndefault_md=sha256\ndefault_days=1\npolicy=policy\n[policy]\ncommonName=supplied\n')
                now = datetime.datetime.now(datetime.timezone.utc)
                openssl('ca', '-batch', '-config', 'ca.conf', '-in', 'guest.csr', '-out', 'guest.pem', '-notext', '-extfile', 'extensions',
                        '-startdate', (now-datetime.timedelta(seconds=2)).strftime('%y%m%d%H%M%SZ'),
                        '-enddate', (now+datetime.timedelta(seconds=8)).strftime('%y%m%d%H%M%SZ'))
            (root / 'guest.key').chmod(0o644 if readable_key else 0o600)
            received = []
            release_backend = threading.Event()
            def exact(stream, length):
                data = b''
                while len(data) < length:
                    chunk = stream.recv(length-len(data))
                    if not chunk: raise EOFError('fixture stream closed')
                    data += chunk
                return data
            def headers(stream):
                data = b''
                while not data.endswith(b'\r\n\r\n'):
                    if len(data) >= 8192: raise ValueError('fixture header too large')
                    data += exact(stream, 1)
                return data
            class Backend(socketserver.BaseRequestHandler):
                def handle(self):
                    request = headers(self.request)
                    received.append(request)
                    if websocket:
                        key = next(line.split(b': ',1)[1] for line in request.split(b'\r\n') if line.startswith(b'Sec-WebSocket-Key:'))
                        accept = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                        self.request.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n')
                        first, second = exact(self.request, 2)
                        if first != 0x82 or second & 0x80 == 0 or second & 0x7f > 125: return
                        mask = exact(self.request, 4)
                        payload = exact(self.request, second & 0x7f)
                        plain = bytes(value ^ mask[index % 4] for index,value in enumerate(payload))
                        received.append(plain)
                        self.request.sendall(bytes([0x82,len(plain)])+plain)
                        if short_lease: release_backend.wait(timeout=20)
                    else:
                        self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            backend = socketserver.UnixStreamServer(str(root / 'stream.sock'), Backend)
            thread = threading.Thread(target=backend.serve_forever, daemon=True)
            thread.start()
            probe = socket.socket()
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]; probe.close()
            config = dict(cert=str(root / 'guest.pem'), key=str(root / 'guest.key'), ca=str(root / 'ca.pem'),
                          serverName=name, unixSocket=str(root / 'stream.sock'), host='127.0.0.1', port=port)
            if wrong_identity:
                config['serverName'] = 'other.guest.dpadplay.internal'
            if symlink:
                (root / 'redirect.sock').symlink_to(root / 'stream.sock')
                config['unixSocket'] = str(root / 'redirect.sock')
            if parent_symlink:
                (root / 'redirect-dir').symlink_to(root, target_is_directory=True)
                config['unixSocket'] = str(root / 'redirect-dir' / 'stream.sock')
            config_path = root / 'config.json'; config_path.write_text(json.dumps(config)); config_path.chmod(0o666 if exposed_config else 0o600)
            command = [sys.executable, str(SCRIPT), str(config_path)]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                if readable_key or wrong_identity or exposed_config:
                    try:
                        self.assertEqual(process.wait(timeout=2), 1)
                    except subprocess.TimeoutExpired:
                        self.fail("gateway accepted invalid custody or identity")
                    return
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=0.2): break
                    except OSError:
                        if process.poll() is not None or time.monotonic() > deadline: self.fail('gateway did not start')
                        time.sleep(0.02)
                context = ssl.create_default_context(cafile=str(root / 'ca.pem'))
                with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                    with context.wrap_socket(raw, server_hostname=name) as client:
                        if websocket:
                            key = base64.b64encode(os.urandom(16))
                            client.sendall(b'GET /ws HTTP/1.1\r\nHost: fixture\r\nAuthorization: Basic fixture-only\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: '+key+b'\r\n\r\n')
                            response = headers(client)
                            self.assertIn(b'101 Switching Protocols', response)
                            expected = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                            self.assertIn(b'Sec-WebSocket-Accept: '+expected, response)
                            payload = b'fixture binary frame'
                            mask = os.urandom(4)
                            client.sendall(bytes([0x82,0x80|len(payload)])+mask+bytes(value ^ mask[index % 4] for index,value in enumerate(payload)))
                            self.assertEqual(exact(client, len(payload)+2), bytes([0x82,len(payload)])+payload)
                            self.assertEqual(received[-1], payload)
                            if short_lease:
                                try: self.assertEqual(process.wait(timeout=10), 0)
                                except subprocess.TimeoutExpired: self.fail('established WSS delayed certificate expiry shutdown')
                            return
                        client.sendall(b'GET /health HTTP/1.1\r\nHost: fixture\r\nAuthorization: Basic fixture-only\r\n\r\n')
                        try:
                            response = client.recv(8192)
                        except OSError:
                            response = b''
                        if symlink or parent_symlink:
                            self.assertNotIn(b'200 OK', response)
                        else:
                            self.assertIn(b'200 OK', response)
                self.assertEqual(len(received), 0 if symlink or parent_symlink else 1)
                if received:
                    self.assertIn(b'Authorization: Basic fixture-only', received[0])
                if replace_socket:
                    backend.shutdown(); backend.server_close(); thread.join(timeout=2)
                    (root / 'stream.sock').unlink()
                    backend = socketserver.UnixStreamServer(str(root / 'stream.sock'), Backend)
                    thread = threading.Thread(target=backend.serve_forever, daemon=True)
                    thread.start()
                    before = len(received)
                    with socket.create_connection(('127.0.0.1', port), timeout=3) as raw:
                        with context.wrap_socket(raw, server_hostname=name) as client:
                            client.sendall(b'GET / HTTP/1.1\r\nHost: fixture\r\n\r\n')
                            try: response = client.recv(8192)
                            except OSError: response = b''
                            self.assertNotIn(b'200 OK', response, 'successor socket inherited stale TLS authority')
                    self.assertEqual(len(received), before)
                if short_lease:
                    try:
                        self.assertEqual(process.wait(timeout=10), 0)
                    except subprocess.TimeoutExpired:
                        self.fail('gateway survived its certificate expiry')
            finally:
                process.terminate(); process.wait(timeout=5)
                release_backend.set()
                backend.shutdown(); backend.server_close(); thread.join(timeout=2)

if __name__ == '__main__':
    unittest.main()
