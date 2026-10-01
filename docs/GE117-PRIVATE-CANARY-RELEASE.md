# GE-Proton11-7 private canary release

## Scope

Publish one account-free official-store image to a new versioned canary tag in
`forcespt/dpadcloud-gaming`. Keep customer image references unchanged. A registry
push creates no VM and does not deploy the website. Use the returned registry
digest for the existing private admin test selector; a local image ID is not a
substitute for a remotely verified pull reference.

Runtime source: `460ca0b` (resolve the full Git revision at build time).
Verified local base: `dpadplay/official-stores:ge117-complete`, image ID
`sha256:7f761f3c8e80367208e6ae31cc44c901a22b9936e0467f971a45d7cbdc9eafe2`.
`Dockerfile.official-store-canary` adds release provenance to this verified base;
it does not rebuild or change the runner, wrappers or installation templates.

## Evidence and settings

- Global runner: GE-Proton11-7; Steam Windows tool: GE-Proton11-7-x86_64.
- Epic uses Faugus with the official Epic client; GOG uses official Galaxy.
- Official Epic/GOG/Battle.net/EA/Ubisoft installation templates are included.
- The normal gaming entrypoint is retained; no local noVNC harness is included.
- Scoped compatibility components were rebuilt from pinned GE11 sources.
- Package parity/selector checks, five native-loader boundaries, nine
  preservation checks and actual GOG cold/restore wrapper fixture passed.
- Owner client acceptance and known first-launch caveat: PROJECT_STATE.md.
- Private profile volumes and authenticated logs/screenshots are excluded.

The inherited `DPAD_FAUGUS_CLIENT_ONLY_TEST=1` is intentional: an Instant admin
test opens the store picker without pretending the shared game is registered.
Official shared-game recognition needs its separately reviewed capsule, private
write overlay and matching control-plane changes. This image alone does not
complete that deployment.

## Publication and provider test sequence

1. Check the base ID, committed release source and account-free package receipt.
2. Build the metadata layer from a clean committed context and label the full
   release/runtime revisions and exact verified base image ID.
3. Verify the final labels, expected entrypoint/defaults, package parity and
   installation-template scrubber in disposable containers with no owner mounts.
4. Publish only the new canary tag; record the returned digest and independently
   compare the remote manifest with the local image. Do not retag a public default.
5. Read current production admin-selector/Compose state before preparing any
   cutover. Historical hardcoded September scripts are not current release plans.
   Use an exact rollback and deadline appropriate to the newly approved test.
6. Obtain a fresh bounded provider-test authorization before creating a paid VM.
   Check startup, NVIDIA/EGL, video/audio/input and cleanup on that exact digest.
7. Gameplay is deferred from local testing to live providers at the owner's
   request. Record it as pending until observed; verify game/shared-storage
   behavior before broad customer promotion.

Runtime registry preparation is deployed with admission off and management
disabled. Do not enable that registry or mark an unqualified binding active to
deliver this private image test. Other provider/profile combinations require
their own qualification.

## Rollback

Publication alone requires no runtime rollback because it changes no binding.
For a private-selector cutover, preserve the exact prior image/deadline/settings
and Compose chain, then restore that baseline when the test ends. Never reuse a
completed session's resource IDs or expired timer. Preserve customer/private
volumes; confirm exact paid VM and boot-volume absence after teardown.
