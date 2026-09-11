# Instant selected-release mount integration

## Status

Source implementation only. Not deployed, no GPU or Docker container run. Selected-release mounting and private Heroic/Legendary installation registration are implemented. Customer login and launch authorization remain the normal in-VM store flow; no separate website ownership check was added. **Not a complete Instant game runtime:** control-plane handoff construction, admission-pin authority, durable cleanup, actual image and authenticated gameplay acceptance remain pending. See `INSTANT-EPIC-REGISTRATION.md`.

## Maintained launcher interface

`dpad-launch-session launch <slot> none none <stream-password> <digest-image>` remains the launcher. An opt-in `DPAD_INSTANT_CONFIG=/run/dpad-instant/requests/<session-uuid>.json` enables validation before any Docker call. Never put stream credentials in this JSON.

The request must be root-owned0600, regular, single-link, at most4096 bytes with root-controlled parent directories. Duplicate and unknown JSON fields are refused. Fields:

- `sessionId`, `releaseId`: canonical UUID strings; filename matches session.
- `slot`: integer0–31, matching invocation.
- `manifestSha256`: pinned final manifest digest.
- `image`: `forcespt/dpadcloud-gaming@sha256:<digest>`, matching invocation.
- `app`: Epic app identifier, not a command or executable.
- `metadata`: credential-free pinned installation descriptor, with exactly `app`, `title`, `version`, `executable`, `launchParameters`, `requiresOwnershipToken`, `installSize`. Its app must match the top-level app. The trusted adapter must obtain this from the selected verified release and its original vendor metadata, not current/latest metadata or customer-provided fields. See the registration document for limits and provenance requirements.
- `scratchGiB`: explicit integer1–200. No new storage-budget default is imposed.
- `expiresAt`: absolute integer Unix time, still future and no more than420s away.

This is a trusted host handoff, not an Internet API: the control-plane adapter must establish a valid live session pin and authorization before producing it. No contract writer or entitlement bypass was added.

`dpad_instant_mount.py` and `dpad_instant_register.py` must be staged alongside the launcher in one verified, root-controlled host bundle. The latter provides shared metadata validation. No mutable network download was added to bootstrap. A missing helper fails closed. Host distribution/digest verification and exact image packaging must be completed before activation.

The helper reads kernel `findmnt` data for `/srv/dpad-instant/paris/releases`. It requires `10.80.0.2:/releases`, NFS4, ro/nosuid/nodev/vers4.1. It does **not** create/remount an export or alter fstab. Selected wrapper/files/manifest must be sealed and non-symlinked; manifest digest must match.

Only `<release>/files` is bound at `/opt/dpad-instant/game`, readonly and `bind-recursive=disabled` to exclude nested mounts. Docker must support that option and the immutable image must already be staged (`--pull=never`). Neither the full catalog nor the installer directory is exposed by this bind.

Private writes use the existing ephemeral container rootfs storage mechanism with the contract's explicit quota; no provider volume or shared writable prefix is mounted. Existing Docker/XFS project-quota enforcement is still a host prerequisite, not proven by argument tests. `DPAD_STORES=epic`, `DPAD_INSTANT_APP` and base64-encoded `DPAD_INSTANT_METADATA` are supplied. The Epic wrapper registers inventory before opening Heroic, but never auto-runs the executable or authenticates as the installer. Base64 is transport encoding, not encryption or an authorization signature.

Instant slots refuse occupied names; they never run the normal stale-container removal path. Readiness waiting is limited by the earlier of the contract deadline and existing360s desktop limit. This remains **desktop readiness**, not game readiness. Docker start/mount hangs, timeout reconciliation, session-identity-bound stop and pin-release acknowledgement need the lifecycle adapter; do not claim the end-to-end7-minute guarantee yet.

Cloud Compute without `DPAD_INSTANT_CONFIG` retains existing behavior. Security flags were not broadened. Existing SYS_ADMIN/unconfined/host-network settings are not proof of multi-tenant isolation; do not enable shared-customer use based on these tests.

## Verification

`python3 -m unittest discover -s scripts -p test_instant_mount.py`: seven tests pass. Red failures preceded implementation for missing mount integration, validation, CLI refusal, launcher guard, image-pull denial and metadata handoff. Cases cover malformed bindings/options, expired requests, changed/writable releases, selected-only mount args, occupied slots, metadata app mismatch and unchanged ordinary launch behavior.

The positive Bash test uses the real compiler and maintained launcher but a fixture for root-request/NFS CLI transport and a recording Docker executable. It proves argument integration, **not actual NFS/Docker/GPU isolation**. The CLI's untrusted-request denial is executed directly; positive root-owned request acceptance is not yet exercised on a real host.

Existing regression scripts passed: TURN/ports, stream hotfix bundle, stream quality, FPS plumbing, Sway/Labwc selection, launcher-only architecture, prefix identity and preinstalled stores. Launcher shell syntax passed.
