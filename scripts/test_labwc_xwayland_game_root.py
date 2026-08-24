#!/usr/bin/env python3
"""Regression contract for the Labwc XWayland game-root crash."""

from pathlib import Path
import hashlib
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
PATCH_PATH = ROOT / "patches" / "labwc-0.7.1-xwayland-game-root.patch"
LABWC_ARCHIVE_SHA256 = "1810ec55e287708e7a3cd44c726aa887db02480704db82b3d0bd550a6c4bfb76"
PATCH_SHA256 = "410888d3c11ddd7cc01173308fd705a572eb19fbcd29f4d9b8a5d6f3609c6dd3"


class LabwcXwaylandGameRootTests(unittest.TestCase):
    def test_image_builds_patched_labwc_with_upstream_game_root_fallback(self):
        self.assertTrue(PATCH_PATH.is_file(), "missing pinned Labwc XWayland crash patch")
        patch = PATCH_PATH.read_text()
        self.assertIn(
            "return (root && root->data) ? (struct view *)root->data : view;",
            patch,
        )
        self.assertIn("FROM ubuntu:24.04 AS labwc-builder", DOCKERFILE)
        self.assertRegex(DOCKERFILE, r"ARG LABWC_REF=0\.7\.1\b")
        self.assertIn(f"ARG LABWC_SHA256={LABWC_ARCHIVE_SHA256}", DOCKERFILE)
        self.assertEqual(hashlib.sha256(PATCH_PATH.read_bytes()).hexdigest(), PATCH_SHA256)
        self.assertIn("labwc-0.7.1-xwayland-game-root.patch", DOCKERFILE)
        self.assertRegex(
            DOCKERFILE,
            re.compile(r"COPY --from=labwc-builder\s+/out/usr/bin/labwc\s+/usr/bin/labwc"),
        )


if __name__ == "__main__":
    unittest.main()
