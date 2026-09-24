from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[1] / 'scripts' / 'dpad-selkies-listener-health.py'


def probe(path):
    return subprocess.run([sys.executable, str(HELPER), str(path)], capture_output=True).returncode


class ListenerHealthTest(unittest.TestCase):
    def test_live_stale_and_non_listening_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signal.sock'
            self.assertEqual(probe(path), 1)
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                self.assertEqual(probe(path), 1, 'a bound socket without listen is unavailable')
                listener.listen(2)
                self.assertEqual(probe(path), 0)
                alias = Path(directory) / 'alias.sock'
                alias.symlink_to(path)
                self.assertEqual(probe(alias), 1, 'a symlink must not count as the bound endpoint')
            self.assertEqual(probe(path), 1, 'socket file survives but listener is gone')
            path.unlink()
            self.assertEqual(probe(path), 1)

    def test_invalid_path_is_not_a_restart_signal(self):
        self.assertEqual(probe('relative.sock'), 2)


if __name__ == '__main__':
    unittest.main()
