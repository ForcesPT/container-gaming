# Direct Epic Instant Play candidate

Published with owner approval on October 3 to
`forcespt/dpadcloud-gaming:official-epic-direct-canary-20261003-10f1991` at immutable
digest `sha256:8a18d043bccc4e6e2c65f44cf0d64e63d3abbb9bcf8830eac80e3e638245a4bf`.
Remote Linux manifest `e969f906…e7a0b` and index match the frozen image. Source is
recoverable on `canary/instant-epic-direct-20261003-10f1991`. This is a private
candidate; no public runtime binding was changed and no paid VM was started.

Instant startup with a qualified official Epic capsule now prepares the private
client, imports only the selected release and invokes official Epic with the
catalog launch URI derived from that sealed capsule. It does not open the store
picker. The protocol uses namespace, catalog item and artifact IDs; Epic handles
sign-in/ownership. The installed account-free template's protocol registry maps
the URI directly to `EpicGamesLauncher.exe %1`.

Cloud Compute Dedicated/Shared without Instant metadata retains the picker.
`launcher-toggle` restores only Epic for official Instant sessions: an existing
managed process receives the normal second-instance invocation; a free launch
lock starts the store without another game request. A busy lock with no matching
managed client fails, avoiding a second controller during updater/game activity.

`--instant` derives its URI from pinned session metadata, the sealed installation
capsule and root-owned overlay receipt. Caller-supplied URIs are discarded.
Faugus arguments quote the complete URI as one shell argument. Invalid imports,
selected-game mismatches or unqualified sessions fail closed.

Build the scoped derivative with `Dockerfile.epic-instant-flow` and an explicitly
pinned qualified Epic import image. The full `Dockerfile.epic-instant` also copies
these helpers for subsequent rebuilds. GE-Proton11-7 and the accepted transport,
DPoP/EOS fixes, private prefixes and writable overlay remain inherited. Other
store binaries remain in the derivative, though Instant invokes only Epic.

Local disposable tests cover startup, preparation, registration, exact URI,
argument quoting, lock ownership and restoration. They use client doubles and
do not replace a private provider test of fresh Epic sign-in and game activation.
This candidate must not replace the accepted ABZÛ runtime binding directly; the
control plane binds images immutably per release. Prepare a new tested release.

The companion control plane now has a generic official-install capture/bank
workflow and admits new Epic builds while retaining older published/pinned ones.
See its `docs/INSTANT-EPIC-FLOW-20261003.md` for preparation and promotion steps.

## October 3 provider check and local follow-up

One approved Paris L4 test (`67dfb0fb-a857-4f82-bb87-2c834b4ae278`) reached
official Epic directly, without a store picker. All 14 shared ABZÛ files (4.82 GB)
matched their accepted hashes; NFS/official records were read-only and the
session's overlay was writable. Epic recognized the game as Launch. The owner
signed in, launched it manually and confirmed controls and audio.

Closing Epic before sign-in revealed a missing recovery control. Source
`ced433e` adds a permanent Epic Games panel button using the existing validated
client-only restore route. A three-script same-VM patch was accepted by the
owner. This modified runtime test does not qualify a new immutable image or the
interrupted fresh-auth automatic game request. Cloud Compute keeps Stores.

Portuguese input exposed a stale python-xlib map. A static real-Xwayland check
reproduced US keycode 21 remaining cached after PT selection and verified that
the public mapping refresh resolves `=` to PT keycode 19. The local fix refreshes
before new Labwc presses, pairs releases/repeats with the original keycode, and
clears tracked keys on reset. It does not enable input logging. The selector and
input behavior checks pass offline; the new patch still needs runtime acceptance.

The session ended at 05:38:29 UTC. Native VM/boot deletion was verified at 05:43
UTC, within one hour from admission; the normal warm grace had to be skipped
with the exact fenced cleanup path. Wallet debit was $1.29. There are no remaining
paid test resources. Public image selection is unchanged.
