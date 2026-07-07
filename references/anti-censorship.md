# Anti-censorship modes — block vs throttle, and how to actually survive

Classic Shadowsocks on a clean IP is the simple default, but a censoring firewall
has **two** weapons, and a clean IP only defeats one of them:

| What the firewall does | Symptom | Real fix |
|---|---|---|
| **Null-route the IP** | Every port times out from inside, but the server is reachable from abroad | A **clean IP** (new instance/region). Config changes won't help. |
| **Fingerprint + throttle the protocol** | TCP connects fine, the proxy even works — but speed is choked to a few KB/s (unusable), or drops randomly | A **censorship-resistant transport** (REALITY or CDN). A new IP just gets throttled again. |

The second one is the trap: people keep swapping IPs when the problem is that
**classic SS traffic is fingerprintable**. Once you've seen a *clean* IP get
throttled to ~10 KB/s, stop changing IPs and change the transport.

## Diagnose first (block vs throttle)

Test from a **clean** China vantage — a machine with **no VPN/TUN running**. A
proxy client active on the test machine (Clash TUN, another VPN) silently routes
your `curl`/`nc` through *itself* and poisons every result. Turn it off first.

- `nc -zv -G5 <ip> <port>` from inside **times out**, but 8+ overseas nodes on
  `check-host.net` connect in <400 ms → **IP null-routed** → new clean IP.
- `nc` **connects**, but a real download through the proxy is a few KB/s while the
  raw line (`scp` a 10 MB file over SSH) is far faster → **protocol throttle** →
  REALITY or CDN below.
- `ping <ip>` bypasses Clash TUN (ICMP isn't proxied), so it's a rare clean signal
  even with the tunnel up — useful for latency to an origin or to CF IPs.

## The three modes — pick one in Step 0

| Mode | Hides IP? | Beats throttle? | Needs | Speed on a bad China line |
|---|---|---|---|---|
| **A. Classic SS** | no | no | nothing | best *if* IP is clean & untargeted |
| **B. VLESS + REALITY** | no (IP exposed) | **yes** (no fingerprint) | nothing extra | full line speed, but IP can still be null-routed |
| **C. VLESS + WS + TLS behind Cloudflare** | **yes** (origin hidden) | **yes** | a domain on Cloudflare | capped by the China→CF route (often 1–2 Mbps on 电信), but unblockable |

Rule of thumb: **A** until it's targeted → **B** if the IP is clean but throttled
and you don't want a domain → **C** when the IP keeps getting blocked *and* you
want it to stay reachable no matter what (the durable end state).

---

## Mode B — VLESS + REALITY

Traffic is indistinguishable from a real TLS visit to a big site; the firewall
can't fingerprint it. No domain, no CDN. The origin IP is still exposed, so a
determined firewall can still null-route it — but it won't *throttle* you.

**The one gotcha that costs hours: the REALITY handshake target (`server_name` /
`handshake.server`) MUST be a site that speaks TLS 1.3 + X25519 + HTTP/2.**
`www.microsoft.com` does **not** and yields `REALITY: processed invalid
connection` on every handshake — with perfectly correct keys. Use one of:
`gateway.icloud.com`, `www.apple.com`, `dl.google.com`, `www.lovelive-anime.jp`.

Server inbound (sing-box):
```jsonc
{ "type":"vless","listen":"::","listen_port":443,
  "users":[{"uuid":"<uuid>","flow":"xtls-rprx-vision"}],
  "tls":{"enabled":true,"server_name":"gateway.icloud.com",
    "reality":{"enabled":true,
      "handshake":{"server":"gateway.icloud.com","server_port":443},
      "private_key":"<from: sing-box generate reality-keypair>",
      "short_id":["<from: sing-box generate rand 8 --hex>"]}}}
```
- Generate keys once: `sing-box generate reality-keypair` (private→server,
  public→clients), `sing-box generate uuid`, `sing-box generate rand 8 --hex`.
- One UUID per device (revoke individually); all share the keypair + short_id.
- Put REALITY on **443** — that's what "a normal HTTPS site" looks like.

**mihomo (Clash) compatibility:** sing-box↔sing-box works with
`flow: xtls-rprx-vision`, but **mihomo clients can fail the handshake with vision
flow — drop the flow** (plain VLESS+REALITY) for Clash Verge / Stash users.
Verify with a loopback sing-box client before blaming the client.

---

## Mode C — VLESS + WS + TLS behind Cloudflare CDN (the durable one)

```
client → Cloudflare edge (优选IP, standard TLS) → CF → origin VPS (VLESS+WS+TLS) → [upstream] → internet
```
The client only ever talks to **Cloudflare** on port 443 with ordinary TLS. The
origin IP never appears on the wire, so the firewall can't block or throttle it
(blocking CF would break half the web). This survives everything — at the cost of
being capped by the China→CF route quality.

### 1. Domain onto Cloudflare (required — orange cloud needs CF as authoritative)
Add the domain in CF (free plan), let it import existing records, then change the
**registrar's nameservers** to the two CF gives you. If the domain is
Tencent-registered, `tccli domain ModifyDomainDNSBatch --Domains '["ex.com"]'
--Dns '["a.ns.cloudflare.com","b.ns.cloudflare.com"]'`. `.com` NS propagates in
minutes. Any records CF auto-imported that point at the VPS on non-HTTP ports
(SS, a panel) must be set **DNS-only (grey)** or they break.

### 2. Origin inbound — VLESS + WS + TLS on a CF-proxied port
Cloudflare only proxies these origin ports: **443, 2053, 2083, 2087, 2096, 8443**
(HTTPS) — and it connects back on the *same* port the client used. Pick one that's
free on the box (e.g. **2053**, so classic-SS 443 can keep running as fallback).
```jsonc
{ "type":"vless","listen":"::","listen_port":2053,
  "users":[{"uuid":"<uuid>"}],
  "tls":{"enabled":true,"server_name":"cdn.example.com",
    "certificate_path":"/etc/sb-cdn/cert.pem","key_path":"/etc/sb-cdn/key.pem"},
  "transport":{"type":"ws","path":"/<random-hex>"} }
```
- Self-signed cert is fine: `openssl req -x509 -newkey rsa:2048 -nodes -days 3650
  -keyout key.pem -out cert.pem -subj "/CN=cdn.example.com"`.
- Run it as a **separate service** (`sing-box-cdn`) alongside the SS one so you
  never restart the connection the user is currently on.

### 3. Cloudflare records + SSL
- DNS: `A cdn → <origin IP>`, **Proxied (orange)**.
- SSL/TLS mode: **Full** (accepts the self-signed origin cert). Modern zones
  often default to this already — test before assuming you must change it.
- CF issues a Universal SSL cert for the new hostname in ~5–15 min; until then the
  client→CF TLS handshake fails. Wait, then retry.

### 4. Client config — use a 优选IP, not the domain
Cloudflare's *default* IPs route badly from China (200–300 ms, packet loss). Pin
the client to a **优选IP** (a CF anycast IP that routes to a nearby PoP) as the
**server address**, and set SNI + WS `Host` to the domain:
```yaml
- name: CDN
  type: vless
  server: 104.19.200.1        # 优选IP (scan for your line — see below)
  port: 2053
  uuid: <uuid>
  tls: true
  servername: cdn.example.com
  network: ws
  ws-opts: { path: /<random-hex>, headers: { Host: cdn.example.com } }
```
Using an IP (not the domain) as `server` also sidesteps the desktop-Clash TUN
DNS-deadlock (see `troubleshooting.md`).

**Finding a 优选IP:** ICMP ping bypasses Clash TUN, so from the user's own machine
`ping` a spread of CF IPs (`104.16–104.28.*`, `172.64–172.67.*`) and pick the
**lowest loss** (latency is usually a flat ~180 ms on 电信 — loss/jitter is the
real differentiator; a 0%-loss 184 ms IP beats a 180 ms 33%-loss one). Good IPs
rotate — treat this as periodic maintenance, or run CloudflareSpeedTest.

### Reality check on speed
CF hides the origin and kills throttling, but it **cannot fix a bad China→CF
backbone route** — expect ~1–2 Mbps single-stream on a mediocre 电信 line vs the
few-KB/s a throttled SS gives. It's a 10–100× win over a throttled proxy and it's
unblockable; it is *not* a low-latency pipe. Only IPLC/dedicated transit fixes the
latency, at real cost.

## Combining with the residential upstream
All three modes keep the optional upstream SOCKS5/HTTP exit unchanged — the
inbound transport (SS / REALITY / WS-TLS) is independent of the outbound
(`direct` or `socks → residential`). A CDN node still exits from your static
residential IP; only the *client-facing* hop changed.
