"""Exercise the maintained entrypoint command builder without GPU startup."""
from pathlib import Path
import subprocess
import socket
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SelkiesLaunchCommand(unittest.TestCase):
    def test_image_applies_unix_transform_after_pinned_wheel_install(self):
        dockerfile = (ROOT/'Dockerfile').read_text()
        copy = 'COPY scripts/dpad-patch-selkies-unix /opt/dpadcloud/dpad-patch-selkies-unix'
        run = 'RUN python3 /opt/dpadcloud/dpad-patch-selkies-unix '
        self.assertTrue(copy in dockerfile, 'image does not copy Unix transport patcher')
        self.assertTrue(run in dockerfile, 'image does not apply Unix transport patcher')
        self.assertLess(dockerfile.index('pip3 install --no-cache-dir --force-reinstall'), dockerfile.index(copy))
        self.assertLess(dockerfile.index(copy), dockerfile.index(run))

    def health_probe(self, socket_path, port):
        # Execute the real signaling healthcheck prefix. GPU/desktop checks are
        # unchanged and intentionally outside this CPU transport test.
        script = (ROOT/'healthcheck.sh').read_text().split('# The server can listen', 1)[0]
        script = script.replace('/run/dpad-signaling/stream.sock', str(socket_path))
        return subprocess.run(['bash', '-c', 'pgrep() { return 0; }\n'
                               + f'DPAD_SELKIES_PORT={port}\n' + script],
                              capture_output=True, text=True, timeout=5)

    def test_healthcheck_accepts_unix_listener_without_tcp(self):
        with tempfile.TemporaryDirectory(prefix='dpad-health-') as directory:
            path = Path(directory)/'signal.sock'
            with socket.socket(socket.AF_UNIX) as server, socket.socket() as tcp:
                server.bind(str(path))
                server.listen()
                tcp.bind(('127.0.0.1', 0))  # Reserved but not listening.
                result = self.health_probe(path, tcp.getsockname()[1])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_healthcheck_rejects_tcp_without_unix_listener(self):
        with tempfile.TemporaryDirectory(prefix='dpad-health-') as directory:
            with socket.socket() as tcp:
                tcp.bind(('127.0.0.1', 0))
                tcp.listen()
                result = self.health_probe(Path(directory)/'missing.sock', tcp.getsockname()[1])
                self.assertNotEqual(result.returncode, 0, 'TCP listener must not satisfy Unix transport health')

    def test_user_switch_command_preserves_private_socket(self):
        text = (ROOT/'entrypoint.sh').read_text()
        start = text.index('    build_selkies_cmd() {')
        end = text.index('\n    }', start) + len('\n    }')
        script = '''
as_user() { printf '%s\n' "$1" >&2; }
_dpad_res() { printf '1920x1080'; }
_dpad_quality() { printf '20000 192000'; }
video_src=waylanddisplaysrc
DPAD_DESKTOP_CLIENT=sway
XDG_RUNTIME_DIR=/run/user/1000
PULSE_SERVER=unix:/run/user/1000/pulse/native
SELKIES_INTERPOSER=fixture
selkies_port=16100
enc=nvh264enc
stream_fps=60
SELKIES_USER=fixture
SELKIES_PASS=fixture
rtc='{}'
SELKIES_WEB_ROOT=/opt/gst-web
'''+text[start:end]+'\nbuild_selkies_cmd\n'
        result = subprocess.run(['bash','-c',script],capture_output=True,text=True,check=True)
        self.assertIn('DPAD_SIGNAL_UNIX_SOCKET=/run/dpad-signaling/stream.sock',result.stdout)
        self.assertIn('--enable_https=false',result.stdout)

if __name__ == '__main__': unittest.main()
