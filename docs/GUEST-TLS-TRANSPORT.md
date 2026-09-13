# Guest TLS transport — local implementation only

The host gateway keeps the TLS private key outside gaming containers and forwards
HTTPS/WSS to a session-private Unix socket. Configuration and key custody checks
reject exposed files. Socket resolution rejects symlinks in every path component;
the selected inode remains pinned for the gateway lifetime. Replacing the socket
does not transfer the old gateway's authority. Leaf/issuer expiry bounds lifetime.
The session controller now creates a session-specific leaf under its protected
state directory and mounts only that leaf. The entrypoint exports the fixed Unix
socket path across the user switch, and the Dockerfile applies the transform.
These are source changes, not a built or installed image.

`dpad-patch-selkies-unix` adapts the pinned Selkies 1.6.2 signaling server and local
client to maintained websockets Unix APIs. The transformed code requires an
absolute `DPAD_SIGNAL_UNIX_SOCKET`, rejects in-container TLS mode and does not fall
back to TCP. HTTP/authentication/WS signaling remain upstream Selkies behavior.
No key is provided to Selkies. Patch application is wired into the Dockerfile; a candidate image is not built.

## Local proof

The latest explicit upstream run exercised 35 tests with no skips, including
gateway expiry on an established WSS connection, actual upstream signaling,
entrypoint command construction and session-control lifecycle tests.
The real Selkies server rejects unauthorized upgrades with 401 and exchanges
HELLO/session/offer messages with its real local signaling client, both directly
on Unix and through authenticated, certificate-verified WSS at the host gateway.
Deprecation warnings are errors in the verification command.

```sh
DPAD_TEST_USER_SYSTEMD=1 DPAD_SELKIES_WHEEL=/absolute/path/to/selkies_gstreamer-1.6.2-py3-none-any.whl \
  /path/to/venv/bin/python -W error::DeprecationWarning \
  -m unittest discover -s /absolute/path/to/this/repo/tests -v
```

The isolated venv needs websockets==13.1 and basicauth==1.0.0. The wheel hash is
checked before importing its signaling modules. Without explicit wheel selection,
the two upstream tests skip; that default run is not upstream acceptance.
See `guest-selkies-transport-verification.json` for source hashes and run evidence.

## Still open

The controller now supports `tls-start <slot> <session>`, validates the exact
running container and protected configuration (session/container/socket/port),
and durably records the session-specific systemd stop obligation before start.
Stop refuses to remove the container if gateway stop fails. These systemd calls
were tested through explicit local shims; the template passes systemd-analyze
verify but is not installed or runtime-certified. The template disables automatic
restart, so a successor socket cannot silently acquire the previous authority.

Worker now vendors/pins the gateway and unit in the actual installation commands;
the installer passed sandbox execution. A real transient user-systemd run also
proved gateway start, certificate-verified HTTPS forwarding, and stop; no test
units remained. This is not production root-unit/image acceptance.

The controller now also supports `tls-csr <slot> <session>` and
`tls-install <slot> <base64-public-certificate-payload> <session>`. The CSR uses
one private, protected host key outside signaling mounts. Installation verifies
CA/hostname/key/SPKI and publishes session-bound configuration only after the
certificate files are durable. Changed configuration restarts the TLS context;
completed and pending configuration hashes remain separate for crash recovery.
Identical activation replay does not restart a healthy unchanged context.

The real transient user-systemd test now runs CSR generation, installation,
HTTPS peer-certificate verification, a second certificate installation/restart,
verification of the actual new peer certificate, and stop. Docker identity is a
fixture in this test; the root service template and a built GPU image are not
runtime-certified. The latest controller changes are not yet in worker assets.

The main control plane now implements database route authority and authenticated
bridge HTTPS/WSS callers; their component tests are not whole-area acceptance.
Root-service/image acceptance and worker issuance/install/activation/renewal
orchestration remain open. The endpoint must not be published
merely because these local fixtures pass. First connection pinning is not an
independent session enrollment proof; the controller/activation path must bind it.
No image build, GPU test, provider mutation, deployment or production CA occurred.
Release remains NO-GO.
