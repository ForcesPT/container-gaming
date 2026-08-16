#!/bin/bash
# Health check for the launcher-only Selkies/Sway desktop.
set -u

if ! pgrep -f "selkies-gstreamer" >/dev/null; then
    echo "UNHEALTHY: selkies-gstreamer is not running"; exit 1
fi
# The server can listen and pass pgrep while its capture plugin is blacklisted;
# that failure only crashes Selkies when the first browser peer starts video.
# Probe the exact factory so a runtime ABI mismatch cannot be reported ready.
if ! ( . /opt/gstreamer/gst-env && gst-inspect-1.0 waylanddisplaysrc >/dev/null 2>&1 ); then
    echo "UNHEALTHY: waylanddisplaysrc is unavailable or blacklisted"; exit 1
fi
if ! pgrep -x "pipewire" >/dev/null || ! pgrep -x "pipewire-pulse" >/dev/null; then
    echo "UNHEALTHY: PipeWire audio is not running"; exit 1
fi
# Sway starts only after a browser peer creates the compositor socket. Once a
# session has a Sway log, its process must remain alive.
if [ -e /tmp/sway-client.log ] && ! pgrep -x "sway" >/dev/null; then
    echo "UNHEALTHY: Sway desktop exited"; exit 1
fi
if command -v nvidia-smi >/dev/null 2>&1 && ! nvidia-smi >/dev/null 2>&1; then
    echo "UNHEALTHY: NVIDIA GPU is inaccessible"; exit 1
fi
echo "HEALTHY"
