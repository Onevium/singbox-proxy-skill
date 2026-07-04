# Providers & tools — picking a clean VPS and a stable exit IP

Two independent choices decide whether this works well. Verify current
pricing/terms yourself — this is guidance, not endorsement.

```
your device ──▶ VPS relay (entry, clean IP) ──▶ [optional] upstream proxy (stable exit IP) ──▶ Internet
                └ sing-box + this panel          └ static residential / ISP IP
```

## Why a *stable* exit IP (the Claude Code angle)

AI dev tools — **Claude Code / Claude API, OpenAI, Cursor, Copilot** — are
sensitive to the IP you connect from:

- **Datacenter / cloud IPs** are often rate-limited, challenged, or outright
  blocked by these services (they look like bots/VPNs).
- **Shared VPN IPs** rotate and get flagged; you hit CAPTCHAs and 403s.
- A **static residential / ISP IP** looks like a normal home user: consistent,
  trusted, no rotation. Your Claude Code stays logged in and unthrottled.

So the winning setup for reliable AI-tool access is: a nearby **clean-IP VPS** as
the entry (fast handshake, good route to you) chained to a **static residential
upstream** as the exit (the stable identity the AI service sees). If you only
need to bypass a network block and don't care about IP reputation, skip the
upstream and exit directly from the VPS.

## 1) The VPS (entry relay)

Pick a region with a good route to you and a **clean IP**. IP cleanliness varies
per instance — if a fresh IP is blocked from your network, destroy it and get
another (see `troubleshooting.md`).

| Provider | Notes |
|---|---|
| **Vultr / DigitalOcean / Linode (Akamai)** | Global, hourly billing → cheap to churn a dirty IP. Datacenter IPs. |
| **Hetzner** | Cheap EU/US; great value, datacenter IPs. |
| **Oracle Cloud** | Free-tier ARM instances; good for a always-on relay. |
| **腾讯云 / 阿里云 轻量应用服务器** | Seoul / Tokyo / HK / Singapore nodes are close to China; simple console firewall. Japan IPs are often pre-flagged — prefer **Seoul / Singapore / HK**. |
| **BandwagonHost (搬瓦工)** | **CN2 GIA** premium lines = very stable China↔US routing. |

Rules of thumb for users behind heavy censorship:
- Prefer **nearby regions**: Hong Kong, Japan, Korea, Singapore.
- Prefer **premium lines** (CN2 GIA / 三网优化) for latency + stability.
- Keep the instance **hourly / easily replaceable** so a dirty IP costs minutes.

## 2) The upstream exit proxy (stable IP) — optional

For a trusted, non-rotating exit IP, chain through a **static residential / ISP**
proxy. Set `UPSTREAM_URL=socks5://user:pass@host:port` (or `http://…`).

| Type | Providers (examples) | Trade-off |
|---|---|---|
| **Static residential / ISP** (best for AI tools) | Bright Data, Oxylabs, IPRoyal, Proxy-Cheap, Decodo (Smartproxy), NetNut | Stable single IP; often **speed-capped** (e.g. ~20 Mbps) and priced per-IP/GB. |
| **Rotating residential** | same providers | Cheaper/GB but the IP *rotates* — bad for staying logged in; avoid for Claude Code. |
| **Datacenter proxy** | most VPS + a SOCKS server | Fast + cheap, but the same reputation problems as a bare VPS IP. |

Notes:
- Want it stable for AI logins → **static residential/ISP**, not rotating.
- The upstream account's plan is your **speed ceiling**; a bigger VPS won't
  raise it. Test the chained path, not just the VPS (`troubleshooting.md`).
- Some upstreams block non-web ports; if a chained request stalls on an unusual
  port, try 443/80.

## 3) Domain (stable endpoint) — optional but recommended

Any registrar/DNS with a plain **A record** works: Cloudflare (DNS-only / **grey
cloud**), DNSPod, Namecheap, Porkbun, Route 53. Point clients at the domain, not
the IP → migrating servers is a one-line DNS change. **Never** put the SS domain
behind Cloudflare's orange-cloud proxy; it can't carry Shadowsocks.

## 4) Clients

- **Desktop:** Clash Verge Rev (mihomo), Stash.
- **Phone:** Hiddify, Stash, official sing-box app. (This skill ships **classic
  SS**, which all of them import cleanly.)
