# Official Epic shared-game import on GE-Proton11-7

## October 2 local qualification

The private extension uses the exact published store base
`forcespt/dpadcloud-gaming@sha256:93fef1d0839b8b88c8f04dadc8abbf493746f9b44036535b626d97a782e62fe1`.
That base passed owner-assisted Epic sign-in, Store/Library navigation and
window reopening on Paris L4. The import extension is a separate candidate.

Only account-free game records were mounted for this qualification. Genuine
ABZU capture `8562197e-690b-4eee-9034-fa574d421863` matches the live shared
release's 14 files, 4,818,969,865 bytes, build `1.0`, app `Curry` and executable
`AbzuGame.exe`. Payload hash:
`a1b9a8af9df8ebfe4c338785f009a41eae8014120a07413f86fc5892e8658592`.
Vendor hash: `948f8707e8b3c24b43bc349386880ffe8b70896371cb5991b0c4915f8fa14b3c`.
Original sanitized capsule:
`7ac68a36c101d3eca98a0de7bfb9a60de9892c87616e4a40ca503267be014c6d`.

The new `rebind` command permits a fresh release UUID while requiring every
game/build/file binding to remain identical. It preserves the genuine item's
provenance hash and refuses overwriting a capsule. Existing immutable releases
must remain unchanged. This supports other Epic games with their own verified
official installation records; it does not invent missing records.

`test_epic_shared_records.py` passed actual packaged client preparation,
private FUSE registration and repeat startup using those genuine records.
A session-user save and atomic executable replacement affected only the
private view. All 14 shared files retained their payload hashes. The test used
the GE-Proton11-7 default, no network, no GPU, no signed-in prefix and no account.
The owner previously accepted local shared-file recognition/gameplay on the
earlier import image. No new GE11 gameplay or UI acceptance is claimed here.

Eleven non-root installation regressions and two capsule-rebinding tests
passed. Companion control-plane qualification passed the updated host mount
compiler, real PostgreSQL metadata transactions, sidecar staging/publication
and release verification. Receipts remain ignored under
`test-results/official-epic-recognition/` in the two release checkouts.

## Runtime changes

- The extension adds pinned `fuse-overlayfs=1.13-1` to the qualified base.
- Instant sessions require official installation pins; the former client-only
  fallback is disabled in this extension. Ordinary Cloud Compute still follows
  its normal store flow when no Instant request exists.
- The host supplies the game and two sidecars read-only plus `/dev/fuse`.
- A root-created private FUSE view is registered in the user's prepared Epic
  prefix before the picker starts. Account state stays in the private prefix.
- Each session has its own upper layer. Shared payloads and game records are
  never writable from a player container. Entitlement remains Epic's check.

## Release boundary

No registry push, deployment, catalog publication or paid VM occurred in this
work. The current public image is unchanged. Publish a private import canary
only after source/package review; coordinate it with the companion official
record worker/storage artifact. A new release with pinned sidecars is required.
Then qualify NFS-backed FUSE and actual Epic recognition/game launch in one
separately approved bounded provider test before public promotion.
