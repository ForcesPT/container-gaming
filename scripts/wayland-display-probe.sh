#!/bin/bash
# wayland-display-probe.sh — Step 2a probe launcher for the gst-wayland-display
# compositor path (WAYLAND-ARCHITECTURE.md §14). Run ON THE VM (after
# vm-bootstrap.sh install) as root. Launches a probe container with
# DPAD_COMPOSITOR=wayland-display + DPAD_GAMESCOPE=1 so the entrypoint's new
# start_wayland_display_session() gate runs the inverted boot order:
#   selkies (waylanddisplaysrc compositor) FIRST  →  DPAD_READY (listening)
#   →  browser connects  →  compositor starts  →  wayland-N socket appears
#   →  gamescope --backend wayland -- steam -gamepadui  →  video (~30-40s).
#
# This validates the RUNTIME selkies patch (patch_selkies_waylanddisplay.py) —
# the §13.14 live validation proved the compositor+capture+gamescope-as-client
# via gst-launch, but NOT through selkies' webrtcbin (which builds the pipeline
# only on a peer's video request). The gate is: the browser shows m=video:2
# (vs m=video:0 for the broken Lutris-under-gamescope-headless case, §17.3) +
# Steam Big Picture renders (not black).
#
# Usage (on the VM, as root, after vm-bootstrap):
#   VM_IP=<public-ip> bash /opt/dpadcloud/wayland-display-probe.sh
#   # then open http://$VM_IP:16100 (login dpad/testpass) in a browser
#   # watch: docker logs -f wd-probe
#   # teardown: docker rm -f wd-probe
#
# Env:
#   VM_IP            the VM public IP (for TURN) — REQUIRED
#   IMAGE            the image tag (default: forcespt/dpadcloud-gaming:dpad-SteamOS)
#                    use dpad-SteamOS-wd-spike for the spike tag with the plugin baked
#   PASS             the selkies basic-auth password (default: testpass)
#   SHELL            steam (default) | lutris (validates the §17.3 Lutris capture fix)
#   EXTRA_ENV        extra -e flags (e.g. DPAD_LUTRIS_DISABLE_GPU=1 for the probe)
set -euo pipefail

VM_IP="${VM_IP:?VM_IP is required (the VM public IP for TURN)}"
IMAGE="${IMAGE:-forcespt/dpadcloud-gaming:dpad-SteamOS}"
PASS="${PASS:-testpass}"
SHELL_SEL="${SHELL:-steam}"
NAME="wd-probe"
PORT=3478
SELKIES_PORT=16100

echo "[*] Launching wayland-display probe container:"
echo "    image:   $IMAGE"
echo "    shell:   $SHELL_SEL"
echo "    stream:  http://$VM_IP:$SELKIES_PORT (login dpad/$PASS)"
echo "    VM IP:   $VM_IP (coturn UDP $PORT)"

# Tear down any prior probe container.
docker rm -f "$NAME" 2>/dev/null || true

# The flags mirror dpad-launch-session's docker run (CDI per-GPU isolation,
# SYS_ADMIN+unconfined for userns, --device /dev/dri for the compositor's raw
# render-node open, shm-size for CEF, coturn+selkies ports) + the entrypoint
# bind-mount hotfix (the image's baked entrypoint predates the DPAD_COMPOSITOR
# gate; vm-bootstrap fetches entrypoint.sh from repo main to /opt/dpadcloud/).
# If /opt/dpadcloud/entrypoint.sh is absent, the image's baked entrypoint runs
# (the DPAD_COMPOSITOR gate is missing → falls through to gamescope-headless).
entry_mount=()
[ -f /opt/dpadcloud/entrypoint.sh ] \
    && entry_mount+=( -v /opt/dpadcloud/entrypoint.sh:/opt/dpadcloud/entrypoint.sh:ro )
[ -f /opt/dpadcloud/extract-nvrtc.sh ] \
    && entry_mount+=( -v /opt/dpadcloud/extract-nvrtc.sh:/opt/dpadcloud/extract-nvrtc.sh:ro )

docker run -d --name "$NAME" \
    --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0 \
    --cap-add SYS_ADMIN --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
    --device /dev/dri \
    --shm-size=2g --ulimit nofile=1048576:1048576 \
    "${entry_mount[@]}" \
    -p "${PORT}:${PORT}/udp" \
    -p "${SELKIES_PORT}:${SELKIES_PORT}" \
    -e DPAD_GAMESCOPE=1 \
    -e DPAD_COMPOSITOR=wayland-display \
    -e DPAD_STORE_SHELL="$SHELL_SEL" \
    -e DPAD_TUNNEL=ssh \
    -e DPAD_SELKIES_BIND=0.0.0.0 \
    -e DPAD_COTURN_PORT="$PORT" \
    -e DPAD_TURN_PUBLIC_IP="$VM_IP" \
    -e DPAD_TURN_UDP_EXTERNAL_PORT="$PORT" \
    -e SELKIES_BASIC_AUTH_USER=dpad \
    -e "SELKIES_BASIC_AUTH_PASSWORD=$PASS" \
    ${EXTRA_ENV:+-e "$EXTRA_ENV"} \
    "$IMAGE"

echo ""
echo "[*] Container launched. Watching for DPAD_READY (selkies listening)..."
echo "    (DPAD_READY fires when selkies is LISTENING — before gamescope, since"
echo "     the compositor starts only when a browser peer connects.)"
echo ""

# Tail until DPAD_READY or 3 min.
deadline=$(( $(date +%s) + 180 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    if docker logs "$NAME" 2>&1 | grep -q '^DPAD_READY '; then
        echo "=== DPAD_READY ==="
        docker logs "$NAME" 2>&1 | grep '^DPAD_READY ' | tail -1
        echo ""
        echo "=== PROBE GATE (open the browser + connect) ==="
        echo "  1. Open http://$VM_IP:$SELKIES_PORT (login dpad/$PASS)."
        echo "  2. Watch 'docker logs -f $NAME' for:"
        echo "       'Compositor socket wayland-N appeared (peer connected)'"
        echo "       'launching gamescope --backend wayland -- $SHELL_SEL'"
        echo "  3. GATE: the browser should show video (Steam Big Picture, not black)"
        echo "     within ~30-40s of connecting. Check the SDP + compositor logs:"
        echo "       docker logs $NAME 2>&1 | grep -E 'm=video|waylanddisplaysrc|nvrtc: error'"
        echo "       m=video:2 = video track negotiated (SUCCESS)"
        echo "       m=video:0 = no video track (the pivot did NOT fix §17.3)"
        echo "       nvrtc: error count = 0 (NVRTC moot on CUDAMemory, §13.14)"
        echo "  4. GST_DEBUG detail (optional): restart selkies inside the container with"
        echo "       GST_DEBUG=waylanddisplaysrc:5,nvh264enc:5 to trace caps negotiation"
        echo "       + CUDAMemory zero-copy (look for 'memory:CUDAMemory' caps)."
        echo ""
        echo "  Teardown: docker rm -f $NAME"
        exit 0
    fi
    # Container died?
    if ! docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null | grep -q true; then
        echo "[ERROR] container $NAME exited before DPAD_READY — last logs:"
        docker logs "$NAME" 2>&1 | tail -30 | sed 's/^/    /'
        exit 1
    fi
    sleep 3
done
echo "[ERROR] timed out waiting for DPAD_READY (3 min) — last logs:"
docker logs "$NAME" 2>&1 | tail -40 | sed 's/^/    /'
exit 1
