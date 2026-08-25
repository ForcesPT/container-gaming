#!/usr/bin/env python3
"""Regression contract for one-image, fully preinstalled store releases."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
dockerfile = (ROOT / "Dockerfile").read_text()
unified_path = ROOT / "scripts" / "build-preinstall-stores.sh"
if not unified_path.exists():
    raise SystemExit("unified privileged store preinstall script is missing")
unified = unified_path.read_text()

if dockerfile.count("/tmp/build-bootstrap-battlenet.sh"):
    raise SystemExit("Dockerfile still creates a separate Battle.net pre-bake layer")
if dockerfile.count("/tmp/build-bootstrap-ea.sh"):
    raise SystemExit("Dockerfile still creates a separate EA pre-bake layer")
if "${HOME}/.local/share/umu" in dockerfile and "chown -R" in dockerfile:
    raise SystemExit("Dockerfile must not recursively copy-up the shared UMU runtime")
if "COPY scripts/build-preinstall-stores.sh /opt/dpadcloud/build-preinstall-stores.sh" not in dockerfile:
    raise SystemExit("gaming image does not package the unified privileged preinstall script")

if "COPY scripts/build-click-x11.py /opt/dpadcloud/build-click-x11.py" not in dockerfile:
    raise SystemExit("gaming image does not package the narrow X11 installer-click helper")
if "COPY scripts/dpad-randomize-prefix-id /opt/dpadcloud/dpad-randomize-prefix-id" not in dockerfile:
    raise SystemExit("gaming image does not package Wine prefix identity randomization")

for required in (
    'PREFIX_BNET="/opt/dpadcloud/battlenet-prefix"',
    'PREFIX_EA="/opt/dpadcloud/ea-prefix"',
    'PREFIX_UBISOFT="/opt/dpadcloud/ubisoft-prefix"',
    'Battle.net Launcher.exe',
    'EADesktop.exe',
    'UbisoftConnect.exe',
    '.dpad-preinstalled',
    'sanitize_prefix()',
    '/opt/dpadcloud/dpad-randomize-prefix-id --template',
    'PREINSTALLED_STORES_READY',
):
    if required not in unified:
        raise SystemExit(f"unified store preinstall contract missing: {required}")

for bootstrap_name in ("battlenet", "ea", "ubisoft"):
    bootstrap = (ROOT / "scripts" / f"build-bootstrap-{bootstrap_name}.sh").read_text()
    if "rm -f /tmp/.X9-lock /tmp/.X11-unix/X9" not in bootstrap:
        raise SystemExit(f"{bootstrap_name} preinstall does not reset stale Xvfb :9 state")
    if ".dpad-preinstalled" not in bootstrap:
        raise SystemExit(f"{bootstrap_name} preinstall is not idempotent after finalization")
    if bootstrap_name == "ea" and "build-click-x11.py --display :9 --title-part ea --title-part installer" not in bootstrap:
        raise SystemExit("EA preinstall does not activate the deterministic installer control")

for name in ("battlenet", "ea", "ubisoft"):
    launch = (ROOT / "scripts" / f"{name}-launch").read_text()
    source = f'/opt/dpadcloud/{name}-prefix'
    if source not in launch:
        raise SystemExit(f"{name} launcher does not consume its in-image prefix template")
    if ".dpad-preinstalled" not in launch:
        raise SystemExit(f"{name} launcher does not require the fully preinstalled marker")
    if 'DPAD_RANDOMIZE_PREFIX_ID:-/opt/dpadcloud/dpad-randomize-prefix-id' not in launch:
        raise SystemExit(f"{name} launcher lacks the packaged Wine identity-helper default")
    if '"$RANDOMIZE_PREFIX_ID" "$PREFIX"' not in launch:
        raise SystemExit(f"{name} launcher does not generate a per-user Wine MachineGuid")
    if 'rm -rf "$PREFIX"' in launch:
        raise SystemExit(f"{name} launcher can recursively delete an overridable WINEPREFIX")

print("Single-image preinstalled stores contract: PASS")
