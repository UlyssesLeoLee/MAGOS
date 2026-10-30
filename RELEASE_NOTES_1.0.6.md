# MAGOS 1.0.6 — 统一命名版 / The one-naming release

A patch release: the `/` menu of Claude Code lists the eight commands under one naming, and the READMEs say what the plugin runs, sends and fetches. The behaviour of the lane guard is unchanged.

## 版本概述

1.0.6 让 Claude Code 的 `/` 菜单里只出现八个 `/magos:GitXxx` 命令，写法统一：入口 Skill `git-orchestrator` 不再出现在菜单里，由 Claude 在你描述问题时自己加载（模型看到它的方式不变）。三份 README 的最前面新增“它运行什么、发送什么、联网做什么”一节，各处关于命令名的说明也改成各宿主真正提供的名字：Claude Code 里是 `/magos:GitXxx`，Hermes 里是 `/magos:git-xxx`，Codex 里是 `$magos:git-xxx`。守卫的行为不变，只有版本号随包升到 1.0.6。

## Highlights

- **One naming in the menu.** Claude Code lists the eight `/magos:GitXxx` commands and nothing else; the orchestrator `git-orchestrator` is loaded by Claude on its own.
- **What it runs, sends and fetches.** A section at the top of the three READMEs: the hooks, what the guard reads and writes, that it sends and fetches nothing, which commands touch the network only when you ask, and how to turn it off.
- **Texts that match the hosts.** The READMEs and the eight adapters name the commands each host really offers; the disclosure says where the model is kept from starting the write commands (Claude Code, Codex) and where it is only told (Hermes).

## Changed

- `skills/git-orchestrator` sets `user-invocable: false`.
- The package contract requires that setting on the entry skill and drops the unused `WRITE_ADAPTERS`; the README test reads a `#` inside quotes as part of the command; TC-104 of the test design states the rule and names the tests.
- `GUARD_VERSION` and the manifests state 1.0.6.

## 升级 / Upgrade

1. Upgrade the plugin on each host (`references/installation.md`) and **restart every running Claude Code session**: `claude plugin marketplace update magos`, then `claude plugin update magos@magos`. A Hermes install pinned with `--ref` must move its pin: `hermes plugins install UlyssesLeoLee/MAGOS --ref <40-char SHA of v1.0.6> --force --enable`.
2. The guard changes only in its version number; run `doctor` from the new version and the `install --host <host>` commands it prints to refresh a guard copy.

## Known issues

- Claude Code does not document how `user-invocable: false` and `disable-model-invocation: true` combine; the one set of commands was checked on Claude Code 2.1.309 only.
- A host other than Claude Code that reads the same two frontmatter keys hides the adapters there too.
- A second set can still come from files outside the package: command copies in `~/.claude/commands/` and a clone below `~/.claude/skills/`.
- The lane guard's own limits, unchanged since 1.0.3, are listed in `references/lane-split.md`, section 12.
