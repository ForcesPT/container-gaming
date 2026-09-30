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

Packaged locally from source `fcae0b1` as `dpadplay/faugus-epic-service:local`,
image `sha256:94ec2a1002af15a65e2f88a11815ff21951b0f002409d42bd9330631f05b6b37`.
Its qualification label is `official-epic-service-local-candidate`.
The packaged PE SHA256 is
`49254510115d8d913e898efedcd07b91a69ea755d9b981defc6f3afef15e303f`.
It differs from the directly tested PE in four bytes only: the COFF build
timestamp and PE checksum. After zeroing those two metadata fields, all bytes
match. This verifies the packaged code without claiming a new GPU run. No push
was performed. Docker's two default-FROM argument warnings reflect the explicit
base-reference requirement; both supplied bases resolved to the reviewed local
digests during this build.

## Remaining acceptance

Do not promote or claim reliable login from these local results. A future,
separately approved GPU test must first verify the pinned image and NVIDIA ICD,
complete automatic official updating with DXVK, and reach a usable sign-in
window without manual renderer changes. Only then should the owner sign in.
Require responsive Library/Store, stable post-verification operation and two
clean reopen checks. Cross-VM login persistence and ABZÛ installation metadata
remain separate unverified work.

## EOS service identity: 2026-09-30 local follow-up

The earlier `spawn UNKNOWN` result was not the persistent failure in this run.
The current bundled installer installed EOS 5.8.0 successfully. The installed
service had name `EpicOnlineServices`, display `Epic Online Services`, type
`0x10`, account `LocalSystem` and the exact default host path. Its Windows
service child nevertheless reported `isSystemUser: false`, selected `starter`,
and exited 91 with `STARTER_INIT_ERROR` / missing `EOS_SESSION_GUID`.

Inspection of pinned Wine's `service_start_process` showed ordinary
`CreateProcessW` regardless of the configured LocalSystem account. A disposable
native token proof confirmed `NtCreateToken` plus `CreateProcessAsUserW` could
provide the System SID without changing the Linux user. The combined patch
`patches/wine-epic-services.patch` retains the earlier updater desktop exception
and adds this identity change only when all five EOS checks match: service
name, display, exact quoted/unquoted host binary, own-process service type and
LocalSystem account. Failure to create its token fails the start rather than
silently falling back to the wrong identity. Other services keep Wine's current
behavior. No invented GUID, development-mode EOS, credential bypass or modified
Epic executable is used. This is a Wine compatibility change, not a claim of
complete native Windows service-session emulation.

The installed prefix contains a copied `services.exe`, not a link to the runner
payload. An initial hot-copy into the runner alone did not update the retained
prefix; its results do not qualify the patch. The actual acceptance used a
newly built local image and a **fresh** prefix, whose copied service PE SHA256
was `05f9926b559e14df0abcc9a479d62dff7ce89145770b87ddf138ceac5fbd8826`.

That fresh Faugus/UMU/DXVK run completed the official launcher update and EOS
installer automatically. Vendor evidence showed:

- EOS installer return code 0 and the installed service host present.
- System service child metadata `isSystemUser: true`.
- `DC_UPDATE_SUCCESS`, main-service readiness, and service-host exit 0.
- No missing-GUID, starter-initialization or minimum-version failure.
- Current launcher manifest, successful update commandlet and up-to-date marker.
- A visible official sign-in page, without changing graphics backends.

The page accepted a pointer click in its email field and a dummy
`qa-input-check` string; the text was cleared and never submitted. These are
headless local Labwc/software-Vulkan results. No account was used. Screenshots
are local QA artifacts under `test-results`, not files included in the image.

The native SCM fixture `scripts/epic_service_identity_probe.c` creates a fake
executable **only in a fresh test prefix**. It refuses to overwrite an installed
host. Exact target case 0 reports System identity; five independent controls
(wrong name, display, binary, account or service type) report ordinary identity.
The fixture and its six JSON reports passed. Build it in the pinned compiler:

```text
x86_64-w64-mingw32-gcc -Wall -Wextra -Werror -O2 \
  /workspace/scripts/epic_service_identity_probe.c \
  -o /workspace/test-results/epic_service_identity_probe.exe -ladvapi32
```

Run `scripts/run_epic_service_identity_probe.sh` via `xvfb-run -a /bin/bash` as
`dpad` in an `--rm` candidate container with a read-only workspace mount and
120-second outer timeout. It asserts all six reports and removes its prefix.
The fake executable is never packaged into the gaming image.

The real-updater probe now reports EOS evidence as booleans without exposing
environment values or account material. Optional `--hold-prefix-seconds` is
bounded to 1,800 seconds for account-free diagnostics only. Increase the outer
container timeout accordingly; signal completion with the exact temporary
root's `end-diagnostic-hold` file. Always use `--rm` and no user state mounts.

### Restore dispatch

UMU defaults to Proton's `waitforexitandrun`, which waits for the Wine server
before invoking the client. A second-instance restore needs `run` instead.
An experimental `PROTON_VERB=run` change did not qualify restoration of the
minimized pre-login window and was reverted. The existing UID, private-prefix,
marker, exact-executable and updater exclusion checks remain, and their six
tests passed. Ordinary fresh launches and restore behavior remain as in the
reviewed base. This candidate changes only Wine's service implementation.

Minimizing the pre-login window under local Labwc did not automatically reveal
it through second-instance dispatch; compositor focus restored it. This does
not qualify hidden-window restoration in production Sway. The GPU test must
verify the actual picker action after account login. Do not claim the local
minimize experiment as a successful hidden-window acceptance.

A clean local close/reopen reached sign-in again without a renderer change.
An additional two-cycle assertion did not pass: the observed client did not
exit within the 20-second close wait. Repeated close/reopen is therefore still
unqualified. The bounded diagnostic container subsequently ended and was
removed automatically. Do not describe this as two successful reopen checks.

### Next GPU acceptance

This candidate addresses the two concrete local startup failures. Publication
and a new bounded VM require new owner authorization. Verify the immutable
digest and NVIDIA ICD first. Require automatic fresh startup and EOS success
without manual renderer changes, then owner sign-in, stable verification,
responsive Store/Library and two signed-in picker reopen checks. Stop the test
if those pre-login gates fail; do not repeat account login attempts. Shared
ABZÛ installation metadata and cross-VM account persistence remain later work.

### Final local package receipt

- Source: `cc952c5c58a29a8984c7276229813ce8aa48bb9b`.
- Local tag: `dpadplay/faugus-epic-eos:local`.
- Image: `sha256:cc58f0f2fa167ba464a4c5634076d3e8720e07f890118692fa332a26ff27f4ff`.
- Qualification: `official-epic-service-local-candidate`.
- Packaged service PE: `05f9926b559e14df0abcc9a479d62dff7ce89145770b87ddf138ceac5fbd8826`.
- Reviewed-base wrapper retained: SHA256 `c7946062f8a9e048f125b81f72aecee4526bfe5522b067dc750f010e61d508e4`.

The packaged service PE exactly matches the fresh-prefix real-Epic run, not
just a normalized comparison. All six native SCM reports passed again against
this final image: case 0 System, cases 1–5 ordinary user. Source label and
payload hashes were inspected. The source/patch/licenses are included in the
image. Both account-free Epic diagnostic containers and the scope fixture were
removed; no user state was attached. No push or paid resource was created.

This is ready for a **focused GPU startup/login acceptance test**, not public
promotion or a claim that repeated reopening already works. Publish only as a
private canary after owner authorization. Check pre-login gates before asking
for account input, and record reopening failures separately from startup.
