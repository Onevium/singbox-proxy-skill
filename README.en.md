[中文](README.md) · **English**

# singbox-proxy-skill — a stable-IP proxy for Claude Code & AI tools

> A **"stable-IP setup"** skill for developers: stand up a **sing-box Shadowsocks
> relay + web admin panel + hardening** on your own VPS, optionally chained to a
> **static residential exit**, so you can reach **Claude Code / Claude API / Codex /
> Cursor and other AI dev tools reliably and with a trusted IP** from any network.
> Run it by hand, or drive it with any AI coding agent.

**singbox-proxy-skill** is an open-source [Claude Code](https://claude.com/claude-code)
agent skill (portable to Cursor / Cline / Aider / Codex …). Hand it a fresh Ubuntu
VPS and it:

- installs **sing-box** (classic Shadowsocks `aes-256-gcm`, one account = one port = one password);
- runs a **single-file web panel**: live server monitoring (CPU/mem/disk/net/service health),
  account CRUD + rotate, one-click config export;
- hardens the box (**key-only SSH, UFW, fail2ban, auto-updates**);
- optionally **chains an upstream SOCKS5/HTTP proxy** (residential exit) and
  optionally **binds a domain** (migrate servers with a one-line DNS change);
- exports **Clash / `ss://`** configs for desktop and phone.

## The admin panel

After login: **live server monitoring** (CPU / memory / disk / network / service
health / egress IP), reached over an SSH tunnel, never exposed publicly:

![Dashboard](assets/dashboard.png)

**Account management** — one account = one port = one password; create / disable /
enable / rotate / delete:

![Accounts](assets/accounts.png)

**One-click config export per account** (`ss://` for phones + full Clash YAML for
desktops, with China/overseas split routing):

![Client config](assets/config.png)

> All values shown are sanitized samples (`vpn.example.com` / `203.0.113.7`).

## Why a *stable* IP — the Claude Code problem

Claude Code / Claude API, OpenAI, Cursor are sensitive to your egress IP:

- **datacenter / cloud IPs** get rate-limited, challenged, or blocked;
- **shared VPN IPs** rotate and get flagged — constant CAPTCHAs and re-logins;
- a **static residential / ISP IP** looks like a normal home user: stable, trusted,
  no rotation — your Claude Code stays logged in and unthrottled.

Best setup: a nearby **clean-IP VPS** as the entry + a **static residential
upstream** as the exit. Only bypassing a network block and don't care about IP
reputation? Skip the upstream and exit straight from the VPS. See
[`references/providers.md`](references/providers.md).

## Quick start

> You **don't need a working AI tool yet** (you're setting one up *because* your
> environment is flaky). The three commands below run **by hand**, or you can
> drive the skill with **any** coding agent / AI IDE you already have.

**Option A — run it by hand** (no AI tool needed): the three commands below.

**Option B — let an agent / AI IDE do it**: hand this repo to whatever you use —
Claude Code, [Codex](https://openai.com/codex/), Cursor, Cline, Aider, or Chinese
IDEs like **Tongyi Lingma / CodeGeeX / Comate / MarsCode / Trae** — point it at
[`SKILL.md`](SKILL.md) and give it your VPS `user@host` + key. (On Claude Code:
`/singbox-proxy`.)

**By hand:**

```bash
# 1. deploy (SERVER_HOST = domain/IP clients connect to; UPSTREAM_URL optional)
SERVER_HOST=vpn.example.com FIRST_ACCOUNT=my-laptop FIRST_PORT=443 \
UPSTREAM_URL=socks5://user:pass@1.2.3.4:1080 \
./scripts/deploy.sh -i ~/.ssh/id_ed25519 root@203.0.113.10

# 2. harden
ssh -i ~/.ssh/id_ed25519 root@203.0.113.10 \
  'cd /tmp/proxy-admin-panel && sudo SS_PORTS="443 80 8443" TIMEZONE=Asia/Seoul bash scripts/harden.sh'

# 3. tunnel to the panel (local-only, never public)
ssh -i ~/.ssh/id_ed25519 -L 17000:127.0.0.1:7000 root@203.0.113.10
# open http://127.0.0.1:17000
```

Migrating later is a single DNS A-record change — clients don't re-import.

## Ports & firewall (read this — don't get misled)

This uses **classic Shadowsocks**: **one account = one port = one password**.

- ✅ **Upside:** works in every client (incl. Hiddify); each device has its own
  password, so a lost device means rotating/disabling *just that one* account.
- ⚠️ **Cost:** **every port you use must be opened in BOTH firewall layers** —
  1. the machine's **UFW** — `harden.sh` sets the baseline, and the panel
     auto-runs `ufw allow` / `ufw delete` when you add / delete an account, so you
     don't manage this layer; and
  2. **your cloud provider's security group / firewall console** (Vultr, DO,
     Tencent, Aliyun… — you must open these **by hand**; no software can).
  - Forget layer 2 and you get *"some ports connect, others time out"* — e.g.
    80 works but 443 hangs → the cloud console hasn't opened 443.
- ➕ **A new account on a new port**: the panel opens UFW for you — you only need
  to open that port in your cloud console (the panel reminds you after creation).
- 🧩 **Don't want a port per account?** Put everyone on **one shared port + one
  password** (e.g. all on 443): set `FIRST_PORT` once and hand out the same
  config. Never open another port — at the cost of no per-device isolation
  (lose one device → everyone rotates).

> In short: **however many ports you use, open that many in each of the two
> layers (UFW + cloud security group).** This skill does **not** use SS2022
> single-port multi-user (Hiddify can't parse it; censorship-resistance unproven).

## Hard-won rules (the heart of this project)

1. **Classic Shadowsocks, not SS2022** — SS2022 multi-user keys break Hiddify.
2. **Times out but the port is reachable = dirty IP, not config** — get a clean IP.
3. **Never expose the panel publicly** — SSH tunnel, or a single-source-IP firewall rule.
4. **Point clients at a domain (DNS-only)** — migrate with one DNS change.
5. **Secrets stay on the server** — never committed.

See [`references/`](references) for troubleshooting, security, clients, providers.

## Layout

```text
SKILL.md            full deploy/ops workflow (agent entry point)
app.py              single-file web admin panel (stdlib only)
scripts/            install.sh · harden.sh · deploy.sh
references/         providers · troubleshooting · security · clients
examples/           config.example.json
```

## Safety & compliance

Self-hosted, for you and people you trust. Follow your local laws and your
VPS/proxy providers' terms. This project just configures a VPS you own as a
hardened Shadowsocks relay.

## License

[MIT](LICENSE)
