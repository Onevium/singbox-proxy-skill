#!/usr/bin/env bash
# Push this repo to a server and run install.sh there.
# Usage:
#   SERVER_HOST=vpn.example.com \
#   ./scripts/deploy.sh <user>@<host> [ssh args...]
#
# All install.sh env vars (SERVER_HOST, UPSTREAM_URL, FIRST_ACCOUNT, ...) are
# forwarded. Example:
#   SERVER_HOST=vpn.example.com UPSTREAM_URL=socks5://u:p@1.2.3.4:1080 \
#   ./scripts/deploy.sh -i ~/.ssh/id_ed25519 root@203.0.113.10
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -ge 1 ]] || { echo "usage: SERVER_HOST=... ./scripts/deploy.sh [ssh args] <user>@<host>" >&2; exit 1; }

TARGET="${@: -1}"
SSH_ARGS=("${@:1:$#-1}")
ARCHIVE="/tmp/proxy-admin-panel.tar.gz"
REMOTE_DIR="/tmp/proxy-admin-panel"

tar -C "${ROOT_DIR}" --exclude ".git" --exclude "references" -czf "${ARCHIVE}" app.py scripts

# Forward the install/harden env vars.
FORWARD=""
for v in SERVER_HOST FIRST_ACCOUNT FIRST_PORT NODE_PREFIX UPSTREAM_URL PANEL_APP_NAME SS_PORTS TIMEZONE ADMIN_SRC_IP; do
  [[ -n "${!v:-}" ]] && FORWARD+="${v}=$(printf %q "${!v}") "
done

ssh "${SSH_ARGS[@]}" "${TARGET}" "rm -rf '${REMOTE_DIR}' && mkdir -p '${REMOTE_DIR}'"
scp "${SSH_ARGS[@]}" "${ARCHIVE}" "${TARGET}:${ARCHIVE}"
ssh "${SSH_ARGS[@]}" "${TARGET}" "tar -xzf '${ARCHIVE}' -C '${REMOTE_DIR}' && cd '${REMOTE_DIR}' && chmod +x scripts/*.sh && sudo ${FORWARD}bash scripts/install.sh"

echo
echo "Installed. Next: harden + open your cloud firewall ports."
echo "  ssh ${SSH_ARGS[*]} ${TARGET} 'cd ${REMOTE_DIR} && sudo ${FORWARD}bash scripts/harden.sh'"
echo "  Tunnel to the panel: ssh ${SSH_ARGS[*]} -L 17000:127.0.0.1:7000 ${TARGET}"
