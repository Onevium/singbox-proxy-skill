---
name: singbox-proxy
description: >-
  Deploy and manage your own hardened Shadowsocks proxy on a fresh VPS —
  sing-box (classic aes-256-gcm, one account per port), a single-file web admin
  panel with live server monitoring, SSH/UFW/fail2ban hardening, an optional
  upstream SOCKS5/HTTP exit (residential proxy), an optional domain so you can
  swap servers without re-issuing client configs, and one-click Clash / ss://
  exports. Picks an anti-censorship transport — classic SS, VLESS+REALITY, or
  VLESS+WS+TLS behind a Cloudflare CDN — so a clean IP that gets blocked or
  throttled still survives. Use when the user wants to "set up a proxy / VPN
  server", "deploy shadowsocks / sing-box / reality / cloudflare cdn proxy",
  "self-host a proxy", "make my own VPN", "get around GFW blocking or throttling",
  "migrate my proxy to a new server", or "add / rotate a proxy account".
argument-hint: "<user@host> [domain]"
user-invocable: true
---

# sing-box Proxy — deploy & manage your own

You are standing up a **personal, hardened Shadowsocks relay** on a VPS the user
controls, plus a small web panel to manage accounts. Move top to bottom; each
step links one level deep into `references/` for detail.

## Iron rules (learned the hard way)

1. **Classic Shadowsocks (`aes-256-gcm`), not SS2022.** SS2022 multi-user
   (combined `iPSK:uPSK` key) is elegant but **Hiddify can't parse it**, and its
   censorship behaviour is unproven. Classic SS works in every client and is
   field-tested through restrictive networks. This skill ships classic SS.
2. **A firewall blocks two ways — a new IP only fixes one.** If TCP times out
   from inside but the server answers from abroad, the **IP is null-routed** →
   get a clean IP. But if TCP *connects* and the proxy even works, yet speed is
   choked to a few KB/s on a **clean** IP, the firewall is **fingerprinting and
   throttling classic SS** — a new IP just gets throttled again. That's the trap:
   stop swapping IPs and switch the **transport** (REALITY or Cloudflare CDN).
   See `references/anti-censorship.md` (block-vs-throttle diagnosis + modes) and
   `references/troubleshooting.md`.
3. **Never expose the panel to the public internet.** It binds `127.0.0.1:7000`.
   Reach it over an SSH tunnel. The only acceptable public exposure is a
   firewall rule that allows a **single source IP** (e.g. your static egress).
4. **Point clients at a domain, not the raw IP.** Then migrating servers is a
   one-line DNS change — clients never re-import. For SS/REALITY the record is
   **DNS-only** (plain A; Cloudflare "orange cloud" can't carry SS). The one
   exception is **CDN mode** (`references/anti-censorship.md`): there the orange
   cloud + a VLESS+WS+TLS origin is the whole point, and clients pin a CF 优选IP.
5. **Secrets stay on the server.** Upstream creds, account passwords, SSH keys,
   admin password — never commit them, never print them into shared logs.
6. **One account = one port = one password — open every port in *two* firewalls.**
   Classic SS has no multi-user, so each account needs its own port, and each port
   must be allowed in BOTH the machine's **UFW** *and* the **cloud provider's
   security group / firewall console**. The panel auto-runs `ufw allow`/`ufw
   delete` on account add/delete, so **UFW is handled — only the cloud layer is
   manual**. Forgetting the cloud layer looks like *"some ports connect, others
   time out"* (e.g. 80 works, 443 hangs). Tell the user this up front, list
   exactly which ports to open in their cloud console, and remind them that
   **adding an account on a new port means opening that port in the cloud
   console too**. If they'd rather never touch the firewall again,
   offer the single-shared-port + single-password model (no per-device isolation).

## Step 0 — gather inputs from the user FIRST (reverse-prompt)

This skill is normally run by an agent for a user who may not have things ready.
**Ask for the following and wait for answers before touching anything** — don't guess:

**Required**
- A **fresh Ubuntu/Debian VPS** they control — its `user@host` and the **SSH key path**.
- The **cloud provider** (Tencent / Aliyun / Vultr / DO …) — you'll tell them the
  exact ports to open in its firewall console, the one layer you can't automate.
- **Which anti-censorship mode** (`references/anti-censorship.md`): **A** classic
  SS (simplest, default), **B** VLESS+REALITY (beats protocol throttling, no
  domain), or **C** VLESS+WS+TLS behind **Cloudflare** (hides the origin IP —
  unblockable *and* un-throttleable, needs a domain on Cloudflare). Start at A;
  move to B/C the moment a *clean* IP gets blocked or throttled. Mode C
  additionally needs a **domain whose nameservers you can move to Cloudflare**.

**Recommended / optional**
- A **domain** they control (stable, migratable endpoint). None → clients use the raw IP.
- An **upstream SOCKS5/HTTP proxy** (`socks5://user:pass@host:port`) for a static
  residential exit IP (`references/providers.md`). Omit → exit directly from the VPS.
- Their **rough location / censorship level** → pick a nearby clean-IP region.

If they don't have a VPS yet, help them pick one (`references/providers.md`) before
deploying. If they give a domain, also set `server_ip` in the panel config so the
Config page can hand out an **IP-based** config (desktop Clash often needs it — see
`references/troubleshooting.md`).

**Choosing a VPS and an exit IP:** see `references/providers.md` — clean-IP VPS
options, static-residential upstream providers, and *why a stable IP matters for
Claude Code / AI tools* (datacenter IPs get flagged; a static residential exit
stays trusted). Recommend a nearby, easily-replaceable clean-IP region; for
AI-tool reliability, chain through a **static** (not rotating) residential upstream.

## Deploy (fresh server)

1. **Reach the server.** `ssh <args> user@host 'echo ok; . /etc/os-release; echo $PRETTY_NAME'`.
   If the user's own machine runs a VPN in TUN mode, SSH to a brand-new IP may be
   captured by the tunnel — add a direct host route first (see
   `references/troubleshooting.md#tun`).
2. **Deploy + install.** From this repo:
   ```bash
   SERVER_HOST=vpn.example.com \
   FIRST_ACCOUNT=my-laptop FIRST_PORT=443 \
   [UPSTREAM_URL=socks5://user:pass@1.2.3.4:1080] \
   ./scripts/deploy.sh <ssh args> user@host
   ```
   This installs sing-box, writes the config, creates the first account + a
   random admin password, and starts the panel on `127.0.0.1:7000`.
   `SERVER_HOST` is the domain/IP clients connect to; `UPSTREAM_URL` is optional
   (omit → traffic exits directly from the VPS).
3. **Harden.** `sudo SS_PORTS="443 80 8443" TIMEZONE=Asia/Seoul bash scripts/harden.sh`
   — key-only SSH (22+2222), UFW, fail2ban, auto-updates. See `references/security.md`.
   **Verify a new SSH session works before closing the current one.**
4. **Open the cloud firewall.** UFW is only the inner layer — also open the SS
   ports (+ 22/2222) in the VPS provider's security group / firewall console.
5. **DNS (if using a domain).** Add a **DNS-only** A record for `SERVER_HOST` →
   the VPS IP. Low TTL (60–120s) so future migrations propagate fast.
6. **Verify end to end.** From the server, confirm the egress:
   `curl -x socks5h://<upstream> https://ifconfig.me/ip` (or plain `curl ifconfig.me`
   for a direct exit). Then have the user import a config (next) and open
   `https://ifconfig.me` — it should show the expected egress IP.

**Modes B / C (REALITY, Cloudflare CDN).** `deploy.sh` sets up classic SS. For
an anti-censorship transport, add its inbound as a **separate `sing-box-*`
service on its own port** so you never disturb a connection the user is on, then
follow `references/anti-censorship.md` end to end (REALITY handshake-target
gotcha, CF nameserver move, WS+TLS origin on a CF-proxied port, SSL=Full, 优选IP).
Keep SS running as a fallback until the new transport is verified from a clean
China vantage. **Verify by measuring from a machine with no VPN/TUN active** — a
client tunnel on the test box poisons every speed/reachability check.

## Manage accounts

Open the panel over an SSH tunnel:
`ssh <args> -L 17000:127.0.0.1:7000 user@host` → `http://127.0.0.1:17000`
(admin password printed by install, stored at `/etc/proxy-admin/`).

- **Dashboard** — live CPU / memory / disk / network, service health, egress IP,
  restart sing-box, speed test.
- **Accounts** — create (auto or fixed port), disable, rotate password, delete.
  One account = one port = one password, so losing a device = rotate just that one.
  New account on a new port → also open that port in the cloud firewall.
- **Config page** — per-account `ss://` URI (phone) + full Clash/Mihomo YAML
  (desktop), one-click copy **and download**, with a **Domain / IP toggle**:
  hand out the domain version for portability, or the IP version when a desktop
  Clash can't resolve the domain under TUN (set `server_ip` in the panel config
  to enable the IP tab).

## Give configs to devices

See `references/clients.md`. Short version:
- **Desktop (Clash Verge / mihomo, Stash):** import the full YAML.
- **Phone (Hiddify, Stash, sing-box app):** paste the `ss://` URI.

## Migrate to a new server

1. Deploy + harden on the new (clean-IP) VPS with the **same `SERVER_HOST`**.
2. Migrate upstream creds + accounts if you want identical passwords (copy
   `/etc/proxy-admin/{config,clients}.json` and re-apply), or just create fresh.
3. **Repoint the DNS A record** to the new IP. Clients change nothing.

## Troubleshooting

`references/troubleshooting.md` covers: proxy times out but TCP connects (dirty
IP / censorship), TUN captures SSH to a new IP, client can't resolve the domain,
Hiddify + SS2022, wrong egress IP, and the fail-safe apply behaviour.
