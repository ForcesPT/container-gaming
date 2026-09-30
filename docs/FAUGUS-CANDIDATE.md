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

## Prerequisite candidate (failed on GPU VM) — 2026-09-28

The managed Faugus Epic record passed `-SkipBuildPatchPrereq`, while Faugus's
own Epic record leaves the game arguments empty. [Epic describes that flag](https://www.epicgames.com/help/c-32735058/c-37477814/a19481967?lang=en-US)
as a workaround for failed prerequisite installation, and [separately states](https://www.epicgames.com/help/en-US/epic-games-store-c5719341124379/launcher-support-c5719357217435/epic-online-services-and-epic-games-launcher-14-2-0-update-a5720351763099)
that the current launcher requires a local Online Services component. Removing the
flag may allow that component to install during the normal launcher flow;
the current logs do not establish that the flag caused this login loop.
That candidate cleared the flag from both new and existing managed records
while retaining their private prefix and playtime. A bounded GPU test was
required before any claim about signed-in library access or gameplay.
Ten Linux preparation tests pass, including migration of an existing managed
record away from the skip flag. A local network-isolated diagnostic image was
built from the published WineD3D canary using `Dockerfile.faugus-prereqs`;
its image ID is
`sha256:4fe701debcd9ac311155b59257e52224aa23da9294a310d7c6adc1e83190920f`.
The packaged preparation script hash matches the tested source
(`sha256:de9b77b0b2bd7f2eaa8dfe1797713ac4c3a6338fbfed7f6c4c48fd0d4afdafe4`).
At that point no registry push or VM test had been done for this revision.

The owner then approved publication of this exact image to
`forcespt/dpadcloud-gaming:faugus-epic-prereqs-canary-20260928-5171244`;
Docker Hub reported the same `sha256:4fe701de…90920f` digest. The ordinary
customer `Play game` route was mistakenly used for the first bounded VM after
that publication. Its live slot inspection showed the public Heroic image
`sha256:59c8efe…37d20`, so it provided no evidence about the prerequisite
candidate. The session was ended after 200 billed GPU seconds (the $1.29
minimum). The admin test image selector applies only to the admin **Test game**
flow; it is intentionally ignored by the ordinary customer launch route.
Future Faugus tests must enter through ABZÛ’s **Test game** in Instant Play
administration, then verify the live slot digest before asking the owner to
sign in.
The mistaken session ended at 03:53:54 UTC. Its native Scaleway VM
`c5106eb7-4614-4c66-87f6-a46c6aec035e` and SBS volume
`d9ea1d32-93d2-441d-8cd8-970d5b1e54d4` both returned 404 at 04:05 UTC.
The first scoped API selector was restored, its fallback timers disabled, and
public API health returned HTTP 200 before the corrected admin-only selector
was staged.

## Prerequisite canary result — 2026-09-28

The corrected admin **Test game** route launched one Paris L4 VM for session
`0ffd18c2-3fe3-42ca-b2f1-add676b43e47`. A bound worker inspection proved
slot `dpad-slot-0` ran the intended Faugus prerequisite image at digest
`sha256:4fe701debcd9ac311155b59257e52224aa23da9294a310d7c6adc1e83190920f`.
The embedded Selkies stream connected and showed the DpadPlay store picker.
The official Epic MSI and update ran, but the launcher returned to the picker
before sign-in. A second launch again logged updater code 8
`StartServiceFailed`: the service reached `SERVICE_START_PENDING`, briefly
reported `SERVICE_RUNNING` in some attempts, then stopped. This disproves the
prerequisite-skip removal as a fix for this VM.

For diagnosis only, the VM's preparation script was changed back to
`-SkipBuildPatchPrereq` with a pinned source hash check. Epic's update service
then reported success, but its client remained in an indeterminate
"Installing Updates" window. Epic's bundled `EpicOnlineServicesInstaller.exe`
was run in the same private Wine prefix; its MSI and setup logs reported
success and installed `EpicOnlineServicesHost.exe`. A subsequent launcher
attempt still failed to reach sign-in. The first failed update could have
damaged that prefix, so the test preserved it under a diagnostic backup path,
prepared a fresh prefix, installed the same verified Epic MSI, and repeated
the launch with `-SkipBuildPatchPrereq` from the beginning. The updater briefly
showed "Completed Update" then returned to the picker with code 8 again.
Installing the bundled Online Services component in the fresh prefix did not
resolve the updater failure. No account sign-in or game launch was attempted
in this VM.

The session was ended at 04:41:41 UTC with 1,799 billed GPU seconds and the
$1.29 minimum charge. Its native VM is
`16cc1dda-7acc-4d34-8830-a60a423c4fc8` and SBS volume
`dea90aac-4372-4cff-b067-054df11a33cc`; direct Scaleway GETs for both
returned 404 at 04:53 UTC, and the VM database record became `destroyed`.
The admin-only API selector was restored to the prior image, its test image
reference is empty, public API health returned HTTP 200, and both fallback
timers were disabled. The public Heroic image remained unchanged. The candidate
source restores `-SkipBuildPatchPrereq` because removing it regressed the
updater. Do not select the published prerequisite canary for another VM test.
Further work should isolate the updater service child process and
Wine graphics/registry behavior before another billed test. An EOS install
success alone does not qualify Epic login, library access, or ABZÛ gameplay.

## Epic process handoff and keyboard selector candidate — 2026-09-28

Pinned Faugus 2.4.2 source review found an Epic process-lifecycle risk:
`runner.py` invokes `kill_by_faugusid(gameid)` and kills the UMU process group
immediately when the watched parent exits. Epic's updater and client can restart
as Windows child processes while that parent exits. The normal Faugus cleanup
can therefore terminate a still-running updater or newly relaunched client.
This is a concrete mechanism for the return to the store picker; it is **not
yet proof** that it caused the observed post-login `SignedIn=1` to `SignedIn=0`
transition. The earlier `GenerateDpop failed to parse public key` log still
needs a fresh, sanitized trace after the process handoff is protected.

The new exact-source adapter changes Faugus only for the managed `dpad-epic`
entry. After its UMU parent exits, it watches marked Epic launcher/updater
processes and waits for a continuous 20-second quiet period before Faugus's
usual cleanup. Other Faugus entries retain upstream behavior. Local tests
cover an updater/client handoff, unrelated processes, a real marked Linux
process, and patching the pinned 2.4.2 source. A disposable container test of
the built image passed one stub install and two launches against one private
prefix. This has no account or GPU acceptance yet.

Labwc's bottom Waybar now has a keyboard button that opens a searchable layout
selector. It reads installed XKB layouts, displays clear country names such as
Portuguese (Portugal), stores the user's choice in a private file, and asks
Labwc to reconfigure the Wayland seat. The published Labwc `environment`
symlink points to that file. A failed reconfigure restores the previous layout.
The popup opened under Xvfb, local selector tests passed, and a headless Labwc
instance accepted a live switch to `pt`. Sway remains the public default and
has no bottom Waybar; the browser-to-guest symbol mapping and actual in-game
typing still require a GPU/browser check.

This candidate is local only. It has not been published, selected for admin
testing, or tested with an Epic account. A new bounded admin **Test game** VM
should verify the exact image digest, Epic updater handoff, one owner sign-in,
library persistence after closing/reopening Epic, Portuguese `@` and `=` input,
and then ABZÛ before any promotion. Preserve Heroic as the public route.

## Handoff/keyboard canary publication — 2026-09-28

The paragraph above records the pre-publication state. Source revision
`c277a8323d344ea3d89a2eb7dc94f947d649a93d` was subsequently published,
with the owner's approval, only as the separate Docker Hub canary
`forcespt/dpadcloud-gaming:faugus-handoff-keyboard-canary-20260928-c277a83`.
Docker Hub independently reported immutable index digest
`sha256:0dc089aa168d8ffabecd1367a84d7c18c27dcc228b6cf5d8c324f3a526431b00`,
matching the local image ID. This does not promote the image to customers.

The previously verified admin-test API artifact
`sha256:9a756e190ccb8d8e031c41fa3d0dfc52a7dc3827e1efff9c25e1ce4116d91ba8`
is temporarily selected on the production API with
`INSTANT_PLAY_TEST_IMAGE_REF` set to the exact digest above and deadline
`2026-09-28T19:00:00Z`. An active systemd timer restores API baseline
`sha256:1d107049e195522665afb1f9a018a763934ec3048eb29165e4ac750c606a96e6`
at that deadline. The public image remains the accepted Heroic digest
`sha256:59c8efe85c30224c5e9e878c577b78d3b9563cdecf0763665eb297a50d837d20`;
the live API health check passed after the scoped cutover.

At this checkpoint, **no GPU VM has been launched**. The browser admin flow
requires the owner to sign in. A verified one-session teardown guard is staged
but is armed only after an exact admin Test game session is created. The owner
approved at most one Paris L4 VM, an $8 infrastructure cap, and teardown within
one hour; the test must verify the slot's exact digest before Epic sign-in.

The owner was away from the computer, so the admin selector was rolled back
before any test submission. The API returned to baseline
`sha256:1d107049e195522665afb1f9a018a763934ec3048eb29165e4ac750c606a96e6`,
its test image reference is empty, the public Heroic reference is unchanged,
and the timer was disabled. The first immediate public health request during
the API restart returned 502; a subsequent request returned HTTP 200 with
`{"status":"ok"}`. The published canary remains available for a later
explicitly bounded test. No GPU VM was created or billed in this attempt.

With no account input, a separate disposable-container integration smoke used
the **actual patched Faugus runner** and a stub UMU that spawned a marked
`EpicGamesLaunc` child before its parent exited. The child completed its
five-second work; Faugus logged the handoff and finalized after a quiet period,
and the wrapper returned successfully after 30 seconds. This is stronger than
the helper unit test because it exercises Faugus's real process-exit callback.
The same smoke was repeated in a disposable container with upstream 2.4.2's
unpatched `runner.py`: the marked child started but was terminated before it
could finish. This negative control confirms that the smoke distinguishes the
specific premature-cleanup behavior the adapter changes.
It does not authenticate to Epic or establish the cause of the previous
post-login `SignedIn=1` to `SignedIn=0` transition.

## Handoff/keyboard GPU canary — 2026-09-28

One bounded Paris L4 admin **Test game** session ran image
`forcespt/dpadcloud-gaming@sha256:0dc089aa168d8ffabecd1367a84d7c18c27dcc228b6cf5d8c324f3a526431b00`;
`docker inspect` on the assigned slot confirmed that exact image. The embedded
Selkies stream connected and showed the store picker. The owner used the new
taskbar selector to change from US to Portuguese (Portugal); the taskbar showed
`PT`. This verifies the selector's visible result, not every key mapping in an
Epic input field. An initial Steam window was caused by selecting the Steam
card; it was closed before the Epic checks.

Epic's official MSI opened and installed. Each subsequent launch returned to
the picker before sign-in. The updater service log showed the
`selfupdateinstall` child exiting with code `777006`, followed by the service
stopping; its controller reported code 8, `StartServiceFailed`. The launcher
log reported a successful download/install but no current
`C:\ProgramData\Epic\EpicGamesLauncher\Data\Launcher.manifest`; only the staged
`LauncherUpdate.manifest` existed. The service also logged a missing
`HKLM\SOFTWARE\WOW6432Node\EpicGames\Epic Games Updater` key, then constructed
the launcher path as a fallback. These are observed signals, not yet proof of
the root cause.

For a runner comparison on this disposable VM only, both the wrapper's
`PROTONPATH` and Faugus's saved `dpad-epic` runner selection were switched to
the already installed GE-Proton11-3, keeping WineD3D. The updater displayed
“Installing Updates” for several minutes without log progress and still did
not reach sign-in. After stopping that attempt, a copy of the officially
downloaded `LauncherUpdate.manifest` was placed at the missing current-manifest
path in the disposable prefix. The next launch returned to the picker with the
same `StartServiceFailed` result. This rules out the missing file alone as a
fix. None of these diagnostic edits changed the published image.

The owner never entered Epic credentials in this session. Login persistence,
library access, and ABZÛ launch therefore remain unverified. The session ended
at 20:22:56 UTC after 2,124 billed GPU seconds with the $1.29 minimum charge.
The API's private test selector was restored to baseline, and the public Heroic
image stayed unchanged. The VM entered the normal 10-minute idle drain period.
The scheduler then destroyed the VM, and exact Scaleway GETs for native VM
`799ba26b-0661-49b1-b3d9-6eaf2c53129e` and SBS volume
`c4c59f71-97dc-4ab8-b884-78fd0656adc6` both returned HTTP 404 at
20:34 UTC. The VM database record is `destroyed` with no cleanup error.

A later unpaid Docker Desktop attempt used the same canary image and its
official MSI under Xvfb, but UMU stopped before starting Wine because the
local Docker engine disallowed the user namespace required by pressure-vessel.
It supplied no evidence about Epic's updater and the disposable container was
removed.

The canary also exposed a retry-timing bug: the wrapper only checked for a
fresh `StartServiceFailed` log when Faugus exited within 30 seconds. Its new
process handoff can wait 20 seconds after Epic's updater exits, pushing an
otherwise short failure past that limit. A follow-up candidate increases the
exact-log check window to 120 seconds and shows a startup error in the picker
when the Faugus wrapper exits nonzero. A local stub test with a 31-second
first launch passed, along with the immediate-failure and normal-exit cases;
both edited JavaScript files passed `node --check`. This improves recovery and
feedback but does not establish that the official updater can complete.

## Updater crash diagnosis prepared — 2026-09-28

[Epic's Unreal Engine exit-code reference](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Core/ECrashExitCodes)
names `777006` `CrashDuringStaticInit`. The GPU updater's `selfupdateinstall`
child returned that number; this points to an early crash, but the available
service log has no stack and does not identify the failing library.

An unpaid Docker Desktop reproduction used the published handoff image with
the documented UMU container permissions, its bundled official Epic MSI, and
the managed Faugus entry. The MSI installed and the client ran for the bounded
150-second observation. Six local updater controller logs reported
`SERVICE_RUNNING` and exit code 0. They *also* reported the same missing
`HKLM\\SOFTWARE\\WOW6432Node\\EpicGames\\Epic Games Updater` key seen on the GPU
VM, then constructed the correct launcher path, so that registry message alone
cannot explain the GPU updater crash. The local GUI repeatedly failed with
`wined3d_caps_gl_ctx_create Failed to find a suitable pixel format` and an
access violation under Xvfb, which has no representative GPU OpenGL context.
It did not reach sign-in and does not qualify the VM graphics path. The
disposable container was removed; no cloud resource was created.

`Dockerfile.faugus-diagnostic` now derives from the immutable published
handoff image and replaces only the Epic wrapper plus its exact failure
detector. Its admin-only `DPAD_EPIC_DIAGNOSTICS=1` mode asks Faugus for
UMU/Proton logs in the private Faugus data root and captures Wine error and
SEH warning lines without the very large full trace. The regular wrapper path
does not enable logging. A focused fault test covers the opt-in arguments and
the prior one-retry behavior. The diagnostic image built locally from source
commit `9be5e843e212806e13f78b3066a888d6c0bc0d48` at image ID
`sha256:bba1dbff12fc7ab610216badf3476e8f996361b841f528194970223fc25fe33b`.
The packaged shell and Python syntax checks passed in a network-isolated
container; the focused delayed-failure, two-failure, normal-exit, and
diagnostic-mode test passed. At this preparation point, the image had not
yet been published or selected for any provider. The subsequent GPU test
is recorded below.

## Updater trace GPU test and flag-forwarding fix — 2026-09-28

The diagnostic image above was published separately at immutable digest
`sha256:bba1dbff12fc7ab610216badf3476e8f996361b841f528194970223fc25fe33b`
and selected only for ABZÛ's private admin test. Session
`baf15266-1822-486f-a94d-580b732bb7a2` ran one Scaleway Paris L4 VM at
that exact digest; the public Heroic image stayed at its accepted digest.
The official Epic installer and updater initially returned to the store
picker. Several updater service attempts started the
`-Commandlet=selfupdateinstall` child, which exited `777006` within roughly
0.2 seconds; the controller then reported code 8 `StartServiceFailed`.
The previously suspected missing registry key also appeared, but the service
constructed the correct launcher path, and the local successful run had the
same key message. A later launch in this same VM reached the official Epic
sign-in screen. No account credentials were entered, so login persistence,
library access, and ABZÛ remain unverified. The session ended at 21:33:04 UTC
after 790 billed GPU seconds; the VM entered its normal drain cleanup. The
admin-only API selector was restored to the prior image and live health
returned HTTP 200. The VM became `destroyed` in the DpadPlay database, and
direct Scaleway GETs for server `b995ea8c-f11a-4180-89e4-bc3970310074`
and boot volume `4da4f1b8-dd06-4198-8fb7-9c331a619cff` both returned 404.
The completed fallback timers were disabled.

The opt-in `--logs` did **not** reach Faugus. The pinned upstream
`faugus-launcher` shell entry has a `--game` case that forwards only `$2` to
`faugus.runner`, discarding our third `--logs` argument. The live process
confirmed `python3 -m faugus.runner --game dpad-epic` with no `--logs`, and
no Proton/UMU trace files existed. The separate diagnostic Dockerfile now
applies an exact-source, fail-closed patch to forward remaining `--game`
arguments. A new local image built successfully; a real container invocation
with an unknown probe flag was rejected by `runner.py`, proving the flag
reached the runner, and `--game nonexistent --logs` was accepted. This local
fix has not been published or selected for a provider. The next GPU test
should collect the actual pre-login trace and then, with separate owner
authorization, test account sign-in persistence.

## Flag-forwarding GPU test — 2026-09-28/29

The exact-source `--logs` forwarding patch was published as the separate
admin-only image `forcespt/dpadcloud-gaming@sha256:197c62900eb7d7e3d8ba184a596e4194c45a723a4d0c8f7c816748066b2c4894`.
An approved Paris L4 **Test game** session
`fd8a349e-e36d-4bf5-abeb-69672850f8e1` ran that exact digest; the public
Heroic image remained unchanged. A transient NFS readiness failure prevented
the first attempt from reaching a stream, with zero billed GPU seconds. The
worker's bounded NFS mount retry was then released independently. This second
VM completed host preparation in 11 seconds and reached a connected Selkies
stream.

The official Epic MSI installed and its update reached the native Epic sign-in
window. Process inspection proved Faugus actually ran
`python3 -m faugus.runner --game dpad-epic --logs`; it produced `umu.log` and a
Proton trace. The updater service still logged `selfupdateinstall` exit
`777006` at 23:14:56 UTC, yet the client subsequently rendered sign-in. The
account owner advanced through password sign-in to Epic's authenticator prompt.
The Windows Epic client then restarted repeatedly under the same long-running
Faugus/UMU parent; a later client PID was only seconds old while its parent
was more than seven minutes old. The Proton trace repeatedly showed
`0xc0000005` access violations at a null address. This is a stronger signal
for a client crash/restart loop than a Faugus parent handoff, but the captured
trace does not identify the crashing module or prove a root cause. Signed-in
library access and ABZÛ were **not** verified.

The opt-in `WINEDEBUG=-all,err+all,warn+seh` setting generated 1.77 GB of Proton
trace before teardown; future diagnostics must avoid this unbounded SEH output.
This Instant Play admin session used ephemeral storage: `DPAD_VOLUME_MOUNT` and
`DPAD_FAUGUS_STATE_ROOT` were absent, and the Epic prefix was on the
container's overlay filesystem. Even if same-VM sign-in succeeded, credentials
could not persist across a new VM session under this storage profile. This
needs a per-user private state design before promising cross-session login
persistence.

The session ended early at 23:25:40 UTC after 936 billed GPU seconds, with
billing finalized at 23:25:46 UTC. The VM entered normal drain cleanup,
briefly showed `error`, and the scheduler's cleanup retry marked it
`destroyed`. Direct Scaleway GETs for server
`954ab4af-edf3-4265-a3f7-3e212f196345` and boot volume
`30c04e32-faef-47c4-a25d-f58f160acc37` both returned 404. The admin-only
API selector was restored to its prior image and live health returned HTTP
200; both completed fallback timers were disabled. No GPU resource from this
test remains.

The next diagnostic should isolate the launcher executable choice and capture
bounded, sanitized client errors around the first authenticated restart. A
fresh owner-approved GPU test is required to establish whether Epic reaches a
stable signed-in library. This test does not justify promoting Faugus to the
public Instant Play route.

## Win32 executable hypothesis ruled out locally — 2026-09-29

[UMU's own Epic launch example](https://github.com/Open-Wine-Components/umu-launcher#how-do-i-use-it)
uses `Binaries/Win32/EpicGamesLauncher.exe`, while the DpadPlay Faugus record
uses `Binaries/Win64/EpicGamesLauncher.exe`. A disposable local install of the
exact bundled official Epic MSI under UMU/GE-Proton10-34 completed with status
0, but its prefix contained only the Win64 executable. The proposed Win32
candidate was removed before publication or a billed GPU test. A newer Epic
installer would need its own executable inventory check before revisiting that
idea.

The reproducible next diagnostic image is defined by
`Dockerfile.faugus-epic-postauth`. It derives from the exact tested
flag-forwarding digest and changes only the Epic wrapper's default Wine debug
channels from `-all,err+all,warn+seh` to `-all,err+all`. It remains admin-only
and does not claim to fix the launcher crash. A local build from source
`6fcee8d` produced image ID
`sha256:62462253608d1caeb84fc2f66382900c1e7c0407fa0491d15e198e616907e93b`;
the packaged script passed `bash -n` and the image's diagnostic mode and Wine
channel check passed.

## Post-verification Epic restart — 2026-09-29

The exact diagnostic image above was published as the separate Docker Hub
digest `sha256:62462253608d1caeb84fc2f66382900c1e7c0407fa0491d15e198e616907e93b`
and selected only for an approved ABZÛ admin **Test game** session
`90653013-afb9-4b9a-91de-113eaba0eeec` on one Paris L4 VM. The running
slot's `docker inspect` image matched that digest. The public Heroic route
remained unchanged.

The official Epic MSI installed and updated, with several early returns to the
store picker. The updater service logged `StartServiceFailed` (`code 8`), yet a
later launch reached the native Epic sign-in window. That pre-login window
stayed open for over two minutes with the same Windows client PID. The account
owner completed password entry and reached the verification prompt. After
verification, Epic restarted repeatedly while Faugus/UMU stayed alive.

Epic's own logs gave a more specific auth failure than the earlier large Proton
trace: `LogDPoP: Failed to create persistent DPoP key (Status: 0x80090029)`,
followed by `no public JWK available`, `GenerateDpop failed to parse public
key`, and `EOS_NotConfigured`. The launcher logged `SignedIn=1` briefly and
then `SignedIn=0` across successive client restarts. This strongly implicates
the DPoP key failure in the login loop; it does not prove that every process
restart has the same cause. The bounded Proton trace stayed below 200 KB and
showed no new `0xc0000005` line in the inspected tail; a separate Xalia
accessibility exception was present, with no established causal link to Epic.

[Microsoft's error table](https://learn.microsoft.com/windows/win32/com/com-error-codes-4)
defines `0x80090029` as `NTE_NOT_SUPPORTED`. Current upstream
[Wine `ncrypt` source](https://github.com/wine-mirror/wine/blob/master/dlls/ncrypt/main.c)
still marks named persistent keys unsupported, and `NCryptOpenKey` returns
`NTE_NOT_SUPPORTED`. This makes a Wine/Proton CNG compatibility gap the leading
explanation, but the exact Epic algorithm and failing CNG call have not yet
been traced. Swapping Faugus UI or storage mounts alone cannot establish
working DPoP authentication. An implementation must preserve Epic's DPoP
security semantics; disabling proofs is not a valid product fix.

The session ended at 00:17:13 UTC after 829 billed GPU seconds, and billing
finalized at 00:17:16 UTC. The API-only selector was restored to the prior
image, both private selector variables were empty, and live health was HTTP
200. The DB VM reached `destroyed`; Scaleway returned 404 for exact server
`70c36e17-6392-46f5-ba3f-a5f2ac35a490` and boot volume
`772dd2b7-3322-4a20-bcfe-c2fd01c8d1f9`. The completed session teardown
fallback timer was disabled. No VM or volume from this test remains.

## Official Epic persistence research — 2026-09-29

The requirement is Epic's official Windows store client, launched by Faugus;
Heroic/Legendary is not an acceptable substitute for this candidate. Epic's
[published requirements](https://www.epicgames.com/help/c-202300000001619/a202300000014568)
list Windows and macOS, not Linux. Faugus
[re-added the official Epic launcher](https://github.com/Faugus/faugus-launcher/releases)
with Proton support in its July 2026 release, but that does not qualify this
specific GE-Proton runtime or DpadPlay's session lifecycle.

[Soju's published Wine patch](https://github.com/BCD1210/soju/blob/main/patches/ncrypt-persisted-keys.patch)
documents the *same* Epic `Failed to create persistent DPoP key (Status:
0x80090029)` and missing public JWK markers. It implements named CNG key
persistence and ECDSA P-256/P-384 support in `ncrypt`, and Soju reports official
Epic login and game installation on macOS. This is an exact diagnostic lead,
not Linux validation. The GE-Proton10-34 tag `GE-Proton10-34` pins Valve Wine
source `1729f00e17e879f98f9df1f2bca86bc5d21a65df`; `git apply --check`
against that revision's `dlls/ncrypt/main.c` and `ncrypt_internal.h` passed
without modification.

The patch stores private keys in the Wine prefix under
`%APPDATA%\Microsoft\Crypto\Keys`. Any canary must ensure this path is
private to one user, never stored in the shared game master, and survives a
launcher restart. A separate durable per-user volume is needed for login
persistence across different VMs; the tested Instant Play session used
ephemeral client state. Before promotion, verify official Epic sign-in and
restart on one VM, then persistence across VMs with a private volume. Keep
the patch source and licensing notices with any distributed image. The public
Heroic route remains unchanged.

## Pinned DPoP canary — local validation, 2026-09-29

`Dockerfile.faugus-epic-dpop` now builds only the 64 bit `ncrypt.dll` from
GE-Proton10-34's pinned Valve Wine revision and applies Soju revision
`f482f2b607e3374163e8a5e47a75f422b3d332b6`'s patch after verifying
SHA-256 `6283b3637b1d98bf43f68618c0991ee23e719c8bddaed05eff05e3989c954efe`.
It replaces that DLL in the exact prior admin diagnostic image, and copies a
launcher with `umask 077` and a preparation check requiring the Epic prefix to
be mode 0700. A local packaging proof image is
`sha256:ddfd865e6ad4ec4bc10de2279e8426b391868718516ce71703c63c34e0e2d503`;
it includes the modified source, patch, and Wine and Soju license notices.
It has not been published or selected for production.

The account-free `scripts/ncrypt_persistence_probe.c` was compiled for Windows
and run with the bundled GE-Proton Wine in a disposable container. The patched
runner created a named ECDSA P-256 key, exported its public blob, signed data,
then a separate Wine process reopened the key, exported the identical public
blob, and signed again. The baseline image failed at key creation with the
same `0x80090029` seen in Epic's log. With the new launcher file mask, the key
file was mode 0600 under the private prefix. All 11 focused preparation tests
passed. The local container had no preinstalled UMU sniper runtime, so this
probe used the bundled Wine executable directly; the Faugus/UMU and official
Epic paths still require a bounded GPU canary.

At this local-only validation stage, official Epic login, a stable library
after restart, ABZÛ gameplay, and login persistence across separate VMs were
unverified. The last item needs durable per-user state rather than the current
ephemeral Instant Play client volume. The later GPU result follows.

## Official Epic authenticated storefront canary — 2026-09-29

The DPoP canary was published at immutable digest
`sha256:43f8459d1b56f2922deb011271688e04b73f12ef23142ac60fff049f32fb0eb3`
and selected for one private Paris L4 admin session
`560f185f-d92d-43ed-83a2-1d51b81ceae7`. The running slot matched the
digest. The owner signed in inside the official Epic client. The patched
`ncrypt.dll` created one private, persistent key file in the Wine prefix;
the inspected logs had zero DPoP key creation, missing JWK, or parse failures
and reported `SignedIn=1`.

The launcher nevertheless restarted about every nine seconds with the
WineD3D/OpenGL fallback. Epic logged graphics-device loss before requesting
each restart; the Proton trace repeatedly failed to create an OpenGL context.
The L4's host Vulkan and OpenGL probes passed. A test-only `-noselfupdate`
option did not stop the cycle. On this same VM, removing
`PROTON_USE_WINED3D=1` and pinning
`VK_ICD_FILENAMES=/etc/vulkan/icd.d/nvidia_icd.json` switched the client to
DXVK/Vulkan. The official signed-in Epic storefront rendered and stayed open
for several minutes, beyond the prior nine-second restart cycle. The source
wrapper now makes this graphics change locally, preserving an explicitly
configured Vulkan ICD and falling back to the NVIDIA ICD used by this canary.
`Dockerfile.faugus-epic-dxvk` layers that wrapper on the exact tested DPoP
digest. The local image builds and the disposable updater-retry wrapper test
passes; no replacement image has been published or deployed.

Epic's Library and ABZÛ were not verified. The owner reported that left click
and other controls in the Epic window did not respond. Browser automated
clicks also failed to activate the Library, so the stream input path needs a
focused check before another billed canary. Compare the browser pointer over a
known Epic target against XWayland root coordinates, then record X11 button
press/release on that window. If coordinates are correct, compare one guarded
XTest click with the browser click to isolate the compositor/CEF route. Do not
change global Selkies input based only on this one observation. A deliberate
Epic close/reopen,
game launch, and login persistence across VMs remain open. In particular, the
DPoP key is private inside this ephemeral VM; a durable per-user client state
volume is still needed for cross-VM sign-in persistence.

The session ended at 03:10:31 UTC after 2,596 billed GPU seconds; billing
finalized at 03:10:36 UTC. The scheduler destroyed the exact VM, and Scaleway
returned 404 for server `817dcbe3-2adf-407b-b99d-62e64a1f719b` and boot
volume `e582e74b-e45b-40a9-a799-d2e641b834eb`. The API-only test selector
was restored to its baseline image with both selector values empty and health
HTTP 200. Both completed fallback timers were disabled. The public Heroic
route remained unchanged.

## Official Epic DXVK follow-up canary — 2026-09-29

Commit `d9f1777` built and published the admin-only DXVK image at immutable
digest `sha256:a38b41e2d2549abcd65c2634f4dd10ff8178563540d0e0752af78a4739420352`.
The locally built image passed the disposable updater-retry wrapper check. One
approved Paris L4 admin session `bd6b48b4-8f12-45da-b98c-bbd2c8fac899`
reached `ready` at 03:36:33 UTC with that exact image pinned in the running
slot. The public Heroic image was not changed.

This test did **not** reach the Epic installer or sign-in. Both the embedded
and direct Selkies players stayed at `Waiting for stream.` Browser status
recorded an incoming video track and input data channel. Its displayed media
statistics remained zero, but later source inspection showed that the stats
loop does not start until both video and audio peers connect. Those zeroes
therefore do not establish that video RTP packets or frames were absent.
Relay-only mode failed to connect. The guest had a healthy slot,
Labwc/XWayland and launcher processes, Wayland sockets, a started GStreamer
video pipeline, and nonzero NVIDIA encoder utilization. Coturn listened on
UDP/TCP 3478 with relay allocations in the configured 40000–40063 range;
the attached Scaleway security group had inbound default `accept`. These
checks narrow the fault to media delivery or browser playback, but do not
identify the failing hop.

A test-only TCP TURN entry was added inside this VM; the player still advertised
the UDP route and did not start playback. I then sent SIGTERM to the Selkies
process to test supervisor recovery. The process was still present afterward,
but the gateway began reporting socket hang-ups and the direct page returned
`ERR_INVALID_RESPONSE`. Worker certificate renewal repeatedly recorded
`probe_websocket` / `connection_reset` and ended the session at 03:53:12 UTC.
Its bounded evidence showed a running container with no OOM, the signaling
socket and service present, and only `python_traceback` and
`websocket_handler_error` log signatures. The termination signal may have
caused that later failure; it cannot explain the original waiting state,
which preceded it. Do not treat this result as DXVK or Epic qualification,
and do not send signals to Selkies during a billed media probe without a
recovery plan.

Billing finalized after 1,000 GPU seconds. The exact DB VM reached
`destroyed`, and Scaleway returned 404 for server
`ffb451e1-b71f-4e6d-ac96-69bb32c2c770` and boot volume
`94b53ec5-9f74-476f-922a-675bd9bc38d7`. The API returned to baseline
`sha256:1d107049e195522665afb1f9a018a763934ec3048eb29165e4ac750c606a96e6`;
both private image selector values were empty, health returned HTTP 200, and
the completed fallback timers were disabled. No resource from this test remains.

Before another billed Epic attempt, capture a browser WebRTC selected
candidate pair, inbound RTP bytes/frames, and a bounded server RTP counter
while the player is in the original waiting state. Establish actual video
first, then test the pinned DXVK image and Epic pointer coordinates on the
same session.

## Video-first Selkies canary — local only, 2026-09-29

Source inspection after teardown found a specific browser gate. This Selkies
client runs separate WebRTC connections for video and audio. Its loading
overlay and START button depend on `app.status`, but the callbacks only set
that status to `connected` once **both** peers connect. The observed browser
logs had an incoming video track and input data channel, while audio only
waited for its peer. This is consistent with the overlay remaining visible;
it does not prove that video RTP frames arrived. The existing diagnostics also
wait for both peers, which explains why their displayed zero counters were not
valid evidence of zero video traffic.

`Dockerfile.faugus-epic-video-first` pins the exact published DXVK canary and
patches only the private Selkies web client. Video connection now reveals the
player and START button even when audio is pending or reconnecting. The drawer
shows separate peer states and samples video RTP bytes, packets, candidate type,
and decoded frames without waiting for audio. Loss of video still restores the
connection overlay. The script checks exact source snippets and refuses an
unknown Selkies version. The local image built successfully; its bundled
JavaScript passed `node --check`, and a runtime state-transition test passed
the video-only, audio reset, audio reconnect, and video loss cases. This is a
diagnostic canary, not an audio transport or Epic login qualification.

The image has not been published or run on a GPU VM. The previous paid VM is
gone, so a new capped test needs separate authorization. During that test,
record these video-only counters before attempting Epic; if RTP packets or
decoded frames remain zero, inspect server RTP and the selected candidate
pair rather than treating the overlay fix as proof of playback. A prior project
note documents a separate stale audio-peer UID failure on reconnect; there is
no evidence yet that it occurred in this specific test.

## Video-first GPU canary — 2026-09-29

The owner approved one Paris L4 admin test on the published private image
`sha256:8bd0f99256c7ecb6dd6d9305ef577185950049eb3ec242a10029bb09cdf98d49`.
Session `57c63757-9612-4f3d-b85c-27df6be3fc4f` reached ready at 04:27:57 UTC
with the exact image in its running slot. The embedded Selkies player rendered
the picker while audio was still connecting. Both peers subsequently connected;
the browser reported a host candidate, more than 9 MB of video RTP, more than
9,000 video packets, and over 2,400 decoded frames. This resolves the earlier
`Waiting for stream` overlay symptom for this canary and proves actual video
delivery. It does not establish every audio reconnect path.

The owner launched official Epic from the picker. The first two launches showed
Epic self-update and returned to the picker. Epic's own updater log reported
`StartServiceFailed` (code 8). The third launch reached sign-in. The owner
signed in within Epic, opened Library using the mouse, and found ABZÛ in the
account. Epic offered Install: the official launcher has no installation record
for the shared game files. The taskbar keyboard indicator showed Portuguese
after the owner used its layout selector. No game installation or gameplay was
attempted.

Closing the Epic window left its process running without a visible window, so
the picker reported that Epic was still starting. After terminating only that
leftover Epic process, Faugus released its launch lock. The owner relaunched
Epic and it opened signed in, proving sign-in persistence across a launcher
restart within this one VM. The current admin test prefix was mode 0700 at
`/home/dpad/Faugus/epic-games`, with no `DPAD_VOLUME_MOUNT` or
`DPAD_FAUGUS_STATE_ROOT`; this does not prove persistence across separate VMs.

The session was ended at 04:45:49 UTC, 1,072 GPU seconds billed, well before
the one-hour deadline. The API-only image selector was restored to its baseline
`sha256:1d107049e195522665afb1f9a018a763934ec3048eb29165e4ac750c606a96e6`;
both private selector values were empty and public health returned HTTP 200.
After the scheduler's 10-minute drain grace, the DB VM reached `destroyed`.
Scaleway returned 404 for the exact server
`941fe1b9-b905-4aab-8d9c-bad916026007` and SBS boot volume
`07f0f1d9-13f7-4fcd-a7d0-d76b11d950ca`. Both completed fallback timers were
disabled. The public Instant Play image remained the Heroic digest
`sha256:59c8efe85c30224c5e9e878c577b78d3b9563cdecf0763665eb297a50d837d20`.

Next technical steps: prepare the official Epic client before exposing the
picker, bind its mutable prefix to private per-user storage, provide a clean
Quit action for tray/background processes, and register Epic's genuine install
metadata against an authorized game payload. A container image containing
Epic binaries raises separate distribution and commercial-use licensing
questions; review Epic's current Store EULA and obtain any required rights
before shipping a preinstalled public image.

## Official Epic startup and reopening — local candidate, 2026-09-29

The new `Dockerfile.faugus-epic-startup` layers onto the exact GPU-tested
video-first image `sha256:8bd0f992…98d49`. It retains the DPoP key patch,
DXVK/NVIDIA ICD default and video-first player. No installed prefix or user
account state is copied into an image. It is local only; no selector or public
deployment has changed and no paid VM was started.

Changes:

- `faugus-epic-launch --prepare-only` validates private Faugus state and silently
  installs the checksum-pinned official MSI with `/qn /norestart`, bounded to
  five minutes plus termination grace. A prepared prefix is reused without
  launching Epic or requesting an account. The ordinary store card performs
  the same preparation automatically if needed.
- The launcher retries **only** fresh updater `StartServiceFailed` code-8 errors
  from attempts shorter than two minutes, at most three launches. This covers
  the observed two failed updater rounds without requiring three card clicks.
  Normal exits, unrelated errors and stale logs do not cause reopening.
- Selecting a previously visible but now hidden managed Epic client sends
  `--resume`. The helper requires a held launch-owner lock and a live matching
  effective UID, private prefix, `FAUGUSID` and exact official executable.
  It invokes the same official executable through UMU with Faugus's runtime
  options; it does not start another Faugus controller or kill a client/game.
- The picker waits up to 30 seconds for a visible, focused Epic window.
  Concurrent selections share one restore operation. Timeout, focus failure
  and owner exit leave the picker available. From-scratch Faugus builds use
  the same wrapper and exact picker adapter.

Local verification:

- A fresh **real** MSI install via Faugus/UMU/GE-Proton/Xvfb passed in a
  disposable container without account sign-in. Prefix mode was 0700;
  repeat preparation reused the install. The offline attempt failed because
  UMU's Steam runtime was not initialized in the base. Allowing its initial
  runtime download passed. A provisioning caller therefore needs either a
  prepared runtime or network access for that first setup.
- Four process-guard cases, eleven private-state preparation cases, three
  updater-log cases, the retry/installation wrapper scenarios, packaged
  picker selectors/native module import, and reopen concurrency/timeout/focus
  policy passed. A real marked Linux test process also verifies exact restore
  dispatch and that the existing process remains alive while duplicate normal
  launch is refused. This uses a stub UMU command, not Epic's window behavior.

Remaining acceptance: one bounded GPU canary must verify unattended first
install, updater completion from one card selection, closing the signed-in
official window, and reopening it without manual process termination. The
`--prepare-only` command installs the MSI; it does **not** certify all Epic
self-updates before VM readiness. Provisioning integration, genuine shared
ABZÛ installation registration, gameplay and private cross-VM state remain
separate work. Existing Epic binary distribution/commercial-use rights review
still applies before public release.

## Startup GPU canary — 2026-09-29 (fully cleaned up)

The owner approved publishing `f6be930` only as
`forcespt/dpadcloud-gaming:faugus-epic-startup-canary-20260929-f6be930`,
then one Paris L4 admin VM capped at $8 and one hour. The published and live
slot digest was
`sha256:9140640cdfa19d343344362ae595bacbdea95f7b0e135e49e4a5d6d12c3d441c`.
Session `2d358d3f-18ea-41cb-bc14-65715315a1d0` launched at 22:58:32 UTC
and reached ready at 23:04:20 UTC. An absolute teardown timer was armed for
23:40 UTC; its idle deadline was bound to the same exact session. Public
Heroic stayed unchanged.

Results:

- The first card launch installed the pinned MSI unattended, with no installer
  clicks. Both media peers connected and real decoded video rendered.
- The ordinary DXVK path retried three times and exited code 1. A later normal
  launch repeated the same bounded result. Six updater controller logs reported
  code 8 `StartServiceFailed`; the service reached running but its
  `selfupdateinstall` child exited `777006`. The current Proton trace contained
  `wine_vkCreateInstance Failed to create instance, res=-7`.
- A same-VM diagnostic used Epic's documented `-noselfupdate` flag. It reached
  UMU but left an updater window and no stable client; it was stopped before
  sign-in and the flag was reverted. It is not a proposed production default.
- A test-only wrapper change enabled WineD3D for updating. The official update
  installer ran, and the owner completed account sign-in inside Epic. The
  owner then reported the same post-login restart loop. No credentials or
  verification codes were entered by the agent or copied into diagnostics.
- DXVK was atomically restored for future launches. Only the exact managed
  test client's process tree was terminated, with guards refusing an unknown
  Windows child; the observed `tabtip.exe` input helper was accounted for.
  Epic reopened directly into the signed-in library at about 23:33 UTC.
- The agent closed only the visible Epic window and selected its store card.
  Library reappeared signed in without another Faugus launch or process
  termination. The owner confirmed Store and Library navigation respond.
  This qualifies the observed close/card recovery; the separate no-window
  `--resume` second-instance branch was not positively identified in the trace.

The normal session destroy flow ended the session at 23:35:40 UTC, finalized
billing at 23:35:44 UTC, billed 1,880 GPU seconds, freed the slot, and marked
the VM draining. Production API was restored to
`sha256:1d107049e195522665afb1f9a018a763934ec3048eb29165e4ac750c606a96e6`,
both private test selector values were empty, and health returned 200. Its
completed rollback timer was disabled. After the normal drain grace, the DB VM
reached `destroyed`. Exact Scaleway server and boot-volume GETs both returned
404 at 23:46 UTC, within one hour of launch. The completed session teardown
timer was also disabled. Resource identities:

- DB VM: `3e4ca19f-b608-4291-89e0-49bc7e7e2159`
- Scaleway server: `97bed207-38f7-4649-a547-d0567be29ece`
- Boot volume: `75901854-a3ba-48f4-b2b8-bf35f6f3db98`

Local proof screenshots are under `test-results/epic-startup-*-20260929.png`;
they are untracked test artifacts, not image inputs. The signed-in library
proof is `epic-startup-signed-in-dxvk-20260929.png`.

Next: qualify an unattended update preparation path before exposing the picker,
while preserving DXVK for the signed-in client. The updater's graphics context
and Wine service environment need isolation; more identical retries do not
resolve the observed Vulkan error. Genuine Epic installation metadata for the
shared ABZÛ payload, game launch, and private cross-VM state remain open.
The original published startup digest still requires manual graphics-phase
changes and is not ready for public promotion.

## Automatic update preparation investigation — 2026-09-30

`scripts/probe_epic_update_local.py` is an account-free investigation tool for
the existing startup image, not a new startup policy. It creates an isolated
private prefix, copies the installed wrapper into a temporary directory,
enables WineD3D only in that disposable copy, performs the real silent MSI
install, then observes the official launcher for at most three minutes.
It prints only selected update-stage messages, redacting URLs, emails and
long IDs and excluding authentication-related lines. It never signs in and
does not change the installed image wrapper or production profiles.

Run in a disposable container as the image user with a read-only repository
mount at `/workspace`. Use the manual authenticated Xvfb harness and an outer
timeout; `xvfb-run` hung during local Docker recovery:

```bash
timeout --kill-after=15s 600s bash /workspace/scripts/run_epic_update_probe.sh
```

Purpose: learn a genuine vendor update-completion signal before implementing
an automated OpenGL preparation / DXVK client handoff. A zero launcher exit,
an existing executable, or a visible window alone must not be treated as
proof that self-update completed. Account-bearing prefixes and user games
must not be interrupted by preparation.

Docker's engine recovered after the owner restarted it. Two bounded probes
completed the real silent MSI install with exit 0, then observed the official
updater for three minutes without account sign-in. Both disposable containers
were removed. The second probe explicitly selected the image's software
`lvp_icd.json`; a native Vulkan summary reported Mesa llvmpipe. This is a local
CPU graphics probe, not evidence of NVIDIA GPU compatibility.

The updater service's child repeatedly exited `777006`. Importantly, the
client also logged `LogSelfUpdateService: Installer complete. Success:1`,
`Waiting for next version update` and a successful `queryinstallation`, then
repeated the updater cycle. None of those messages alone can qualify completed
updating or trigger an automatic graphics switch. The probe now orders log
files by modification time and omits verbose build-stat counters. A genuine
stable completion signal still needs qualification on the GPU environment.

The same real, account-free run exposed two process-identity mismatches:
Epic changes its Linux process name between `EpicGamesLaunch` and `GameThread`,
and UMU sets `WINEPREFIX` to `<private-prefix>/pfx/`, where `pfx` is a symlink
back to the private prefix. Both were observed with the exact official Epic
executable and `FAUGUSID=dpad-epic`. The old restore helper rejected this alias;
the old handoff watcher missed `GameThread` entirely.

The local candidate corrects these guards. Resume accepts only the matching
user, marker, official executable and either the original prefix or its
verified self-referential `pfx` symlink. Updater commandlets, UMU helpers and
unrelated games cannot request client restoration. Handoff preserves a renamed
`GameThread` only with a matching owner, marker, private prefix and official
executable. Its existing continuous quiet period remains unchanged.

Focused validation passed: six resume tests, four handoff tests, an installed
wrapper restore dispatch with a real marked `GameThread` and `pfx/` alias
(existing process stayed alive; a second controller was refused), and the
actual installed Faugus hook retaining a detached marked child until it exited
before its quiet-period cleanup (30 seconds total). This is a process identity
fix, not a claim that the updater/client graphics handoff is automatic.
No image publication, production change or new cloud VM occurred.

## Updater service graphics proof — 2026-09-30

The owner's request to establish stronger evidence before another paid login
test was handled with account-free local diagnostics. Removing just Mesa's
headless Vulkan surface capability reproduced `wine_vkCreateInstance res=-7`
in a noninteractive Wine service while desktop D3D11 continued working. A
targeted pinned-Wine desktop exception for Epic's exact updater service made
that fixture pass; unrelated services retained the original behavior.

The actual official MSI and Faugus/UMU update then completed locally with DXVK:
`selfupdateinstall` exited 0, the service/application reported success, the
current launcher manifest existed, and the client reported up to date. Epic's
service type remained `0x10`. This removes the need for a broad service setting
change in the candidate. An earlier interactive-service experiment returned
installation-query code 4 and was discarded.

Local Xvfb caused a separate zero-refresh DXGI divide-by-zero; a disposable
Labwc/Xwayland software display removed that diagnostic obstacle. Production
Sway remains unchanged. The updated client logged a handled EOS minimum-version
warning after its installer reported `spawn UNKNOWN`; sign-in UI, account
operation, GPU extension capability and reopen acceptance are not claimed.

Source patch, narrow packaging recipe, reproducible service fixtures, exact
limitations and remaining acceptance are in
[EPIC-SERVICE-DIAGNOSTICS.md](EPIC-SERVICE-DIAGNOSTICS.md). All probe containers
and temporary prefixes were removed. No publication, production change or paid
VM occurred.
