# Local official-store qualification — 2026-10-01

Owner scope: use the Windows PC and RTX 4070 Ti, with no paid cloud VM.
Publish/deploy only after the local store gates pass. The earlier account-free
qualification did not enter credentials. Owner-assisted account checks are
recorded separately below; login-window qualification alone does not prove
authenticated libraries, game installation, gameplay, or cross-session tokens.

## October 1 owner-assisted Epic check

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
| Epic Windows | Preinstalled-template DXVK sign-in/input, clean initial close and normal reopening passed on the assembled runtime without installation/runtime download | Local account and gameplay acceptance |
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
