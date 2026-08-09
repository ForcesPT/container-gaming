#!/bin/bash
# relaunch the wayland-display probe with the input-fix + 720p-caps bind-mounts.
set -euo pipefail
IP=79.137.11.29
docker rm -f wd-probe 2>/dev/null || true
docker run -d --name wd-probe \
  --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
  --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
  --device /dev/dri \
  --shm-size=2g --ulimit nofile=1048576:1048576 \
  -v /opt/dpadcloud/entrypoint.sh:/opt/dpadcloud/entrypoint.sh:ro \
  -v /opt/dpadcloud/extract-nvrtc.sh:/opt/dpadcloud/extract-nvrtc.sh:ro \
  -v /opt/dpadcloud/dpad_input_patch.py:/usr/local/lib/python3.12/dist-packages/dpad_input_patch.py:ro \
  -p 3478:3478/udp -p 16100:16100 \
  -e DPAD_GAMESCOPE=1 \
  -e DPAD_COMPOSITOR=wayland-display \
  -e DPAD_WAYLAND_CLIENT=sway \
  -e DPAD_STORE_SHELL=steam \
  -e DPAD_TUNNEL=ssh \
  -e DPAD_SELKIES_BIND=0.0.0.0 \
  -e DPAD_COTURN_PORT=3478 \
  -e DPAD_TURN_PUBLIC_IP="$IP" \
  -e DPAD_TURN_UDP_EXTERNAL_PORT=3478 \
  -e SELKIES_BASIC_AUTH_USER=dpad \
  -e SELKIES_BASIC_AUTH_PASSWORD=testpass \
  -e DPAD_INPUT_DEBUG=1 \
  forcespt/dpadcloud-gaming:dpad-SteamOS
echo "[*] relaunched wd-probe. waiting for DPAD_READY (up to 3 min)..."
deadline=$(( $(date +%s) + 180 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if docker logs wd-probe 2>&1 | grep -q '^DPAD_READY '; then
    echo "=== DPAD_READY ==="
    docker logs wd-probe 2>&1 | grep '^DPAD_READY ' | tail -1
    echo "stream: http://$IP:16100 (dpad/testpass)"
    exit 0
  fi
  if ! docker inspect -f '{{.State.Running}}' wd-probe 2>/dev/null | grep -q true; then
    echo "[ERROR] container exited before DPAD_READY:"; docker logs wd-probe 2>&1 | tail -25 | sed 's/^/    /'; exit 1
  fi
  sleep 3
done
echo "[ERROR] timed out waiting for DPAD_READY:"; docker logs wd-probe 2>&1 | tail -30 | sed 's/^/    /'; exit 1