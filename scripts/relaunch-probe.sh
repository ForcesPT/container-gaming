#!/bin/bash
# Relaunch the launcher-only production probe with input diagnostics.
set -euo pipefail
IP="${VM_IP:-79.137.11.29}"
DPAD_INPUT_DEBUG=1 VM_IP="$IP" NAME=launcher-probe \
  bash "$(dirname "$0")/wayland-display-probe.sh"
