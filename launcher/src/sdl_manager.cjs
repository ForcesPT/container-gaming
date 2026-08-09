// sdl_manager.cjs — init SDL3 (koffi) + poll gamepads, returning them in the
// Web Gamepad API shape so the renderer's existing navigation logic is reused.
// Ported from lutris-gamepad-ui's sdl_manager.cjs; drops its utils.cjs +
// gamecontrollerdb.txt deps (we rely on the SDL_GAMECONTROLLERCONFIG env the
// entrypoint sets — the "Selkies Controller" mapping — instead of a bundled db).

const fs = require('fs');
const { bindSDL3, SDL3_LIBRARY_NAME, configureKoffiSdl } = require('./sdl_bindings.cjs');

const LOG_FILE = '/tmp/launcher-sdl.log';
function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  try { fs.appendFileSync(LOG_FILE, line + '\n'); } catch (_) {}
}

const HANDLE = { value: null, loadError: null };

function getSdlHandle() {
  if (HANDLE.value) return HANDLE.value;
  if (HANDLE.loadError) return null;
  try {
    const koffi = require('koffi');
    configureKoffiSdl(koffi);
    for (const name of SDL3_LIBRARY_NAME) {
      try {
        const lib = koffi.load(name);
        const sdl = bindSDL3(lib);
        if (!sdl.SDL_Init(sdl.SDL_INIT_GAMEPAD)) throw new Error('SDL_Init(GAMEPAD) failed');
        // The entrypoint sets SDL_GAMECONTROLLERCONFIG (the Selkies mapping);
        // SDL3 reads it at init. Also feed it explicitly if present (idempotent).
        const envMap = process.env.SDL_GAMECONTROLLERCONFIG;
        if (envMap) { try { sdl.SDL_AddGamepadMapping(envMap); } catch (_) {} }
        log(`SDL3 initialized! ${name} (SDL_GAMECONTROLLERCONFIG=${envMap ? 'set' : 'unset'})`);
        const activeControllers = new Map();
        process.on('exit', () => {
          for (const ptr of activeControllers.values()) if (ptr) sdl.SDL_CloseGamepad(ptr);
          activeControllers.clear();
          sdl.SDL_Quit();
        });
        HANDLE.value = { sdl, activeControllers, koffi };
        return HANDLE.value;
      } catch (e) { log(`load ${name} failed: ${e.message}`); }
    }
    HANDLE.loadError = new Error('Unable to load SDL3');
    log('FATAL: Unable to load SDL3 (libSDL3.so.0 missing?)');
    return null;
  } catch (e) {
    HANDLE.loadError = e;
    log(`FATAL koffi load: ${e.message}`);
    return null;
  }
}

function pollGamepadsWithHandle({ sdl, activeControllers, koffi }) {
  sdl.SDL_PumpEvents();
  sdl.SDL_UpdateGamepads();
  const countPtr = new Int32Array(1);
  const gamepadsPtr = sdl.SDL_GetGamepads(countPtr);
  const num = countPtr[0];
  const currentIds = new Set();
  if (gamepadsPtr) {
    try {
      const ids = koffi.decode(gamepadsPtr, 'SDL_JoystickID', num);
      for (let i = 0; i < num; i++) currentIds.add(ids[i]);
    } finally {
      sdl.SDL_free(gamepadsPtr);
    }
  }
  for (const [id, ptr] of activeControllers.entries()) {
    if (!currentIds.has(id) || !sdl.SDL_GamepadConnected(ptr)) {
      sdl.SDL_CloseGamepad(ptr); activeControllers.delete(id);
    }
  }
  const out = [];
  for (const id of currentIds) {
    let ptr = activeControllers.get(id);
    if (!ptr && sdl.SDL_IsGamepad(id)) {
      ptr = sdl.SDL_OpenGamepad(id);
      if (ptr) activeControllers.set(id, ptr);
    }
    if (ptr) {
      if (!sdl.SDL_GamepadConnected(ptr)) { sdl.SDL_CloseGamepad(ptr); activeControllers.delete(id); continue; }
      const axes = [];
      const buttons = [];
      for (let a = 0; a < sdl.SDL_GAMEPAD_AXIS_COUNT; a++) {
        const raw = sdl.SDL_GetGamepadAxis(ptr, a);
        axes.push(Math.max(-1, Math.min(1, raw / 32767)));
      }
      for (let b = 0; b < sdl.SDL_GAMEPAD_BUTTON_COUNT; b++) buttons.push(sdl.SDL_GetGamepadButton(ptr, b) === 1);
      out.push({ index: id, axes, buttons });
    }
  }
  return out;
}

function pollGamepads() {
  const h = getSdlHandle();
  return h ? pollGamepadsWithHandle(h) : null;
}

// SDL3 -> W3C Standard Gamepad mapping (same as lutris-gamepad-ui).
const BUTTON_MAPPING = [
  { type: 'button', index: 0 },  // A
  { type: 'button', index: 1 },  // B
  { type: 'button', index: 2 },  // X
  { type: 'button', index: 3 },  // Y
  { type: 'button', index: 9 },  // L1
  { type: 'button', index: 10 }, // R1
  { type: 'axis', index: 4 },    // L2
  { type: 'axis', index: 5 },    // R2
  { type: 'button', index: 4 },  // Back
  { type: 'button', index: 6 },  // Start
  { type: 'button', index: 7 },  // L3
  { type: 'button', index: 8 },  // R3
  { type: 'button', index: 11 }, // Dpad Up
  { type: 'button', index: 12 }, // Dpad Down
  { type: 'button', index: 13 }, // Dpad Left
  { type: 'button', index: 14 }, // Dpad Right
  { type: 'button', index: 5 },  // Guide
];
const AXIS_MAPPING = [0, 1, 2, 3];

function mapToWebApi(gamepads) {
  return gamepads.map((gp) => ({
    index: gp.index,
    mapping: 'standard',
    buttons: BUTTON_MAPPING.map((m) => {
      if (m.type === 'button') {
        const pressed = gp.buttons[m.index] || false;
        return { pressed, value: pressed ? 1 : 0 };
      }
      const value = Math.max(0, gp.axes[m.index] || 0);
      return { pressed: value > 0.1, value };
    }),
    axes: AXIS_MAPPING.map((idx) => gp.axes[idx] || 0),
  }));
}

module.exports = { pollGamepads, mapToWebApi };