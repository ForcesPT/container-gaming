#!/usr/bin/env python3
"""GPU integration test: browser-peer churn must preserve the desktop."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "dpad-reconnect-spike:latest"
NAME = f"dpad-reconnect-test-{os.getpid()}"
DOCKER_RUN = [
    "docker", "run", "-d", "--name", NAME,
    "--runtime=nvidia",
    "-e", "NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=0",
    "--cap-add", "SYS_ADMIN",
    "--security-opt", "seccomp=unconfined",
    "--security-opt", "apparmor=unconfined",
    "--security-opt", "systempaths=unconfined",
    "--shm-size=2g",
    "--ulimit", "nofile=1048576:1048576",
    "--device", "/dev/dri",
    "-e", "DPAD_SELKIES_BIND=0.0.0.0",
    "-e", "SELKIES_BASIC_AUTH_USER=dpad",
    "-e", "SELKIES_BASIC_AUTH_PASSWORD=testpass",
    IMAGE,
]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def exec_in(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("docker", "exec", NAME, *args, check=check)


def wait_healthy(timeout: int = 360) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = run(
            "docker", "inspect", "-f",
            "{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            NAME,
        ).stdout.split()
        if state[0] != "true":
            raise AssertionError("container exited before becoming healthy")
        status = state[1]
        if status == "healthy":
            return
        if status == "unhealthy":
            raise AssertionError("container became unhealthy")
        time.sleep(3)
    raise AssertionError("container health timeout")


def start_peer(label: str, hold_seconds: int) -> None:
    run(
        "docker", "exec", "-d", NAME, "bash", "-c",
        f"python3 /tmp/hold-peer.py 127.0.0.1 16100 1 {hold_seconds} > /tmp/{label}.log 2>&1",
    )


def wait_sway(timeout: int = 60) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = exec_in("pgrep", "-x", "sway", check=False)
        if result.returncode == 0:
            return int(result.stdout.splitlines()[0])
        time.sleep(1)
    raise AssertionError("Sway did not launch after peer connection")


def wayland_socket_identity() -> tuple[str, int]:
    code = (
        "from pathlib import Path; import stat; "
        "p=next(p for p in Path('/run/user/1001').glob('wayland-*') "
        "if stat.S_ISSOCK(p.stat().st_mode)); print(p.name, p.stat().st_ino)"
    )
    name, inode = exec_in("python3", "-c", code).stdout.split()
    return name, int(inode)


def process_identity(name: str) -> tuple[int, int]:
    result = exec_in("pgrep", "-xo", name, check=False)
    if result.returncode != 0:
        raise AssertionError(f"{name} is not running")
    pid = int(result.stdout.strip())
    stat_fields = exec_in(
        "python3", "-c",
        f"s=open('/proc/{pid}/stat').read().split(); print(s[2], s[21])",
    ).stdout.split()
    if stat_fields[0] == "Z":
        raise AssertionError(f"{name} PID {pid} is a zombie")
    start_time = int(stat_fields[1])
    return pid, start_time


def assert_identity(name: str, expected: tuple[int, int], phase: str) -> None:
    actual = process_identity(name)
    if actual != expected:
        raise AssertionError(f"{name} changed {phase}: expected {expected}, got {actual}")


def wait_peer_video_offer(label: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        result = exec_in(
            "python3", "-c",
            f"from pathlib import Path; p=Path('/tmp/{label}.log'); print(p.read_text() if p.exists() else '')",
        )
        output = result.stdout
        if "[*] peer disconnected" in output:
            if "hold done" not in output or "=== m_video=m=video" not in output:
                raise AssertionError(f"{label} completed without a video offer:\n{output}")
            return
        time.sleep(1)
    raise AssertionError(f"{label} did not complete successfully:\n{output}")


def assert_selkies_log_clean() -> None:
    log = exec_in("python3", "-c", "print(open('/tmp/selkies.log').read())").stdout
    fatal_markers = (
        "Failed to transition pipeline",
        "Internal data stream error",
        "not-linked",
        "failed to start video pipeline",
    )
    found = [marker for marker in fatal_markers if marker in log]
    if found:
        raise AssertionError(f"Selkies video pipeline errors found: {found}")
    lifecycle_markers = (
        "video pipeline started",
        "Pipeline state changed from paused to playing",
        "handling on-negotiation-needed, creating offer",
    )
    missing = [marker for marker in lifecycle_markers if log.count(marker) < 2]
    if missing:
        raise AssertionError(f"Second video pipeline lifecycle was incomplete: {missing}")
    if "Reusing persistent waylanddisplaysrc compositor" not in log:
        raise AssertionError("Selkies did not reuse the persistent compositor source")


def print_diagnostics() -> None:
    for title, command in (
        ("container", ("docker", "logs", "--tail", "100", NAME)),
        ("selkies", ("docker", "exec", NAME, "python3", "-c", "print(open('/tmp/selkies.log').read())")),
        ("peer1", ("docker", "exec", NAME, "python3", "-c", "from pathlib import Path; p=Path('/tmp/peer1.log'); print(p.read_text() if p.exists() else '')")),
        ("peer2", ("docker", "exec", NAME, "python3", "-c", "from pathlib import Path; p=Path('/tmp/peer2.log'); print(p.read_text() if p.exists() else '')")),
    ):
        result = run(*command, check=False)
        print(f"--- {title} diagnostics ---", file=sys.stderr)
        print(result.stdout + result.stderr, file=sys.stderr)


try:
    run(*DOCKER_RUN)
    run("docker", "cp", str(ROOT / "scripts" / "hold-peer.py"), f"{NAME}:/tmp/hold-peer.py")
    wait_healthy()

    start_peer("peer1", 20)
    wait_sway()
    sway = process_identity("sway")
    xwayland = process_identity("Xwayland")
    launcher = process_identity("dpad-launcher")
    socket = wayland_socket_identity()
    print(
        f"first peer: sway={sway} Xwayland={xwayland} "
        f"launcher={launcher} socket={socket}"
    )

    wait_peer_video_offer("peer1", 30)
    time.sleep(2)
    assert_identity("sway", sway, "after first peer disconnected")
    assert_identity("Xwayland", xwayland, "after first peer disconnected")
    assert_identity("dpad-launcher", launcher, "after first peer disconnected")
    if wayland_socket_identity() != socket:
        raise AssertionError("Wayland socket changed after peer disconnect")

    start_peer("peer2", 10)
    time.sleep(5)
    assert_identity("sway", sway, "during second peer connection")
    assert_identity("Xwayland", xwayland, "during second peer connection")
    assert_identity("dpad-launcher", launcher, "during second peer connection")
    if wayland_socket_identity() != socket:
        raise AssertionError("Wayland socket changed during peer reconnect")

    wait_peer_video_offer("peer2", 20)
    time.sleep(2)
    assert_identity("sway", sway, "after second peer disconnected")
    assert_identity("Xwayland", xwayland, "after second peer disconnected")
    assert_identity("dpad-launcher", launcher, "after second peer disconnected")
    if wayland_socket_identity() != socket:
        raise AssertionError("Wayland socket changed after second peer disconnect")
    assert_selkies_log_clean()

    print(
        "PASS: Wayland socket, Sway, Xwayland, and launcher identities "
        "survived two peer lifecycles with video offers"
    )
except Exception:
    print_diagnostics()
    raise
finally:
    run("docker", "rm", "-f", NAME, check=False)
