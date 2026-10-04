# Local selected-game normal shutdown helper

October 4, 2026. Final runtime source `6fb4bb2`, private immutable image
`sha256:b266313d4460e8b42236a5f4db51f824d204dc263cc494fb0d4ed134d7031063`.
Base `3442ee78` (reviewed local replay candidate) and its runtime configuration
are preserved. No image publication, production activation or paid VM.

The helper validates the sealed selected release and private desktop environment.
Only the exact selected executable/private-prefix/UID process qualifies. It reads
X11 window PID and supported normal-close protocol, grabs the server to exclude
window reuse, then re-resolves a fresh process object and creation time before
sending `WM_DELETE_WINDOW`. A cached psutil creation time is insufficient; the
final source explicitly resolves a fresh instance. No foreground/title fallback,
process kill, account log or credential/save export is used. A request is an
opportunity to exit normally, not proof of game exit or cloud synchronization.

The root host owns cancellation, a fixed journaled grace deadline and eventual
immutable-ID stop/removal. The companion control plane's policy and exact-image
allowlist default off. Native controller/lifecycle/helper artifacts must be
qualified and admitted together. [Coordinator evidence](../../instant-admin-release-20261003/docs/INSTANT-SHUTDOWN-LOCAL-20261004.md).

Twenty-five non-root offline packaged helper/wrapper cases pass, including three
real Xvfb/X11 protocol cases and an actual disposable process identity check.
Normal-close messages arrive without destroying either window. PID/protocol/
process mismatches send no request. Five packaged helper hashes match source,
base layers/environment/entrypoint are preserved, and disposable containers are
removed. Receipt: `qualification/instant-shutdown-image-local-20261004.json`.
The earlier 24-case image (`dcb4cfd5`) was a preliminary checkpoint and is not the
final candidate.

Genuine Wine/game close, confirmation-dialog handling, store sync and fresh save
restoration, production NVIDIA/encoder/transport and provider acceptance remain
unqualified. The helper neither accepts game dialogs nor reports synchronization
success. Continued shutdown after its bounded opportunity may discard local
progress that the store has not uploaded; the customer warning must remain.
