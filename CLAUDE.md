# CLAUDE.md

This repo is a Claude Code **skill**. Entry point: [`SKILL.md`](./SKILL.md).
Read it first, then follow its links into [`references/`](./references).

Quick map:
- `app.py` — the single-file admin panel (stdlib only; classic Shadowsocks).
- `scripts/install.sh` · `scripts/harden.sh` · `scripts/deploy.sh` — deployment.
- `references/providers.md` — VPS / exit-IP / domain recommendations.
- `references/troubleshooting.md` — dirty-IP, TUN, Hiddify, bandwidth, etc.

Guardrails when using this skill:
- Ship **classic Shadowsocks (aes-256-gcm)**, not SS2022.
- The panel binds `127.0.0.1` — never expose it publicly without a
  single-source-IP firewall rule.
- Never print or commit account passwords, upstream creds, admin passwords, or
  SSH keys. `.gitignore` already excludes the secret files.
