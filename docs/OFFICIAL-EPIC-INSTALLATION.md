# Official Epic installation recognition candidate

The accepted official-client image is `forcespt/dpadcloud-gaming@sha256:cc58f0f2fa167ba464a4c5634076d3e8720e07f890118692fa332a26ff27f4ff`. Login and reopening the library passed on Paris L4. Game recognition is a separate qualification step. This candidate has not yet recognized or launched ABZÛ in the official client.

## Per-game records

Capture a completed installation's official `.item` and its actual `.egstore` vendor manifest. Export only the allowlisted public installation fields with `scripts/dpad_epic_installation.py export`. Never copy the account prefix, login state, cookies, passwords or tokens into a shared release or Docker image.

The export binding contains the release UUID, payload manifest SHA-256, vendor manifest SHA-256, Epic app name, exact build version, executable and install size. Export refuses incomplete installations and mismatched records. The resulting `installation.json` and `vendor.manifest` form the release's `epic/` sidecar directory. Its hashes are stored in optional `launchMetadata.official_epic` on a newly prepared release. Existing immutable releases must not be changed in place.

The storage worker accepts these files under `<plans>/<release UUID>/official-epic/`. Its plan contains the same `official_epic` hashes and public runtime metadata. Inspection binds records to the decoded vendor build; publication also binds them to the verified payload manifest. Publication and later verification include both sidecars. Releases without this optional field retain their existing contract.

## Session storage

`Dockerfile.epic-instant` extends the accepted client image and adds pinned Ubuntu FUSE overlayfs 1.13-1. The trusted host passes `/dev/fuse` only when an official-record binding is present. Shared payload and sidecar binds stay read-only.

The root entrypoint validates these records and creates a private FUSE view at `/opt/dpad-instant/official-game`. Its upper/work directories live inside the disposable container. The launcher registers the completed installation into that user's Epic prefix, with a Windows path to this private view. Updates, installation metadata and saves affect the private view. The existing scratch storage limit and dedicated-disk admission contract still apply. Destroying the session container discards private writes.

An account still must own the game and sign in to official Epic. Recognition does not bypass entitlement checks.

## Local evidence and remaining gates

September 30 local checks: six export/register fixture tests; ten host mount tests; fourteen Linux sidecar/release tests; two vendor/runtime binding tests; database build and worker typecheck; a 52-file artifact digest check; and actual FUSE storage plus non-root registration in a disposable container. The FUSE test replaced a game executable and wrote a save while the lower files, modes and directory contents stayed unchanged.

September 30 unattended follow-up: the export/register suite now has ten tests.
Registration takes a private, bounded per-prefix lock so simultaneous game
imports cannot lose each other's inventory entries. Existing inventory, item,
manifest and drive-mapping conflicts are checked before publishing any game
record. The inventory size limit is checked before writes. New records are
written and synced privately before an exclusive link publishes them, so a
failed write cannot expose a partial item or overwrite an existing record.

The concurrent two-process test holds the first import immediately before its
inventory commit, verifies the second waits, then verifies both games and an
existing unrelated entry survive. Conflict tests verify no game mapping, item
or manifest is created and the existing inventory is byte-identical. Injected
publication failure leaves no partial file. Symlink/public-lock cases fail
without changing their targets. Run as the non-root session user:

```bash
python3 -I scripts/test_epic_installation.py
```

The updated helper also passed the actual disposable FUSE overlay test, including
non-root registration, executable replacement, private save creation and
unchanged shared-lower bytes/modes. Evidence:
`test-results/epic-registration-hardening-fuse.log`. No account or real vendor
manifest was involved. These changes are a source-only recognition candidate;
the qualified six-store image and public profiles were not changed.

Registration must run before the official client starts. The per-prefix lock
coordinates our importers; it does not coordinate Epic's own inventory writer.
An interrupted import can be replayed because matching records are retained;
this is not an all-files filesystem transaction.

Fixtures are synthetic and do not prove Epic UI acceptance. Kernel overlay failed with a Docker writable upper layer, so this candidate uses FUSE. NFS-backed FUSE, genuine ABZÛ record compatibility, official-client recognition, game launch, update behavior and GPU performance still require qualification. No new import image is published or promoted by these local results.
