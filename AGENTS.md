# AGENTS.md

This repository is a portable **agent skill**. The full instructions live in
[`SKILL.md`](./SKILL.md) — read it as the entry point, then follow its links into
[`references/`](./references) as needed.

For humans and non-agent use, see [`README.md`](./README.md).

Any agent (Claude Code, Cursor, Cline, Aider, Codex, …) can use this skill:
point it at `SKILL.md`. It deploys and manages a self-hosted Shadowsocks proxy
via the scripts in [`scripts/`](./scripts) and the single-file panel
[`app.py`](./app.py).
