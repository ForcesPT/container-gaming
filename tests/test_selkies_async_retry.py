"""Exercise the real pinned callbacks without requiring a GPU or Gst import."""
import ast
import asyncio
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest

SOURCE = Path(sys.argv.pop())
PATCH = runpy.run_path(os.environ.get('DPAD_ASYNC_RETRY_PATCHER', str(Path(__file__).resolve().parents[1] / 'scripts/dpad-patch-selkies-async-retry')))

class AsyncRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_missing_peer_waits_allow_handshakes_to_proceed(self):
        changed = PATCH['transform'](SOURCE.read_text())
        wanted = {'on_signalling_error', 'on_audio_signalling_error'}
        callbacks = [node for node in ast.walk(ast.parse(changed)) if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted]
        self.assertEqual(len(callbacks), 2)
        release = asyncio.Event()
        waiting = []
        calls = []
        async def pause(seconds):
            waiting.append(seconds)
            await release.wait()
        async def video(): calls.append('video')
        async def audio(): calls.append('audio')
        class MissingPeer(Exception): pass
        namespace = {'asyncio': SimpleNamespace(sleep=pause), 'WebRTCSignallingErrorNoPeer': MissingPeer,
                     'signalling': SimpleNamespace(setup_call=video), 'audio_signalling': SimpleNamespace(setup_call=audio)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=callbacks, type_ignores=[])), '<pinned callbacks>', 'exec'), namespace)
        tasks = [asyncio.create_task(namespace[name](MissingPeer())) for name in sorted(wanted)]
        await asyncio.sleep(0)
        self.assertEqual(waiting, [2, 2])
        self.assertEqual(calls, [])
        # Another task can service a browser handshake while both retries wait.
        async def handshake(): return 'HELLO'
        self.assertEqual(await asyncio.wait_for(handshake(), .1), 'HELLO')
        release.set()
        await asyncio.gather(*tasks)
        self.assertCountEqual(calls, ['video', 'audio'])

    async def test_exact_source_validation_and_idempotence(self):
        source = SOURCE.read_text()
        changed = PATCH['transform'](source)
        self.assertEqual(PATCH['transform'](changed), changed)
        with self.assertRaises(ValueError): PATCH['transform'](source + '\n# changed source\n')
        with self.assertRaises(ValueError): PATCH['transform'](changed + '\n# changed output\n')

if __name__ == '__main__': unittest.main()
