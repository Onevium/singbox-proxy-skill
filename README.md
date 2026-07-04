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

## 血泪铁律（这几条是这个项目的核心价值）

1. **用经典 Shadowsocks（aes-256-gcm），不用 SS2022。** SS2022 多用户组合密钥 **Hiddify 解析不了**，抗审查表现也未验证；经典 SS 所有客户端通用、实测能穿。
2. **代理超时但端口能通 = IP 脏了，不是配置问题。** `nc` 能连、墙外能用、墙内超时 → 这个 VPS IP 被防火墙盯上了。**换个干净 IP**，别在配置里瞎折腾。（腾讯云日本 IP 尤其容易脏，优先首尔/新加坡/香港。）
3. **面板绝不公网裸奔。** 只监听 `127.0.0.1:7000`，走 SSH 隧道进；真要公网就用防火墙**只放行你一个源 IP**。
4. **客户端指向域名，不指向 IP。** 换机器 = 改一条 DNS，客户端零改动。域名必须 **DNS-only（灰云）**，别套 Cloudflare 橙云代理（扛不了 SS）。
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
