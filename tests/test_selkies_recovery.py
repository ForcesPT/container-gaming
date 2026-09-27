import ast
import asyncio
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest

patch = runpy.run_path('/opt/dpadcloud/dpad-patch-selkies-recovery')
source = Path('/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/__main__.py').read_text()
rtc = Path('/opt/gst-web/webrtc.js').read_text()

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_bounded_retry_and_success_reset(self):
        tree = ast.parse(patch['transform']('main', source))
        helper = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'wait_for_peer')
        delays = []
        gate = asyncio.Event()
        async def sleep(delay):
            delays.append(delay)
            if delay == .25:
                await gate.wait()
        state = {}
        scope = {'asyncio': SimpleNamespace(sleep=sleep), 'peer_retry_count': state}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[])), '<retry>', 'exec'), scope)
        tasks = [asyncio.create_task(scope['wait_for_peer'](peer)) for peer in (1, 3)]
        await asyncio.sleep(0)
        self.assertEqual(delays, [.25, .25])
        # Browser handshake remains schedulable while both retry tasks wait.
        async def handshake(): return 'HELLO'
        self.assertEqual(await asyncio.wait_for(handshake(), .1), 'HELLO')
        gate.set()
        await asyncio.gather(*tasks)
        for _ in range(5): await scope['wait_for_peer'](1)
        self.assertEqual(delays[2:], [.5, 1, 2, 2, 2])
        self.assertEqual(state['3'], 1)
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'on_session_handler')
        scope['session_peer_id'] = 1
        exec(compile(ast.fix_missing_locations(ast.Module(body=[handler.body[0]], type_ignores=[])), '<success>', 'exec'), scope)
        await scope['wait_for_peer'](1)
        self.assertEqual(delays[-1], .25)
        self.assertEqual(state['3'], 1)

    def test_modified_sources_rejected(self):
        for kind, text in [('main', source), ('rtc', rtc)]:
            with self.assertRaises(ValueError): patch['transform'](kind, text + '\n# changed\n')

    def test_cache_entries_validated_before_versioning(self):
        for name in patch['ASSET_PINS']:
            text = Path('/opt/gst-web', name).read_text()
            changed = patch['version_asset'](name, text)
            self.assertNotIn(patch['OLD_VERSION'], changed)
            self.assertIn(patch['VERSION'], changed)
            with self.assertRaises(ValueError): patch['version_asset'](name, text + '\n')

if __name__ == '__main__': unittest.main()
