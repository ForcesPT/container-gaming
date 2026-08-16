#!/usr/bin/env python3
"""Regression coverage for the DpadPlay-branded Selkies drawer."""

from __future__ import annotations

import builtins
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "patch_live_resolution.py"

INDEX_FIXTURE = '''<!doctype html>
<html>
<head>
  <meta name="theme-color" content="black"/>
  <style>
    html { font-family: Roboto, Arial, sans; }
    [v-cloak] { display: none; }
  </style>
  <title>Selkies - webrtc</title>
</head>
<body>
  <div id="app" v-cloak>
    <v-app>
      <v-navigation-drawer v-model="showDrawer" app fixed right temporary width="600">
        <v-container fluid grid-list-lg>
          <v-layout row wrap>
            <v-flex xs12>
              <p>
                <v-toolbar>
                <v-divider class="mr-1" vertical></v-divider>
                <v-tooltip bottom><template v-slot:activator="{ on }"><v-btn icon v-on:click="enterFullscreen()"><v-icon color="black" v-on="on">fullscreen</v-icon></v-btn></template><span>Enter fullscreen mode</span></v-tooltip>
                <v-tooltip bottom><template v-slot:activator="{ on }"><v-btn block icon v-on:click="enableClipboard()"><v-icon color="blue" v-on="on">file_copy</v-icon></v-btn></template><span>Enable clipboard access</span></v-tooltip>
                <v-tooltip bottom><template v-slot:activator="{ on }"><v-btn icon href="/"><v-icon color="black" v-on="on">home</v-icon></v-btn></template><span>Return to launcher</span></v-tooltip>
                <v-tooltip bottom><template v-slot:activator="{ on }"><v-icon color="grey" v-on="on">videogame_asset</v-icon></template><span>Gamepad disconnected</span></v-tooltip>
                <v-tooltip bottom><template v-slot:activator="{ on }"><v-icon class="ml-2" color="black" v-on="on">account_circle</v-icon></template><span>Logged in as {{ getUsername() }}</span></v-tooltip>
              </v-toolbar></p>
              <p>
                <v-select :items="videoBitRateOptions" label="Video bitrate" menu-props="left" v-model="videoBitRate"
                  hint="Dynamic bitrate selection for host video encoder" persistent-hint></v-select>
              </p>
              <p>
                <v-select :items="videoFramerateOptions" label="Video framerate" menu-props="left"
                  v-model="videoFramerate" hint="Framerate selection for host video encoder" persistent-hint>
                </v-select>
              </p>
              <p>
                <v-select :items="audioBitRateOptions" label="Audio bitrate" menu-props="left" v-model="audioBitRate"
                  hint="Streaming bitrate selection for host audio encoder" persistent-hint>
                </v-select>
              </p>
              <p>
              <ul><li>Peer connection state</li></ul>
              <small>
              Shortcuts
              </small>
              </p>
              <hr />
            </v-flex>
          </v-layout>
        </v-container>
      </v-navigation-drawer>
      <v-btn class="fab-container" v-on:click="showDrawer=!showDrawer" color="grey" fab dark fixed right>
      </v-btn>
      <div class="loading"><div class="loading-text">{{ loadingText }}</div></div>
    </v-app>
  </div>
</body>
</html>
'''

APP_FIXTURE = '''var app = new Vue({
    data() {
        return {
            appName: "webrtc",
            videoBitRate: 8000,
            videoFramerate: 60,
        }
    },
    watch: {
        videoFramerate(newValue) {
            if (newValue === null) return;
            console.log("video framerate changed to " + newValue);
            webrtc.sendDataChannelMessage('_arg_fps,' + newValue);
            this.setIntParam("videoFramerate", newValue);
        },
    }
});
'''

INPUT_FIXTURE = '''class WebRTCInput:
    def on_message(self, msg):
        toks = msg.split(",")
        if toks[0] == "noop":
            pass
        elif toks[0] == "_arg_fps":
            # Set framerate
            fps = int(toks[1])
            logger.info("Setting framerate to: %d" % fps)
            self.on_set_fps(fps)
'''


def test_brands_selkies_and_places_manual_refresh_notice_by_resolution() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        web = root / "opt/gst-web"
        pkg = root / "usr/local/lib/python3.12/dist-packages/selkies_gstreamer"
        web.mkdir(parents=True)
        pkg.mkdir(parents=True)
        (web / "index.html").write_text(INDEX_FIXTURE, encoding="utf-8")
        (web / "app.js").write_text(APP_FIXTURE, encoding="utf-8")
        (pkg / "webrtc_input.py").write_text(INPUT_FIXTURE, encoding="utf-8")

        env = os.environ.copy()
        env.update({
            "DPAD_PATCH_ROOT": str(root),
            "DPAD_WD_WIDTH": "2560",
            "DPAD_WD_HEIGHT": "1440",
        })
        result = subprocess.run(
            [sys.executable, str(PATCHER)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        html = (web / "index.html").read_text(encoding="utf-8")
        app = (web / "app.js").read_text(encoding="utf-8")

        assert "DPAD_STREAM_UI_V2" in html
        assert "DpadPlay Stream" in html
        assert 'class="dpad-drawer"' in html
        assert 'width="440"' in html
        assert "--dpad-v0: #08090a" in html
        assert "--dpad-v9: #f7f8fa" in html
        assert "scrollbar-color: var(--dpad-v4) transparent" in html
        assert "dpad-resolution-note" in html
        assert "Manual refresh required" in html
        assert "After changing resolution, refresh this page to reconnect." in html
        assert 'v-on:click="location.reload()"' in html
        assert html.index('label="Resolution"') < html.index('<div class="dpad-resolution-note"')
        assert html.index('<div class="dpad-resolution-note"') < html.index("</v-navigation-drawer>")
        assert '<v-icon>tune</v-icon>' in html
        assert '<div class="dpad-drawer-head">' in html
        assert '<div class="dpad-settings-card">' in html
        assert '<div class="dpad-diagnostics">' in html
        assert '</small>\n              </div>\n              <hr />' in html
        assert 'v-if="status !== \'connected\' || showStart" class="loading"' in html

        # Session actions are the first category and are no longer mixed into
        # the telemetry toolbar.
        assert '<div class="dpad-section-label">Session actions</div>' in html
        assert '<div class="dpad-action-card">' in html
        assert '<v-toolbar class="dpad-action-toolbar">' in html
        action_pos = html.index('Session actions')
        telemetry_pos = html.index('Stream telemetry')
        quality_pos = html.index('Stream quality')
        assert action_pos < telemetry_pos < quality_pos
        action_end = html.index('</div>', html.index('<div class="dpad-action-card">'))
        action_html = html[action_pos:action_end]
        for icon in ('fullscreen', 'file_copy', 'home', 'videogame_asset', 'account_circle'):
            assert f'>{icon}<' in action_html
        assert '<v-btn block icon' not in action_html

        # Detached Vuetify menus need explicit dark list/tile colors.
        assert '.v-menu__content .v-list__tile__title' in html
        assert 'background: var(--dpad-v2) !important' in html
        # The settings launcher is an edge-attached oval tab: most of it stays
        # visible while the right side touches/extends past the viewport edge.
        assert '.fab-container .v-btn__content' in html
        assert 'right: -14px !important' in html
        assert 'width: 54px; height: 42px' in html
        assert 'border-radius: 999px !important' in html
        assert 'transform: translateX(-7px)' in html

        assert "videoResolution: window.localStorage.getItem" in app
        assert "|| '2560x1440'" in app
        assert "window.setTimeout(() => window.location.reload()" not in app
        assert 'document.title = "DpadPlay Stream"' in app

        patched_input = (pkg / "webrtc_input.py").read_text(encoding="utf-8")
        assert 'if len(toks) != 2 or toks[1] not in {' in patched_input
        for resolution in ("1280x720", "1920x1080", "2560x1440", "3840x2160"):
            assert f'"{resolution}"' in patched_input
        assert 'logger.warning("DPAD: rejecting unsupported resolution command: %s" % msg)' in patched_input
        assert patched_input.index('f.write(res)') < patched_input.index('_threading.Thread(')

        before = (html, app, patched_input)
        rerun = subprocess.run(
            [sys.executable, str(PATCHER)],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rerun.returncode == 0, rerun.stdout + rerun.stderr
        after = (
            (web / "index.html").read_text(encoding="utf-8"),
            (web / "app.js").read_text(encoding="utf-8"),
            (pkg / "webrtc_input.py").read_text(encoding="utf-8"),
        )
        assert after == before

        # A runtime environment different from the image-build default must
        # converge the persisted fallback without duplicating the UI patch.
        runtime_env = env | {"DPAD_WD_WIDTH": "3840", "DPAD_WD_HEIGHT": "2160"}
        runtime_rerun = subprocess.run(
            [sys.executable, str(PATCHER)],
            env=runtime_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert runtime_rerun.returncode == 0, runtime_rerun.stdout + runtime_rerun.stderr
        runtime_app = (web / "app.js").read_text(encoding="utf-8")
        runtime_html = (web / "index.html").read_text(encoding="utf-8")
        assert "|| '3840x2160'" in runtime_app
        assert "|| '2560x1440'" not in runtime_app
        assert runtime_html == html

        # Exercise malformed/oversized commands and state-file write failure
        # against the generated Python, without allowing a successful branch
        # to schedule its self-SIGTERM thread.
        class LogCapture:
            def __init__(self) -> None:
                self.warnings: list[str] = []
                self.errors: list[str] = []

            def info(self, *_args: object) -> None:
                pass

            def warning(self, message: str) -> None:
                self.warnings.append(message)

            def error(self, message: str) -> None:
                self.errors.append(message)

        logger = LogCapture()
        namespace: dict[str, Any] = {"logger": logger}
        exec(patched_input, namespace)
        input_handler = namespace["WebRTCInput"]()
        for command in ("_arg_res", "_arg_res,99999x99999", "_arg_res,1920x1080,extra"):
            input_handler.on_message(command)
        assert len(logger.warnings) == 3

        real_open = builtins.open
        try:
            def deny_state_write(*_args: object, **_kwargs: object) -> object:
                raise OSError("read-only test state")

            builtins.open = deny_state_write
            input_handler.on_message("_arg_res,1920x1080")
        finally:
            builtins.open = real_open
        assert logger.errors and "restart cancelled" in logger.errors[-1]

        # A container with the prior permissive overlay must be migrated in
        # place, not skipped or given a duplicate _arg_res branch.
        legacy_input = INPUT_FIXTURE + '''        elif toks[0] == "_arg_res":
            res = toks[1]
            parts = res.split("x")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                with open("/tmp/dpad_resolution", "w") as f:
                    f.write(res)
'''
        (pkg / "webrtc_input.py").write_text(legacy_input, encoding="utf-8")
        migration = subprocess.run(
            [sys.executable, str(PATCHER)],
            env=runtime_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert migration.returncode == 0, migration.stdout + migration.stderr
        migrated = (pkg / "webrtc_input.py").read_text(encoding="utf-8")
        assert migrated.count('elif toks[0] == "_arg_res":') == 1
        assert 'if len(toks) != 2 or toks[1] not in {' in migrated
        assert "parts[0].isdigit()" not in migrated


def test_migrates_v1_drawer_to_v2_without_losing_actions() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        web = root / "opt/gst-web"
        web.mkdir(parents=True)
        (web / "index.html").write_text(INDEX_FIXTURE, encoding="utf-8")
        (web / "app.js").write_text(APP_FIXTURE, encoding="utf-8")
        env = os.environ | {"DPAD_PATCH_ROOT": str(root)}

        first = subprocess.run(
            [sys.executable, str(PATCHER)], env=env, text=True,
            capture_output=True, check=False,
        )
        assert first.returncode == 0, first.stdout + first.stderr
        html = (web / "index.html").read_text(encoding="utf-8")

        settings_v3 = re.compile(
            r'\s*/\* DPAD_SETTINGS_TAB_V3.*?\*/.*?'
            r'\.fab-container \.v-btn__content \{.*?\}\s*',
            re.DOTALL,
        )
        active_v2_html, removed = settings_v3.subn("\n", html, count=1)
        assert removed == 1 and "DPAD_SETTINGS_TAB_V3" not in active_v2_html
        (web / "index.html").write_text(active_v2_html, encoding="utf-8")
        v2_migration = subprocess.run(
            [sys.executable, str(PATCHER)], env=env, text=True,
            capture_output=True, check=False,
        )
        assert v2_migration.returncode == 0, v2_migration.stdout + v2_migration.stderr
        html = (web / "index.html").read_text(encoding="utf-8")
        assert html.count("DPAD_SETTINGS_TAB_V3") == 1
        assert html.index("DPAD_STREAM_UI_V2") < html.index("DPAD_SETTINGS_TAB_V3")

        # Reconstruct the relevant V1 layout: actions embedded at the end of
        # telemetry, V1 marker, persistent outer loading element.
        section = re.search(
            r'\s*<div class="dpad-section-label">Session actions</div>\s*'
            r'<div class="dpad-action-card">\s*'
            r'<v-toolbar class="dpad-action-toolbar">(?P<actions>.*?)</v-toolbar>\s*'
            r'</div>\s*<div class="dpad-section-label">Stream telemetry</div>',
            html,
            re.DOTALL,
        )
        assert section is not None
        actions = section.group("actions").strip()
        v1_html = html[:section.start()] + html[section.end():]
        telemetry_end = v1_html.index("</v-toolbar>")
        v1_html = v1_html[:telemetry_end] + "\n" + actions + "\n                " + v1_html[telemetry_end:]
        v1_html = v1_html.replace("DPAD_STREAM_UI_V2", "DPAD_STREAM_UI_V1")
        v1_html, removed = settings_v3.subn("\n", v1_html, count=1)
        assert removed == 1 and "DPAD_SETTINGS_TAB_V3" not in v1_html
        v1_html = v1_html.replace(
            '<div v-if="status !== \'connected\' || showStart" class="loading">',
            '<div class="loading">',
        )
        (web / "index.html").write_text(v1_html, encoding="utf-8")

        migration = subprocess.run(
            [sys.executable, str(PATCHER)], env=env, text=True,
            capture_output=True, check=False,
        )
        assert migration.returncode == 0, migration.stdout + migration.stderr
        migrated = (web / "index.html").read_text(encoding="utf-8")
        assert "DPAD_STREAM_UI_V2" in migrated
        assert migrated.count("DPAD_SETTINGS_TAB_V3") == 1
        assert migrated.count('<div class="dpad-action-card">') == 1
        assert migrated.index("Session actions") < migrated.index("Stream telemetry")
        for icon in ("fullscreen", "file_copy", "home", "videogame_asset", "account_circle"):
            assert migrated.count(f">{icon}<") == 1
        assert 'v-if="status !== \'connected\' || showStart" class="loading"' in migrated


if __name__ == "__main__":
    test_brands_selkies_and_places_manual_refresh_notice_by_resolution()
    test_migrates_v1_drawer_to_v2_without_losing_actions()
    print("Selkies DpadPlay UI patch: PASS")
