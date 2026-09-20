# UpCloud Unix signaling image-source correction

**Source-only; no image build, registry push, commit, VM, or production change.**
Worktree: `/home/home/dpadplay-worktrees/upcloud-guest-tls-image`, branch
`fix/upcloud-guest-tls-image`, base `1928a6b2f75d3c21a14b5a0d033f27bdbeb0ee1a`.
See `HELSINKI-GUEST-TLS-INCIDENT.md` for the parent's incident and rollout record.

## Minimal production delta

- Port `scripts/dpad-patch-selkies-unix` byte-for-byte from the maintained
  `container-cleanup-fencing` worktree. Both server and local client require an
  absolute Unix socket; neither falls back to TCP. Basic auth stays upstream.
- Apply it in **both** `Dockerfile` and `Dockerfile.stock595`. The differential
  stock595 recipe does not execute the main Dockerfile; it needs its own hook.
- Add only `DPAD_SIGNAL_UNIX_SOCKET=/run/dpad-signaling/stream.sock` to the
  entrypoint's existing user-switch export. Removing that one substring restores
  the exact baseline entrypoint bytes. The NVENC preflight, scoped EGL/Vulkan
  environment, modern encoder wrapper/options, and driver logic are untouched.
- Change only the signaling probe in `healthcheck.sh` from TCP to a bounded Unix
  connect. Otherwise the image would report unhealthy despite a working private
  server, or incorrectly accept a separate host TCP gateway as Selkies health.
- Refresh the entrypoint checksum in `scripts/vm-bootstrap.sh` and clarify its
  existing incompatible-old-image warning. No bootstrap execution logic changes.
  Baseline stream checksum test passed; it failed after the export change and
  passed after this required checksum refresh.

No host gateway/controller was ported into the image. The integration test uses
an explicit external gateway exported from worker **501c5a4**, with SHA-256
`1e5ef5a3421630f231c76e29e286d790754a32155aebea16df49447da58392d8`.
The Selkies 1.6.2 wheel SHA-256 is asserted before extraction:
`f426ae093853492ecf857609efd4c9bd2141b24c619118561e42220927554eee`.
The tests need `websockets==13.1`, `basicauth==1.0.0`, and OpenSSL, not GStreamer
or a GPU. They import the actual wheel's server and local-client modules.

## Observed RED / GREEN

Tests were ported first, before production edits. Original-wheel RED:

```text
Selkies listeners: [('AF_INET', ('127.0.0.1', 44599))]
Selkies listeners: [('AF_INET', ('127.0.0.1', 41311))]
AssertionError: False is not true : Selkies opened TCP instead of its private Unix socket
Ran 4 tests in 0.080s
FAILED (failures=4)
```

The other failures were the missing socket export and main Dockerfile hook.
The differential-recipe hook then had its own RED, followed by GREEN.
The real-listener healthcheck tests separately failed in both directions before
changing its probe: live Unix/no TCP was unhealthy; live TCP/no Unix was accepted.

Final transport suite: **7 tests, no skips, all pass**, with deprecations fatal:

```text
Unix unauthenticated upgrade: HTTP 401
Verified WSS unauthenticated upgrade: HTTP 401
Verified WSS -> host gateway -> Unix Selkies: authenticated HELLO / SESSION_OK / offer relay passed
```

All actual Selkies listener families are asserted `AF_UNIX`. WSS validates the
fixture CA and DNS server identity; there is no disabled certificate check or
TLS bypass. The offer is a fixture payload relayed by real upstream signaling,
not generated video SDP, browser decode, or GPU evidence.

## Reproduction and evidence

```sh
DPAD_SELKIES_WHEEL=/absolute/path/selkies_gstreamer-1.6.2-py3-none-any.whl \
DPAD_GUEST_TLS_GATEWAY=/absolute/path/dpad-guest-tls-from-worker-501c5a4 \
  /path/to/venv/bin/python -W error::DeprecationWarning \
  -m unittest discover -s tests -v
```

Without explicit wheel/gateway selection the opt-in tests skip; that is not
upstream acceptance. The original unpatched wheel emits websockets deprecations,
so its transport RED was run without `-W error` to observe its actual TCP sockets.

Local artifacts: `/home/home/.cache/dpad-review-tmp/upcloud-guest-tls-image/`:

- `red.log`, `stock595-recipe-red.log`, `health-red.log`
- `green.log`, `baseline-quality.log`, individual regression logs
- `verify.py`, `verification.json`: exact commands, exits, counts, log hashes
- `source.patch`, `source-sha256.json`: reviewable delta and source fingerprints

Final verifier: **118 unittest tests; 0 failed commands**, plus successful
Dockerfile pin validation (including 12 rejected unsafe mutations), TURN plumbing,
launcher/desktop/Waybar source gates, shell syntax and `git diff --check`.
Selected CPU regression suites include all stock595 tests, both UpCloud profile
suites, stream FPS/quality/hotfix tests, host-driver policy and NVIDIA EGL runtime
fixtures. This is not the GPU suite or a complete image runtime test.

## Remaining acceptance boundaries

- No image is built or promoted. The old immutable image is unchanged and still
  incompatible. A future authorized build must inspect the actual patched wheel,
  baked entrypoint/healthcheck, and private socket permissions/mounts.
- This patch assumes the deployed worker supplies the session-private signaling
  mount and host gateway. Old TCP-only launchers/probes are not compatible; do not
  roll this entrypoint alone onto an old image or use legacy GPU probes unchanged.
- The retained entrypoint `DPAD_READY`/listening text still describes its legacy
  TCP bind and uses the existing process check. It is **not** Unix/TLS readiness
  proof. The parent owns control-plane readiness/diagnostic guards; transport and
  certificate activation must be positively verified before publishing a route.
- Root systemd lifecycle, gateway renewal/rebinding after a Selkies restart,
  end-to-end worker/bridge registration, GPU/browser/video/audio/input/reconnect,
  cleanup and billing remain future authorized acceptance work. No TLS key was
  mounted in a game process; no driver downgrade was made.
