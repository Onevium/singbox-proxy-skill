#!/usr/bin/env python3
"""Self-hosted Shadowsocks admin panel (single-file, stdlib-only).

Manages classic Shadowsocks (aes-256-gcm) accounts on a sing-box server:
one account = one port = one password. Optionally chains all traffic through
an upstream SOCKS5/HTTP proxy (e.g. a residential exit). Serves a small web
UI with live server monitoring, account CRUD, and one-click client exports.

Binds to 127.0.0.1 by default — reach it over an SSH tunnel. Never expose it
to the public internet without a firewall source-IP allowlist.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import http.cookies
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

APP_NAME = os.environ.get("PANEL_APP_NAME", "Proxy Admin")
CONFIG_DIR = Path(os.environ.get("PANEL_CONFIG_DIR", "/etc/proxy-admin"))
SING_BOX_CONFIG = Path(os.environ.get("SING_BOX_CONFIG", "/etc/sing-box/config.json"))
HOST = os.environ.get("PANEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("PANEL_PORT", "7000"))
SESSION_TTL = 8 * 60 * 60
PBKDF2_ROUNDS = 240_000
COOKIE_NAME = "panel_session"
SS_METHOD = "aes-256-gcm"
DEFAULT_HOST = "example.com"


# --------------------------------------------------------------------------- io
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    for path in [CONFIG_DIR, CONFIG_DIR / "backups"]:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_config() -> dict[str, Any]:
    return read_json(CONFIG_DIR / "config.json", {})


def load_admin() -> dict[str, Any]:
    return read_json(CONFIG_DIR / "admin.json", {})


def load_clients() -> list[dict[str, Any]]:
    clients = read_json(CONFIG_DIR / "clients.json", [])
    return sorted(clients, key=lambda c: (int(c.get("port", 0)), c.get("name", "")))


def save_clients(clients: list[dict[str, Any]]) -> None:
    write_json(CONFIG_DIR / "clients.json", clients)


def audit(action: str, detail: str, actor: str = "admin") -> None:
    line = json.dumps({"time": now_iso(), "actor": actor, "action": action, "detail": detail}, ensure_ascii=False)
    with (CONFIG_DIR / "audit.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    os.chmod(CONFIG_DIR / "audit.log", 0o600)


def server_host() -> str:
    return str(load_config().get("server_host", DEFAULT_HOST)).strip() or DEFAULT_HOST


def node_prefix() -> str:
    return str(load_config().get("node_prefix", "Node")).strip() or "Node"


def server_ip() -> str:
    """The raw IP clients dial when the domain can't be resolved (e.g. desktop
    Clash under TUN). Uses config `server_ip` if set, else resolves server_host."""
    ip = str(load_config().get("server_ip", "")).strip()
    if ip:
        return ip
    try:
        import socket
        return socket.gethostbyname(server_host())
    except Exception:
        return server_host()


def effective_host(use_ip: bool = False) -> str:
    return server_ip() if use_ip else server_host()


# --------------------------------------------------------------------- auth/session
def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ROUNDS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds_s, salt_s, digest_s = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_s + "=" * (-len(salt_s) % 4))
        expected = base64.urlsafe_b64decode(digest_s + "=" * (-len(digest_s) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds_s))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign(value: str) -> str:
    secret = load_admin().get("session_secret", "")
    return b64(hmac.new(secret.encode(), value.encode(), hashlib.sha256).digest())


def make_session() -> str:
    payload = {"iat": int(time.time()), "nonce": b64(secrets.token_bytes(18))}
    raw = b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{raw}.{sign(raw)}"


def verify_session(token: str) -> bool:
    try:
        raw, mac = token.split(".", 1)
        if not hmac.compare_digest(mac, sign(raw)):
            return False
        payload = json.loads(unb64(raw))
        return int(time.time()) - int(payload["iat"]) <= SESSION_TTL
    except Exception:
        return False


# ------------------------------------------------------------------- accounts model
def random_password() -> str:
    return base64.b64encode(secrets.token_bytes(16)).decode()


def used_ports(clients: list[dict[str, Any]]) -> set[int]:
    return {int(c["port"]) for c in clients}


def next_port(clients: list[dict[str, Any]]) -> int:
    used = used_ports(clients)
    preferred = load_config().get("preferred_ports", [443, 80, 8443, 8080, 2053, 2083, 2087, 2096])
    for port in preferred:
        if int(port) not in used:
            return int(port)
    for port in range(9000, 10000):
        if port not in used:
            return port
    raise RuntimeError("no available ports")


def slugify_name(name: str) -> str:
    value = "".join(ch.lower() if ch.isalnum() else "-" for ch in name.strip())
    while "--" in value:
        value = value.replace("--", "-")
    value = value.strip("-")
    if not value:
        raise ValueError("name is required")
    return value[:48]


# ---------------------------------------------------------------- sing-box config
def _outbounds() -> list[dict[str, Any]]:
    """Egress outbounds. If an upstream proxy is configured, route through it;
    otherwise exit directly from the server."""
    up = load_config().get("upstream") or {}
    if up.get("server") and up.get("server_port"):
        proxy = {
            "type": up.get("type", "socks"),
            "tag": "egress",
            "server": up["server"],
            "server_port": int(up["server_port"]),
        }
        if up.get("username"):
            proxy["username"] = up["username"]
        if up.get("password"):
            proxy["password"] = up["password"]
        return [proxy, {"type": "direct", "tag": "direct"}, {"type": "block", "tag": "block"}]
    return [{"type": "direct", "tag": "egress"}, {"type": "block", "tag": "block"}]


def render_sing_box_config(clients: list[dict[str, Any]]) -> dict[str, Any]:
    inbounds: list[dict[str, Any]] = []
    for c in clients:
        if not c.get("enabled", True):
            continue
        inbounds.append(
            {
                "type": "shadowsocks",
                "tag": f"ss-{c['name']}-{c['port']}",
                "listen": "0.0.0.0",
                "listen_port": int(c["port"]),
                "method": SS_METHOD,
                "password": c["password"],
                "network": "tcp",
            }
        )
    return {
        "log": {"disabled": False, "level": "info", "timestamp": True},
        "inbounds": inbounds,
        "outbounds": _outbounds(),
        "route": {"auto_detect_interface": True, "final": "egress"},
    }


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


def apply_sing_box(clients: list[dict[str, Any]]) -> tuple[bool, str]:
    new_config = render_sing_box_config(clients)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
        json.dump(new_config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        tmp_path = Path(fh.name)
    try:
        check = run(["sing-box", "check", "-c", str(tmp_path)])
        if check.returncode != 0:
            return False, (check.stderr or check.stdout or "sing-box check failed")
        backup = CONFIG_DIR / "backups" / f"sing-box-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        if SING_BOX_CONFIG.exists():
            shutil.copy2(SING_BOX_CONFIG, backup)
            os.chmod(backup, 0o600)
        shutil.copy2(tmp_path, SING_BOX_CONFIG)
        os.chmod(SING_BOX_CONFIG, 0o600)
        restart = run(["systemctl", "restart", "sing-box"], timeout=30)
        if restart.returncode != 0:
            return False, restart.stderr or restart.stdout or "systemctl restart failed"
        return True, "applied"
    finally:
        tmp_path.unlink(missing_ok=True)


def ufw_allow(port: int) -> None:
    """Open a Shadowsocks port in UFW (best-effort; the cloud provider's firewall
    still has to be opened by hand — no software can do that for you)."""
    run(["ufw", "allow", f"{int(port)}/tcp", "comment", "Shadowsocks (panel)"], timeout=10)


def ufw_delete(port: int) -> None:
    run(["ufw", "delete", "allow", f"{int(port)}/tcp"], timeout=10)


# --------------------------------------------------------------------- monitoring
def _read_proc(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def fmt_bytes(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def system_metrics() -> dict[str, Any]:
    m: dict[str, Any] = {}
    try:
        up = float(_read_proc("/proc/uptime").split()[0])
        d, rem = divmod(int(up), 86400)
        h, rem = divmod(rem, 3600)
        m["uptime"] = (f"{d}d " if d else "") + f"{h}h {rem // 60}m"
    except Exception:
        m["uptime"] = "n/a"
    try:
        m["load"] = " ".join(_read_proc("/proc/loadavg").split()[:3])
    except Exception:
        try:
            m["load"] = " ".join(f"{x:.2f}" for x in os.getloadavg())
        except Exception:
            m["load"] = "n/a"
    m["cpus"] = os.cpu_count() or 1

    def _cpu() -> tuple[int, int]:
        p = _read_proc("/proc/stat").splitlines()[0].split()[1:8]
        v = [int(x) for x in p]
        return sum(v), v[3] + v[4]

    try:
        t1, i1 = _cpu()
        time.sleep(0.2)
        t2, i2 = _cpu()
        dt_ = t2 - t1
        m["cpu_pct"] = max(0, min(100, round((1 - (i2 - i1) / dt_) * 100))) if dt_ > 0 else 0
    except Exception:
        m["cpu_pct"] = None
    try:
        info: dict[str, int] = {}
        for line in _read_proc("/proc/meminfo").splitlines():
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])
        total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
        m["mem_pct"] = round((total - avail) / total * 100)
        m["mem_used"] = fmt_bytes((total - avail) * 1024)
        m["mem_total"] = fmt_bytes(total * 1024)
    except Exception:
        m["mem_pct"] = None
    try:
        du = shutil.disk_usage("/")
        m["disk_pct"] = round(du.used / du.total * 100)
        m["disk_used"] = fmt_bytes(du.used)
        m["disk_total"] = fmt_bytes(du.total)
    except Exception:
        m["disk_pct"] = None

    def _net() -> tuple[int, int]:
        rx = tx = 0
        for line in _read_proc("/proc/net/dev").splitlines():
            if ":" not in line:
                continue
            iface, _, rest = line.partition(":")
            if iface.strip() == "lo":
                continue
            f = rest.split()
            rx += int(f[0])
            tx += int(f[8])
        return rx, tx

    try:
        r1, x1 = _net()
        time.sleep(0.2)
        r2, x2 = _net()
        m["net_rx_rate"] = fmt_bytes((r2 - r1) / 0.2) + "/s"
        m["net_tx_rate"] = fmt_bytes((x2 - x1) / 0.2) + "/s"
        m["net_rx_total"] = fmt_bytes(r2)
        m["net_tx_total"] = fmt_bytes(x2)
    except Exception:
        m["net_rx_rate"] = m["net_tx_rate"] = m["net_rx_total"] = m["net_tx_total"] = "n/a"
    return m


def _egress_curl_args() -> list[str]:
    up = load_config().get("upstream") or {}
    if up.get("server") and up.get("server_port"):
        scheme = "socks5h" if up.get("type", "socks") == "socks" else "http"
        auth = f"{up['username']}:{up['password']}@" if up.get("username") else ""
        return ["-x", f"{scheme}://{auth}{up['server']}:{up['server_port']}"]
    return []


def shell_status() -> dict[str, str]:
    result: dict[str, str] = {}
    for service in ["sing-box", "ufw", "fail2ban", "ssh"]:
        proc = run(["systemctl", "is-active", service], timeout=5)
        result[service] = (proc.stdout or proc.stderr).strip()
    proc = run(["timedatectl"], timeout=5)
    result["timezone"] = "unknown"
    for line in proc.stdout.splitlines():
        if "Time zone:" in line:
            result["timezone"] = line.split("Time zone:", 1)[1].strip()
    proc = run(["fail2ban-client", "status", "sshd"], timeout=5)
    result["banned"] = "0"
    for line in proc.stdout.splitlines():
        if "Currently banned:" in line:
            result["banned"] = line.split(":", 1)[1].strip()
    try:
        proc = run(["curl", "-4", "--connect-timeout", "8", "--max-time", "12", "-sS", *_egress_curl_args(), "https://ipinfo.io/ip"], timeout=15)
        result["egress_ip"] = proc.stdout.strip() if proc.returncode == 0 else "failed"
    except Exception:
        result["egress_ip"] = "failed"
    return result


def speed_test() -> str:
    try:
        proc = run(["curl", "-4", "-s", "-o", "/dev/null", "-w", "%{speed_download}", "--max-time", "30", *_egress_curl_args(), "https://speed.cloudflare.com/__down?bytes=15000000"], timeout=35)
        speed = float((proc.stdout or "0").strip() or 0)
        if speed <= 0:
            return "speed test failed"
        return f"{speed * 8 / 1e6:.1f} Mbps ({fmt_bytes(speed)}/s)"
    except Exception as exc:
        return f"speed test failed: {exc}"


# ------------------------------------------------------------------- client export
def node_name(client: dict[str, Any]) -> str:
    return f"{node_prefix()}-{client['name']}-{client['port']}"


def clash_node(client: dict[str, Any], host: str | None = None) -> str:
    host = host or server_host()
    return "\n".join(
        [
            f"  - name: {node_name(client)}",
            "    type: ss",
            f"    server: {host}",
            f"    port: {int(client['port'])}",
            f"    cipher: {SS_METHOD}",
            f'    password: "{client["password"]}"',
            "    udp: true",
        ]
    )


def ss_uri(client: dict[str, Any], host: str | None = None) -> str:
    host = host or server_host()
    userinfo = base64.urlsafe_b64encode(f"{SS_METHOD}:{client['password']}".encode()).decode().rstrip("=")
    label = urllib.parse.quote(node_name(client))
    return f"ss://{userinfo}@{host}:{int(client['port'])}#{label}"


def server_direct_rule(host: str | None = None) -> str:
    host = host or server_host()
    try:
        ipaddress.ip_address(host)
        return f"  - IP-CIDR,{host}/32,DIRECT,no-resolve"
    except ValueError:
        return f"  - DOMAIN,{host},DIRECT"


# Explicit China-direct rules — work without a geosite/geoip database (which the
# client may not have downloaded yet), so domestic sites stay direct from the
# first connect. GEOSITE,cn / GEOIP,CN below still catch everything else.
CN_DIRECT_RULES = """  - DOMAIN-SUFFIX,cn,DIRECT
  - DOMAIN-SUFFIX,baidu.com,DIRECT
  - DOMAIN-SUFFIX,bdstatic.com,DIRECT
  - DOMAIN-SUFFIX,qq.com,DIRECT
  - DOMAIN-SUFFIX,wechat.com,DIRECT
  - DOMAIN-SUFFIX,weixin.qq.com,DIRECT
  - DOMAIN-SUFFIX,tencent.com,DIRECT
  - DOMAIN-SUFFIX,tencent-cloud.com,DIRECT
  - DOMAIN-SUFFIX,qcloud.com,DIRECT
  - DOMAIN-SUFFIX,dingtalk.com,DIRECT
  - DOMAIN-SUFFIX,aliyun.com,DIRECT
  - DOMAIN-SUFFIX,alicdn.com,DIRECT
  - DOMAIN-SUFFIX,alibaba.com,DIRECT
  - DOMAIN-SUFFIX,taobao.com,DIRECT
  - DOMAIN-SUFFIX,tmall.com,DIRECT
  - DOMAIN-SUFFIX,alipay.com,DIRECT
  - DOMAIN-SUFFIX,jd.com,DIRECT
  - DOMAIN-SUFFIX,360buyimg.com,DIRECT
  - DOMAIN-SUFFIX,douyin.com,DIRECT
  - DOMAIN-SUFFIX,byteimg.com,DIRECT
  - DOMAIN-SUFFIX,bytedance.com,DIRECT
  - DOMAIN-SUFFIX,feishu.cn,DIRECT
  - DOMAIN-SUFFIX,larksuite.com,DIRECT
  - DOMAIN-SUFFIX,wps.cn,DIRECT
  - DOMAIN-SUFFIX,kdocs.cn,DIRECT
  - DOMAIN-SUFFIX,kingsoft.com,DIRECT
  - DOMAIN-SUFFIX,bilibili.com,DIRECT
  - DOMAIN-SUFFIX,biliapi.com,DIRECT
  - DOMAIN-SUFFIX,hdslb.com,DIRECT
  - DOMAIN-SUFFIX,iqiyi.com,DIRECT
  - DOMAIN-SUFFIX,iqiyipic.com,DIRECT
  - DOMAIN-SUFFIX,youku.com,DIRECT
  - DOMAIN-SUFFIX,zhihu.com,DIRECT
  - DOMAIN-SUFFIX,zhimg.com,DIRECT
  - DOMAIN-SUFFIX,xiaohongshu.com,DIRECT
  - DOMAIN-SUFFIX,xhscdn.com,DIRECT
  - DOMAIN-SUFFIX,weibo.com,DIRECT
  - DOMAIN-SUFFIX,weibocdn.com,DIRECT
  - DOMAIN-SUFFIX,netease.com,DIRECT
  - DOMAIN-SUFFIX,163.com,DIRECT
  - DOMAIN-SUFFIX,126.net,DIRECT
  - DOMAIN-SUFFIX,music.163.com,DIRECT
  - DOMAIN-SUFFIX,douban.com,DIRECT
  - DOMAIN-SUFFIX,csdn.net,DIRECT
  - DOMAIN-SUFFIX,cnblogs.com,DIRECT
  - DOMAIN-SUFFIX,juejin.cn,DIRECT
  - DOMAIN-SUFFIX,gitee.com,DIRECT
  - DOMAIN-SUFFIX,oschina.net,DIRECT
  - DOMAIN-SUFFIX,huawei.com,DIRECT
  - DOMAIN-SUFFIX,huaweicloud.com,DIRECT
  - DOMAIN-SUFFIX,volcengine.com,DIRECT
  - DOMAIN-SUFFIX,mi.com,DIRECT
  - DOMAIN-SUFFIX,xiaomi.com,DIRECT
  - DOMAIN-SUFFIX,meituan.com,DIRECT
  - DOMAIN-SUFFIX,dianping.com,DIRECT
  - DOMAIN-SUFFIX,amap.com,DIRECT
  - DOMAIN-SUFFIX,autonavi.com,DIRECT
  - DOMAIN-SUFFIX,12306.cn,DIRECT
  - DOMAIN-SUFFIX,gov.cn,DIRECT
  - DOMAIN-SUFFIX,edu.cn,DIRECT
  - DOMAIN-SUFFIX,jd.com,DIRECT
  - DOMAIN-SUFFIX,pinduoduo.com,DIRECT
  - DOMAIN-SUFFIX,yuque.com,DIRECT
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,169.254.0.0/16,DIRECT,no-resolve"""


def mihomo_full_config(client: dict[str, Any], host: str | None = None) -> str:
    node = node_name(client)
    host = host or server_host()
    return f"""mixed-port: 7890
allow-lan: false
mode: rule
log-level: info
ipv6: false
tun:
  enable: true
  stack: mixed
  auto-route: true
  auto-detect-interface: true
  dns-hijack: [any:53]
dns:
  enable: true
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  fake-ip-filter: ["+.{host}", "*.lan", "*.local"]
  default-nameserver: [223.5.5.5, 119.29.29.29, 114.114.114.114]
  nameserver: [223.5.5.5, 119.29.29.29, "https://doh.pub/dns-query"]
  fallback: ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"]
proxies:
{clash_node(client, host)}
proxy-groups:
  - name: Proxy
    type: select
    proxies: [{node}, DIRECT]
rules:
{CN_DIRECT_RULES}
{server_direct_rule(host)}
  - GEOSITE,private,DIRECT
  - GEOSITE,cn,DIRECT
  - GEOIP,CN,DIRECT
  - MATCH,Proxy
"""


# ---------------------------------------------------------------------------- ui
PAGE_CSS = """
:root{color-scheme:light;--bg:#f4f5f7;--panel:#fff;--line:#e7e9ee;--text:#14161c;--muted:#6b7280;--accent:#4f46e5;--accent-weak:#eef2ff;--green:#16a34a;--green-bg:#dcfce7;--red:#dc2626;--red-bg:#fee2e2;--radius:12px;--shadow:0 1px 2px rgba(16,24,40,.04),0 1px 3px rgba(16,24,40,.05)}
*{box-sizing:border-box}
body{margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
.topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:14px;height:60px;padding:0 22px;background:rgba(255,255,255,.82);backdrop-filter:saturate(180%) blur(12px);-webkit-backdrop-filter:saturate(180%) blur(12px);border-bottom:1px solid var(--line)}
.brand{font-size:15.5px;font-weight:700;letter-spacing:-.01em;display:flex;align-items:center;gap:9px}
.brand .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px var(--accent-weak)}
.topnav{display:flex;gap:2px;margin-left:6px}
.topnav a{color:var(--muted);padding:7px 12px;border-radius:8px;font-weight:500}
.topnav a:hover{background:var(--bg);color:var(--text)}
.topnav a.active{background:var(--accent-weak);color:var(--accent)}
.spacer{flex:1}
main{max-width:1060px;margin:0 auto;padding:26px 22px 64px}
h1{margin:0 0 3px;font-size:22px;letter-spacing:-.02em}
h2{margin:28px 0 12px;font-size:15px;font-weight:600}
.sub{color:var(--muted);margin-bottom:22px;font-size:13px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(4,minmax(0,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:15px 17px;box-shadow:var(--shadow)}
.metric{color:var(--muted);font-size:12px;font-weight:500}
.value{font-size:21px;font-weight:700;margin-top:6px;letter-spacing:-.02em;overflow-wrap:anywhere}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
.panel-head{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--line);font-weight:600}
.panel-body{padding:18px}
table{width:100%;border-collapse:collapse}
th,td{padding:12px 16px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{color:var(--muted);font-size:12px;font-weight:600;background:#fbfbfc;letter-spacing:.02em}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:#fafafb}
td.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
input,select{width:100%;height:38px;border:1px solid var(--line);border-radius:8px;padding:0 12px;background:#fff;color:var(--text);font:inherit}
input:focus,select:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-weak)}
label{display:block;color:var(--muted);font-size:12px;font-weight:500;margin-bottom:6px}
.row{display:grid;grid-template-columns:1.4fr .7fr .8fr auto;gap:12px;align-items:end}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:36px;padding:0 14px;border:1px solid var(--line);background:#fff;color:var(--text);border-radius:8px;cursor:pointer;font:inherit;font-weight:500;white-space:nowrap;transition:.12s}
.btn:hover{background:var(--bg)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn.primary:hover{background:#4338ca}
.btn.danger{color:var(--red)}
.btn.danger:hover{background:var(--red-bg);border-color:var(--red)}
.btn.sm{height:30px;padding:0 11px;font-size:13px}
.badge{display:inline-flex;align-items:center;height:24px;border-radius:999px;padding:0 10px;font-size:12px;font-weight:600}
.ok{background:var(--green-bg);color:var(--green)}
.off{background:var(--red-bg);color:var(--red)}
pre{margin:0;padding:14px;background:#0d1117;color:#c9d1d9;border-radius:10px;overflow:auto;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
.flash{padding:11px 14px;border:1px solid #bfdbfe;background:#eff6ff;color:#1e40af;border-radius:8px;margin-bottom:18px}
.login{max-width:380px;margin:15vh auto;background:#fff;border:1px solid var(--line);border-radius:16px;padding:30px;box-shadow:0 8px 30px rgba(16,24,40,.08)}
.login .brand{justify-content:center;margin-bottom:20px;font-size:17px}
.actions{display:flex;gap:6px;flex-wrap:wrap}
form.inline{display:inline}
.kv{display:grid;grid-template-columns:110px 1fr;gap:11px 16px;margin:0;align-items:center}
.kv dt{color:var(--muted);font-size:13px}
.kv dd{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere;display:flex;align-items:center;gap:8px}
.hint{color:var(--muted);margin:0 0 14px;font-size:13px}
.bar{height:8px;border-radius:999px;background:#eef0f4;overflow:hidden;margin-top:12px}
.bar>i{display:block;height:100%;border-radius:999px;background:var(--accent);transition:width .3s}
.bar.warn>i{background:#f59e0b}
.bar.crit>i{background:var(--red)}
.mini{color:var(--muted);font-size:12px;margin-top:3px}
.svc{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.codewrap{position:relative}
.codewrap .copy{position:absolute;top:9px;right:9px}
@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}.row{grid-template-columns:1fr}.topnav{display:none}}
"""

PAGE_JS = """
<script>
function bpCopy(b){var el=document.getElementById(b.dataset.t);if(!el)return;var s=(el.innerText||el.textContent||'').trim();function done(){var o=b.innerHTML;b.innerHTML='copied \\u2713';b.classList.add('primary');setTimeout(function(){b.innerHTML=o;b.classList.remove('primary')},1400)}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(s).then(done).catch(function(){})}else{var t=document.createElement('textarea');t.value=s;document.body.appendChild(t);t.select();try{document.execCommand('copy')}catch(e){}document.body.removeChild(t);done()}}
</script>
"""


def page(title: str, body: str) -> bytes:
    content = (
        "<!doctype html><html lang=\"en\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)} · {html.escape(APP_NAME)}</title>"
        f"<style>{PAGE_CSS}</style></head>"
        f"<body>{body}{PAGE_JS}</body></html>"
    )
    return content.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "ProxyAdmin/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        audit("http", fmt % args)

    def parse_cookies(self) -> http.cookies.SimpleCookie:
        cookie = http.cookies.SimpleCookie()
        raw = self.headers.get("Cookie")
        if raw:
            cookie.load(raw)
        return cookie

    def authenticated(self) -> bool:
        morsel = self.parse_cookies().get(COOKIE_NAME)
        return bool(morsel and verify_session(morsel.value))

    def redirect(self, path: str) -> None:
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def send_html(self, title: str, body: str, status: int = 200) -> None:
        data = page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_download(self, filename: str, content: str, content_type: str = "application/octet-stream") -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        return {k: v[-1] for k, v in urllib.parse.parse_qs(data).items()}

    def require_auth(self) -> bool:
        if self.authenticated():
            return True
        self.redirect("/login")
        return False

    def layout(self, title: str, content: str) -> str:
        current = urllib.parse.urlparse(self.path).path
        links = [("/", "Dashboard"), ("/clients", "Accounts"), ("/export", "Export"), ("/audit", "Audit")]
        nav = "".join(
            "<a href='{h}'{c}>{l}</a>".format(
                h=h, l=l,
                c=" class='active'" if (h == "/" and current == "/") or (h != "/" and current.startswith(h)) else "",
            )
            for h, l in links
        )
        return f"""<div class="topbar">
  <div class="brand"><span class="dot"></span>{html.escape(APP_NAME)}</div>
  <nav class="topnav">{nav}</nav>
  <div class="spacer"></div>
  <a class="btn sm" href="/logout">Logout</a>
</div>
<main>
  <h1>{html.escape(title)}</h1>
  <div class="sub">sing-box Shadowsocks · local-only admin (reach via SSH tunnel)</div>
  {content}
</main>"""

    # -- routing --
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/login":
            self.login_page()
        elif path == "/logout":
            self.send_response(303)
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/login")
            self.end_headers()
        elif not self.require_auth():
            return
        elif path == "/":
            self.dashboard()
        elif path == "/clients":
            self.clients_page()
        elif path == "/clients/config":
            self.client_config_page(urllib.parse.parse_qs(parsed.query).get("name", [""])[0])
        elif path == "/clients/download":
            q = urllib.parse.parse_qs(parsed.query)
            self.download_client(q.get("name", [""])[0], q.get("fmt", ["clash"])[0], q.get("host", ["domain"])[0])
        elif path == "/export":
            self.export_page()
        elif path == "/export/download":
            self.download_export()
        elif path == "/audit":
            self.audit_page()
        else:
            self.send_html("Not found", self.layout("Not found", "<p>Not found</p>"), 404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            self.login()
            return
        if not self.require_auth():
            return
        form = self.read_form()
        try:
            if path == "/clients/add":
                self.add_client(form)
            elif path == "/clients/toggle":
                self.toggle_client(form)
            elif path == "/clients/delete":
                self.delete_client(form)
            elif path == "/clients/rotate":
                self.rotate_client(form)
            elif path == "/clients/apply":
                self.apply_clients()
            elif path == "/ops/restart":
                self.ops_restart()
            elif path == "/ops/speedtest":
                self.ops_speedtest()
            else:
                self.send_html("Not found", self.layout("Not found", "<p>Not found</p>"), 404)
        except Exception as exc:
            self.send_html("Error", self.layout("Error", f"<div class='flash'>{html.escape(str(exc))}</div>"), 500)

    # -- auth pages --
    def login_page(self) -> None:
        self.send_html(
            "Login",
            f"""<div class="login">
  <div class="brand"><span class="dot"></span>{html.escape(APP_NAME)}</div>
  <form method="post" action="/login">
    <label>Admin password</label>
    <input type="password" name="password" autofocus required>
    <div style="height:16px"></div>
    <button class="btn primary" type="submit" style="width:100%">Log in</button>
  </form>
</div>""",
        )

    def login(self) -> None:
        form = self.read_form()
        if verify_password(form.get("password", ""), load_admin().get("password_hash", "")):
            token = make_session()
            self.send_response(303)
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}")
            self.send_header("Location", "/")
            self.end_headers()
            audit("login", "success")
        else:
            audit("login", "failed")
            time.sleep(1.2)
            self.send_html("Login", "<div class='login'><div class='flash'>Login failed</div><a href='/login'>Back</a></div>", 403)

    # -- dashboard --
    def dashboard(self, flash: str = "") -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        auto = query.get("auto", ["0"])[0] == "1"
        if not flash:
            flash = query.get("flash", [""])[0]
        status = shell_status()
        metrics = system_metrics()
        clients = load_clients()
        enabled = sum(1 for c in clients if c.get("enabled", True))

        def bar(pct: Any) -> str:
            if pct is None:
                return "<div class='mini'>n/a</div>"
            cls = "crit" if pct >= 90 else "warn" if pct >= 75 else ""
            return f"<div class='bar {cls}'><i style='width:{int(pct)}%'></i></div>"

        def res(title: str, big: str, pct: Any, sub: str) -> str:
            return f"<div class='card'><div class='metric'>{title}</div><div class='value'>{html.escape(big)}</div>{bar(pct)}<div class='mini'>{html.escape(sub)}</div></div>"

        egress_ok = status["egress_ip"] not in ("failed", "")
        kpi = "".join([
            f"<div class='card'><div class='metric'>sing-box</div><div class='value'><span class='badge {'ok' if status['sing-box']=='active' else 'off'}'>{html.escape(status['sing-box'])}</span></div><div class='mini'>uptime {html.escape(metrics.get('uptime','n/a'))}</div></div>",
            f"<div class='card'><div class='metric'>egress IP</div><div class='value' style='color:{'var(--green)' if egress_ok else 'var(--red)'}'>{html.escape(status['egress_ip'])}</div><div class='mini'>timezone {html.escape(status['timezone'])}</div></div>",
            f"<div class='card'><div class='metric'>accounts</div><div class='value'>{enabled} <span style='font-size:13px;color:var(--muted);font-weight:500'>/ {len(clients)}</span></div><div class='mini'>enabled / total</div></div>",
            f"<div class='card'><div class='metric'>load (1/5/15m)</div><div class='value' style='font-size:17px'>{html.escape(metrics.get('load','n/a'))}</div><div class='mini'>{metrics.get('cpus','?')} cores</div></div>",
        ])
        resources = "".join([
            res("CPU", f"{metrics['cpu_pct']}%" if metrics.get("cpu_pct") is not None else "n/a", metrics.get("cpu_pct"), f"{metrics.get('cpus','?')} cores"),
            res("Memory", f"{metrics['mem_pct']}%" if metrics.get("mem_pct") is not None else "n/a", metrics.get("mem_pct"), f"{metrics.get('mem_used','?')} / {metrics.get('mem_total','?')}"),
            res("Disk /", f"{metrics['disk_pct']}%" if metrics.get("disk_pct") is not None else "n/a", metrics.get("disk_pct"), f"{metrics.get('disk_used','?')} / {metrics.get('disk_total','?')}"),
            f"<div class='card'><div class='metric'>Network</div><div class='value' style='font-size:16px'>&#8595; {html.escape(metrics.get('net_rx_rate','n/a'))}<br>&#8593; {html.escape(metrics.get('net_tx_rate','n/a'))}</div><div class='mini'>total &#8595;{html.escape(metrics.get('net_rx_total','n/a'))} &#8593;{html.escape(metrics.get('net_tx_total','n/a'))}</div></div>",
        ])

        def svc(name: str, key: str) -> str:
            v = status.get(key, "?")
            return f"<span class='badge {'ok' if v=='active' else 'off'}'>{name} {html.escape(v)}</span>"
        svcs = " ".join([svc("sing-box", "sing-box"), svc("ufw", "ufw"), svc("fail2ban", "fail2ban"), svc("ssh", "ssh"),
                         f"<span class='badge {'off' if status['banned'] not in ('0','') else 'ok'}'>fail2ban banned {html.escape(status['banned'])}</span>"])

        flash_html = f"<div class='flash'>{html.escape(flash)}</div>" if flash else ""
        auto_btn = "<a class='btn sm primary' href='/'>auto-refresh: on</a>" if auto else "<a class='btn sm' href='/?auto=1'>auto-refresh</a>"
        actions = (
            "<div class='svc'>"
            "<form class='inline' method='post' action='/ops/restart' onsubmit='return confirm(\"Restart sing-box? Brief drop.\")'><button class='btn' type='submit'>Restart sing-box</button></form>"
            "<form class='inline' method='post' action='/ops/speedtest'><button class='btn' type='submit'>Speed test</button></form>"
            "<a class='btn' href='/clients'>Manage accounts</a><a class='btn' href='/export'>Export</a>"
            f"<a class='btn' href='/'>Refresh</a>{auto_btn}</div>"
        )
        body = (
            f"{flash_html}<div class='grid'>{kpi}</div>"
            f"<h2>System resources</h2><div class='grid'>{resources}</div>"
            f"<h2>Services &amp; security</h2><div class='panel'><div class='panel-body'><div class='svc'>{svcs}</div></div></div>"
            f"<h2>Actions</h2><div class='panel'><div class='panel-body'>{actions}</div></div>"
        )
        auto_js = "<script>setTimeout(function(){location.href='/?auto=1'},8000)</script>" if auto else ""
        self.send_html("Dashboard", self.layout("Dashboard", body) + auto_js)

    # -- accounts --
    def clients_page(self) -> None:
        flash = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("flash", [""])[0]
        clients = load_clients()
        rows = []
        for c in clients:
            state = "<span class='badge ok'>enabled</span>" if c.get("enabled", True) else "<span class='badge off'>disabled</span>"
            rows.append(
                f"<tr><td><b>{html.escape(c['name'])}</b></td><td class='mono'>{int(c['port'])}</td><td>{state}</td><td class='mono' style='color:var(--muted)'>{html.escape(c.get('created_at','')[:10])}</td><td class='actions'>"
                f"<a class='btn sm primary' href='/clients/config?name={urllib.parse.quote(c['name'])}'>Config</a>"
                f"<form class='inline' method='post' action='/clients/toggle'><input type='hidden' name='name' value='{html.escape(c['name'])}'><button class='btn sm' type='submit'>{'Disable' if c.get('enabled', True) else 'Enable'}</button></form>"
                f"<form class='inline' method='post' action='/clients/rotate'><input type='hidden' name='name' value='{html.escape(c['name'])}'><button class='btn sm' type='submit'>Rotate</button></form>"
                f"<form class='inline' method='post' action='/clients/delete' onsubmit='return confirm(\"Delete {html.escape(c['name'])}?\")'><input type='hidden' name='name' value='{html.escape(c['name'])}'><button class='btn sm danger' type='submit'>Delete</button></form>"
                "</td></tr>"
            )
        table = "<table><thead><tr><th>Account</th><th>Port</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>{}</tbody></table>".format("".join(rows))
        form = """<form method="post" action="/clients/add" class="row">
  <div><label>Account name (device/person)</label><input name="name" placeholder="alice-laptop" required></div>
  <div><label>Port (blank = auto)</label><input name="port" placeholder="auto"></div>
  <div><label>Status</label><select name="enabled"><option value="true">enabled</option><option value="false">disabled</option></select></div>
  <button class="btn primary" type="submit">+ Create</button>
</form>"""
        flash_html = f"<div class='flash'>{html.escape(flash)}</div>" if flash else ""
        body = f"{flash_html}<div class='panel'><div class='panel-head'><span>New account</span><span style='font-weight:400;color:var(--muted);font-size:12px'>one account = one port + one password · new port also needs opening in your cloud firewall</span></div><div class='panel-body'>{form}</div></div><h2>Accounts</h2><div class='panel'>{table}</div><div style='height:16px'></div><form method='post' action='/clients/apply'><button class='btn' type='submit'>Re-check &amp; apply sing-box config</button></form>"
        self.send_html("Accounts", self.layout("Accounts", body))

    def client_config_page(self, name: str) -> None:
        client = self.find_client(load_clients(), name)
        use_ip = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("host", ["domain"])[0] == "ip"
        eff = effective_host(use_ip)
        hp = "ip" if use_ip else "domain"
        node = clash_node(client, eff)
        full = mihomo_full_config(client, eff)
        uri = ss_uri(client, eff)
        q = urllib.parse.quote(client["name"])
        tabs = (
            f"<a class='btn sm {'primary' if not use_ip else ''}' href='/clients/config?name={q}&amp;host=domain'>Domain</a>"
            f"<a class='btn sm {'primary' if use_ip else ''}' href='/clients/config?name={q}&amp;host=ip'>IP</a>"
        )
        note = ("Raw IP — desktop Clash under TUN can't always resolve the domain, so IP is the reliable pick there. Trade-off: re-import if you migrate servers."
                if use_ip else
                "Domain — migrate servers with just a DNS change (no client re-import). If a desktop client times out resolving it, use the IP tab.")
        body = f"""<div class='panel'>
  <div class='panel-head'><span>{html.escape(client['name'])} · port {int(client['port'])}</span><span class='actions'>{tabs}<a class='btn sm primary' href='/clients/download?name={q}&amp;fmt=clash&amp;host={hp}'>&#8595; .yaml</a><a class='btn sm' href='/clients/download?name={q}&amp;fmt=uri&amp;host={hp}'>&#8595; ss://</a><a class='btn sm' href='/clients'>&larr; Back</a></span></div>
  <div class='panel-body'>
    <p class='hint'>Phone: import the <b>URI</b>. Desktop: import the <b>full Clash config</b> below. {note}</p>
    <dl class='kv'>
      <dt>Server</dt><dd>{html.escape(eff)} <span style='color:var(--muted)'>({hp})</span></dd>
      <dt>Port</dt><dd>{int(client['port'])}</dd>
      <dt>Cipher</dt><dd>{SS_METHOD}</dd>
      <dt>Password</dt><dd><span id='c-pwd'>{html.escape(client['password'])}</span><button class='btn sm copy' data-t='c-pwd' onclick='bpCopy(this)'>copy</button></dd>
      <dt>URI</dt><dd><span id='c-uri' style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:500px'>{html.escape(uri)}</span><button class='btn sm copy' data-t='c-uri' onclick='bpCopy(this)'>copy ss://</button></dd>
    </dl>
  </div>
</div>
<h2>Single node</h2>
<div class='panel'><div class='panel-body'><div class='codewrap'><button class='btn sm copy' data-t='cfg-node' onclick='bpCopy(this)'>copy</button><pre id='cfg-node'>proxies:
{html.escape(node)}</pre></div></div></div>
<h2>Full Clash / Mihomo config (import as a whole)</h2>
<div class='panel'><div class='panel-body'><div class='codewrap'><button class='btn sm copy' data-t='cfg-full' onclick='bpCopy(this)'>copy</button><pre id='cfg-full'>{html.escape(full)}</pre></div></div></div>"""
        self.send_html("Client config", self.layout("Client config", body))

    def download_client(self, name: str, fmt: str, host: str = "domain") -> None:
        client = self.find_client(load_clients(), name)
        eff = effective_host(host == "ip")
        suffix = "-ip" if host == "ip" else ""
        if fmt == "uri":
            self.send_download(f"{client['name']}{suffix}-ss.txt", ss_uri(client, eff) + "\n", "text/plain; charset=utf-8")
        else:
            self.send_download(f"{client['name']}{suffix}-clash.yaml", mihomo_full_config(client, eff), "application/x-yaml; charset=utf-8")

    def download_export(self) -> None:
        clients = [c for c in load_clients() if c.get("enabled", True)]
        nodes = "\n".join(clash_node(c) for c in clients)
        group = "proxy-groups:\n  - name: Proxy\n    type: select\n    proxies:\n" + "".join(f"      - {node_name(c)}\n" for c in clients)
        self.send_download("nodes.yaml", "proxies:\n" + nodes + "\n\n" + group, "application/x-yaml; charset=utf-8")

    def find_client(self, clients: list[dict[str, Any]], name: str) -> dict[str, Any]:
        for client in clients:
            if client["name"] == name:
                return client
        raise ValueError("account not found")

    def add_client(self, form: dict[str, str]) -> None:
        clients = load_clients()
        name = slugify_name(form.get("name", ""))
        if any(c["name"] == name for c in clients):
            raise ValueError("account already exists")
        port_s = form.get("port", "").strip()
        port = int(port_s) if port_s else next_port(clients)
        if port < 1 or port > 65535:
            raise ValueError("invalid port")
        if port in used_ports(clients):
            raise ValueError("port already used")
        clients.append({"name": name, "port": port, "password": random_password(), "enabled": form.get("enabled") != "false", "created_at": now_iso(), "updated_at": now_iso()})
        ok, message = apply_sing_box(clients)
        if not ok:
            raise RuntimeError(message)
        save_clients(clients)
        ufw_allow(port)
        audit("client.add", f"{name}:{port}")
        self.redirect("/clients?flash=" + urllib.parse.quote(
            f"Account '{name}' created on port {port}. UFW opened this port — now ALSO open TCP {port} in your cloud provider's firewall / security group, or it will time out."))

    def toggle_client(self, form: dict[str, str]) -> None:
        clients = load_clients()
        client = self.find_client(clients, form.get("name", ""))
        client["enabled"] = not bool(client.get("enabled", True))
        client["updated_at"] = now_iso()
        ok, message = apply_sing_box(clients)
        if not ok:
            raise RuntimeError(message)
        save_clients(clients)
        audit("client.toggle", f"{client['name']} enabled={client['enabled']}")
        self.redirect("/clients")

    def rotate_client(self, form: dict[str, str]) -> None:
        clients = load_clients()
        client = self.find_client(clients, form.get("name", ""))
        client["password"] = random_password()
        client["updated_at"] = now_iso()
        ok, message = apply_sing_box(clients)
        if not ok:
            raise RuntimeError(message)
        save_clients(clients)
        audit("client.rotate", client["name"])
        self.redirect("/clients")

    def delete_client(self, form: dict[str, str]) -> None:
        clients = load_clients()
        name = form.get("name", "")
        deleted = self.find_client(clients, name)
        port = int(deleted["port"])
        clients = [c for c in clients if c["name"] != name]
        ok, message = apply_sing_box(clients)
        if not ok:
            raise RuntimeError(message)
        save_clients(clients)
        ufw_delete(port)
        audit("client.delete", f"{name}:{port}")
        self.redirect("/clients")

    def apply_clients(self) -> None:
        ok, message = apply_sing_box(load_clients())
        if not ok:
            raise RuntimeError(message)
        audit("config.apply", "manual")
        self.redirect("/clients")

    def ops_restart(self) -> None:
        proc = run(["systemctl", "restart", "sing-box"], timeout=30)
        ok = proc.returncode == 0
        audit("ops.restart", "sing-box ok" if ok else (proc.stderr or "failed"))
        self.redirect("/?flash=" + urllib.parse.quote("sing-box restarted" if ok else f"restart failed: {proc.stderr or proc.stdout}"))

    def ops_speedtest(self) -> None:
        result = speed_test()
        audit("ops.speedtest", result)
        self.dashboard(flash=result)

    def export_page(self) -> None:
        clients = [c for c in load_clients() if c.get("enabled", True)]
        nodes = "\n".join(clash_node(c) for c in clients)
        group = "proxy-groups:\n  - name: Proxy\n    type: select\n    proxies:\n" + "".join(f"      - {node_name(c)}\n" for c in clients)
        export_config = "proxies:\n" + nodes + "\n\n" + group
        body = f"<div class='panel'><div class='panel-head'><span>All enabled nodes (Mihomo)</span><a class='btn sm primary' href='/export/download'>&#8595; nodes.yaml</a></div><div class='panel-body'><div class='codewrap'><button class='btn sm copy' data-t='exp' onclick='bpCopy(this)'>copy all</button><pre id='exp'>{html.escape(export_config)}</pre></div></div></div>"
        self.send_html("Export", self.layout("Export", body))

    def audit_page(self) -> None:
        path = CONFIG_DIR / "audit.log"
        lines = path.read_text(encoding="utf-8").splitlines()[-200:] if path.exists() else []
        body = "<div class='panel'><div class='panel-body'><pre>{}</pre></div></div>".format(html.escape("\n".join(lines)))
        self.send_html("Audit", self.layout("Audit", body))


def main() -> None:
    ensure_dirs()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{APP_NAME} listening on http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
