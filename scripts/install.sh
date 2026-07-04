#!/usr/bin/env bash
# Install sing-box + the admin panel on a fresh Ubuntu/Debian VPS.
# Run as root ON the server. Configure via env vars:
#
#   SERVER_HOST     required. Domain or IP clients connect to (e.g. vpn.example.com)
#   FIRST_ACCOUNT   first account name (default: my-laptop)
#   FIRST_PORT      first account port  (default: 443)
#   NODE_PREFIX     node label prefix in exported configs (default: Node)
#   UPSTREAM_URL    optional upstream proxy, e.g. socks5://user:pass@1.2.3.4:1080
#                   (omit for a direct exit from this VPS)
#   PANEL_APP_NAME  admin panel title (default: Proxy Admin)
#
# Idempotent-ish: keeps existing accounts/admin password if already installed.
set -euo pipefail

APP_SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="/opt/proxy-admin"
CONFIG_DIR="/etc/proxy-admin"
SING_BOX_CONFIG="/etc/sing-box/config.json"

SERVER_HOST="${SERVER_HOST:?set SERVER_HOST (domain or IP clients connect to)}"
FIRST_ACCOUNT="${FIRST_ACCOUNT:-my-laptop}"
FIRST_PORT="${FIRST_PORT:-443}"
NODE_PREFIX="${NODE_PREFIX:-Node}"
UPSTREAM_URL="${UPSTREAM_URL:-}"
PANEL_APP_NAME="${PANEL_APP_NAME:-Proxy Admin}"

[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }

echo "==> base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl jq ufw fail2ban unattended-upgrades python3 >/dev/null

echo "==> sing-box"
if ! command -v sing-box >/dev/null; then
  bash -c 'curl -fsSL https://sing-box.app/deb-install.sh | bash'
fi
sing-box version | head -1

install -d -m 0755 "${APP_DIR}"
install -d -m 0700 "${CONFIG_DIR}" "${CONFIG_DIR}/backups"
install -d -m 0700 /etc/sing-box
install -m 0755 "${APP_SRC_DIR}/app.py" "${APP_DIR}/app.py"

echo "==> panel config + first account + sing-box config"
SERVER_HOST="${SERVER_HOST}" FIRST_ACCOUNT="${FIRST_ACCOUNT}" FIRST_PORT="${FIRST_PORT}" \
NODE_PREFIX="${NODE_PREFIX}" UPSTREAM_URL="${UPSTREAM_URL}" python3 - <<'PY'
import base64, hashlib, json, os, secrets, urllib.parse
from pathlib import Path

CFG = Path("/etc/proxy-admin")
SB = Path("/etc/sing-box/config.json")

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)

def parse_upstream(url):
    if not url:
        return None
    p = urllib.parse.urlparse(url)
    typ = "http" if p.scheme in ("http", "https") else "socks"
    up = {"type": typ, "server": p.hostname, "server_port": p.port}
    if p.username:
        up["username"] = urllib.parse.unquote(p.username)
    if p.password:
        up["password"] = urllib.parse.unquote(p.password)
    return up

upstream = parse_upstream(os.environ.get("UPSTREAM_URL", "").strip())

# panel config.json (keep existing, patch fields)
cfg = json.loads((CFG / "config.json").read_text()) if (CFG / "config.json").exists() else {}
cfg["server_host"] = os.environ["SERVER_HOST"]
cfg["node_prefix"] = os.environ["NODE_PREFIX"]
if upstream:
    cfg["upstream"] = upstream
write(CFG / "config.json", cfg)

# first account (only if no clients yet)
if not (CFG / "clients.json").exists():
    pw = base64.b64encode(secrets.token_bytes(16)).decode()
    write(CFG / "clients.json", [{
        "name": os.environ["FIRST_ACCOUNT"], "port": int(os.environ["FIRST_PORT"]),
        "password": pw, "enabled": True, "created_at": "install", "updated_at": "install",
    }])

# admin password (only if no admin yet)
if not (CFG / "admin.json").exists():
    admin_pw = base64.urlsafe_b64encode(secrets.token_bytes(18)).decode().rstrip("=")
    salt = secrets.token_bytes(16)
    dig = hashlib.pbkdf2_hmac("sha256", admin_pw.encode(), salt, 240000)
    enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    write(CFG / "admin.json", {
        "password_hash": f"pbkdf2_sha256$240000${enc(salt)}${enc(dig)}",
        "session_secret": enc(secrets.token_bytes(32)),
    })
    (CFG / "initial-admin-password.txt").write_text(admin_pw + "\n")
    os.chmod(CFG / "initial-admin-password.txt", 0o600)

# render sing-box config from clients + upstream (same logic as app.py)
clients = json.loads((CFG / "clients.json").read_text())
inbounds = [{
    "type": "shadowsocks", "tag": f"ss-{c['name']}-{c['port']}", "listen": "0.0.0.0",
    "listen_port": int(c["port"]), "method": "aes-256-gcm", "password": c["password"], "network": "tcp",
} for c in clients if c.get("enabled", True)]
if upstream:
    eg = {"type": upstream["type"], "tag": "egress", "server": upstream["server"], "server_port": int(upstream["server_port"])}
    if upstream.get("username"): eg["username"] = upstream["username"]
    if upstream.get("password"): eg["password"] = upstream["password"]
    outbounds = [eg, {"type": "direct", "tag": "direct"}, {"type": "block", "tag": "block"}]
else:
    outbounds = [{"type": "direct", "tag": "egress"}, {"type": "block", "tag": "block"}]
sb = {"log": {"level": "info", "timestamp": True}, "inbounds": inbounds,
      "outbounds": outbounds, "route": {"auto_detect_interface": True, "final": "egress"}}
write(SB, sb)
print("egress:", "upstream " + upstream["server"] if upstream else "direct (this VPS)")
PY

echo "==> sing-box check + start"
sing-box check -c "${SING_BOX_CONFIG}"
systemctl enable --now sing-box
systemctl restart sing-box

echo "==> panel systemd service"
cat >/etc/systemd/system/proxy-admin.service <<EOF
[Unit]
Description=Proxy Admin Panel
After=network-online.target sing-box.service
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=PANEL_HOST=127.0.0.1
Environment=PANEL_PORT=7000
Environment=PANEL_CONFIG_DIR=/etc/proxy-admin
Environment=SING_BOX_CONFIG=/etc/sing-box/config.json
Environment=PANEL_APP_NAME=${PANEL_APP_NAME}
ExecStart=/usr/bin/python3 /opt/proxy-admin/app.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/etc/proxy-admin /etc/sing-box

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now proxy-admin.service
sleep 1
systemctl --no-pager --full status proxy-admin.service | head -6

echo
echo "===================================================================="
echo "  Done. sing-box listening on port ${FIRST_PORT} (account ${FIRST_ACCOUNT})."
if [[ -f "${CONFIG_DIR}/initial-admin-password.txt" ]]; then
  echo "  Admin password: $(cat "${CONFIG_DIR}/initial-admin-password.txt")"
fi
echo "  Open the panel over an SSH tunnel (never expose 7000 publicly):"
echo "    ssh -L 17000:127.0.0.1:7000 <user>@${SERVER_HOST}"
echo "    open http://127.0.0.1:17000"
echo "  Now run scripts/harden.sh to lock down SSH + firewall."
echo "===================================================================="
