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
- Replacement image build, packaged checks and immutable configuration/layer
  comparison are recorded separately after completing the build.

This fixes the reproduced permission boundary. Genuine automatic launch through
fresh Epic sign-in and Play again still require a separately approved native
test. No new paid VM or publication is authorized by these local checks.
The previous test is closed: native VM and boot volume absent, zero complete
Paris inventory, billing finalized at $1.29, original settings restored, guard
disabled/inactive before its deadline. Control-plane closure receipt:
`instant-admin-release-20261003/docs/release-evidence-20261013/among-us-native-game-test.json`.
