#!/bin/bash
set -u
cd /tmp
gcc -shared -fPIC -O2 -ldl -o selkies_joystick_interposer_patched.so ji_patched.c 2>&1 | tail -3
ls -la selkies_joystick_interposer_patched.so
echo "=== SDL3 GUID test with PATCHED interposer (as dpad) ==="
su -s /bin/bash dpad -c "SDL_JOYSTICK_LINUX_CLASSIC=1 SDL_JOYSTICK_DISABLE_UDEV=1 SDL_JOYSTICK_DEVICE=/dev/input/js1 LD_PRELOAD=/tmp/selkies_joystick_interposer_patched.so LD_LIBRARY_PATH=/tmp ./sdl3_guid_test" 2>&1 | head -14
echo "=== interposer log tail ==="
tail -4 /tmp/selkies_js.log 2>/dev/null