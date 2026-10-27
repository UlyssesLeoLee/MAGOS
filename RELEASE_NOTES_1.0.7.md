# MAGOS 1.0.7 — 一键批准版 / The one-click approval release

A feature release: in Claude Code, `override`, `arm`, `disarm` and `install` are approved with a click in Claude Code's own permission dialog instead of a command typed in a terminal.

## 版本概述

1.0.7 让 Claude Code 里的 `override`、`arm`、`disarm`、`install` 不必再由你手工输入终端命令：代理先问你，你同意后它运行守卫命令，Claude Code 弹出自己的权限对话框，写明批准的是什么和代理写的理由，你点一下就是批准。级别由本仓库的 git 配置 `magos.approval` 决定：`terminal`（你在真实终端里运行）、`prompt`（默认，点一下批准）、`auto-safe`（普通的 `arm` 与装到默认守卫目录的 `install` 不用点击，`override` 与 `disarm` 仍然要问你）。没有让代理无人值守地覆盖的级别；想关掉守卫，自己运行 `git config --local magos.guard off`。Codex 与 Hermes 始终走终端路径。

## Highlights

- **One-click approval in Claude Code.** `override`, `arm`, `disarm` and `install` are approved with a click in Claude Code's own permission dialog, which shows what is approved and the reason the agent wrote.
- **Three levels.** `git config --local magos.approval <level>`: `terminal`, `prompt` (the default) and `auto-safe` (a plain `arm` and an `install` into the default guard home without a click; `override` and `disarm` still ask).
- **No unattended override.** There is no level at which an agent overrides or disarms on its own; the opt-out is `magos.guard off`, set by you.

## Changed

- The hook hands Claude Code the one direct guard command it asks you to approve, rebuilt with a single-use approval token (120 seconds, bound to the command); every approved run records its route (`via`).
- `SKILL.md`, `references/lane-split.md`, `references/installation.md`, `references/pressure-tests.md`, `PR_DESCRIPTION.md` and the three READMEs state the levels and disclose the approval and denial records.

## 升级 / Upgrade

1. Upgrade the plugin on each host (`references/installation.md`) and **restart every running Claude Code session**: `claude plugin marketplace update magos`, then `claude plugin update magos@magos`. A Hermes install pinned with `--ref` must move its pin to the commit of `v1.0.7`.
2. Nothing needs configuring: `prompt` is the default. To keep typing every user-only command in a terminal, run `git config --local magos.approval terminal` in each repository. To refresh a guard copy, run `doctor` from the new version and the `install --host <host>` commands it prints.

## Known issues

- The route relies on Claude Code holding a hook's `ask` until you click and applying the rewritten command (headless runs on Claude Code 2.1.310 showed both; the click in the real dialog is not covered by them). Codex and Hermes always use the terminal.
- The token is convenience, not access control: the barrier is the dialog; the lane guard's own limits are listed in `references/lane-split.md`, section 12.
- A guard older than 1.0.7 given `--approval` stops with a usage error.
