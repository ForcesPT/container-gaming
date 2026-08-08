#!/usr/bin/env python3
# selkies-sdp-probe.py — connect to a selkies-gstreamer signaling endpoint,
# initiate a SESSION, and dump the SDP offer the server sends. The m=video line
# is the §17.3 gate: m=video:2 = video track offered (the waylanddisplaysrc
# compositor engaged); m=video:0 = no video track (the bug persists).
#
# We do NOT complete the WebRTC handshake (no aiortc) — we only need the
# server's SDP OFFER to read the m=video line. The server builds the video
# pipeline (waylanddisplaysrc compositor) on SESSION, so this is enough to
# validate the runtime selkies patch.
#
# Usage: python3 selkies-sdp-probe.py <host> <port> [peer_id]
#   peer_id defaults to 1 (the selkies app's video peer_id per __main__.py:510).
import asyncio, sys, json, base64, os
try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets", file=sys.stderr); sys.exit(2)

async def main(host, port, peer_id):
    # The selkies-gstreamer APP connects as my_id=0 (video) + my_id=2 (audio)
    # and ACTIVELY calls SESSION 1 / SESSION 3 — it waits for a browser peer 1
    # (video) + peer 3 (audio) to connect. So we connect AS peer_id (default 1)
    # and WAIT for the app to call us + send the SDP offer. We do NOT send SESSION
    # (that's the app's job; sending it ourselves is backwards + gets no response).
    my_id = str(peer_id)  # we ARE the peer the app is trying to call
    user = os.environ.get("SELKIES_USER", "dpad")
    pw = os.environ.get("SELKIES_PASS", "testpass")
    # websockets lib version differences: older=extra_headers, newer=additional_headers.
    # Simplest: embed the auth in the URI (websockets honors user:pass@host basic-auth).
    uri = f"ws://{user}:{pw}@{host}:{port}/ws"
    print(f"[*] connecting to ws://{host}:{port}/ws as peer {my_id} (waiting for the app to call us)...", flush=True)
    async with websockets.connect(uri, max_size=2**24, ping_interval=20) as ws:
        # HELLO handshake: send "HELLO <my_id>", expect "HELLO" back.
        await ws.send(f"HELLO {my_id}")
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        if resp != "HELLO":
            print(f"[!] unexpected HELLO response: {resp!r}", flush=True); sys.exit(1)
        print("[*] HELLO exchanged — waiting for the app's SESSION + SDP offer...", flush=True)
        # Do NOT send SESSION — the app (peer 0) will send SESSION <my_id> to us.
        # The server relays SDP/ICE from peer 0 once the session establishes.
        # The server relays messages from peer_id. The first is usually the SDP offer.
        # Relay format: "<from_peer_id> {json}" or bare JSON. Parse + look for SDP.
        m_video_seen = None
        _seen_sdp = False
        msgs = 0
        while msgs < 40:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
            except asyncio.TimeoutError:
                print("[!] timed out waiting for messages", flush=True); break
            msgs += 1
            # The relayed message: selkies signalling sends JSON {type, sdp} or {type, ice}.
            # The wrapper: "<peer_id> <json>" (connection_handler relays raw). Strip a leading peer id.
            body = msg
            if body.startswith(f"{peer_id} "):
                body = body[len(f"{peer_id} "):]
            # Try to parse as JSON.
            try:
                obj = json.loads(body)
            except Exception:
                # Non-JSON relayed message (ERROR, STATUS, etc.). Print it.
                print(f"[msg {msgs}] (raw): {msg[:200]!r}", flush=True)
                if "m=video" in msg:
                    for line in msg.splitlines():
                        if line.startswith("m=video"):
                            m_video_seen = line; print(f"=== FOUND (raw): {line} ===", flush=True)
                continue
            # selkies sends {"sdp": {"type": "offer", "sdp": "..."}} or {"ice": ...}
            t = obj.get("type")
            if "sdp" in obj or t == "sdp":
                sdp = obj.get("sdp", {})
                if isinstance(sdp, dict):
                    sdp_text = sdp.get("sdp", "")
                else:
                    sdp_text = sdp
                _seen_sdp = True
                print(f"[msg {msgs}] SDP type={sdp.get('type','?') if isinstance(sdp, dict) else '?'}", flush=True)
                for line in sdp_text.splitlines():
                    if line.startswith("m=video") or line.startswith("m=audio"):
                        print(f"    {line}", flush=True)
                        if line.startswith("m=video"):
                            m_video_seen = line
                # We have the offer — that's the gate. Bail.
                break
            elif "ice" in obj or t == "ice":
                if not _seen_sdp:
                    print(f"[msg {msgs}] ICE candidate (waiting for SDP offer...)", flush=True)
                continue  # don't spam ICE candidates
            else:
                print(f"[msg {msgs}] type={t} keys={list(obj.keys())}", flush=True)
        print("", flush=True)
        if m_video_seen:
            port_num = m_video_seen.split()[1] if len(m_video_seen.split()) > 1 else "?"
            print(f"=== RESULT: {m_video_seen}", flush=True)
            if port_num != "0":
                print(f"=== GATE PASSED: m=video:{port_num} — video track offered (waylanddisplaysrc compositor engaged) ===", flush=True)
                sys.exit(0)
            else:
                print(f"=== GATE FAILED: m=video:0 — no video track (the §17.3 bug persists) ===", flush=True)
                sys.exit(1)
        else:
            print("=== RESULT: no m=video line found in the SDP offer ===", flush=True)
            sys.exit(1)

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = sys.argv[2] if len(sys.argv) > 2 else "16100"
    peer_id = sys.argv[3] if len(sys.argv) > 3 else "1"
    asyncio.run(main(host, port, peer_id))
