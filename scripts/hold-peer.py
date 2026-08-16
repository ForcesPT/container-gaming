#!/usr/bin/env python3
# hold-peer.py — connect to a selkies-gstreamer signaling endpoint as a browser
# peer, exchange HELLO, then HOLD the connection open for N seconds (default 60)
# so the compositor's wayland-N socket appears + the wayland client (sway) stays
# up long enough to reproduce/observe the §16.9 sway SIGTRAP (~33s). Unlike
# selkies-sdp-probe.py (which bails after the SDP offer → peer disconnects →
# compositor tears down → sway never reaches the crash), this stays connected.
#
# Prints the m=video / m=audio lines from the SDP offer + a heartbeat. Does NOT
# complete the WebRTC handshake (no aiortc) — holding the signaling socket is
# enough to keep the compositor up (the §16.7 audio-pollution caveat does NOT
# apply: there is no later browser peer to pollute self.peers for).
#
# Usage: python3 hold-peer.py <host> <port> [peer_id] [hold_seconds]
#   peer_id defaults to 1 (the selkies app's video peer). hold_seconds default 60.
import asyncio, sys, json, os, time

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets", file=sys.stderr); sys.exit(2)


async def main(host, port, peer_id, hold_s):
    my_id = str(peer_id)
    user = os.environ.get("SELKIES_USER", "dpad")
    pw = os.environ.get("SELKIES_PASS", "testpass")
    uri = f"ws://{user}:{pw}@{host}:{port}/ws"
    print(f"[*] connect to ws://{host}:{port}/ws as peer {my_id}, hold {hold_s}s", flush=True)
    async with websockets.connect(uri, max_size=2**24, ping_interval=20) as ws:
        await ws.send(f"HELLO {my_id}")
        resp = await asyncio.wait_for(ws.recv(), timeout=15)
        if resp != "HELLO":
            print(f"[!] unexpected HELLO response: {resp!r}", flush=True); sys.exit(1)
        print(f"[*] HELLO exchanged (t=0) — compositor should start, sway launches on socket appear", flush=True)
        t0 = time.time()
        m_video = m_audio = None
        last_beat = 0
        while time.time() - t0 < hold_s:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                body = msg
                if body.startswith(f"{peer_id} "):
                    body = body[len(f"{peer_id} "):]
                try:
                    obj = json.loads(body)
                except Exception:
                    if "m=video" in msg or "m=audio" in msg:
                        for line in msg.splitlines():
                            if line.startswith("m=video") and m_video is None:
                                m_video = line
                                print(f"  [t={time.time()-t0:.1f}s] SDP {line}", flush=True)
                            elif line.startswith("m=audio") and m_audio is None:
                                m_audio = line
                                print(f"  [t={time.time()-t0:.1f}s] SDP {line}", flush=True)
                    continue
                t = obj.get("type")
                if "sdp" in obj or t == "sdp":
                    sdp = obj.get("sdp", {})
                    sdp_text = sdp.get("sdp", "") if isinstance(sdp, dict) else sdp
                    for line in sdp_text.splitlines():
                        if line.startswith("m=video") and m_video is None:
                            m_video = line; print(f"  [t={time.time()-t0:.1f}s] SDP {line}", flush=True)
                        elif line.startswith("m=audio") and m_audio is None:
                            m_audio = line; print(f"  [t={time.time()-t0:.1f}s] SDP {line}", flush=True)
                elif "ice" in obj or t == "ice":
                    pass  # quiet
                else:
                    print(f"  [t={time.time()-t0:.1f}s] msg type={t} keys={list(obj.keys())}", flush=True)
            except asyncio.TimeoutError:
                pass
            now = time.time() - t0
            if now - last_beat >= 10:
                last_beat = now
                print(f"[*] still connected at t={now:.0f}s (m_video={m_video!r})", flush=True)
        print(f"[*] hold done at t={time.time()-t0:.0f}s — closing", flush=True)
        print(f"=== m_video={m_video}  m_audio={m_audio}", flush=True)
    print("[*] peer disconnected", flush=True)


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = sys.argv[2] if len(sys.argv) > 2 else "16100"
    peer_id = sys.argv[3] if len(sys.argv) > 3 else "1"
    hold_s = int(sys.argv[4]) if len(sys.argv) > 4 else 60
    asyncio.run(main(host, int(port), peer_id, hold_s))