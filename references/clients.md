# Client setup

Every account exposes two forms (panel → account → **Config**): an `ss://` URI
(for phones) and a full Clash/Mihomo YAML (for desktops). The cipher is
`aes-256-gcm`; the "account" is `server + port + password`.

Verify success by opening `https://ifconfig.me` — it should show your expected
egress IP (the upstream's exit if configured, otherwise the VPS IP).

## Desktop

### Clash Verge Rev / mihomo (Windows, macOS, Linux)
1. Profiles → import the full YAML (from the panel Config page, or a saved file).
2. Mode: **Rule**. Turn on **System Proxy**. For apps that ignore the system
   proxy, also enable **TUN / virtual NIC**.
3. Pick the node in the `Proxy` group.

### Stash (macOS, iOS)
Import the same Clash YAML (Stash uses a Clash-compatible core). Good iOS choice.

## Phone

### Hiddify (iOS, Android)
Copy the `ss://` line → Hiddify → import from clipboard → connect.
Hiddify handles **classic SS** cleanly (this skill's default).

### sing-box (official app)
Import the `ss://` URI, or a full sing-box JSON profile.

## Split routing

The exported Clash config sends China/private/LAN traffic **DIRECT** and
everything else through the proxy (`GEOSITE,cn` / `GEOIP,CN` / private ranges +
the server's own domain DIRECT to avoid a self-proxy loop). Edit the `rules:`
block to taste. Use **Rule** mode, not Global, or domestic traffic is proxied too.

## Migrating servers

Because configs point at your **domain**, a server migration is just a DNS A
record change — clients keep working with **zero re-import**. (If you point
clients at a raw IP instead, every device must re-import on migration.)
