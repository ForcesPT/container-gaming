#!/bin/bash
echo "=== interposer .so present? ==="
ls -la /usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so 2>/dev/null
ls -la /usr/lib64/selkies_joystick_interposer.so 2>/dev/null
echo "=== steam pid + LD_PRELOAD/SDL_JOYSTICK/SELKIES_INTERPOSER (as dpad) ==="
P=$(pgrep -x steam | head -1)
echo "steam pid=$P"
su -s /bin/bash dpad -c "tr '\0' '\n' < /proc/$P/environ 2>/dev/null | grep -E '^LD_PRELOAD=|^SDL_JOYSTICK_DEVICE=|^SDL_JOYSTICK_LINUX_CLASSIC=|^SDL_JOYSTICK_DISABLE_UDEV=|^SDL_GAMECONTROLLERCONFIG=|^SELKIES_INTERPOSER='"
echo "=== interposer mapped into steam? ==="
grep -q selkies_joystick /proc/$P/maps 2>/dev/null && echo "MAPPED" || echo "NOT mapped"