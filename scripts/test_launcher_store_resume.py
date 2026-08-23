#!/usr/bin/env python3
"""Behavioral tests for resuming an already-running store window."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "launcher" / "src" / "store_lifecycle.cjs"

program = r'''
const assert = require('assert');
const { detectStoreIdFromTitles, resumeActiveStore } = require(process.argv[1]);

assert.strictEqual(resumeActiveStore({ activeStoreId: null }), null);
assert.strictEqual(detectStoreIdFromTitles(['Sign in to Steam']), 'steam');
assert.strictEqual(detectStoreIdFromTitles(['Battle.net Login']), 'battlenet');
assert.strictEqual(detectStoreIdFromTitles(['DpadPlay']), null);

const calls = [];
const resumed = resumeActiveStore({
  activeStoreId: 'steam',
  activeStorePid: 42,
  isWindowVisible: id => { calls.push(`visible:${id}`); return true; },
  hideLauncher: () => calls.push('hide'),
  notifyVisible: id => calls.push(`notify:${id}`),
  log: line => calls.push(`log:${line}`),
});
assert.deepStrictEqual(resumed, { ok: true, resumed: true, storeId: 'steam', pid: 42 });
assert.deepStrictEqual(calls.slice(0, 3), ['visible:steam', 'hide', 'notify:steam']);

const waitingCalls = [];
const waiting = resumeActiveStore({
  activeStoreId: 'epic',
  activeStorePid: 99,
  isWindowVisible: () => false,
  hideLauncher: () => waitingCalls.push('hide'),
  notifyVisible: () => waitingCalls.push('notify'),
  log: line => waitingCalls.push(`log:${line}`),
});
assert.deepStrictEqual(waiting, {
  ok: false,
  activeStoreId: 'epic',
  error: 'Epic is still starting; its window will open automatically',
});
assert.deepStrictEqual(waitingCalls, ['log:resume-store epic: window not visible yet']);
'''

result = subprocess.run(
    ["node", "-e", program, str(POLICY)],
    text=True,
    capture_output=True,
)
if result.returncode:
    raise SystemExit(result.stderr or result.stdout)
print("Launcher active-store resume: PASS")
