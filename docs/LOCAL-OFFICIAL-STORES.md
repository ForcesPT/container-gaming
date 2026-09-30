# Local official-store qualification — 2026-09-30

Owner scope: use the Windows PC and RTX 4070 Ti, with no paid cloud VM.
Publish/deploy only after the local store gates pass. No account credentials
were entered during these checks. Login-window qualification does not prove
authenticated libraries, game installation, gameplay, or cross-session tokens.

## Current result

| Client | Local evidence | Remaining gate |
| --- | --- | --- |
| Steam Linux | Official sign-in rendered; pointer focus and dummy input worked | Final assembled-image recheck |
| Epic Windows | Fresh official MSI/update completed; DXVK sign-in rendered; dummy input and close/reopen passed; fresh preinstalled-template launch and clean close/reopen passed without installer/runtime download | Final all-store assembled-image recheck; no local account authentication |
| GOG Galaxy Windows | Official 2.1.9.27 sign-in rendered; dummy input, clean close/reopen, sanitized-template fresh clone passed; reproduced on the rebuilt shared-cache image without runtime download | No local account authentication |
| Battle.net Windows | Official installer completed; settled sign-in rendered; dummy input passed and was cleared | Fresh sanitized-template sign-in and reopen checks |
| EA App Windows | Official sign-in/input passed; fresh sanitized-template clone and reopen passed after repairing the existing service path | Final assembled-image recheck; no local account authentication |
| Ubisoft Connect Windows | Official installer completed; sign-in, dummy input and clean close/reopen passed | Fresh sanitized-template sign-in and reopen checks |

The Computer Use skill requires explicit approval before accepting a legally
binding installer agreement. On 2026-09-30 the owner explicitly approved
accepting the EA, Battle.net and Ubisoft installer agreements. Finish those
local installations and their UI checks under that approval.
GOG's previous account-free installation is available for independent checks.
No all-six-store release, registry publication, website deployment, or new
paid VM has been performed in this local qualification session.

## Fixes and actual behavior checks

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
