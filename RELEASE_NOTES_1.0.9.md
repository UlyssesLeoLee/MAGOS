# MAGOS 1.0.9 — 1.0.8 审查修复版 / Review fixes for 1.0.8

A security and fix release after a full code review of 1.0.8. The guard's hook now reads every part of a command before it decides, and the Codex and Hermes approval routes read their directories and commands exactly.

## 版本概述

1.0.9 修复对 1.0.8 全面审查发现的问题。1.0.8 中，代理自己的 shell 与它能启动的审批服务之间只隔着钩子的文本检查，所以每个漏读之处都可能让一条普通命令在没有人点击的情况下批准 `override`、`arm`、`disarm` 或 `install`。1.0.9 让钩子读完整条命令后取最严重的结论（引号、子 shell、here-document、git 别名值、多个写入目标都会读到），识别更多守卫与 Python 的写法，拒绝超过三层嵌套且提到 MAGOS 的文本；Codex 的拒绝只为一条规整的守卫调用给出 `magos_approve` 参数；Hermes 对目录与 `~` 的判断更严格，插件在 `plugins.isolation: host` 下不再误拦 `plan`、`version`。

## Highlights

- **One severity ranking.** An always-denied finding (a user-only subcommand, `mcp`, `hook`, an approval-store write) anywhere in a command wins over a guarded one before it.
- **Here-documents, brace and glob words, guard-word spellings, Python builds, git alias values and deep nesting** are read; text nested deeper than three levels that names MAGOS is denied.
- **Linear reading** of long commands.
- **Codex denial** maps only one plain invocation of this guard onto `magos_approve`.
- **Hermes**: stricter directories, `~` words refused without `workdir`, and the plugin works under `plugins.isolation: host`.

## Known limits

- The Codex approval server cannot authenticate its client; the hook's text filter is the barrier and reads the spellings above, not a renamed copy of the guard.
- A Hermes terminal call without `workdir` is judged in the Hermes process directory (unchanged).

## 升级 / Upgrade

1. Upgrade the plugin on each host and restart it: Claude Code `claude plugin marketplace update magos`, then `claude plugin update magos@magos`; Codex `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos`; Hermes `hermes plugins update magos`.
2. Re-run `install --host <host>` to refresh copies under `~/.magos/guard`; `doctor` names a stale copy.
