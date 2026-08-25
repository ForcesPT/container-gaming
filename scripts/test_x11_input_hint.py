#!/usr/bin/env python3
"""Behavioral regression tests for dpad-x11-input-hint."""
from __future__ import annotations

import runpy
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
module = runpy.run_path(str(ROOT / "scripts" / "dpad-x11-input-hint"), run_name="dpad_x11_input_hint_test")

select_owned_windows = module.get("select_owned_windows")
if select_owned_windows is None:
    raise SystemExit("input-hint helper missing select_owned_windows()")

# A pre-existing matching EA window and an unrelated matching EA window must be
# ignored. Only a new WM_CLASS match whose _NET_WM_PID descends from the wrapped
# child is eligible.
now = [10.0]
details = {
    "0xold": (("steam_app_eaapp", "steam_app_eaapp"), 111),
    "0xforeign": (("steam_app_eaapp", "steam_app_eaapp"), 222),
    "0xowned": (("steam_app_eaapp", "steam_app_eaapp"), 333),
    "0xother": (("other", "other"), 444),
}
selected = select_owned_windows(
    windows=["0xold", "0xforeign", "0xowned", "0xother"],
    known_windows={"0xold"},
    wm_class="steam_app_eaapp",
    child_pid=900,
    deadline=11.0,
    monotonic=lambda: now[0],
    details=lambda window, timeout: details.get(window),
    descends=lambda pid, ancestor: pid == 333 and ancestor == 900,
)
assert selected == ["0xowned"], selected

# The deadline must be checked before every per-window probe. A slow first probe
# may consume the budget; later windows must not be inspected afterward.
probed: list[str] = []
def slow_details(window: str, timeout: float):
    assert 0 < timeout <= 0.25
    probed.append(window)
    now[0] = 20.0
    return (("other", "other"), 1)

now[0] = 15.0
selected = select_owned_windows(
    windows=["0x1", "0x2", "0x3"],
    known_windows=set(),
    wm_class="steam_app_eaapp",
    child_pid=900,
    deadline=15.1,
    monotonic=lambda: now[0],
    details=slow_details,
    descends=lambda _pid, _ancestor: False,
)
assert selected == []
assert probed == ["0x1"], probed

# Destroyed windows are represented by a failed details probe and must be
# skipped rather than terminating the lifecycle owner.
now[0] = 30.0
selected = select_owned_windows(
    windows=["0xdestroyed", "0xowned"],
    known_windows=set(),
    wm_class="steam_app_eaapp",
    child_pid=900,
    deadline=31.0,
    monotonic=lambda: now[0],
    details=lambda window, _timeout: None if window == "0xdestroyed" else (("steam_app_eaapp",), 333),
    descends=lambda pid, ancestor: pid == 333 and ancestor == 900,
)
assert selected == ["0xowned"]

source = (ROOT / "scripts" / "dpad-x11-input-hint").read_text()
for contract in (
    "pending_signals.append(signum)",
    "for signum in pending_signals:",
    "except ProcessLookupError:",
    "x11.XSetErrorHandler",
    "x11.XSync(display, 0)",
):
    if contract not in source:
        raise SystemExit(f"input-hint helper missing lifecycle/race contract: {contract}")

# A direct SIGTERM sent immediately after child creation must be forwarded to an
# unblocked child and the lifecycle wrapper must exit promptly. Use a private
# process group so failure cleanup cannot touch the test runner.
wrapper = subprocess.Popen(
    [
        sys.executable,
        str(ROOT / "scripts" / "dpad-x11-input-hint"),
        "--class", "never_matches",
        "--wait-seconds", "1",
        "--", sys.executable, "-c", "import time; time.sleep(30)",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=True,
)
try:
    time.sleep(0.2)
    wrapper.send_signal(signal.SIGTERM)
    wrapper.wait(timeout=3)
    assert wrapper.returncode == -signal.SIGTERM, wrapper.returncode
except subprocess.TimeoutExpired:
    os.killpg(wrapper.pid, signal.SIGKILL)
    wrapper.wait()
    raise SystemExit("input-hint wrapper hung after forwarded SIGTERM")
finally:
    try:
        os.killpg(wrapper.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

# Uncatchable child termination must also be propagated exactly; attempting to
# install SIG_DFL for SIGKILL itself raises OSError/ValueError.
killed_child = subprocess.run(
    [
        sys.executable,
        str(ROOT / "scripts" / "dpad-x11-input-hint"),
        "--class", "never_matches",
        "--wait-seconds", "1",
        "--", sys.executable, "-c",
        "import os,signal; os.kill(os.getpid(), signal.SIGKILL)",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    timeout=3,
)
assert killed_child.returncode == -signal.SIGKILL, killed_child

print("X11 input-hint behavioral regression: PASS")
