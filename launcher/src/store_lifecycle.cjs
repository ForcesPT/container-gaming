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
  for (const title of titles) {
    for (const [storeId, pattern] of STORE_TITLE_PATTERNS) {
      if (pattern.test(title)) return storeId;
    }
  }
  return null;
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

module.exports = { detectStoreIdFromTitles, resumeActiveStore };
