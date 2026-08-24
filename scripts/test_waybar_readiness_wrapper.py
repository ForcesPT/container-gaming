#!/usr/bin/env python3
"""Behavioral tests for fail-closed Waybar readiness supervision."""

import os
from pathlib import Path
import signal
import select
import subprocess
import tempfile
import time
import ctypes
import json

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/dpad-waybar"
STATE_CHECK = ROOT / "scripts/dpad-waybar-state-check"


def write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    log = tmp_path / "waybar.log"
    marker = runtime / "dpad-waybar.state"
    config = tmp_path / "waybar.json"
    style = tmp_path / "waybar.css"
    expected_config = {
        "position": "bottom",
        "layer": "top",
        "start_hidden": False,
        "exclusive": True,
        "passthrough": False,
        "height": 46,
        "spacing": 6,
        "modules-left": ["wlr/taskbar"],
        "modules-right": ["clock"],
        "wlr/taskbar": {
            "format": "{icon}  {title}",
            "icon-size": 24,
            "max-length": 48,
            "tooltip-format": "{title}",
            "on-click": "activate",
        },
        "clock": {"format": "{:%H:%M}"},
    }
    config.write_text(json.dumps(expected_config))
    style.write_text("#taskbar {}\n")
    wayland_info = tmp_path / "wayland-info"
    write_executable(
        wayland_info,
        "#!/bin/sh\necho \"interface: 'wl_seat', version: 9\"\n"
        "echo \"interface: 'zwlr_foreign_toplevel_manager_v1', version: 3\"\n",
    )

    failing = tmp_path / "waybar"
    write_executable(
        failing,
        "#!/bin/sh\necho 'Failed to register as toplevel manager' >&2\nsleep 10\n",
    )
    env = {
        **os.environ,
        "WAYBAR_BIN": str(failing),
        "DPAD_WAYBAR_RUNTIME_DIR": str(runtime),
        "DPAD_WAYBAR_LOG": str(log),
        "DPAD_WAYBAR_PROBE_TICKS": "30",
        "DPAD_WAYBAR_PROBE_INTERVAL": "0.01",
        "WAYLAND_INFO_BIN": str(wayland_info),
    }

    # Protocol preflight must fail before Waybar can create an exclusive layer.
    missing_manager = tmp_path / "wayland-info-missing"
    write_executable(missing_manager, "#!/bin/sh\necho \"interface: 'wl_seat', version: 9\"\n")
    sentinel = tmp_path / "waybar-started"
    should_not_start = tmp_path / "waybar-sentinel"
    write_executable(should_not_start, f"#!/bin/sh\ntouch '{sentinel}'\nsleep 10\n")
    preflight_env = {
        **env,
        "WAYBAR_BIN": str(should_not_start),
        "WAYLAND_INFO_BIN": str(missing_manager),
    }
    preflight = subprocess.run(
        [str(WRAPPER), "--config", str(config), "--style", str(style)],
        env=preflight_env,
        text=True,
        capture_output=True,
        timeout=3,
    )
    assert preflight.returncode != 0
    assert not sentinel.exists()
    assert not marker.exists()

    # Type-loose or incomplete JSON must fail before the panel starts.
    for name, mutate in (
        ("modules-string", lambda value: value.update({"modules-left": "wlr/taskbar"})),
        ("float-height", lambda value: value.update({"height": 46.0})),
        ("unexpected-action", lambda value: value["wlr/taskbar"].update({"on-click-middle": "close"})),
        ("missing-clock", lambda value: value.pop("clock")),
    ):
        malformed = json.loads(json.dumps(expected_config))
        mutate(malformed)
        malformed_path = tmp_path / f"waybar-{name}.json"
        malformed_path.write_text(json.dumps(malformed))
        sentinel.unlink(missing_ok=True)
        malformed_result = subprocess.run(
            [str(WRAPPER), "--config", str(malformed_path), "--style", str(style)],
            env={**env, "WAYBAR_BIN": str(should_not_start)},
            text=True,
            capture_output=True,
            timeout=3,
        )
        assert malformed_result.returncode != 0, name
        assert not sentinel.exists(), name

    duplicate = tmp_path / "waybar-duplicate.json"
    duplicate.write_text(config.read_text().replace('"position": "bottom"', '"position": "top", "position": "bottom"'))
    sentinel.unlink(missing_ok=True)
    duplicate_result = subprocess.run(
        [str(WRAPPER), "--config", str(duplicate), "--style", str(style)],
        env={**env, "WAYBAR_BIN": str(should_not_start)},
        text=True,
        capture_output=True,
        timeout=3,
    )
    assert duplicate_result.returncode != 0
    assert not sentinel.exists()

    result = subprocess.run(
        [str(WRAPPER), "--config", str(config), "--style", str(style)],
        env=env,
        text=True,
        capture_output=True,
        timeout=3,
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert "Failed to register as toplevel manager" in log.read_text()


    healthy = tmp_path / "waybar"
    write_executable(
        healthy,
        "#!/usr/bin/env python3\n"
        "import ctypes, signal, sys\n"
        "ctypes.CDLL(None).prctl(15, b'waybar', 0, 0, 0)\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "while True: signal.pause()\n",
    )
    env["WAYBAR_BIN"] = str(healthy)
    env["DPAD_WAYBAR_PROBE_TICKS"] = "2"
    proc = subprocess.Popen(
        [str(WRAPPER), "--config", str(config), "--style", str(style)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 2
    marker_text = ""
    while time.monotonic() < deadline:
        if marker.exists():
            marker_text = marker.read_text()
            if marker_text.startswith("ready "):
                break
        time.sleep(0.01)
    assert marker_text.startswith("ready "), "wrapper did not publish readiness"
    state, pid_text, start_ticks = marker_text.split()
    assert state == "ready"
    waybar_pid = int(pid_text)
    assert start_ticks.isdigit()
    os.kill(waybar_pid, 0)

    # The health predicate must accept the exact live PID/start tuple.
    state_check = subprocess.run([str(STATE_CHECK), str(marker)], capture_output=True, text=True)
    assert state_check.returncode == 0, state_check.stdout + state_check.stderr

    marker.write_text(marker_before := marker.read_text() + marker.read_text())
    multiline_check = subprocess.run([str(STATE_CHECK), str(marker)], capture_output=True, text=True)
    assert multiline_check.returncode != 0
    assert "record" in multiline_check.stdout.lower()
    marker.write_text(marker_before[: len(marker_before) // 2])

    # A concurrent supervisor must fail without touching the live owner/state.
    marker_before = marker.read_text()
    second = subprocess.Popen(
        [str(WRAPPER), "--config", str(config), "--style", str(style)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    second_rc = second.wait(timeout=3)
    assert second_rc is not None and second_rc != 0
    assert proc.poll() is None
    assert marker.read_text() == marker_before

    # A real zombie named waybar must be rejected even though kill -0 and comm pass.
    zombie_pid = os.fork()
    if zombie_pid == 0:
        libc = ctypes.CDLL(None)
        libc.prctl(15, b"waybar", 0, 0, 0)
        os._exit(0)
    zombie_stat = Path(f"/proc/{zombie_pid}/stat")
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        fields = zombie_stat.read_text().split()
        if fields[2] == "Z":
            break
        time.sleep(0.01)
    fields = zombie_stat.read_text().split()
    assert fields[2] == "Z"
    marker.write_text(f"ready {zombie_pid} {fields[21]}\n")
    zombie_check = subprocess.run([str(STATE_CHECK), str(marker)], capture_output=True, text=True)
    assert zombie_check.returncode != 0
    assert "zombie" in zombie_check.stdout.lower()
    os.waitpid(zombie_pid, 0)
    marker.write_text(marker_before)

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=3)
    assert not marker.exists()
    try:
        os.kill(waybar_pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("supervised Waybar survived wrapper shutdown")

    # After supervisor SIGKILL, replacement must terminate the exact stale
    # pidfd-bound Waybar and publish a different ready PID.
    crash_owner = subprocess.Popen(
        [str(WRAPPER), "--config", str(config), "--style", str(style)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 2
    crash_marker = ""
    while time.monotonic() < deadline:
        if marker.exists():
            crash_marker = marker.read_text()
            if crash_marker.startswith("ready "):
                break
        time.sleep(0.01)
    _, crash_child_text, _ = crash_marker.split()
    crash_child = int(crash_child_text)
    crash_pidfd = os.pidfd_open(crash_child)
    crash_owner.kill()
    crash_owner.wait(timeout=3)
    os.kill(crash_child, 0)
    replacement = subprocess.Popen(
        [str(WRAPPER), "--config", str(config), "--style", str(style)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 5
    replacement_marker = ""
    while time.monotonic() < deadline:
        replacement_rc = replacement.poll()
        if replacement_rc is not None:
            out, err = replacement.communicate(timeout=1)
            raise AssertionError(f"replacement exited {replacement_rc}: {out}{err}")
        if marker.exists():
            replacement_marker = marker.read_text()
            if replacement_marker.startswith("ready ") and replacement_marker != crash_marker:
                break
        time.sleep(0.01)
    assert replacement_marker.startswith("ready ")
    assert replacement_marker != crash_marker
    poller = select.poll()
    poller.register(crash_pidfd, select.POLLIN)
    assert poller.poll(1000), "replacement left stale Waybar alive"
    os.close(crash_pidfd)
    replacement.terminate()
    replacement.wait(timeout=3)

print("Waybar readiness supervisor fails closed: PASS")
