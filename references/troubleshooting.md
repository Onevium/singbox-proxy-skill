# Troubleshooting

## The proxy times out, but the port is reachable — dirty IP / censorship

Symptom: `nc -z <ip> 443` connects, the server tests fine locally, it works from
a machine *outside* the censored network — but the client just spins on
"connecting" and times out.

This is the single most common failure and it is **not your config**. A national
firewall lets the TCP handshake through (so `nc` succeeds) then interferes with
the proxy *data* — classic active interference on a flagged IP. Cheap
recycled cloud IPs (especially Japan Tencent/Alibaba ranges heavily used for
proxies) are frequently already dirty.

**Diagnose (decisive):** connect to the server's SS from a vantage point
*outside* the censored network (another VPS, a friend abroad). If it works there
but not from the censored network → the IP is being blocked on that path.

**Fix, in order of effort:**
1. **New IP.** Change the VPS public IP, or spin up a fresh instance — ideally in
   a region a working peer already uses. Re-deploy (5 min, all scripted) and
   repoint DNS. This resolves it the vast majority of the time.
2. If a *fresh* IP is *also* blocked immediately, the transport pattern is being
   fingerprinted — move to a TLS-camouflaged transport (Trojan / VLESS-Reality /
   ShadowTLS). Out of scope for this skill's classic-SS default, but a known next step.

Do **not** keep editing client config, swapping ports, or changing ciphers when
the real problem is the IP.

## <a id="tun"></a>SSH to a brand-new IP hangs (`kex_exchange_identification` / timeout)

If your **own machine runs a VPN in TUN mode** (Clash/mihomo virtual NIC), all
traffic — including SSH to the new server — is captured by the tunnel, and the
new IP isn't in the tunnel's direct rules, so the handshake dies.

Add a direct host route so traffic to the server bypasses the tunnel:
```bash
sudo route -n add -host <new-server-ip> <your-lan-gateway>   # macOS
# sudo ip route add <new-server-ip> via <lan-gateway>        # Linux
```
Remove it when done: `sudo route -n delete -host <new-server-ip>`.
(Alternatively: turn off TUN / "virtual NIC" mode while you deploy.)

## Client can't resolve the domain

- The A record must be **DNS-only**. On Cloudflare, the cloud icon must be
  **grey**, not orange — the orange proxy terminates TLS and cannot carry
  Shadowsocks.
- In fake-ip Clash setups, the proxy server's own domain must resolve to a real
  IP. The exported config already adds `+.<domain>` to `fake-ip-filter` and a
  `DOMAIN,<domain>,DIRECT` rule to prevent a self-proxy loop.
- For a quick isolation test, hand the phone an `ss://` that uses the **raw IP**
  instead of the domain; if that connects, the issue was domain resolution.

## Desktop Clash times out on a domain node (but the phone works)

Exact symptom: the phone (Hiddify) connects via the domain, but desktop Clash
Verge / mihomo times out on the *same* domain — activating it drops all internet,
so you revert to keep connectivity (which makes it look intermittent).

Cause: **mihomo uses its own internal DNS**, not the OS resolver. Under TUN, with
only DoH (`https://…`) nameservers and no `default-nameserver`, mihomo can't
bootstrap the resolvers and fails to resolve the proxy server's domain
(`context deadline exceeded`) — the node times out. The phone works because it
resolves via the OS; IP-based nodes work because they need no resolution.

Fixes (both shipped by this skill):
1. The exported Clash config now includes `default-nameserver` (plain-UDP
   `223.5.5.5 / 119.29.29.29 / 114.114.114.114`) so mihomo can resolve. Re-import
   the current config.
2. Or use the **IP tab** on the panel's Config page (needs `server_ip` set in the
   panel config) and import the IP version on that desktop — 100% reliable, at the
   cost of re-importing on a server migration. A common split: **desktop = IP,
   phone = domain**.

Confirm what mihomo actually resolves, via its control API:
`curl --unix-socket <verge-mihomo.sock> "http://localhost/dns/query?name=<domain>&type=A"`
— `context deadline exceeded` confirms the DNS-bootstrap problem.

## Hiddify shows "connecting" forever

Hiddify (sing-box core) reliably imports **classic SS** `ss://` links. It has
historically mishandled **SS2022 multi-user** links (the combined `iPSK:uPSK`
key). This skill ships classic SS specifically to avoid that. If a link still
fails in Hiddify, try **Stash** or the official **sing-box** app, or import the
full config instead of the bare URI.

## Wrong egress IP

- With an upstream proxy configured, the dashboard "egress IP" should be the
  **upstream's** exit. If it shows the VPS IP, the upstream isn't being used —
  check `/etc/proxy-admin/config.json` `upstream` and re-apply from the panel.
- On the client, if `ifconfig.me` shows your home IP, the proxy isn't active or
  the node isn't selected — pick the node and enable system proxy / TUN.

## Panel "apply" fails but nothing breaks

`apply_sing_box()` runs `sing-box check` on the *new* config in a temp file and
only swaps + restarts if it passes. A bad config fails the check and the live
service is left untouched — safe by design. Read the error shown in the panel.

## Bandwidth feels capped

If you chain through an **upstream residential proxy**, your ceiling is that
account's speed cap, *not* the VPS bandwidth. Test both legs separately: the VPS
direct download vs. the download through the upstream. If the VPS is fast but the
chained path is slow, the upstream plan is the bottleneck — a bigger VPS won't help.
