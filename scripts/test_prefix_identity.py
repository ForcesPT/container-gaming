#!/usr/bin/env python3
"""Behavioral contract for Wine prefix MachineGuid sanitization."""
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "dpad-randomize-prefix-id"
if not HELPER.exists():
    raise SystemExit("prefix identity helper missing")

helper_source = HELPER.read_text(encoding="utf-8")
if "os.fsync(prefix_fd)" not in helper_source:
    raise SystemExit("prefix identity helper does not fsync system.reg parent after replacement")

with tempfile.TemporaryDirectory() as td:
    prefix = Path(td)
    reg = prefix / "system.reg"
    reg.write_text('[Software\\Microsoft\\Cryptography]\n"MachineGuid"="60432b04-68ac-4109-810f-268770162ed7"\n')

    subprocess.run([str(HELPER), "--template", str(prefix)], check=True)
    text = reg.read_text()
    if '"MachineGuid"="00000000-0000-0000-0000-000000000000"' not in text:
        raise SystemExit("template MachineGuid was not neutralized")

    subprocess.run([str(HELPER), str(prefix)], check=True)
    text = reg.read_text()
    match = re.search(r'"MachineGuid"="([^"]+)"', text)
    if not match:
        raise SystemExit("runtime MachineGuid missing")
    first_runtime = uuid.UUID(match.group(1))
    if first_runtime.int == 0:
        raise SystemExit("runtime MachineGuid stayed at template placeholder")

    subprocess.run([str(HELPER), str(prefix)], check=True)
    second_text = reg.read_text()
    second_match = re.search(r'"MachineGuid"="([^"]+)"', second_text)
    if not second_match or uuid.UUID(second_match.group(1)) != first_runtime:
        raise SystemExit("runtime MachineGuid changed on an idempotent recheck")

    reg.write_text(
        '[Software\\Microsoft\\Cryptography]\n'
        '"MachineGuid"="{00000000-0000-0000-0000-000000000000}"\n'
    )
    subprocess.run([str(HELPER), str(prefix)], check=True)
    alternate_match = re.search(r'"MachineGuid"="([^"]+)"', reg.read_text())
    if not alternate_match or uuid.UUID(alternate_match.group(1)).int == 0:
        raise SystemExit("runtime helper preserved an alternate nil MachineGuid representation")

print("Wine prefix identity randomization: PASS")
