#!/usr/bin/env python3
"""Behavioral tests for Selkies -> gst-wayland-display input events."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "dpad_wayland_input.py"

spec = importlib.util.spec_from_file_location("dpad_wayland_input", MODULE)
if spec is None or spec.loader is None:
    raise SystemExit("could not load dpad_wayland_input")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class FakeStructure:
    def __init__(self, description):
        self.description = description

    @classmethod
    def new_from_string(cls, description):
        return cls(description)


class FakeEvent:
    @staticmethod
    def new_custom(event_type, structure):
        return {"type": event_type, "structure": structure}


class FakeGst:
    Structure = FakeStructure
    Event = FakeEvent

    class EventType:
        CUSTOM_UPSTREAM = "custom-upstream"


class FakeSource:
    def __init__(self, accepted=True):
        self.events = []
        self.accepted = accepted

    def send_event(self, event):
        self.events.append(event)
        return self.accepted


imports = []


class FakeGi:
    @staticmethod
    def require_version(namespace, version):
        assert (namespace, version) == ("Gst", "1.0")


def fake_import_module(name):
    imports.append(name)
    return FakeGi if name == "gi" else FakeGst


setattr(bridge, "_gst", None)
setattr(bridge, "import_module", fake_import_module)
assert bridge._get_gst() is FakeGst
assert imports == ["gi", "gi.repository.Gst"]

setattr(bridge, "_gst", FakeGst)
bridge.clear_source()
assert bridge.pointer_motion_absolute(12, 34) is False

source = FakeSource()
bridge.register_source(source)
assert bridge.pointer_motion_absolute(12, 34) is True
assert bridge.pointer_motion_relative(-5, 6) is True
assert bridge.pointer_button(0x110, True) is True
assert bridge.pointer_axis(0, -120) is True
assert bridge.keyboard_key(30, False) is True

actual = [event["structure"].description for event in source.events]
assert actual == [
    "MouseMoveAbsolute, pointer_x=(double)12.0, pointer_y=(double)34.0",
    "MouseMoveRelative, pointer_x=(double)-5.0, pointer_y=(double)6.0",
    "MouseButton, button=(uint)272, pressed=(boolean)true",
    "MouseAxis, x=(double)0.0, y=(double)-120.0",
    "KeyboardKey, key=(uint)30, pressed=(boolean)false",
]
assert all(event["type"] == "custom-upstream" for event in source.events)

rejected = FakeSource(accepted=False)
bridge.register_source(rejected)
assert bridge.pointer_button(0x110, True) is False

print("Wayland compositor input bridge: PASS")
