# Local keyboard and corrected startup candidates

October 4, 2026. Runtime source `5ac9167204097330dc7f4ea6f3c24e3ec8ec2afc`.
All builds and packaged checks below ran locally, offline, without accounts,
production changes or a paid VM.

## Corrections

- Both Sway XTest and Labwc input paths refresh the X11 keyboard map before a
  new press, retain the original keycode until release, and release held keys on
  reset. Native Wayland routing is unchanged.
- The searchable selector supports Sway through an owned, canonical IPC socket.
  It accepts only an unambiguous successful compositor reply. Failure restores
  the previous saved layout and makes one bounded attempt to restore it in the
  compositor. Labwc has the same rollback behavior.
- Desktop publication preserves the catalog-validated saved layout. Sway exposes
  the selector with Ctrl+Alt+L. Labwc retains its existing taskbar selector.
  This does not add a Sway taskbar or qualify fullscreen taskbar stacking.
- Both maintained image builders package the selector and desktop publisher
  together. The offline input derivative packages their reviewed bytes.

## Compute startup correction

The previous Compute candidate `a1efea01` is withdrawn. Its builder changed the
accepted base's default startup user from root to dpad. The root entrypoint must
initialize services before launching clients as dpad. Earlier fixtures explicitly
ran as UID 1000 and compared environment and entrypoint, so they missed this
startup contract difference. Their picker behavior evidence remains valid in that
limited scope.

The corrected builder preserves root. Both packaging qualifiers now compare
User, Cmd, WorkingDir, StopSignal, Healthcheck, Volumes and ExposedPorts as well
as environment, entrypoint and base layers.

## Local artifacts and retained evidence

| Artifact | Local immutable image ID | Evidence |
| --- | --- | --- |
| Corrected Compute picker | `sha256:a9ea464f87d488ed569da10fb8bcb77c4a38d7a7c219c78a85a1d14f92192c99` | [8 packaged cases](qualification/compute-picker-startup-user-local-20261004.json) |
| Instant keyboard successor | `sha256:acddbe8e16b17ae1f84dfebaa5d85952bebe5c2ca0e45ce758a70887599bb2c7` | [12 packaged cases](qualification/instant-input-local-20261004.json) |
| Compute keyboard successor | `sha256:d6bf574a817a0d38f0a33c930249f44472b7ec5108a4cf1b9c7b9840e2157688` | [12 packaged cases](qualification/compute-input-local-20261004.json) |

Each keyboard image passed eight selector cases, two routing scenarios and two
real X11 mapping scenarios. The last scenarios use the actual packaged Selkies
receiver, XTest, Xvfb and setxkbmap while the receiver connection stays open.
US to Portuguese to US produces the expected equals sign; held-key release and
reset remain correct across changes. The Labwc scenario deliberately exercises
its XTest fallback. It does not qualify the native Gst Wayland seat, WebRTC or
NVIDIA media.

Eighteen maintained desktop/helper cases pass, including saved Portuguese layout
publication. An initial fixture bypassed normal entrypoint ownership initialization
and encountered its baked home directory permissions. The fixture now uses owned
disposable layout state; no customer profile or runtime permission workaround was
introduced. All disposable test containers were removed.

## Remaining acceptance

Native browser keys, selector rendering, official client close/reopen, game
fullscreen, media, Shared isolation and genuine cloud-save restoration remain
open. These local image IDs are not published repository references. Before a
rollout, qualify and admit the exact published runtime and its reviewed host
overlay policy so legacy mounts cannot shadow these packaged helpers.
