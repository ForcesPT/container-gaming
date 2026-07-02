#!/bin/bash
# =============================================================================
# DpadCloud Container Gaming — Quick Deploy Script
# Ubuntu 24.04 + CUDA 12.5.1 (wide Vast pool preserved via CUDA minor-version
# compatibility: a 12.5 image runs on any driver >=525). A 12.8.1 variant for
# RTX 50/Blackwell can be built with --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8.
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

COMMAND="${1:-up}"
IMAGE_NAME="dpadcloud/gaming"
TAG="ubuntu24.04"

# Optional second arg: a CUDA variant override (default 12.5.1). Only used for
# build/push. 12.8 -> tag ubuntu24.04-rtx50 (for RTX 50/Blackwell, driver >=570).
CUDA_VARIANT="${CUDA_VARIANT:-${2:-12.5}}"

case "${CUDA_VARIANT}" in
  12.5) CUDA_VERSION="12.5.1"; CUDA_PKG="12-5" ;;
  12.8) CUDA_VERSION="12.8.1"; CUDA_PKG="12-8"; TAG="ubuntu24.04-rtx50" ;;
  *) echo "Unknown CUDA_VARIANT '${CUDA_VARIANT}' (use 12.5 or 12.8)"; exit 1 ;;
esac

case "${COMMAND}" in
  build)
    echo "[*] Building DpadCloud gaming image (Ubuntu 24.04, CUDA ${CUDA_VERSION} -> ${IMAGE_NAME}:${TAG})..."
    docker build --build-arg CUDA_VERSION="${CUDA_VERSION}" --build-arg CUDA_PKG="${CUDA_PKG}" \
      -t "${IMAGE_NAME}:${TAG}" .
    echo "[*] Build complete: ${IMAGE_NAME}:${TAG} (CUDA ${CUDA_VERSION})"
    ;;

  up)
    echo "[*] Starting DpadCloud gaming container..."
    docker compose up -d
    echo ""
    echo "=========================================="
    echo "  Container starting... (wait ~60s)"
    echo ""
    echo "  Browser (primary, mws + Sunshine NVENC):  http://localhost:8080"
    echo "    - first login creates the admin user"
    echo "    - add host 'localhost', pair via Sunshine PIN"
    echo "  Browser (fallback, Selkies):              http://localhost:16100  (dpad / dpadcloud)"
    echo "  Sunshine Web UI (native Moonlight PIN):   https://localhost:47990  (admin / dpadcloud)"
    echo "=========================================="
    ;;

  down)
    echo "[*] Stopping container..."
    docker compose down
    ;;

  logs)
    docker compose logs -f
    ;;

  status)
    docker ps --filter "name=dpadcloud-gaming" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    ;;

  shell)
    echo "[*] Opening shell inside container..."
    docker exec -it dpadcloud-gaming bash
    ;;

  clean)
    echo "[*] Stopping and removing all data..."
    docker compose down -v
    docker rmi "${IMAGE_NAME}:${TAG}" 2>/dev/null || true
    echo "[*] Cleaned up."
    ;;

  push)
    if [ -z "$2" ]; then
      echo "Usage: ./deploy.sh push YOUR_DOCKERHUB_USER [CUDA_VARIANT]"
      exit 1
    fi
    docker tag "${IMAGE_NAME}:${TAG}" "$2/${IMAGE_NAME}:${TAG}"
    docker push "$2/${IMAGE_NAME}:${TAG}"
    echo "[*] Pushed to: $2/${IMAGE_NAME}:${TAG}"
    ;;

  *)
    echo "DpadCloud Gaming Container — Quick Deploy (Ubuntu 24.04 / CUDA 12.5.1)"
    echo ""
    echo "Usage: ./deploy.sh [command] [CUDA_VARIANT]"
    echo ""
    echo "CUDA_VARIANT: 12.5 (default; driver>=525 via minor compat, widest pool, no RTX 50)"
    echo "              12.8 (RTX 50/Blackwell + driver>=570; tag=ubuntu24.04-rtx50)"
    echo ""
    echo "Commands:"
    echo "  build [V]     Build the Docker image (V=12.5|12.8)"
    echo "  up            Start container (docker compose up -d)"
    echo "  down          Stop container"
    echo "  logs          Follow container logs"
    echo "  status        Show container status"
    echo "  shell         Open bash shell inside container"
    echo "  clean         Stop + remove volumes + remove image"
    echo "  push USER [V] Tag and push to Docker Hub"
    echo ""
    echo "Env: CUDA_VARIANT=12.8 ./deploy.sh build"
    ;;
esac