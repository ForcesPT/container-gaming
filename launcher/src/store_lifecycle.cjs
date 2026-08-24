'use strict';

const STORE_NAMES = {
  steam: 'Steam',
  battlenet: 'Battle.net',
  epic: 'Epic',
  gog: 'GOG',
  ea: 'EA App',
  ubisoft: 'Ubisoft Connect',
};

const STORE_TITLE_PATTERNS = [
  ['steam', /steam/i],
  ['battlenet', /battle\.net|blizzard/i],
  ['epic', /epic games/i],
  ['gog', /\bgog\b|galaxy/i],
  ['ea', /\bea app\b|electronic arts/i],
  ['ubisoft', /ubisoft/i],
];

function detectStoreIdFromTitles(titles) {
  return detectStoreIdsFromTitles(titles)[0] || null;
}

function detectStoreIdsFromTitles(titles) {
  const found = [];
  for (const title of titles) {
    for (const [storeId, pattern] of STORE_TITLE_PATTERNS) {
      if (pattern.test(title) && !found.includes(storeId)) found.push(storeId);
    }
  }
  return found;
}

function chooseStoreAction({ requestedStoreId, runningStoreIds = [], snapshotAvailable = true }) {
  return {
    action: runningStoreIds.includes(requestedStoreId)
      ? 'resume'
      : (snapshotAvailable ? 'launch' : 'wait'),
    storeId: requestedStoreId,
  };
}

function clearOwnedTimer(timerMap, storeId, owner, clearTimer = clearInterval) {
  const record = timerMap.get(storeId);
  if (!record || (owner && record.owner !== owner)) return false;
  clearTimer(record.timer);
  timerMap.delete(storeId);
  return true;
}

function nextLauncherHiddenAfterHide(currentHidden, hideSucceeded) {
  return hideSucceeded ? true : currentHidden;
}

function launcherWindowPolicy(desktopClient) {
  if (desktopClient === 'labwc') {
    return {
      fullscreen: false,
      maximize: true,
      restoreCommand: '[title="DpadPlay"] maximize enable',
    };
  }
  return {
    fullscreen: true,
    maximize: false,
    restoreCommand: '[title="DpadPlay"] fullscreen enable',
  };
}

function shouldMonitorAdoptedStore(resumeSucceeded, hasManagedChild) {
  return resumeSucceeded && !hasManagedChild;
}

function createLauncherVisibilityGeneration() {
  let generation = 0;
  return {
    invalidate() {
      generation += 1;
      return generation;
    },
    capture() {
      return generation;
    },
    isCurrent(token) {
      return token === generation;
    },
  };
}

function createLauncherRestoreReconciler({
  hasActiveChildren,
  getWindowTitles,
  isLauncherHidden,
  restoreLauncher,
  schedule = (fn, delay) => setTimeout(fn, delay),
  retryMs = 500,
}) {
  let pending = null;

  const reconcile = () => {
    pending = null;
    if (!isLauncherHidden() || hasActiveChildren()) return;

    const titles = getWindowTitles();
    if (Array.isArray(titles) && titles.length === 0) {
      if (restoreLauncher() === true) return;
    }

    // Unavailable and non-empty snapshots are both inconclusive. Keep polling
    // until the compositor confirms that no non-launcher window remains.
    pending = schedule(reconcile, retryMs);
  };

  return {
    request() {
      if (pending !== null || !isLauncherHidden()) return;
      pending = schedule(reconcile, retryMs);
    },
  };
}

/**
 * Resume a visible store that is already owned by the launcher.
 *
 * Returns null when no store is active, an ok result after restoring the
 * existing window, or a bounded waiting error while a first-launch installer
 * has not created a window yet. Dependencies are injected so this policy stays
 * deterministic and testable outside Electron.
 */
function resumeActiveStore({
  activeStoreId,
  activeStorePid = null,
  isWindowVisible = () => false,
  focusStore = () => false,
  hideLauncher = () => {},
  notifyVisible = () => {},
  log = () => {},
}) {
  if (!activeStoreId) return null;

  if (!isWindowVisible(activeStoreId)) {
    log(`resume-store ${activeStoreId}: window not visible yet`);
    const name = STORE_NAMES[activeStoreId] || activeStoreId;
    return {
      ok: false,
      activeStoreId,
      error: `${name} is still starting; its window will open automatically`,
    };
  }

  // Focusing must succeed before the launcher is hidden. Labwc does not
  // reliably transfer focus when a fullscreen toplevel is merely minimized,
  // so hiding first can leave the user with no visible store or launcher.
  if (!focusStore(activeStoreId)) {
    log(`resume-store ${activeStoreId}: failed to focus existing store window`);
    const name = STORE_NAMES[activeStoreId] || activeStoreId;
    return {
      ok: false,
      activeStoreId,
      error: `${name} is running but its window could not be focused`,
    };
  }

  hideLauncher();
  notifyVisible(activeStoreId);
  log(`resume-store ${activeStoreId}: focused existing store window`);
  return {
    ok: true,
    resumed: true,
    storeId: activeStoreId,
    pid: activeStorePid,
  };
}

module.exports = {
  detectStoreIdFromTitles,
  detectStoreIdsFromTitles,
  chooseStoreAction,
  clearOwnedTimer,
  createLauncherRestoreReconciler,
  nextLauncherHiddenAfterHide,
  launcherWindowPolicy,
  shouldMonitorAdoptedStore,
  createLauncherVisibilityGeneration,
  resumeActiveStore,
};
