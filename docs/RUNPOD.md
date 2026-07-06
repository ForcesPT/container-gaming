# DpadCloud on RunPod

RunPod is the **userns-capable provider** (the second provider after Vast). Two
things make it interesting vs. Vast:

1. **User namespaces are available** (RunPod pods run with a real `unshare -U`).
   That means Steam's pressure-vessel runtime works natively → CEF webhelper
   works → the **interactive Steam UI logs in** → cloud saves / achievements /
   online multiplayer. On Vast this was blocked (CEF crashed under bubbleroot's
   ptrace). So on RunPod the *full* Steam experience may work (validate it).
   The headless `steamcmd + dpad-launch` path still works too — it's a fallback.
2. **No UDP.** Pods only do TCP. Our image already uses **TCP-only coturn TURN**
   (`SELKIES_TURN_PROTOCOL=tcp`), so WebRTC media relays fine. Native Moonlight
   (which needs UDP 47989/48010/47984) only works *over Tailscale* (DERP relays
   over TCP/HTTPS), not over a direct public IP.

## Networking model (how RunPod differs from Vast)

| | Vast | RunPod |
|---|---|---|
| Browser web UI | cloudflared quick tunnel (outbound) | **same** — cloudflared quick tunnel (outbound, zero inbound HTTP ports) |
| WebRTC media relay | coturn on the 73478 "identity port" (1:1 public mapping) | coturn on a **normal TCP port** (`3478/tcp`); entrypoint fetches the mapped external port from the RunPod API |
| Public IP env | `PUBLIC_IPADDR` (set by Vast) | resolved via `GET /v1/pods/{id}` `publicIp` field (RunPod API; `RUNPOD_API_KEY`+`RUNPOD_POD_ID` are auto-injected) |
| TURN port (browser-facing) | `VAST_TCP_PORT_73478` (= 73478, 1:1) | the mapped **external** port from `portMappings["3478"]` |
| UDP | available | **none** → native Moonlight only via Tailscale |
| User namespaces | none → Steam UI blocked | **available** → Steam UI likely works |

The entrypoint auto-detects RunPod (`RUNPOD_POD_ID` is set by RunPod) and reads the **two env vars RunPod auto-injects into every pod** (no API call, no manual lookup needed — see RunPod's env-vars docs):
- `RUNPOD_PUBLIC_IP` → the pod's public IP (used for coturn `--external-ip` + the browser TURN URL).
- `RUNPOD_TCP_PORT_3478` → the external port RunPod mapped to our exposed `3478/tcp` (the pattern is `RUNPOD_TCP_PORT_<internal>`, the same one RunPod's SSH setup uses for `RUNPOD_TCP_PORT_22`).

Then it:
- binds coturn on `0.0.0.0:3478` (`--listening-ip=0.0.0.0`) so RunPod's TCP port
  forward reaches it regardless of which container interface the traffic lands on
  (the default coturn auto-bind to `127.0.0.1` + the container eth0 IP left it
  unreachable in testing),
- starts coturn with `--external-ip=<publicIp>`,
- writes a **dual-ICE `rtc_config.json`** (Selkies) / adds a 2nd ICE server (mws)
  with TWO TURN entries — `turn:127.0.0.1:3478` (Selkies/mws reach coturn locally,
  no NAT-loopback needed) and `turn:<publicIp>:<externalPort>` (the browser reaches
  coturn via the RunPod TCP map). Both peers are TURN clients of the SAME coturn,
  which short-circuits the media internally over the two control connections, so
  only the listening port needs to be exposed.

Manual overrides `DPAD_TURN_PUBLIC_IP` / `DPAD_TURN_EXTERNAL_PORT` still win if set
(belt-and-suspenders), and the RunPod REST API is a last-resort fallback — but
the injected env vars make the pod zero-config. The boot log prints
`RunPod env: RUNPOD_PUBLIC_IP=... RUNPOD_TCP_PORT_3478=...` so you can confirm.

The web UI still rides on **cloudflared quick tunnels** (outbound HTTPS → no
inbound HTTP port needed). The browser URL is printed in the pod logs as
`mws tunnel URL: https://....trycloudflare.com`.

> Why a single normal TCP port is enough: when both WebRTC peers are TURN
> clients of the *same* coturn, media relays internally over their two control
> connections to coturn's **listening port**; the per-allocation relay ports are
> never contacted externally. So only coturn's listening port (`3478`) needs to
> be reachable, and the browser just dials `publicIp:<externalPort>`.
>
> Why not the `>70000` "symmetrical port" tokens? The RunPod **REST API** accepts
> them as a special signal (allocate matching internal==external port), but the
> **console UI** validates port numbers ≤ 65535 and rejects them. Exposing a
> normal `3478/tcp` works from the UI; the entrypoint reconciles the external
> port from the API.

## Template config (RunPod console → New Template, or REST API)

```
Name:                DpadCloud Gaming (Steam, Ubuntu 24.04)
Container image:     forcespt/dpadcloud-gaming:SteamUbuntu24.04
Compute type:        NVIDIA GPU
Container disk:      32 GB
Volume disk:         0 GB   (persistent storage; 0 for ephemeral per-session)
Volume mount path:   /workspace   (ignored if volume = 0)
Container start cmd: (leave blank — use the image ENTRYPOINT)

HTTP ports:           (none — web UI via cloudflared quick tunnel)
TCP ports:            3478/tcp       <- coturn TURN listening port (WebRTC media)

Environment variables:
  SUNSHINE_PASSWORD=pass
  SELKIES_BASIC_AUTH_USER=dpad
  SELKIES_BASIC_AUTH_PASSWORD=pass
  STEAM_USER=forcestuga
```

> `3478` is a real port (the standard TURN port, ≤65535, accepted by the console
> UI). RunPod maps it to a public IP + a random external port (e.g.
> `213.x.x.x:13007 -> :3478`). The entrypoint reads that external port from the
> RunPod API and points the browser's TURN ICE server at
> `publicIp:<externalPort>` — you don't need to know the external port yourself;
> it's handled automatically.

### Optional add-ons

- **Sunshine Web UI** (enthusiast; HTTPS self-signed on 47990): add `47990/tcp`
  to TCP ports. Reach it at `<publicIp>:<mapped-external-port>` (browser will
  warn about the self-signed cert). Not needed for the browser gaming path.
- **Named Cloudflare tunnel** (production, stable `play-<id>.dpadcloud.com`
  URL instead of ephemeral trycloudflare.com): add
  `CLOUDFLARED_TUNNEL_TOKEN=<token>` + `CLOUDFLARED_HOSTNAME=https://play-<id>.dpadcloud.com`.
- **Native Moonlight over Tailscale**: add `TAILSCALE_AUTH_KEY=tskey-...` env.
  Native Moonlight connects over the Tailnet IP (Tailscale DERP relays over
  TCP/HTTPS, so no UDP needed). Without Tailscale, native Moonlight does NOT work
  on RunPod (it needs UDP).

### Cloud / public IP

- **Secure Cloud**: always gets a public IP for TCP ports. Recommended.
- **Community Cloud**: requires the host to `supportPublicIp` and the pod to
  request a public IP (`--require-public-ip` / "Require public IP"). If
  `publicIp` comes back null, coturn falls back to the pod's egress IP, which
  may not match the TCP public IP → WebRTC media fails. Prefer Secure Cloud.

## How to launch + connect

1. Deploy the pod from the template (pick an RTX 30/40/A-series GPU; the image
   is CUDA 12.5.1 so any driver ≥525 works; RTX 50/Blackwell needs the
   `:ubuntu24.04-rtx50` image variant with CUDA 12.8).
2. Wait ~60–90s, then open the pod **Logs** tab and look for:
   ```
   [*] Provider: RunPod  turn_port=<NNNNN>  public_ip=<A.B.C.D>
   [mws-autopair] SUCCESS — mws is paired with Sunshine
   mws running on 0.0.0.0:8080 (Sunshine NVENC -> WebRTC)
   mws tunnel URL: https://<random>.trycloudflare.com
   ```
3. Open the **`mws tunnel URL`** in a browser → log in (`dpad` / the
   `SUNSHINE_PASSWORD`) → the `localhost` host is already paired (auto-pair at
   boot) → launch an app / Desktop.
4. The browser's WebRTC peer connection relays media through coturn at
   `<publicIp>:<NNNNN>` (TCP). If video doesn't connect, verify coturn is
   reachable: from outside, `nc -vz <publicIp> <NNNNN>` should succeed.

## Verify after boot (from the pod web terminal / exec)

```bash
# coturn listening on 3478 (internal); browser-facing external port from the API?
echo "coturn listen: 3478 ; browser TURN port: see the 'Provider: RunPod' line in logs"
ss -lntp | grep turnserver

# publicIp resolved?
grep -i 'Provider: RunPod' /proc/1/fd/1 2>/dev/null || true   # or just read logs

# Sunshine encoder?
grep -i 'Found H.264 encoder' /tmp/sunshine.log

# mws streamer?
tail -n 60 /tmp/mws.log

# User namespaces? (if YES -> full Steam UI works)
unshare -U true && echo "userns: YES" || echo "userns: NO"
```

## What to validate on RunPod (the interesting bits)

1. **Does the interactive Steam UI log in?** With userns available, Steam's
   pressure-vessel + CEF should work → first-run Steam Guard, then cloud saves +
   achievements + online. If yes, RunPod becomes the **full-Steam provider**
   (Vast stays the cheap single-player / headless path). The image already
   autostarts Steam on the XFCE desktop (`DPAD_AUTOSTART_STEAM=1`); just open the
   mws Desktop and watch Steam come up. `DPAD_BUBBLEROOT` should stay `auto`
   (it won't activate since `unshare -U` succeeds).
2. **WebRTC media through coturn on the mapped TCP port** — the core
   networking change. If the mws page loads but video never connects, the
   `publicIp`/external port advertised to the browser is wrong: check the
   `[*] Provider: RunPod coturn_listen=3478 turn_ext=<NNNNN> public_ip=<A.B.C.D>`
   line, `/tmp/coturn.log`, and `chrome://webrtc-internals`. From outside the pod,
   `nc -vz <publicIp> <NNNNN>` should reach coturn (NNNNN = turn_ext above).
3. **Xorg + nvidia-DDX**: RunPod may grant CAP_SYS_ADMIN / DRM master, which
   would let the DDX use real KMS modesetting instead of the NULL-mode
   workaround (better for Vulkan present / DXVK). `DPAD_XORG=1` (default) still
   applies; watch `/tmp/xorg.log` for whether it used modeset or NULL mode.

## Provider split (where this leaves the product)

- **Vast** — cheapest, no userns → headless `steamcmd + dpad-launch`, single
  player, local saves persisted per-user. No Steam Cloud/online.
- **RunPod** — userns → full interactive Steam UI + standard Proton + cloud
  saves + online. Slightly pricier. The image is provider-agnostic; the
  orchestrator routes by need.