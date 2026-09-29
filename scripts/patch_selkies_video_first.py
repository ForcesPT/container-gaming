"""Expose a connected Selkies video peer even when its audio peer is delayed.

The upstream client has separate video and audio RTCPeerConnections. Its single
``status`` gates the loading overlay and START button, so a missing audio peer
currently hides usable video. Patch exact known snippets and fail on drift.
"""

from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one original snippet, found {count}")
    return source.replace(old, new, 1)


def patch_app(source: str) -> str:
    if "// DPAD_VIDEO_FIRST_V1" in source:
        raise ValueError("video-first patch is already present")

    source = replace_once(
        source,
        "            status: 'connecting',\n            loadingText: '',",
        "            status: 'connecting',\n"
        "            videoPeerState: 'connecting',\n"
        "            audioPeerState: 'connecting',\n"
        "            videoProbe: {bytes: 0, packets: 0, decodedFrames: 0, candidateType: 'NA'},\n"
        "            videoProbeError: '',\n"
        "            loadingText: '',",
        "Vue media state",
    )
    source = replace_once(
        source,
        "        playStream() {\n"
        "            webrtc.playStream();\n"
        "            audio_webrtc.playStream();\n"
        "            this.showStart = false;\n"
        "        },",
        "        playStream() {\n"
        "            webrtc.playStream();\n"
        "            // Audio can still be negotiating when the video START button appears.\n"
        "            if (audioConnected === 'connected') audio_webrtc.playStream();\n"
        "            this.showStart = false;\n"
        "        },",
        "START handler",
    )
    source = replace_once(
        source,
        "signalling.ondisconnect = () => {\n"
        "    app.status = 'connecting';\n"
        "    videoElement.style.cursor = \"auto\";\n"
        "    webrtc.reset();\n"
        "}",
        "signalling.ondisconnect = () => {\n"
        "    videoConnected = 'connecting';\n"
        "    app.videoPeerState = videoConnected;\n"
        "    app.status = 'connecting';\n"
        "    videoElement.style.cursor = \"auto\";\n"
        "    webrtc.reset();\n"
        "}",
        "video signaling disconnect",
    )
    source = replace_once(
        source,
        "audio_signalling.ondisconnect = () => {\n"
        "    app.status = 'connecting';\n"
        "    videoElement.style.cursor = \"auto\";\n"
        "    audio_webrtc.reset();\n"
        "}",
        "audio_signalling.ondisconnect = () => {\n"
        "    audioConnected = 'connecting';\n"
        "    app.audioPeerState = audioConnected;\n"
        "    // DPAD_VIDEO_FIRST_V1: a delayed audio peer must not mask video.\n"
        "    app.status = videoConnected === 'connected' ? 'connected' : 'connecting';\n"
        "    audio_webrtc.reset();\n"
        "}",
        "audio signaling disconnect",
    )
    source = replace_once(
        source,
        "webrtc.onconnectionstatechange = (state) => {\n"
        "    videoConnected = state;",
        "// Sample video independently: the normal Selkies stats loop waits for audio.\n"
        "var videoProbeTimer = null;\n"
        "function updateVideoProbe() {\n"
        "    if (videoConnected !== 'connected') return;\n"
        "    Promise.resolve().then(() => webrtc.getConnectionStats()).then((stats) => {\n"
        "        if (videoConnected !== 'connected') return;\n"
        "        app.videoProbeError = '';\n"
        "        const quality = videoElement.getVideoPlaybackQuality ? videoElement.getVideoPlaybackQuality() : null;\n"
        "        app.videoProbe = {\n"
        "            bytes: stats.video.bytesReceived || 0,\n"
        "            packets: stats.video.packetsReceived || 0,\n"
        "            decodedFrames: quality ? quality.totalVideoFrames : 0,\n"
        "            candidateType: stats.general.connectionType || 'NA',\n"
        "        };\n"
        "    }).catch((error) => { app.videoProbeError = String(error && error.message || error); });\n"
        "}\n"
        "webrtc.onconnectionstatechange = (state) => {\n"
        "    videoConnected = state;\n"
        "    app.videoPeerState = state;\n"
        "    if (state === 'connected' && videoProbeTimer === null) {\n"
        "        videoProbeTimer = setInterval(updateVideoProbe, 1000);\n"
        "    } else if (state !== 'connected' && videoProbeTimer !== null) {\n"
        "        clearInterval(videoProbeTimer);\n"
        "        videoProbeTimer = null;\n"
        "    }",
        "video state callback and independent RTP probe",
    )
    source = replace_once(
        source,
        "audio_webrtc.onconnectionstatechange = (state) => {\n"
        "    audioConnected = state;",
        "audio_webrtc.onconnectionstatechange = (state) => {\n"
        "    audioConnected = state;\n"
        "    app.audioPeerState = state;",
        "audio state callback",
    )
    source = replace_once(
        source,
        "    } else {\n"
        "        app.status = state === \"connected\" ? audioConnected : videoConnected;\n"
        "    }\n"
        "};\n"
        "audio_webrtc.onconnectionstatechange",
        "    } else {\n"
        "        app.status = videoConnected;\n"
        "    }\n"
        "};\n"
        "audio_webrtc.onconnectionstatechange",
        "video-only status",
    )
    source = replace_once(
        source,
        "    } else {\n"
        "        app.status = state === \"connected\" ? videoConnected : audioConnected;\n"
        "    }\n"
        "};\n\n"
        "webrtc.ondatachannelopen",
        "    } else {\n"
        "        app.status = videoConnected;\n"
        "    }\n"
        "};\n\n"
        "webrtc.ondatachannelopen",
        "audio-only status",
    )
    return source


def patch_html(source: str) -> str:
    return replace_once(
        source,
        "                <li>Peer connection state: <b>{{ status }}</b></li>",
        "                <li>Video peer: <b>{{ videoPeerState }}</b></li>\n"
        "                <li>Audio peer: <b>{{ audioPeerState }}</b></li>\n"
        "                <li>Video candidate: <b>{{ videoProbe.candidateType }}</b></li>\n"
        "                <li>Video RTP: <b>{{ videoProbe.bytes }} bytes / {{ videoProbe.packets }} packets</b></li>\n"
        "                <li>Decoded video frames: <b>{{ videoProbe.decodedFrames }}</b></li>\n"
        "                <li v-if=\"videoProbeError\">Video probe error: <b>{{ videoProbeError }}</b></li>\n"
        "                <li>Combined media metrics appear after audio connects.</li>",
        "diagnostics label",
    )


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_selkies_video_first.py APP_JS INDEX_HTML")
    app_path, html_path = map(Path, sys.argv[1:])
    app_source = app_path.read_text(encoding="utf-8")
    html_source = html_path.read_text(encoding="utf-8")
    # Prepare both results before changing either file.
    patched_app = patch_app(app_source)
    patched_html = patch_html(html_source)
    app_path.write_text(patched_app, encoding="utf-8")
    html_path.write_text(patched_html, encoding="utf-8")


if __name__ == "__main__":
    main()
