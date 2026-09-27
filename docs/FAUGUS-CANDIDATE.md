# Faugus official Epic candidate — 2026-09-27

## Scope

Separate Dockerfile.faugus extends the exact accepted gaming runtime digest
59c8efe85c30224c5e9e878c577b78d3b9563cdecf0763665eb297a50d837d20.
This is a local candidate, not a production replacement or gameplay qualification.
No cloud VM was started for this work.

The existing Epic picker card invokes epic-launch. DPAD_EPIC_BACKEND=faugus
routes that wrapper to Faugus and the official Windows Epic Games Launcher.
The default backend in the existing images remains heroic. Provider adapters do
not participate in this choice: the image/profile selects the backend.

## Pinned components

- Faugus 2.4.2, commit 7737a92c55b890381050c745801f1e463478de3d.
- Source archive SHA256 2de1b4df9e02ac3246369ccbb0db0cd3e037cf7b46ec07097a494affb1013168.
- Existing image UMU and GE-Proton11-3; no Faugus component/runner auto-update.
- Official Epic MSI SHA256 d55d79710edfeaa107a62f2ea007bec1eeeac8b715a43c2ba3858eec7bc60337.

Epic's installer URL is mutable. A changed download deliberately fails the build;
review the new installer and update the checksum before rebuilding. The Epic
client itself can still perform its normal updates; this image does not promise
to pin the client after installation.

Faugus receives two narrow, exact-match patches: use /usr/bin/umu-run and honour
disabled component downloads even when optional EAC/BattleEye components are
absent. This does not qualify anti-cheat compatibility.

## Private state and launch

Prefix: $HOME/Faugus/epic-games. Config/inventory: private Faugus directories
under $HOME/.config and $HOME/.local/share. Login is performed by the customer
in official Epic. No account token is seeded in the image or inventory.

With DPAD_VOLUME_MOUNT, the wrapper instead uses <volume>/faugus for prefixes,
config, inventory and state. DPAD_FAUGUS_STATE_ROOT can explicitly override this
with an absolute path on a private user volume. The root must be owned by the
session user and not writable by other users. A configured missing volume is
refused rather than silently losing state. The provider/profile is responsible
for attaching the correct user's volume; never use a shared game master as this
state root. No entrypoint replacement is needed for these paths.

Changing the configured state root is not an automatic migration of existing
ephemeral client state. Choose it before the first Epic installation/login.

First launch shows the cached official MSI through the pinned runner. The user
completes the installer. Subsequent launches use the managed dpad-epic record.
An advisory lock serializes the wrapper through client exit. Managed paths are
validated; unrelated games and Epic playtime are retained. Repeated preparation
removes custom hooks from the managed Epic entry.

## Local verification

Build command:

    docker build -f Dockerfile.faugus -t dpadplay-faugus-candidate:2.4.2 .

Contract tests (temporary Linux container, bind scripts read-only):

    python3 /work/test_faugus_prepare.py

Runtime smoke: scripts/test_faugus_runtime.sh runs only inside a disposable
container. It REPLACES UMU with a stub there; never run it in a customer session.
It proves the actual Faugus runner dispatches with the pinned prefix, runner,
disabled updates, and that Instant launch is refused. It does not execute Wine,
install Epic, authenticate, or render a game.

Eight contract tests passed, including state preservation with a replacement
home, separate-volume isolation and refusal of an untrusted volume. Actual
Faugus imports and command generation passed under Xvfb. The complete wrapper
with the real Faugus runner and a stub UMU installed once and launched twice
from the private volume, without downloading private UMU.

The inherited picker archive is extracted, patched with an exact selector
match, and repackaged using @electron/asar 3.2.17 in a pinned Node build stage.
Only the Epic selector changes: official Epic for Faugus, Heroic otherwise.
Packaged selector/title-detection and native koffi import checks passed. Actual
window WM_CLASS/focus still needs confirmation on the GPU session.

## Required before promotion

1. Official Epic installer and login under a GPU session; ownership rejection for
   an account without the test game, then successful ABZU gameplay for an owner.
2. Export genuine official Epic .item/.egstore installation metadata. Current
   Instant descriptors seed Legendary/Heroic only and lack official catalog
   identifiers. Do not invent these or mark a shared payload as installed.
3. Qualify official Epic verification/update behaviour against shared read-only
   game storage. Use private writable state/overlay where needed; never let a
   customer mutate the provider's shared master files.
4. Confirm prefix/login persistence in real Dedicated/Shared profiles and volume
   attachment isolation across two accounts. Local volume tests pass.
5. Confirm official Epic window class and picker resume/focus on a GPU. The
   packaged selector and native dependency tests pass locally.
6. Validate fullscreen/taskbar behaviour and stream recovery with the real game.
7. Publish an immutable candidate image, register it as a canary profile and
   promote only after the above results. No live profile was switched here.

Until official import is qualified, launcher-shell refuses Instant sessions
when the Faugus backend is selected. Cloud Compute is the initial test target.
GOG, EA, Ubisoft and Battle.net remain separate future qualifications.
