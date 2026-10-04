# Fresh official client windows, local check

October 4, 2026. Compute runtime source `5ac9167`, image
`sha256:d6bf574a817a0d38f0a33c930249f44472b7ec5108a4cf1b9c7b9840e2157688`.

## Result

Official Epic, GOG Galaxy, Battle.net, EA App, Ubisoft Connect and native Steam
each displayed a fresh sign-in window. Closing their window and requesting the
client again through its maintained wrapper reopened the expected sign-in window.
Windows clients used GE-Proton11-7. No account input or sign-in submission occurred.
Epic reopening used its normal `--open` action, which restores the existing
client; an initial diagnostic invocation of `--launch` was corrected.

Each client ran in a separate fresh disposable container, with no owner mounts,
accounts or copied private profiles. The viewer bound only to `127.0.0.1:5812`.
All six exact container identities and their anonymous volumes were removed,
and the temporary browser viewer was closed. Private client logs stayed inside
their disposable containers and were not exported. Steam evidence crops out its
transient sign-in QR ticket. Twelve screenshot hashes are retained in the
[sanitized receipt](qualification/official-store-windows-local-20261004.json).
The screenshots remain in the local ignored test-results directory.

## Scope

The local test adapter is
`sha256:5d7fdfa0b222e444b3e98c798c1ffcf4b5c53356fea4bb107d0ad9f2e167243c`.
It preserves the Compute image's layers and adds Xorg dummy, Openbox and noVNC
for inspection. Mesa software rendering was used. Cold first starts sometimes
took several minutes to download or initialize the official client.

This is client-window startup/reopening evidence. It does not qualify the
production Wayland compositor, NVIDIA encoder, WebRTC, audio, full picker/client
interaction, fresh account login, cloud-save restoration, game launch or Shared
isolation. Earlier owner-assisted account tests remain historical evidence and
are not reclassified as checks on this successor.

No image was pushed, no production setting changed and no paid resource was
created. Native qualification remains required before promotion.
