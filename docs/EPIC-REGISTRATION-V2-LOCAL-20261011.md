# Version-two Epic registration reader

October 11, 2026. Local candidate only; no image publication, provider VM or
production image selection.

- Runtime source `f1f0f239003adbdbf2516dbb3c50ebade364e4d2`.
- Local image `sha256:a19d2c40bae51e83fea55544e47b1a288245411ff664b1711b0f840ef0b004ef`.
- Reviewed base `sha256:acddbe8e16b17ae1f84dfebaa5d85952bebe5c2ca0e45ce758a70887599bb2c7`.
- The offline derivative changes only the public installation reader and labels;
  base layers and full startup/runtime contract are preserved.
- Version-one captured records remain supported. Version two explicitly records
  vendor-derived provenance and the canonical owned-catalog/build/manifest source
  digest. No captured-installation attestation is invented.

Fourteen tests passed against the actual packaged reader, non-root, offline and
with read-only image storage. They include version-two registration/launch URI,
source tampering and existing version-one/private-path behavior. Eight selector,
two input-routing and two real X11 mapping cases passed; packaged keyboard bytes
and startup contract match the reviewed base. This preserves local software input
evidence, not native NVIDIA/Wayland/WebRTC or provider acceptance.

The first build carried a mistaken source-revision label and is not accepted.
The corrected build uses the actual full Git revision above. No registry upload
occurred. Logs and receipts are retained under
`test-results/epic-registration-image-20261011` and
`test-results/epic-registration-input-20261011-1`.

The control-plane integration is in the companion release checkout. New derived
releases may select only an approved image explicitly declaring `vendor-v2`.
Publishing this candidate and resolving its immutable registry reference remain
deployment steps. Existing ABZU runtime selections stay unchanged.
