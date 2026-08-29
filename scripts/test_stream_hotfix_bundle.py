#!/usr/bin/env python3
from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "scripts" / "dpad-update-stream-hotfix"


class StreamHotfixBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.host_root = base / "host"
        self.source = base / "source"
        scripts = self.source / "scripts"
        scripts.mkdir(parents=True)
        (self.source / "entrypoint.sh").write_text(
            "#!/usr/bin/env bash\n"
            "/opt/dpadcloud/dpad-resolve-stream-quality 1920 1080 60\n"
            "python3 /opt/dpadcloud/patch_live_resolution.py\n",
            encoding="utf-8",
        )
        (scripts / "dpad-resolve-stream-quality").write_text(
            "#!/usr/bin/env bash\nprintf '20000 192000\\n'\n", encoding="utf-8"
        )
        (scripts / "patch_live_resolution.py").write_text(
            "#!/usr/bin/env python3\n"
            "# DPAD: server launch profile owns initial video bitrate.\n"
            "# DPAD: server launch profile owns initial audio bitrate.\n",
            encoding="utf-8",
        )

    def artifact_hashes(self) -> list[str]:
        return [
            hashlib.sha256((self.source / "entrypoint.sh").read_bytes()).hexdigest()
            if (self.source / "entrypoint.sh").exists() else "0" * 64,
            hashlib.sha256((self.source / "scripts/dpad-resolve-stream-quality").read_bytes()).hexdigest()
            if (self.source / "scripts/dpad-resolve-stream-quality").exists() else "0" * 64,
            hashlib.sha256((self.source / "scripts/patch_live_resolution.py").read_bytes()).hexdigest()
            if (self.source / "scripts/patch_live_resolution.py").exists() else "0" * 64,
        ]

    def update(self, expected_hashes: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        if not UPDATER.exists():
            return subprocess.CompletedProcess([str(UPDATER)], 127, "", "updater missing")
        hashes = expected_hashes or self.artifact_hashes()
        return subprocess.run(
            [str(UPDATER), str(self.host_root), self.source.as_uri(), *hashes],
            text=True,
            capture_output=True,
            check=False,
        )

    def current(self) -> Path:
        return (self.host_root / "stream-hotfix-current").resolve()

    def test_success_publishes_one_complete_bundle(self) -> None:
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        current = self.current()
        self.assertTrue(current.is_dir())
        self.assertEqual(
            {path.name for path in current.iterdir() if path.name != "__pycache__"},
            {"entrypoint.sh", "dpad-resolve-stream-quality", "patch_live_resolution.py"},
        )
        self.assertTrue(os.access(current / "entrypoint.sh", os.X_OK))
        self.assertTrue(os.access(current / "dpad-resolve-stream-quality", os.X_OK))

    def test_failed_refresh_retains_last_known_good_bundle(self) -> None:
        first = self.update()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        previous_target = os.readlink(self.host_root / "stream-hotfix-current")
        previous_entrypoint = (self.current() / "entrypoint.sh").read_bytes()
        (self.source / "scripts" / "dpad-resolve-stream-quality").unlink()

        failed = self.update()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(os.readlink(self.host_root / "stream-hotfix-current"), previous_target)
        self.assertEqual((self.current() / "entrypoint.sh").read_bytes(), previous_entrypoint)

    def test_identical_refresh_reuses_the_same_content_address(self) -> None:
        first = self.update()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_target = os.readlink(self.host_root / "stream-hotfix-current")
        second = self.update()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(os.readlink(self.host_root / "stream-hotfix-current"), first_target)
        bundle_dirs = [
            path for path in self.host_root.glob("stream-hotfix-*")
            if path.name != "stream-hotfix-current"
        ]
        self.assertEqual(len(bundle_dirs), 1)

    def test_initial_failure_publishes_nothing(self) -> None:
        (self.source / "scripts" / "patch_live_resolution.py").unlink()
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.host_root / "stream-hotfix-current").exists())
        self.assertEqual(list(self.host_root.glob(".stream-hotfix.*")), [])

    def test_incompatible_artifact_is_rejected(self) -> None:
        (self.source / "entrypoint.sh").write_text("#!/usr/bin/env bash\ntrue\n", encoding="utf-8")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incompatible entrypoint", result.stderr)
        self.assertFalse((self.host_root / "stream-hotfix-current").exists())

    def test_digest_mismatch_is_rejected_before_publication(self) -> None:
        pinned = self.artifact_hashes()
        (self.source / "entrypoint.sh").write_text(
            "#!/usr/bin/env bash\necho tampered\n", encoding="utf-8"
        )
        result = self.update(pinned)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authenticity check failed", result.stderr)
        self.assertFalse((self.host_root / "stream-hotfix-current").exists())


if __name__ == "__main__":
    unittest.main()
