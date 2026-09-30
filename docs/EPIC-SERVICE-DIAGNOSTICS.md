# Official Epic updater: local service graphics diagnosis

## Result — 2026-09-30

No image was published, production changed, or paid VM started for this work.
All disposable local probes are account-free and use new temporary prefixes.

The Paris L4 test previously failed in the updater's `selfupdateinstall` child
with exit `777006` and Wine Vulkan instance creation `res=-7`. It subsequently
worked after a manual WineD3D update and DXVK client restart. Those are separate
graphics contexts; leaving WineD3D enabled caused post-login device loss.

The exact GE-Proton10-34 Wine source shows why a service differs from the client:
noninteractive services run on `__wineservice_winstation\Default`, where Wine's
null display driver translates the Windows Vulkan surface to
`VK_EXT_headless_surface`. Desktop processes use the desktop surface extension.

A test-only Mesa ICD proxy removes just the headless surface capability. With
the same pinned runner and fresh prefixes, the controlled results were:

| Case | Desktop D3D11 | Service D3D11 | Service desktop |
| --- | --- | --- | --- |
| Normal software ICD, original Wine | Pass | Pass | Noninteractive |
| Headless capability removed, original Wine | Pass | Fail, `res=-7` | Noninteractive |
| Capability removed, interactive diagnostic service | Pass | Pass | Visible |
| Capability removed, patched Wine, matching Epic identity | Pass | Pass | Visible |
| Capability removed, patched Wine, unrelated service | Pass | Fail, `res=-7` | Noninteractive |

This establishes the failure mechanism and narrow patch behavior locally. It
does **not** establish which extension the actual NVIDIA ICD lacked: the paid
VM had already been deleted and its extension list was not captured. Confirm
the exact ICD capabilities before treating this as the proven GPU root cause.

## Candidate change

`patches/wine-epic-updater-desktop.patch` adds a desktop exception to Wine's
existing service launch logic, analogous to its existing Arc Service exception.
All three must match:

- Service name: `EpicGamesUpdater`.
- Display name: `Epic Games Updater`.
- Exact installed Win64 updater executable under `C:\Program Files\Epic Games`.

It preserves Epic's service type `0x10`, executable, update behavior and login
flow. It retains DXVK for both updater and client, and changes no other service.
Only the pinned runner's 64-bit `services.exe` is rebuilt; ncrypt's prior
persistent-key patch remains in the reviewed runtime base.

The rebuilt local PE SHA256 was
`1dd79ee329ee0d4834036ff8942dbce373ebb604ae418ea61568d2a1be823408`.

The installed MSI confirmed the exact service identifiers and binary path.
An experimental `SERVICE_INTERACTIVE_PROCESS` configuration change succeeded
but the full client returned installation-query code 4 and did not qualify
startup. That approach was discarded; its helper is not included in the image
or retained as a launch option.

## Official updater check

A fresh account-free installation, actual Faugus/UMU integration, patched Wine,
software Vulkan and local headless Labwc completed the official update:

- Silent pinned MSI installation returned zero.
- Epic's service retained type `0x10`.
- `selfupdateinstall` finished with exit code **0**, at 01:22:14 UTC.
- Updater service/application exited **0 (Success)**.
- The current `Launcher.manifest` existed, replacing the staging-only state.
- Epic reported **up to date**, at 01:22:23 UTC.

`Installer complete. Success:1` alone remains insufficient. The reusable probe
reports commandlet success, current-manifest presence and the vendor's
up-to-date marker separately. GPU/login qualification always remains false.
Local updating also progressed with the original service on Mesa, which
supports the headless capability; that control does not reproduce the L4.

The final updated client logged a **handled ensure**, `EOSH is disabled` with
`MinimumVersionNotSatisfied`, after the bundled Online Services installer
reported `spawn UNKNOWN`. The launcher continued and reported up to date;
this does not establish healthy EOS prerequisites or a usable sign-in page.
Investigate that account-free prerequisite path before requesting another paid
owner login test. No sign-in screen or account acceptance is claimed here.

Xvfb initially caused an independent DXGI divide-by-zero at its zero-refresh
display mode. A local Labwc/Xwayland headless display reporting about 60 Hz
removed that diagnostic obstacle. This does not change production's Sway
default or qualify Labwc for GPU production.

## Reproduce locally

Use the reviewed local runtime `dpadplay/faugus-epic-handoff:local` (source
`3223c2c`, image `sha256:cc3db02e…c2d27e`) and pinned builder:

```powershell
docker build -f Dockerfile.faugus-epic-dpop --target ncrypt-builder `
  -t dpadplay/epic-probe-compiler:local .
```

Build the test-only executable and ICD proxy with a writable `/workspace` mount
in that builder. Install `libvulkan-dev` in the disposable compiler container,
then run `/bin/bash /workspace/scripts/build_epic_graphics_probes.sh`.

Execution mounts `/workspace` read-only and runs as `dpad`. The standard harness
is `/bin/bash /workspace/scripts/run_epic_update_probe.sh`. Apply an outer
120-second timeout for service comparisons or 600 seconds for official updates.
Use `--rm`; never attach user prefixes or credentials to these probes.

Service comparison flags:

```text
--backend dxvk --graphics-service-probe --direct-proton
--backend dxvk --graphics-service-probe --direct-proton --without-headless
--backend dxvk --graphics-service-probe --direct-proton --without-headless --interactive-service
```

For the patched target fixture, also use `--epic-service-identity`. This copies
the fake graphics probe to the matching updater path **only in its fresh test
prefix**, not over an installed official client. Do not use that option for the
real updater check. The comparison asserts both context reports and expected
device results; exit zero means the controlled comparison matched, not GPU
acceptance.

The fault ICD is validated only with direct Proton outside the Steam runtime.
Inside pressure-vessel its Mesa driver import produced `res=-9` in both contexts;
that was an invalid fault fixture, not an Epic result. The CLI refuses that
combination. Never include the fake executable or fault ICD in a gaming image.

`Dockerfile.faugus-epic-service` packages the narrow Wine patch into a local/private
candidate. It requires explicit `EPIC_WINE_BUILDER` and `EPIC_RUNTIME_BASE` build
arguments. Use immutable reviewed references before any publication. It checks
the exact Wine source revision before applying and building the patch, and
includes corresponding modified source and license files.

## Remaining acceptance

Do not promote or claim reliable login from these local results. A future,
separately approved GPU test must first verify the pinned image and NVIDIA ICD,
complete automatic official updating with DXVK, and reach a usable sign-in
window without manual renderer changes. Only then should the owner sign in.
Require responsive Library/Store, stable post-verification operation and two
clean reopen checks. Cross-VM login persistence and ABZÛ installation metadata
remain separate unverified work.
