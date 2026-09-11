# Instant host lifecycle (source only)

`dpad_instant_lifecycle.py` is a root-only companion to the maintained
`dpad-launch-session`, mount validator and private installation registrar.
Install all four files as a matched, hash-verified host bundle. The image must
also contain its previously implemented launcher-shell/registration integration.

- `launch BASE64_REQUEST PASSWORD WIDTH HEIGHT FPS` writes the exact request in
  `/run/dpad-instant/requests/<session>.json` (0600, exclusive, immutable replay).
  It invokes the maintained launcher with `none none` and `DPAD_INSTANT_CONFIG`.
- Launch and cleanup share a nonblocking host slot lock. Deadline uses the
  request's original absolute expiry; replay cannot extend it. Launcher timeout
  kills its process group but deliberately leaves the pin/request for recovery.
- Ready requires the maintained launcher's DPAD_READY result, the expected live
  container labels, successful installation-registration log and exact
  `dpad-launcher` process. This is runtime readiness, not gameplay/video proof.
- `cleanup SESSION RELEASE SLOT` checks engine availability and exact immutable
  container ID/labels. It refuses a different owner, unexpected Docker volumes,
  failed deletion or remaining session containers. Only then does it delete the
  request and emit the identity-bound `cleanup_confirmed` receipt.
- Cleanup never calls the legacy slot-only stop command, never unmounts the
  shared read-only host catalog and never touches another session's store state.
  Container-private writable state and its selected bind mount are removed by
  confirmed Docker container deletion. Unexpected volume state requires review.

The control plane must terminalize the session and settle the durable provision
lease before cleanup; release the game pin only after the exact receipt, then
release the slot. Host locks complement rather than replace that database fence.

Tests use isolated user/mount namespaces and fixture engine/launcher commands,
plus actual Legendary inventory/read-only namespace tests from registration.
They allocate no GPU and do not certify a production Docker/NFS/image boundary.
Private route/NFS and a real-image GPU/stream test remain explicit acceptance
requirements. Public activation remains disabled.
