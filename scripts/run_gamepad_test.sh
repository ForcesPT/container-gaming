#!/bin/bash
# Validate the Selkies v1.6.2 joystick interposer end-to-end inside the container.
# Feeder (python) serves the js_config + events on /tmp/selkies_js0.sock; the C
# client opens /dev/input/js0 under LD_PRELOAD and reads js_event structs.
set -u
cd /tmp
rm -f /tmp/selkies_js0.sock /tmp/selkies_js.log
gcc -O2 -o /tmp/jsclient /tmp/jsclient.c 2>&1 || { echo "GCC_FAIL"; exit 2; }

# Start the feeder in the background; it waits up to 20s for the interposer.
python3 /tmp/jsfeeder.py >/tmp/feeder.out 2>&1 &
FEED=$!
# Give the feeder a moment to bind+listen BEFORE the client opens js0 (the
# interposer only retries connect for 250ms).
sleep 1

echo "=== running C client with interposer (LD_PRELOAD) ==="
LD_PRELOAD=/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so \
SELKIES_INTERPOSER=/usr/lib/x86_64-linux-gnu/selkies_joystick_interposer.so \
  /tmp/jsclient /dev/input/js0
RC=$?

wait $FEED 2>/dev/null
echo "=== feeder output ==="
cat /tmp/feeder.out
echo "=== interposer log (/tmp/selkies_js.log) ==="
cat /tmp/selkies_js.log 2>/dev/null || echo "(no interposer log)"
echo "=== client rc=$RC ==="
exit $RC