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
    cmd: ['steam', '-gamepadui'],
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
    bin: null,
    cmd: null,
    comingSoon: true,
    color: '#ff5757',
  },
  {
    id: 'ubisoft',
    name: 'Ubisoft Connect',
    subtitle: 'Ubisoft titles',
    bin: null,
    cmd: null,
    comingSoon: true,
    color: '#0078ff',
  },
];

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
let activeStoreChild = null;   // the current store's child process
let activeStoreId = null;      // the current store's id
let storeVisibleTimer = null;  // poll timer for store window detection

// --- Sway window management ---

// Move the launcher window to the sway scratchpad (hide it) so the store
// client can take over the full output without side-by-side tiling.
function hideLauncherToScratchpad() {
  // Focus the launcher window first (in case it lost focus), then move it.
  if (mainWindow) {
    try { mainWindow.focus(); } catch (_) {}
  }
  // Use [title="DpadPlay"] to match our launcher window (the index.html title).
  // Moving to scratchpad hides it completely — no tiling side-by-side.
  swaymsg('[title="DpadPlay"] move container to scratchpad');
  log('launcher hidden to scratchpad');
}

// Restore the launcher from scratchpad + fullscreen it.
function showLauncherFromScratchpad() {
  swaymsg('scratchpad show');
  // Give sway a moment to map the window, then fullscreen it.
  setTimeout(() => {
    swaymsg('[title="DpadPlay"] fullscreen enable');
    log('launcher restored from scratchpad + fullscreened');
  }, 200);
}

// Check if the store's window has appeared in the sway tree. We poll the
// sway tree for any window that is NOT our launcher — once we see one, the
// store is visible.
function checkStoreWindowVisible(storeId) {
  const output = swaymsg('-t get_tree');
  if (!output) return false;
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
    return storeWindows.length > 0;
  } catch (e) {
    return false;
  }
}

// --- Window lifecycle ---

function createWindow() {
  const win = new BrowserWindow({
    fullscreen: true,
    frame: false,
    autoHideMenuBar: true,
    menuBarVisible: false,
    backgroundColor: '#0c0d11',
    show: true,
    title: 'DpadPlay',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  win.loadFile(path.join(__dirname, 'index.html'));
  if (process.env.DPAD_LAUNCHER_DEV) win.webContents.openDevTools({ mode: 'detach' });

  // The launcher must never die. If its window is closed, recreate it.
  win.on('closed', () => {
    mainWindow = null;
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

  // Don't launch if a store is already running
  if (activeStoreChild) {
    log(`launch-store ${storeId}: another store (${activeStoreId}) is already running`);
    return { ok: false, error: 'another store is already running' };
  }

  log(`launch-store ${storeId}: ${store.cmd.join(' ')}`);
  try {
    const child = spawn(store.cmd[0], store.cmd.slice(1), {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },
    });
    activeStoreChild = child;
    activeStoreId = storeId;

    child.on('error', (e) => {
      log(`launch-store ${storeId} spawn error: ${e.message}`);
      activeStoreChild = null;
      activeStoreId = null;
      // Notify renderer to dismiss overlay + show error
      if (mainWindow) mainWindow.webContents.send('store-launch-failed', storeId, e.message);
    });

    // Poll for the store window appearing in the sway tree. Once visible,
    // hide the launcher to scratchpad + notify the renderer to dismiss the
    // overlay. Timeout after 30s (give up + hide launcher anyway).
    let pollCount = 0;
    const maxPolls = 60; // 60 * 500ms = 30s
    if (storeVisibleTimer) clearInterval(storeVisibleTimer);
    storeVisibleTimer = setInterval(() => {
      pollCount++;
      const visible = checkStoreWindowVisible(storeId);
      if (visible) {
        log(`launch-store ${storeId}: store window detected after ${pollCount * 500}ms`);
        clearInterval(storeVisibleTimer);
        storeVisibleTimer = null;
        hideLauncherToScratchpad();
        // Notify renderer that the store is visible (dismiss overlay)
        if (mainWindow) mainWindow.webContents.send('store-visible', storeId);
      } else if (pollCount >= maxPolls) {
        log(`launch-store ${storeId}: window not detected after 30s, hiding launcher anyway`);
        clearInterval(storeVisibleTimer);
        storeVisibleTimer = null;
        hideLauncherToScratchpad();
        if (mainWindow) mainWindow.webContents.send('store-visible', storeId);
      }
    }, 500);

    // When the store client exits, restore the launcher.
    child.on('exit', (code, sig) => {
      log(`launch-store ${storeId} exited (code=${code} sig=${sig})`);
      if (storeVisibleTimer) { clearInterval(storeVisibleTimer); storeVisibleTimer = null; }
      activeStoreChild = null;
      activeStoreId = null;
      // Restore launcher from scratchpad + fullscreen
      showLauncherFromScratchpad();
      // Notify renderer to dismiss any lingering overlay
      if (mainWindow) mainWindow.webContents.send('store-exited', storeId);
    });

    child.unref();
    return { ok: true, pid: child.pid };
  } catch (e) {
    activeStoreChild = null;
    activeStoreId = null;
    return { ok: false, error: e.message };
  }
});

// Check if a store is currently running (used by the renderer to decide
// whether to show the overlay on focus).
ipcMain.handle('get-active-store', () => {
  return activeStoreId || null;
});

// Kill the active store (called by the "back to launcher" shortcut).
ipcMain.handle('kill-active-store', () => {
  if (!activeStoreChild) return { ok: false, error: 'no store running' };
  log(`kill-active-store: killing ${activeStoreId} (pid ${activeStoreChild.pid})`);
  try {
    process.kill(-activeStoreChild.pid, 'SIGTERM');
  } catch (_) {
    try { activeStoreChild.kill('SIGTERM'); } catch (__) {}
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
  if (!quitting) createWindow();
});