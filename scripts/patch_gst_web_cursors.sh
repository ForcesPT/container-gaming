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
# Optional 2nd arg: default Gaming mode on power-on. "1" -> pointer lock ON by
# default (relative mouse for keyboard/mouse tiers); anything else -> Desktop
# mode (visible cursor). The entrypoint passes DPAD_DEFAULT_GAMING_MODE so the
# cloud control plane can pick the default per region/tier without a
# browser-console hack.
DEFAULT_LOCK="${2:-0}"
DEFAULT_LOCK_JS="false"
[ "$DEFAULT_LOCK" = "1" ] && DEFAULT_LOCK_JS="true"
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
// server cursor + ABSOLUTE mouse. Default: Desktop mode (pointer lock OFF),
// overridable by the patch script 2nd arg / DPAD_DEFAULT_GAMING_MODE so the
// control plane can default to Gaming mode for keyboard/mouse tiers.
// Toggle: the floating button (bottom-right) or Ctrl+Shift+G. In Gaming mode
// click the stream to lock the pointer (relative mouse / FPS aim), Esc to
// release. window.DPAD_POINTER_LOCK = true/false still works from the console.
(function () {
  if (window.__dpad_pl_patched) return;
  window.__dpad_pl_patched = true;
  window.DPAD_POINTER_LOCK = __DPAD_DEFAULT_LOCK__; // substituted by patch script

  var _real = Element.prototype.requestPointerLock;
  Element.prototype.requestPointerLock = function () {
    if (window.DPAD_POINTER_LOCK) {
      try { return _real.apply(this, arguments); } catch (e) { return Promise.reject(e); }
    }
    // not locked: document.pointerLockElement stays null -> Selkies uses absolute
    // mouse ("m"), and the server-sent CSS cursor stays visible (even in fullscreen).
    return Promise.reject(new Error("pointer lock disabled (DPAD; click the Gaming button or press Ctrl+Shift+G)"));
  };

  // --- on-screen mode badge (auto-hides) ---
  var badge = document.createElement("div");
  badge.id = "dpad-mode-badge";
  badge.style.cssText = "position:fixed;top:8px;right:8px;z-index:1000000;font:12px/1.4 sans-serif;" +
    "padding:4px 8px;border-radius:6px;color:#fff;background:rgba(0,0,0,0.6);" +
    "pointer-events:none;opacity:0;transition:opacity .25s";
  function showBadge(txt) {
    badge.textContent = txt;
    badge.style.opacity = "1";
    clearTimeout(showBadge._t);
    showBadge._t = setTimeout(function () { badge.style.opacity = "0"; }, 2500);
  }

  // --- persistent toggle button (bottom-right; discoverable, no shortcut needed) ---
  var btn = document.createElement("button");
  btn.id = "dpad-mode-btn";
  btn.type = "button";
  btn.title = "Toggle Gaming mode (relative mouse for FPS aim). Shortcut: Ctrl+Shift+G";
  btn.style.cssText = "position:fixed;bottom:10px;right:10px;z-index:1000000;font:12px/1.4 sans-serif;" +
    "padding:6px 10px;border:1px solid rgba(255,255,255,0.35);border-radius:8px;cursor:pointer;" +
    "color:#fff;background:rgba(0,0,0,0.55)";
  function paintBtn() {
    btn.textContent = window.DPAD_POINTER_LOCK
      ? "\uD83C\uDFAE Gaming \u2014 Esc to release"
      : "\uD83D\uDDA8\uFE0F Desktop \u2014 click for FPS";
  }
  btn.addEventListener("click", function (e) {
    e.preventDefault(); e.stopPropagation();
    var turnOn = !window.DPAD_POINTER_LOCK;
    setGamingMode(turnOn);
    if (turnOn) {
      var v = document.querySelector("video");
      if (v) { try { _real.apply(v); } catch (err) {} }
    }
  });

  function ready() {
    if (document.body) {
      if (!badge.parentNode) document.body.appendChild(badge);
      if (!btn.parentNode) document.body.appendChild(btn);
    }
    paintBtn();
    showBadge(window.DPAD_POINTER_LOCK
      ? "\uD83C\uDFAE Gaming mode ON \u2014 click to lock, Esc to release"
      : "Desktop mode \u2014 click the button for FPS");
  }
  if (document.body) ready(); else document.addEventListener("DOMContentLoaded", ready);

  function setGamingMode(on) {
    window.DPAD_POINTER_LOCK = on;
    if (!on && document.pointerLockElement) document.exitPointerLock();
    paintBtn();
    showBadge(on ? "\uD83C\uDFAE Gaming mode ON \u2014 click to lock, Esc to release"
                 : "Desktop mode \u2014 click the button for FPS");
  }

  // Ctrl+Shift+G toggles gaming mode (not in Selkies keyboard-lock list, so it
  // reaches the local page even while keyboard lock is active).
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && e.shiftKey && (e.code === "KeyG" || e.key === "G" || e.key === "g")) {
      e.preventDefault();
      setGamingMode(!window.DPAD_POINTER_LOCK);
    }
  });

  // In gaming mode, clicking the stream requests pointer lock (relative mouse).
  // Skip clicks on the toggle button itself (handled above).
  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "dpad-mode-btn") return;
    if (!window.DPAD_POINTER_LOCK || document.pointerLockElement) return;
    var v = (e.target && e.target.closest) ? e.target.closest("video") : null;
    if (!v) v = document.querySelector("video");
    if (v) { try { _real.apply(v); } catch (err) {} }
  }, true);

  // Esc releases pointer lock -> update badge + button.
  document.addEventListener("pointerlockchange", function () {
    if (!document.pointerLockElement) {
      paintBtn();
      showBadge(window.DPAD_POINTER_LOCK
        ? "Gaming mode ON \u2014 click to re-lock"
        : "Desktop mode \u2014 click the button for FPS");
    }
  });
})();
// === end DPAD shim ===

'
SHIM="${SHIM/__DPAD_DEFAULT_LOCK__/$DEFAULT_LOCK_JS}"
printf '%s' "$SHIM" | cat - "$FILE" > "${FILE}.new" && mv "${FILE}.new" "$FILE"
echo "patch_gst_web_cursors: patched $FILE (pointer lock default=$DEFAULT_LOCK_JS; Gaming-mode toggle: bottom-right button + Ctrl+Shift+G)"