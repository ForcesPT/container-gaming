// dpad-launcher — main process
//
// A 10-foot, gamepad/keyboard-navigable store launcher that runs as the sway
// startup app (where lutris-shell ran before). It shows the installed store
// clients as cards; selecting one spawns that store's client (e.g.
// `steam -gamepadui`) as a detached child IN THE SAME sway/XWayland session,
// so the store runs fullscreen over the launcher + quitting it returns here.
//
// Why a custom picker instead of lutris-gamepad-ui: Lutris is a *library
// aggregator* (it imports installed games via manifest files), so a fresh VM
// shows "no games found" until each store is logged in + synced. We want a
// *store launcher* — a front door that just opens the store client. Steam +
// Battle.net have client binaries we can launch directly; Epic/GOG (no native
// Linux client) will later shell out to legendary/gogdl.
//
// Runtime: a Linux Electron AppDir (electron-builder --linux dir), baked into
// the image at /opt/dpadcloud/launcher (or bind-mounted for dev). The
// `scripts/launcher-shell` wrapper execs this binary with the session env
// (DISPLAY=:0, the NVIDIA EGL vendor, the gamepad interposer LD_PRELOAD).
//
// Gamepad: the renderer uses the Chromium Web Gamepad API first; if it can't
// see the mknod'd /dev/input/jsN pads in-container (the reason lutris-gamepad-ui
// uses SDL3-via-koffi), we add koffi+SDL3 in v2 (see STORES-PLAN §6).

const {
  app,
  BrowserWindow,
  ipcMain,
  shell,
} = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { pollGamepads, mapToWebApi } = require('./sdl_manager.cjs');

// Where the launcher's app data (cached state, logs) lives. On a persistent
// volume this would be symlinked to <vol>/launcher (STORES-PLAN §9 pattern);
// for now use the dpad home.
const USER_HOME = process.env.HOME || '/home/dpad';
const LOG_FILE = path.join('/tmp', 'launcher.log');

// Store registry. `available` is resolved at runtime by checking the binary
// (or launcher path) exists. `cmd` is launched as a detached child inheriting
// the session env (DISPLAY, EGL vendor, audio, the gamepad interposer).
// `comingSoon: true` cards are shown greyed + non-launchable.
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
    bin: null, // launcher path checked at runtime (Wine prefix) — coming soon
    cmd: null,
    comingSoon: true,
    color: '#00c2ff',
  },
  {
    id: 'epic',
    name: 'Epic Games',
    subtitle: 'Epic store',
    bin: 'legendary',
    cmd: null, // legendary is CLI-only; v2 will wire an install/launch UI
    comingSoon: true,
    color: '#f5f5f5',
  },
  {
    id: 'gog',
    name: 'GOG',
    subtitle: 'DRM-free',
    bin: 'gogdl',
    cmd: null,
    comingSoon: true,
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

// Resolve `available` per store by checking the binary on PATH (or an absolute
// path). `comingSoon` stores stay unavailable.
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
    // In dev (local preview, no Steam on PATH) show Steam as available so the
    // UI looks like it will on the VM. On the VM, `steam` is on PATH.
    available: !s.comingSoon && (dev ? s.id === 'steam' : !!which(s.bin)),
  }));
}

function createWindow() {
  const win = new BrowserWindow({
    fullscreen: true,
    frame: false,
    autoHideMenuBar: true,
    menuBarVisible: false,
    backgroundColor: '#0c0d11',
    show: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  win.loadFile(path.join(__dirname, 'index.html'));
  // Don't swallow input; keep the cursor visible (Desktop mode handles
  // pointer lock upstream). F12 devtools disabled in kiosk.
  if (process.env.DPAD_LAUNCHER_DEV) win.webContents.openDevTools({ mode: 'detach' });

  // Re-assert fullscreen when the window regains focus. When a launched store
  // client (Steam) opens fullscreen it takes the output + sway demotes the
  // launcher; when the store quits + sway refocuses the launcher, sway does
  // NOT restore its fullscreen (the for_window rule only fires on map), so the
  // launcher comes back windowed. Re-send the fullscreen hint on focus/restore.
  const refull = () => { try { win.setFullScreen(true); } catch (_) {} };
  win.on('focus', refull);
  win.on('restore', refull);

  return win;
}

// Launch a store client. Spawned detached INHERITING the launcher's env
// (DISPLAY=:0, __EGL_VENDOR_LIBRARY_FILENAMES=nvidia, PULSE_SERVER, the
// gamepad interposer LD_PRELOAD) so it renders into the same sway/XWayland
// session + is captured by the wayland-display compositor. The store runs
// fullscreen over the launcher; quitting it returns to the launcher (still
// running underneath).
ipcMain.handle('launch-store', (event, storeId) => {
  const store = STORES.find((s) => s.id === storeId);
  if (!store) return { ok: false, error: 'unknown store' };
  if (store.comingSoon || !store.cmd) return { ok: false, error: 'coming soon / no command' };
  log(`launch-store ${storeId}: ${store.cmd.join(' ')}`);
  try {
    const child = spawn(store.cmd[0], store.cmd.slice(1), {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },
    });
    child.on('error', (e) => log(`launch-store ${storeId} spawn error: ${e.message}`));
    child.unref();
    return { ok: true, pid: child.pid };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

ipcMain.handle('get-stores', () => resolveStores());

// Gamepad via SDL3/koffi (the Web Gamepad API doesn't see the mknod'd pads
// in-container). Returns [] shaped like navigator.getGamepads() entries so the
// renderer reuses one navigation path.
ipcMain.handle('poll-gamepads', () => {
  const pads = pollGamepads();
  return pads ? mapToWebApi(pads) : [];
});

// Quit (e.g. the user hits a "Exit" entry). The entrypoint health loop will
// relaunch the shell on the next compositor socket — but normally the shell
// stays for the session; quitting is only for dev.
ipcMain.handle('quit', () => { app.quit(); });

app.whenReady().then(() => {
  log(`dpad-launcher ready. HOME=${USER_HOME} DISPLAY=${process.env.DISPLAY}`);
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => {
  // No macOS here; just quit. The health loop relaunches on the next session.
  app.quit();
});