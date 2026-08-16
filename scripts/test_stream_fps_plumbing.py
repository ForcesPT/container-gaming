#!/usr/bin/env python3
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "dpad-validate-stream-fps"


class StreamFpsPlumbingTests(unittest.TestCase):
    def validate(self, value: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [str(VALIDATOR)]
        if value is not None:
            command.append(value)
        if not VALIDATOR.exists():
            return subprocess.CompletedProcess(command, 127, "", "validator missing")
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def test_session_launcher_forwards_frame_rate_into_container(self) -> None:
        launcher = (ROOT / "scripts" / "dpad-launch-session").read_text()
        self.assertIn('-e DPAD_STREAM_FPS="${DPAD_STREAM_FPS:-60}"', launcher)

    def test_entrypoint_uses_validated_initial_frame_rate(self) -> None:
        entrypoint = (ROOT / "entrypoint.sh").read_text()
        self.assertIn('/opt/dpadcloud/dpad-validate-stream-fps "${DPAD_STREAM_FPS:-60}"', entrypoint)
        self.assertIn('--framerate=${stream_fps}', entrypoint)

    def test_supported_selected_frame_rate_is_preserved(self) -> None:
        result = self.validate("144")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "144\n")

    def test_omitted_frame_rate_defaults_to_60(self) -> None:
        result = self.validate()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "60\n")

    def test_unsupported_frame_rate_is_rejected(self) -> None:
        result = self.validate("90")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_shell_metacharacters_are_rejected_without_execution(self) -> None:
        marker = Path("/tmp/dpad-stream-fps-injection")
        marker.unlink(missing_ok=True)
        result = self.validate(f"60;touch {marker}")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
