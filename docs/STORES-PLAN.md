# DpadCloud Container Gaming — Multi-Store Plan (Lutris shell)

> **Spec (2026-08).** The plan to add non-Steam stores (Epic + GOG + Battle.net,
> with EA App + Ubisoft Connect reserved as v1.1 drop-ins) to the
> `:dpad-SteamOS` image. Today the image runs **one store**: a gamescope-headless
> session with **Steam as the shell** (`gamescope … -- steam -gamepadui`); users
> install games on a persistent per-user volume (download-once) or a 200 GB
> ephemeral rootfs cap. This doc specifies the pivot to a **store-picker shell**
> so the user is never forced to log into Steam to reach another store —
> especially important for **ephemeral** users (nothing persists → they'd log
> into every store every session).
>
> **Companion:** `PROJECT_STATE.md` (the image state + baked-in fixes + open
> items), `IMAGE-RUNBOOK.md` (the launch recipe + env-var reference), the
> `cloud/docs/` set (the control plane that picks the image + writes the
> bootstrap env).
>
> **Status:** IMPLEMENTED + DEPLOYED (2026-08-07), live validation PENDING —
> blocked by a PRE-EXISTING worker↔Scaleway SSH-handshake issue, NOT by the
> multi-store work. The image + entrypoint gate + wrapper + control-plane env
> are all built, pushed, + confirmed live on a Paris VM (the VM's
> `/etc/environment` got `DPAD_STORE_SHELL=lutris` + the open-driver swap + the
> new image pull all succeeded; the session died in the bootstrap-vm-ready
> poll — see §16). Decisions locked 2026-08 (the DECISION block at the
> bottom).

## 0. TL;DR — the pivot

The shell stops being Steam and becomes **`lutris-gamepad-ui`** (a gamepad-
navigable 10-foot-UI frontend over Lutris). The gamescope-headless + Selkies
`pipewiresrc` + coturn + FEC + input pipelines are **unchanged** — only the app
launched at the end of `gamescope … --` changes. Lutris becomes the backend
that owns the library + launches each store's games:

| Store | Type | Launcher needed? | Pre-bake |
|---|---|---|---|
| **Steam** | Native Linux client | (it IS the client) | ✅ Already done — `build-bootstrap-steam.sh` bakes `steamwebhelper`; install-root-on-volume + Steam Guard auto-login already validated (`PROJECT_STATE.md` §3) |
| **Epic** | Lutris source (Legendary) | ❌ No launcher | Just Lutris + the Epic source; first-session browser login |
| **GOG** | Lutris source (gogdl) | ❌ No launcher (DRM-free) | Just Lutris + the GOG source; first-session login |
| **Battle.net** | Windows launcher in a Wine prefix | ✅ `Battle.net.exe` | ✅ **NEW** — pre-run the Lutris install script at build (launcher + prefix baked); first-session Battle.net login |
| *(v1.1)* EA App | Windows launcher in a Wine prefix | ✅ `EADesktop.exe` | same pattern as Battle.net |
| *(v1.1)* Ubisoft Connect | Windows launcher in a Wine prefix | ✅ `UbisoftConnect.exe` | same pattern as Battle.net |

The shared Proton compatibility layer is **GE-Proton11-3** (baked into
`compatibilitytools.d/`), run via **umu-launcher** (the path the image already
uses). GE-Proton11-3 ships the **Battle.net white-screen fix** (11-2 changelog:
"Battle.net: fixed Wine Wayland white-screen behavior" + "`--in-process-gpu`
handling for Wine Wayland launchers"), the bundled **NVIDIA compatibility
libraries** (NVAPI/CUDA/NVENC/NVML/OptiX), **`umu.exe`** ("works the same way
`steam.exe` does… helps 3rd-party launchers run the same way Steam runs them"
— purpose-built for Battle.net/EA-style launchers via umu), the **Diablo IV +
Marvel Rivals upstream fixes**, and the controller haptics/DualSense hotplug
work. All three Windows launchers run via **Xwayland** (`PROTON_ENABLE_WAYLAND`
unset) — the default Proton path and the one your image already uses for
Steam's CEF (see §5 for why).

## 1. Why a store-picker shell (not Steam-as-shell)

Two shapes were considered:

- **Option A — Steam is the shell, other stores are non-Steam shortcuts.**
  Reuses the validated pipeline 100 %; Steam Input (gamepad remapping) for free;
  one unified library inside Steam Big Picture. BUT: forces a Steam account — a
  user who only wants Battle.net must still log into Steam. For ephemeral
  users (nothing persists → log into everything every session) that's real
  friction on top of the store they actually want.
- **Option B — Store picker as the shell.** A neutral front door; a Battle.net-
  only user never touches Steam. Costs a picker UI to maintain and loses Steam
  Input's per-game remapping for non-Steam games (gamepads still work — see §6).

**Decision: Option B.** The ephemeral-login-freedom argument is the deciding
factor — a user on a 200 GB ephemeral rootfs who only wants Battle.net should
not be forced through a Steam login every session. (Steam-login persistence
makes Option A frictionless for *persistent-volume* users, but that doesn't
help ephemeral users, and we don't want two UX models.)

Of the B variants, **B2 — Lutris gamepad-UI as the shell** was chosen over a
custom picker (B1) and Heroic-Console-Mode (B3), because Lutris is the one tool
that covers all v1 stores (Steam + Epic + GOG + Battle.net) and ships a real
maintained gamepad UI. Fallback to a custom picker (B1) if the Lutris UX
doesn't feel right after live validation.

## 2. The pipeline change (minimal)

```
gamescope --backend headless -e -W 1920 -H 1080 -- lutris-gamepad-ui   # was: -- steam -gamepadui
   │  renders the Lutris gamepad-UI on the GPU via Vulkan/gamescope-WSI, NO DRM master
   │  → PipeWire video node (BGRx 1920x1080)  ← UNCHANGED
   │  → Xwayland :0  ← UNCHANGED
   ▼
[Selkies capture — pipewiresrc direct]  ← UNCHANGED
   pipewiresrc(target-object=gamescope, always-copy=True) → videorate → cudaupload
   → cudaconvert(BGRx→NV12) → nvh264enc → webrtcbin → coturn → browser
[Audio]  pipewire-pulse null sink → Selkies pulsesrc  ← UNCHANGED
[Input]  browser WebRTC datachannel → Selkies → xtest.fake_input on :0 → Xwayland → the focused app  ← UNCHANGED
[Gamepad] browser gamepad → Selkies → /tmp/selkies_jsN.sock → root watcher mknods /dev/input/jsN
          → SDL3 (lutris-gamepad-ui reads via LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1; games read /dev/input/jsN)  ← 6-layer chain unchanged
```

Only the `--` argument changes. Everything downstream (capture, encode, coturn,
FEC, input, gamepad mknod) is identical to the validated gamescope-headless path
(`PROJECT_STATE.md` §2). N-on-N MPS oversubscription is unaffected (still one
gamescope session per container, one container per GPU/slot).

## 3. The shell — `lutris-gamepad-ui`

- **Repo:** `andrew-ld/lutris-gamepad-ui` (GPL3, ~59★, actively maintained — AUR
  `lutris-gamepad-ui-git` updated 2026-07-16; games-on-whales bumped to **v0.2.0**
  in gow PR #344, 2026-06).
- **What it is:** a "10-foot UI", gamepad-navigable frontend over Lutris.
  Launches games from the Lutris library; shows a "Now Playing" screen; the
  gamepad Home/Guide button or `Ctrl+X` toggles the UI without closing the game.
- **Distribution:** an **AppImage** (download from the releases page, `chmod +x`,
  run). Easiest to bake into the SteamOS-based image (no AUR/native pkg needed).
- **Backend:** **Lutris** (v0.5.22 current, in Arch Extra — but the image is
  SteamOS-based, so install via the AppImage's bundled Lutris or a pip/Lutris
  tarball). `lutris-gamepad-ui` talks to Lutris via a `lutris_wrapper.py`; Lutris
  owns the library + the install/launch logic.
- **Critical integration detail:** the gamepad-UI uses the Web Gamepad API by
  default, which **does not work in-container** (no browser). Must run with
  **`LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1`** so it reads SDL3 gamepad devices —
  i.e. the `/dev/input/jsN` nodes the entrypoint already mknods. The existing
  6-layer gamepad chain (`PROJECT_STATE.md` §4) feeds these directly; no new
  gamepad plumbing.
- **Config/theme:** lives at `~/.local/lutris-gamepad-ui/` (`theme.json`,
  `theme.default.json`) → symlink to the volume for persistence.

**UX flow (matches the existing one-time-then-automatic pattern):**
- **First session ever** (per store): user lands in the Lutris gamepad-UI →
  uses "Open Lutris" (or a pre-seeded store entry) to configure each store
  — Epic/GOG: browser login + install a game; Battle.net: the pre-baked launcher
  opens → Battle.net login + install a game. This first-time setup needs
  mouse/keyboard, done via Selkies Desktop mode (the existing Desktop/Gaming-
  mode toggle, `IMAGE-RUNBOOK.md`).
- **Every session after:** gamepad-only — open the gamepad-UI → pick a game →
  Play. Persistent-volume users are auto-logged-in to every store they've
  already configured (login tokens live on the volume). Ephemeral users log in
  once per session to whichever store(s) they want (no forced Steam).

## 4. Proton — GE-Proton11-3 (the Battle.net white-screen fix is in)

- **Pin:** `GE-Proton11-3` (published 2026-07-25; the hotfix on top of 11-2).
  Bake into `~/.steam/debian-installation/compatibilitytools.d/` (and expose to
  Lutris/umu).
- **Why 11-3 (not the earlier "pin 10-34" idea):** the Battle.net white-screen
  issue (#427, CEF/Electron on Wayland) is **FIXED in 11-2**, which 11-3 builds
  on. 11-2 changelog verbatim:
  - *"Battle.net and Warframe: added `--in-process-gpu` handling for Wine Wayland
    launchers."*
  - *"Battle.net: fixed Wine Wayland white-screen behavior."*
  - Issue #427 closed by GloriousEggroll pointing at the fix commit
    (`9fdfdf79` → standalone patch `28d0269`, 2026-07-11).
  → No manual `--in-process-gpu` flag, no "disable HW acceleration", no Proton
  version pinning needed. Proton handles the CEF launchers itself.
- **Free wins in 11-3 (all relevant to this image):**
  - **Bundled NVIDIA compatibility libraries** — NVAPI, CUDA, NVENC, NVML,
    OptiX (NVAPI matters for DLSS/Reflex; no separate NVAPI setup).
  - **`umu.exe`** — "works the same way `steam.exe` does… used now instead of
    the standard wine `start.exe`, should help some 3rd-party launchers run the
    same way Steam runs them." Purpose-built for Battle.net/EA launchers via
    umu outside Steam.
  - **Controller improvements** — wired USB haptics for DualShock 4 / DualSense
    / DualSense Edge, controller mono-speaker, hotplug fixes, standardized on
    PulseAudio. Could improve the just-shipped evdev path for PlayStation pads.
  - **Diablo IV + Marvel Rivals upstream fixes imported** (Battle.net titles).
  - **OptiScaler + FSR4/FFX4** upscaling (useful on the L4/L40S).
  - **Media rework** — gutted gstreamer in favor of winedmo/ffmpeg (fewer
    gstreamer dep issues in the container).
- **⚠️ Live-validate:** the #427 reports were all *desktop* Wayland (KDE/KWin).
  Your setup is *gamescope headless* (apps via Xwayland :0, or wine-wayland if
  `PROTON_ENABLE_WAYLAND=1`). The fix targets the wine-wayland path. The safe
  combinations to probe: (a) 11-3 + Xwayland (default — the 11-1 regression was
  wine-wayland-specific, so Xwayland was never affected), or (b) 11-3 +
  `PROTON_ENABLE_WAYLAND=1` (the now-fixed path). **Recommendation: run all
  Windows launchers via Xwayland** (see §5) — so 11-3 + Xwayland is the path to
  validate, and it's the lowest-risk one. Probe on one L4/L40S (OVH Gravelines
  = cheapest validated box) before shipping.

## 5. The Xwayland rule (one consistent path for all launchers)

All three Windows launchers run via **Xwayland** (`PROTON_ENABLE_WAYLAND`
unset) — the default Proton behavior and what the image already does for
Steam's CEF. This is the safe common path:

- **Battle.net** white-screen was a *wine-wayland* regression (now fixed in
  11-3) → Xwayland was never affected, wine-wayland is now fixed too.
- **EA App** is *flaky on wine-wayland* (GE-Proton issue #188: *"Running with
  `PROTON_ENABLE_WAYLAND=0` always works"*) → Xwayland is the safe path.
- **Ubisoft Connect** is CEF/Electron like the others → same guidance.

So: **do not enable `PROTON_ENABLE_WAYLAND` for any launcher.** No per-store
Wayland toggling. The image's existing Xwayland :0 setup (for Steam's CEF)
serves all of them.

## 6. Gamepad — works in any app, not just Steam

Two separate things (cleared up during planning):

1. **"Does the pad work at all?"** → YES, in any app in the gamescope/Xwayland
   session. The current pipeline (browser gamepad → Selkies → `/dev/input/jsN`
   → XTest injection → Xwayland → the focused app) is **app-agnostic**. The 6-
   layer fix is about making **SDL3** see the pads (SDL3 is what most games
   *and* `lutris-gamepad-ui` use), not about Steam. `lutris-gamepad-ui` reads
   them via `LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1`; games read `/dev/input/jsN`
   directly.
2. **"What does Steam specifically add?"** → **Steam Input** — Valve's
   remapping layer (per-game configs, gyro-to-stick, action-sets, chord
   shortcuts). Only applies to games launched *through Steam*. Lost for non-Steam
   games under the Lutris shell. Most users won't miss it; Lutris has its own
   (simpler) controller-config layer to partially replace it.

Net: **no gamepad regression** from dropping Steam-as-shell. The `evdev` path
(`PROJECT_STATE.md` §6 #9, shipped 2026-08-05) keeps working for `lutris-gamepad-
ui` + the games.

## 7. Store coverage — v1

### Steam (native, already pre-baked)
- The native Steam client is **already baked** (`build-bootstrap-steam.sh` →
  `ubuntu12_64/steamwebhelper` in the image; cold boot ~50 s).
- The install root lives **on the volume** (`entrypoint.sh` symlinks
  `~/.steam/debian-installation` → `<vol>/steam-install`; `PROJECT_STATE.md` §4
  + `STATUS.md` §8 #1b). Steam Guard "remember this device" persists →
  **silent auto-login** on every relaunch (validated 2026-08-01).
- Under the Lutris shell: Lutris imports the Steam library as a "source" and
  launches games via `steam://rungameid/<id>`; the native Steam client opens
  inside the same gamescope session (captured by the same `pipewiresrc`).
- **UX wrinkle to validate live:** picking a Steam game from the gamepad-UI
  fires `steam://rungameid`, which opens the native Steam client — the user may
  see a brief Steam flash before the game window. Streaming is unaffected (one
  gamescope session); just a polish item to check on the first Steam-game launch.

### Epic (Lutris source, no launcher)
- Lutris manages Epic directly via **Legendary** (the backend Heroic also
  uses). No "Epic Games Launcher" binary needed — Lutris downloads + installs
  Epic games directly.
- First session: browser login to Epic (mouse/kb via Selkries Desktop mode).
- State on the volume: Lutris config + the Legendary token + per-game install
  dirs (under `<vol>/lutris/` or a games dir). Login persists on the volume.
- **No pre-bake needed** beyond Lutris + the Epic source available.

### GOG (Lutris source, no launcher, DRM-free)
- Lutris manages GOG directly via **gogdl**. No "GOG Galaxy" binary needed.
- First session: browser login to GOG.
- State on the volume: same as Epic. DRM-free = cleanest store.
- **No pre-bake needed.**

### Battle.net (Windows launcher, pre-baked)
- The canonical Lutris install script (well-maintained, ~24 k users on
  lutris.net): create a Wine prefix → winetricks (`corefonts`, `win10`,
  `d3dcompiler_47`, `vcrun2022`…) → run `Battle.net-Setup.exe` → `winekill`.
- **Pre-bake:** run the install script at **image build time** so the
  Battle.net launcher binary + its prefix are baked into the image → first
  session is just a Battle.net login (fast), not a launcher download.
- State on the volume: `<vol>/games/battlenet/` (the prefix `drive_c` + the
  launcher config + installed games). Battle.net session token lives in the
  prefix → login persists on the volume.
- Run via **Xwayland** (§5). Proton = GE-Proton11-3 (§4, white-screen fix in).
- **Known store-level risk:** anti-cheat is per-title (deferred to the website
  phase). Diablo IV / WoW / Hearthstone work on Proton; Overwatch 2 (kernel
  AC) is blocked.

## 8. v1.1 drop-ins (same pattern as Battle.net — reserve slots now)

| Store | Launcher | Lutris install script | Volume slot |
|---|---|---|---|
| **EA App** | `EADesktop.exe` (from `origin-a.akamaihd.net/EAappInstaller.exe`) | ✅ ~24 k users; create_prefix → winetricks (`corefonts win10 d3dcompiler_47 liberation d3dx9`) → `wineexec /silent` → `winekill` | `<vol>/games/ea-app/` |
| **Ubisoft Connect** | `UbisoftConnect.exe` | ✅ community script | `<vol>/games/ubisoft/` |

Both are the **same "Windows launcher in a Wine prefix" pattern** as Battle.net
→ low marginal cost, no re-architecture. EA App-specific note: it's flaky on
wine-wayland (GE-Proton #188) → the §5 Xwayland rule already covers it.

## 9. Volume / state layout (extends the install-root-on-volume fix)

Your §4 "Steam install root ON the volume" fix already carries Steam state.
Extend the same idea: a `<vol>/` root with per-store subdirs, all symlinked
into `~` so each launcher persists its login + games:

```
<vol>/steam-install/         (existing — Steam client + games + Steam Guard login)
<vol>/lutris/                (Lutris config + library cache + Legendary/gogdl tokens)
<vol>/games/battlenet/       (Battle.net Wine prefix + launcher + games)
<vol>/lutris-gamepad-ui/     (gamepad-UI theme + prefs)
<vol>/games/ea-app/          (v1.1 — reserved)
<vol>/games/ubisoft/         (v1.1 — reserved)
```

On session boot, the entrypoint symlinks `~/.config/lutris → <vol>/lutris/.config`,
`~/Games → <vol>/games`, `~/.local/lutris-gamepad-ui → <vol>/lutris-gamepad-ui`,
etc. — the same pattern as `~/.steam/debian-installation → <vol>/steam-install`.
**Login persistence comes free** (Battle.net/Epic/GOG tokens live in their
prefix/config on the volume) — the same mechanism that gives Steam auto-login.
First launch of each store = one-time login; every session after = auto-logged-
in (persistent-volume users).

**Disk budget:** per-store launcher+prefix overhead is ~1–2 GB each; ~6–8 GB
total across Steam + Epic + GOG + Battle.net before any game. The existing
volume presets (50/100/200/500 GB) stay; the picker should **recommend 100 GB+
for multi-store** (50 GB fits one store + one big game). No preset change
needed — just a UX hint.

## 10. Image / build plan

- **One new build target** (`--target vast-vm` still; a thin stage if you want
  to keep the base lean). Bake in:
  - `umu-launcher` + a pinned **GE-Proton11-3** in `compatibilitytools.d/`.
  - **Lutris** (native pkg or tarball) + the **`lutris-gamepad-ui` AppImage**
    (download from the releases page, `chmod +x`).
  - **Battle.net launcher + prefix** pre-baked via the Lutris install script
    run at build time.
  - A new `setup_stores()` entrypoint step: symlinks the per-store volume
    subdirs + seeds the Lutris library with the enabled stores (Epic/GOG
    sources + the pre-baked Battle.net entry) per `DPAD_STORES`.
- **Rebuild + push:** the owner-blocked Docker Hub step. Until then, ship via
  the **entrypoint bind-mount hotfix path** (`PROJECT_STATE.md` §4 /
  `STATUS.md` gotcha #19) — fetch a `setup_stores.sh` from `main` at bootstrap.
  The GE-Proton download (~508 MB) + Lutris + the AppImage can run on first
  boot (cached on the volume) to avoid bloating the image, OR be baked — bake
  is preferred for the fast-Play goal.

## 11. Control-plane changes (the `cloud` repo)

- The worker's bootstrap env-write (`apps/worker/src/index.ts:711-726`) writes
  a *fixed* var list. Add **`DPAD_STORES`** (e.g. `steam,epic,gog,battlenet`)
  so the entrypoint knows which stores to wire/symlink on a given session/tier.
- The tier catalog (`GPU_TIERS_V2`) — **no change for v1**. All stores are
  available on all tiers; the only cost is the Wine-prefix disk space on the
  volume (covered by the volume presets). A per-store dimension is a future
  option, not v1.
- The web launch flow — **no change for v1**. Stores appear in the Lutris
  gamepad-UI; the web app just launches the session (the existing flow). A
  future "choose your store" web step is a later polish (Option B1 territory).
- **Anti-cheat = a website/doc problem, deferred** — not a docker concern. The
  site will get a disclaimer + a ProtonDB-linked help section in a separate
  web phase.

## 12. Open items (the build/validation handoff)

1. **Live-probe GE-Proton11-3 + Battle.net in *headless* gamescope on one
   L4/L40S** (OVH Gravelines = cheapest validated box). Confirm the white-
   screen fix holds in the nested EGL context (the #427 reports were desktop
   Wayland). Validate the Xwayland path first (§5).
2. **Confirm `LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1` sees the mknod'd
   `/dev/input/jsN`** in the gamescope session — i.e. the 6-layer gamepad
   chain feeds the gamepad-UI, not just Steam. Decisive test: navigate the
   gamepad-UI + launch a game with a real controller.
3. **Check the Steam-game-launch flash** — picking a Steam game from the
   gamepad-UI opens the native Steam client; confirm the brief Steam UI flash
   is acceptable (or tune Steam to launch games quietly).
4. **First-time-setup UX** — confirm mouse/kb via Selkies Desktop mode works
   for the one-time store logins (Epic/GOG browser auth + Battle.net launcher
   login) inside the gamescope session.
5. **Image rebuild + Docker Hub push** (the owner step) — the Battle.net pre-
   bake + GE-Proton11-3 + Lutris/AppImage need the rebuild to ship cleanly.
   Until then, the entrypoint bind-mount hotfix path carries the wiring.
6. **Lutris-in-headless probe** — Lutris itself (Python/GTK) running inside
   gamescope headless via Xwayland; confirm it renders + the gamepad-UI launches
   it. Reference: games-on-whales runs Lutris in their container with
   `RUN_SWAY=1` or `RUN_GAMESCOPE=1`; we use gamescope headless directly.
7. **Lutris install-script reproducibility** — the Battle.net pre-bake runs the
   install script at build time; confirm it's reproducible (the script downloads
   `Battle.net-Setup.exe` from EA's/Blizzard's CDN — pin the URL or mirror the
   installer in the image for build determinism).

## 13. DECISION block (locked 2026-08)

- **Shell:** Option B2 — `lutris-gamepad-ui` (AppImage) with
  `LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1`; Lutris backend. Fallback: B1 custom
  picker if the UX doesn't feel right.
- **Proton:** GE-Proton11-3 baked in; Xwayland for all Windows launchers
  (`PROTON_ENABLE_WAYLAND` unset).
- **Stores (v1):** Steam (native, already pre-baked) · Epic (Lutris source) ·
  GOG (Lutris source) · Battle.net (pre-baked launcher+prefix via Lutris script).
- **v1.1 (drop-in, same pattern):** EA App · Ubisoft Connect — reserve
  `<vol>/games/ea-app/` + `<vol>/games/ubisoft/` now.
- **Pre-bake:** Steam (done) + Battle.net launcher+prefix (new). Epic/GOG have
  no launcher to pre-bake.
- **Anti-cheat:** deferred to the website phase (disclaimer + ProtonDB help
  section), not a docker concern.
- **Volume:** keep 50/100/200/500 GB presets; recommend 100 GB+ for multi-store.
- **Control plane:** add `DPAD_STORES` to the worker bootstrap env-write; no
  tier-catalog or web-flow change for v1.

## 14. Cross-references

- `PROJECT_STATE.md` — the image state; §2 (the gamescope-headless pipeline this
  reuses), §3 (validated state incl. Steam-login persistence), §4 (the baked-in
  fixes — install-root-on-volume, gamepad 6-layer chain, NVENC interposer), §6
  (open image-side items).
- `IMAGE-RUNBOOK.md` — the launch recipe + env-var reference; the `--` app swap
  + the new `DPAD_STORES` env land here when built.
- `cloud/docs/STATUS.md` — the control-plane handoff; the `DPAD_STORES` worker
  env-write (§`apps/worker/src/index.ts:711-726`) + the entrypoint bind-mount
  hotfix path (gotcha #19).
- `cloud/docs/V2-PLAN.md` — the regions/tiers/volumes architecture this slots
  into; the per-user persistent volume (§5) is where the per-store state lives.
- `cloud/docs/PRICING-V2.md` — the tier prices; no v1 change (stores don't add
  a tier dimension yet).

## 15. Resume

```bash
cd dpadplay/container-gaming && git pull
# IMPLEMENTED + pushed (2026-08-07) — see §16. The live-test gate is the
# pre-existing worker↔Scaleway bootstrap-SSH issue (§16), NOT the multi-store
# work. To resume a live test:
# 1. Retry a Paris Standard launch; watch `journalctl -u dpadcloud-bootstrap -f`
#    on the VM + the worker log.
# 2. If it fails at the vm-ready poll again (the 12-min "not ready" timeout),
#    apply the worker SSH patch (§16 #2: bump readyTimeoutMs + log step-3).
# 3. Once a session boots, validate §12 #1/#2/#3 (Lutris shell renders in
#    headless gamescope; gamepad↔SDL3; Steam-game-launch flash).
# 4. Then piece #2: Battle.net launcher+prefix pre-bake (deferred).
```

## 16. Implementation + live-test state (2026-08-07)

**Built + pushed + deployed (all build-verified on the build host + confirmed
live on a Paris VM):**

| Piece | Repo:file | Status |
|---|---|---|
| 1a GE-Proton11-3 + lutris-gamepad-ui AppImage (extracted at build) | `container-gaming/Dockerfile` (vast-vm) | ✅ built + pushed |
| 1b wine + wine32 + winetricks + Lutris v0.5.22 (symlink `/usr/games/lutris → /usr/bin/lutris`) | `container-gaming/Dockerfile` | ✅ built + pushed |
| 3 `DPAD_STORE_SHELL` gate in `start_gamescope_session` (default=Steam; `=lutris`→wrapper; shell-aware ready-check + health-loop) | `container-gaming/entrypoint.sh` | ✅ (ships via the entrypoint bind-mount hotfix path) |
| 4 `lutris-shell` wrapper (`LUTRIS_GAMEPAD_UI_ENABLE_SDL_INPUT=1` + `--no-sandbox` + execs the extracted `AppRun`) | `container-gaming/scripts/lutris-shell` | ✅ |
| 5a forward `-e DPAD_STORE_SHELL` + `-e DPAD_STORES` to the container | `container-gaming/scripts/dpad-launch-session` | ✅ |
| 5b opt-in `echo DPAD_STORE_SHELL/DPAD_STORES >> /etc/environment` at VM bootstrap | `cloud/apps/worker/src/index.ts` | ✅ deployed (worker typecheck clean) |
| 5c opt-in VALUES on the worker service env | `cloud/deploy/vps/docker-compose.yml` (`DPAD_STORE_SHELL: lutris` + `DPAD_STORES: steam,epic,gog,battlenet`) | ✅ deployed (TEST opt-in — revert: set `DPAD_STORE_SHELL: steam`) |

**Build bugs caught + fixed by the build-test loop** (why blind edits needed
building): (1) Ubuntu 24.04 wine 9.0 merged into one `wine` binary — `wine64`
is at `/usr/lib/wine/`, not on PATH (sanity check uses `wine`, added `wine32`
for 32-bit games); (2) the Lutris .deb ships its binary in `/usr/games/lutris`
(not `/usr/bin/`) — added `ln -sf /usr/games/lutris /usr/bin/lutris` (mirrors
the existing gamescope symlink); (3) the AppImage needs extraction (the
container's `docker run` flags don't include `--device /dev/fuse`) — extract
at build with `--appimage-extract`, run the extracted `AppRun` (no FUSE at
runtime).

**Live-test result (Paris Standard, session `06e1842f`, VM `1be9dc31` @
`51.159.179.121`, 2026-08-07 03:27):** the multi-store plumbing landed
CORRECTLY on the VM — `/etc/environment` had `DPAD_STORE_SHELL=lutris` +
`DPAD_STORES=...`, the proprietary→open driver swap completed (`580.178.04`),
the new image was pulled, + the `vm-ready` marker was touched at 03:33 (~6 min).
BUT the session **failed** at 03:39 (the 12-min `BOOTSTRAP_DEADLINE_MS`) — the
worker's step-3 `vm-ready` poll (SSH `test -f /opt/dpadcloud/vm-ready && echo
READY`) never returned READY, despite the marker existing + a manual `ssh
root@51.159.179.121` from the VPS succeeding. The worker log shows
`Timed out while waiting for handshake` (the ssh2/node library's handshake
timeout, `readyTimeoutMs: 15000`).

**This is NOT caused by the multi-store work** — the pre-deploy attempt the
same day (01:37, session `f7e2eb92`/VM `9d1c7060`) **also failed** on
Scaleway SSH (at step 2a: "sshd never came up (4 min)"); the multi-store env-
write ran fine. The two attempts failed at *different* steps (2a vs 3) — just
timing variance of when the driver-swap reboot falls relative to the 4-min/12-
min windows. Root cause is likely: the ssh2 npm library's 15s handshake timeout
is too short for Scaleway's sshd after the driver-swap reboot (slow banner /
reverse-DNS / `scw-fetch-ssh-keys` settling), where openssh CLI tolerates the
delay. Paris WAS validated end-to-end 2026-08-05, so it can work — this looks
transient / timeout-too-tight.

**Next steps to resume the live test:**
1. Retry a Paris Standard launch; watch `journalctl -u dpadcloud-bootstrap -f`
   on the VM + `docker logs dpadplay-worker-1`. If it boots → validate §12
   #1/#2/#3 (the real multi-store unknowns: does lutris-gamepad-ui render in
   headless gamescope? does the gamepad navigate it via SDL3? the Steam-game-
   launch flash?).
2. If it fails at the vm-ready poll again, patch the worker:
   - `cloud/apps/worker/src/index.ts` step 2a (line ~772) + step 3 (line ~804):
     bump `readyTimeoutMs: 15000` → `30000`.
   - Step 3's `catch` is SILENT (swallows the SSH error) — add a debug log
     (`console.warn`) so the actual handshake error shows. Without it the 12-
     min timeout is invisible.
   - Redeploy: `cd dpadplay/cloud && ./deploy/vps/deploy.sh`.
3. Piece #2 (Battle.net launcher+prefix pre-bake) is DEFERRED until the shell
   works — it's an optimization (fast first Battle.net session), not a blocker.
4. Revert the opt-in when done testing: `cloud/deploy/vps/docker-compose.yml` →
   `DPAD_STORE_SHELL: steam` → `./deploy/vps/deploy.sh` (new VMs back to the
   validated Steam path).

**Repos' git state (uncommitted on the build host):** `container-gaming` →
`Dockerfile`, `entrypoint.sh`, `scripts/dpad-launch-session` modified +
`docs/STORES-PLAN.md` + `scripts/lutris-shell` new; `cloud` →
`apps/worker/src/index.ts` + `deploy/vps/docker-compose.yml` modified. (The
`cloud/scripts/*` OVH/Scaleway probe + `*-reply.md` untracked files predate this
work — left for review.)