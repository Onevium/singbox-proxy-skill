**中文** · [English](README.en.md)

# singbox-proxy-skill —— 给 Claude Code / AI 工具自建稳定 IP 代理

> 给开发者的「**稳定 IP 搭建**」skill:一条命令级地在自己的 VPS 上起一套
> **sing-box Shadowsocks 中转 + 网页管理面板 + 安全加固**，可选链一个**静态住宅出口**，
> 让你从任何网络都能**稳定、可信地**访问 Claude Code / Claude API / Codex / Cursor 等 AI 开发工具。
> 手动可跑,也能被任何 AI 编码 agent 驱动。

**singbox-proxy-skill** 是一个开源的 [Claude Code](https://claude.com/claude-code) agent
skill（也可移植到 Cursor / Cline / Aider / Codex 等）。你把一台干净的 Ubuntu VPS 交给它，它就：

- 装好 **sing-box**（经典 Shadowsocks `aes-256-gcm`，一账号一端口一密码）；
- 起一个**单文件网页面板**：服务器实时监控（CPU/内存/磁盘/网络/服务健康）+ 账号增删/禁用/轮换 + 一键导出配置；
- 做好 **SSH 加固 + UFW + fail2ban + 自动安全更新**；
- 可选**链上游 SOCKS5/HTTP 代理**（住宅出口 IP），可选**绑域名**（换机器只改 DNS，客户端零改动）；
- **抗封传输可选**：经典 SS（默认）/ VLESS+REALITY / VLESS+WS+TLS 套 **Cloudflare CDN**——干净 IP 被封或被限速时，换协议或让源站藏到 CF 后面（见下方[链路架构](#链路架构两种方案看你有没有-cloudflare)）；
- 一键出 **Clash / `ss://`** 配置发给你的电脑和手机。

## 管理面板（网页）

登录后即是**服务器实时监控**（CPU / 内存 / 磁盘 / 网络 / 服务健康 / 出口 IP），走 SSH 隧道访问、不公网暴露：

![仪表盘](assets/dashboard.png)

**账号管理** —— 一账号一端口一密码，可创建 / 禁用 / 启用 / 轮换密码 / 删除：

![账号管理](assets/accounts.png)

**每个账号一键导出配置**（手机 `ss://` + 电脑完整 Clash YAML，含国内外分流规则）：

![客户端配置](assets/config.png)

> 图中均为脱敏示例数据（`vpn.example.com` / `203.0.113.7`）。

## 为什么要「稳定 IP」——Claude Code 的痛点

Claude Code / Claude API、OpenAI、Cursor 这些 AI 工具**对你的出口 IP 很敏感**：

- **机房 / 云 IP** 经常被限流、弹验证码，甚至直接 403（看着像机器人）；
- **共享 VPN IP** 会轮换、被拉黑，动不动掉线重登；
- **静态住宅 / ISP IP** 像正常家庭用户：固定、可信、不轮换 —— Claude Code 稳定在线、不被卡。

所以最稳的组合是:**离你近的干净 IP VPS 做入口**（握手快、线路好）+ **静态住宅上游做出口**（AI 服务看到的那个可信身份）。
只想翻过网络封锁、不在乎 IP 信誉，就跳过上游，直接从 VPS 出。选型见 [`references/providers.md`](references/providers.md)。

## 链路架构：两种方案，看你有没有 Cloudflare

同一套服务器，两种客户端接入链路。**没有 Cloudflare 域名 → 走方案一（经典直连，老搭建）；有域名并托管到 Cloudflare → 走方案二（CDN 抗封，新链路）。** 出口那一段（可选的静态住宅上游）两种方案完全一样。

### 方案一 · 经典直连（无需 Cloudflare · 最简单）

客户端直接连你 VPS 的公网 IP。传输用经典 Shadowsocks（或 VLESS+REALITY）。

```text
 ┌──────────┐   经典SS / REALITY    ┌───────────────┐  （可选）SOCKS5上游  ┌────────────────┐
 │  你的设备  │ ───────────────────▶ │   你的 VPS      │ ─────────────────▶ │  静态住宅出口 IP  │ ──▶ 互联网
 │ Mac / 手机 │   直连 VPS 公网 IP     │ sing-box 入站   │    住宅代理商        │  例 198.51.x.x   │
 └──────────┘                       └───────────────┘                    └────────────────┘
      ▲ VPS 的公网 IP 直接暴露给客户端：IP 干净就又快又稳；一旦被 GFW 盯上，
        要么整 IP 被封（换干净 IP），要么经典 SS 被识别限速（换 REALITY 或上方案二）。
```

### 方案二 · Cloudflare CDN 抗封（有域名 · 新链路）

客户端只连 **Cloudflare**，你 VPS 的源站 IP 从不出现在链路上——GFW 封不到、也识别不了（看着就是普通 HTTPS 访问 CF）。

```text
 ┌──────────┐   标准 TLS      ┌──────────────┐   CF 加密回源   ┌───────────────┐ （可选）住宅上游 ┌────────────────┐
 │  你的设备  │ ─────────────▶ │  Cloudflare   │ ─────────────▶ │  你的 VPS 源站  │ ────────────▶ │  静态住宅出口 IP  │ ──▶ 互联网
 │ Mac / 手机 │  优选IP : 443   │  全球边缘节点   │               │ VLESS+WS+TLS  │   住宅代理商     │  例 198.51.x.x   │
 └──────────┘                 └──────────────┘                └───────────────┘                └────────────────┘
      ▲ 你连的是 Cloudflare 的 IP（优选 IP），源站 IP 永不上网 → 封不到 / 限不了；
        代价是速度受「你家宽带 → Cloudflare」这段路由质量限制（国内电信线常见 1–2 Mbps）。
```

### 怎么选

| | 方案一 经典直连 | 方案二 Cloudflare CDN |
|---|---|---|
| 需要域名 | 否（IP 或 DNS-only 域名） | **是**（域名 NS 托管到 Cloudflare） |
| 源站 IP | 暴露给客户端 | **隐身**（客户端只见 CF） |
| 被 GFW 封 IP | 会（换 IP） | **封不到** |
| 被识别限速 | 经典 SS 会（换 REALITY） | **识别不了**（就是标准 TLS） |
| 速度 | IP 干净时最快 | 受 China→CF 路由限制 |
| 适合 | 起步、IP 干净、没域名 | IP 反复被封/限速、要长期稳 |

先从方案一起步；等**干净 IP 也被封或被限速**时，再切 REALITY 或方案二。三种传输（SS / REALITY / CF-CDN）的选择与逐步搭建，见 [`references/anti-censorship.md`](references/anti-censorship.md)。

## 快速开始

> 你**不需要已经能用 Claude Code**（正因为环境不稳才来搭它）。三条命令**纯手动**就能跑完，
> 或者用你**手头任何**能读 skill 的编码 agent / AI IDE 来驱动。

**方式一 · 手动三条命令（不依赖任何 AI 工具，最省事）** —— 见下面。

**方式二 · 让 agent / AI IDE 帮你做**：把这个仓库交给你在用的工具 —— Claude Code、
[Codex](https://openai.com/codex/)、Cursor、Cline、Aider，或国内的**通义灵码 / CodeGeeX / 文心快码 Comate /
MarsCode / Trae** 等 —— 让它读 [`SKILL.md`](SKILL.md)，说一句"照这个 skill 在我这台 VPS 上搭稳定 IP 代理"，
把 VPS 的 `user@host` + 密钥给它即可。（用 Claude Code 的话可直接 `/singbox-proxy`。）

**手动三条命令:**

```bash
# 1. 部署（SERVER_HOST=客户端连的域名或IP；UPSTREAM_URL 可选）
SERVER_HOST=vpn.example.com \
FIRST_ACCOUNT=my-laptop FIRST_PORT=443 \
UPSTREAM_URL=socks5://user:pass@1.2.3.4:1080 \
./scripts/deploy.sh -i ~/.ssh/id_ed25519 root@203.0.113.10

# 2. 加固（SSH 仅密钥 + UFW + fail2ban）
ssh -i ~/.ssh/id_ed25519 root@203.0.113.10 \
  'cd /tmp/proxy-admin-panel && sudo SS_PORTS="443 80 8443" TIMEZONE=Asia/Seoul bash scripts/harden.sh'

# 3. SSH 隧道进面板（面板只监听本机，绝不公网暴露）
ssh -i ~/.ssh/id_ed25519 -L 17000:127.0.0.1:7000 root@203.0.113.10
# 浏览器打开 http://127.0.0.1:17000
```

之后**换机器只改一条 DNS A 记录**，客户端一个字都不用动。

## 端口 & 防火墙（务必看懂，别被误导）

这套用**经典 Shadowsocks**，模型是 **一账号 = 一端口 = 一密码**：

- ✅ **优点**：全客户端通用（含 Hiddify）；每台设备独立密码，丢设备只需禁用/轮换**那一个**账号，不影响别人。
- ⚠️ **代价**：**每个用到的端口，必须在两层防火墙都放行** ——
  1. 机器内 **UFW** —— `harden.sh` 设好初始端口，**而且面板加/删账号时会自动 `ufw allow` / `ufw delete`**，这层你不用管；
  2. **你云厂商控制台的安全组 / 防火墙**（腾讯云/阿里云/Vultr… 的网页控制台，**必须手动开**，任何软件都碰不了这层）。
  - 少开第 2 层，就会出现「**有的端口能连、有的超时**」——比如 80 通、443 超时，八成就是云控制台没放行 443。
- ➕ **新加一个账号 = 新开一个端口**：面板已自动开好 UFW，你**只需再去云控制台**放行该端口（后台建账号后也会弹提示）。
- 🧩 **不想每账号开端口？** 让所有人**共用一个端口 + 一个密码**（例如都用 443）：`FIRST_PORT` 设一个、大家导入同一份配置。永不再开端口，代价是没有独立密码（丢一台设备，全体换密码）。

> 一句话：**用几个端口，就要在「UFW + 云厂商安全组」两层各放行几个。** SS2022 那种「单端口多用户、加人不开端口」的方案本 skill **不用**（Hiddify 不兼容、抗审查未验证）。

## 血泪铁律（这几条是这个项目的核心价值）

1. **用经典 Shadowsocks（aes-256-gcm），不用 SS2022。** SS2022 多用户组合密钥 **Hiddify 解析不了**，抗审查表现也未验证；经典 SS 所有客户端通用、实测能穿。
2. **防火墙有两招，换 IP 只解一招。** ① 墙内 `nc` 就超时、墙外正常 = **整 IP 被 null-route** → 换干净 IP。② `nc` 能连、代理甚至能用，但**干净 IP 上速度被掐到几 KB/s** = 防火墙在**指纹识别 + 限速经典 SS** → 换 IP 没用（照样被限），得**换传输协议**（REALITY 或方案二 CF-CDN）。别一直换 IP 打地鼠。详见 [`references/anti-censorship.md`](references/anti-censorship.md)。
3. **面板绝不公网裸奔。** 只监听 `127.0.0.1:7000`，走 SSH 隧道进；真要公网就用防火墙**只放行你一个源 IP**。
4. **客户端指向域名，不指向 IP。** 换机器 = 改一条 DNS，客户端零改动。经典 SS/REALITY 的域名必须 **DNS-only（灰云）**（Cloudflare 橙云扛不了 SS）；**唯一例外是方案二 CF-CDN**——那里橙云代理 + VLESS+WS+TLS 源站正是核心，客户端钉一个 CF 优选 IP。
5. **密钥/密码只留服务端，绝不进 Git。**

详见 [`references/troubleshooting.md`](references/troubleshooting.md)（脏 IP / TUN 劫持 SSH / 域名解析 / Hiddify 等）、[`references/security.md`](references/security.md)、[`references/clients.md`](references/clients.md)、[`references/providers.md`](references/providers.md)。

## 仓库结构

```text
SKILL.md            部署与运维的完整流程（agent 入口）
app.py              单文件网页管理面板（纯标准库，无依赖）
scripts/
  install.sh        装 sing-box + 面板 + 首个账号（可选上游）
  harden.sh         SSH 加固 + UFW + fail2ban + 时区
  deploy.sh         本地推送到服务器并安装
references/
  anti-censorship.md 抗封三模式（SS / REALITY / Cloudflare CDN）+ 封锁vs限速诊断
  providers.md      VPS / 出口 IP / 域名 / 客户端 平台推荐
  troubleshooting.md 排障（脏 IP、TUN、Hiddify、带宽…）
  security.md       安全模型
  clients.md        各客户端导入
examples/
  config.example.json 面板配置示例（脱敏）
```

## 安全与合规

自托管、给自己和信任的人用。请遵守你所在地区的法律法规，并遵守 VPS / 代理服务商的条款。
本项目不提供任何绕过特定服务的手段，只是把一台你自己的 VPS 配成一个加固的 Shadowsocks 中转。

## License

[MIT](LICENSE)
