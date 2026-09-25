# Instant Play private signaling image candidate

The 2026-09-25 ABZÛ canary reached `DPAD_READY` with the immutable gaming image
`forcespt/dpadcloud-gaming@sha256:c5fa2556c232dbf2cfb4e031aa215fade1a5ca233090ba98cf03dbd93a1142dd`,
then failed before its guest certificate activated. That image runs Selkies on
TCP, while the current host gateway expects `/run/dpad-signaling/stream.sock`.

This branch begins at the exact canary image source revision
`657b10baccd0f70b37f2af10f908e61e2415f9b2`. The base image's baked
`entrypoint.sh` and `healthcheck.sh` SHA-256 hashes matched that revision before
editing. `Dockerfile.instant-unix` is a scoped derivative of the exact immutable
base. It preserves all Epic, Heroic, launcher, driver, and game content. It
applies the previously verified Selkies 1.6.2 Unix signaling transformation,
exports the socket through the entrypoint's user switch, and probes the socket
before `DPAD_READY` or image health can succeed. The main `Dockerfile` also
contains the transformation hook for a later full rebuild.

Local unbilled verification:

- `Dockerfile.instant-unix` built successfully from the exact base digest.
- The derived image's actual Selkies server had only `AF_UNIX` listeners.
- Unauthenticated Unix and WSS upgrades returned HTTP 401.
- An authenticated HELLO, SESSION_OK, and fixture offer relayed through the
  current worker's host TLS gateway and the Unix socket.
- 20 focused launch, quality, hotfix, and TURN checks passed in Linux.

The local handshake is signaling evidence, not decoded GPU video or Epic game
acceptance. The candidate was published without selecting it in production:
`forcespt/dpadcloud-gaming:instant-unix-20260925-937ed8c` resolves to exact
digest `sha256:056eb3a0bd2ec139030519e17e2914ef5261aa1b267adee4be952b4389e2c3c2`
with a Linux amd64 manifest. Its source revision label is
`937ed8c5f79ffbe93b111406477fec011ba1652c`. The companion worker branch
adds precisely this digest to the baked-Unix-image allowlist. Its 15 host
controller fixture tests verify that only the stale stream-hotfix mounts are
removed for this image, and that unrelated image references retain their mounts.

Before production selection, build and review the scoped worker release from
the companion branch, then run a separately bounded Paris canary through
gameplay, billing, and complete server/boot-volume cleanup. The old entrypoint
overlay must never shadow this image in that release.
