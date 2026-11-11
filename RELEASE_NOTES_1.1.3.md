# MAGOS 1.1.3 — Claude Code 不再运行批处理文件 / No batch file in Claude Code

Claude Code no longer runs a batch file: its hooks start the guard through a POSIX shell launcher, so no Claude Code hook starts cmd.exe.

## 版本概述

在 Windows 上，Claude Code 通过 Git Bash 运行钩子，而 Git Bash 会把扩展名是 `.cmd` 的文件交给 cmd.exe。所以在此之前，每次调用 Bash、PowerShell、Agent 等工具，都会从插件缓存里用 cmd.exe 启动批处理与 shell 两用的启动器 `hooks/run-guard.cmd`，一些杀毒软件（例如 360 安全卫士）会反复拦截它。1.1.3 新增纯 shell 启动器 `hooks/run-guard`：Claude Code 在所有系统上都改为 `sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-guard" ...`，不再启动 cmd.exe，也不再运行批处理文件；在 Windows 上它先试 `py -3`，与原来的选择一致。`install` 打印的 Claude 配置、Codex 的 `command` 和非 Windows 上的 Hermes 条目也改用 `run-guard`；Windows 上的 Codex（`commandWindows`）和 Hermes 条目仍然运行 `run-guard.cmd`。`run-guard.cmd` 保持原样，以前合并的条目照常工作。守卫的所有判定与 1.1.2 相同。

## Highlights

- **Claude Code**: `hooks/hooks.json` runs `sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-guard"`; no hook starts cmd.exe or a batch file.
- **Codex and Hermes**: the POSIX entries `install` prints run `run-guard`; the Windows entries still run `run-guard.cmd`.
- **doctor**: compares both launchers and names a generated entry that still runs `run-guard.cmd`, a Claude one included; it reads the entries `install` generated, not your host configuration.
- **POSIX launcher**: a `nounset` or `errexit` in the host's `SHELLOPTS` cannot stop it, and `MAGOS_GUARD=off` is read in any case.

## Known limits

- Codex and Hermes on Windows still start cmd.exe on `run-guard.cmd`, so a security product may still react there.
- Entries merged before 1.1.3 keep running `run-guard.cmd`, which is unchanged; merge the new entry to move them. A Claude entry from `install --host claude` in `~/.claude/settings.json` starts cmd.exe on Windows until you merge the new one.
- On Windows, Git Bash reads a hook's payload one byte at a time: about 1.5 s more per MB than through cmd.exe.

## 升级 / Upgrade

1. Upgrade the plugin on each host and restart it: Claude Code `claude plugin marketplace update magos`, then `claude plugin update magos@magos`; Codex `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos`; Hermes `hermes plugins update magos`.
2. Re-run `install --host <host>` to refresh copies under `~/.magos/guard`; on Linux and macOS merge the printed Codex or Hermes entry to move it to `run-guard`; on Windows, if you use the `install --host claude` entry instead of the plugin, merge the new Claude entry into `~/.claude/settings.json`. `doctor` names a stale copy and a generated entry that still runs `run-guard.cmd`; `doctor` reads the entries `install` generated under `~/.magos/guard/generated/`, not `~/.claude/settings.json` or the Codex and Hermes configuration: after `install` has written the new entry, replace the old one there yourself.
