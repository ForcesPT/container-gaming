"""Exercise the maintained entrypoint command builder without GPU startup."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SelkiesLaunchCommand(unittest.TestCase):
    def test_user_switch_command_preserves_private_socket(self):
        text = (ROOT/'entrypoint.sh').read_text()
        start = text.index('    build_selkies_cmd() {')
        end = text.index('\n    }', start) + len('\n    }')
        script = '''
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
