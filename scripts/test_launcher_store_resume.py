#!/usr/bin/env python3
"""Behavioral tests for resuming an already-running store window."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "launcher" / "src" / "store_lifecycle.cjs"

program = r'''
const assert = require('assert');
const {
  detectStoreIdFromTitles,
  detectStoreIdsFromTitles,
  chooseStoreAction,
  clearOwnedTimer,
  createLauncherRestoreReconciler,
  nextLauncherHiddenAfterHide,
  launcherWindowPolicy,
  launcherFocusBeforeHide,
  shouldMonitorAdoptedStore,
  createLauncherVisibilityGeneration,
  resumeActiveStore,
  validatedExternalUrl,
} = require(process.argv[1]);

assert.strictEqual(validatedExternalUrl('https://example.com/releases'), 'https://example.com/releases');
assert.strictEqual(validatedExternalUrl('http://127.0.0.1/callback'), 'http://127.0.0.1/callback');
assert.strictEqual(validatedExternalUrl('javascript:alert(1)'), null);
assert.strictEqual(validatedExternalUrl('file:///etc/passwd'), null);
assert.strictEqual(validatedExternalUrl(''), null);

assert.strictEqual(resumeActiveStore({ activeStoreId: null }), null);
assert.strictEqual(detectStoreIdFromTitles(['Sign in to Steam']), 'steam');
assert.strictEqual(detectStoreIdFromTitles(['Battle.net Login']), 'battlenet');
assert.strictEqual(detectStoreIdFromTitles(['EA']), 'ea');
assert.strictEqual(detectStoreIdFromTitles(['DpadPlay']), null);
assert.deepStrictEqual(
  detectStoreIdsFromTitles(['Sign in to Steam', 'Epic Games Launcher', 'DpadPlay']),
  ['steam', 'epic'],
);
// Epic and GOG share one Heroic client. A live Heroic window must satisfy both
// cards so either selection focuses the existing process instead of duplicating it.
assert.deepStrictEqual(
  detectStoreIdsFromTitles(['Heroic Games Launcher']),
  ['epic', 'gog'],
);
assert.deepStrictEqual(
  chooseStoreAction({ requestedStoreId: 'epic', runningStoreIds: ['steam'] }),
  { action: 'launch', storeId: 'epic' },
);
assert.deepStrictEqual(
  chooseStoreAction({ requestedStoreId: 'steam', runningStoreIds: ['steam', 'epic'] }),
  { action: 'resume', storeId: 'steam' },
);
assert.deepStrictEqual(
  chooseStoreAction({ requestedStoreId: 'epic', runningStoreIds: [], snapshotAvailable: false }),
  { action: 'wait', storeId: 'epic' },
);
assert.strictEqual(nextLauncherHiddenAfterHide(true, false), true);
assert.strictEqual(nextLauncherHiddenAfterHide(false, false), false);
assert.strictEqual(nextLauncherHiddenAfterHide(false, true), true);
assert.deepStrictEqual(launcherWindowPolicy('labwc'), {
  fullscreen: false,
  maximize: true,
  restoreCommand: '[title="DpadPlay"] maximize enable',
});
assert.deepStrictEqual(launcherWindowPolicy('sway'), {
  fullscreen: true,
  maximize: false,
  restoreCommand: '[title="DpadPlay"] fullscreen enable',
});
assert.strictEqual(launcherFocusBeforeHide('labwc'), false);
assert.strictEqual(launcherFocusBeforeHide('sway'), true);
assert.strictEqual(shouldMonitorAdoptedStore(true, false), true);
assert.strictEqual(shouldMonitorAdoptedStore(true, true), false);
assert.strictEqual(shouldMonitorAdoptedStore(false, false), false);
const visibilityGeneration = createLauncherVisibilityGeneration();
const staleRestoreToken = visibilityGeneration.capture();
visibilityGeneration.invalidate(); // a newer hide cycle starts
assert.strictEqual(visibilityGeneration.isCurrent(staleRestoreToken), false);
const currentRestoreToken = visibilityGeneration.capture();
assert.strictEqual(visibilityGeneration.isCurrent(currentRestoreToken), true);

const oldOwner = {};
const newOwner = {};
const clearedTimers = [];
const timerMap = new Map([['steam', { timer: 22, owner: newOwner }]]);
assert.strictEqual(clearOwnedTimer(timerMap, 'steam', oldOwner, id => clearedTimers.push(id)), false);
assert.strictEqual(timerMap.has('steam'), true);
assert.deepStrictEqual(clearedTimers, []);
assert.strictEqual(clearOwnedTimer(timerMap, 'steam', newOwner, id => clearedTimers.push(id)), true);
assert.strictEqual(timerMap.has('steam'), false);
assert.deepStrictEqual(clearedTimers, [22]);

const scheduled = [];
const snapshots = [null, ['Steam'], []];
let restored = 0;
const reconciler = createLauncherRestoreReconciler({
  hasActiveChildren: () => false,
  getWindowTitles: () => snapshots.shift(),
  isLauncherHidden: () => true,
  restoreLauncher: () => { restored++; return true; },
  schedule: fn => { scheduled.push(fn); return fn; },
});
reconciler.request();
assert.strictEqual(scheduled.length, 1);
scheduled.shift()(); // unavailable compositor snapshot: retry
assert.strictEqual(restored, 0);
assert.strictEqual(scheduled.length, 1);
scheduled.shift()(); // stale title from an exited store: retry
assert.strictEqual(restored, 0);
assert.strictEqual(scheduled.length, 1);
scheduled.shift()(); // confirmed empty desktop: restore exactly once
assert.strictEqual(restored, 1);
assert.strictEqual(scheduled.length, 0);

const restoreQueue = [];
const restoreResults = [false, true];
let restoreAttempts = 0;
const failedRestoreReconciler = createLauncherRestoreReconciler({
  hasActiveChildren: () => false,
  getWindowTitles: () => [],
  isLauncherHidden: () => true,
  restoreLauncher: () => { restoreAttempts++; return restoreResults.shift(); },
  schedule: fn => { restoreQueue.push(fn); return fn; },
});
failedRestoreReconciler.request();
restoreQueue.shift()();
assert.strictEqual(restoreAttempts, 1);
assert.strictEqual(restoreQueue.length, 1);
restoreQueue.shift()();
assert.strictEqual(restoreAttempts, 2);
assert.strictEqual(restoreQueue.length, 0);

const calls = [];
const resumed = resumeActiveStore({
  activeStoreId: 'steam',
  activeStorePid: 42,
  isWindowVisible: id => { calls.push(`visible:${id}`); return true; },
  focusStore: id => { calls.push(`focus:${id}`); return true; },
  hideLauncher: () => calls.push('hide'),
  notifyVisible: id => calls.push(`notify:${id}`),
  log: line => calls.push(`log:${line}`),
});
assert.deepStrictEqual(resumed, { ok: true, resumed: true, storeId: 'steam', pid: 42 });
assert.deepStrictEqual(calls.slice(0, 4), ['visible:steam', 'focus:steam', 'hide', 'notify:steam']);

const focusFailedCalls = [];
const focusFailed = resumeActiveStore({
  activeStoreId: 'steam',
  isWindowVisible: () => true,
  focusStore: id => { focusFailedCalls.push(`focus:${id}`); return false; },
  hideLauncher: () => focusFailedCalls.push('hide'),
});
assert.deepStrictEqual(focusFailed, {
  ok: false,
  activeStoreId: 'steam',
  error: 'Steam is running but its window could not be focused',
});
assert.deepStrictEqual(focusFailedCalls, ['focus:steam']);

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

main = (ROOT / "launcher" / "src" / "main.js").read_text()
compat = (ROOT / "scripts" / "swaymsg-desktop-compat").read_text()
open_url = (ROOT / "scripts" / "dpad-open-url").read_text()
for required in (
    "const externalUrl = validatedExternalUrl(process.env.ELECTRON_OVERRIDE_URL);",
    "app.setPath('userData'",
    "if (externalUrl) win.loadURL(externalUrl);",
    "preload: externalUrl ? undefined : path.join(__dirname, 'preload.js')",
    "if (externalUrl) app.quit();",
):
    if required not in main:
        raise SystemExit(f"launcher external-browser mode missing: {required}")
if 'ELECTRON_OVERRIDE_URL="$URL"' not in open_url:
    raise SystemExit("dpad-open-url does not pass its validated URL through the override environment")
if '"$ELECTRON" --kiosk' in open_url:
    raise SystemExit("dpad-open-url incorrectly treats the packaged app binary as generic Electron")
if 'nohup "$ELECTRON" --no-sandbox' in open_url:
    raise SystemExit("isolated external browser must not disable Chromium's process sandbox")
for required in (
    "epic: 'heroic'",
    "gog: 'heroic'",
):
    if required not in main:
        raise SystemExit(f"Heroic-backed store focus mapping missing: {required}")
if "'[class=heroic]') APP_ID=heroic" not in compat:
    raise SystemExit("Labwc compatibility wrapper cannot focus the shared Heroic client")
if "'[class=Battle.net.exe]') APP_ID=steam_app_battlenet" not in compat:
    raise SystemExit("Labwc compatibility wrapper cannot focus Battle.net's actual app ID")
if "'[class=EADesktop.exe]') APP_ID=steam_app_eaapp" not in compat:
    raise SystemExit("Labwc compatibility wrapper cannot focus EA App's actual app ID")
for forbidden in (
    "let activeStoreChild = null",
    "let activeStoreId = null",
    "let storeVisibleTimer = null",
):
    if forbidden in main:
        raise SystemExit(f"launcher retains single-store state: {forbidden}")
for required in (
    "const activeStoreChildren = new Map()",
    "const storeVisibleTimers = new Map()",
    "chooseStoreAction({",
):
    if required not in main:
        raise SystemExit(f"launcher missing multi-store state contract: {required}")
if "swaymsg('[title=\"DpadPlay\"] scratchpad show')" not in main:
    raise SystemExit("launcher restoration must target DpadPlay")
if "swaymsg('scratchpad show')" in main:
    raise SystemExit("launcher restoration must not use untargeted scratchpad show")
if "if (configured !== null) {\n      launcherHidden = false;" not in main:
    raise SystemExit("launcher must clear hidden state only after restore policy succeeds")
if "launcherRestoreReconciler.request(); // monitor adopted store closure" not in main:
    raise SystemExit("launcher must monitor adopted store closure")
if "if (!launcherVisibilityGeneration.isCurrent(restoreGeneration))" not in main:
    raise SystemExit("stale restore callbacks must not clear a newer hide generation")
package = json.loads((ROOT / "launcher" / "package.json").read_text())
launcher_dockerfile = (ROOT / "launcher" / "Dockerfile").read_text()
parent_dockerfile = (ROOT / "Dockerfile").read_text()
if package["version"] != "0.1.6":
    raise SystemExit("launcher package version must match release 0.1.6")
if launcher_dockerfile.count("0.1.6") < 2:
    raise SystemExit("launcher Dockerfile example and label must both use 0.1.6")
if "dpadcloud-launcher:0.1.6" not in parent_dockerfile:
    raise SystemExit("parent image must pin launcher 0.1.6")
print("Launcher active-store resume: PASS")
