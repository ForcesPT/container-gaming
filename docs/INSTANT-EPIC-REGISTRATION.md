# Instant Play: private Epic installation registration

## Status and customer flow

Implemented locally, not deployed and not GPU/gameplay accepted.

1. The trusted host adapter supplies the pinned release mount and credential-free installation metadata.
2. Before the DpadPlay desktop launcher starts, `launcher-shell` invokes the registration helper as the session user. This prevents a pre-existing Heroic GUI from caching an empty installed-game list. The Epic wrapper repeats the check idempotently before opening Heroic.
3. The customer opens Epic/Heroic, signs into their own account **inside the isolated GPU session**, and chooses Play. Heroic/Legendary handle their normal online launch, ownership-token requirements, Wine/Proton and any required store checks. Registration is file inventory, **not proof of entitlement**.
4. Credentials, Heroic configuration, Wine prefixes, caches and saves use the session's existing private ephemeral HOME/rootfs, never the catalog. Login time remains billable GPU time and must be disclosed on the customer path.

No installer account, tokens, signed CDN URL, offline-login bypass, raw executable launch, game import/download/repair command, or website ownership check is involved in registration. It does not automatically press Play or claim that a game is running. The payload remains a read-only bind, with no per-session game copy.

## Why not `legendary import-game`?

Inspected Legendary 0.21.1 `core.import_game`: without an existing `.egstore` manifest it downloads the **latest** vendor manifest. That may describe a different release from the session's immutable pin. We must not invent matching version metadata, write `.egstore` into the shared payload, or silently update a pinned installation.

The helper instead writes the supported installed-record shape to Heroic's private Legendary registry:

`$HOME/.config/heroic/legendaryConfig/legendary/installed.json`

The path was checked against Heroic v2.22.0's `legendary/constants.ts`; the record shape was checked against Legendary 0.21.1 `InstalledGame` and read back using the real `LGDLFS.get_installed_game` implementation. Heroic GUI and authenticated online launch still need acceptance using the exact candidate image.

Sources inspected:
- https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/v2.22.0/src/backend/storeManagers/legendary/constants.ts
- https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/v2.22.0/src/backend/storeManagers/legendary/games.ts

## Metadata contract and provenance

The root-owned host request now requires `metadata` with exactly:

- `app`: alphanumeric-first Epic identifier, maximum 128 characters, matching the session app.
- `title`: original public game title, maximum 512 characters.
- `version`: **original selected release's** vendor build version, maximum 256 characters.
- `executable`: sealed regular file relative to the game root, maximum 1024 characters; no absolute paths, parent traversal, Windows drive prefixes, backslashes or symlink traversal. The handoff producer must normalize a vendor Windows path before admission.
- `launchParameters`: original vendor launch parameters, maximum 4096 characters; not a shell command override.
- `requiresOwnershipToken`: required Boolean copied from the vendor's public ownership-token requirement; do not guess false when absent from an unvalidated source.
- `installSize`: positive integer public installation size, at most 2 TiB.

No control characters or unknown fields are accepted. The whole host request retains its tighter 4096-byte cap. Metadata must come from the selected, verified release and original vendor metadata, within the trusted pin-producing transaction. It is **not** an Internet/customer request schema. The control-plane producer and its provenance binding are still pending; these source tests use an explicitly labeled tiny fixture, not invented ABZU metadata.

`dpad_instant_mount.py` validates the descriptor and supplies base64 JSON via `DPAD_INSTANT_METADATA`, together with `DPAD_INSTANT_APP`. Base64 prevents shell/line-delimiter interpretation; it is not encryption, a signature, or an entitlement. Both helpers must be installed beside the maintained host launcher in one verified root-controlled bundle. The Dockerfile includes the registration helper beside the two image wrappers.

## Filesystem and concurrency behavior

The CLI refuses root execution, missing/mismatched metadata, a redirected `XDG_CONFIG_HOME`, and a game mount without the kernel read-only flag. File sealing and resolved-path checks are additional to, not replacements for, read-only mount validation.

Registration uses the same `installed.json.lock` flock boundary as Legendary on Linux, nonblocking acquisition, a private temporary file, fsync and atomic replacement. State directories must belong to the session user and not be group/world writable. Registry and lock redirects/hardlinks are refused. Corrupt or conflicting installed records are not silently repaired or replaced; other games' entries are retained. Matching records are idempotent and retain fields subsequently added by Heroic.

The new inventory record defaults to online launch (`can_run_offline=false`) and preserves the supplied ownership-token requirement. `needs_verification=true` deliberately does not masquerade as a Legendary full-file verification receipt. The DpadPlay immutable release verification remains upstream. No `.egstore`, payload, prefix or credential file is touched by this helper.

The shell has a 15-second helper timeout. Sanitized registration status is logged locally; it is **not** a trusted game-readiness, billing-stop or unpin receipt. The session shell remains the DpadPlay launcher. Cloud Compute without Instant environment variables follows its existing path.

## Executed local verification

Run using an environment containing Legendary 0.21.1, plus `bwrap` with unprivileged namespaces enabled:

```sh
/home/home/.cache/dpad-instant-tools/legendary-0.21.1/bin/python \
  -m unittest discover -s scripts -p 'test_instant*.py'
bash -n scripts/launcher-shell scripts/epic-launch scripts/dpad-launch-session entrypoint.sh scripts/vm-bootstrap.sh
```

Ten tests passed, none skipped. The integration case executes the real host argument compiler and Bash image wrappers, a real Python registration helper, and real Legendary registry reading. It creates an isolated network-disabled namespace with an actual read-only selected-game bind. Heroic and the desktop GUI are explicit recording stand-ins, not fabricated store responses. It proves registration-before-GUI handoff, kernel-writable-mount refusal, missing metadata refusal, unchanged ordinary store flow, private registry mode, pinned version preservation and unchanged fixture payload. Unit cases cover malformed metadata, option-like app IDs, redirected registry, conflicts and idempotence. Legendary's upstream registry loader emits a nonfatal ResourceWarning for its own `json.load(open(...))` implementation; no dependency was patched or warning hidden.

Existing TURN, hotfix-bundle, stream-quality, FPS, desktop selection, launcher-only, prefix identity, preinstalled-store, store-template-security and Dockerfile-pin regressions passed. No sudo, paid VM, store authentication, game payload download or production mutation was performed.

## Still required before paid testing

- Trusted control-plane construction of this exact request from a live session pin and original vendor metadata.
- Exact image/host-bundle staging and independent game-host to Paris private-NFS acceptance.
- Identity-bound teardown and durable cleanup acknowledgement before unpinning; current desktop-ready output is not game-ready and does not prove the seven-minute end-to-end ceiling.
- Separately authorized GPU acceptance: actual customer login, owned-game launch, no-ownership behavior, Wine state/saves, video/audio/controller, cold/hot timing, teardown and billing stop.

Keep ABZU unpublished/Maintenance until those gates pass. This feature alone does not make the platform ready for a paid GPU test.
