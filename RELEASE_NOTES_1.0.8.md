# MAGOS 1.0.8 — Codex 与 Hermes 一键批准版 / One click in Codex and Hermes

A feature release: Codex and Hermes get the click that Claude Code has had since 1.0.7. A user-only guard command (`override`, `arm`, `disarm`, `install`) is approved in each host's own prompt instead of a command typed in a terminal.

## 版本概述

1.0.8 把 1.0.7 在 Claude Code 里的一键批准带到 Codex 和 Hermes。Codex：守卫自带一个本地 MCP 服务，代理在被拦截后调用它，Codex 弹出带一个必选“批准”勾选框的表单，勾上并确认才执行；审批策略为 `never` 时 Codex 自己拒绝，然后走终端。Hermes：插件注册两个检查，用 Hermes 自己的人工审批提示确认；在 `/yolo`、`-z`、`-q`、`approvals.mode off` 等不会真的问人的情况下，守卫改走终端。这两条路线都没有免点击的路径；`override`、`disarm` 永远要你点或在终端里输入。同时，守卫收紧了一处：工具命令里守卫的子命令必须是写明的普通单词，用变量、命令替换、`xargs` 喂入、`hook`、`mcp` 等都会被拒绝。

## Highlights

- **Codex: one click.** The guard's `mcp` subcommand is a local MCP approval server with the tool `magos_approve`; Codex's form has one required Approve checkbox; the root `mcp.json` brings the server with the plugin.
- **Hermes: one click.** The plugin's two callbacks hand Hermes the rewritten command and its own approval request; Hermes' prompt is the click.
- **No click-free path in these routes, no unattended override.**
- **The subcommand of a guard run must be a plain word** (closes a route that would have let an agent answer the Codex form itself).
- **`doctor` and `install`** know both routes.
- **A fix for a Windows race:** two processes using one approval token at the same instant could both succeed (1.0.7 had it); the token is now claimed exclusively and the second use answers 27.

## Changed

- The Hermes plugin turns the guard on for every terminal call after `hermes plugins update magos` and a restart (`MAGOS_GUARD=off`, `magos.guard off` and `hermes plugins disable magos` turn it off).
- The ready terminal command is quoted for Windows PowerShell 5.1; the denial, `need_tty`, token errors, install footer and `doctor` name the click per host.
- Documents and pins describe the three routes and their limits.

## 升级 / Upgrade

1. Upgrade the plugin on each host and restart it: Codex `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos`; Hermes `hermes plugins update magos`; Claude Code `claude plugin marketplace update magos`, then `claude plugin update magos@magos`. A Hermes install pinned with `--ref` must move its pin to the commit of `v1.0.8`.
2. Codex: merge the hook entry printed by `install --host codex` into your Codex hook file and review it once in `/hooks`. Hermes: remove any MAGOS `hooks:` entry from the Hermes config.
3. Nothing needs configuring: `prompt` is the default; `git config --local magos.approval terminal` keeps the terminal route.

## Known issues

- Nobody has clicked the real Codex app or the real Hermes prompt yet; the routes were checked with each host's own protocol and a fake model.
- The Codex server cannot authenticate its client: a renamed copy or `python -c` can play the client (the same class as forging state files).
- The Codex hook still comes from `install --host codex` and your trust in `/hooks`.
- Hermes `/yolo` and `-z` are seen through undocumented Hermes internals; if they change, the plugin falls back to the terminal.
