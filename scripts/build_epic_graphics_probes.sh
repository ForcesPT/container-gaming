#!/bin/bash
# Local diagnostic artifacts only. Never COPY these into a gaming image.
# Run in the ncrypt-builder toolchain with libvulkan-dev installed and
# /workspace mounted writable. Execution probes mount it read-only instead.
set -euo pipefail
cd /workspace
mkdir -p test-results
x86_64-w64-mingw32-gcc -Wall -Wextra -Werror -O2 \
    scripts/epic_graphics_service_probe.c \
    -o test-results/epic_graphics_service_probe.exe -ld3d11 -ladvapi32
gcc -Wall -Wextra -Werror -shared -fPIC \
    scripts/epic_vulkan_no_headless_probe.c \
    -o test-results/libdpad-lvp-no-headless-probe.so -ldl -lpthread
python3 - <<'PY'
import json
from pathlib import Path
Path('test-results/dpad-lvp-no-headless-probe.json').write_text(json.dumps({
    'file_format_version': '1.0.0',
    'ICD': {'library_path': '/workspace/test-results/libdpad-lvp-no-headless-probe.so',
            'api_version': '1.3.0'}
}) + '\n')
PY
