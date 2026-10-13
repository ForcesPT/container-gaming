# Instant desktop environment fix

The owner-approved Paris test of Among Us7489 recognized the bare-metal files
in official Epic without another installation. The owner confirmed gameplay,
controls and audio. Exit observation produced the five-minute Play again screen.
Automatic initial launch and Play again failed before entering the store wrapper.

The live sanitized diagnostic found a valid sealed launch URI, no private desktop
environment receipt, and the fixed `Selected game replay unavailable` marker.
The entrypoint uses an owned sticky `1777` XDG runtime directory for desktop/audio
sockets, while the previous helper required that directory to be private `0700`.
The two real helper CLI regressions fail against the immutable published
`a19d2c40bae51e83fea55544e47b1a288245411ff664b1711b0f840ef0b004ef` image.

## Change

`dpad_instant_replay.py` retains the desktop XDG runtime and stores its operational
environment in a new owned `0700` `dpad-instant` child, with a `0600` receipt.
It accepts only an owned canonical runtime with mode `0700` or sticky `1777`.
It rejects shared/non-sticky parents, redirected or shared children, redirected
or hard-linked receipts, extra keys and invalid environment bindings. Existing
paths are never chmodded or chowned. The allowlist excludes credentials, account
state, client logs and the store URI. The corrected receipt is session-local.

`Dockerfile.instant-desktop-state` derives from the exact tested registration
image and replaces only this helper. No store, runner, driver, entrypoint,
registration parser, account profile or game file is rebuilt into the image.

## Local evidence

- Fourteen offline non-root tests pass: seven permission/validation cases,
  two real startup/replay CLI cases and five selected-game wrapper cases.
- The same two startup CLI cases fail against the original packaged helper.
- Fixtures contain no account data and use network `none`.
- Local runtime source `07c17a512a346a5cdccedf6c8eec5c8d260a89c1` builds image
  `sha256:85ae52ddadaed0e67049ec182a6e626ada49759c7accbe34562f54fbafae2f67`.
- The actual packaged helper passes the seven permission and two CLI cases;
  five wrapper cases pass against the unchanged, hash-verified launch wrapper.
- Base layers, all startup configuration fields and seven other runtime hashes
  match the reviewed image. Only the replay helper changes. All fixture containers
  were disposable and are removed.
- [Qualification receipt](qualification/instant-desktop-state-local-20261014.json).

This fixes the reproduced permission boundary. Genuine automatic launch through
fresh Epic sign-in and Play again still require a separately approved native
test. No new paid VM or publication is authorized by these local checks.
The previous test is closed: native VM and boot volume absent, zero complete
Paris inventory, billing finalized at $1.29, original settings restored, guard
disabled/inactive before its deadline. Control-plane closure receipt:
`instant-admin-release-20261003/docs/release-evidence-20261013/among-us-native-game-test.json`.
