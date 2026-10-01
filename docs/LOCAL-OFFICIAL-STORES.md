# Local official-store qualification — 2026-10-01

Owner scope: use the Windows PC and RTX 4070 Ti, with no paid cloud VM.
Publish/deploy only after the local store gates pass. The earlier account-free
qualification did not enter credentials. Owner-assisted account checks are
recorded separately below; login-window qualification alone does not prove
authenticated libraries, game installation, gameplay, or cross-session tokens.

## GE-Proton11-7 default — source `66613ff`

The owner requested GE-Proton11-7 as the default after the local EA/Battle.net
comparison. Source now applies it to base builds, bootstrap installers and
EA/Battle.net/Ubisoft wrappers, with per-store overrides taking priority over
`DPAD_PROTON_VERSION`. Epic/GOG retain their patched Proton 10 compatibility
overrides. The account-free official base build and local GUI canary completed.
The offline base probe verified actual selection/override cases, wrapper hashes,
runner availability and absence of owner state/local viewer. The final template
image `dpadplay/official-stores:66613ff-all` completed as
`sha256:05c6d8044259457a95e291cb4d375011e689234628e17619e3abdaec14788a45`.
All five installation-only template gates and the final offline default/wrapper
probe passed. Receipt: `test-results/official-stores-66613ff-receipt.json`.

| Client | Owner account acceptance on 11-7 | Full container restart |
|---|---|---|
| EA | Verification input, Home and Library passed | Reopened signed in; Library responded |
| Battle.net | Home and My Games passed; zero minidumps | Stable password prompt, email retained; remembered login unchecked |
| Ubisoft | Home and Library passed | Reopened signed in; Library loaded |

Ubisoft container `dpad-local-owner-ubisoft-ge117-66613ff` used localhost port
5808 with private volume `dpad-owner-ubisoft-ge117-local-20261001-66613ff`.
Its template was cloned offline and Portuguese input configured. It is stopped,
as are the completed EA/Battle.net tests; preserve all private volumes.
No game installation/gameplay was tested for these three clients. GOG reliable
cold start and native GPU streaming/NFS qualification remain open. No push,
deployment or paid cloud test. Receipt:
`test-results/owner-ubisoft-ge117-66613ff.json`.

## October 1 owner-assisted Epic check

The completed shared-game Epic container was stopped at the owner's request.
Both private Epic volumes and the game-only capture volume are preserved.
The next local account check uses a separate Steam container
`dpad-local-owner-steam-6e001d4`, built from the qualified
`dpadplay/official-stores:6e001d4-all` image. Its localhost viewer uses port
5803. The private volume `dpad-owner-steam-local-20261001-6e001d4` holds the
Steam install root, with the same `~/.steam/debian-installation` symlink
contract as production. Portuguese (Portugal) input is configured. Account
sign-in and Library navigation passed. After normal Steam Exit and a full
container restart, the client returned to sign-in. A sanitized probe confirmed
the account record and configuration survived on the private volume, but the
saved `RememberPassword` flag was `0`. The owner signed in again with Remember
me enabled, and the flag changed to `1`. Normal Steam Exit followed by another
full container restart reopened the client signed in, and Library navigation
responded. Local authenticated Library and container-restart login acceptance
pass. No Steam game installation or gameplay was tested in this account pass.
The ignored receipt is
`test-results/owner-steam-local-6e001d4.json`. No private state was packaged.

The next GOG account test is prepared offline in private volume
`dpad-owner-gog-local-20261001-6e001d4`. Mount its parent at
`/home/dpad/owner-gog` and use child prefix `/home/dpad/owner-gog/gog-galaxy`;
the template cloner atomically replaces an empty destination, so the prefix
itself must not be a Docker mount point. The official preinstalled executable
was verified present with networking disabled. The local GUI container
`dpad-local-owner-gog-6e001d4` uses viewer port 5804 and Portuguese input. Its
first launch exited before sign-in with `double free or corruption (fasttop)`.
One initialized-prefix relaunch rendered official GOG sign-in; owner account
acceptance is requested. The packaged msvcrt/ucrtbase hashes match the earlier
qualified d1a4c6c image. The owner then signed in; Owned games opened and
navigation responded. A full container restart preserved login, but its first
client launch exited without a window. One controlled relaunch reopened signed
in, and Owned games responded again. Login-state retention passes with that
qualification; reliable first launch remains unresolved and must be fixed
before publishing. The completed account-test container is stopped and its
private prefix is preserved. No GOG game was installed or played.
Receipt: `test-results/owner-gog-local-6e001d4.json`.

Official Battle.net is the next local account check. Its sanitized installation
template was cloned offline into private volume
`dpad-owner-battlenet-local-20261001-6e001d4`, with child prefix
`/home/dpad/owner-battlenet/battlenet`. Container
`dpad-local-owner-battlenet-6e001d4` uses localhost viewer port 5805 and
Portuguese input. Receipt: `test-results/owner-battlenet-local-6e001d4.json`.

The owner corrected the initial Home report: the client disappeared after
login and showed Blizzard's unexpected-error reporter. Authenticated Home is
not verified. The reporter was closed without sending a report. A local
sanitized minidump inspection recorded access violation `0xc0000005` at
`battle.net.dll+0xf08ab5`, reading `0x1de` with EAX zero. Public vendor DLL
disassembly places a caller near its threaded DNS resolver code; this does
not establish the cause. No private dump, authenticated log, or account
prefix was exported. A test-only wrapper copy now selects the already
installed GE-Proton10-34 runner on this same local container. The owner signed
in successfully; Home and My Games opened and navigation responded. No new
crash dump appeared during this check. Normal Exit and a full container
restart reopened sign-in without a crash. The email was retained; Keep me
logged in was unchecked. The owner chose to continue without another
automatic-login check, so remembered authentication is not claimed. The
completed container is stopped and its private volume is preserved.
The official-store Dockerfile
now selects `DPAD_BATTLENET_PROTON_VERSION=GE-Proton10-34`; the wrapper retains
GE-Proton11-3 as its legacy base-image default. Template assembly reapplies the
reviewed Battle.net wrapper after older installation archives. Packaging and
restart checks are in progress; no publication or production change occurred.

The next local account check is official EA App in
`dpad-local-owner-ea-6e001d4`, viewer port 5806. Its dedicated private volume
`dpad-owner-ea-local-20261001-6e001d4` mounts at `/home/dpad/owner-ea`, with
child prefix `ea-app`. It was cloned offline from the sanitized EA template;
the preinstalled executable was verified present. Portuguese input is set.
The service query reports RUNNING and zero exit codes; the official sign-in
window was visually verified. Owner reached verification, but could not enter
the code; refocusing the titlebar/field and using top-row number keys did not
resolve it. Authenticated EA acceptance remains open. The owner requested a
GE-Proton11-7 comparison; the old EA container is stopped and its private
volume is preserved. This test
uses the earlier qualified GUI harness; EA code/runtime were not changed by
the Battle.net runner selection. No cloud resource or private-state export.

`Dockerfile.local-proton-canary` is a local GUI comparison only. Source
`febce34` verifies the official GE-Proton11-7 x86_64 release archive against
SHA-256 `c5448b76a230384e2d7bc6beb5ccb97bafb7e2c3b6c527cb03a1a546bbcb00a0`.
It sets independent EA and Battle.net runner settings to GE-Proton11-7 while
retaining the installed older runners. The earlier built official-store image
uses the locally successful Battle.net GE-Proton10-34 fallback.
Do not copy patched GE-Proton10-34 DLLs into the new runner or infer that
all stores/games pass from its release notes. The completed local canary is
`dpadplay/local-proton-canary:ge11-7-febce34`, ID
`sha256:2469548f52d0ad009d6a15f231c41e14a0b6228144cf34b714dec0f692faab0c`.
Offline checks verified both reviewed wrappers, runner availability and absence
of owner prefixes. The image includes the local viewer and must never be published.

The owner completed EA verification successfully on GE-Proton11-7. Home and
Library opened and responded. Normal EA Exit followed by a full container
restart reopened signed in to Home; Library navigation responded again.
This qualifies EA account input, navigation and restart retention in the local
software Xorg harness. EA gameplay and native streaming remain untested.
The completed `dpad-local-owner-ea-ge117-febce34` container is stopped; its private
volume is preserved. Receipt: `test-results/owner-ea-ge117-febce34.json`.
Template assembly now reapplies the reviewed EA wrapper after copying older
installation archives; official-image integration of its new runner remains open.

Battle.net's GE-Proton11-7 comparison uses a new private prefix, leaving the
working GE-Proton10-34 prefix untouched. The completed container
`dpad-local-owner-battlenet-ge117-febce34` exposes only localhost port 5807.
The sanitized template was cloned offline into
`dpad-owner-battlenet-ge117-local-20261001-febce34`, with `battlenet` as the child
of its `/home/dpad/owner-battlenet` mount. Owner sign-in and responsive Home/My
Games passed. Normal Exit and full container restart reopened the password prompt
with email retained and Keep me logged in unchecked. Automatic-login testing was
previously skipped at the owner's request, so it is not claimed. A sanitized
probe found zero minidumps and confirmed the running UMU process selected the
GE-Proton11-7 runner. This completed test is stopped; preserve both private prefixes.
Receipt: `test-results/owner-battlenet-ge117-febce34.json`.

At the owner's request GE-Proton11-7 is now the source default for base builds,
bootstrap installers and EA/Battle.net/Ubisoft wrappers. `DPAD_PROTON_VERSION`
sets the default, and each store's own runner override takes priority. Base build
version, x86_64 asset name and checksum were updated together; custom build
overrides must supply all three matching values. The official-store source uses
an account-free stage and copies only the checksum-verified runner directory.
Epic/GOG retain their qualified patched GE-Proton10-34 runtime. The older runner
stays available as fallback in the official-store candidate. Template assembly
reapplies EA/Ubisoft wrappers alongside Epic/Battle.net. Ubisoft's GE-Proton11-7
owner check is being prepared. The existing EA contract check had stale expected
paths after its earlier numeric-version resolver change; it was corrected and
passes. This source has not been published or deployed; native streaming and
gameplay qualification remain separate gates.

The account-free fallback image from clean source `48d3afb` completed as
`dpadplay/official-stores:48d3afb-all`, ID
`sha256:fb3b050190fe2b88353eb309c3e2d1cfd241fc0be42a26fd4f5002c589139052`.
All five Windows template gates passed. Offline package checks confirmed the
Battle.net runner setting, executable availability, wrapper syntax, source
hashes for Battle.net/Epic, and absence of owner prefixes/local viewer.

The owner signed in inside official Epic on the local GUI harness built from
`dpadplay/official-stores:d1a4c6c-all`. Its private state is in a dedicated Docker
volume, separate from the release image and build context. Library opened.
After a full restart of the same test container and reopening the official
client, it returned signed in without another credential prompt. Library
navigation then responded. A separate window-only close/reopen check remains
pending; early viewer clicks did not activate the close control.

The private volume must be preserved and must never be exported or packaged.
The resource/acceptance receipt is ignored under
`test-results/owner-epic-local-d1a4c6c.json`; it contains no account details.
No raw authentication logs or signed-in prefix were copied. Official Epic
finished installing ABZÛ, showed Launch, and the owner reported the game worked
and that they exited it. This is local functional launch evidence, not native
Linux streaming, NFS or GPU-performance qualification.

After stopping the container, an offline helper mounted the owner's source
volume read-only with networking disabled. It copied only the fourteen
vendor-listed game files and verified their sizes and hashes against the
genuine official `.egstore` manifest. Payload size is 4,818,969,865 bytes.
The packaged exporter accepted the real completed `.item` record. The
game-only capture receipt is `test-results/abzu-genuine-capture-receipt.json`:

- Local release: `8562197e-690b-4eee-9034-fa574d421863`.
- Payload manifest: `a1b9a8af9df8ebfe4c338785f009a41eae8014120a07413f86fc5892e8658592`.
- Vendor manifest: `948f8707e8b3c24b43bc349386880ffe8b70896371cb5991b0c4915f8fa14b3c`.
- Installation capsule: `7ac68a36c101d3eca98a0de7bfb9a60de9892c87616e4a40ca503267be014c6d`.

A fresh local import harness then mounted that game-only volume read-only,
prepared the packaged private FUSE view, cloned the preinstalled official
client, and successfully registered the genuine records before starting Epic.
Its prefix is fresh; the original account prefix was not copied. The owner
signed in and confirmed ABZÛ gameplay worked, then exited normally. All fourteen
shared lower files were reverified against the captured payload manifest and
Epic vendor hashes while this private-overlay test was running. Mount flags
confirmed the shared lower was read-only and the private view was writable.
This passes genuine local shared-file recognition and functional game launch;
it does not establish NFS-backed FUSE or native streaming/performance.

This fresh volume also exposed a startup gap: setting Faugus's XDG data root
on the volume made UMU miss the baked home runtime and download steamrt3.
The recognition test proceeded to sign-in and gameplay. The source fix pins
`UMU_FOLDERS_PATH=/home/dpad/.local/share`, independently of the private Faugus
data root. The disposable image integration gate
`scripts/test_epic_runtime_location.py` passed an actual UMU/Proton console
probe with networking disabled, a fresh private-volume prefix and an initially
wrong inherited runtime path. It verified no runtime tree appeared in account
data. This gate uses a fake Faugus controller to execute the real console probe;
the actual Faugus child path is checked separately before packaging.
No cloud VM, registry push or deployment was performed.

The actual account-free Faugus child also resolved the baked home runtime,
reported no runtime download, and created no UMU tree under private account
data with networking disabled. This is a runtime-path check, not an offline
Epic sign-in assertion. The baked and downloaded runtimes' `VERSIONS.txt`
metadata is identical. Commit `6e001d4` also applies the reviewed wrapper after
template archives, so an older snapshot cannot replace it during assembly.

Final local packages from clean source `6e001d472a3b63465b17f2f6d55574ff97fa265e`:

| Artifact | Local image ID |
| --- | --- |
| `dpadplay/official-stores:6e001d4-all` | `sha256:a0436bd0ed80e99a412168562d5222940208d3614a4874bac7c50c1940fdb150` |
| `dpadplay/epic-instant:6e001d4-local` | `sha256:fafd0500d75ee6d411a32ed03716bcced0b781bcdface325595154ba81b72638` |

Both source labels match. All five Windows template gates passed. Both images
contain the tested clean-source wrapper with SHA-256
`e381e119d0aa51892e8ae4f7e62f840bd1c4dec16085f6bbbc6b0cdb745538e3`.
The qualified picker, Wine server and service executable remain byte-identical.
Neither private owner storage nor the local viewer is packaged. Build logs and
hashes are recorded in `test-results/official-stores-6e001d4-receipt.json`.
The successful owner-assisted game session remains on the earlier local import
harness; the fixed runtime route was checked independently above. Other-store
authenticated acceptance, NFS and native streaming/performance remain gates.

## October 1 packaged follow-up

The startup, registration and keyboard rollback fixes are now built from clean
source `d1a4c6c3a80ef1a7c0cd3034a1d765da7da55b95`:

| Local artifact | Local image index | Scope |
| --- | --- | --- |
| `dpadplay/official-stores:d1a4c6c-all` | `sha256:7f76586348d66fe0906b8d14e6d7544ea40a5156e475b0460f230f3e7641ee16` | Private official-client candidate |
| `dpadplay/epic-instant:d1a4c6c-local` | `sha256:e96b48f5a47f6fb0d8ef61e8cd955918fb9fd54ff6ee6df947721226e19bf17f` | Private import candidate; no genuine-game acceptance |

The import image extends the assembled six-store image with FUSE; it does not
replace the qualified runner, graphics configuration or preinstalled client.
Both source labels match the clean build revision. These are local indices,
not registry publication receipts. Neither image was pushed or deployed.

Account-free checks completed:

- All five Windows template assembly/sanitization gates passed.
- Actual packaged helpers match the clean source; no local viewer or test
  desktop is included. The picker archive, Wine server and service binary are
  byte-identical to the previously qualified runtime. This retains previous
  six-client UI evidence; it does not claim six new UI/account runs.
- Eleven installation tests, five keyboard rollback tests and two launcher
  startup-order/failure tests passed on the updated image.
- RTX 4070 Ti CUDA conversion and NVENC completed 60 frames on the assembled
  image without overriding the plugin registry. Native Wayland/EGL capture
  remains unsupported by this Windows/WSL test host.
- Real packaged Epic preparation cloned its installed template before game
  registration. Home and volume prefixes both registered and replayed one
  synthetic game while preserving client identity and one inventory entry.
- Real FUSE executable replacement and private save creation left shared lower
  bytes, directory contents and permissions unchanged in both cases.
- A real disposable Docker volume reused by two separate `--rm` containers
  retained the same private client identity and item record. The test volume
  was removed after its exact name and test/source labels were checked. This
  proves installation-state persistence, not saved account-token acceptance.

Fixture revision `eae66ff35558a30b3c300773ca15e18beddbf631` changes only the
overlay test relative to the image source. It corrects a shadowed test snapshot
variable and adds the two-container volume check. Product image code is
unchanged. Build/test logs and their hashes are bound by
`test-results/official-stores-d1a4c6c-receipt.json`.

The earlier saved local GUI container remains stopped. No account credentials,
real vendor manifest, game, registry publication, website deployment or paid
resource was used in this follow-up. Owner account/library checks, genuine ABZÛ
records and recognition, gameplay, NFS-backed FUSE, and native Linux streaming
remain acceptance gates before public Instant Play promotion.

## Current result

| Client | Local evidence | Remaining gate |
| --- | --- | --- |
| Steam Linux | Official sign-in, pointer/input and reopening passed on the assembled runtime after the normal client update | Account, library and gameplay acceptance |
| Epic Windows | Owner sign-in and container-restart persistence passed; genuine ABZÛ install and fresh-prefix shared-file gameplay passed locally; fixed private-volume runtime startup passed offline | NFS-backed storage and native streaming/performance acceptance |
| GOG Galaxy Windows | Official 2.1.9.27 sign-in/input, clean close and reopening passed on the assembled runtime | Account, library and gameplay acceptance |
| Battle.net Windows | Preinstalled-template sign-in/input, initial exit 0 and reopening passed on the assembled runtime | Account, library and gameplay acceptance |
| EA App Windows | Preinstalled-template sign-in, clean close and reopening passed with the service-path repair; input passed in the fresh repair test | Account, library and gameplay acceptance |
| Ubisoft Connect Windows | Preinstalled-template sign-in/input, initial exit 0 and reopening passed on the assembled runtime | Account, library and gameplay acceptance |

These UI results bind to local assembled runtime
`sha256:fdc695bb1a5ba2394a3a3512340fc91efc5a205eef37ad81810cb563fcec1086`
from source `7266fc11a2aab47131b8a1e756eabdd645e6c897`.
The private-prefix follow-up is source `d785c946d30a1b296f3bdc9d9e170bf612ebf541`;
its picker and rebuilt Wine service binaries match that qualified runtime byte
for byte and its installation-template input is unchanged. All five real
template clones passed private-root/marker permissions, ownership, distinct
identities, neutral-template retention and staging cleanup on the final image.

The Computer Use skill requires explicit approval before accepting a legally
binding installer agreement. On 2026-09-30 the owner explicitly approved
accepting the EA, Battle.net and Ubisoft installer agreements. These local
installations and their UI checks completed under that approval.
No registry publication, website deployment or new paid VM has been performed
in this local qualification session.

## Private publication candidate

- Image: `dpadplay/official-stores:d785c94-all`.
- Local image index:
  `sha256:63c3506ff444f00b7e9327f9c6c9eb5d7b9481ee084d02303984f66b38fee855`.
- Source: `d785c946d30a1b296f3bdc9d9e170bf612ebf541`, exported with `git archive`;
  unfinished shared-game recognition edits were excluded.
- Final hardware test: 60 frames of CUDA upload/conversion, NV12 and modern
  NVENC p4/ultra-low-latency/CBR on RTX 4070 Ti, without overriding the plugin
  registry. Evidence: `test-results/d785c94-all-nvenc.log`.
- Final security test: `test-results/d785c94-security.log`.
- Five actual private clones: `test-results/d785c94-private-identities.log`.
- Packaged EA sign-in and dummy input passed after the privacy fix. Evidence:
  `test-results/private-final-ea-login.jpg` and `test-results/d785c94-ea-ui.log`.
- Package scope: `test-results/d785c94-package-scope.log`; no local viewer,
  workspace or proof mounts are packaged. The client-only private test gate is
  retained. No public Instant Play binding is qualified by this receipt.

The six-client UI screenshots and close/reopen logs are named `final-<store>-*`
and `7266fc1-<store>-*` in `test-results/`. Actual Wine scope fixtures on that
runtime passed all three Galaxy renderer boundaries and six Epic SCM cases.
The privacy follow-up changes staging and root permissions plus the three
wrappers' ownership/mode setup; it preserves the qualified picker, Wine
components and installation templates. Keep that distinction in release claims.

Suggested separate publication tag:
`forcespt/dpadcloud-gaming:official-stores-local-canary-20260930-d785c94`.
Publishing this image does not itself approve a public product/profile change.
Record the registry's returned immutable digest before any profile binding.
For public Instant Play, capture genuine official game installation metadata
and verify recognition and gameplay first. Local launcher-window and NVENC
checks cannot replace native Linux Wayland/WebRTC/provider acceptance.

## Fixes and actual behavior checks

- The real five-prefix identity check exposed template root mode `0755` being
  copied into the EA, Battle.net and Ubisoft private prefixes. Cloning now
  keeps the copied payload inside a private staging envelope and publishes its
  root as `0700`. These three wrappers also repair the mode of an existing
  user-owned prefix before starting Wine and create new files with umask `077`.
  The regression gate uses an actual permissive template and preserves a
  non-empty prefix while testing each wrapper's permission repair.
- EA's installer registered a legacy `EABackgroundService.exe` path although
  its installed binary lives in a versioned directory. A fresh prefix exposed
  error 2 and the "Background services crashed" dialog. The wrapper now picks
  the newest valid installed version and repairs only the existing service's
  executable path through Wine's live registry API, preserving its account,
  start mode and permissions. A second untouched template clone reached
  sign-in, accepted dummy input and reopened without reinstalling. Evidence:
  `ea-fresh-service-repaired-login.jpg` and `ea-fresh-reopen.jpg`.
- GE-Proton10-34 Wine source, full GE/staging patch set and server protocol 864
  are matched before rebuilding components. An earlier protocol-856 experiment
  is rejected and must never be published.
- GalaxyClientService receives its exact Windows LocalSystem service identity
  and elevated primary token. Unix UID and ordinary user tokens stay unchanged.
  Existing exact Epic service rules are retained.
- Galaxy overwrites Qt's Chromium flags. The scoped Wine API/CRT compatibility
  hook appends `--disable-gpu` only for `GalaxyClient.exe` when
  `DPAD_GOG_SOFTWARE_RENDERING=1`. Three actual native probes passed: another
  executable is unchanged, Galaxy with the switch off is unchanged, and opted-in
  Galaxy receives the flag. Environment deletion remains valid in all cases.
- GOG uses a private user prefix and an external launch lock. The picker detects
  and focuses the exact official Galaxy window when `DPAD_GOG_BACKEND=official`.
  Accepted Epic reopen code is preserved through a narrow pinned ASAR adapter.
  Existing image builds retain their configured Heroic backend until the new
  release explicitly selects official GOG.
- Sanitization removes Galaxy local/roaming state, ProgramData account databases,
  user registry Galaxy branches and registry backups. Unrelated game registry
  keys remain. Symlink/race tests passed, including holding an original symlink
  inode open so an unlink/recreate cannot reuse it during quarantine checks.
- Template MachineGuid is neutralized and randomized in each atomic private
  clone. Only installation payloads are copied into the final image.
- The first fresh test exposed an absent shared UMU cache. The account-free
  official Steam Linux Runtime cache is now included in the generated template
  stage; its locks, test desktop, user prefixes and logs are excluded.
- CUDA's unversioned NVRTC library alias is packaged. The bundled GStreamer
  1.24.6 CUDA upload/conversion -> NV12 -> modern NVENC encoder completed 90
  frames on this RTX 4070 Ti with low-latency p4/CBR settings. The old legacy
  factory probe falsely rejected this driver; the preflight now matches Selkies'
  modern encoder selection.

## Local display limits

With GPU injection enabled, Docker's regenerated loader cache selected the
system Wayland 1.22 server instead of the packaged 1.23 ABI. Explicitly putting
`/usr/local/lib/x86_64-linux-gnu` on `LD_LIBRARY_PATH` resolves that symbol error.
The candidate and future base-image builds retain that precedence; a build-time
factory check verifies the packaged compositor loads without GPU injection.
That check uses and removes a temporary plugin registry. Baking a no-GPU
registry into root's cache hid CUDA/NVENC factories from later root probes;
using a fresh registry restored hardware encoding on the assembled image.

Docker Desktop exposes CUDA/NVENC through WSL but this host does not expose the
native Linux EGL interop entry point needed by the production Wayland capture
plugin. A 60 Hz dummy Xorg display and software Vulkan/GL are used for local
launcher UI checks. Hardware CUDA conversion/encoding is independently tested.
This is not proof of the full production Wayland/WebRTC path or GPU gameplay.
Do not change provider driver rules to work around a Windows-only test limitation.

## Rebuild sequence

Run from this worktree with Docker Desktop's Linux engine running:

```powershell
docker build -f Dockerfile.store-wine-builder -t dpadplay/store-wine-builder:repro .
docker build -f Dockerfile.official-stores -t dpadplay/official-stores:repro --build-arg DPAD_SOURCE_REVISION=<clean-full-commit> .
```

`Dockerfile.store-wine-builder` uses a pinned official Ubuntu base, exact Valve
Wine/GE/staging source commits and checked source-archive/patch hashes. The
runtime retains the immutable accepted official-Epic base
`forcespt/dpadcloud-gaming@sha256:cc58f0f2fa167ba464a4c5634076d3e8720e07f890118692fa332a26ff27f4ff`.
Complete patched Wine source and licenses are bundled in the candidate.
The Qt compatibility work adapts the MIT-licensed
[Soju patch](https://github.com/BCD1210/soju/blob/54c6c10a77e72c05d048090526af000748729d88/patches/chromium-flags-append.patch)
with an exact Galaxy executable/switch gate; its license is bundled too.

Compile the account-free native fixtures with the builder's
`x86_64-w64-mingw32-gcc`: `scripts/gog_environment_probe.c` ->
`test-results/GalaxyClient-probe.exe` and the maintained
`scripts/epic_service_identity_probe.c` ->
`test-results/epic_service_identity_probe.exe`. Run them through
`scripts/test_gog_environment.py` and `scripts/test_epic_service_identity_umu.py`
as `dpad` in the disposable GUI harness. These use temporary private prefixes;
they do not start an account login flow.

Generated installation templates are separate local scratch images. Export only
sanitized installation prefixes, and the validated `steamrt3`, `steamrt4` and
`umu-shim` caches;
never commit a GUI test container as the release image. Build a minimal scratch
context with `ADD <store>-prefix.tar /opt/dpadcloud/` for each Windows store,
`ADD umu-runtime.tar /home/dpad/` and `ADD steamrt4.tar /home/dpad/`, then:

```powershell
docker build -t dpadplay/store-templates:local test-results/gog-template-build
docker build -f Dockerfile.official-store-templates --build-arg STORE_IMAGE=dpadplay/official-stores:repro --build-arg TEMPLATE_IMAGE=dpadplay/store-templates:local -t dpadplay/official-stores:ready-local .
docker build -f Dockerfile.local-store-test --build-arg STORE_IMAGE=dpadplay/official-stores:ready-local -t dpadplay/local-store-test:ready-local .
```

The default assembly gate requires all five Windows clients and their matching
shared runtimes. Missing executable, template marker or runtime fails the build.
It reruns account-state sanitization and requires a neutral template MachineGuid.
An intermediate local Epic/GOG assembly explicitly uses
`--build-arg WINDOWS_STORES=epic,gog`; it is a partial test image, not a release.
The local tag `ready-local` does not signify all six stores passed. Finish the
UI matrix before publishing; the template gate cannot prove login rendering.
Host viewers must be bound only to `127.0.0.1`; they are not production images.
Use `--gpus all --shm-size 2g --cap-add SYS_ADMIN` and the documented nested-UMU
seccomp/apparmor/systempaths options. No cloud provider API calls are needed.

## Saved local evidence

Build logs and an account-free GOG sign-in screenshot are under ignored Docker
context directory `test-results/`. The exported GOG archive SHA-256 is
`f48fe156c17f5f9a9052b10a6456568238a1aa66593180a45b3a1abc7a20cfcb`;
the validated runtime cache archive is
`25d761f9469a96978419d3fd7027b7a8dc6edfe3d43889bab8a362474af26b08`.
The account-free Epic template archive is
`c8fdb5fdd5c6bf643aa31630eed3e55e4cab3e88ed22b9e75a38fb2d5b0d90f6`;
the validated Steam Runtime 4 archive is
`226e9af7cf90e2219b7880086481eb76b4a281bab1e4972672c0a831a925eb7b`.
The final assembly reruns sanitization before template use.

The intermediate Epic/GOG assembly
`sha256:9f0fd3f52b3dd84f0afa0d4f301cc8d713af40cdca94fe5af89af41870d5e301`
opened official Epic sign-in directly from an empty private prefix. Dummy input
worked and was cleared without submission. Its first close exited normally;
normal reopen returned to sign-in without cloning again, reinstalling or
downloading the runtime. The template MachineGuid remained neutral and the
private clone received a distinct identity. No account was entered.
Saved evidence: `test-results/epic-preinstalled-login.jpg`.

The combined Epic/GOG image also rendered official Galaxy sign-in from a fresh
private prefix and exited cleanly after its window closed. Saved evidence:
`test-results/gog-combined-login.jpg`. Official Ubisoft, EA and Battle.net
sign-in screenshots are `ubisoft-login.jpg`, `ubisoft-reopen-login.jpg`,
`ea-login.jpg` and `battlenet-login.jpg` under that same ignored directory.
No dummy input was submitted and no local store account was authenticated.

Installation-only archives from these account-free tests:

| Store | SHA-256 |
| --- | --- |
| Ubisoft | `5734d4dcdb935360f735277497c81574c4194738c9882c4cd0bbcf654bc36ad1` |
| EA | `66da636288ffddc1037dc185f7829c997fc2951ccef7f538778d27c4f2c5ad1d` |
| Battle.net | `4c0db5ed5ee4c527e8220ea8e24e573aa91ef189865d84d3111fdd22693a6395` |

Final local assembly index `sha256:1c434a27c24b093b007381008ae4b315901ec92d304dfc6a43843efad3a2bc0e`
rendered GOG sign-in with `template_cloned=True`, `runtime_download=False` and
`runtime_validation_failed=False`. The fresh source builder's three real Wine
API/CRT renderer probes passed, and six Epic SCM cases passed through UMU:
only the exact official EOS service received LocalSystem identity. The raw
host-Proton fixture cannot run reliably on this WSL harness; its actual UMU
runtime invocation is `test_epic_service_identity_umu.py`.

Focused regression results: store-template security/atomicity passed; picker
resume passed; desktop helper tests 17 passed under the non-root user; GPU
preflight tests 4 passed. Desktop publication intentionally rejects arbitrary
root output paths; run its fixtures as `dpad`, not root.

Official ABZÛ installation records still have not been captured. Existing shared
payload recognition work remains separate from this six-store qualification.
