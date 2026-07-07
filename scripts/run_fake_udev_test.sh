#!/bin/bash
# Validate the fake-libudev + evdev interposer combo for Steam-in-container
# gamepad support (Phase 2). Creates dummy /dev/input nodes, compiles a minimal
# libudev enumeration test (mimics SDL3's gamepad discovery), and confirms the
# fake library makes the test "see" the 4 virtual XBox pads.
set -u
FAKE=/tmp/build/fake-udev
INTERPOSER=/tmp/build/interposer/selkies_joystick_interposer.so

echo "=== fix dummy /dev/input nodes (char devices, not touched files) ==="
mkdir -pm1777 /dev/input
for i in 0 1 2 3; do rm -f "/dev/input/js$i"; mknod "/dev/input/js$i" c 13 "$i"; done
for i in 0 1 2 3; do n=$((1000+i)); m=$((64+n)); rm -f "/dev/input/event$n"; mknod "/dev/input/event$n" c 13 "$m"; done
chmod 666 /dev/input/js* /dev/input/event100* 2>/dev/null || true
ls -la /dev/input/ | tail -10

echo "=== compile udev enumeration test against fake libudev ==="
gcc -I"$FAKE" -O2 -o /tmp/udev_test /tmp/udev_enumerate_test.c -L"$FAKE" -ludev 2>&1 | tail -8
ls -la /tmp/udev_test 2>&1

echo "=== baseline: real udev (no LD_PRELOAD) — expect 0 gamepads in this no-udev container ==="
/tmp/udev_test 2>&1 | tail -6 || echo "baseline_rc=$?"

echo "=== WITH fake-libudev LD_PRELOAD — expect 4 XBox pads discovered ==="
LD_PRELOAD="$FAKE/libudev.so.1" /tmp/udev_test 2>&1 | grep -E "found device|discovered|FAIL|OK" | tail -12
echo "rc=$?"