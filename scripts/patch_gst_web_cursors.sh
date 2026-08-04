#!/usr/bin/env bash
# Idempotently inject the DPAD pointer-lock gate into the Selkies web client's
# input.js. Selkies auto-requests pointer lock on fullscreen + click, which
# HIDES the server-sent CSS cursor (browsers hide the cursor during pointer
# lock) and forces relative mouse. For Steam-UI/desktop navigation we want the
# visible server cursor + ABSOLUTE mouse, so pointer lock is disabled by
# default ("Desktop mode").
#
# FPS games need relative mouse (pointer lock) to aim. Instead of requiring
# the browser console, a "Gaming mode" toggle is injected: press Ctrl+Shift+G
# to flip window.DPAD_POINTER_LOCK (a badge shows the state). In Gaming mode,
# clicking the stream locks the pointer (relative mouse / camera aim); Esc
# releases it. The Selkies Ctrl+Shift+LeftClick hotkey also honors the gate.
# window.DPAD_POINTER_LOCK = true/false still works from the console too.
#
# Run at build time (Dockerfile) and/or boot time (entrypoint); re-runnable
# (strips any prior DPAD shim block, then injects the current one).
set -u
FILE="${1:-/opt/gst-web/input.js}"
# The image bake injects an earlier shim into input.js at BUILD time, so the
# marker is already present at boot. Re-injecting by prepending would stack two
# shims and the window.__dpad_pl_patched guard would no-op the new one. So:
# STRIP any previously-injected DPAD shim block first, then inject the current
# one. Safe: only deletes when BOTH start+end markers are present (won't nuke
# the file on a half-injected state). Handles multiple stacked blocks too.
START_MARK="=== DPAD pointer-lock gate"
END_MARK="=== end DPAD shim ==="
if [ ! -f "$FILE" ]; then
    echo "patch_gst_web_cursors: $FILE not found — skipping" >&2
    exit 0
fi
if grep -q "$START_MARK" "$FILE" 2>/dev/null && grep -q "$END_MARK" "$FILE" 2>/dev/null; then
    cp "$FILE" "${FILE}.orig" 2>/dev/null || true
    sed -i "/$START_MARK/,/$END_MARK/d" "$FILE"
    echo "patch_gst_web_cursors: stripped previous DPAD shim from $FILE"
elif grep -q "$START_MARK" "$FILE" 2>/dev/null; then
    echo "patch_gst_web_cursors: WARNING: start marker present without end marker — not stripping (would nuke file); injecting after" >&2
fi
cp "$FILE" "${FILE}.orig" 2>/dev/null || true
SHIM='// === DPAD pointer-lock gate (auto-injected by patch_gst_web_cursors) ===
// Selkies auto-requests pointer lock on fullscreen + click, which HIDES the
// server-sent CSS cursor (browsers hide the cursor during pointer lock) and
// forces relative mouse. For Steam-UI/desktop navigation we want the visible
// server cursor + ABSOLUTE mouse. Default: pointer lock OFF ("Desktop mode").
// FPS games need relative mouse to aim: press Ctrl+Shift+G to toggle Gaming
// mode (a badge shows the state); in Gaming mode click the stream to lock the
// pointer, Esc releases. window.DPAD_POINTER_LOCK = true/false still works.
(function () {
  if (window.__dpad_pl_patched) return;
  window.__dpad_pl_patched = true;
  window.DPAD_POINTER_LOCK = false; // Desktop mode by default

  var _real = Element.prototype.requestPointerLock;
  Element.prototype.requestPointerLock = function () {
    if (window.DPAD_POINTER_LOCK) {
      try { return _real.apply(this, arguments); } catch (e) { return Promise.reject(e); }
    }
    // not locked: document.pointerLockElement stays null -> Selkies uses absolute
    // mouse ("m"), and the server-sent CSS cursor stays visible (even in fullscreen).
    return Promise.reject(new Error("pointer lock disabled (DPAD; press Ctrl+Shift+G for gaming mode)"));
  };

  // --- on-screen mode badge ---
  var badge = document.createElement("div");
  badge.id = "dpad-mode-badge";
  badge.style.cssText = "position:fixed;top:8px;right:8px;z-index:999999;font:12px/1.4 sans-serif;" +
    "padding:4px 8px;border-radius:6px;color:#fff;background:rgba(0,0,0,0.6);" +
    "pointer-events:none;opacity:0;transition:opacity .25s";
  function showBadge(txt) {
    badge.textContent = txt;
    badge.style.opacity = "1";
    clearTimeout(showBadge._t);
    showBadge._t = setTimeout(function () { badge.style.opacity = "0"; }, 2500);
  }
  function ready() {
    if (!badge.parentNode && document.body) document.body.appendChild(badge);
    showBadge(window.DPAD_POINTER_LOCK
      ? "\uD83C\uDFAE Gaming mode ON \u2014 click to lock, Esc to release"
      : "Desktop mode \u2014 Ctrl+Shift+G for gaming mode");
  }
  if (document.body) ready(); else document.addEventListener("DOMContentLoaded", ready);

  function setGamingMode(on) {
    window.DPAD_POINTER_LOCK = on;
    if (!on && document.pointerLockElement) document.exitPointerLock();
    showBadge(on ? "\uD83C\uDFAE Gaming mode ON \u2014 click to lock, Esc to release"
                 : "Desktop mode \u2014 Ctrl+Shift+G for gaming mode");
  }

  // Ctrl+Shift+G toggles gaming mode. Not in Selkies keyboard-lock list, so it
  // reaches the local page even while keyboard lock is active.
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && e.shiftKey && (e.code === "KeyG" || e.key === "G" || e.key === "g")) {
      e.preventDefault();
      setGamingMode(!window.DPAD_POINTER_LOCK);
    }
  });

  // In gaming mode, clicking the stream requests pointer lock (relative mouse).
  document.addEventListener("click", function (e) {
    if (!window.DPAD_POINTER_LOCK || document.pointerLockElement) return;
    var v = (e.target && e.target.closest) ? e.target.closest("video") : null;
    if (!v) v = document.querySelector("video");
    if (v) { try { _real.apply(v); } catch (err) {} }
  }, true);

  // Esc releases pointer lock -> update the badge.
  document.addEventListener("pointerlockchange", function () {
    if (!document.pointerLockElement) {
      showBadge(window.DPAD_POINTER_LOCK
        ? "Gaming mode ON \u2014 click to re-lock"
        : "Desktop mode \u2014 Ctrl+Shift+G for gaming mode");
    }
  });
})();
// === end DPAD shim ===

'
printf '%s' "$SHIM" | cat - "$FILE" > "${FILE}.new" && mv "${FILE}.new" "$FILE"
echo "patch_gst_web_cursors: patched $FILE (pointer lock gated behind window.DPAD_POINTER_LOCK, default off)"