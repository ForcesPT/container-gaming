#!/usr/bin/env python3
from pathlib import Path
import hashlib
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts" / "dpad-resolve-stream-quality"


class StreamQualityPlumbingTests(unittest.TestCase):
    def resolve(
        self,
        width: str,
        height: str,
        fps: str,
        video: str = "",
        audio: str = "",
    ) -> subprocess.CompletedProcess[str]:
        command = [str(RESOLVER), width, height, fps, video, audio]
        if not RESOLVER.exists():
            return subprocess.CompletedProcess(command, 127, "", "resolver missing")
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def test_1080p60_defaults_to_high_quality_h264_and_opus(self) -> None:
        result = self.resolve("1920", "1080", "60")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "20000 192000\n")

    def test_higher_frame_rate_receives_a_larger_video_budget(self) -> None:
        expected = {
            "120": "30000 192000\n",
            "144": "35000 192000\n",
            "240": "50000 192000\n",
        }
        for fps, output in expected.items():
            with self.subTest(fps=fps):
                result = self.resolve("1920", "1080", fps)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, output)

    def test_higher_resolution_receives_a_larger_video_budget(self) -> None:
        expected = {
            ("1280", "720"): "12000 192000\n",
            ("2560", "1440"): "32000 192000\n",
            ("3840", "2160"): "60000 192000\n",
        }
        for (width, height), output in expected.items():
            with self.subTest(resolution=f"{width}x{height}"):
                result = self.resolve(width, height, "60")
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, output)

    def test_valid_operator_overrides_are_preserved(self) -> None:
        result = self.resolve("1920", "1080", "60", "28000", "256000")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "28000 256000\n")

    def test_invalid_values_fail_closed(self) -> None:
        invalid_cases = [
            ("1920;touch /tmp/no", "1080", "60", "", ""),
            ("1920", "1080", "90", "", ""),
            ("1920", "1080", "60", "999", ""),
            ("1920", "1080", "60", "200001", ""),
            ("1920", "1080", "60", "", "31999"),
            ("1920", "1080", "60", "", "510001"),
        ]
        for args in invalid_cases:
            with self.subTest(args=args):
                result = self.resolve(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_session_launcher_forwards_operator_overrides(self) -> None:
        launcher = (ROOT / "scripts" / "dpad-launch-session").read_text()
        self.assertIn(
            '-e DPAD_VIDEO_BITRATE_KBPS="${DPAD_VIDEO_BITRATE_KBPS:-}"', launcher
        )
        self.assertIn(
            '-e DPAD_AUDIO_BITRATE_BPS="${DPAD_AUDIO_BITRATE_BPS:-}"', launcher
        )

    def test_entrypoint_resolves_and_applies_both_bitrates(self) -> None:
        entrypoint = (ROOT / "entrypoint.sh").read_text()
        self.assertIn("/opt/dpadcloud/dpad-resolve-stream-quality", entrypoint)
        self.assertIn("--video_bitrate=${video_bitrate}", entrypoint)
        self.assertIn("--audio_bitrate=${audio_bitrate}", entrypoint)

    def test_quality_files_are_baked_and_mounted_as_one_bundle(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text()
        launcher = (ROOT / "scripts" / "dpad-launch-session").read_text()
        bootstrap = (ROOT / "scripts" / "vm-bootstrap.sh").read_text()
        self.assertIn("scripts/dpad-resolve-stream-quality", dockerfile)
        self.assertIn("scripts/dpad-update-stream-hotfix", dockerfile)
        self.assertIn("local stream_hotfix=/opt/dpadcloud/stream-hotfix-current", launcher)
        self.assertIn('stream_hotfix_resolved="$(readlink -f', launcher)
        self.assertIn('${stream_hotfix_resolved}/entrypoint.sh', launcher)
        self.assertIn('${stream_hotfix_resolved}/dpad-resolve-stream-quality', launcher)
        self.assertIn('${stream_hotfix_resolved}/patch_live_resolution.py', launcher)
        self.assertNotIn("[ -f /opt/dpadcloud/entrypoint.sh ]", launcher)
        self.assertIn("dpad-update-stream-hotfix", bootstrap)
        self.assertIn("DPAD_STREAM_HOTFIX_UPDATER_SHA256=", bootstrap)
        self.assertIn('sha256sum -c -', bootstrap)

    def test_entrypoint_requires_the_local_browser_patch(self) -> None:
        entrypoint = (ROOT / "entrypoint.sh").read_text()
        overlay_start = entrypoint.index("# --- live-resolution + authoritative-quality overlay")
        overlay_end = entrypoint.index("# --- fixed session shell", overlay_start)
        overlay = entrypoint[overlay_start:overlay_end]
        self.assertNotIn("curl ", overlay)
        self.assertNotIn("|| true", overlay)
        self.assertIn("python3 /opt/dpadcloud/patch_live_resolution.py", overlay)
        self.assertIn("return 1", overlay)

    def test_bootstrap_pins_the_exact_hotfix_artifact_hashes(self) -> None:
        bootstrap = (ROOT / "scripts" / "vm-bootstrap.sh").read_text()
        expected = {
            "UPDATER": ROOT / "scripts/dpad-update-stream-hotfix",
            "ENTRYPOINT": ROOT / "entrypoint.sh",
            "RESOLVER": ROOT / "scripts/dpad-resolve-stream-quality",
            "BROWSER_PATCH": ROOT / "scripts/patch_live_resolution.py",
        }
        for label, path in expected.items():
            match = re.search(
                rf'DPAD_STREAM_HOTFIX_{label}_SHA256="([0-9a-f]{{64}})"', bootstrap
            )
            if match is None:
                self.fail(f"missing pinned digest for {label}")
            self.assertEqual(match.group(1), hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
