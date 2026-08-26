#!/usr/bin/env python3
"""Behavioral release gate for sanitized, atomic store templates."""
from pathlib import Path
import importlib.machinery
import importlib.util
import os
import re
import shutil
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SANITIZER = SCRIPTS / "dpad-sanitize-store-prefix"
VALIDATOR = SCRIPTS / "dpad-verify-windows-binary"
CLONER = SCRIPTS / "dpad-clone-prefix-template"
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

for helper in (SANITIZER, VALIDATOR, CLONER):
    if not helper.is_file():
        raise SystemExit(f"required store security helper missing: {helper.name}")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check)


def write_pe(path: Path, size: int = 65536) -> None:
    data = bytearray(size)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = b"d\x86"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def load_script(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise AssertionError(f"cannot load test subject: {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)

    valid = root / "valid.exe"
    empty = root / "empty.exe"
    truncated = root / "truncated.exe"
    write_pe(valid)
    empty.write_bytes(b"")
    truncated.write_bytes(b"MZ" + b"\0" * 100)
    run(str(VALIDATOR), "--pe-only", str(valid))
    valid_link = root / "valid-link.exe"
    valid_link.symlink_to(valid)
    result = run(str(VALIDATOR), "--pe-only", str(valid_link), check=False)
    if result.returncode == 0:
        raise SystemExit("PE validator accepted a symlinked executable")
    linked_binary_dir = root / "linked-binary-dir"
    linked_binary_dir.symlink_to(root, target_is_directory=True)
    result = run(str(VALIDATOR), "--pe-only", str(linked_binary_dir / valid.name), check=False)
    if result.returncode == 0:
        raise SystemExit("PE validator accepted an executable beneath a symlinked ancestor")
    for invalid in (empty, truncated):
        result = run(str(VALIDATOR), "--pe-only", str(invalid), check=False)
        if result.returncode == 0:
            raise SystemExit(f"PE validator accepted invalid file: {invalid.name}")

    validator_module = load_script("dpad_verify_windows_binary", VALIDATOR)
    publisher_cases = (
        ("Subject: /C=US/O=Electronic Arts, Inc./CN=EA Code Signing\n", "Electronic Arts, Inc.", True),
        ("Subject: /C=US/O=Other/CN=Blizzard Entertainment, Inc.\n", "Blizzard Entertainment, Inc.", True),
        ("Subject: /C=US/O=Electronic Arts, Inc. Evil/CN=Signer\n", "Electronic Arts, Inc.", False),
        ("Subject: /C=US/O=Other/CN=UBISOFT ENTERTAINMENT INC. Backup\n", "UBISOFT ENTERTAINMENT INC.", False),
        (
            "Subject: /C=US/O=Lookalike/CN=Lookalike\nSubject: /C=US/O=Electronic Arts, Inc./CN=Signer\n",
            "Electronic Arts, Inc.",
            False,
        ),
    )
    for output, publisher, expected in publisher_cases:
        actual = validator_module.first_signer_matches_publisher(output, publisher)
        if actual is not expected:
            raise SystemExit(f"publisher parser mismatch for {output!r}: expected {expected}, got {actual}")

    linked_ca = root / "linked-ca.pem"
    linked_ca.symlink_to(SCRIPTS / "microsoft-identity-root-2020.pem")
    original_which = validator_module.shutil.which
    original_subprocess_run = validator_module.subprocess.run
    validator_module.shutil.which = lambda _name: "/usr/bin/osslsigncode"
    validator_module.subprocess.run = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout="Subject: /CN=Expected Publisher\nSignature verification: ok\n",
        stderr="",
    )
    try:
        try:
            validator_module.verify_signature(
                SimpleNamespace(
                    ca_file=str(linked_ca),
                    ca_sha256=None,
                    trusted_signing_time=False,
                    publisher="Expected Publisher",
                ),
                valid,
            )
        except SystemExit:
            pass
        else:
            raise SystemExit("Authenticode verifier accepted a symlinked CA file")
    finally:
        validator_module.shutil.which = original_which
        validator_module.subprocess.run = original_subprocess_run

    prefix = root / "dirty-prefix"
    user = prefix / "drive_c/users/dpad"
    outside = root / "outside-token"
    outside.write_text("must survive", encoding="utf-8")
    dirty_paths = (
        user / "AppData/Local/Temp/.hidden-token",
        user / "AppData/Local/Vendor/Local Storage/session.db",
        user / "AppData/Local/Vendor/Session Storage/session.db",
        user / "AppData/Local/Vendor/WebStorage/state.db",
        user / "AppData/Local/Vendor/IndexedDB/account.db",
        user / "AppData/Local/Vendor/Network/Cookies",
        user / "AppData/Local/Vendor/Login Data",
        user / "AppData/Local/Vendor/Web Data",
        user / "AppData/Local/Vendor/History",
        user / "AppData/Local/Vendor/Preferences",
        user / "AppData/Local/Vendor/Secure Preferences",
        user / "AppData/Roaming/Battle.net/saved-account.config",
        user / "AppData/Local/Electronic Arts/EA Desktop/CEF/account.bin",
        user / "AppData/Local/Ubisoft Game Launcher/account.dat",
        prefix / "drive_c/ProgramData/Battle.net/Agent/data/cache/agent-state.bin",
        prefix / "drive_c/windows/temp/installer-residue.tmp",
        prefix / "client.log",
        prefix / "crash.dmp",
    )
    for path in dirty_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("credential-like fixture", encoding="utf-8")
    benign = prefix / "drive_c/Program Files/Vendor/client.exe"
    write_pe(benign)
    symlink = user / "AppData/Local/Vendor/Cookies"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(outside)
    non_forbidden_symlink = user / "AppData/Local/Vendor/AccountBridge"
    non_forbidden_symlink.symlink_to(outside)
    run(str(SANITIZER), str(prefix))
    if not benign.is_file() or outside.read_text(encoding="utf-8") != "must survive":
        raise SystemExit("sanitizer damaged benign client data or followed an external symlink")
    for path in dirty_paths:
        if path.exists():
            raise SystemExit(f"sanitizer left forbidden artifact: {path}")
    if symlink.exists() or symlink.is_symlink():
        raise SystemExit("sanitizer left a forbidden symlink")
    if non_forbidden_symlink.exists() or non_forbidden_symlink.is_symlink():
        raise SystemExit("sanitizer retained a non-forbidden user-tree symlink")

    missing_users = root / "missing-users-prefix"
    (missing_users / "drive_c").mkdir(parents=True)
    result = run(str(SANITIZER), str(missing_users), check=False)
    if result.returncode == 0:
        raise SystemExit("sanitizer accepted a prefix without drive_c/users")

    external_users = root / "external-users"
    external_users.mkdir()
    symlink_users = root / "symlink-users-prefix"
    (symlink_users / "drive_c").mkdir(parents=True)
    (symlink_users / "drive_c/users").symlink_to(external_users, target_is_directory=True)
    result = run(str(SANITIZER), str(symlink_users), check=False)
    if result.returncode == 0:
        raise SystemExit("sanitizer accepted a symlinked drive_c/users")

    symlink_prefix = root / "symlink-prefix"
    symlink_prefix.symlink_to(prefix, target_is_directory=True)
    result = run(str(SANITIZER), str(symlink_prefix), check=False)
    if result.returncode == 0:
        raise SystemExit("sanitizer accepted a symlinked prefix path")

    symlink_user_prefix = root / "symlink-user-prefix"
    users_root = symlink_user_prefix / "drive_c/users"
    users_root.mkdir(parents=True)
    real_user = users_root / "steamuser"
    real_user.mkdir()
    external_user = root / "external-wine-user"
    external_user.mkdir()
    external_user_token = external_user / "must-survive"
    external_user_token.write_text("preserve", encoding="utf-8")
    wine_user_alias = users_root / "dpad"
    wine_user_alias.symlink_to(external_user, target_is_directory=True)
    result = run(str(SANITIZER), str(symlink_user_prefix), check=False)
    if result.returncode != 0:
        raise SystemExit("sanitizer rejected a removable Wine user alias")
    if wine_user_alias.exists() or wine_user_alias.is_symlink():
        raise SystemExit("sanitizer retained a Wine user alias")
    if external_user_token.read_text(encoding="utf-8") != "preserve":
        raise SystemExit("sanitizer followed a Wine user alias outside the prefix")

    ancestor_prefix = root / "symlink-ancestor-prefix"
    ancestor_user = ancestor_prefix / "drive_c/users/dpad"
    ancestor_user.mkdir(parents=True)
    external_appdata = root / "external-appdata"
    external_token = external_appdata / "Roaming/Battle.net/account-token"
    external_token.parent.mkdir(parents=True)
    external_token.write_text("must survive", encoding="utf-8")
    (ancestor_user / "AppData").symlink_to(external_appdata, target_is_directory=True)
    result = run(str(SANITIZER), str(ancestor_prefix), check=False)
    if result.returncode == 0 or not external_token.is_file():
        raise SystemExit("sanitizer followed a symlink ancestor outside the prefix")

    sanitizer_module = load_script("dpad_sanitize_store_prefix", SANITIZER)

    prefix_parent = root / "prefix-parent-race"
    prefix_race = prefix_parent / "prefix"
    (prefix_race / "drive_c/users/steamuser").mkdir(parents=True)
    moved_prefix_parent = root / "prefix-parent-original"
    external_prefix_parent = root / "external-prefix-parent"
    external_prefix = external_prefix_parent / "prefix"
    external_prefix_user = external_prefix / "drive_c/users/steamuser"
    external_prefix_user.mkdir(parents=True)
    external_prefix_token = external_prefix_user / "external.log"
    external_prefix_token.write_text("preserve", encoding="utf-8")
    original_open = sanitizer_module.os.open
    prefix_parent_swapped = [False]

    def substitute_prefix_parent_before_open(path, flags, *args, **kwargs):
        if Path(path) == prefix_race and not prefix_parent_swapped[0]:
            prefix_parent_swapped[0] = True
            prefix_parent.rename(moved_prefix_parent)
            prefix_parent.symlink_to(external_prefix_parent, target_is_directory=True)
        elif path == prefix_parent.name and kwargs.get("dir_fd") is not None and not prefix_parent_swapped[0]:
            prefix_parent_swapped[0] = True
            prefix_parent.rename(moved_prefix_parent)
            prefix_parent.symlink_to(external_prefix_parent, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    sanitizer_module.os.open = substitute_prefix_parent_before_open
    try:
        try:
            sanitizer_module.sanitize(prefix_race)
        except (OSError, SystemExit):
            pass
    finally:
        sanitizer_module.os.open = original_open
    if not prefix_parent_swapped[0]:
        raise SystemExit("prefix-parent substitution fixture did not execute before open")
    if external_prefix_token.read_text(encoding="utf-8") != "preserve":
        raise SystemExit("sanitizer followed a substituted prefix ancestor")

    late_prefix = root / "late-user-prefix"
    (late_prefix / "drive_c/users/steamuser").mkdir(parents=True)
    late_opened = sanitizer_module.open_prefix(late_prefix)
    try:
        sanitizer_module.sanitize_open(late_opened)
        os.mkdir("lateuser", dir_fd=late_opened.users_fd)
        late_user_fd = os.open("lateuser", os.O_RDONLY | os.O_DIRECTORY, dir_fd=late_opened.users_fd)
        try:
            token_fd = os.open("Cookies", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=late_user_fd)
            os.close(token_fd)
        finally:
            os.close(late_user_fd)
        os.symlink("steamuser", "latealias", dir_fd=late_opened.users_fd)
        try:
            sanitizer_module.verify_open(late_opened)
        except SystemExit:
            pass
        else:
            raise SystemExit("sanitizer accepted a late Wine user and alias after its pinned snapshot")
    finally:
        late_opened.close()

    collision_users = root / "quarantine-collision-users"
    collision_users.mkdir()
    collision_target = root / "quarantine-collision-target"
    collision_target.write_text("preserve", encoding="utf-8")
    collision_alias = collision_users / "dpad"
    collision_alias.symlink_to(collision_target)
    collision_fd = os.open(collision_users, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    collision_expected = os.stat("dpad", dir_fd=collision_fd, follow_symlinks=False)
    fixed_token = "fixed-collision"
    quarantine_name = f".dpad-sanitize-alias-{os.getpid()}-{fixed_token}"
    quarantine_path = collision_users / quarantine_name
    quarantine_path.write_text("pre-existing", encoding="utf-8")
    original_token_hex = sanitizer_module.secrets.token_hex
    sanitizer_module.secrets.token_hex = lambda _size: fixed_token
    try:
        try:
            sanitizer_module.unlink_user_alias(collision_fd, "dpad", collision_expected)
        except SystemExit:
            pass
        else:
            raise SystemExit("sanitizer overwrote a colliding quarantine entry")
    finally:
        sanitizer_module.secrets.token_hex = original_token_hex
        os.close(collision_fd)
    if not collision_alias.is_symlink():
        raise SystemExit("quarantine collision destroyed the original Wine alias")
    if quarantine_path.read_text(encoding="utf-8") != "pre-existing":
        raise SystemExit("quarantine collision destroyed the pre-existing entry")

    drive_race_prefix = root / "drive-substitution-prefix"
    drive_race_drive = drive_race_prefix / "drive_c"
    (drive_race_drive / "users/steamuser").mkdir(parents=True)
    moved_drive = drive_race_prefix / "drive_c-original"
    external_drive = root / "external-race-drive"
    external_drive_user = external_drive / "users/steamuser"
    external_drive_user.mkdir(parents=True)
    external_drive_token = external_drive_user / "account.log"
    external_drive_token.write_text("preserve", encoding="utf-8")
    original_open = sanitizer_module.os.open
    drive_swapped = [False]

    def substitute_drive_before_open(path, flags, *args, **kwargs):
        if path == "drive_c" and kwargs.get("dir_fd") is not None and not drive_swapped[0]:
            drive_swapped[0] = True
            drive_race_drive.rename(moved_drive)
            drive_race_drive.symlink_to(external_drive, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    sanitizer_module.os.open = substitute_drive_before_open
    try:
        try:
            sanitizer_module.sanitize(drive_race_prefix)
        except (OSError, SystemExit):
            pass
    finally:
        sanitizer_module.os.open = original_open
    if not drive_swapped[0]:
        raise SystemExit("drive_c substitution fixture did not execute immediately before open")
    if external_drive_token.read_text(encoding="utf-8") != "preserve":
        raise SystemExit("sanitizer followed a substituted drive_c directory")

    users_race_prefix = root / "users-after-check-prefix"
    users_race_users = users_race_prefix / "drive_c/users"
    original_race_user = users_race_users / "steamuser"
    original_race_user.mkdir(parents=True)
    (original_race_user / "original.log").write_text("remove", encoding="utf-8")
    moved_race_users = users_race_prefix / "drive_c/users-original"
    external_checked_users = root / "external-checked-users"
    external_checked_user = external_checked_users / "steamuser"
    external_checked_user.mkdir(parents=True)
    external_checked_token = external_checked_user / "external.log"
    external_checked_token.write_text("preserve", encoding="utf-8")
    users_swapped = [False]

    def substitute_users_before_user_open(path, flags, *args, **kwargs):
        if path == "steamuser" and kwargs.get("dir_fd") is not None and not users_swapped[0]:
            users_swapped[0] = True
            users_race_users.rename(moved_race_users)
            users_race_users.symlink_to(external_checked_users, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    sanitizer_module.os.open = substitute_users_before_user_open
    try:
        try:
            sanitizer_module.sanitize(users_race_prefix)
        except (OSError, SystemExit):
            pass
    finally:
        sanitizer_module.os.open = original_open
    if not users_swapped[0]:
        raise SystemExit("users substitution fixture did not execute before regular-user open")
    if external_checked_token.read_text(encoding="utf-8") != "preserve":
        raise SystemExit("sanitizer followed users substituted after its identity check")

    occupied_users = root / "occupied-restore-users"
    occupied_users.mkdir()
    original_alias_target = root / "original-alias-target"
    original_alias_target.write_text("preserve", encoding="utf-8")
    occupied_alias = occupied_users / "dpad"
    occupied_alias.symlink_to(original_alias_target)
    occupied_fd = os.open(occupied_users, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    occupied_expected = os.stat("dpad", dir_fd=occupied_fd, follow_symlinks=False)
    replacement_alias_target = root / "replacement-alias-target"
    replacement_alias_target.write_text("preserve", encoding="utf-8")
    original_rename_noreplace = sanitizer_module.rename_noreplace
    original_stat = sanitizer_module.os.stat
    occupied_restore_attempted = [False]

    def substitute_alias_before_quarantine(directory_fd, src, dst):
        if src == "dpad":
            os.unlink("dpad", dir_fd=occupied_fd)
            os.symlink(replacement_alias_target, "dpad", dir_fd=occupied_fd)
        return original_rename_noreplace(directory_fd, src, dst)

    def occupy_name_after_quarantine_check(path, *args, **kwargs):
        captured = original_stat(path, *args, **kwargs)
        if str(path).startswith(".dpad-sanitize-alias-") and not occupied_restore_attempted[0]:
            occupied_restore_attempted[0] = True
            Path(occupied_users / "dpad").write_text("new occupant", encoding="utf-8")
        return captured

    sanitizer_module.rename_noreplace = substitute_alias_before_quarantine
    sanitizer_module.os.stat = occupy_name_after_quarantine_check
    try:
        try:
            sanitizer_module.unlink_user_alias(occupied_fd, "dpad", occupied_expected)
        except SystemExit:
            pass
        else:
            raise SystemExit("sanitizer accepted a mismatched quarantined Wine user alias")
    finally:
        sanitizer_module.rename_noreplace = original_rename_noreplace
        sanitizer_module.os.stat = original_stat
        os.close(occupied_fd)
    quarantines = list(occupied_users.glob(".dpad-sanitize-alias-*"))
    if not occupied_restore_attempted[0]:
        raise SystemExit("occupied quarantine restore fixture did not execute")
    if not occupied_alias.is_file() or occupied_alias.read_text(encoding="utf-8") != "new occupant":
        raise SystemExit("mismatched quarantine restore overwrote the occupied original name")
    if len(quarantines) != 1 or not quarantines[0].is_symlink():
        raise SystemExit("mismatched quarantine was not preserved when restore destination was occupied")

    entry_race_users = root / "entry-substitution-users"
    entry_race_users.mkdir()
    entry_alias = entry_race_users / "dpad"
    entry_alias.symlink_to(original_alias_target)
    replacement = root / "replacement-user-directory"
    replacement.mkdir()
    replacement_token = replacement / "must-survive"
    replacement_token.write_text("preserve", encoding="utf-8")
    entry_fd = os.open(entry_race_users, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    expected_alias = os.stat("dpad", dir_fd=entry_fd, follow_symlinks=False)
    original_rename_noreplace = sanitizer_module.rename_noreplace
    entry_swapped = [False]

    def substitute_alias(directory_fd, src, dst):
        if src == "dpad" and not entry_swapped[0]:
            entry_swapped[0] = True
            os.unlink("dpad", dir_fd=entry_fd)
            os.rename(replacement, entry_alias)
        return original_rename_noreplace(directory_fd, src, dst)

    sanitizer_module.rename_noreplace = substitute_alias
    try:
        try:
            sanitizer_module.unlink_user_alias(entry_fd, "dpad", expected_alias)
        except SystemExit:
            pass
        else:
            raise SystemExit("sanitizer accepted a substituted regular Wine user directory")
    finally:
        sanitizer_module.rename_noreplace = original_rename_noreplace
        os.close(entry_fd)
    if not entry_swapped[0] or not entry_alias.is_dir() or entry_alias.is_symlink():
        raise SystemExit("Wine user directory substitution fixture was not restored")
    if (entry_alias / "must-survive").read_text(encoding="utf-8") != "preserve":
        raise SystemExit("sanitizer deleted a substituted regular Wine user directory")

    for relative in (
        "drive_c/users/dpad/AppData/Roaming/Battle.net/account-token",
        "drive_c/ea-setup/EAappInstaller.exe",
        "drive_c/ProgramData/Battle.net/Agent/data/cache/agent-state.bin",
        "drive_c/windows/temp/installer-residue.tmp",
    ):
        residue_prefix = root / f"residue-{relative.split('/')[1]}-{len(relative)}"
        residue = residue_prefix / relative
        residue.parent.mkdir(parents=True, exist_ok=True)
        residue.write_text("must be rejected", encoding="utf-8")
        try:
            sanitizer_module.verify_clean(residue_prefix)
        except SystemExit:
            pass
        else:
            raise SystemExit(f"sanitizer postcheck accepted store-specific residue: {relative}")

    template = root / "template"
    template.mkdir()
    (template / "system.reg").write_text(
        f'WINE REGISTRY Version 2\n"MachineGuid"="{PLACEHOLDER}"\n', encoding="ascii"
    )
    required = template / "drive_c/client.exe"
    write_pe(required)
    (template / ".dpad-preinstalled").touch()

    symlink_marker_template = root / "symlink-marker-template"
    shutil.copytree(template, symlink_marker_template)
    (symlink_marker_template / ".dpad-preinstalled").unlink()
    (symlink_marker_template / ".dpad-preinstalled").symlink_to(required)
    result = run(
        str(CLONER),
        str(symlink_marker_template),
        str(root / "symlink-marker-destination"),
        "--required",
        "drive_c/client.exe",
        check=False,
    )
    if result.returncode == 0:
        raise SystemExit("atomic cloner accepted a symlinked template marker")

    linked_template_parent = root / "linked-template-parent"
    linked_template_parent.symlink_to(root, target_is_directory=True)
    result = run(
        str(CLONER),
        str(linked_template_parent / template.name),
        str(root / "linked-template-destination"),
        "--required",
        "drive_c/client.exe",
        check=False,
    )
    if result.returncode == 0:
        raise SystemExit("atomic cloner accepted a template beneath a symlinked ancestor")

    real_destination_parent = root / "real-destination-parent"
    real_destination_parent.mkdir()
    linked_destination_parent = root / "linked-destination-parent"
    linked_destination_parent.symlink_to(real_destination_parent, target_is_directory=True)
    result = run(
        str(CLONER),
        str(template),
        str(linked_destination_parent / "runtime-prefix"),
        "--required",
        "drive_c/client.exe",
        check=False,
    )
    if result.returncode == 0 or "destination path must not use symlinks" not in result.stderr:
        raise SystemExit("atomic cloner did not explicitly reject a symlinked destination ancestor")

    symlink_required_template = root / "symlink-required-template"
    shutil.copytree(template, symlink_required_template)
    linked_required = symlink_required_template / "drive_c/client.exe"
    linked_required.unlink()
    linked_required.symlink_to(required)
    result = run(
        str(CLONER),
        str(symlink_required_template),
        str(root / "symlink-required-destination"),
        "--required",
        "drive_c/client.exe",
        check=False,
    )
    if result.returncode == 0 or "required template executable must be regular" not in result.stderr:
        raise SystemExit("atomic cloner did not directly reject a symlinked required executable")

    destination = root / "runtime-prefix"
    run(str(CLONER), str(template), str(destination), "--required", "drive_c/client.exe")
    if not (destination / ".dpad-preinstalled").is_file():
        raise SystemExit("atomic clone did not create final marker")
    registry = (destination / "system.reg").read_text(encoding="ascii")
    match = re.search(r'"MachineGuid"="([^"]+)"', registry)
    if not match or match.group(1) == PLACEHOLDER or uuid.UUID(match.group(1)).int == 0:
        raise SystemExit("atomic clone reused the template MachineGuid")

    existing = root / "existing-prefix"
    existing.mkdir()
    keep = existing / "keep-user-state"
    keep.write_text("preserve", encoding="utf-8")
    result = run(
        str(CLONER), str(template), str(existing), "--required", "drive_c/client.exe", check=False
    )
    if result.returncode != 3 or keep.read_text(encoding="utf-8") != "preserve":
        raise SystemExit("atomic clone did not preserve a non-empty existing prefix")

cloner_source = CLONER.read_text(encoding="utf-8")
if "fsync_tree(stage)" not in cloner_source or "os.fsync(parent_fd)" not in cloner_source:
    raise SystemExit("atomic cloner does not durably fsync payload tree and parent directory")

for launcher, installed, publisher in (
    ("ea-launch", "ea_installed", "Electronic Arts, Inc."),
    ("ubisoft-launch", "ubi_installed", "UBISOFT ENTERTAINMENT INC."),
    ("battlenet-launch", "bn_installed", "Blizzard Entertainment, Inc."),
):
    source = (SCRIPTS / launcher).read_text(encoding="utf-8")
    if f"if ! {installed} && [ -f \"$PREBAKED_SRC/.dpad-preinstalled\" ]; then" not in source:
        raise SystemExit(f"{launcher} can overlay a template onto an existing installed prefix")
    if 'cp -a "$PREBAKED_SRC/.' in source:
        raise SystemExit(f"{launcher} still performs a non-atomic marker-bearing copy")
    if "/opt/dpadcloud/dpad-clone-prefix-template" not in source:
        raise SystemExit(f"{launcher} does not use the atomic template cloner")
    if "/opt/dpadcloud/dpad-verify-windows-binary" not in source or publisher not in source:
        raise SystemExit(f"{launcher} runtime fallback executes an unverified installer")

preinstall = (SCRIPTS / "build-preinstall-stores.sh").read_text(encoding="utf-8")
if "/opt/dpadcloud/dpad-sanitize-store-prefix" not in preinstall:
    raise SystemExit("unified preinstall does not use the fail-closed sanitizer")
if "/opt/dpadcloud/dpad-verify-windows-binary --pe-only" not in preinstall:
    raise SystemExit("unified preinstall does not reject invalid installed executables")
if "EA Desktop/EA Desktop/EALauncher.exe" not in preinstall:
    raise SystemExit("unified preinstall rejects the supported non-versioned EALauncher layout")

for bootstrap, publisher in (
    ("build-bootstrap-battlenet.sh", "Blizzard Entertainment, Inc."),
    ("build-bootstrap-ea.sh", "Electronic Arts, Inc."),
    ("build-bootstrap-ubisoft.sh", "UBISOFT ENTERTAINMENT INC."),
):
    source = (SCRIPTS / bootstrap).read_text(encoding="utf-8")
    if "/opt/dpadcloud/dpad-verify-windows-binary" not in source or publisher not in source:
        raise SystemExit(f"{bootstrap} executes an installer without expected-publisher verification")

dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
for required_text in (
    "osslsigncode",
    "dpad-sanitize-store-prefix",
    "dpad-verify-windows-binary",
    "dpad-clone-prefix-template",
    "microsoft-identity-root-2020.pem",
):
    if required_text not in dockerfile:
        raise SystemExit(f"Dockerfile does not package security dependency: {required_text}")

print("Store template security and atomicity: PASS")
