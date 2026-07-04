#!/usr/bin/env bash
# Harden a fresh Ubuntu/Debian VPS: SSH (key-only), UFW, fail2ban, auto-updates.
# Run as root ON the server, AFTER install.sh. Configure via env vars:
#
#   SS_PORTS       space-separated Shadowsocks ports to open (default: "443 80 8443")
#   TIMEZONE       e.g. Asia/Seoul (default: keep current)
#   ADMIN_SRC_IP   if set, opens panel port 7000 ONLY from this source IP
#                  (e.g. your static egress IP). Omit to keep 7000 local-only.
#
# Keeps SSH on port 22 AND adds 2222. Verify a NEW ssh session works before
# closing your current one. Never lock yourself out.
set -euo pipefail

SS_PORTS="${SS_PORTS:-443 80 8443}"
TIMEZONE="${TIMEZONE:-}"
ADMIN_SRC_IP="${ADMIN_SRC_IP:-}"

[[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 1; }

if [[ -n "${TIMEZONE}" ]]; then
  echo "==> timezone ${TIMEZONE}"
  timedatectl set-timezone "${TIMEZONE}"
fi

echo "==> auto security updates"
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true

echo "==> UFW (default deny incoming)"
ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp comment 'SSH' >/dev/null
ufw allow 2222/tcp comment 'SSH maintenance' >/dev/null
for p in ${SS_PORTS}; do ufw allow "${p}/tcp" comment 'Shadowsocks' >/dev/null; done
if [[ -n "${ADMIN_SRC_IP}" ]]; then
  ufw allow from "${ADMIN_SRC_IP}" to any port 7000 proto tcp comment 'admin panel (source-locked)' >/dev/null
  echo "    panel 7000 opened ONLY from ${ADMIN_SRC_IP}"
fi
ufw --force enable >/dev/null
ufw status | grep -E 'ALLOW' | grep -v '(v6)'

echo "==> fail2ban"
systemctl enable --now fail2ban >/dev/null 2>&1
systemctl is-active fail2ban

echo "==> SSH hardening (key-only, no root, ports 22 + 2222)"
mkdir -p /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/99-proxy-admin.conf <<'EOF'
Port 22
Port 2222
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
X11Forwarding no
EOF
# Ubuntu cloud images ship 50-cloud-init.conf with PasswordAuthentication yes,
# which wins because sshd honours the FIRST match. Neutralise it.
CI=/etc/ssh/sshd_config.d/50-cloud-init.conf
[[ -f "${CI}" ]] && sed -i 's/^\s*PasswordAuthentication.*/PasswordAuthentication no/I' "${CI}"

if sshd -t; then
  systemctl disable --now ssh.socket 2>/dev/null || true
  systemctl restart ssh.service
  echo "    effective:"
  sshd -T | grep -iE '^(permitrootlogin|passwordauthentication|pubkeyauthentication)' | sed 's/^/      /'
else
  echo "!! sshd config invalid, rolled back, NOT restarting" >&2
  rm -f /etc/ssh/sshd_config.d/99-proxy-admin.conf
  exit 1
fi

echo
echo "Hardening done. From a NEW terminal, confirm you can still ssh in"
echo "BEFORE closing this session. Also open the same ports in your cloud"
echo "provider's firewall / security group (UFW is only the inner layer)."
