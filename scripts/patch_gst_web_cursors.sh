#!/usr/bin/env bash
# Idempotently inject the DPAD pointer-lock gate into the Selkies web client's
# input.js. Selkies auto-requests pointer lock on fullscreen + click, which
# HIDES the server-sent CSS cursor (browsers hide the cursor during pointer
# lock) and forces relative mouse. For Steam-UI/desktop navigation we want the
# visible server cursor + ABSOLUTE mouse, so pointer lock is disabled by
# default. Set window.DPAD_POINTER_LOCK = true in the browser console to
# re-enable pointer lock for an FPS game.
#
# Run at build time (Dockerfile) and/or boot time (entrypoint); idempotent
# (skips if the marker is already present). Safe to re-run.
set -u
FILE="${1:-/opt/gst-web/input.js}"
MARKER="DPAD pointer-lock gate"
if [ ! -f "$FILE" ]; then
    echo "patch_gst_web_cursors: $FILE not found — skipping" >&2
    exit 0
fi
if grep -q "$MARKER" "$FILE" 2>/dev/null; then
    echo "patch_gst_web_cursors: already patched ($FILE) — skipping"
    exit 0
fi
cp "$FILE" "${FILE}.orig" 2>/dev/null || true
SHIM='// === DPAD pointer-lock gate (auto-injected by patch_gst_web_cursors) ===
// Selkies auto-requests pointer lock on fullscreen + click, which HIDES the
// server-sent CSS cursor (browsers hide the cursor during pointer lock) and
// forces relative mouse. For Steam-UI/desktop navigation we want the visible
// server cursor + ABSOLUTE mouse. Default: pointer lock OFF. To re-enable for
// an FPS game, run in the browser console:  window.DPAD_POINTER_LOCK = true
(function () {
  if (window.__dpad_pl_patched) return;
  window.__dpad_pl_patched = true;
  window.DPAD_POINTER_LOCK = false;
  var _real = Element.prototype.requestPointerLock;
  Element.prototype.requestPointerLock = function () {
    if (window.DPAD_POINTER_LOCK) {
      try { return _real.apply(this, arguments); } catch (e) { return Promise.reject(e); }
    }
    // not locked: document.pointerLockElement stays null -> Selkies uses absolute
    // mouse ("m"), and the server-sent CSS cursor stays visible (even in fullscreen).
    return Promise.reject(new Error("pointer lock disabled (DPAD; set window.DPAD_POINTER_LOCK=true to enable)"));
  };
})();
// === end DPAD shim ===

'
printf '%s' "$SHIM" | cat - "$FILE" > "${FILE}.new" && mv "${FILE}.new" "$FILE"
echo "patch_gst_web_cursors: patched $FILE (pointer lock gated behind window.DPAD_POINTER_LOCK, default off)"