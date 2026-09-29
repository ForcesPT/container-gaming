'use strict';
const assert = require('node:assert/strict');
const { reopenManagedEpic } = require(process.argv[2] || '../launcher/src/epic_reopen.cjs');

(async () => {
  const owner = { pid: 42 };
  let visible = false, requested = 0, hidden = 0, notified = 0, waits = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const args = {
    owner, isCurrent: () => true, isVisible: () => visible,
    requestRestore: () => { requested++; return true; }, focus: () => true,
    hide: () => { hidden++; }, notify: () => { notified++; },
    wait: async () => { waits++; await gate; visible = true; }, attempts: 3,
  };
  const first = reopenManagedEpic(args);
  const second = reopenManagedEpic(args);
  assert.equal(first, second, 'concurrent selections share one operation');
  assert.equal(requested, 1);
  assert.equal(hidden, 0, 'picker stays visible before the official window exists');
  release();
  assert.deepEqual(await first, { ok: true, resumed: true, storeId: 'epic', pid: 42 });
  assert.equal(hidden, 1);
  assert.equal(notified, 1);
  assert.equal(waits, 1);

  hidden = 0; notified = 0;
  const quiet = { ...args, owner: {}, isVisible: () => false,
    wait: async () => {}, attempts: 3 };
  assert.equal((await reopenManagedEpic(quiet)).ok, false, 'timeout keeps picker usable');
  assert.equal(hidden, 0);
  assert.equal(notified, 0);
  assert.equal((await reopenManagedEpic({ ...args, owner: {}, focus: () => false })).ok, false);
  assert.equal(hidden, 0, 'focus failure never hides the picker');
  requested = 0;
  assert.equal((await reopenManagedEpic({ ...args, owner: {}, isCurrent: () => false })).ok, false);
  assert.equal(requested, 0, 'an exited owner never receives a restore request');
  assert.equal((await reopenManagedEpic({ ...args, owner: {}, requestRestore: () => { throw Error('spawn'); } })).ok, false);
  console.log('EPIC_REOPEN_POLICY_OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
