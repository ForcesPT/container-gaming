#!/usr/bin/env python3
"""Guard the gst-wayland-display runtime ABI required by Noble."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dockerfile = (root / "Dockerfile").read_text()

runtime_copy = (
    "COPY --from=wayland-display-builder "
    "/usr/local/lib/x86_64-linux-gnu/libwayland-server.so.0* "
    "/usr/local/lib/x86_64-linux-gnu/"
)
if runtime_copy not in dockerfile:
    raise SystemExit(
        "Dockerfile does not ship libwayland-server >=1.23; "
        "waylanddisplaysrc will blacklist with undefined symbol "
        "wl_client_set_max_buffer_size on Ubuntu 24.04"
    )
if "objdump -T /usr/local/lib/x86_64-linux-gnu/libwayland-server.so.0" not in dockerfile:
    raise SystemExit("Dockerfile does not verify the required libwayland runtime symbol")

copy_at = dockerfile.index(runtime_copy)
plugin_at = dockerfile.index(
    "COPY --from=wayland-display-builder /out/lib/x86_64-linux-gnu/"
    "gstreamer-1.0/libgstwaylanddisplaysrc.so"
)
if copy_at > plugin_at:
    raise SystemExit("libwayland-server must be installed before the GStreamer plugin")

print("waylanddisplaysrc runtime ABI is bundled")
