# Direct Epic Instant Play candidate

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
