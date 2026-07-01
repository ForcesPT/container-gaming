#!/bin/bash
# =============================================================================
# DpadCloud Container Gaming — Quick Deploy Script
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

COMMAND="${1:-up}"
IMAGE_NAME="dpadcloud/gaming"
TAG="latest"
# CUDA variant: 12.1 (default, widest pool, no RTX 50) or 12.8 (RTX 50/Blackwell,
# driver >=570). Set CUDA_VARIANT=12.8 env or pass as 2nd arg to build/push.
CUDA_VARIANT="${CUDA_VARIANT:-${2:-12.1}}"

case "${CUDA_VARIANT}" in
  12.1) CUDA_VERSION="12.1.1"; CUDA_PKG="12-1" ;;
  12.8) CUDA_VERSION="12.8.1"; CUDA_PKG="12-8"; TAG="cuda12.8" ;;
  *) echo "Unknown CUDA_VARIANT '${CUDA_VARIANT}' (use 12.1 or 12.8)"; exit 1 ;;
esac

case "${COMMAND}" in
  build)
    echo "[*] Building DpadCloud gaming image (CUDA ${CUDA_VARIANT} -> ${CUDA_VERSION})..."
    docker build --build-arg CUDA_VERSION="${CUDA_VERSION}" --build-arg CUDA_PKG="${CUDA_PKG}" \
      -t "${IMAGE_NAME}:${TAG}" .
    echo "[*] Build complete: ${IMAGE_NAME}:${TAG} (CUDA ${CUDA_VERSION})"
    ;;

  up)
    echo "[*] Starting DpadCloud gaming container..."
    docker compose up -d
    echo ""
    echo "=========================================="
    echo "  Container starting..."
    echo "  Wait ~60 seconds, then:"
    echo ""
    echo "  1. Open browser to http://localhost:47989"
    echo "  2. Login: admin / dpadcloud"
    echo "  3. Get PIN from web UI"
    echo "  4. Open Moonlight → Add PC → localhost"
    echo "  5. Enter PIN → Connect!"
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
      echo "Usage: ./deploy.sh push YOUR_DOCKERHUB_USER"
      exit 1
    fi
    docker tag "${IMAGE_NAME}:${TAG}" "$2/${IMAGE_NAME}:${TAG}"
    docker push "$2/${IMAGE_NAME}:${TAG}"
    echo "[*] Pushed to: $2/${IMAGE_NAME}:${TAG}"
    ;;

  *)
    echo "DpadCloud Gaming Container — Quick Deploy"
    echo ""
    echo "Usage: ./deploy.sh [command] [CUDA_VARIANT]"
    echo ""
    echo "CUDA_VARIANT: 12.1 (default; driver>=525, widest pool, no RTX 50)"
    echo "              12.8 (RTX 50/Blackwell + driver>=570; tag=cuda12.8)"
    echo ""
    echo "Commands:"
    echo "  build [V]     Build the Docker image (V=12.1|12.8)"
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
