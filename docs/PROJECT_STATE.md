# DpadCloud Container Gaming — Image State & Handoff

> **Lean handoff (2026-07-30).** Current state of the
> `forcespt/dpadcloud-gaming` images: what's built, what's validated, the
> baked-in fixes, the known limitations, and the open image-side items. The full
> debug journey (gamescope breakthrough, N-on-N validation, the 6-layer
> gamepad fix chain, the bubbleroot/steamcmd dead-ends, the wrong-then-corrected
> driver diagnoses) is preserved in `git log` — this doc is the resume point,
> not the history.
>
> **Companion:** `IMAGE-RUNBOOK.md` (the launch recipe + env-var reference +
> troubleshooting — the operational runbook), `cloud/docs/STATUS.md` (the
> control-plane handoff), `cloud/docs/V2-PLAN.md` (the post-Vast architecture),
> **`WAYLAND-ARCHITECTURE.md`** (the compositor pivot decision and historical
> validation record).
>
> **2026-08-16 launcher-only Steam desktop — CURRENT SOURCE RESUME POINT.**
> The runtime now has exactly one architecture: Selkies/
> `gst-wayland-display` → nested Sway/XWayland → DpadPlay launcher. The DpadPlay
> launcher is always the session shell. Its Steam card starts Valve's official
> Linux desktop client with no special presentation mode. The image build no
> longer installs the retired compositor, its patched builder/binaries, capture
> bridge, runtime functions, probes, or selection variables. The old Steam-shell
> fallback and all old shell/compositor env gates are gone from `entrypoint.sh`,
> `dpad-launch-session`, and `vm-bootstrap.sh`. A compatibility wrapper at
> `/usr/local/bin/steam` starts `/usr/bin/steam` without inherited launcher
> presentation flags, so the already-published cached launcher bundle cannot
> restore the removed mode. Regression guard:
> `python3 scripts/test_launcher_only_architecture.py`.
>
> **Release state:** this is implemented and source-validated, but it is not yet
> a new registry release. The existing `r4` digest below remains the current
> published image until a Docker-capable NVIDIA builder creates and canaries a
> new immutable tag.
>
> **2026-08-16 Selkies browser UI overlay — CURRENT.**
> `scripts/patch_live_resolution.py` now restyles the Selkies 1.6.2 navigation
> drawer with the DpadPlay dark monochrome design system, keeps the selected
> resolution visible across the required reconnect, and places a clear
> **Manual refresh required** notice plus Refresh button immediately below the
> Resolution selector. The V2 overlay hides the loading treatment once both
> media peers are connected, uses an edge-attached capsule with explicitly
> centered Settings icon, applies dark styling to detached Vuetify dropdown
> menus, and puts session actions (fullscreen, clipboard, launcher, gamepad,
> user) in the first drawer category. Loading is intentionally minimal: a flat
> dark viewport with the centered Selkies loader and status text, without a
> logo letter or ambient effects. Resolution changes remain intentionally
> manual-refresh:
> NVENC does not renegotiate dimensions in-place. The runtime overlay is fetched
> from `main` at container boot as an idempotent backstop; the accepted V5 UI is
> also baked into the immutable `r4` image below.
>
> **2026-08-16 `r4` Selkies UI release — CURRENT REGISTRY IMAGE.** Commit
> `c3a1b7b7579bd87ea088e781f3c2be8b42530bcd` was cloned cleanly on an OVH
> GRA11 NVIDIA L4 builder, passed the Selkies UI suite, obsolete-component guard,
> exact-pin validator, all 12 unsafe mutation cases, and BuildKit validation, and
> was built with that exact OCI revision label. NVIDIA smoke checks on driver
> 580.159.03 verified Selkies 1.6.2, the DpadPlay launcher, SDL3, Lutris, NVENC,
> gst-wayland-display, the baked V5 UI, and absence of both retired components.
> The immutable `forcespt/dpadcloud-gaming:dpad-SteamOS-2026.08.16-r4` and
> convenience `:dpad-SteamOS` tags resolve to index digest
> `sha256:7244378ed3061b512ddcf415f12083840eb852db323b7bd0a3d09b92052a3bae`
> with linux/amd64 manifest
> `sha256:befd231611484a3cbc42ca3241ed4055e9d3dd46287368d13e832966b490de47`.
> The remote manifest was pulled back and its revision label reverified. Provider
> production references remain on `r3` until an explicitly approved canary/promotion.
>
> **2026-08-15 `r3` component-cleanup release — PREVIOUS/ROLLBACK IMAGE.**
> The gaming image no longer installs or starts an in-container tunnel daemon:
> production HTTPS is `play-<session>.dpadplay.com` → Caddy → stream-bridge →
> the VM's published Selkies port. The retired alternate gamepad shell and its
> wrapper/env branches were also removed; `DPAD_STORE_SHELL=picker` remains the
> authoritative DpadPlay launcher path. **Lutris remains installed as a possible
> compatibility/backend component, and SDL3 remains because dpad-launcher uses
> it through koffi for gamepad input.** Run
> `python3 scripts/test_obsolete_components_removed.py` to guard this boundary.
> Commit `6699b5ffef6de628604fd103fdcb756364d3bf40` was cloned cleanly on an
> OVH GRA11 `l4-90`, passed all three source validators and BuildKit validation,
> and was built with that exact OCI revision label. Runtime checks on NVIDIA L4
> driver 580.159.03 verified Selkies 1.6.2, SDL3, Lutris, and the DpadPlay
> launcher remain while both retired binaries/wrappers are absent. The immutable
> `forcespt/dpadcloud-gaming:dpad-SteamOS-2026.08.15-r3` and convenience
> `:dpad-SteamOS` tags both resolve to
> `sha256:f0017b8a115a870eb733c715d5917e2ccfaa4ff85e2d0555ade4dee141ec3762`
> (amd64 manifest `sha256:2c08d1df621d204b1d4252748942eb6344e2dfa0b0f7914475b103cbd356f20d`).
> The remote image was pulled back and its revision label reverified.
>
> **2026-08-15 `r2` exact-provenance release — SUPERSEDED BY `r3`.** Commit
> `63eb0c037fb79578b9f3cc37c19f8f8f73609927` was cloned cleanly on an OVH
> GRA11 `l4-90`, validated with `docker buildx build --check`, built with OCI
> revision label set to that full commit, structurally smoke-tested, GPU-tested
> on an NVIDIA L4/driver 580.159.03, and pushed as both
> `forcespt/dpadcloud-gaming:dpad-SteamOS-2026.08.15-r2` and `:dpad-SteamOS`.
> Both remote tags resolve to OCI digest
> `sha256:50a8ce28a32b0e2f0ae396e3e9d6523f7509d551f9400279ef6525c263b0aa34`
> (amd64 manifest `sha256:1d7026273a359641b41d931bdce5dd292a9bd5262e7944256ef26a94aa898fcc`),
> and the remote image revision label was read back and verified. In addition to
> the `r1` guards, `r2` pins/checksums SDL3, cloudflared, VirtualGL, Heroic,
> VKD3D-Proton, DXVK, DXVK-NVAPI, lutris-gamepad-ui, and Lutris; every guarded
> download uses bounded retries, an exact URL template, an in-scope version/hash
> ARG, exact checksum target, and failure-gated consumption. Smoke checks passed
> for Selkies 1.6.2, SDL3, cloudflared 2025.7.0, VirtualGL, Heroic, Lutris,
> lutris-gamepad-ui, all three Heroic compatibility-tool directories, umu,
> GE-Proton, the Wayland plugin, launcher, and NVIDIA runtime.
> Permanent regression commands are `python3 scripts/test_dockerfile_pins.py`
> and `python3 scripts/test_dockerfile_pins_mutations.py`; the latter currently
> proves 12 unsafe mutations are rejected, including the two late independent-
> review findings (`! sha256sum` and arbitrary successful `||` fallbacks).
>
> **2026-08-15 reproducible-build slice — COMPLETE, BUILT + PUSHED from OVHcloud GRA11.**
> The first item in `.hermes/plans/2026-08-15_195142-container-gaming-stack-roadmap.md`
> is partially implemented: Selkies is pinned to `1.6.2` and all four consumed release assets
> (GStreamer bundle, Python wheel, web bundle, joystick-interposer deb) are
> SHA-256 verified; GE-Proton11-3 and umu-launcher 1.4.4 now have non-empty
> checksum defaults. The Wayland 1.23.1 and pinned gst-wayland-display source
> archives are also checksum-verified and downloaded to files with bounded
> retries before extraction. This was validated by a real failure: the first OVH
> build hit a GitLab HTTP 504 in the old `curl | tar` path; the hardened retry
> path then completed cleanly. Built on an OVH `l4-90` (Ubuntu 24.04.4, NVIDIA
> L4, desktop driver 580.159.03), structurally smoke-tested (Selkies 1.6.2,
> Wayland plugin, launcher, umu, GE-Proton, NVIDIA runtime), and pushed as both
> `forcespt/dpadcloud-gaming:dpad-SteamOS-2026.08.15-r1` and `:dpad-SteamOS`.
> Both tags resolve to OCI digest
> `sha256:1f9282b89eaf305c0193af36365de3ddd9c6a97f61ed3ba60c7a36398bfd6f62`
> (amd64 manifest `sha256:699702893897e046e9ece2ffed199f5d0360954c5d6c48a92a22a383b99085c5`).
> Standard BuildKit could not pre-bake the Battle.net/EA prefixes because
> pressure-vessel/bwrap needs the documented privileged-container + commit
> workflow; runtime fallback remains intact. Regression guard:
> `python3 scripts/test_dockerfile_pins.py`.
>
> **Post-build review hardening (commits `34313a2`, `bbfffb8`):** future builds
> cannot bypass GE-Proton or umu verification with an empty build argument.
> Every guarded checksum is bound to its exact downloaded filename, each curl
> command has bounded retries, and verification must exclusively gate the next
> verification/extraction/install command. Mutation checks reject wrong targets,
> swapped Selkies targets, conditional checks, `|| true`, `&& true || true`,
> consumption before verification, missing downloads/retries, and `curl | tar`.
> The published `r1` image was built with the recorded non-empty checksums and
> passed all artifact/GPU smoke checks; these follow-up commits harden the build
> policy and validator for subsequent releases. `r2` above supersedes it and
> provides exact source/image provenance.
>
> **Scope boundary:** this completes the first safe reproducibility slice, not
> every item in roadmap Task 1. Still unpinned/unlocked include base/external
> image digests, NVRTC selection, Rust/cargo, Steam bootstrap, APT snapshots,
> and conditional store-prefix installers. Roadmap Task 2 is also partial:
> immutable tag + digest publication are done, but control-plane digest pinning,
> canary rollout, and rollback wiring remain.
>
> **2026-08-10 Battle.net session — the `battlenet-launch` wrapper + launcher
> card shipped + were live-tested on an OVH Gravelines L4; the install stalls at
> the 32-bit Blizzard Update Agent under Wine 11's experimental new wow64 → the
> next step is umu-launcher (STORES-PLAN §10 piece 1c).** Built + pushed: the
> `battlenet-launch` wrapper (`scripts/battlenet-launch`), the launcher's
> `battlenet` card (`bin:'battlenet-launch'`, `comingSoon` removed), the
> entrypoint's `setup_stores()` (symlinks `~/Games` → `<vol>/games` when
> `battlenet` ∈ `DPAD_STORES`; plain dir on ephemeral), + the Dockerfile bake
> (`/usr/local/bin/battlenet-launch`). Launcher image rebuilt + pushed
> (`forcespt/dpadcloud-launcher:0.1.0`, digest `sha256:340629a6…`) +
> `:dpad-SteamOS` rebuilt + pushed (digest `sha256:0091f28279c8…`). Commits
> `5b01494` (the wiring) + `06feb00` (the live-test fixes). The cloud worker
> already writes `DPAD_STORES=steam,epic,gog,battlenet` + `DPAD_STORE_SHELL=picker`
> to `/etc/environment` (commit `56b5db7`, deployed) → new VMs activate
> `setup_stores` automatically.
>
> **The live test (OVH L4 `591b387c-…` @ `51.210.224.7`, open R580, picker +
> wayland-display + sway):** the wrapper launches, the Blizzard installer
> downloads, + the Blizzard Update Agent (Agent.exe + AgentHelper.exe +
> BlizzardError.exe) downloads fully — BUT the Agent won't launch:
> `BLZBNTBTS0000005C` / `BLZBNTAGT00000002`, *"Failed to communicate with
> Agent after launch, Agent.exe error=2"*. `Agent.exe` is **32-bit** (PE32
> Intel 80386) + Wine 11's *"experimental new wow64 mode"* struggles with its
> process creation/IPC — the documented-fragile manual-wine wall. Two live-test
> fixes landed in `06feb00`: (1) the working installer URL
> `getInstallerForGame?os=win&version=LIVE&gameProgram=BATTLENET_APP` (the
> `getInstaller?installer=` endpoint 400s from the EU/OVH IP); (2) the Lutris-
> script-equivalent pre-config — `WINE_SIMULATE_WRITECOPY=1` +
> `WINEDLLOVERRIDES="locationapi=d"` + `winetricks -q corefonts win10 vcrun2022
> d3dcompiler_47` + a pre-written `Battle.net.config` (HW accel/sound/streaming
> off). These got the install from *nothing* → *Agent fully downloaded* but did
> NOT fix the Agent launch (vcrun2022 was not the missing piece — the diagnostic
> showed Agent.exe loads its core DLLs fine, no missing module).
>
> **Two stacked blockers:** (a) the Agent-launch wow64/IPC failure (above) → the
> umu pivot; (b) the §16.9 sway SIGTRAP (the wlroots keyboard-group-destroy
> assert on compositor teardown at peer-disconnect) killed the long-running
> install once — the Battle.net install is a ~5-min wine process that needs
> sway/XWayland up the whole time. umu fixes (a); the follow-up for (b) is the
> build-time prefix pre-bake (STORES-PLAN §7 piece 2) so first launch is a fast
> login, not a 5-min install (the pre-bake needs umu to fix the Agent launch
> first — same wine at build time would hit the same wow64 issue without umu).
>
> **✅ DONE (code, 2026-08-10) — the umu-launcher pivot (STORES-PLAN §10 piece
> 1c) LANDED in `container-gaming` `main` + **built + pushed to Docker Hub**
> (digest `sha256:76e3cfaa22af…`, supersedes the `sha256:166b76709e0c` wrapper-only
> image):** `scripts/battlenet-launch` is rewritten to use
> `umu-run` (`STORE=battlenet GAMEID=umu-battlenet PROTONPATH=GE-Proton11-3`)
> instead of raw `wine`, + a new Dockerfile block (vast-vm stage, piece (e))
> bakes `umu-launcher` 1.4.4 from the official Ubuntu Noble `.deb`. Validated by
> an isolated `ubuntu:24.04` + deb build-test: `python3-umu-launcher` installs
> clean (apt resolves python3-xlib / apparmor-profiles / libzstd1 / libgl1-mesa-
> dri:i386 / libglx-mesa0:i386), `/usr/bin/umu-run` on PATH, `import
> umu.umu_consts` works (cpython-3.12 = Noble's python3), `umu-run -h` prints
> help without fetching the ~1–2 GB SLR (build-time sanity is safe); the
> Dockerfile parses (`buildx --check`: no warnings). umu wraps GE-Proton in the
> Steam Linux Runtime container (matched 32+64-bit libs + Valve's tested wow64 +
> protonfixes) — the 2026 consensus reliable path (sudowheel: *"Method 1: Via
> Steam [umu] is the most reliable approach"*). The image already runs
> Steam/Proton so pressure-vessel works. **Container nesting:** umu →
> pressure-vessel → bwrap needs `unshare(CLONE_NEWUSER)` + a few syscalls; our
> session container already runs the bwrap-nest flag set (`--cap-add SYS_ADMIN`
> + `--security-opt seccomp=unconfined apparmor=unconfined`, IMAGE-RUNBOOK) +
> the host sysctls (`kernel.unprivileged_userns_clone=1` +
> `kernel.apparmor_restrict_unprivileged_userns=0`, vm-bootstrap) — covers umu
> issue #156 + the Noble AppArmor userns restriction. One possible runtime extra:
> if pressure-vessel hits `Can't mount proc on /newroot/proc`, add
> `--security-opt systempaths=unconfined` to the `docker run` (the 4th bwrap-
> nest flag). **✅ LIVE-VALIDATED on an OVH Gravelines L4 (2026-08-10):**
> umu + pressure-vessel + bwrap nested cleanly with the 4-flag set
> (`--cap-add SYS_ADMIN` + `seccomp`/`apparmor`/`systempaths` unconfined — no
> `Can't mount proc` error); `umu-run winetricks` initialized the prefix inside
> the SLR; the Blizzard installer ran via `umu.exe`→GE-Proton + the 32-bit
> **Agent.exe launched (no `error=2` / "Failed to communicate with Agent"** —
> the raw-wine wall is gone); Battle.net installed + launched. **One follow-up
> fix:** the CEF UI white-screens under Xwayland-in-SLR (the `CrGpuMain` GPU
> present path is broken; the SLR's libnvidia-egl-wayland can't find
> libwayland-server.so.0). Fixed by `--disable-gpu --in-process-gpu` on
> Battle.net.exe (commit `85b6a85`, env-gated via `DPAD_BATTLENET_CEF_ARGS`) →
> no CrGpuMain, the login UI renders solidly. **Image built + pushed (digest
> `sha256:e5ad5baaa7ea…`, supersedes `76e3cfaa22af`).** The deb's `postinst`
> warns `systemctl: command not found` (no systemd in the image) — harmless;
> the AppArmor profile symlink is laid down by the deb's data.tar regardless.
> **✅ DONE (code, commit `31f38fa`) — the partial build-time prefix prebake**
> (STORES-PLAN §7/§10 piece 2 + §18.4.1): the FULL build-time install is
> blocked (the Battle.net-Setup Chromium GUI won't complete headless — even
> `--disable-gpu` under Xvfb stalls before Battle.net.exe; needs a real
> display), so the prebake bakes everything UP TO the installer — `umu-run
> winetricks` prefix init + the ~657 MB Steam Linux Runtime + `Battle.net.config`
> + the downloaded `Battle.net-Setup.exe` at `/opt/dpadcloud/battlenet-prefix`
> (via the new `scripts/build-bootstrap-battlenet.sh`, Xvfb :9 software GL, no
> GPU needed). `battlenet-launch` copies that prefix to the session WINEPREFIX
> on first launch (~seconds) + runs only the installer (user clicks through it
> in the stream) → cuts the ~2-min winetricks + the SLR download from every
> first launch (most valuable for ephemeral sessions). Best-effort build script
> (no marker on failure → runtime falls back to full winetricks, no broken
> image). **⚠️ Build-time blocker:** the prebake layer needs `umu-run` →
> pressure-vessel → `bwrap` to create a user namespace, but a standard `docker
> build` container lacks the bwrap-nest privileges (those are runtime `docker
> run` flags, not build flags) → the build script degrades gracefully (no marker
> → runtime falls back to full winetricks, no broken image). To bake the
> prebake, the build must run privileged (`docker buildx build --allow
> security.insecure` via a builder with `--allow-insecure-entitlement
> security.insecure`; the default Docker-Desktop daemon rejects it + a custom
> builder doesn't share cache → a full rebuild). The prebake CODE is landed +
> correct + graceful — it bakes on a build host that allows the insecure
> entitlement; on a standard build it's a no-op (runtime fallback). The current
> Docker Hub image (`sha256:e5ad5baaa7ea…`) has the umu pivot + the `--disable-
> gpu` CEF fix but not the prebake. See STORES-PLAN §18.4 / §18.4.1.
> for the full record.
>
> **PREVIOUS (the live-test that motivated the pivot, kept as the record):** the
> `battlenet-launch` wrapper + launcher card shipped + were live-tested on an
> OVH Gravelines L4; the install stalls at the 32-bit Blizzard Update Agent
> under Wine 11's experimental new wow64 → the umu pivot (above) is the fix.**
> **The image on Docker Hub
> (`sha256:0091f28279c8`) has the OLD wrapper baked (the `5b01494` version with
> the wrong URL); the fixed wrapper is on `main` (`06feb00`) + will bake in at
> the umu rebuild.** **[Updated 2026-08-10:] the image was re-pushed with the
> FIXED wrapper baked — digest `sha256:166b76709e0c…` (the `06feb00` wrapper:
> the working URL + the pre-config); the earlier `sha256:0091f28279c8` (OLD wrapper,
> wrong URL) is superseded.** The live test VM (still up, ~€0.75/hr) has the fixed
> wrapper patched in via `docker cp` (a re-provision would pull the new image).
>
> **2026-08-11 session (latest) — UpCloud (Helsinki) re-validated on the `gst-wayland-display` compositor; `DPAD_SKIP_DRIVER_SWAP`/`DPAD_SKIP_MODESET` probe knobs shipped.** (container-gaming `8b39a27` on `main` + cloud `8b973fc`.)
>
> - **Probe 1 (skip the swap, shipped 595):** the `gst-wayland-display` compositor crashes with the SAME failure as Scaleway's `-580-server` variant — `libEGL warning: pci id ... 10de:27b8, driver (null)` → `egl: failed to create dri2 screen` → `[EGL] NOT_INITIALIZED eglInitialize: DRI2: failed to load driver` → `Failed to create EGLDisplay: InitFailed(NotInitialized)` → `Panicked: called Result::unwrap() on an Err value: RecvError`. Mesa EGL can't match the L4 on 595 → the compositor panics on every peer connect → selkies crash-loops. **595 is unusable for the wayland-display compositor (not just flicker — it crashes EGL init) → the 595→580 downgrade is MANDATORY on UpCloud on both compositors.**
> - **Probe 2 (after the swap, open-580 580.178.04):** the compositor EGL-inits clean — `CUDA initialization successful` → `Successfully selected EGL platform: PLATFORM_DEVICE_EXT` → `EGL Initialized (1.5)` → `GL Version: "OpenGL ES 3.2 NVIDIA 580.178.04"` → `GL Renderer: "NVIDIA L4/PCIe/SSE2"` → `EGL hardware-acceleration enabled` → `Listening on wayland socket. socket_name="wayland-1"`. On peer connect: `Compositor socket wayland-1 appeared (peer connected) — launching wayland client (DPAD_WAYLAND_CLIENT=sway) -- /opt/dpadcloud/launcher-shell`; the SDP carries `m=video`; sway + the dpad-launcher picker render + stream. **User-confirmed: image AND sound work** (over HTTPS via a temp Caddy reverse-proxy route `upcloud-probe.dpadplay.com`). UpCloud is re-validated on the wayland path (the prior 2026-07-30 validation was gamescope-headless). Swap ~4-5 min (faster than the old 6-10 min estimate).
> - **Shipped (container-gaming `8b39a27`):** `DPAD_SKIP_DRIVER_SWAP` + `DPAD_SKIP_MODESET` probe knobs in `vm-bootstrap.sh` (default off → zero regression). Setting either in `/etc/environment` before `vm-bootstrap.sh install` skips `ensure_driver_580` / `ensure_modeset` so the SHIPPED driver/modeset stays — for testing whether a given shipped driver works for the compositor's EGL/GBM glamor without the swap. Used here to prove 595 crashes the compositor (the swap is mandatory, not avoidable).
> - **Browser-test gotcha (for direct-IP probes): WebRTC needs HTTPS (a secure context).** The direct `http://<vm-ip>:16100` URL loads the Selkies page + the signaling peer registers, but the WebRTC peer never establishes (`SESSION 1`/`SESSION 3` loop, no `on_session` → the compositor never starts) because `RTCPeerConnection` is gated on a secure context. Use a temp named-site Caddy route on the VPS (`<probe>.dpadplay.com { reverse_proxy <vm-ip>:16100 }` — the `*.dpadplay.com` wildcard DNS + a normal LE cert, NOT the on-demand `:443` catch-all) + `docker compose up -d --force-recreate caddy` for a direct-IP probe; remove after.
> - **All 5 providers are now re-validated on the `gst-wayland-display` compositor path** (Helsinki/Gravelines/Des Moines/Quebec/Paris). The probe VM was torn down (0 UpCloud servers/storages, no orphan).
>

> **2026-08-11 session (later) — Scaleway (Paris) `gst-wayland-display` VALIDATED end-to-end + the `start_cursor_monitor` latent bug FIXED + the `dpad_input_patch.py` bind-mount hotfix path WIRED + the cloud default FLIPPED to the wayland path.** (container-gaming `de1f40f` on `main` + cloud `5297f1f` deployed live.)
>
> - **Scaleway `-580-server` → open swap confirmed required for the `gst-wayland-display` compositor too** (not just gamescope-headless). Empirical probe on a fresh Paris L4 with the swap SKIPPED (`DPAD_SKIP_DRIVER_SWAP=1`+`DPAD_SKIP_MODESET=1` patched into vm-bootstrap): the compositor EGL-inits off the render node BUT crashes `driver (null)`/`failed to create dri2 screen` (the §5 failure) → segfault → "connection error". After the swap (purge `-580-server` → `nvidia-driver-580-open` + modeset=Y + reboot): compositor EGL-inits clean (`GL Renderer: NVIDIA L4`, `EGL hardware-acceleration enabled`), `m=video:9` negotiated, sway + the dpad-launcher picker render, image + audio work. **The swap is ~2 min** (the DKMS build was quick here, not the old 12-18 min estimate). SSH survived the reboot (the IAM-key fix `65cdeba`). See `cloud/docs/STATUS.md` (the 2026-08-11 Scaleway note at the top) + `WAYLAND-ARCHITECTURE.md` (the §16.7 banner updated).
> - **`start_cursor_monitor` latent bug FIXED** (`scripts/dpad_input_patch.py`, `de1f40f`). The §17.2 lazy-XTest-input fix patched `send_x11_keypress`/`send_mouse` to tolerate `self.xdisplay=None` while sway's Xwayland `:0` isn't up (the inverted boot), but NOT selkies' own `start_cursor_monitor` — which derefs `self.xdisplay.has_extension('XFIXES')` at startup → a logged thread `AttributeError` (benign — selkies survives, stream works — but the server-side cursor monitor was dead on the wayland path). Fix: a bounded wait-for-`:0` guard that then calls the original → the cursor monitor now starts (`Found XFIXES version 4.0` + `watching for cursor changes`). A runtime cursor-watch-loop display-death crash (`webrtc_input.py:471 pending_events`) remains a pre-existing benign thread exception (hardening is a later polish).
> - **`dpad_input_patch.py` bind-mount hotfix path WIRED** (`de1f40f`) so the guard ships to EXISTING (pre-bake) images without a Docker Hub rebuild: `vm-bootstrap.sh` `ensure_image` fetches `scripts/dpad_input_patch.py` to `/opt/dpadcloud/dpad_input_patch.py` (alongside `entrypoint.sh`/`evdev_bridge.py`/`extract-nvrtc.sh`) + `scripts/dpad-launch-session` bind-mounts it over `/usr/local/lib/python3.12/dist-packages/dpad_input_patch.py` when present. (The §17.4 follow-up — closes the gap where the entrypoint bind-mount hotfix path existed but `dpad_input_patch.py` had no hotfix path.)
> - **Cloud default FLIPPED to the wayland path** (cloud `5297f1f`, deployed): worker env `DPAD_COMPOSITOR=wayland-display` + `DPAD_WAYLAND_CLIENT=sway` + `DPAD_STORE_SHELL=picker` + the worker writes `DPAD_COMPOSITOR`/`DPAD_WAYLAND_CLIENT` to `/etc/environment` at bootstrap. This was a real fix — the deployed default was already `DPAD_STORE_SHELL=picker` but `DPAD_COMPOSITOR` was unset → gamescope-headless, which CAN'T capture the Electron picker (§17.3) → no video. The probe VM was torn down (0 Scaleway orphans). The real worker-managed Paris session (full control-plane test) is deferred.
>
> **2026-08-11 session — per-provider cold-boot optimization (OVH + Hyperstack)
> + 3 vm-bootstrap fixes shipped. The OVH proprietary-580 swap is SKIPPED
> (it was never needed); Hyperstack's 3 stacked bootstrap bugs are fixed.**
>
> - **OVH: the plain DESKTOP proprietary `nvidia-driver-580` works for BOTH
>   compositors — the swap is skipped.** Empirically validated on a fresh GRA11
>   l4-90 (580.159.03, license: NVIDIA): gamescope-headless + Steam (frame mean
>   38.4/255) AND wayland-display + sway + dpad-launcher picker (compositor
>   EGL-inits off /dev/dri/renderD128, sway stable, picker renders + captures,
>   umu/Battle.net prefix init runs). The §5 note below ("gamescope does NOT
>   support the NVIDIA proprietary driver") + the §16.6 "OVH plain must swap"
>   claim are DISPROVEN for the DESKTOP build — they're true ONLY for the
>   `-580-server` SERVER build (Scaleway, mean 0.3/255). The real distinction is
>   the driver BUILD, not proprietary-vs-open per se. Fix shipped (`c00784a`):
>   `ensure_driver_580` keeps the plain desktop proprietary 580 (return 0, no
>   swap, no reboot); only the `-580-server` branch still swaps. **OVH cold boot
>   ~12-18 min → ~6.2 min, no reboot.**
> - **Hyperstack: 3 fixes shipped + R570-open works for both compositors.**
>   R570-open (570.195.03, `Dual MIT/GPL`) needs NO swap (the `*` case keeps it);
>   validated gamescope-headless (mean 38.6/255) + wayland+picker (image+audio).
>   Three stacked bugs had broken Hyperstack in production (never reached
>   vm-ready / the worker's getVm crashed):
>   1. **Modeset reboot loop** (`6028238`) — the R570 image ships
>      `nvidia-graphics-drivers-kms.conf` with `modeset=0`, overriding our
>      `modeset=Y` on boot (lexical order) → ~30s reboot loop. Fix: `ensure_modeset`
>      neutralizes any `nvidia_drm modeset=0` in modprobe.d + update-initramfs.
>   2. **`boot disk too small for XFS Docker store (95 GB)` FATAL** (`fcab859`) —
>      the n3-L40x1 root is ~95 GB < the old 120 GB floor. Fix: floor 120→30 GB +
>      adaptive headroom (12 GB on roots <200 GB) → 83 GB XFS, cap enforces.
>   3. (cloud-side) **Hyperstack adapter `getVm` crashed on the `{instance:...}`
>      response shape** (cloud `911162f`, deployed) — read `r.instance` first.
>      Also the adapter `sshUsername:'root'` is wrong (the R570 image forces
>      `ubuntu`) — a follow-up adapter fix.
>   - **Hyperstack cold boot now ~4-5 min** (build ~seconds + one modeset reboot
>     ~1.5 min + bootstrap ~130s + container ~50s). The modeset reboot is the one
>     unavoidable Hyperstack cost (the image ships modeset=0).
> - **Snapshot/custom-image route: REJECTED on OVH (net loss).** A 29.44 GB
>   private snapshot booted in ~11+ min vs the curated v580 image's ~3.5 min (OVH
>   copies the private snapshot; the curated public image is pre-staged). The
>   ~80s bootstrap savings is dwarfed by the ~7+ min build increase. The snapshot
>   route only wins where build-from-snapshot is fast relative to the bootstrap
>   it saves — UNTESTED on UpCloud/Scaleway (where the required swap/downgrade is
>   ~6-10 min, so a custom image with open-580 baked could still win).
> - **Shipped this session:** container-gaming `c00784a` (OVH swap-skip),
>   `6028238` (modeset-loop), `fcab859` (XFS floor/headroom); cloud `911162f`
>   (hyperstack getVm) + deployed. All vm-bootstrap fixes ship via the GitHub-fetch
>   (no image rebuild).
> - **Next (new chat):** MassedCompute (image 184 driver probe), Scaleway
>   (`-580-server` swap required — custom-image lever), UpCloud (595 downgrade
>   required — custom-image with open-580 baked).
>
> **2026-08-10 session — the dpad-launcher Electron store-picker shell replaces
> lutris-gamepad-ui as the session shell (`DPAD_STORE_SHELL=picker`).** Lutris is
> a *library aggregator* (it imports installed games via each store's
> manifests) → a fresh VM showed "no games found" until each store was logged in
> + synced. The dpad-launcher is a *store launcher* — a 10-foot front door that
> spawns the installed store clients (Steam available; Battle.net/Epic/GOG/EA/
> Ubisoft "coming soon" cards). It's the Option-B1 custom picker from
> STORES-PLAN §1 (Lutris was B2; the new compositor retired the §17.3 Electron
> capture blocker that made Lutris "the wrong shape", so a custom picker is now
> the simpler, owned-UX choice). See `launcher/README.md`.
>
> - **Gamepad via SDL3/koffi** (ported from lutris-gamepad-ui's `sdl_manager`)
>   — the Web Gamepad API does NOT see the mknod'd `/dev/input/jsN` pads
>   in-container (validated: dpad didn't work via the Web API; works via SDL3).
>   The main process polls SDL3 + ships the state to the renderer over IPC.
> - **SIGTRAP isolation result (retires the §6 #9 / §16.9 "SDL3 is the
>   trigger" hypothesis):** A/B'd SDL3 ON vs OFF — both crash **identically**.
>   SDL3 is NOT the trigger. The crash is the **wlroots 0.17.1 keyboard-group-
>   destroy assert** during sway's *shutdown*, triggered by compositor teardown
>   on **peer disconnect** (browser refresh / network blip): selkies tears down
>   the pipeline → `waylanddisplaysrc` socket closes → sway gets "failed to
>   read Wayland events: Broken pipe" → sway shuts down → removes the
>   compositor's `wayland-pointer/touch/keyboard-seat-0` devices → "Destroying
>   empty keyboard group" → wlroots aborts (SIGTRAP). It **self-heals** (~20s
>   stall; the entrypoint health loop relaunches sway on the new compositor
>   socket). NOT a hard blocker. Hardening (a wlroots bump or keeping the
>   compositor alive across peer disconnect) is an open follow-up.
> - **Shipped:** `launcher/` (Electron app, graphite6 palette from the live
>   site, real brand SVG logos bundled), `scripts/launcher-shell` (the
>   wrapper), the `DPAD_STORE_SHELL=picker` branch in `entrypoint.sh` (both the
>   wayland-display + gamescope-headless paths), `scripts/hold-peer.py` (the
>   SIGTRAP-isolation probe), the `lutris-shell` SDL3 env-override
>   (`DPAD_LUTRIS_SDL3`). Built + pushed as `forcespt/dpadcloud-launcher:0.1.0`
>   (a FROM-scratch file-bundle image holding the Linux Electron AppDir at
>   `/opt/dpadcloud/launcher`), then **baked into `:dpad-SteamOS`** via
>   `COPY --from=forcespt/dpadcloud-launcher:0.1.0` (Dockerfile vast-vm stage).
>   The `:dpad-SteamOS` image rebuilt + pushed (digest `sha256:1445c8d5…`).
> - **Live-validated on an OVH Gravelines L4** (`DPAD_STORE_SHELL=picker`, baked
>   image, no bind-mounts): renders, gamepad navigates (d-pad/stick + A launch +
>   B/Esc cancel), the launch overlay (logo + spinner, B/Esc dismiss), Steam
>   launches from the card, survives sway restarts/refresh.
> - **Fullscreen-after-store-quit:** the launcher never dies — on window
>   'closed' it recreates the window (sway's `for_window` re-fullscreens the
>   re-map); on the launched store's exit it destroys the window to force that
>   recreate (recovers if the store's XWayland teardown destabilized it +
>   re-fullscreens the demoted case). sway `default_border none` removes the
>   blue focused-border flash during the brief windowed phase.
> - **Open:** the other stores (Epic/GOG/Battle.net "coming soon" — need
>   `legendary`/`gogdl`/`protobuf` baked + the launcher wiring to launch them;
>   Battle.net via Proton, Epic/GOG via legendary/gogdl); the sway SIGTRAP
>   hardening; the **cloud flip** (`DPAD_STORE_SHELL: picker` in the worker
>   env, now that the image is baked — a `cloud` repo change + redeploy).
>
> **2026-08-08 — the multi-store blocker is being solved at the architecture
> level, not the Lutris-flag level.** See **`WAYLAND-ARCHITECTURE.md`** — the
> decision to adopt `gst-wayland-display` (a Smithay micro-compositor) as the
> compositor + capture layer, with gamescope demoted to an XWayland-providing
> *client*. Retires §6 #11 (Electron renders directly into the new compositor)
> + retires §6 #12 (libSDL3) via the `sdl3-builder` stage now that Lutris is the
> primary shell. The §6 #10 NVRTC
> fix is likely moot on the new CUDAMemory path (kept as fallback). Phased
> plan (probe → spike → shell → store launchers → flip default → inputtino).
>
> **2026-08-08 session (libSDL3 bake + WAYLAND-ARCHITECTURE decision + OVH live
> validation): the §17.4 gamepad-nav fix is SHIPPED + live-validated; the §17.3
> probe confirms the `gst-wayland-display` pivot is strictly necessary.**
> - **Built + pushed** a new `:dpad-SteamOS` image (Docker Hub digest
>   `sha256:b403937ba97ddea54856502cf2b9d93119424bb1885175c05db4d541ffe8c0b5`)
>   with a new `sdl3-builder` Dockerfile stage: SDL3 3.2.28 from source, minimal
>   backends (joystick/hidapi/events; video/audio/render OFF;
>   `SDL_UNIX_CONSOLE_BUILD=ON` skips the no-X11/Wayland FATAL), installed as
>   `libSDL3.so.0` (SDL3's SOVERSION is 0, deliberate) → fixes §6 #12 / §17.4:
>   `lutris-gamepad-ui`'s koffi `dlopen("libSDL3.so.0")` now resolves (it lived
>   only in Steam's runtime dirs before → gamepad wouldn't navigate the Lutris
>   UI). Committed to `main` as `af5bda6` (Dockerfile + WAYLAND-ARCHITECTURE.md +
>   the §6/§17 cross-refs).
> - **Provisioned an OVH Gravelines L4 directly via the OVH API** (NOT the
>   website — `createOvhAdapter` from the worker container's env; VM
>   `188.165.71.21`, driver 580.159.03, image `b403937b…`). `vm-bootstrap.sh
>   install` → `DPAD_VM_READY`; manual `docker run -e DPAD_STORE_SHELL=lutris …`.
> - **§17.4 FIXED (live):** `lutris-shell.log` → `[sdl_manager] SDL3
>   initialized! libSDL3.so.0` (vs the old `Unable to load libSDL3.so.0`).
>   `lutris-gamepad-ui.bin` running + the Lutris wrapper querying the library.
> - **§17.3 probe (§8 step 1) RUN — `DPAD_LUTRIS_DISABLE_GPU=1` did NOT fix
>   it:** browser still "Waiting for stream"; gamescope's PipeWire stream
>   oscillated paused↔streaming + the `gamescope:capture_1` node was active,
>   but Selkies' `pipewiresrc → webrtcbin` produced no video track (a parallel
>   `gst-launch pipewiresrc` grab captured 0 frames in 14s). → the bug is
>   fundamental to gamescope-headless + Electron, NOT a GPU-init issue → **the
>   `gst-wayland-display` pivot (§8 step 2) is strictly necessary.**
> - **VM torn down** (`adapter.destroyVm`; `[]` instances, no orphan, billing
>   stopped). The spike will rebuild the image (add `wayland-display-builder`)
>   + provision a fresh OVH L4.
> - **Next (§8 step 2, the spike):** build `gst-wayland-display` (Rust + cargo-c
>   + Smithay, `cuda` feature) + `gst-cuda-1.0` + `inputtino` from source; wire
>   `DPAD_COMPOSITOR=wayland-display` in the entrypoint (default stays
>   `gamescope` = no regression) with `waylanddisplaysrc ! CUDAMemory ! nvh264enc
>   ! webrtcbin`; rebuild + push; fresh OVH L4; validate the Lutris shell
>   **streams video** (retires §17.3) + N-on-N (2 compositors on 1 GPU) +
>   CUDAMemory zero-copy + NVRTC-error=0-without-extraction. With libSDL3
>   already shipped, the Lutris shell will then have BOTH video + gamepad nav.
>
> **2026-08-04 session (gamepad): the evdev gamepad path — VALIDATED
> END-TO-END with a real controller on OVH Gravelines L4 (Steam Big Picture
> navigates); two blocking bugs found + fixed; shipped in the 2026-08-05 image
> rebuild + push (see the 2026-08-05 note below + §6 #9).**
> See §6 #9 + `scripts/gamepad-evdev-fallback/README.md`. The 2026-08-05 work
> wired + gated the path (`DPAD_GAMEPAD_INTERPOSER=evdev`, default OFF) +
> validated the dispatch (feeder → `evdev_bridge.py` → interposer → evclient)
> + the boot wiring. This session did the real-controller test (the last
> pending item) + found TWO bugs that made Steam see zero gamepads:
> **(a) i386 fake-libudev wrong SONAME** — the 32-bit fake was built
> `-soname libudev_x86.so.1` instead of `libudev.so.1`; Steam's 32-bit binary
> does `dlopen("libudev.so.1")`+`dlsym` (SDL3), so the wrong soname made it
> load the REAL libudev from the steam runtime → real enumeration over `/sys`
> (the fake nodes have no `/sys` backing) → 0 devices. Fix: i386
> `-soname libudev.so.1` (`fake-udev/Makefile`). **(b) bridge event sockets
> root-owned mode 755** — the bridge runs as root, Steam as `dpad`, so the
> interposer got `EACCES` connecting to `/tmp/selkies_event100N.sock`. Fix:
> `evdev_bridge.py` `os.chmod(self.ev_sock, 0o777)`. With both fixes, `JS_LOG=1`
> shows SDL3 calling the fake `udev_enumerate_*` (115 calls) → discovering the 8
> nodes → the interposer `open()`s `event1000` → `EVIOCGID -> ven:0x045e
> prod:0x028e` → Steam's SDL3 accepts the 4 X-Box 360 pads; a real browser
> controller then navigated Big Picture (bridge `js client connected` →
> `translated ... input_events` → interposer `SOCKET_READ_OK read 16 bytes`).
> **Both fixes are baked in the image** (the `.so` in `interposer-builder`, the
> bridge via `Dockerfile` COPY) → **shipped via the 2026-08-05 image rebuild +
> Docker Hub push** (the `.so` soname is set at link time, not hotfixable; the
> bridge is now ALSO on the entrypoint bind-mount hotfix path — `vm-bootstrap` fetches
> `evdev_bridge.py` + `dpad-launch-session` bind-mounts it — so future bridge
> fixes ship without a rebuild, but the soname fix still needs the rebuild).
> Not urgent: evdev is opt-in (default OFF), classic path unaffected. **Remaining
> (optional, after the rebuild):** wire the env into the control plane (cloud
> `apps/worker/src/index.ts:711-726`: add `echo "DPAD_GAMEPAD_INTERPOSER=evdev"
> >> /etc/environment` to the bootstrap) + redeploy the worker.
> **Ops note:** a stale dead-VM loop occurred (an OVH VM was deleted directly on
> the OVH dashboard; the control plane kept reusing the stale `ready`
> `warm_pool_vms` record → sessions failed in a loop) — fixed by forcing that
> row to `destroyed` in the DB; the control plane has no liveness-check for
> provider-deleted VMs (a gap, not yet fixed).
>
> **2026-08-05 session (image rebuilt + pushed): the public `:dpad-SteamOS`
> image now bakes the input + evdev fixes.** The blocked owner rebuild was
> done + pushed to Docker Hub, so the following are now live on a fresh
> `docker pull` (no hotfix overlay needed):
> - **Mouse scroll direction** (`dpad_input_patch.py`): the v1.6.2
>   scroll-constant inversion is corrected (XTest `MOUSE_SCROLL_UP→button 5`,
>   `MOUSE_SCROLL_DOWN→button 4`) — see §4.
> - **FPS aim / Gaming-mode toggle** (`patch_gst_web_cursors.sh`): a
>   floating bottom-right button + `Ctrl+Shift+G` toggle pointer lock for
>   relative mouse; default controllable via `DPAD_DEFAULT_GAMING_MODE`.
> - **evdev gamepad path** (§6 #9): the i386 fake-libudev SONAME fix + the
>   `evdev_bridge.py` socket-chmod fix are baked — evdev now works on the
>   public image (was: "still has both bugs on the current public image").
> The `DPAD_INPUT_HOTFIX=1` entrypoint overlay is now a redundant no-op (it
> re-fetches the same content from `main`); set `DPAD_INPUT_HOTFIX=0` to pin to
> the baked copies and avoid a `main`-regression overwriting them. The
> `:dpad-SteamOS-L4` experimental tag (§6 #2) was NOT part of this push — still
> pending (not a v2-flow blocker; the control plane uses `:dpad-SteamOS` for L4).

## 1. The images

One multi-stage Dockerfile; `--target` selects the image. v2 uses the
`:dpad-SteamOS` family exclusively (full-VM providers with userns → full
Steam).

| Tag | Target | CUDA | Use |
|---|---|---|---|
| `:dpad-SteamOS` | `vast-vm` | 12.5.1 | **Ada** (Turing/Ampere/Ada: RTX 20/30/40, GTX 16, T4, A10, A40, L4, L40S, RTX 6000 Ada). The default. |
| `:dpad-SteamOS-rtx50` | `vast-vm` | 12.8.1 | **Blackwell** (RTX 50, RTX PRO 6000 Blackwell; sm_120/121). Driver ≥570. |
| `:dpad-SteamOS-L4` | `vast-vm` | 12.5.1 | L4 oversubscription variant: gamescope **3.16.25** + the `drmProps` headless patch + libpixman 0.46.4. **Built locally on the UpCloud box; NOT pushed to Docker Hub** (owner step — public tag is the stale 3.16.19 image). |

**Build:**
```bash
docker build --target vast-vm -t forcespt/dpadcloud-gaming:dpad-SteamOS .
docker build --target vast-vm --build-arg CUDA_VERSION=12.8.1 --build-arg CUDA_PKG=12-8 \
  -t forcespt/dpadcloud-gaming:dpad-SteamOS-rtx50 .
```
Build-time Steam pre-bootstrap (`scripts/build-bootstrap-steam.sh`) bakes
`ubuntu12_64/steamwebhelper` in → a fresh boot skips the ~3–4 min Steam
download (cold boot ~50s). The `gamescope-builder` stage clones the gamescope
**3.16.25** tag + applies `scripts/gamescope-headless-drmprops.patch`.

**Deprecated (Vast dropped 2026-07-28):** `:dpad-heroic` / `:dpad-heroic-rtx50`
(Vast Docker, no userns → Heroic storefront via the `umu_run.py` → Proton-direct
bypass) and the headless `steamcmd` + `dpad-launch` path. v2 is SteamOS-only on
full-root VMs. See §7.

## 2. The pipeline (gamescope headless)

```
gamescope --backend headless -e -W 1920 -H 1080 -- steam -gamepadui
   │  renders Steam on the GPU via Vulkan/gamescope-WSI, NO DRM master
   │  → PipeWire video node (BGRx 1920x1080, modifier 0 = system memory)
   │  → Xwayland :0 (Steam's CEF/X11 UI runs here)
   ▼
[Selkies capture — pipewiresrc direct, NO Xvfb :2 / ximagesrc bridge]
   pipewiresrc(target-object=gamescope, always-copy=True) → videorate (FPS throttle)
   → cudaupload → cudaconvert(BGRx→NV12) → nvh264enc → webrtcbin → coturn → browser
[Audio]  pipewire-pulse null sink (dummy.monitor) → Selkies pulsesrc
[Input]  browser WebRTC datachannel → Selkies → xtest.fake_input on :0 → Xwayland → Steam
[Gamepad] browser gamepad → Selkies → /tmp/selkies_jsN.sock → root watcher mknods /dev/input/jsN
          → v1.6.2 joystick interposer (LD_PRELOAD, open() redirect) → SDL3 classic → Steam Big Picture
```

`gamescope --backend headless` is the multi-tenant enabler: it renders via
Vulkan/gamescope-WSI with **no DRM master** → no nvidia-modeset singleton →
**N sessions on N GPUs in one VM** (validated 2-GPU + 4-GPU). Capture is
`pipewiresrc` (system-memory BGRx, not true dmabuf zero-copy, but the old `:2`
Xvfb round-trip + CPU `videoconvert` passes are gone). `DPAD_VIDEO_SRC=ximagesrc`
reverts to the `:2` bridge fallback.

## 3. Validated state

- **1:1 + N-on-N:** 1-GPU (RTX 3060/580), 2-GPU + 4-GPU (RTX 5060 Ti, sm_120),
  each container sees exactly 1 GPU (CDI `NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=i`).
- **Gamepad in Steam Big Picture:** D-pad/sticks/A navigate; the 6-layer fix is
  baked (§4). Validated with a real controller.
- **Cold boot ~50s** to the stream URL (was 172s before the targeted-chown fix).
- **RTX 50 / Blackwell (cuda 13.3):** RTX 5080/5090 stream with the GLVND bake
  (no zink fallback). `:dpad-SteamOS-rtx50` selected per `compute_cap ≥ 12`.
- **Stream quality:** Selkies `nvh264enc` (hardware) on all tested drivers
  (580/595/610). Built-in Opus inband FEC + ULP_RED video FEC + NACK rtx
  (gated on `DPAD_AUDIO_PACKETLOSS` / `DPAD_VIDEO_PACKETLOSS`).
- **MPS oversubscription (N-on-1) — 2:1 validated live 2026-07-30 (UpCloud L4):**
  two Casual sessions on one L4 via the host MPS daemon — 2nd session reused the
  ready VM's slot 1 (no boot), both containers `DPAD_READY`, both `gamescope`
  processes on the GPU via `nvidia-cuda-mps-server`, each with its own 200 GB
  ephemeral cap, Steam Storage showed 200 GB on both. (3:1 + active-gameplay
  frame-time still open — see `cloud/docs/STATUS.md` §8.)
- **Persistent-volume Storage display — validated live 2026-08-01 (UpCloud L4):**
  a 50 GB persistent volume → Steam → Settings → Storage shows **50 GB** (was
  647 GB — the install root was on the uncapped rootfs). Fix: the Steam install
  root now lives ON the volume (`~/.steam/debian-installation` →
  `<vol>/steam-install`, client copied once). See §4 + `cloud/docs/STATUS.md`
  §8 #1b. **Volume SURVIVAL + Steam auto-login validated end-to-end (twice):**
  an installed game survived End+relaunch (download-once) + Steam Guard
  "remember this device" persisted → silent auto-login. The whole Steam state
  (client+games+login) lives on the volume.

## 4. The baked-in fixes (don't re-discover)

| Fix | Where | What |
|---|---|---|
| **gamescope `drmProps` headless patch** | `scripts/gamescope-headless-drmprops.patch` (gamescope-builder stage) | gamescope's `VkPhysicalDeviceDrmPropertiesEXT` query returns zeros on these configs → "physical device has no primary node" → headless backend aborts. Patch relaxes the headless `!hasPrimary` abort to a warning + adds a `/dev/dri/renderD*` scan fallback when `hasRender` is false. Required on every host (driver-agnostic). Upstream PR #2073 only covers the `!hasDrmProps` branch, not ours. |
| **Vulkan ICD → `libEGL_nvidia.so.0`** | `entrypoint.sh` (after install-display-drivers) | Driver 595's `libGLX_nvidia.so.0` Vulkan ICD fails `vkCreateInstance` in a headless container (no X server). Rewrites the ICD JSON to `libEGL_nvidia.so.0` (NVIDIA's headless recommendation). No-op on 580 (GLX ICD works). |
| **Render-node GID auto-add** | `entrypoint.sh` (early, before gamescope) | Some hosts map the nvidia render node to a GID that's neither `render` nor `video` in the container (UpCloud = 993/`polkitd`) → `dpad` EACCES opening `/dev/dri/renderD128`. Detects the owning GID + `usermod -aG` dpad to it. Host-agnostic. |
| **GLVND-neutral `libglx.so` bake** | Dockerfile `base` stage | nvidia 610.x ships only `libglxserver_nvidia.so`; Mesa's `libglx.so` self-registers swrast for screen 0 first → GL falls to zink → `ximagesrc` can't capture → no stream (worst on cuda≥13.3 Blackwell). Bakes xserver-xorg-core's neutral `libglx.so` into the nvidia ModulePath + entrypoint hides Mesa's on the nvidia-DDX path. |
| **NVENC #1249 flexgrip interposer** | `scripts/nvenc_fix.c` → `libnvenc_fix.so`, wired in `setup_nvenc_fix()` | Driver 570–609: NVENC peer-inits with unmounted host GPUs → `NvEncOpenEncodeSessionEx error 2`. The interposer filters `GET_ATTACHED_IDS` to mounted GPUs (full-PCI-address match, lowercased — slots with hex letters B/D/F…). Auto-enabled on 570..609 when host GPU count > mounted. Single-GPU hosts immune on any driver. |
| **Gamepad 6-layer chain** | Dockerfile + `entrypoint.sh` `start_gamescope_session` | (1) interposer wired into the gamescope path; (2) `SDL_JOYSTICK_LINUX_CLASSIC=1` + `SDL_JOYSTICK_DEVICE=/dev/input/js0`; (3) root watcher mknods `/dev/input/jsN` on socket appear; (4) `SDL_JOYSTICK_DISABLE_UDEV=1` (ENUMERATION_FALLBACK hotplug); (5) `JSIOCGNAME` returns name length (source patch); (6) **both x86_64 AND i386 `.so` rebuilt** (`gcc-multilib`/`libc6-dev-i386`, fail loud — Steam's main binary is 32-bit). |
| **Targeted chown (no blanket `chown -R`)** | `entrypoint.sh` | A blanket `chown -R dpad:dpad /home/dpad` copy-ups all ~33k pre-baked files on overlayfs (no `metacopy`) → ~119s wasted. Use `find <dir> ! \( -user dpad -group dpad \) -exec chown dpad:dpad {} +` (skips already-owned). Cold boot 172s → 50s. **Never reintroduce `chown -R` over a large pre-baked dir.** |
| **Cursor: `--enable_cursors=true` + Gaming-mode pointer-lock toggle** | entrypoint + `patch_gst_web_cursors.sh` | gamescope headless doesn't composite the X cursor → the XFIXES CSS overlay is the only visible cursor; the web client's auto pointer-lock hides it. Fix: `--enable_cursors=true` (safe after the `dpad_input_patch.py` xfixes crash fix) + a `window.DPAD_POINTER_LOCK` gate in `/opt/gst-web/input.js` (default Desktop mode → absolute mouse + visible cursor for Steam UI). **FPS aim**: toggle Gaming mode with the floating bottom-right button or `Ctrl+Shift+G` (badge shows state) → click the stream to lock the pointer (relative mouse); `Esc` releases. The script **strips any prior DPAD shim block before re-injecting** (the image bake injects an earlier shim with the same marker; without stripping, the boot re-run would skip and the old shim — with `window.__dpad_pl_patched` set — would no-op the new one). Default controllable via `DPAD_DEFAULT_GAMING_MODE=1` (control plane can default Gaming mode on for keyboard/mouse tiers). |
| **Mouse scroll direction (v1.6.2 constant inversion)** | `dpad_input_patch.py` `send_mouse` | Selkies v1.6.2's scroll constants are inverted vs the physical wheel: the web client sets bit 4 for `deltaY<0` (wheel UP) + bit 3 for wheel DOWN, while the server maps bit 3→`MOUSE_SCROLL_UP` + bit 4→`MOUSE_SCROLL_DOWN`. Stock pynput cancels this with a flipped `dy` sign, but the XTest patch took the constant names literally → wheel-up produced screen-down (reversed). Fix: inject X button 5 for `MOUSE_SCROLL_UP` (wheel-DOWN→screen-DOWN) + button 4 for `MOUSE_SCROLL_DOWN` (wheel-UP→screen-UP). The button numbers look "backwards" on purpose — do NOT swap back. |
| **`unattended-upgrades` disabled (protects live sessions)** | `vm-bootstrap.sh` `ensure_no_auto_updates()` (runs FIRST) | Ubuntu's `apt-daily-upgrade.timer` ran `unattended-upgrades` mid-session, upgrading the kernel + libc6 + openssh; `needrestart` then issued `systemctl daemon-reexec` + restarted containerd/docker → every game container died exit 137 ~2 min after `DPAD_READY` (observed live 2026-07-30). Masks the apt timers + zeros `APT::Periodic::*` + sets `needrestart` to restart-mode=list (no auto-restart). |
| **CAP-PROBE corrected + FATAL verify** | `vm-bootstrap.sh` `ensure_docker_xfs_quota()` | The old `dd ... \| tail -3` dropped the `No space left on device` line (dd prints it BEFORE its summary) + `$?` was `tail`'s → a working cap falsely reported "NOT enforced." Now captures dd's full output + real exit; the verify is FATAL (`return 1`) so an uncapped ephemeral VM never ships. Also the docker drop-in `RequiresMountsFor` moved to `[Unit]` (was wrongly `[Service]`, ignored) + idempotency hardened (img + fstab entry) vs the daemon-reexec `findmnt` race. |
| **oversub cuInit forward-compat skip** | `entrypoint.sh` `configure_cuda()` | The forward-compat `cuInit(0)` test (loads the image's OLD compat `libcuda.so.555` against the newer 580 driver) **deadlocks under a 2nd concurrent MPS client** (`skb_wait_for_more_packet` on the MPS control socket) → the 2nd oversub session's boot stalled 7+ min, exceeding the launch deadline. Forward-compat is only needed when the IMAGE's CUDA is NEWER than the host max CUDA; now the test runs only then (`dpkg --compare-versions`) + is `timeout 20`-guarded. For our images (12.5/12.8 ≤ host 13.0) it's skipped → always the fast fallback path (slot-0 proved the fallback works). |
| **entrypoint bind-mount hotfix path** | `dpad-launch-session` + `vm-bootstrap.sh` `ensure_image()` | `dpad-launch-session` bind-mounts the host's `/opt/dpadcloud/entrypoint.sh` over the image's baked entrypoint (if present); `vm-bootstrap` fetches it fresh from repo `main` at bootstrap. Lets entrypoint hotfixes go live **WITHOUT an image rebuild + Docker Hub push** (the owner step that's blocked) — validated live (the cuInit fix shipped this way on the 2nd oversub session). Falls back to the baked entrypoint if the fetch/host file is absent. |
| **Steam install root ON the volume** (Settings→Storage shows the volume) | `entrypoint.sh` `setup_user_volume()` | Steam FORCES library "0" = the install root + reports `statvfs()` of that path's filesystem, so with the install root on the rootfs Storage showed the uncapped rootfs (~647 GB), not the 50 GB volume; pre-seeding `libraryfolders.vdf` `0`=volume does NOT stick (Steam overwrites it within ~2-3 min; on a fresh volume there's no Steam-generated `contentid` to preserve + Steam rejects contentid `0`). Fix: symlink `~/.steam/debian-installation` → `<vol>/steam-install` (copy the ~2.1 GB baked client to the volume once — fast-boot preserved; Steam auto-updates the volume's copy). Steam's forced `0`=install root now resolves to the volume → Storage shows the volume (validated live 2026-08-01: 50 GB volume → Storage shows 50 GB). Old top-level subpath layout is migrated into `steam-install/`. |
| **Volume device found by label/exclusion (not virtio letter)** | `dpad-launch-session` `mount_volume()` | The `virtio:N`→`/dev/vd<letter>` mapping is UNRELIABLE after a detach (the guest doesn't reuse a freed letter; observed vdb→vdc→vdd). Re-attach mounts by LABEL (`blkid -L dpadvol-<uuid8>`); first-attach finds the raw device by EXCLUSION (not boot disk / docker loop / mounted / `dpadvol-*`-labelled). The `virtio:N` arg is now just a hint. |
| **`stop` unmounts the volume** (no stale mount crash) | `dpad-launch-session` `stop()` | `stop` inspects the container's `/mnt/dpad-library` bind source before `docker rm`, then `umount`s it. The old `stop` left the host mount in place; once the control plane detached the volume it went STALE (I/O errors) + the next session's `mount_volume` reused it via `findmnt -T` → the install-root-on-volume read unreadable files → gamescope segfault (libtinfo/libpciaccess). |

## 5. Known limitations (accepted, don't chase)

- **Mild Steam-menu flicker on driver 580** (gamescope #1964) — menu/overlay
  transitions. Accepted (same on the Vast 3060/580 baseline). The fix is a host
  driver downgrade to 575 (not image-fixable). See
  `cloud/docs/DEPLOY-RUNBOOK.md`. **Severe whole-frame flicker on driver
  595** is a different bug — the host must downgrade 595 → R580 LTS (see §6 #1).
- **⚠️ NEW 2026-08-05 — headless gamescope renders a BLACK screen on the
  PROPRIETARY NVIDIA **`-580-server`** driver (the SERVER build); the OPEN variant
  is required.** ⚠️ **SUPERSEDED 2026-08-11 for the PLAIN DESKTOP proprietary
  build** (`nvidia-driver-580`, OVH) — the DESKTOP build's render-node EGL/GBM
  glamor works for BOTH compositors (validated: gamescope-headless mean 38.4/255
  + wayland-display + picker on OVH l4-90, 580.159.03, license: NVIDIA). The
  black screen is specific to the `-580-server` SERVER build (Scaleway), NOT the
  plain desktop build (OVH). The real distinction is the driver BUILD, not
  proprietary-vs-open per se. `ensure_driver_580` now swaps only the `-580-server`
  variant; the plain desktop proprietary 580 is kept (commit `c00784a`). The
  original §5 note below is kept as the Scaleway-`-server` record — read it with
  this correction.
  Confirmed on Scaleway Paris L4 (proprietary `580.126.20`, `nvidia-dkms-580-
  server`). Symptom: `vulkan: vkGetPhysicalDeviceFormatProperties2 returned zero
  modifiers for DRM format 0x38344241/0x38344258` → `libEGL warning: egl:
  failed to create dri2 screen` (`pci id 10de:27b8, driver (null)`) → `Refusing
  to try glamor on llvmpipe` → `EGL setup failed, disabling glamor` → `Failed
  to initialize glamor, falling back to sw` → Steam Big Picture's CEF (GL-
  based) composites a BLACK screen while audio plays. NVENC IS encoding (7%) —
  it's encoding black; captured gamescope PipeWire frames are near-pure-black
  (mean 0.3/255). The capture + encoder pipeline is fine; gamescope is
  faithfully compositing a black CEF output. **gamescope does NOT support the
  NVIDIA proprietary driver** (maintainer emersion, gamescope issue #255 —
  verbatim same log). The OPEN variant of R580 (`nvidia-driver-580-open`, what
  UpCloud runs successfully as `580.173.02-open`) works — its Mesa EGL/GBM
  glamor path works in headless. This is a proprietary-vs-open VARIANT issue,
  NOT a version issue (R580 LTS is the deliberate choice — longest support to
  Aug 2028; R595 causes severe L4 flicker; R610 is NFB; even the newest
  proprietary would have the same glamor failure). **Fix (Scaleway-gated,
  IMPLEMENTED + ✅ VALIDATED LIVE 2026-08-05 — commits `fbbd718` + `2b19ead`/
  `2647a18`/`487ceb5`; see `cloud/docs/STATUS.md` §4 #42 + the Paris session
  note):** `vm-bootstrap`'s `ensure_driver_580` detects the proprietary variant
  (`nvidia-dkms-580-server` present, no `nvidia-dkms-580-open`), PURGES the
  proprietary `-server` packages first (every installed package ending in
  `-580-server` — resolves the `nvidia-kernel-common-580` conflict that failed
  the reverted `1bb6f26` install), then `apt install nvidia-driver-580-open` +
  modeset=Y + reboot, FATAL on failure (the `bootstrap()` call site `|| return 1`s
  it). Gated on the proprietary variant (UpCloud is already open after its
  595→580 downgrade; OVH's pre-installed 580 is open + validated working → the
  gate skips it). LANDED with the Scaleway SSH-key fix (`cloud/docs/STATUS.md`
  §4 #41 — cloud commit `65cdeba`: the adapter's `ensureOrchestratorSshKey`
  registers the orchestrator key via the IAM API so `scw-fetch-ssh-keys` re-adds
  it on every boot; without it the driver-swap reboot would lock the worker out).
  A non-gated version of this swap was pushed (`1bb6f26`) then REVERTED
  (`3d5530c`) — main is back to the safe no-op-on-580 behavior; `fbbd718` is
  the gated, purge-first, FATAL successor. **Validation:** driver flipped
  proprietary `580.126.20` (`license: NVIDIA`) → open `580.178.04` (`license:
  Dual MIT/GPL`); SSH survived the reboot (Fix B); container `DPAD_READY
  encoder=nvh264enc` on the open driver; captured gamescope frame mean
  **37.64/255** (Steam Big Picture content) vs the proprietary **0.3/255** (pure
  black) — user confirmed not black + working. **3 extra driver-swap bugs were
  found + fixed during the validation** (all on `main`): the
  `has_proprietary_580`/`has_open_580` SIGPIPE-under-pipefail (`grep -qE` → 141;
  fix `grep -E >/dev/null`, `2b19ead`), the purge-list `$`-anchor-on-dpkg-line
  bug (empty purge → the conflict; fix extract-name-first, `2647a18`), + the
  CDI-spec-staleness-after-swap bug (`ensure_nct` ran the GPU check before
  regenerating CDI → stale `libcuda.so.580.126.20` mount; fix
  regen-CDI-before-check, `487ceb5`).
- **Browser refresh occasionally "Waiting for stream"** — a Selkies 1.6.2
  WebRTC reconnect race. Self-heals on a 2nd refresh; a fresh incognito tab
  always works. **A restart-on-disconnect supervisor now auto-relaunches
  `selkies-gstreamer` when it dies while gamescope is up** (`relaunch_selkies()`
  in the health loop — §6 #7) so the browser reconnects without a manual
  refresh; **validated live 2026-08-05** (OVH Gravelines L4: killed
  `selkies-gstreamer` in a live container → the health loop relaunched it as a
  fresh process, same encoder, within ~20s; gamescope untouched, browser
  reconnects).
- **Steam "no internet" icon + ~70s CM bounce** — Steam's CM servers bounce the
  datacenter IP. Login/install/play all work; cosmetic, not fixable from the image.
- **NVRTC "invalid value for --gpu-architecture" on the L4 (sm_89) AND Blackwell
  (sm_120) — NOT non-fatal; it BLOCKS video.** The bundled GStreamer ships a
  CUDA 11.4 `libnvrtc` that can't JIT for sm_89/sm_120 → `cudaconvert`'s NVRTC
  JIT fails → the video pipeline starts but produces NO capturable video (the
  "cubin fallback" doesn't yield usable frames). The **canonical fix** (from
  the official Selkies `selkies-gstreamer-entrypoint.sh`): extract a `libnvrtc`
  matching the host CUDA (capped to 12.9 for host CUDA≥13, GStreamer issue
  #4655) into `/opt/gstreamer/lib/x86_64-linux-gnu/`, replacing the bundled 11.4.
  **Validated live 2026-08-07** on Paris L4: extracted `libnvrtc 12.9.86` →
  `nvrtc: error` count → 0, video pipeline clean, + the **steam** shell then
  streams video (browser sees the image). See `STORES-PLAN.md` §17.2 + §6 #10.
  **NOT yet baked into the repo** (next step: add the extraction block to
  `entrypoint.sh`/Dockerfile + rebuild).
- **`webrtcnice … failed to resolve "<uuid>.local"`** — Chrome's mDNS `.local`
  ICE candidates the container can't resolve; the TURN relay handles it.
- **Selkies launch loop `[: 0\n0: integer expression expected`** (`entrypoint.sh`
  ~line 497, `start_gamescope_stream`) — cosmetic. The `err_before`/`err_after`
  counters are `$(grep -ac … || echo 0)`; when there are 0 NVENC failures (the
  common case) `grep -ac` prints `0` AND exits 1, so `|| echo 0` appends a
  second `0` → `0\n0` → the `[ … -gt … ]` errors. Harmless (the comparison
  fails → falls through to "Selkies running"); not from the evdev/supervisor
  work. One-line fix: drop the `|| echo 0` (or `grep -ac … | head -1`).

## 6. Open image-side items

1. **`vm-bootstrap` driver 595 → 580 auto-downgrade — DONE + validated live
   2026-07-30.** `ensure_driver_580` detected `595.58.03` on a fresh UpCloud
   AI/ML template → removed the pinning package → installed
   `nvidia-driver-580-open` → rebooted → the oneshot resumed with
   `580.173.02` (`nvidia-smi` confirmed). The full downgrade+reboot+resume path
   ran on a real v2 launch. (Was: REQUIRED for UpCloud L4 + MassedCompute L40S
   flicker-free streams — the AI/ML template + image 184 ship 595 → severe
   whole-frame flicker; see `cloud/docs/DEPLOY-RUNBOOK.md` §1.)
2. **Push `:dpad-SteamOS-L4` to Docker Hub** (owner step — the build box isn't
   logged in). The public tag is the stale 3.16.19 image; warm-pool/`docker
   pull` gets the wrong one. After pushing, re-enable the `dpadcloud-bootstrap`
   oneshot on the L4 box.
3. **`dpad-launch-session` ephemeral (`volumeId=none`) live validation** — the
   v2 ephemeral path (no `-v` bind, no `DPAD_VOLUME_MOUNT`). The script change
   is on `main`; validate on the first MassedCompute launch.
4. **`--storage-opt size=<N>g` ephemeral disk cap — DONE + validated live
   2026-07-30.** `vm-bootstrap.sh` `ensure_docker_xfs_quota()` moves `/var/lib/docker`
   onto an XFS-`pquota` loopback on the boot disk (`ftype=1` + `reflink=0`) +
   disables the containerd image store → legacy `overlay2`, which enforces
   `--storage-opt size`. `dpad-launch-session` caps ephemeral via
   `--storage-opt size=$DPAD_EPHEMERAL_DISK_GB` (cloud worker writes `=200`).
   Validated: a fresh Helsinki → Casual → no-storage container got
   `StorageOpt=map[size:200g]`, `df /` = `200G`, and Steam → Settings → Storage
   showed **200 GB / 198.23 GB free**. The CAP-PROBE is corrected + FATAL
   (see §4). (Was: plumbed but dormant; needed XFS pquota on the VM Docker store.)
5. **Steam-login persistence — DONE + validated 2026-08-01.** The linchpin of
   the v2 "your cloud PC" UX. Achieved via the install-root-on-volume (§4): the
   Steam login config (`config.vdf`/`loginusers.vdf` + the Steam Guard
   "remember this device" token) lives under `<vol>/steam-install/config`, so
   on End+relaunch Steam auto-logs-in silently (validated live: persisted across
   two End+relaunch cycles). No separate encrypted-credential injection needed —
   the install root on the volume carries the login state naturally. First
   launch: one-time Steam login + Steam Guard. `cloud/docs/V2-PLAN.md` §5.
6. **`dpad-launch-session` live validation** (v2 worker side) — the SSH launch
   + volume mount + per-slot coturn + the `DPAD_READY` readiness marker (the
   worker currently uses a `docker ps` count heuristic).
7. **restart-on-disconnect supervisor — IMPLEMENTED in `entrypoint.sh` (`relaunch_selkies()` + the health loop) + VALIDATED LIVE 2026-08-05.** Was: optional, for 100%-consistent refresh. The health loop now relaunches `selkies-gstreamer` when it dies while gamescope+Steam are up (reusing the resolved encoder + re-reading gamescope's current Xwayland display), and kills the stale selkies on a gamescope restart. Ships via the entrypoint bind-mount hotfix (no image rebuild). **Validation (done):** OVH Gravelines L4 — killed `selkies-gstreamer` inside a live streaming container → the health loop detected it within ~20s, `relaunch_selkies()` relaunched it as a fresh process (new PIDs, same encoder=nvh264enc), gamescope untouched, stream recovered (the browser reconnects).
8. **(optional) NVRTC soname-11 real fix** (make CUDA 12.8 libnvrtc win).
   → SUPERSEDED by #10 below (the 12.9 extraction fix — apply that instead).
9. **evdev gamepad path — VALIDATED END-TO-END with a real controller
   (2026-08-04, OVH Gravelines L4); two blocking bugs found + fixed; SHIPPED in
   the 2026-08-05 image rebuild + push (the public `:dpad-SteamOS` now bakes
   both fixes — evdev works on a fresh `docker pull`, no bind-mount needed).** Activates the evdev interposer + fake-libudev stack
   (`scripts/gamepad-evdev-fallback/`) — SDL3 discovers 4 virtual Microsoft
   X-Box 360 pads (auto-mapped, no GUID hack) + unblocks 4-controller + rumble.
   The missing dual-serve dispatch (the interposer does NOT translate
   `js_event`→`input_event`) is `scripts/evdev_bridge.py` (external asyncio
   bridge: js socket → `input_event`+`EV_SYN` on `event100N`, arch-aware
   16B/24B). **2026-08-04 live validation: a real browser controller navigated
   Steam Big Picture end-to-end** (browser gamepad → Selkies → bridge →
   interposer → SDL3 → Steam). Two bugs were blocking it (both fixed in repo):
   - **(a) i386 fake-libudev wrong SONAME** (`scripts/gamepad-evdev-fallback/
     fake-udev/Makefile`): the 32-bit fake was built `-soname libudev_x86.so.1`
     instead of `libudev.so.1`. Steam's main binary is 32-bit (`ubuntu12_32/
     steam`) + SDL3 resolves gamepad discovery via `dlopen("libudev.so.1")` +
     `dlsym` (NOT link-time symbols), so the wrong soname made dlopen skip the
     LD_PRELOAD'd fake + load the REAL `libudev.so.1.7.8` shipped by the steam
     runtime → real enumeration over `/sys` (the fake `/dev/input/event100N`
     nodes have no `/sys` backing) + no udev daemon → **zero devices**. Fix:
     i386 `-soname libudev.so.1` (x86_64 was already correct). With the fix,
     SDL3's dlopen finds the already-LD_PRELOAD'd fake → fake enumeration →
     discovers the 8 nodes (proven: `JS_LOG=1` shows 115 `udev_enumerate_*`
     calls into the fake + `EVIOCGID -> ven:0x045e prod:0x028e`).
   - **(b) bridge event sockets created root-owned mode 755** (`scripts/
     evdev_bridge.py`): the bridge runs as root (entrypoint `setsid`), Steam
     runs as `dpad`, so the interposer got `EACCES` connecting to
     `/tmp/selkies_event100N.sock` (no write bit for others). Fix: the bridge
     `os.chmod(self.ev_sock, 0o777)` after `start_unix_server`.
   Both fixes are baked into the image (the `.so` in the `interposer-builder`
   stage, the bridge via `Dockerfile` COPY) — **SHIPPED via the 2026-08-05 image
   rebuild + Docker Hub push** (the `.so` soname is set at link time + can't be
   hotfixed, so this needed the rebuild; the bridge is ALSO on the entrypoint
   bind-mount hotfix path — `vm-bootstrap` fetches `evdev_bridge.py` +
   `dpad-launch-session` bind-mounts it — so future bridge fixes ship without a
   rebuild). Not urgent: evdev is opt-in (default OFF), the classic path is the
   default + unaffected. The classic path (the default) is unchanged +
   validated working. **Remaining (optional, now unblocked by the rebuild):**
   wire the env into the control plane (cloud `apps/worker/src/index.ts:711-726`:
   add `echo "DPAD_GAMEPAD_INTERPOSER=evdev" >> /etc/environment` to the
   bootstrap) + redeploy the worker for a normal dpadplay session to boot evdev.
   See `scripts/gamepad-evdev-fallback/README.md` + the 2026-08-04 session note.
10. **NVRTC fix — ✅ DONE (2026-08-07): baked into the repo.** Likely **moot on the new compositor path** (`WAYLAND-ARCHITECTURE.md` §2.2/§7 — the CUDAMemory `waylanddisplaysrc ! nvh265enc` path bypasses `cudaconvert`'s NVRTC JIT); kept as the hotfix path for existing gamescope-headless images + the gst-wayland-display `DMABuf`/software fallbacks. **✅ CONFIRMED LIVE 2026-08-08 (OVH L4, §13.14): NVRTC-error count = 0 on the CUDAMemory path** (no `cudaconvert` in the pipeline → no NVRTC JIT). Added
    `container-gaming/scripts/extract-nvrtc.sh` (canonical, idempotent,
    hardened — leaves the bundled libnvrtc on a download failure). The
    **Dockerfile** (`# --- 4b` block, after the Selkies tarball install) bakes
    `libnvrtc 12.9.86` into `/opt/gstreamer/lib/x86_64-linux-gnu/` at build
    time with a FATAL `test -f` verify (a silent skip would ship a
    broken-stream image). The **entrypoint** (first action after `set -o
    pipefail`) re-runs it idempotently (`|| true`) — no-op when baked; lets the
    **entrypoint bind-mount hotfix path** ship it to EXISTING images without
    a Docker Hub rebuild (gotcha #19; the rebuild is owner-blocked). Reference
    impl mirrors `cloud/scripts/extract-nvrtc.sh` (the live-VM version).
    Unblocks video for BOTH the steam + lutris shells on every provider (not
    just the live-patched Paris VM). (Was: the live Paris VM had the
    libnvrtc 12.9.86 extraction inlined in the bind-mounted `entrypoint.sh`;
    validated: with 12.9.86, `nvrtc: error` count → 0 + the steam shell streams
    video.) Next owner step: the image rebuild + push bakes it; until then
    fresh VMs get it via the hotfix fetch from `main`. See §5 (the NVRTC
    note) + `STORES-PLAN.md` §17.2/§17.5 #1.
11. **Lutris shell produces NO capturable video — the multi-store blocker
    (STORES-PLAN §17.3).** **Retired by the compositor pivot**
    (`WAYLAND-ARCHITECTURE.md` — adopt `gst-wayland-display` as the compositor
    + capture layer; Electron renders directly into it). **✅ The compositor +
    CUDAMemory capture are LIVE-VALIDATED 2026-08-08 on an OVH L4**
    (`WAYLAND-ARCHITECTURE.md` §13.14: compositor starts on the render node, EGL
    glamor works on the open R580, CUDAMemory zero-copy engages, nvh264enc inits,
    NVRTC-error=0, the wayland socket is created). The remaining live half is the
    client/XWayland layer (the current gamescope build has NO `--backend wayland`
    → rebuild with the wayland backend OR use sway as the Wayland client) + the
    Selkies `build_video_pipeline` patch + the entrypoint `DPAD_COMPOSITOR` gate
    + the full browser-stream (webrtcbin+coturn) validation. The probe knobs stay
    as a stopgap + a way to characterise the bug; the real fix is the new
    compositor. **✅ RESOLVED 2026-08-09 (WAYLAND-ARCHITECTURE.md §16.7):** the
    sway-as-client fallback (`DPAD_WAYLAND_CLIENT=sway`) is LIVE-VALIDATED on an
    OVH L4 — sway stays up (self-heals on drop), Steam renders, audio plays, +
    the user can click. The gamescope `--backend wayland` client drop (§16.3) is
    BYPASSED. The remaining §8 phasing: Lutris shell + store launchers under
    sway, gamepad input under sway (§5.4), N-on-N on sway, then flip the default. With the NVRTC fix + `DPAD_STORE_SHELL=lutris`, the
    video webrtcbin never adds a video m-line (`m=video: 0` vs `m=video: 2`
    for steam on the SAME VM/image) → audio connects but no video → "Waiting
    for stream". `lutris-gamepad-ui` (Electron AppImage) does NOT render into
    the gamescope `pipewiresrc` capture node the way Steam's CEF does.
    **✅ Probe RUN 2026-08-08 (OVH Gravelines L4, image `b403937b…`): `--disable-gpu`
    did NOT fix it** — browser still "Waiting for stream"; gamescope's PipeWire
    stream oscillated paused↔streaming + the capture node was active, but
    Selkies' pipewiresrc→webrtcbin produced no video track (a parallel gst grab
    captured 0 frames in 14s). So the bug is fundamental to gamescope-headless +
    Electron, NOT a GPU-init issue → the `gst-wayland-display` pivot is strictly
    necessary. (Same session validated §17.4 — sdl_manager loaded libSDL3.so.0.)
    **Probe knobs now wired (2026-08-07):** `scripts/lutris-shell` appends
    Electron flags behind env gates (default OFF = no regression): `--disable-gpu`
    (`DPAD_LUTRIS_DISABLE_GPU=1`, the cheapest diagnostic),
    `--ozone-platform=wayland` (`DPAD_LUTRIS_OZONE=wayland`), `--use-gl=egl`
    (`DPAD_LUTRIS_USE_GL=egl`), arbitrary flags (`DPAD_LUTRIS_EXTRA_ARGS`);
    the entrypoint re-exports them through `as_user` (su) via a `LUTRIS_ENV`
    blob; `dpad-launch-session` forwards them (`-e DPAD_LUTRIS_*`) +
    `-e DPAD_VIDEO_SRC` (so a manual `DPAD_VIDEO_SRC=ximagesrc` flips Selkies
    to the `:2` Xvfb bridge, which may capture an X-rendering Electron app).
    Reference: `games-on-whales` runs Lutris with `RUN_SWAY=1`/`RUN_GAMESCOPE=1`
    — check their capture wiring. Decisive test: `DPAD_LUTRIS_DISABLE_GPU=1` →
    does `m=video:2` appear? Then `GST_DEBUG=webrtcbin:5` + compare the video
    pad link/caps between the two shells. (The steam shell streams fine → NOT
    an image regression.) See STORES-PLAN §17.5 #2.
12. **`libSDL3.so.0` unfindable by `lutris-gamepad-ui` (STORES-PLAN §17.4).**
    **On the critical path** under the Lutris-primary shell decision
    (`WAYLAND-ARCHITECTURE.md` §6 — Lutris is the v1 shell; the new compositor
    retires the §17.3 capture bug, so Electron is fine, and this libSDL3 bug
    is the one remaining blocker for gamepad nav). Fix = a `sdl3-builder`
    stage (build SDL3 from source with minimal backends; §5.6). Keyboard/mouse
    via Selkies Desktop mode works without it.
    `lutris-shell.log`: `[sdl_manager] Unable to load libSDL3.so.0 … No such
    file or directory`. libSDL3 exists ONLY in Steam's runtime dirs
    (`steamrt32/`/`steamrt64/`), not on the system library path; the
    `lutris-gamepad-ui` Electron app (koffi FFI `dlopen`) can't find it → the
    SDL3 gamepad path (`LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1`) is broken → the
    gamepad won't navigate the Lutris UI (keyboard/mouse via Selkies Desktop
    mode still work). Fix: install `libsdl3-0` system-wide in the Dockerfile
    (cleanest), OR add the steamrt libSDL3 path to `LD_LIBRARY_PATH` in
    `scripts/lutris-shell`, OR symlink libSDL3 into the AppImage's `usr/lib`.

13. **`start_cursor_monitor` latent bug — ✅ DONE (2026-08-11, `de1f40f`).** The §17.2 lazy-XTest-input fix patched `send_x11_keypress`/`send_mouse` to tolerate `self.xdisplay=None` while sway's Xwayland `:0` isn't up (the inverted boot of the wayland-display path), but NOT selkies' own `start_cursor_monitor` — which derefs `self.xdisplay.has_extension('XFIXES')` at startup → a logged background-thread `AttributeError` (benign — selkies survives, stream works — but the server-side cursor monitor was dead on the wayland path). Fix: a bounded wait-for-`:0` guard in `scripts/dpad_input_patch.py` that then calls the original → the cursor monitor now starts (`Found XFIXES version 4.0` + `watching for cursor changes`). Live-validated on a Scaleway Paris L4 (open R580). **Ships via the new `dpad_input_patch.py` bind-mount hotfix path** (`vm-bootstrap.sh` `ensure_image` fetches it to `/opt/dpadcloud/dpad_input_patch.py` + `scripts/dpad-launch-session` bind-mounts it over the site-packages copy — no Docker Hub rebuild needed; the §17.4 follow-up). A runtime cursor-watch-loop display-death crash (`webrtc_input.py:471 pending_events`) remains a pre-existing benign thread exception (hardening is a later polish).

## 7. Deprecated (Vast era — in git history only)

- `:dpad-heroic` / `:dpad-heroic-rtx50` (Vast Docker, no userns → Heroic
  storefront via the `umu_run.py` → Proton-direct bypass).
- The headless `steamcmd` + `dpad-launch` path (Proton-direct, single-player,
  no Steam UI).
- `bubbleroot` (proot-based bwrap shim) — dead-end (CEF crashes under ptrace).
- The DFP Xorg / `--connected-monitor=DFP-0` single-user path (nvidia-modeset
  singleton → 1 full-Steam per VM). Superseded by gamescope headless N-on-N.
- `mws` / Sunshine / Tailscale / native-Moonlight — removed; Selkies is the
  only browser stream.
- The `ximagesrc` `:2` Xvfb bridge — replaced by `pipewiresrc` direct capture
  (`DPAD_VIDEO_SRC=ximagesrc` keeps it as a fallback).

## 8. Cross-references

- `IMAGE-RUNBOOK.md` — the launch recipe (`vm-bootstrap.sh` one-command + the
  manual `docker run` with the flag table) + the env-var reference + boot
  milestones + troubleshooting. The operational runbook.
- `cloud/docs/STATUS.md` — the control-plane handoff (v2 flow, the 3 live
  provider adapters, the open control-plane items).
- `cloud/docs/V2-PLAN.md` — the post-Vast architecture (regions, tiers,
  volumes, on-demand N-to-N, billing).
- `cloud/docs/DEPLOY-RUNBOOK.md` — the driver-per-pool recommendations
  (R580 LTS for the L4) + the regression registry.
- `STORES-PLAN.md` — the multi-store pivot (Lutris gamepad-UI shell; Epic+
  GOG+Battle.net v1; EA App + Ubisoft Connect v1.1). **IMPLEMENTED + deployed
  2026-08-07** (§16). **2026-08-07 deep live-test (§17):** the `dpad-launch-session`
  inline-`#` bug is FIXED + pushed (`13f8687`); the NVRTC `cudaconvert` blocker
  is **✅ baked into the repo (§6 #10 — Dockerfile 4b + entrypoint, ships via
  the bind-mount hotfix path without a rebuild)**; **the remaining multi-store
  blocker is Lutris-specific** — `lutris-gamepad-ui` doesn't render into
  gamescope's capture (Steam streams fine on the same VM). **Probe knobs wired**
  (`DPAD_LUTRIS_DISABLE_GPU`/`_OZONE`/`_USE_GL`/`_EXTRA_ARGS` + `DPAD_VIDEO_SRC=ximagesrc`;
  STORES-PLAN §17.5 #2) for the next live test. `libSDL3.so.0` unfindable
  (gamepad won't navigate) is DEFERRED until the capture works (§6 #12).
  The image bakes GE-Proton11-3 + Lutris + the `lutris-gamepad-ui` AppImage;
  the entrypoint `DPAD_STORE_SHELL` gate (default Steam) + `scripts/lutris-shell`
  wrapper; `dpad-launch-session` forwards `DPAD_STORE_SHELL`/`DPAD_STORES` +
  the capture-probe env; the cloud worker writes them to `/etc/environment`
  (opt-in via `deploy/vps/docker-compose.yml`).

## 9. Resume

```bash
cd dpadplay/container-gaming && git pull
docker build --target vast-vm -t forcespt/dpadcloud-gaming:dpad-SteamOS .
# Then read §6 — the driver-595→580 downgrade + the Docker Hub push are the
# two owner steps blocking flicker-free v2 streams.
```