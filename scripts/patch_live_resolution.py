#!/usr/bin/env python3
"""Brand Selkies for DpadPlay and add manual live-resolution switching.

Idempotent runtime overlay applied by entrypoint.sh. It patches:
  * /opt/gst-web/index.html — DpadPlay visual system, drawer layout, Resolution UI
  * /opt/gst-web/app.js — resolution state + data-channel watcher
  * selkies_gstreamer/webrtc_input.py — validated _arg_res handler

Resolution changes deliberately remain manual-refresh: the server writes the new
mode and restarts Selkies, while the drawer tells the player to refresh the page
to establish a fresh WebRTC/NVENC pipeline.
"""

from __future__ import annotations

import glob
import os
import re
import tempfile
from pathlib import Path

PATCH_ROOT = os.environ.get("DPAD_PATCH_ROOT", "").rstrip("/")


def rooted(path: str) -> str:
    return PATCH_ROOT + path if PATCH_ROOT else path


def patch_file(path: str, guard, transform) -> None:
    actual = rooted(path)
    try:
        source = Path(actual).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"SKIP {path} (not found)")
        return
    if guard(source):
        print(f"SKIP {path} (already patched)")
        return
    updated = transform(source)
    if updated is None:
        raise RuntimeError(f"FAIL {path} (anchor not found)")
    if not guard(updated):
        raise RuntimeError(f"FAIL {path} (postcondition failed)")
    target = Path(actual)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.dpad-",
            delete=False,
        ) as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = handle.name
        os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    print(f"OK {path} patched")


def default_resolution() -> str:
    width = os.environ.get("DPAD_WD_WIDTH", "1920")
    height = os.environ.get("DPAD_WD_HEIGHT", "1080")
    value = f"{width}x{height}"
    return value if re.fullmatch(r"[1-9][0-9]{2,4}x[1-9][0-9]{2,4}", value) else "1920x1080"


DPAD_STYLE = r'''
    /* DPAD_STREAM_UI_V2 — mirrors dpadplay.com design tokens and controls. */
    :root {
      --dpad-v0: #08090a; --dpad-v1: #0c0d10; --dpad-v2: #101216;
      --dpad-v3: #15171c; --dpad-v4: #1c1f26; --dpad-v5: #3a4150;
      --dpad-v6: #a0a6b4; --dpad-v7: #d0d5de; --dpad-v8: #e8eaf0;
      --dpad-v9: #f7f8fa; --dpad-h0: rgba(255,255,255,.04);
      --dpad-h1: rgba(255,255,255,.06); --dpad-h2: rgba(255,255,255,.09);
      --dpad-warn: #e6be72; --dpad-error: #f2768a;
    }
    html, body, .application, .application--wrap {
      background: var(--dpad-v0) !important;
      color: var(--dpad-v7) !important;
      font-family: Inter, Geist, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
      -webkit-font-smoothing: antialiased;
    }
    ::selection { background: var(--dpad-v9); color: var(--dpad-v0); }
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: var(--dpad-v1); }
    ::-webkit-scrollbar-thumb { background: var(--dpad-v4); border-radius: 3px; }

    .dpad-drawer.v-navigation-drawer {
      background: rgba(12,13,17,.97) !important;
      color: var(--dpad-v7) !important;
      border-left: 1px solid var(--dpad-h1) !important;
      box-shadow: -28px 0 70px rgba(0,0,0,.42) !important;
      backdrop-filter: blur(24px) saturate(1.1);
    }
    .dpad-drawer .container { padding: 0 20px 32px !important; }
    .dpad-drawer-head {
      position: sticky; top: 0; z-index: 4;
      display: flex; align-items: center; justify-content: space-between;
      margin: 0 -20px 20px; padding: 14px 20px;
      background: rgba(8,9,10,.88); border-bottom: 1px solid var(--dpad-h1);
      backdrop-filter: blur(20px);
    }
    .dpad-brand { display: flex; align-items: center; gap: 10px; }
    .dpad-brand-mark {
      display: inline-flex; width: 27px; height: 27px; align-items: center; justify-content: center;
      border-radius: 7px; color: var(--dpad-v0); background: linear-gradient(135deg,#fff,var(--dpad-v8));
      font-size: 12px; font-weight: 900; box-shadow: 0 0 18px -6px rgba(247,248,250,.4);
    }
    .dpad-brand-name { color: var(--dpad-v9); font-size: 14px; font-weight: 800; letter-spacing: -.02em; }
    .dpad-brand-sub { color: var(--dpad-v5); font: 600 9px/1.2 ui-monospace, monospace; letter-spacing: .14em; text-transform: uppercase; }
    .dpad-close.v-btn { color: var(--dpad-v6) !important; }
    .dpad-section-label {
      margin: 22px 0 9px; color: var(--dpad-v5);
      font: 700 9px/1.2 ui-monospace, monospace; letter-spacing: .16em; text-transform: uppercase;
    }
    .dpad-settings-card {
      overflow: hidden; padding: 6px 15px 2px;
      border: 1px solid var(--dpad-h1); border-radius: 12px;
      background: linear-gradient(170deg,rgba(255,255,255,.025),rgba(255,255,255,.005));
    }
    .dpad-settings-card > p { margin: 7px 0 15px; }
    .dpad-drawer .v-toolbar {
      min-height: 66px; height: auto !important; overflow-x: auto;
      scrollbar-width: thin; scrollbar-color: var(--dpad-v4) transparent;
      border: 1px solid var(--dpad-h1); border-radius: 12px;
      background: linear-gradient(170deg,rgba(255,255,255,.035),rgba(255,255,255,.01)) !important;
      box-shadow: none !important;
    }
    .dpad-drawer .v-toolbar__content { height: auto !important; min-width: max-content; padding: 7px 9px; }
    .dpad-drawer .v-progress-circular { color: var(--dpad-v8) !important; }
    .dpad-drawer .v-divider { border-color: var(--dpad-h2) !important; }
    .dpad-drawer .v-icon, .dpad-drawer .v-btn .v-icon { color: var(--dpad-v7) !important; }
    .dpad-drawer .v-label, .dpad-drawer .v-select__selection, .dpad-drawer input,
    .dpad-drawer textarea, .dpad-drawer b { color: var(--dpad-v8) !important; }
    .dpad-drawer .v-messages__message { color: var(--dpad-v5) !important; font-size: 10px; line-height: 1.4; }
    .dpad-drawer .v-input__slot:before { border-color: var(--dpad-h2) !important; }
    .dpad-drawer .v-input__slot:after { border-color: var(--dpad-v9) !important; }
    .v-menu__content { background: var(--dpad-v2) !important; border: 1px solid var(--dpad-h2); border-radius: 8px; box-shadow: 0 18px 48px rgba(0,0,0,.45) !important; }
    .v-menu__content .v-list { background: var(--dpad-v2) !important; color: var(--dpad-v7) !important; }
    .v-menu__content .v-list__tile, .v-menu__content .v-list__tile__title { color: var(--dpad-v7) !important; }
    .v-menu__content .v-list__tile--active, .v-menu__content .v-list__tile:hover { background: var(--dpad-h2) !important; color: var(--dpad-v9) !important; }
    .v-menu__content .v-list__tile--active .v-list__tile__title,
    .v-menu__content .v-list__tile:hover .v-list__tile__title { color: var(--dpad-v9) !important; }
    .dpad-action-card { padding: 4px; border: 1px solid var(--dpad-h1); border-radius: 12px; background: var(--dpad-h0); }
    .dpad-action-toolbar.v-toolbar { min-height: 48px; border: 0; background: transparent !important; }
    .dpad-action-toolbar .v-toolbar__content { justify-content: space-around; width: 100%; padding: 4px !important; }
    .dpad-action-toolbar .v-btn { width: 38px; height: 38px; margin: 0 2px; border-radius: 999px; }
    .dpad-resolution-note {
      display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: center;
      margin: -3px 0 14px; padding: 11px 11px;
      border: 1px solid rgba(230,190,114,.22); border-radius: 9px;
      background: rgba(230,190,114,.08); color: #f1d9a6;
    }
    .dpad-resolution-note .v-icon { color: var(--dpad-warn) !important; font-size: 18px; }
    .dpad-resolution-note strong { display: block; color: #f5deb0 !important; font-size: 11px; font-weight: 700; }
    .dpad-resolution-note span { display: block; margin-top: 2px; color: rgba(241,217,166,.7); font-size: 10px; line-height: 1.35; }
    .dpad-resolution-note .v-btn {
      min-width: 0; height: 28px; margin: 0; padding: 0 9px;
      border: 1px solid rgba(230,190,114,.28); border-radius: 7px;
      background: rgba(230,190,114,.1) !important; color: #f1d9a6 !important;
      box-shadow: none !important; font: 700 9px ui-monospace, monospace; letter-spacing: .08em;
    }
    .dpad-diagnostics {
      padding: 14px 15px; border: 1px solid var(--dpad-h1); border-radius: 12px;
      background: var(--dpad-h0); color: var(--dpad-v6); font-size: 11px; line-height: 1.7;
    }
    .dpad-diagnostics ul { margin: 0 0 10px; padding-left: 17px; }
    .dpad-drawer hr { border: 0; border-top: 1px solid var(--dpad-h1); margin: 22px 0; }
    .dpad-drawer .v-textarea { border: 1px solid var(--dpad-h1); border-radius: 10px; padding: 8px 10px; background: var(--dpad-h0); }
    .dpad-drawer a { color: var(--dpad-v8) !important; }

    .fab-container.v-btn {
      top: 50% !important; right: 6px !important; width: 38px; height: 38px;
      min-width: 38px !important; padding: 0 !important;
      opacity: .86 !important; border: 1px solid var(--dpad-h2); border-radius: 999px !important;
      background: rgba(12,13,17,.9) !important; color: var(--dpad-v9) !important;
      box-shadow: 0 10px 34px rgba(0,0,0,.4) !important; backdrop-filter: blur(16px);
      transition: opacity .2s ease, border-color .2s ease, transform .2s ease;
    }
    .fab-container.v-btn:hover { right: 6px !important; opacity: 1 !important; border-color: var(--dpad-h2); transform: translateY(-1px); }
    .fab-container .v-icon { color: var(--dpad-v9) !important; font-size: 19px; }
    .loading { color: var(--dpad-v7) !important; font-family: ui-monospace, monospace; font-size: 11px; letter-spacing: .04em; }
    .loading .v-btn { border-radius: 8px; background: var(--dpad-v9) !important; color: var(--dpad-v0) !important; box-shadow: none !important; }
    @media (max-width: 520px) {
      .dpad-drawer.v-navigation-drawer { width: 100vw !important; max-width: 100vw !important; }
      .dpad-drawer .container { padding-left: 14px !important; padding-right: 14px !important; }
      .dpad-drawer-head { margin-left: -14px; margin-right: -14px; padding-left: 14px; padding-right: 14px; }
      .dpad-resolution-note { grid-template-columns: 24px 1fr; }
      .dpad-resolution-note .v-btn { grid-column: 2; justify-self: start; }
    }
'''


DPAD_V2_FIX_STYLE = r'''
    /* DPAD_STREAM_UI_V2 — connection-state, action layout, menu and launcher fixes. */
    .v-menu__content { background: var(--dpad-v2) !important; border: 1px solid var(--dpad-h2); border-radius: 8px; box-shadow: 0 18px 48px rgba(0,0,0,.45) !important; }
    .v-menu__content .v-list { background: var(--dpad-v2) !important; color: var(--dpad-v7) !important; }
    .v-menu__content .v-list__tile, .v-menu__content .v-list__tile__title { color: var(--dpad-v7) !important; }
    .v-menu__content .v-list__tile--active, .v-menu__content .v-list__tile:hover { background: var(--dpad-h2) !important; }
    .v-menu__content .v-list__tile--active .v-list__tile__title,
    .v-menu__content .v-list__tile:hover .v-list__tile__title { color: var(--dpad-v9) !important; }
    .dpad-action-card { padding: 4px; border: 1px solid var(--dpad-h1); border-radius: 12px; background: var(--dpad-h0); }
    .dpad-action-toolbar.v-toolbar { min-height: 48px; border: 0; background: transparent !important; }
    .dpad-action-toolbar .v-toolbar__content { justify-content: space-around; width: 100%; padding: 4px !important; }
    .dpad-action-toolbar .v-btn { width: 38px; height: 38px; margin: 0 2px; border-radius: 999px; }
    .fab-container.v-btn, .fab-container.v-btn:hover {
      right: 6px !important; width: 38px; height: 38px; min-width: 38px !important;
      padding: 0 !important; border-radius: 999px !important;
    }
'''


DPAD_SETTINGS_TAB_STYLE = r'''
    /* DPAD_SETTINGS_TAB_V3 — edge-attached oval settings control. */
    .fab-container.v-btn, .fab-container.v-btn:hover {
      right: -14px !important; width: 54px; height: 42px; min-width: 54px !important;
      padding: 0 !important; border-radius: 999px !important;
    }
    .fab-container .v-btn__content { transform: translateX(-7px); }
'''


DPAD_STREAM_POLISH_STYLE = r'''
    /* DPAD_STREAM_POLISH_V4 — centered edge capsule and website loading atmosphere. */
    .fab-container.v-btn, .fab-container.v-btn:hover {
      top: 50% !important; right: -18px !important;
      width: 64px; height: 44px; min-width: 64px !important;
      padding: 0 !important; border-radius: 999px !important; overflow: hidden;
      display: flex !important; align-items: center !important; justify-content: center !important;
      transform: translateY(-50%) !important;
    }
    .fab-container.v-btn:before { border-radius: inherit !important; }
    .fab-container .v-btn__content {
      width: 100%; height: 100%; padding: 0;
      display: flex !important; align-items: center !important; justify-content: center !important;
      line-height: 1 !important; transform: translateX(-9px);
    }
    .fab-container .v-icon {
      display: flex !important; align-items: center; justify-content: center;
      margin: 0 !important; line-height: 1 !important; vertical-align: middle;
    }
    .loading {
      position: fixed !important; inset: 0 !important; z-index: 7;
      width: auto !important; height: auto !important;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      overflow: hidden; isolation: isolate;
      background:
        radial-gradient(620px 420px at 78% 8%, rgba(247,248,250,.055), transparent 60%),
        radial-gradient(520px 380px at 12% 92%, rgba(58,65,80,.09), transparent 60%),
        #08090a;
    }
    .loading:before {
      content: ""; position: absolute; inset: -8%; z-index: -2; pointer-events: none;
      background-image:
        linear-gradient(to right, rgba(255,255,255,.045) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255,255,255,.045) 1px, transparent 1px);
      background-size: 28px 28px;
      -webkit-mask-image: radial-gradient(ellipse 78% 82% at 78% 8%, #000 16%, transparent 76%);
      mask-image: radial-gradient(ellipse 78% 82% at 78% 8%, #000 16%, transparent 76%);
      animation: dpad-loading-drift 9s ease-in-out infinite alternate;
    }
    .loading:after {
      content: ""; position: absolute; inset: -35% 0; z-index: -1; pointer-events: none;
      background: linear-gradient(180deg, transparent 42%, rgba(247,248,250,.055) 50%, transparent 58%);
      filter: blur(10px); animation: dpad-loading-scan 6.5s linear infinite;
    }
    .loading > * { position: relative; z-index: 1; }
    @keyframes dpad-loading-drift {
      from { transform: translate3d(-1.5%, -1%, 0) scale(1); opacity: .62; }
      to { transform: translate3d(1.5%, 1%, 0) scale(1.035); opacity: .9; }
    }
    @keyframes dpad-loading-scan {
      from { transform: translateY(-34%); opacity: 0; }
      12%, 88% { opacity: 1; }
      to { transform: translateY(34%); opacity: 0; }
    }
    @media (prefers-reduced-motion: reduce) {
      .loading:before, .loading:after { animation: none !important; }
    }
'''


def resolution_block() -> str:
    return '''              <p class="dpad-resolution-control">
                <v-select :items="videoResolutionOptions" label="Resolution" menu-props="left"
                  v-model="videoResolution" hint="Select a stream resolution, then refresh to reconnect" persistent-hint>
                </v-select>
              </p>
              <div class="dpad-resolution-note" role="note" aria-label="Manual refresh required">
                <v-icon aria-hidden="true">refresh</v-icon>
                <div>
                  <strong>Manual refresh required</strong>
                  <span>After changing resolution, refresh this page to reconnect.</span>
                </div>
                <v-btn small flat v-on:click="location.reload()">Refresh</v-btn>
              </div>'''


def patch_index(source: str) -> str | None:
    updated = source

    # Remove the rejected V1 logo-letter loading badge during upgrades.
    updated = re.sub(
        r'\n\s*\.loading:before \{\n\s*content: "D";.*?\n\s*\}\n',
        "\n",
        updated,
        count=1,
        flags=re.DOTALL,
    )

    if "DPAD_STREAM_UI_V2" not in updated:
        if "</style>" not in updated:
            return None
        style = DPAD_V2_FIX_STYLE if "DPAD_STREAM_UI_V1" in updated else DPAD_STYLE
        updated = updated.replace("</style>", style + "\n  </style>", 1)
    if "DPAD_SETTINGS_TAB_V3" not in updated:
        if "</style>" not in updated:
            return None
        updated = updated.replace("</style>", DPAD_SETTINGS_TAB_STYLE + "\n  </style>", 1)
    if "DPAD_STREAM_POLISH_V4" not in updated:
        if "</style>" not in updated:
            return None
        updated = updated.replace("</style>", DPAD_STREAM_POLISH_STYLE + "\n  </style>", 1)

    updated = updated.replace('<meta name="theme-color" content="black"/>', '<meta name="theme-color" content="#08090a"/>')
    updated = updated.replace("<title>Selkies - webrtc</title>", "<title>DpadPlay Stream</title>")

    drawer = '<v-navigation-drawer v-model="showDrawer" app fixed right temporary width="600">'
    branded_drawer = '<v-navigation-drawer v-model="showDrawer" app fixed right temporary width="440" class="dpad-drawer">'
    updated = updated.replace(drawer, branded_drawer, 1)

    flex_anchor = "            <v-flex xs12>"
    if '<div class="dpad-drawer-head">' not in updated:
        if flex_anchor not in updated:
            return None
        header = flex_anchor + '''
              <div class="dpad-drawer-head">
                <div class="dpad-brand">
                  <span class="dpad-brand-mark">D</span>
                  <div><div class="dpad-brand-name">DPADPLAY</div><div class="dpad-brand-sub">Stream controls</div></div>
                </div>
                <v-btn class="dpad-close" icon flat aria-label="Close stream controls" v-on:click="showDrawer=false"><v-icon>close</v-icon></v-btn>
              </div>'''
        updated = updated.replace(flex_anchor, header, 1)

    if '<div class="dpad-action-card">' not in updated:
        actions_pattern = re.compile(
            r'''(?P<actions>\s*<v-tooltip bottom>\s*<template v-slot:activator="\{ on \}">\s*<v-btn icon v-on:click="enterFullscreen\(\)">.*?<span>Logged in as \{\{ getUsername\(\) \}\}\s*</span>\s*</v-tooltip>)''',
            re.DOTALL,
        )
        actions_match = actions_pattern.search(updated)
        if actions_match is None:
            return None
        actions = actions_match.group("actions").strip().replace("<v-btn block icon", "<v-btn icon")
        updated = updated[:actions_match.start()] + updated[actions_match.end():]
        toolbar_anchor = '''              <p>
                <v-toolbar>'''
        if toolbar_anchor not in updated:
            return None
        action_section = f'''              <div class="dpad-section-label">Session actions</div>
              <div class="dpad-action-card">
                <v-toolbar class="dpad-action-toolbar">
{actions}
                </v-toolbar>
              </div>
              <div class="dpad-section-label">Stream telemetry</div>
'''
        updated = updated.replace(toolbar_anchor, action_section + toolbar_anchor, 1)
    updated = updated.replace("<v-btn block icon", "<v-btn icon")

    bitrate_anchor = '''              <p>
                <v-select :items="videoBitRateOptions"'''
    if '<div class="dpad-settings-card">' not in updated:
        if bitrate_anchor not in updated:
            return None
        updated = updated.replace(
            bitrate_anchor,
            '''              <div class="dpad-section-label">Stream quality</div>
              <div class="dpad-settings-card">
              <p>
                <v-select :items="videoBitRateOptions"''',
            1,
        )

    old_resolution = re.compile(
        r'''\s*<p(?: class="dpad-resolution-control")?>\s*<v-select :items="videoResolutionOptions".*?</v-select>\s*</p>(?:\s*<div class="dpad-resolution-note".*?</div>)?(?=\s*<p>\s*<v-select :items="audioBitRateOptions")''',
        re.DOTALL,
    )
    if "videoResolutionOptions" in updated:
        updated = old_resolution.sub("\n" + resolution_block(), updated, count=1)
    else:
        framerate_anchor = '''              <p>
                <v-select :items="videoFramerateOptions" label="Video framerate" menu-props="left"
                  v-model="videoFramerate" hint="Framerate selection for host video encoder" persistent-hint>
                </v-select>
              </p>'''
        if framerate_anchor not in updated:
            return None
        updated = updated.replace(framerate_anchor, framerate_anchor + "\n" + resolution_block(), 1)

    audio_end = '''                </v-select>
              </p>
              <p>
              <ul>'''
    if '<div class="dpad-diagnostics">' not in updated:
        if audio_end not in updated:
            return None
        updated = updated.replace(
            audio_end,
            '''                </v-select>
              </p>
              </div>
              <div class="dpad-section-label">Connection diagnostics</div>
              <div class="dpad-diagnostics">
              <ul>''',
            1,
        )
        diagnostics_end = '''              </small>
              </p>
              <hr />'''
        if diagnostics_end not in updated:
            return None
        updated = updated.replace(
            diagnostics_end,
            '''              </small>
              </div>
              <hr />''',
            1,
        )

    fab = '''      <v-btn class="fab-container" v-on:click="showDrawer=!showDrawer" color="grey" fab dark fixed right>
      </v-btn>'''
    branded_fab = '''      <v-btn class="fab-container" aria-label="Open stream controls" v-on:click="showDrawer=!showDrawer" fab dark fixed right>
        <v-icon>tune</v-icon>
      </v-btn>'''
    updated = updated.replace(fab, branded_fab, 1)

    updated = updated.replace(
        '<div class="loading">',
        '<div v-if="status !== \'connected\' || showStart" class="loading">',
        1,
    )

    return updated


patch_file(
    "/opt/gst-web/index.html",
    lambda source: (
        "DPAD_STREAM_UI_V2" in source
        and "DPAD_SETTINGS_TAB_V3" in source
        and "DPAD_STREAM_POLISH_V4" in source
        and 'content: "D"' not in source
        and "dpad-resolution-note" in source
        and 'class="dpad-drawer"' in source
        and '<v-icon>tune</v-icon>' in source
        and '<div class="dpad-drawer-head">' in source
        and '<div class="dpad-settings-card">' in source
        and '<div class="dpad-diagnostics">' in source
        and '<div class="dpad-action-card">' in source
        and '<v-btn block icon' not in source
        and 'v-if="status !== \'connected\' || showStart" class="loading"' in source
    ),
    patch_index,
)


def patch_appjs(source: str) -> str | None:
    updated = source.replace("            window.setTimeout(() => window.location.reload(), 750);\n", "")
    updated = updated.replace('document.title = "Selkies - " + newValue;', 'document.title = "DpadPlay Stream";')
    updated = updated.replace('document.title = "Selkies - " + app.appName;', 'document.title = "DpadPlay Stream";')
    if 'document.title = "DpadPlay Stream";' not in updated:
        updated = 'document.title = "DpadPlay Stream";\n' + updated
    desired_resolution = (
        "            videoResolution: window.localStorage.getItem("
        "((window.location.pathname.endsWith(\"/\") && window.location.pathname.split(\"/\")[1]) || \"webrtc\") "
        f"+ \"_videoResolution\") || '{default_resolution()}',"
    )

    existing_resolution = re.compile(r"^\s*videoResolution:\s*.*,$", re.MULTILINE)
    if existing_resolution.search(updated):
        updated = existing_resolution.sub(desired_resolution, updated, count=1)
    else:
        data_anchor = "            videoFramerate: 60,"
        if data_anchor not in updated:
            return None
        options = f'''{desired_resolution}
            videoResolutionOptions: [
                {{ text: '720p', value: '1280x720' }},
                {{ text: '1080p', value: '1920x1080' }},
                {{ text: '1440p', value: '2560x1440' }},
                {{ text: '4K', value: '3840x2160' }},
            ],
'''
        updated = updated.replace(data_anchor, options + data_anchor, 1)

    watcher_anchor = '''        videoFramerate(newValue) {
            if (newValue === null) return;
            console.log("video framerate changed to " + newValue);
            webrtc.sendDataChannelMessage('_arg_fps,' + newValue);
            this.setIntParam("videoFramerate", newValue);
        },'''
    if "videoResolution(newValue)" not in updated:
        if watcher_anchor not in updated:
            return None
        watcher = watcher_anchor + '''
        videoResolution(newValue) {
            if (newValue === null) return;
            // DPAD: manual refresh required after selection.
            console.log("video resolution changed to " + newValue);
            webrtc.sendDataChannelMessage('_arg_res,' + newValue);
            this.setIntParam("videoResolution", newValue);
        },'''
        updated = updated.replace(watcher_anchor, watcher, 1)
    elif "// DPAD: manual refresh required after selection." not in updated:
        updated = updated.replace(
            '            console.log("video resolution changed to " + newValue);',
            '            // DPAD: manual refresh required after selection.\n            console.log("video resolution changed to " + newValue);',
            1,
        )
    return updated


patch_file(
    "/opt/gst-web/app.js",
    lambda source: (
        "videoResolution: window.localStorage.getItem" in source
        and f"|| '{default_resolution()}'" in source
        and "// DPAD: manual refresh required after selection." in source
        and "window.setTimeout(() => window.location.reload(), 750);" not in source
        and 'document.title = "DpadPlay Stream";' in source
    ),
    patch_appjs,
)


def patch_webrtc_input(source: str) -> str | None:
    py_anchor = '''        elif toks[0] == "_arg_fps":
            # Set framerate
            fps = int(toks[1])
            logger.info("Setting framerate to: %d" % fps)
            self.on_set_fps(fps)'''
    secure_handler = '''        elif toks[0] == "_arg_res":
            # DPAD: live resolution change; browser reconnect remains manual.
            if len(toks) != 2 or toks[1] not in {
                "1280x720", "1920x1080", "2560x1440", "3840x2160"
            }:
                logger.warning("DPAD: rejecting unsupported resolution command: %s" % msg)
                return
            res = toks[1]
            logger.info("DPAD: live resolution change to %s -- writing /tmp/dpad_resolution + restarting selkies" % res)
            try:
                with open("/tmp/dpad_resolution", "w") as f:
                    f.write(res)
            except Exception as e:
                logger.error("failed to write /tmp/dpad_resolution; restart cancelled: %s" % e)
                return
            import os as _os, signal as _signal, threading as _threading
            def _selfterm(_delay=0.5):
                import time; time.sleep(_delay)
                _os.kill(_os.getpid(), _signal.SIGTERM)
            _threading.Thread(target=_selfterm, daemon=True).start()'''

    # Migrate any older permissive _arg_res overlay rather than appending a
    # duplicate branch. The branch ends at the next sibling elif or method.
    legacy_handler = re.compile(
        r'^        elif toks\[0\] == "_arg_res":\n'
        r'(?:(?!^        elif |^    def ).*(?:\n|$))*',
        re.MULTILINE,
    )
    if legacy_handler.search(source):
        return legacy_handler.sub(secure_handler + "\n", source, count=1)
    if py_anchor not in source:
        return None
    return source.replace(py_anchor, py_anchor + "\n" + secure_handler, 1)


candidate_paths = [
    "/usr/local/lib/python3.12/dist-packages/selkies_gstreamer/webrtc_input.py",
    "/usr/local/lib/python3.13/dist-packages/selkies_gstreamer/webrtc_input.py",
]
pattern = rooted("/usr/local/lib/python*/dist-packages/selkies_gstreamer/webrtc_input.py")
for actual in glob.glob(pattern):
    candidate = actual[len(PATCH_ROOT):] if PATCH_ROOT else actual
    candidate_paths.append(candidate)
for candidate in dict.fromkeys(candidate_paths):
    patch_file(
        candidate,
        lambda source: (
            'toks[0] == "_arg_res"' in source
            and 'if len(toks) != 2 or toks[1] not in {' in source
            and 'restart cancelled' in source
        ),
        patch_webrtc_input,
    )

print("patch_live_resolution done")
