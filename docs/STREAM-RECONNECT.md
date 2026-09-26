# Selkies browser reconnect candidate — 2026-09-26

Status: locally built and validated; not published or deployed. The current live
certificate policy recovered in 13 seconds during one observed renewal. This
candidate has no measured GPU reconnect time yet.

## Changes

- Fix the undefined `checkconnect` comparison in Selkies 1.6.2. Audio and video
  reset their own peers independently, avoiding mutual disconnects.
- Retry failed signalling at 250, 500, 1000, 2000 and then 3000 ms. Keep one timer,
  retry without page navigation, and reset backoff after HELLO registration.
- Ignore events from replaced sockets and replaced WebRTC peers.
- Remove the fixed three-second wait before rebuilding an unstable peer.
- Reject unrecognized pristine signalling/WebRTC source by SHA-256. Validate
  all three transformations before writing any file; repeated application is safe.

Certificate pinning, expiry, revocation and the gateway restart remain unchanged.
An interruption is still expected during rotation; seamless renewal is not claimed.

## Reproduce

Run from this repository:

```sh
docker build -f Dockerfile.reconnect -t dpadcloud-gaming:reconnect-local .
docker run --rm --network none --entrypoint python3 -v "$PWD:/candidate:ro" forcespt/dpadcloud-gaming@sha256:056eb3a0bd2ec139030519e17e2914ef5261aa1b267adee4be952b4389e2c3c2 /candidate/tests/test_selkies_reconnect_patch.py /opt/gst-web
```

The build runs the Node lifecycle checks against the actual patched browser files.
The Python suite checks supported source, idempotence, unsupported source rejection
before any write, and detection of upstream changes. All checks passed locally.

`Dockerfile.reconnect` pins the exact production gaming base and adds only this
browser repair. It excludes the pending Heroic GE-Proton discoverability change.
The main Dockerfile also includes the transform for future full image builds.

## Next acceptance

Publish the scoped image and prepare its exact digest in the control plane.
Use a separately authorized bounded GPU canary to observe one certificate renewal,
record audio/video recovery time and check for a second disconnect. End the session
and confirm the provider VM and boot volume are absent. Local lifecycle checks
do not prove GPU recovery or game launch.

## 2026-09-26 cache delivery correction

The gateway reload canary applied a browser patch inside its disposable container,
but a normal reload retained the original retry logs. The pinned PWA cache uses
`1723709107` for its namespace, cached scripts, HTML script URLs and worker
registration. The patch now advances all of these entry points together to
`dpad-reconnect-20260926-v2`, so a cached old script cannot match a new request.
Source validation for HTML and the service worker occurs before any file write.
The Python suite checks matching versions, repeated application and rejection of
unknown cache source without partial writes. Node image gates verify all script
URLs and worker registration agree with the new cache namespace.

The current paid test ended at 03:52:54 UTC. Server and boot volume both returned
404 at 03:53:47 UTC. Its three renewals proved stable gateway PID/start time;
client interruptions were 41, 9 and 9 seconds. The third renewal cannot qualify
the patched client because the PWA still delivered old retry behavior. A new
immutable-image canary is required before claiming combined live acceptance.
