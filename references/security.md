# Security model

The whole design assumes **the panel is never publicly reachable** and the
server is a hardened, single-purpose relay.

## Threat model

- The admin panel manages every account and the sing-box config — compromising it
  compromises everything. So it must not be brute-forceable from the internet.
- Shadowsocks accounts are the only public surface. Each is protected by an
  AEAD password; the port + password *is* the account (SS has no username).

## What `harden.sh` does

- **SSH:** key-only (`PasswordAuthentication no`), no root login, ports 22 + 2222.
  Neutralises Ubuntu's `50-cloud-init.conf` which otherwise re-enables password
  auth (sshd honours the first match). Validates with `sshd -t` before restart
  and rolls back on error.
- **UFW:** default deny incoming; allow only SSH + the Shadowsocks ports.
- **fail2ban:** bans SSH brute-force sources.
- **unattended-upgrades:** automatic security patches.

Always **open the same ports in your cloud provider's firewall / security group**
too — UFW is only the inner layer.

## Reaching the panel

Preferred: **SSH tunnel**, panel stays on `127.0.0.1`:
```bash
ssh <args> -L 17000:127.0.0.1:7000 user@host
open http://127.0.0.1:17000
```

Only if you must have browser access without a tunnel: expose port 7000 but
**lock the source IP** to a single address you control (e.g. a static egress IP),
in *both* UFW (`ADMIN_SRC_IP=...` for `harden.sh`) and the cloud firewall. This
is HTTP (no TLS) and the panel's password is the last line of defence — keep it
strong, and prefer a TLS-fronted auth gateway (e.g. Cloudflare Access) if you
need real remote browser access.

## Secrets discipline

- Account passwords, the upstream proxy creds, the admin password, and SSH keys
  live only on the server (`/etc/proxy-admin/`, `/etc/sing-box/`, `~/.ssh`).
- The initial admin password is written to
  `/etc/proxy-admin/initial-admin-password.txt` (mode 0600) — read it once, then
  you may delete it.
- **Never commit** any of these. `.gitignore` excludes `*.pem`, `config.json`,
  `clients.json`, `admin.json`, and `_secrets/`.
- Client config files contain live passwords — treat them as secrets; don't paste
  them into shared logs or public issues.

## Account hygiene

- One account per device/person. If a device is lost, **rotate** just that
  account (panel → Rotate) — no one else re-imports.
- Prefer stealthy, commonly-open ports (443, 80, 8443) for reachability through
  restrictive networks.
