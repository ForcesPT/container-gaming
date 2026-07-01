#!/bin/bash
# Health check for container orchestrators.

# Xvfb (virtual display) must be up
if ! pgrep -x "Xvfb" >/dev/null; then
    echo "UNHEALTHY: Xvfb not running"; exit 1
fi
# PipeWire (audio) must be up
if ! pgrep -x "pulseaudio" >/dev/null; then
    echo "UNHEALTHY: pulseaudio not running"; exit 1
fi
# At least one streaming host must be up (Selkies for browser, Sunshine for native)
if ! pgrep -f "selkies-gstreamer" >/dev/null && ! pgrep -x "sunshine" >/dev/null; then
    echo "UNHEALTHY: no streamer running (Selkies or Sunshine)"; exit 1
fi
# GPU access (soft — container still streams via software encode if missing)
if command -v nvidia-smi >/dev/null 2>&1 && ! nvidia-smi >/dev/null 2>&1; then
    echo "WARNING: nvidia-smi failed (GPU driver issue)"; fi
echo "HEALTHY"; exit 0