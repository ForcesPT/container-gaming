# Instant GPU host preflight — unpaid preparation

## Changes and evidence
- Reproduced `[: -m: unary operator expected` in the maintained Docker preservation branch with real Bash and temporary files. Corrected the mount test. Existing backup conflicts now stop rather than nesting/overwriting state; failed restoration retains its backup rather than deleting it.
- Four storage regression tests pass without root, mounts, formatting, or touching real Docker storage. These are not live XFS acceptance.
- Added `scripts/instant_gpu_preflight.py IMAGE_DIGEST SOURCE_REVISION`: strict local repository digest and revision validation, no pull, no network/game mounts, NVIDIA library load and bounded actual NVENC pipeline. Container cleanup runs even on timeout. It sources `/opt/gstreamer/gst-env`, matching the image's streaming environment.
- Four probe boundary tests pass with Docker responses explicitly doubled. No live GPU encode has been run in this source pass.
- Full `test_instant*.py` discovery: 23 tests passed using Legendary0.21.1 from an isolated dependency environment. Legendary emits its upstream unclosed-file ResourceWarning. Namespace tests need the system Python path (a venv under `/tmp` is hidden by their isolated `/tmp`). Four separate storage tests also passed.

## Local package-resolution rehearsal
An ephemeral, rootless Ubuntu24.04 container (not a GPU/image builder) ran apt update and simulated:
`apt-get --simulate --no-install-recommends install nvidia-dkms-580-open nvidia-driver-580-open`

It resolved R580.173.02 open DKMS and libnvidia encode/decode/gl dependencies successfully; no `linux-image-*` package in that simulation. Evidence on the agent: `/tmp/instant-noble-open580-plan.log`. The existing default command was separately simulated at `/tmp/instant-noble-existing-driver-plan.log`; it includes additional recommended packages and generic kernel headers. Neither simulation reproduces the exact provider-installed package database or proves current-kernel headers/DKMS, reboot, EGL or encoding on a GPU. No driver-selection behavior was changed on this evidence alone.

## Next authorized host sequence
1. First finish ownership migration/permission rollout rehearsal and obtain explicit production deployment approval. Deploy the matched ownership-aware scheduler; verify acknowledgement before provider POST.
2. Obtain explicit approval for one paid test VM, its fixed reservation deadline, and publication of a uniquely tagged candidate image (not promotion of the public/live tag). The launcher requires `forcespt/dpadcloud-gaming@sha256:...`; a local image ID is NOT a repository digest. Do not weaken this fence.
3. Verify exact provider VM identity; prepare quotas BEFORE building. Filesystem creation is still tool-restricted and requires the authorized manual path if unchanged. Preserve Paris and its shared library.
4. Rehearse the driver transaction against this actual host, including current-kernel headers; do not silently accept a different kernel or assume the rootless simulation is sufficient. Use the maintained driver setup and verify the loaded driver after reboot.
5. Build exact committed runtime source on that SAME GPU with the maintained control-plane builder. Publish only the approved candidate, verify its digest/source, then run:
   `python3 scripts/instant_gpu_preflight.py forcespt/dpadcloud-gaming@sha256:ACTUAL_DIGEST ACTUAL_FULL_COMMIT`
6. Continue only after encode success into the maintained selected-release launch: private Paris NFS, ABZU registration, private customer login, browser gameplay, startup/loading measurements, then exact cleanup/pin release.

No production deployment, GPU allocation, registry publication, Paris modification or game download occurred in this source pass. GPU preflight, browser streaming and gameplay remain unaccepted. The ownership fix is in the companion control-plane repo; it must not be assumed live.
