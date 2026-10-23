# MAGOS 1.0.5 — 单套命令版 / The one-set release

A patch release: Claude Code shows one set of commands. Until now the plugin listed every command twice there, as `/magos:GitRecon` (from `commands/`) and as `/magos:git-recon` (the adapter of `skills/`, made for Codex and Hermes). The behaviour of the lane guard is unchanged.

## 版本概述

1.0.5 让 Claude Code 里每个命令只出现一套。以前插件把 `commands/` 里的命令（`/magos:GitRecon`）和给 Codex、Hermes 用的适配层（`skills/git-recon`，在 Claude Code 里成为 `/magos:git-recon`）都列了出来，同一个命令有两套。现在八个适配层在头信息里设置了 `user-invocable: false` 与 `disable-model-invocation: true`：Claude Code 的 `/` 菜单只列八个命令和入口 Skill `git-orchestrator`，模型也只会看到三个只读命令和入口 Skill。Codex 与 Hermes 忽略这两个键，`$git-recon`、`/git-recon` 照常使用。守卫的行为不变，只有版本号随包升到 1.0.5。

## Highlights

- **One set in Claude Code.** The `/` menu lists the eight commands `/magos:GitRecon` ... `/magos:GitPlan` and the entry skill `git-orchestrator`; the model is offered the three read-only commands and the entry skill.
- **Codex and Hermes unchanged.** Codex reads only the fields it knows, Hermes reads the frontmatter as a mapping: both ignore `user-invocable` and `disable-model-invocation`.
- **Guarded by the package contract.** Both keys are required on the eight adapters and forbidden on the entry skill and the root `SKILL.md`; the frontmatter reader accepts exactly one boolean per key.

## Changed

- The eight adapters of `skills/` set `user-invocable: false` and `disable-model-invocation: true` (the five write adapters already set the second one).
- `references/installation.md` states the one set and the usual sources of a second one: command copies in `~/.claude/commands/` and a clone below `~/.claude/skills/`.
- `GUARD_VERSION` and the manifests state 1.0.5.

## 升级 / Upgrade

1. Upgrade the plugin on each host (`references/installation.md`) and **restart every running Claude Code session**: `claude plugin marketplace update magos`, then `claude plugin update magos@magos`. A Hermes install pinned with `--ref` must move its pin: `hermes plugins install UlyssesLeoLee/MAGOS --ref <40-char SHA of v1.0.5> --force --enable`.
2. Delete command copies in `~/.claude/commands/` (`Git*.md`): the plugin provides the commands.
3. The guard changes only in its version number; run `doctor` from the new version and the `install --host <host>` commands it prints to refresh a guard copy.

## Known issues

- A second set can still come from files outside the package: command copies in `~/.claude/commands/` and a clone below `~/.claude/skills/` (its root `SKILL.md` is also a personal skill).
- Codex was not available for a check of the two host keys; it reads only the fields it knows, as it already does for `disable-model-invocation`.
- The lane guard's own limits, unchanged since 1.0.3, are listed in `references/lane-split.md`, section 12.
