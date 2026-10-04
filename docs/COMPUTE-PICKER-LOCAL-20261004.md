# Local Compute store-picker reliability

Correction, October 4: `a1efea01` below is withdrawn as a release candidate because
its builder changed the default startup user. The picker evidence remains scoped
to its explicit UID-1000 fixtures. Corrected candidate `a9ea464f` preserves the
full startup contract; [current evidence](INPUT-LAYOUT-LOCAL-20261004.md).

October 4, 2026. Final runtime source `6fb4bb2`. Local candidate `dpadplay/compute:picker-local-20261004`, immutable image `sha256:a1efea01f5cd224272e020936928088940836e67bba78d24834763f9d9bc1c4e`. No publication, production activation or paid VM.

## Changes

- A 15-minute startup timeout keeps the picker and reports that startup is unconfirmed. It no longer falsely claims a window opened or hides the picker. Its existing managed child remains owned, preventing a second client.
- Stale child error/exit/timer callbacks cannot release or notify a replacement owner.
- Renderer overlays belong to one store and request generation. Another store's events or a delayed failed IPC result cannot dismiss a newer launch.
- Cards distinguish ready-to-open wrapper presence from Opening, Waiting for window, Window opened and Startup unconfirmed/retry. Returning with Esc/B does not cancel store startup, and refresh preserves keyboard/gamepad selection.
- Slow-start feedback asks users to check the taskbar for an installer/update; elapsed time is not presented as proof of installation progress.
- Failed catalog IPC preserves current choices and offers Reload stores. Launch IPC errors leave usable feedback instead of an abandoned overlay.
- The maintained official-store Dockerfile now packages current picker main/renderer/HTML/CSS and lifecycle code, rather than retaining obsolete UI bytes from its base. The fixed HTML closes its stage correctly.

## Packaged checks

`check_compute_picker_local.py` verifies the cached credential-free Compute base `93fef1d0…e62fe1`, builds a private derivative offline, and checks its base layers, environment and entrypoint are preserved. GE-Proton11-7 and all official client wrappers are unchanged. No customer profile, session volume or test-viewer files are copied.

Eight behavioral cases execute the actual packaged main/renderer code through Electron's Node runtime with explicit disposable IPC/compositor/child/DOM doubles. They cover timeout feedback, confirmed windows, stale owner callbacks, unrelated store events, delayed IPC, retry feedback, return-to-picker state and catalog retry. Five packaged source hashes match; the existing Epic reopen helper and native `koffi` import pass. Tests run offline as UID 1000 with no capabilities. All disposable containers are removed. Existing active-store resume policy checks pass separately against maintained source.

The pinned public ASAR 3.2.17 packaging dependency was downloaded once; its dependency lock hash is retained. The final derivative build and runtime checks use network-disabled execution. An initial network-disabled adapter dependency install was stopped because the cache was empty; no runtime test failed.

Final receipts: `docs/qualification/compute-picker-final-local-20261004.json`
and `compute-picker-ui-local-20261004.json`. The earlier `compute-picker-local`
receipt preserves the initial package checkpoint only.

Five real-browser scenarios pass with explicit IPC doubles at 1280×720,
1920×1080 and 390×844. Ready/retry screenshots were inspected. Browser checks
found and corrected a stale waiting badge after Esc followed by late failure,
and a Reload stores button below the visible viewport. Cards now refresh on
state changes; the card area scrolls and controls stay reachable. The final
package rerun passes all eight cases and its source hashes match the browser
source. The original ASAR dependency image is retained and reused offline by
`Dockerfile.picker-local`; its lock hash is unchanged.

## Remaining acceptance

These tests qualify picker behavior and package integrity only. They do not sign into accounts or prove client-update handling, real windows, pointer/keyboard/gamepad/audio, NVIDIA/WebRTC, persistent volume behavior or Shared isolation. All six official clients require final immutable-image acceptance before public promotion. Instant continues using its selected-store/game flow; this local Compute derivative is not assigned to Instant.
