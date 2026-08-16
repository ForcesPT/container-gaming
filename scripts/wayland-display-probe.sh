#!/bin/bash
# Probe the production launcher-only desktop on a GPU VM.
set -euo pipefail

VM_IP="${VM_IP:?VM_IP is required (public IP for TURN)}"
IMAGE="${IMAGE:-forcespt/dpadcloud-gaming:dpad-SteamOS}"
PASS="${PASS:-testpass}"
NAME="${NAME:-launcher-probe}"
PORT="${PORT:-3478}"
SELKIES_PORT="${SELKIES_PORT:-16100}"

docker rm -f "$NAME" 2>/dev/null || true
entry_mount=()
[ -f /opt/dpadcloud/entrypoint.sh ] && entry_mount+=( -v /opt/dpadcloud/entrypoint.sh:/opt/dpadcloud/entrypoint.sh:ro )
[ -f /opt/dpadcloud/extract-nvrtc.sh ] && entry_mount+=( -v /opt/dpadcloud/extract-nvrtc.sh:/opt/dpadcloud/extract-nvrtc.sh:ro )

docker run -d --name "$NAME" \
    --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --device /dev/dri --shm-size=2g --ulimit nofile=1048576:1048576 \
    "${entry_mount[@]}" \
    -p "${PORT}:${PORT}/udp" -p "${SELKIES_PORT}:${SELKIES_PORT}" \
    -e DPAD_SELKIES_BIND=0.0.0.0 \
    -e DPAD_COTURN_PORT="$PORT" \
    -e DPAD_TURN_PUBLIC_IP="$VM_IP" \
    -e DPAD_TURN_UDP_EXTERNAL_PORT="$PORT" \
    -e SELKIES_BASIC_AUTH_USER=dpad \
    -e "SELKIES_BASIC_AUTH_PASSWORD=$PASS" \
    "$IMAGE"

echo "[*] Waiting for launcher desktop readiness..."
deadline=$(( $(date +%s) + 180 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    if docker logs "$NAME" 2>&1 | grep -q '^DPAD_READY '; then
        docker logs "$NAME" 2>&1 | grep '^DPAD_READY ' | tail -1
        echo "Open http://$VM_IP:$SELKIES_PORT (dpad/$PASS)."
        echo "The DpadPlay launcher must appear; choose Steam to open Valve's desktop client."
        exit 0
    fi
    if ! docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null | grep -q true; then
        echo "[ERROR] container exited before readiness" >&2
        docker logs "$NAME" 2>&1 | tail -40 >&2
        exit 1
    fi
    sleep 3
done
echo "[ERROR] timed out waiting for readiness" >&2
docker logs "$NAME" 2>&1 | tail -40 >&2
exit 1
