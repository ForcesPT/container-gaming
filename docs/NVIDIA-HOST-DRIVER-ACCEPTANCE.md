# NVIDIA host-driver EGL candidate — source-only handoff

2026-09-05: **GPU, image build, and production acceptance pending.** No VM,
remote write, Docker build/push/deploy, commit, or push was performed for this
implementation. The original repository and its unrelated dirty AGENTS.md were
not edited. All implementation work is in the host-driver-egl worktree.

## Evidence and root cause

The separately completed UpCloud canary used host 595.58.03 with modeset Y,
production image
`sha256:f4bf28e7e17b6717b4c83f2e0f6d598eb0761f72543ffe065be5ff27b7ff26e8`,
and bootstrap/launcher revision `bc12cbd5413fdad3202aba58685eb34d12afa1bd`.
Its real NVIDIA library loaded from `/opt/nvidia-drivers/lib64`, but the system
`10_nvidia.json` was empty. A separate process initialized real NVIDIA device
EGL after receiving a temporary valid manifest. No decoded stream was observed.
Both VMs were deleted before this source work.

Original evidence (read-only):
`/home/home/dpadplay-diagnostics/upcloud595/{report.md,library-resolution.txt,egl-probe.sh,egl-probe.txt,final-evidence.txt}`.
This establishes an immediate GLVND registration blocker, not inherent 595
incompatibility and not complete 595 support.

Source investigation explains why the empty manifest survives: the installer
copies `.so*` and Vulkan JSON but never installs EGL vendor JSON. Its cache
shortcut accepts `.driver-version` plus an Xorg DDX file, without validating EGL.
The entrypoint ignores installation failure. Selkies uses default discovery;
Sway and Labwc explicitly select the empty system JSON. The Dockerfile copies
this installer but has no corrective EGL registration step. **The original
creator of the zero-byte live system manifest/placeholders is not established
by the source inspection; it would require separate image/toolkit investigation.**

## Implementation and trust boundary

`dpad-nvidia-egl` has fixed production paths and requires root on x86_64. It
cross-checks `/proc/driver/nvidia/version` against a successful `nvidia-smi`,
validates cached exact-version ELF64/ELF32 libraries and their SONAME links, and
loads the 64-bit SONAME in a fresh subprocess. The subprocess requires the EGL
vendor and Vulkan ICD entry symbols and verifies `/proc/self/maps` names the
exact installed EGL library; mapped core NVIDIA EGL dependencies must match
the same version. This does not call `eglInitialize`.

On every cold/cached setup, it atomically replaces individual manifests in
root-owned `/run/dpad-nvidia`. EGL and headless Vulkan use the architecture-neutral
`libEGL_nvidia.so.0`, allowing 32-bit children to select `lib32` while 64-bit
processes select `lib64`. Vulkan retains the installed package's API version.
The existing extraction of both architectures and Xorg modules remains.
Only `/opt/nvidia-drivers/graphics/lib64` and `graphics/lib32` are registered
with ldconfig; the raw extraction directories are never registered. Every warm
startup replaces the old broad ldconfig configuration and rebuilds its cache,
using the same publication path as a cold extraction. System EGL/Vulkan manifests and toolkit-mounted files are not rewritten;
extracted Vulkan layer metadata remains under `/opt/nvidia-drivers/lib64`.
The optional implicit-layer manifest is registered at its existing standard
location only when absent, using exclusive atomic publication; any existing
system/toolkit layer manifest is preserved.

Selkies explicitly receives the private metadata and library path **after**
`gst-env`; both nested desktops receive the same settings across `su` and
restarts. The private graphics/lib64 and graphics/lib32 directories precede other library
paths, so exact-version NVIDIA EGL wins over empty/stale baked placeholders.
They are rebuilt from an explicit NVIDIA graphics allowlist on each publication;
`check` rejects extra/missing files, aliases outside that set, or broad ldconfig
registration. Raw compute/video files can remain cached but are not published
into loader precedence. CUDA/NVENC/NVCUVID, OptiX, NVML, PTX JIT/NVVM and generic
GLVND dispatch libraries remain supplied by the toolkit/system/CUDA compatibility.

The graphics set retains NVIDIA EGL/GLX/GLES providers, EGL/GL cores, GLSI,
GLVKSPIRV, GPU compiler, ray-tracing core, allocator, TLS, Vulkan producer, and
EGL GBM/Wayland/XCB/Xlib platform libraries when present. The shared
compiler/allocator/ray-tracing dependencies are deliberately retained for
graphics; there is no blanket `libnvidia-*` publication. This allowlist is a
source candidate, not proof of complete GPU dependency closure on any driver.
Full NVENC, EGL/GLX/Vulkan and Steam/Proton interaction still requires acceptance.

Publication/installation preflight rejects symlinks at output paths, escaping
library symlinks, non-root-owned or group/world-writable paths/ancestors, and
mountpoints within installation/publication targets. It never repairs unsafe
ownership/permissions into apparent compliance. Atomic rename replaces JSON
without truncating an existing inode. Trusted root processes are within the
boundary; this does not defend against an already compromised container root.
Session-unreadable libraries or non-traversable library/runtime directories
fail validation. Read-only filesystem publication fails. Missing helpers, failed downloads,
partial libraries, stale aliases, or validation failures terminate startup
before `DPAD_READY`. The entrypoint independently checks the helper so an old,
permissive baked installer cannot bypass the new gate. Existing health checks
remain; readiness still proves signaling availability, not decoded video.

The `.run` extraction retains the existing exact-version NVIDIA HTTPS download
mechanism; it never invokes `nvidia-installer` or changes a kernel driver.
Download/extraction failures are now fatal. This work does not invent a
universal checksum for provider-specific NVIDIA packages.

## Driver policy and staged adoption

`DPAD_DRIVER_POLICY=validated` is the unchanged production default. It retains
OVH desktop 580, Hyperstack 570-open, and MassedCompute 580-open; keeps the
existing 580-server compatibility swap and the 595-to-580 validated fallback;
and does not generically upgrade unknown branches.

`DPAD_DRIVER_POLICY=host` is explicit opt-in: require a working installed GPU
driver and return before all driver package removals, installs, downgrades, or
upgrades. `DPAD_SKIP_DRIVER_SWAP=1` remains a strict alias when policy is unset
or `host`; conflict with explicit `validated` fails. Invalid/empty policies,
invalid skip values, and absent/malformed host driver output fail closed.
Persist the policy in the existing `/etc/environment` mechanism only during a
separately approved canary. Modeset remains a distinct existing bootstrap
requirement and can still require a reboot; host policy promises preservation
of the driver packages, not that all host preparation is read-only.

The staged goal is host-first across providers **after** per-provider GPU
acceptance. This change does not silently promote 595 or remove established
compatibility exceptions. Historical statements that 595 is intrinsically
unusable are superseded by the narrower evidence above; the production fallback
remains until acceptance.

## Packaging: rebuild required for this candidate

The Dockerfile includes the new helper and updated installer. Build an immutable
candidate image from the reviewed source only after build approval. **Do not
ship this entrypoint/bootstrap alone onto old images.** The existing streamed
hotfix bundle has only entrypoint, stream-quality resolver, and browser patch;
it cannot supply the new NVIDIA helper or installer. This candidate intentionally
fails startup when those are absent or incompatible. A rebuild must include the
helper, installer, and entrypoint together. Also verify that any existing host
hotfix bundle does not overlay an older entrypoint onto that rebuilt image.

The local bootstrap's entrypoint digest is computed from the actual changed
source to preserve the existing exact-source guard; this is not a published
artifact hash or authorization to distribute the candidate. All control-plane
pins and the other hotfix source pins are unchanged. The current three-member
updater/launcher protocol is unchanged. If upgrading old images without a
rebuild is later required, implement and review a complete atomic bundle
(entrypoint, installer, helper, resolver, browser patch), pin **every** member
and updater, validate before publication, mount one immutable snapshot, and
retain the previous complete bundle on any failure. Do not fabricate hashes,
relax source guards, or assume a helper happens to exist in an old image.

## Local verification

Reproduction and subsequent results are retained at
`diagnostics/host-driver-egl/red-green.log` (worktree-local, ignored diagnostics).
The initial cached-installer test failed with
`cached installer left NVIDIA EGL unregistered`, then passed after publication.
The host-policy tests failed with unexpected swaps/missing failure checks, then
passed. The old-image permissive-installer regression independently failed before
adding the explicit entrypoint helper check, then passed. Intermediate fixture
and cold-install failures are retained in the same log, not relabeled as success.

Commands:

```bash
python3 scripts/test_nvidia_egl_runtime.py
python3 scripts/test_host_driver_policy.py
python3 scripts/test_stream_quality_plumbing.py
python3 scripts/test_stream_hotfix_bundle.py
python3 scripts/test_dockerfile_pins.py
python3 scripts/test_dockerfile_pins_mutations.py
bash -n entrypoint.sh healthcheck.sh scripts/install-display-drivers scripts/vm-bootstrap.sh
python3 -m py_compile scripts/dpad-nvidia-egl scripts/test_nvidia_egl_runtime.py scripts/test_host_driver_policy.py
git diff --check
```

Final result: **32 local suites passed**, including 17 NVIDIA runtime tests and
4 driver-policy tests (with matrix subcases). All 46 tracked shell scripts
passed `bash -n`; Python compilation and whitespace checks passed. One
container-only Python test is dependency-blocked and three hardware/GPU tests
are excluded as detailed below.

All local `scripts/test_*.py` are enumerated in
`diagnostics/host-driver-egl/local-gates.txt`; per-suite logs are in that directory.
The ELF fixtures are assembled/linked using local `as`/`ld`, with real 64-bit
`ctypes.CDLL` loads. No fixture pretends to initialize a GPU. ELF32 structure and
SONAME resolution are local checks; real 32-bit EGL/Vulkan execution remains a
GPU-image gate. Mount rejection tests include host-mounted ancestors and use fixture mount metadata, not privileged
mounts. Shell child-process tests verify effective settings for Selkies, Sway,
and Labwc, including an intentionally conflicting gst-env.

Exclusions: `test_reconnect_persistence_gpu.py` starts GPU Docker containers;
`test_gamepad_interposer.py` writes device paths and requires the built container
interposer; `test_uinput.py` creates a privileged kernel device. They were not run.
`test_gamepad_patch.py` was attempted and is environment-blocked because
`selkies_gstreamer` is not installed locally; do not report it passing. No package
was fetched to manufacture a pass. Launcher source was not changed, so additional
launcher build/package gates do not apply; its local Python source/behavior
guards were included. Docker BuildKit checks, builds, GPU integration, network,
provisioning, registry, and deployment checks were not run.

Changed source paths:

- `scripts/install-display-drivers`, `scripts/dpad-nvidia-egl`, `entrypoint.sh`,
  and `Dockerfile`: validated userspace, protected metadata, fail-closed startup,
  environment forwarding, and image integration.
- `scripts/vm-bootstrap.sh`: explicit host policy and actual entrypoint source
  digest; provider defaults and control-plane pins remain unchanged.
- `scripts/test_nvidia_egl_runtime.py`, `scripts/test_host_driver_policy.py`:
  behavioral and source regressions.
- `docs/PROJECT_STATE.md`, `docs/IMAGE-RUNBOOK.md`, and this handoff: latest
  evidence, staged adoption, packaging blockers, and future acceptance.
- `diagnostics/host-driver-egl/local-gates.txt`: command inventory/results;
  `.log` evidence is retained locally and ignored by Git.

## Independent-review blocker follow-up (2026-09-05)

Review `upcloud595/review-v1.json` rejected the staged baseline solely because
its broad private-library precedence overrode toolkit CUDA/NVENC and configured
CUDA forward compatibility. The baseline was preserved in
`diagnostics/host-driver-egl/review-v1-baseline.patch`; this follow-up does not
change driver policy or production defaults, and no staging was performed.

RED was obtained before implementation edits with real ELF CPU fixtures:
`library-isolation.red.log` records toolkit `111 111` becoming private `222 222`,
and CUDA-compatibility/cache `123 111` becoming `222 222`. The compatibility
fixture uses actual `ldconfig` output and a private copy of the glibc loader
whose cache pathname points to an inherited fixture file descriptor. It does
not modify the host loader/cache or emulate precedence in Python.

`library-isolation.targeted.log` records the updated runtime suite, including
warm-cache and cold-extraction resolution with real ldconfig cache replacement,
exact ELF64 EGL selection against a competing toolkit EGL, both architecture
SONAME targets, real DT_NEEDED graphics dependency fixtures, excluded libraries,
projection contamination, alias restrictions and existing root/path protections.
ELF32 is assembled/linked and structurally checked; it is **not executed** and
its real loader entry symbols/dependency closure remain acceptance gates.

Follow-up full local gate commands/results and individual logs are retained in
`diagnostics/host-driver-egl/review-v1-fix/`. These supersede the earlier local
suite counts for this follow-up; the original evidence above is retained.
Final follow-up result: **32 suites passed**, including **22 runtime tests** and
**4 policy tests**; all **46 shell syntax checks**, Python compilation, source
hash pin verification, staged-baseline identity and both whitespace checks passed.
`test_gamepad_patch.py` was attempted and failed because `selkies_gstreamer` is
absent. The same three hardware/GPU suites listed above were excluded.
The entrypoint source hash pin was recomputed from the changed file. The parent
must freeze the new artifact hash and obtain a fresh independent review.

## Future explicitly approved 595 canary checklist — NOT RUN

1. Obtain explicit approval for one bounded paid canary, build/push as needed,
   and remote writes. Record immutable source/image IDs, lifetime/cost limit,
   provider resource IDs, and an independent teardown timer. Use `host` policy
   only for that canary. Preserve the existing production pin/default.
2. Record loaded driver version, `nvidia-smi`, kernel module version, modeset,
   and installed package list before and after bootstrap. Require exact 595
   preservation, no driver package transaction, and no silent fallback. Record
   effective source hashes and all bind mounts; confirm the rebuilt helper and
   installer are used and an old hotfix does not shadow the candidate entrypoint.
3. Cold-start the rebuilt image, then restart the same container to exercise the
   cache path. Require `dpad-nvidia-egl check` to pass both times. Record private
   manifests, permissions, both architecture library headers/SONAME targets,
   actual loaded paths, and unchanged system manifest checksums/mounts. Collect
   only the EGL/Vulkan/LD_LIBRARY_PATH variables from process environments;
   do not dump passwords or whole environments.
4. In a fresh process as `dpad`, repeat the supplied `egl-probe.sh` logic with
   `/run/dpad-nvidia/egl.json` and the production library path. Require
   `EGL_PLATFORM_DEVICE_EXT` initialization on NVIDIA, vendor `NVIDIA`, and
   `EGL_SUCCESS`. Mesa software initialization is not success. Also exercise
   EGL/GBM used by the nested desktop. A successful helper load is insufficient.
5. Exercise real **64-bit and 32-bit** EGL/Vulkan clients inside the image/Steam
   runtime, verifying actual loaded exact-version NVIDIA libraries. Test Vulkan
   instance/device creation, GLX/XWayland, and a Proton/DXVK game; ensure no
   needed implicit layer or NVENC behavior was lost. Verify actual CUDA/NVENC
   mapped paths still come from the toolkit and, when configured, CUDA
   forward-compatibility libcuda wins through the loader cache on both cold
   startup and warm restart. Verify the graphics dependency set on real drivers. A 32-bit ELF header alone
   is not acceptance.
6. Test Sway first, then Labwc separately: a real HTTPS browser must decode
   continuous H.264 NVENC video at the requested dimensions/FPS, with visible
   launcher and changing content. Capture decoded frame counts, video statistics,
   screenshots, renderer/encoder logs, and absence of EGL panic, flicker,
   corruption, or Mesa fallback. `DPAD_READY`, SDP, or an input channel alone
   cannot pass this gate.
7. Exercise pointer, scroll direction, keyboard, controller, audio, Steam
   login/launch, a real game, fullscreen, dialogs, and launcher restore. Repeat
   browser connect/decode/disconnect cycles and verify persistent compositor,
   nested desktop, XWayland, launcher identities and socket inode. After container
   restart require health recovery and fresh real browser decode/input/audio.
8. Run the approved reconnect GPU test and compare against a validated 580
   baseline. Verify the provider matrix on its actual GPUs before host-first
   adoption beyond UpCloud. Keep any proven compatibility exception explicit.
9. Save evidence with exact IDs/hashes and separate observed passes, failures,
   and untested items. Tear down the canary and disk and verify provider deletion.
   Promote only after separate review/approval; otherwise retain the current
   production image and validated driver policy.
