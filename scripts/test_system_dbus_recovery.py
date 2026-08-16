#!/usr/bin/env python3
"""Guard D-Bus restart behavior required by Steam networking."""
from pathlib import Path

entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

stale_socket_gate = "[ ! -e /var/run/dbus/system_bus_socket ]"
if stale_socket_gate in entrypoint:
    raise SystemExit(
        "entrypoint trusts system_bus_socket existence; after docker restart the stale "
        "socket makes Steam's NetworkManager client fail"
    )

required = (
    "dbus-send --system --dest=org.freedesktop.DBus",
    "rm -f /run/dbus/system_bus_socket /run/dbus/pid",
    "dbus-daemon --system --fork",
)
missing = [token for token in required if token not in entrypoint]
if missing:
    raise SystemExit("entrypoint lacks live system-bus recovery: " + ", ".join(missing))

print("system D-Bus is health-probed and stale sockets are recovered")
