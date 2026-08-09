// sdl_bindings.cjs — koffi bindings for the SDL3 gamepad API.
// Ported from lutris-gamepad-ui's src_backend/sdl_bindings.cjs (the proven
// in-container gamepad path — the Web Gamepad API does NOT see the mknod'd
// /dev/input/jsN pads without udev, so we poll SDL3 directly via koffi in the
// main process + ship the state to the renderer over IPC).
// Requires libSDL3.so.0 on the system lib path (baked into the dpad-SteamOS
// image by the sdl3-builder stage) + the classic-joystick interposer env the
// entrypoint sets (SDL_JOYSTICK_LINUX_CLASSIC=1, SDL_JOYSTICK_DISABLE_UDEV=1,
// SDL_JOYSTICK_DEVICE=/dev/input/js0, LD_PRELOAD=selkies_joystick_interposer.so).

const SDL3_LIBRARY_NAME = ['libSDL3.so.0', 'libSDL3.so'];

function configureKoffiSdl(koffi) {
  koffi.alias('Uint8', 'uint8_t');
  koffi.alias('Uint16', 'uint16_t');
  koffi.alias('Uint32', 'uint32_t');
  koffi.alias('Sint16', 'int16_t');
  koffi.alias('SDL_JoystickID', 'uint32_t');
  koffi.pointer('SDL_Gamepad', koffi.opaque());
}

function bindSDL3(lib) {
  return {
    SDL_INIT_GAMEPAD: 0x00002000,
    SDL_GAMEPAD_AXIS_COUNT: 6,
    SDL_GAMEPAD_BUTTON_COUNT: 15,

    SDL_Init: lib.func('bool SDL_Init(Uint32 flags)'),
    SDL_Quit: lib.func('void SDL_Quit(void)'),

    SDL_AddGamepadMapping: lib.func('bool SDL_AddGamepadMapping(const char* mappingString)'),

    SDL_GetGamepads: lib.func('SDL_JoystickID* SDL_GetGamepads(int* count)'),
    SDL_free: lib.func('void SDL_free(void* mem)'),

    SDL_IsGamepad: lib.func('bool SDL_IsGamepad(SDL_JoystickID instance_id)'),
    SDL_OpenGamepad: lib.func('SDL_Gamepad* SDL_OpenGamepad(SDL_JoystickID instance_id)'),
    SDL_CloseGamepad: lib.func('void SDL_CloseGamepad(SDL_Gamepad* gamepad)'),
    SDL_GamepadConnected: lib.func('bool SDL_GamepadConnected(SDL_Gamepad* gamepad)'),

    SDL_UpdateGamepads: lib.func('void SDL_UpdateGamepads(void)'),
    SDL_PumpEvents: lib.func('void SDL_PumpEvents(void)'),

    SDL_GetGamepadAxis: lib.func('Sint16 SDL_GetGamepadAxis(SDL_Gamepad* gamepad, int axis)'),
    SDL_GetGamepadButton: lib.func('Uint8 SDL_GetGamepadButton(SDL_Gamepad* gamepad, int button)'),
    SDL_GetGamepadName: lib.func('const char* SDL_GetGamepadName(SDL_Gamepad* gamepad)'),
  };
}

module.exports = { bindSDL3, SDL3_LIBRARY_NAME, configureKoffiSdl };