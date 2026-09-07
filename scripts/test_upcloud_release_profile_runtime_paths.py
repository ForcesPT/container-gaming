#!/usr/bin/env python3
"""Run every existing profile test with both CDI directories sandboxed.

Keep the preexisting suite byte-for-byte. Its shell harness redirects /etc/cdi
but predates the stock595 /var/run/cdi destination; map that additional path
under its existing temporary CDI directory before delegating to the harness.
"""
from pathlib import Path
import unittest
import test_upcloud_release_profile as original


class RuntimePathProfileTests(original.ProfileTests):
    def shell(self, file, body, env=None, source=None):
        source = source if source is not None else (Path(__file__).parent / file).read_text()
        source = source.replace('/var/run/cdi', '/etc/cdi/runtime-fixture')
        return super().shell(file, body, env, source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
