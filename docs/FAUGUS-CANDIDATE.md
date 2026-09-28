# Faugus official Epic candidate — 2026-09-27

## Scope

Separate Dockerfile.faugus extends the exact accepted gaming runtime digest
59c8efe85c30224c5e9e878c577b78d3b9563cdecf0763665eb297a50d837d20.
This is a scoped candidate, not a production replacement or gameplay qualification.

Candidate source was published on `feat/faugus-epic-candidate` at `77d1aaf`.
The separate admin canary image is
`forcespt/dpadcloud-gaming@sha256:53bb9c50d12a49c461d5d445e49fe761b32cd0c9bc6674a41085019fe2dd1f49`.
No public production image binding was changed.

The existing Epic picker card invokes epic-launch. DPAD_EPIC_BACKEND=faugus
routes that wrapper to Faugus and the official Windows Epic Games Launcher.
The default backend in the existing images remains heroic. Provider adapters do
not participate in this choice: the image/profile selects the backend.

## Pinned components

- Faugus 2.4.2, commit 7737a92c55b890381050c745801f1e463478de3d.
- Source archive SHA256 2de1b4df9e02ac3246369ccbb0db0cd3e037cf7b46ec07097a494affb1013168.
- Existing image UMU and GE-Proton11-3. The newer diagnostic candidate adds
  pinned GE-Proton10-34 for Epic; no Faugus component/runner auto-update.
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

The inherited picker archive is extracted, patched with an exact focus-handler
match, and repackaged using @electron/asar 3.2.17 in a pinned Node build stage.
Local Xvfb/Proton launch of the installed official client observed window title
`Epic Games Launcher` and generic WM_CLASS `steam_app_default`. The Faugus route
now focuses by title; Heroic remains class-based. Sway and Labwc paths are both
adapted. Packaged selector/title detection, native koffi import and Labwc
translation checks passed. Real desktop focus still needs GPU stream confirmation.

The official Epic MSI also completed a quiet local install through the actual
Faugus/GE-Proton/UMU path. The executable appeared under the private volume.
The local Docker GPU showed NVIDIA to `nvidia-smi` but Vulkan exposed only
llvmpipe, so this does not qualify graphics or game performance.

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
5. Confirm picker resume/focus on a streamed GPU. Local observed title and
   corrected Sway/Labwc selector tests pass.
6. Validate fullscreen/taskbar behaviour and stream recovery with the real game.
7. Register the published immutable image as a canary profile and promote only
   after the above results. No live profile was switched here.

Until official import is qualified, launcher-shell refuses Instant sessions
when the Faugus backend is selected. Cloud Compute is the initial test target.
GOG, EA, Ubisoft and Battle.net remain separate future qualifications.

## Admin client-only canary

The candidate image has `DPAD_FAUGUS_CLIENT_ONLY_TEST=1` for the approved admin
test. When launched with an Instant game descriptor, it deliberately skips the
Heroic/Legendary registration and opens the normal DpadPlay picker. The official
Epic client can then be installed and signed into on a real GPU. It does not claim
ABZU is installed from the shared mount. No production image uses this opt-in.
Removing the flag restores the refusal gate; the local contract test checks both.

The control API has a separate `INSTANT_PLAY_TEST_IMAGE_REF` for the authenticated
admin test route. Public `/api/sessions` continues to use `INSTANT_PLAY_IMAGE_REF`.
The override accepts only immutable `forcespt/dpadcloud-gaming@sha256:` references;
an invalid test value fails closed. This is an image-selection route for the
bounded canary, not a general provider or release promotion.

## First GPU canary — 2026-09-27

One user-approved Paris L4 admin test launched session
`705a7a3d-5877-4a3f-b9f2-17aeb2fb695f` with the exact digest above. The
VM bootstrapped, the session reached ready, and the embedded Selkies player
rendered the DpadPlay picker with the Epic Games card. Video and audio WebRTC
channels connected in that embedded player. A simultaneous direct player tab
repeatedly had its signaling connection closed; this test did not establish
whether single-player navigation can reconnect cleanly after its prior peer
closes. The official Epic installer, login and ABZÛ were not exercised in this
GPU run, so the launcher's GPU compatibility and shared game import remain
unqualified.

The session ended at 23:13:49 UTC and billed $1.29. The exact Scaleway server
`18670c9d-e7e7-478e-9716-e748eaf3341f` and its verified SBS boot volume
`3fb9e8aa-c01c-4902-b551-e919effcd8a0` were destroyed; both native GETs
returned 404. The API test selector was cleared and the previous API image
`sha256:1d107049e195522665afb1f9a018a763934ec3048eb29165e4ac750c606a96e6`
was restored with public health HTTP 200. A fresh paid test requires a new
authorization.

## Direct-player handoff follow-up — 2026-09-28

The concurrent direct-tab failure is addressed in control repo commit `8832e61`
on `ops/maintained-web-release`: clicking New tab synchronously unmounts the
embedded Selkies iframe before opening the direct player, and Resume here is
available after the direct tab closes. Its focused Playwright handoff test passed.
The owner approved the website-only release of control revision
`2634c6fda17c0ca081c7e5f1c11d0df2012a15f0` on 2026-09-28. The maintained
release command accepted it after the guarded web cutover and live HTTP/asset
checks (receipt `run-3a970b7edbc9447caecaebf48848b7ff`). The live web container
was independently observed healthy on image
`sha256:b8eb1e3f5383d2bd8d90faf2e6c11e88e7968fcca7455cf271908652e598695d`.
The release did not start a gaming VM or promote the Faugus image. Real direct-tab
reconnection, official Epic installation/sign-in, and ABZÛ gameplay still require
a separately authorized bounded GPU canary.

## Second GPU canary — 2026-09-28

One separately approved Paris L4 admin test launched session
`3baa89c6-92e3-4a94-9337-07fbe814045a` on the exact Faugus image digest
above. It reached ready at 00:45:13 UTC. The embedded Selkies player rendered
the picker with hardware H.264. New tab removed the embedded player and the
direct tab connected immediately; after closing it, Resume here restored the
embedded player. Three direct-player signaling closures at 00:49, 00:53 and
00:57 UTC recovered video and audio within about two seconds. The owner clicked
START and confirmed the picture appeared. This qualifies the handoff and brief
reconnect for this browser/VM run, but does not qualify game playback.

The Epic card launched the official Windows Epic MSI in Faugus/UMU/GE-Proton.
The installer completed, and Epic's own log reported a successful self-update.
The installed launcher then returned to the picker rather than displaying a
login window. Its updater log reported `StartServiceFailed` (exit code 8).
Repeated Epic launches also returned to the picker. Adding `-opengl` to the
disposable running container's managed launch command did not resolve it; that
change was not made to the source image or any production profile. Official
Epic login, ABZÛ ownership/import and gameplay remain unqualified. Investigate
the updater's service startup path under this Proton runner before another
billed GPU test.

The session ended at 00:59:38 UTC after 865 billed GPU seconds, with the $1.29
minimum charge and billing finalized at 00:59:42 UTC. The exact VM was
`f357058e-ade7-44fc-93a3-bab6afd02610`, with attached SBS volume
`e558c41e-41a5-4796-b0d3-ac0322cdd63b`. The scheduler destroyed it after
the normal drain grace; both native GETs returned 404 at 01:11 UTC. The bounded
fallback teardown timer was then disabled. The separate admin API test image
selector was cleared, the previous API image restored, and public API health
returned HTTP 200; the public Instant image selection stayed unchanged
throughout.

## Epic updater follow-up — 2026-09-28

The official Epic MSI was installed into three separate local prefixes using
the exact published Faugus canary image. First launch through direct UMU, direct
UMU with Faugus's extra environment, and the complete Faugus wrapper all kept
the client process alive for the bounded 150-second observation. In each case,
the updater service reached `SERVICE_RUNNING`; the service self-update
commandlet finished with exit code 0. The GPU-only `StartServiceFailed` result
therefore did not reproduce locally. This does not establish what failed on the
Paris VM or qualify its graphics/login path.

A separate canary image, `dpadplay-faugus-candidate:epic-updater-retry`, now has
a one-time recovery for exactly this updater failure. If Faugus exits within
30 seconds and an updater log written during that launch reports code 8
`StartServiceFailed`, the wrapper waits eight seconds and launches once more.
A second occurrence exits with an explicit error. Normal exits and old logs do
not trigger a retry. Focused log-detection tests and wrapper fault injection
passed, including the two-failure limit. The owner approved publishing only
this separate canary tag at
`forcespt/dpadcloud-gaming@sha256:67e89b9ee19cdfe862015186ad4471fb99b09a8502468d9e3af8772b3622fb6f`
from source revision `83c8a1dec18c3c332c79f5b13704fa9af794ee79`. No provider binding
or public image was changed. A new bounded GPU run is required to learn whether
the retry resolves the VM-specific failure.

## Epic updater retry GPU canary — 2026-09-28

One separately approved Paris L4 admin test launched session
`677cb50a-3017-4397-8d1d-adc282f14887` with the exact updater-retry digest
`sha256:67e89b9ee19cdfe862015186ad4471fb99b09a8502468d9e3af8772b3622fb6f`.
The session reached ready at 01:59:08 UTC; the embedded Selkies player rendered
the DpadPlay store picker. The owner opened Epic, completed the official MSI,
and the launcher downloaded its update. It then closed instead of showing
sign-in. A second owner-triggered launch also closed. Updater logs from both
launches repeatedly reported code 8 `StartServiceFailed`, with the service
reaching `SERVICE_START_PENDING` but not `SERVICE_RUNNING`. The wrapper's
short-exit retry did not trigger during the longer first update, and the second
manual launch shows that another attempt alone did not resolve the failure.

This canary does not qualify official Epic login, ABZÛ installation or gameplay.
Keep Heroic as the public Instant Epic route; the Faugus image remains an
admin-only candidate. Investigate why Epic's updater service cannot reach the
running state on the GPU VM before another billed test. The session ended at
02:08:47 UTC after 579 billed GPU seconds; billing finalized at 02:08:50 UTC
with the $1.29 minimum. The exact native VM was
`4b7754ef-6a22-4527-ba78-0cc18a06012a` and its attached SBS volume was
`3e92c27f-0d6e-4321-93cc-b1a225feeabd`. The scheduler destroyed the VM
after the normal drain grace; direct Scaleway GETs for both the server and SBS
volume returned 404 at 02:20 UTC. The bounded fallback teardown timer was then
disabled. The scoped API selector was rolled back to its prior image with a
persistent Compose rollback overlay, its rollback timer was disabled, and
public API health returned OK.

## Epic updater service diagnostic — 2026-09-28

One separately approved Paris L4 admin test launched session
`ebede43f-e181-4703-8745-c1499826b67e` on the retry canary. The official
Epic installer completed, but the updater again reported service state
`SERVICE_START_PENDING` followed by code 8 `StartServiceFailed`. A verified
GE-Proton10-34 release (SHA512
`9fd0b2cfbd501c0b5c892239c392c7283a029b5e5d5a77d3f85b0ce190d555456241a18eebca16b53f094b403499201c13550a3f0b9b365e1a5eb5737cbb7303`)
alone reproduced the same failure on this VM.

An opt-in Wine service trace identified the cause on this VM: DXVK could not
create a Vulkan instance (`VK_ERROR_EXTENSION_NOT_PRESENT`) in Epic's updater
startup path, and `EpicGamesLauncher.exe` then raised an access violation.
The session user's normal Vulkan probe still saw the NVIDIA L4 and X11 surface
extensions, so the failure is narrower than a missing GPU device. Setting
`PROTON_USE_WINED3D=1` in the Epic-only Faugus wrapper bypassed the DXVK
failure and rendered the official Epic sign-in window. The owner tested
account login in the diagnostic stream. Epic briefly reported
`OnLoginComplete TRUE` and `SignedIn=1`, then returned to `SignedIn=0` and
presented sign-in again. The sanitized launcher log reported
`GenerateDpop failed to parse public key` and `EOS Auth Login failed error:
EOS_NotConfigured`. The EOS bootstrapper also reported
`CreateProcessAsUser failed: ErrorCode=0x6 (Invalid handle)`; a later attempt
said the EOS service initialized, but sign-in still looped. Switching the same
VM to its GE-Proton11-3 runner with WineD3D retained reproduced the loop.
This is a post-login failure, so another password attempt is not a fix.
Epic [documents a separate local Online Services prerequisite](https://www.epicgames.com/help/en-US/epic-games-store-c5719341124379/launcher-support-c5719357217435/epic-online-services-and-epic-games-launcher-14-2-0-update-a5720351763099)
for current launcher updates. The next local diagnostic should check whether
that component is installed and whether its service starts under Wine, then
test DPoP key creation without recording account tokens. The observed
`EOS_NotConfigured` line alone does not prove which prerequisite failed.
This setting may also affect games
started as children of Epic; game graphics and performance remain to be
measured before public Instant Play qualification.

Source revision `1c3ef28601ecc8732af966f7e4e719fde478ad34` packages that
observed combination in a separate candidate: GE-Proton10-34 for the Faugus
Epic record, `PROTON_USE_WINED3D=1` for its wrapper, and an explicit migration
from the earlier managed GE-Proton11-3 record without losing playtime. Nine
Linux preparation tests pass. A disposable container smoke test confirms the
new image's actual Faugus dispatch, pinned UMU runner and private-volume
wrapper path. The local image ID is
`sha256:b6fa168ca28eea0aed0c74d3943a5473e864b4e37cdc4ee7e3df3a051b09621e`.
After the owner authorized the exact payload and destination, this separate
canary was published as
`forcespt/dpadcloud-gaming:faugus-epic-wined3d-canary-20260928-1c3ef28`
at digest `sha256:b6fa168ca28eea0aed0c74d3943a5473e864b4e37cdc4ee7e3df3a051b09621e`.
It was not selected as the public Instant Play image. The successful container
smoke does not qualify official Epic login, library access, ABZÛ, or gameplay.

The guest Xwayland keyboard started with US layout. Switching it to `pt`
fixed `@` for the owner's Portuguese (Portugal) keyboard, but the Selkies
path still mapped Shift+0 to `>` instead of `=`. On-screen keyboard clicks
stole focus from Epic, so the diagnostic used a focused XTest insertion for
two requested `=` characters. Keyboard mapping needs a separate product fix.

The session ended at 03:22:01 UTC after 2,405 billed GPU seconds; billing
finalized at 03:22:05 UTC. The scheduled cleanup destroyed native Scaleway VM
`e3949fec-48c3-417b-a97b-c06d646ecb1c` and SBS volume
`dfa71d3b-f0b7-40ce-b66b-2a65b257e8bf`; both direct provider GETs returned
404 at 03:33 UTC, before the one-hour deadline. The admin-only API image
selector was rolled back to its previous image, its test image ref is empty,
and public API health returned HTTP 200. Both bounded fallback timers were
disabled after cleanup. Heroic remains the public Instant Epic route.
