#!/bin/bash
# Validate the evdev interposer end-to-end: feeder (new js_config_t protocol) on
# /tmp/selkies_event1000.sock + a C client opening /dev/input/event1000 under the
# new interposer LD_PRELOAD. The interposer translates js_events -> input_events.
set -u
FAKE=/tmp/build/fake-udev
INTERPOSER=/tmp/build/interposer/selkies_joystick_interposer.so
SOCK=/tmp/selkies_event1000.sock

rm -f "$SOCK"
gcc -O2 -o /tmp/evclient /tmp/evclient.c 2>&1 | tail -5
ls -la /tmp/evclient 2>&1

echo "=== start feeder on $SOCK ==="
python3 /tmp/jsfeeder_main.py "$SOCK" >/tmp/feeder2.out 2>&1 &
FEED=$!
sleep 1

echo "=== run evdev client under the interposer ==="
LD_PRELOAD="$INTERPOSER" JS_LOG=0 /tmp/evclient /dev/input/event1000 2>&1 | grep -E "input_event|open|EOF|decoded|FAIL|OK" | tail -12
RC=$?

wait $FEED 2>/dev/null
echo "=== feeder output ==="
cat /tmp/feeder2.out
echo "=== interposer log (selkies_js.log) ==="
cat /tmp/selkies_js.log 2>/dev/null | tail -20
echo "=== client rc=$RC ==="