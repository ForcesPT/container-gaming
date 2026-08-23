"""Send Selkies input into the persistent gst-wayland-display Smithay seat."""

from __future__ import annotations

from importlib import import_module
from threading import Lock
from typing import Any

_source: Any | None = None
_gst: Any | None = None
_lock = Lock()


def _get_gst() -> Any:
    global _gst
    if _gst is None:
        gi = import_module("gi")
        gi.require_version("Gst", "1.0")
        _gst = import_module("gi.repository.Gst")
    return _gst


def register_source(source: Any) -> None:
    """Register the persistent waylanddisplaysrc owned by Selkies."""
    global _source
    with _lock:
        _source = source


def clear_source() -> None:
    global _source
    with _lock:
        _source = None


def _send(description: str) -> bool:
    with _lock:
        source = _source
    if source is None:
        return False

    try:
        gst = _get_gst()
        # Parse explicit GStreamer types. PyGObject otherwise infers Python int
        # as signed gint, while gst-wayland-display requires guint for evdev
        # key/button codes.
        structure = gst.Structure.new_from_string(description)
        event = gst.Event.new_custom(gst.EventType.CUSTOM_UPSTREAM, structure)
        return bool(source.send_event(event))
    except Exception:
        return False


def pointer_motion_absolute(x: float, y: float) -> bool:
    return _send(
        f"MouseMoveAbsolute, pointer_x=(double){float(x)!r}, "
        f"pointer_y=(double){float(y)!r}"
    )


def pointer_motion_relative(x: float, y: float) -> bool:
    return _send(
        f"MouseMoveRelative, pointer_x=(double){float(x)!r}, "
        f"pointer_y=(double){float(y)!r}"
    )


def pointer_button(button: int, pressed: bool) -> bool:
    state = str(bool(pressed)).lower()
    return _send(f"MouseButton, button=(uint){int(button)}, pressed=(boolean){state}")


def pointer_axis(x: float, y: float) -> bool:
    return _send(f"MouseAxis, x=(double){float(x)!r}, y=(double){float(y)!r}")


def keyboard_key(key: int, pressed: bool) -> bool:
    state = str(bool(pressed)).lower()
    return _send(f"KeyboardKey, key=(uint){int(key)}, pressed=(boolean){state}")
