#!/bin/bash
# Validate the v1.6.2 interposer handles SDL3's CLASSIC joystick probe sequence
# (the simplified path: SDL_JOYSTICK_LINUX_CLASSIC=1 + SDL_JOYSTICK_DEVICE=/dev/input/js0).
# Feeder speaks the v1.6.2 protocol (1348-byte config + js_events) on selkies_js0.sock;
# the C client does open + JSIOCG* probes + read js_events, mimicking SDL3 classic.
set -u
INTERPOSER=/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so
SOCK=/tmp/selkies_js0.sock
rm -f "$SOCK" /tmp/selkies_js.log
gcc -O2 -o /tmp/jsclassic /tmp/jsclassic.c 2>&1 | tail -5
echo "=== start v1.6.2 feeder on $SOCK ==="
python3 /tmp/jsfeeder.py "$SOCK" >/tmp/feeder3.out 2>&1 &
FEED=$!
sleep 1
echo "=== run classic-probe client under v1.6.2 interposer ==="
LD_PRELOAD="$INTERPOSER" /tmp/jsclassic 2>&1 | tail -16
RC=$?
wait $FEED 2>/dev/null
echo "=== feeder ==="; cat /tmp/feeder3.out
echo "=== interposer log ==="; tail -8 /tmp/selkies_js.log 2>/dev/null
echo "=== rc=$RC ==="