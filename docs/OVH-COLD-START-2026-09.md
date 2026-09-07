# OVH cold-start canary — 2026-09-07

## Scope and release boundary

Local `perf/ovh-cold-start` branch, based on image source `1c2d158` (the OCI revision of the actual production OVH image), not the incompatible newer stock595 host branch. No production deployment, mutable-tag update, or image rebuild. Keep the newer UpCloud release work untouched.

Opt-in host setting: `DPAD_PROVIDER=ovh`, `DPAD_OVH_COLD_START=1`, default release profile. Wrong provider/profile/flag fails before host preparation. Default/off behavior retains the existing CUDA probe. Production worker integration must explicitly deliver the reviewed bootstrap bytes and this setting; the flag alone with the old bootstrap does nothing.

## Changes

- OVH opt-in defers GPU verification until XFS/overlay2 and the exact selected gaming image are ready. Runs `docker run --rm --pull=never --gpus all --entrypoint nvidia-smi "$image"`; avoids a separate CUDA runtime image download and bypasses the gaming entrypoint.
- Missing image, Docker/GPU failure, or failed CDI generation cannot produce a new ready marker on this path. Existing readiness-marker lifecycle is otherwise unchanged.
- Replaced invalid Bash `[ ! -m /var/lib/docker ]` with `! mountpoint -q /var/lib/docker`. The live canary exposed the invalid unary operator, which skipped preserving pre-mount Docker state. Test reproduced loss of the intended move before the fix.
- No driver-policy, store, image content, or compositor changes.

## Real VM evidence

One authorized OVH GRA11 `l4-90`, public `Ubuntu 24.04 - NVIDIA - v580` template. Host actually supplied NVIDIA **580.178.04**, proprietary desktop, modeset Y. Kept unchanged, no reboot.

Exact gaming image: `forcespt/dpadcloud-gaming@sha256:f4bf28e7e17b6717b4c83f2e0f6d598eb0761f72543ffe065be5ff27b7ff26e8`.

- Provider request → observed ACTIVE: **216 s**.
- Request → observed successful SSH: **245 s** (polling observations, not precise service-availability timestamps).
- Cold bootstrap → VM_READY: **127.044 s**.
- Gaming image pull/unpack within that bootstrap: **112.141 s**.
- Separate old CUDA-image probe on the now-prepared host: **26.06 s**. This is *not* a paired fresh-host end-to-end benchmark or a guaranteed 26 s net improvement; the new probe also takes time.
- Operator gap before bootstrap: **99.611 s**, kept distinct from automated work. Do not quote this manual canary as a customer cold-start SLA or claim under five minutes.
- XFS 256 MB quota probe rejected its 300 MB write as expected.
- Real GPU test passed two peer lifecycles preserving Sway/XWayland/launcher and Wayland socket identities, then a Docker restart and a third peer lifecycle. Repeated after installing the final bootstrap hash.
- Final hash: `622549c9ffe0a7e0dbc7a24bb099011b4f5a54c7a206487bcdcaa2b0ea6ceba8`.
- The cold measurement was made before the mountpoint fix. Final bytes passed a repeat bootstrap on already-prepared storage and the GPU test. The mount-preservation branch is covered by a real shell/temporary-directory regression, not a second fresh VM.

## Image inspection

Registry layers total **6,127,349,278 compressed bytes**. Largest layer: **2,610,895,998 bytes**, preinstalled Windows stores. Actual installed sizes show Battle.net/EA/Ubisoft prefixes plus Wine/Proton runtimes and preinstalled Steam dominate. Apt cache/lists are already effectively empty. Steam's package directory is ~516 MB on disk, but deleting it needs update/recovery testing and rebuilding the owning layer; an added deletion layer would not reduce transferred lower layers. Do not remove store readiness or shared runtime content merely to reduce the number.

No image rebuild was justified in this bounded host-only pass. Image slimming, first-decoded-frame/browser/media acceptance, and the actual worker/customer flow remain separate work; this test proves host preparation and the GPU signaling/reconnect path, not audio/controller/game acceptance.

## Gates and cleanup

Seven new regression methods pass (including expected RED before changes). 28 applicable CPU source test scripts pass. Five runtime-dependent scripts are classified separately in `source-gates.json`: GPU reconnect passed live; uinput/interposer/Selkies-only probes and the existing installed-path store-recovery fixture are not claimed as locally passed. Shell syntax and diff whitespace checks pass. Hermes direct review; no subagents or independent-review claim.

Instance `234d91cb-1988-4e64-b1ec-9c29a872defc` was deleted. OVH first returned a DELETED tombstone, then `instances=[]`; backup cleanup schedule removed afterward. No separate volume was created. Request → deletion acknowledgement was 1000 s; actual invoiced cost was not queried.

Evidence: `/home/home/dpadplay-diagnostics/ovh-cold-start-20260907/` (metrics, cold bootstrap journal, both live GPU test results, image sizing, source gate logs and patch).
