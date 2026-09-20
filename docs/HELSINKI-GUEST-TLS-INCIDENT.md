# Helsinki Dedicated L4 — guest signaling protocol mismatch

## Incident (2026-09-17)

Session `68818121-79f5-4243-a027-03da5b69971a` reached a running UpCloud
`fi-hel2` / `GPU-12xCPU-128GB-1xL4` VM. Bootstrap completed at 02:04:14 UTC.
The gaming container reached launcher readiness, certificate issuance committed
at 02:05:05, and provisioning failed at 02:05:09 with
`session_provision_stream_registration_failed`. Customer GPU billing never
started; the final record contains zero GPU seconds. Session cleanup completed
at 02:05:16.

The deployed worker runs guest certificate installation/activation **before**
bridge registration inside the same sanitized error handler. Therefore that
failure code does not prove the bridge rejected a request. Bridge health and
worker/bridge token equality were verified; no session registration was logged.

Read-only, identity-pinned SSH inspection found the session-bound guest TLS
systemd service failed immediately with `DPAD_GUEST_TLS_UNAVAILABLE`. The
certificate remained `issued`, not `active`. Protected configuration/key/CA/leaf
files had correct root ownership, single links and mode 0600. OpenSSL validation
at the incident timestamp passed; Python loaded the leaf and matching host key.

The actual pinned image was:

`forcespt/dpadcloud-gaming@sha256:207c38a46a2a768698291a37f8073b7c4c0e0bed21e5b84253c44f7bc078882a`

Its source revision is `1928a6b2f75d3c21a14b5a0d033f27bdbeb0ee1a`.
Read-only image-layer inspection confirmed the entrypoint lacks
`DPAD_SIGNAL_UNIX_SOCKET` and starts Selkies using its public TCP bind/port.
The host launcher supplied `0.0.0.0:16100`, while the new TLS gateway also needed
that address and expected Selkies behind a private Unix socket. The session's
signaling directory was empty. The image's hash-pinned upstream Selkies 1.6.2
wheel was not transformed for the new Unix transport.

The original gateway exception text was suppressed. A local loopback reproduction
using the deployed gateway source reproduced its exact exit/diagnostic with the
TCP port occupied, and a same-config control passed CA+hostname verified TLS
when the port was freed. This establishes the incompatible transport contract;
it is not a historical stack trace or GPU gameplay test.

## Source fix scope

Base this correction on the **actual stock595 image source**, not the older
container cleanup branch wholesale. Port the maintained Unix signaling transform
for the upstream server and local client, wire it into image construction, and
preserve the private socket environment across the entrypoint's user switch.
Keep Basic authentication, host-only TLS key custody, certificate verification,
stock595 driver/codec handling and existing graphics/encoder behavior intact.
Missing Unix configuration must not silently fall back to plaintext TCP.

Unpaid tests exercise the hash-pinned upstream wheel, the maintained host TLS
gateway, authenticated WSS and the real local signaling client, rather than
asserting source text alone. They also cover the actual entrypoint command,
Dockerfile wiring and Unix-only healthcheck. The healthcheck must follow the new
socket rather than accidentally accepting the host TCP listener. Both Dockerfile
recipes apply the transform; the bootstrap entrypoint content hash is updated
without changing driver/codec policy.

Parent verification: seven transport/entrypoint/healthcheck tests passed with
zero skips, including authenticated WSS → deployed host gateway source → Unix
Selkies HELLO/SESSION_OK/offer relay and unauthenticated HTTP 401 denial. A separate
73-test stock595/release/driver/stream-quality run passed. The first invocation of
the broader set lacked `PYTHONPATH=scripts`; rerunning with the required import
path resolved that harness import error. These checks cannot certify a built
image, GPU rendering, or gameplay.

The direct GitHub v1.6.2 wheel URL and release-tag API returned 404 during this
investigation. Tests used the existing local cached wheel **after** confirming
its bytes match the Dockerfile SHA-256
`f426ae093853492ecf857609efd4c9bd2141b24c619118561e42220927554eee`.
A future fresh build must also resolve pinned upstream artifact availability;
do not substitute unverified wheels or claim the source test downloaded a fresh
release successfully.

## Build and rollout gate

The user initially authorized build/test on the existing failed VM and a reviewed
image/worker rollout, without creating a new paid VM. Before building began,
the scheduler's normal ten-minute idle drain claimed teardown. UpCloud's exact
server GET subsequently returned `404 SERVER_NOT_FOUND`, and the database
converged to `destroyed` with no remaining cleanup lease.

**Final user instruction:** finish and review the source fix; leave production
unchanged until another build host is authorized. No replacement VM, image build,
registry promotion or production rollout is authorized by this source patch.

Before a future rollout:

1. Obtain authorization for an existing GPU build/test host or a bounded new VM.
2. Build the reviewed immutable commit with the maintained control-plane
   `scripts/build-and-push-gaming-image.sh` on that same GPU VM; do not use the
   production VPS or a separate builder. Use a candidate tag, not a live tag.
3. Verify the **built artifact** has the matching Unix server/client and entrypoint
   behavior, then exercise real container → private socket → host TLS → bridge
   registration/activation and certificate renewal. Check unauthenticated denial,
   no plaintext TCP listener, isolated key custody, cleanup and billing boundaries.
4. Publish only the accepted candidate; update the immutable image reference and
   matching release manifest in the relevant control-plane roles. Preserve each
   live role's exact unrelated environment, mounts and image identity. Confirm
   API admission, worker bootstrap and scheduler paths agree on the same tuple;
   do not assume a worker-only environment edit is sufficient.
5. Retain immutable rollback references. Run a separately authorized website
   launch and distinguish transport readiness from actual user gameplay acceptance.

Do not replay or resurrect this terminal failed session or reactivate its old
certificate. No TLS bypass or NVIDIA driver downgrade is part of this fix.
