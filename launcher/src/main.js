// dpad-launcher — main process
//
// A 10-foot, gamepad/keyboard-navigable store launcher that runs as the sway
// startup app. It shows the installed store clients as cards; selecting one
// spawns that store's client as a detached child IN THE SAME sway/XWayland
// session, so the store runs fullscreen over the launcher + quitting it returns
// here.
//
// Runtime: a Linux Electron AppDir (electron-builder --linux dir), baked into
// the image at /opt/dpadcloud/launcher (or bind-mounted for dev). The
// `scripts/launcher-shell` wrapper execs this binary with the session env
// (DISPLAY=:0, the NVIDIA EGL vendor, the gamepad interposer LD_PRELOAD).

const {
  app,
  BrowserWindow,
  ipcMain,
} = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, execSync } = require('child_process');
const { pollGamepads, mapToWebApi } = require('./sdl_manager.cjs');
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
} = require('./store_lifecycle.cjs');

const launcherPolicy = launcherWindowPolicy(process.env.DPAD_DESKTOP_CLIENT || 'sway');
const focusLauncherBeforeHide = launcherFocusBeforeHide(process.env.DPAD_DESKTOP_CLIENT || 'sway');
const externalUrl = validatedExternalUrl(process.env.ELECTRON_OVERRIDE_URL);
if (externalUrl) {
  // Keep external pages isolated from the store launcher's profile and preload
  // bridge. OAuth/changelog windows only need their own short-lived web session.
  app.setPath('userData', path.join('/tmp', `dpad-browser-${process.pid}`));
}

const USER_HOME = process.env.HOME || '/home/dpad';
const LOG_FILE = path.join('/tmp', 'launcher.log');

// Sway IPC socket — resolve from the runtime dir (the entrypoint sets
// SWAYSOCK or we find it by glob).
function swaySock() {
  if (process.env.SWAYSOCK) return process.env.SWAYSOCK;
  const runtimeDir = process.env.XDG_RUNTIME_DIR || `/run/user/${process.getuid()}`;
  const socks = fs.readdirSync(runtimeDir)
    .filter(f => f.startsWith('sway-ipc.') && f.endsWith('.sock'))
    .map(f => path.join(runtimeDir, f));
  return socks[0] || null;
}

// Run a swaymsg command (best-effort — no throw on failure).
function swaymsg(cmd) {
  const sock = swaySock();
  if (!sock) { log('swaymsg: no sway socket found'); return null; }
  try {
    return execSync(`swaymsg -s ${sock} ${cmd} 2>&1`, { timeout: 3000 }).toString().trim();
  } catch (e) {
    log(`swaymsg ${cmd} failed: ${e.message}`);
    return null;
  }
}

// Store registry. `available` is resolved at runtime by checking the binary
// exists. `comingSoon: true` cards are shown greyed + non-launchable.
const STORES = [
  {
    id: 'steam',
    name: 'Steam',
    subtitle: 'Your Steam library',
    bin: 'steam',
    // Launch Valve's standard desktop Steam client. The DpadPlay launcher is the
    // only session shell; Steam is a store application inside the Sway desktop.
    cmd: ['steam'],
    color: '#66c0f4',
  },
  {
    id: 'battlenet',
    name: 'Battle.net',
    subtitle: 'Blizzard titles',
    bin: 'battlenet-launch',
    cmd: ['battlenet-launch'],
    color: '#00c2ff',
  },
  {
    id: 'epic',
    name: 'Epic Games',
    subtitle: 'Epic store',
    bin: 'epic-launch',
    cmd: ['epic-launch'],
    color: '#f5f5f5',
  },
  {
    id: 'gog',
    name: 'GOG',
    subtitle: 'DRM-free',
    bin: 'gog-launch',
    cmd: ['gog-launch'],
    color: '#a060f5',
  },
  {
    id: 'ea',
    name: 'EA App',
    subtitle: 'Electronic Arts',
    bin: 'ea-launch',
    cmd: ['ea-launch'],
    color: '#ff5757',
  },
  {
    id: 'ubisoft',
    name: 'Ubisoft Connect',
    subtitle: 'Ubisoft titles',
    bin: 'ubisoft-launch',
    cmd: ['ubisoft-launch'],
    color: '#0078ff',
  },
];

// XWayland WM_CLASS values used by native Sway criteria. The Labwc swaymsg
// compatibility wrapper translates this same narrow selector to wlrctl's
// foreign-toplevel app_id matcher.
const STORE_WINDOW_CLASSES = {
  steam: 'steam',
  battlenet: 'Battle.net.exe',
  epic: 'heroic',
  gog: 'heroic',
  ea: 'EADesktop.exe',
  ubisoft: 'upc.exe',
};

function log(line) {
  const stamp = new Date().toISOString();
  const msg = `[${stamp}] ${line}`;
  console.log(msg);
  try { fs.appendFileSync(LOG_FILE, msg + '\n'); } catch (_) {}
}

// Resolve `available` per store by checking the binary on PATH.
function which(bin) {
  if (!bin) return null;
  if (bin.includes('/')) return fs.existsSync(bin) ? bin : null;
  for (const d of (process.env.PATH || '').split(':')) {
    const p = path.join(d, bin);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function resolveStores() {
  const dev = !!process.env.DPAD_LAUNCHER_DEV;
  return STORES.map((s) => ({
    ...s,
    available: !s.comingSoon && (dev ? s.id === 'steam' : !!which(s.bin)),
  }));
}

let mainWindow = null;
let quitting = false;
let launcherHidden = false;
const launcherVisibilityGeneration = createLauncherVisibilityGeneration();
const activeStoreChildren = new Map(); // store id -> detached child process
const storeVisibleTimers = new Map();  // store id -> visibility poll timer

// --- Sway window management ---

// Move the launcher window to the sway scratchpad (hide it) so the store
// client can take over the full output without side-by-side tiling.
function hideLauncherToScratchpad() {
  // Any hide attempt supersedes a delayed restore callback, even if the
  // compositor command itself fails and the previous hidden state is retained.
  launcherVisibilityGeneration.invalidate();
  // Native Sway historically needs DpadPlay focused before moving it to the
  // scratchpad. Labwc's title-targeted minimize does not, and Electron's
  // asynchronous focus request can otherwise steal focus back from the store.
  if (focusLauncherBeforeHide && mainWindow) {
    try { mainWindow.focus(); } catch (_) {}
  }
  // Use [title="DpadPlay"] to match our launcher window (the index.html title).
  // Moving to scratchpad hides it completely — no tiling side-by-side.
  const moved = swaymsg('[title="DpadPlay"] move container to scratchpad');
  const hideSucceeded = moved !== null;
  launcherHidden = nextLauncherHiddenAfterHide(launcherHidden, hideSucceeded);
  log(hideSucceeded ? 'launcher hidden to scratchpad' : 'launcher hide failed; preserving state');
}

// Restore the launcher without hiding Labwc's exclusive-zone taskbar.
function showLauncherFromScratchpad() {
  const shown = swaymsg('[title="DpadPlay"] scratchpad show');
  if (shown === null) {
    log('launcher restore failed; will retry');
    return false;
  }
  const restoreGeneration = launcherVisibilityGeneration.capture();
  // Give the compositor a moment to map the window, then apply its policy.
  setTimeout(() => {
    if (!launcherVisibilityGeneration.isCurrent(restoreGeneration)) {
      log('ignoring stale launcher restore callback');
      return;
    }
    const configured = swaymsg(launcherPolicy.restoreCommand);
    if (configured !== null) {
      launcherHidden = false;
      log(`launcher restored from scratchpad (${launcherPolicy.maximize ? 'maximized' : 'fullscreen'})`);
    } else {
      log('launcher restore policy failed; will retry');
    }
  }, 200);
  // Completion is asynchronous. The reconciler keeps one retry scheduled; it
  // stops when the successful policy command clears launcherHidden.
  return false;
}

const launcherRestoreReconciler = createLauncherRestoreReconciler({
  hasActiveChildren: () => activeStoreChildren.size > 0,
  getWindowTitles: () => getStoreWindowTitles(),
  isLauncherHidden: () => launcherHidden,
  restoreLauncher: () => showLauncherFromScratchpad(),
  schedule: (fn, delay) => {
    const timer = setTimeout(fn, delay);
    if (timer.unref) timer.unref();
    return timer;
  },
});

// Return visible non-launcher window titles from the desktop tree. Keeping the
// titles lets a restarted launcher adopt an already-running store instead of
// losing its in-memory child handle and spawning a duplicate.
function getStoreWindowTitles() {
  const output = swaymsg('-t get_tree');
  if (!output) return null;
  try {
    const tree = JSON.parse(output);
    // Walk the tree looking for any window (leaf node) whose name is not
    // "DpadPlay" (our launcher) and not empty.
    function findStoreWindows(node) {
      let found = [];
      if (node.nodes) {
        for (const child of node.nodes) found = found.concat(findStoreWindows(child));
      }
      if (node.floating_nodes) {
        for (const child of node.floating_nodes) found = found.concat(findStoreWindows(child));
      }
      // Leaf node with a name = a window
      if (node.name && node.name !== 'DpadPlay' && node.type === 'con') {
        found.push(node);
      }
      return found;
    }
    const storeWindows = findStoreWindows(tree);
    return storeWindows.map(node => node.name);
  } catch (e) {
    return null;
  }
}

function checkStoreWindowVisible(storeId) {
  const titles = getStoreWindowTitles();
  return Array.isArray(titles) && detectStoreIdsFromTitles(titles).includes(storeId);
}

function clearStoreVisibleTimer(storeId, owner = null) {
  return clearOwnedTimer(storeVisibleTimers, storeId, owner);
}

function focusStoreWindow(storeId) {
  const windowClass = STORE_WINDOW_CLASSES[storeId];
  if (!windowClass) {
    log(`focus-store ${storeId}: no window class configured`);
    return false;
  }
  return swaymsg(`[class="${windowClass}"] focus`) !== null;
}

// --- Window lifecycle ---

function createWindow() {
  const win = new BrowserWindow({
    fullscreen: externalUrl ? true : launcherPolicy.fullscreen,
    frame: false,
    autoHideMenuBar: true,
    menuBarVisible: false,
    backgroundColor: '#0c0d11',
    show: true,
    title: externalUrl ? 'Dpad Browser' : 'DpadPlay',
    webPreferences: {
      preload: externalUrl ? undefined : path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: Boolean(externalUrl),
    },
  });

  if (externalUrl) win.loadURL(externalUrl);
  else win.loadFile(path.join(__dirname, 'index.html'));
  if (!externalUrl && launcherPolicy.maximize) win.maximize();
  if (process.env.DPAD_LAUNCHER_DEV) win.webContents.openDevTools({ mode: 'detach' });

  // The launcher must never die. If its window is closed, recreate it.
  win.on('closed', () => {
    mainWindow = null;
    if (externalUrl) {
      quitting = true;
      app.quit();
      return;
    }
    if (!quitting) createWindow();
  });

  mainWindow = win;
  return win;
}

// --- Store launch (fix #1 + #2) ---

// Launch a store client. The launcher hides itself to the sway scratchpad
// while the store runs, so there's no side-by-side tiling. The launch overlay
// stays visible in the renderer until the store window actually appears (polled
// via swaymsg), then the launcher window is hidden. When the store exits, the
// launcher is restored from scratchpad + fullscreened.
ipcMain.handle('launch-store', (event, storeId) => {
  const store = STORES.find((s) => s.id === storeId);
  if (!store) return { ok: false, error: 'unknown store' };
  if (store.comingSoon || !store.cmd) return { ok: false, error: 'coming soon / no command' };

  // Resume only the requested store when it already exists. Other stores may
  // remain open concurrently and are independently switchable through Waybar.
  const storeTitles = getStoreWindowTitles();
  const visibleStoreIds = Array.isArray(storeTitles)
    ? detectStoreIdsFromTitles(storeTitles)
    : [];
  const runningStoreIds = Array.from(new Set([
    ...activeStoreChildren.keys(),
    ...visibleStoreIds,
  ]));
  const action = chooseStoreAction({
    requestedStoreId: storeId,
    runningStoreIds,
    snapshotAvailable: Array.isArray(storeTitles),
  });
  if (action.action === 'wait') {
    log(`launch-store ${storeId}: desktop snapshot unavailable; refusing duplicate-risk launch`);
    return {
      ok: false,
      activeStoreId: storeId,
      error: 'Desktop state is temporarily unavailable; try again',
    };
  }
  if (action.action === 'resume') {
    const existingChild = activeStoreChildren.get(storeId);
    const resumed = resumeActiveStore({
      activeStoreId: storeId,
      activeStorePid: existingChild ? existingChild.pid : null,
      isWindowVisible: checkStoreWindowVisible,
      focusStore: focusStoreWindow,
      hideLauncher: hideLauncherToScratchpad,
      notifyVisible: id => {
        if (mainWindow) mainWindow.webContents.send('store-visible', id);
      },
      log,
    });
    if (shouldMonitorAdoptedStore(resumed.ok, Boolean(existingChild))) {
      launcherRestoreReconciler.request(); // monitor adopted store closure
    }
    return resumed;
  }

  log(`launch-store ${storeId}: ${store.cmd.join(' ')}`);
  try {
    const child = spawn(store.cmd[0], store.cmd.slice(1), {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },
    });
    activeStoreChildren.set(storeId, child);

    child.on('error', (e) => {
      log(`launch-store ${storeId} spawn error: ${e.message}`);
      if (activeStoreChildren.get(storeId) === child) activeStoreChildren.delete(storeId);
      clearStoreVisibleTimer(storeId, child);
      // Notify renderer to dismiss overlay + show error
      if (mainWindow) mainWindow.webContents.send('store-launch-failed', storeId, e.message);
    });

    // Poll for the store window appearing in the sway tree. Once visible,
    // hide the launcher to scratchpad + notify the renderer to dismiss the
    // overlay. First-launch installs (EA/Ubisoft/Battle.net) run winetricks
    // + download the installer before any window appears — this can take
    // 5-10 min. Keep the launcher visible with an "Installing…" message
    // so the user gets feedback instead of a black screen.
    let pollCount = 0;
    const POLL_MS = 500;
    const SHORT_TIMEOUT = 30;  // seconds before switching to "installing" message
    const MAX_TIMEOUT = 900;   // 15 min hard cap (give up + hide launcher)
    let installingNotified = false;
    clearStoreVisibleTimer(storeId);
    const storeVisibleTimer = setInterval(() => {
      pollCount++;
      const elapsedSec = Math.round(pollCount * POLL_MS / 1000);
      const visible = checkStoreWindowVisible(storeId);
      if (visible) {
        log(`launch-store ${storeId}: store window detected after ${elapsedSec}s`);
        clearStoreVisibleTimer(storeId, child);
        hideLauncherToScratchpad();
        // Notify renderer that the store is visible (dismiss overlay)
        if (mainWindow) mainWindow.webContents.send('store-visible', storeId);
      } else if (!installingNotified && elapsedSec >= SHORT_TIMEOUT) {
        // No window after 30s — likely a first-launch install. Keep the
        // launcher visible (do NOT hide to scratchpad) and tell the
        // renderer to show an "Installing…" message on the overlay.
        log(`launch-store ${storeId}: no window after ${elapsedSec}s, switching to install overlay`);
        installingNotified = true;
        if (mainWindow) mainWindow.webContents.send('store-installing', storeId);
      } else if (elapsedSec >= MAX_TIMEOUT) {
        log(`launch-store ${storeId}: no window after ${MAX_TIMEOUT}s, giving up`);
        clearStoreVisibleTimer(storeId, child);
        // Last resort: hide launcher. The store may still appear later.
        hideLauncherToScratchpad();
        if (mainWindow) mainWindow.webContents.send('store-visible', storeId);
      }
    }, POLL_MS);
    storeVisibleTimers.set(storeId, { timer: storeVisibleTimer, owner: child });

    // When one store client exits, preserve every other store's lifecycle.
    child.on('exit', (code, sig) => {
      log(`launch-store ${storeId} exited (code=${code} sig=${sig})`);
      clearStoreVisibleTimer(storeId, child);
      if (activeStoreChildren.get(storeId) === child) activeStoreChildren.delete(storeId);
      launcherRestoreReconciler.request();
      // Notify renderer to dismiss any lingering overlay
      if (mainWindow) mainWindow.webContents.send('store-exited', storeId);
    });

    child.unref();
    return { ok: true, pid: child.pid };
  } catch (e) {
    activeStoreChildren.delete(storeId);
    clearStoreVisibleTimer(storeId);
    return { ok: false, error: e.message };
  }
});

// Check if a store is currently running (used by the renderer to decide
// whether to show the overlay on focus).
ipcMain.handle('get-active-store', () => {
  const titles = getStoreWindowTitles();
  return activeStoreChildren.keys().next().value
    || (Array.isArray(titles) ? detectStoreIdFromTitles(titles) : null)
    || null;
});

// Legacy back action terminates one managed store. Normal multi-store switching
// is handled through Waybar and selecting an existing launcher card.
ipcMain.handle('kill-active-store', () => {
  const entry = activeStoreChildren.entries().next().value;
  if (!entry) return { ok: false, error: 'no store running' };
  const [storeId, child] = entry;
  log(`kill-active-store: killing ${storeId} (pid ${child.pid})`);
  try {
    process.kill(-child.pid, 'SIGTERM');
  } catch (_) {
    try { child.kill('SIGTERM'); } catch (__) {}
  }
  return { ok: true };
});

ipcMain.handle('get-stores', () => resolveStores());

// Gamepad via SDL3/koffi
ipcMain.handle('poll-gamepads', () => {
  const pads = pollGamepads();
  return pads ? mapToWebApi(pads) : [];
});

// Quit
ipcMain.handle('quit', () => { quitting = true; app.quit(); });

app.whenReady().then(() => {
  log(`dpad-launcher ready. HOME=${USER_HOME} DISPLAY=${process.env.DISPLAY}`);
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => {
  if (externalUrl) app.quit();
  else if (!quitting) createWindow();
});