# MAGOS 1.1.0 — 分支保护 / Branch protection

A feature release: the ninth command, `/GitProtect`, protects a branch against agents' commits, merges and rewrites on Claude Code, Codex and Hermes.

## 版本概述

1.1.0 新增第九个命令 `/GitProtect`：由你指定一个分支加以保护，此后代理经 Claude Code、Codex 与 Hermes 的受钩工具对它的提交、合并、改写、删除、重命名、强制移动，以及以它为目标的本地 push / fetch，都会被钩子拒绝（代码 `BRANCH_PROTECTED`，不能 override）。读取、检出它、从它创建其他分支和写其他分支仍然允许。设置与解除（`--release`）都只能由你批准：在宿主自己的批准对话框里点击，或在你自己的终端运行；`--status` 只读。保护是防误操作：它拦代理按 git 和 shell 常规写法的写入，不防刻意绕过（例如会执行程序的设置、URL 改写）。仓库的 `magos.guard off` 不会关闭保护。本版本同时修复了 Codex 在 Windows 上把字符串命令按 bash 读取的问题、cmd 的 `cd..` / `cd/d` 写法、PowerShell 的 `-Path:` 写法，以及 Hermes 插件对终端工作目录的判断。

## Highlights

- **`/GitProtect <branch> [--release] [--status]`** with the guard subcommands `protect` (user-only) and `protect-show` (read-only); Codex approves through `magos_approve`, Hermes through the plugin's question.
- **Order-aware hook rule**: `git switch -c feat && git commit` on a protected `main` is allowed (it writes `feat`); `git switch main; git commit` is refused with a hint to split or join the calls.
- **Guarded record**: deleting or rewriting `protected.json` or the refs of a protected repository is refused in the ordinary spellings (globs, `cd`, `find -delete`, pipes); only `MAGOS_GUARD=off` and `--release` lift a protection.
- **Walker fixes**: Codex string commands on Windows read as PowerShell; cmd `cd..` / `cd/d` / `cd;x`; PowerShell `Set-Location -Path:`; the Hermes plugin judges the terminal session's directory.

## Known limits

- An accident guard, not an evasion boundary: settings that run a program, URL rewriting, git control files edited between calls, interpreters and unhooked file tools are not judged.
- Pushes to a remote host and `gh pr merge` are guarded by the hosting service; your terminal and Git itself are not affected; Gemini CLI has no tool hook.

## 升级 / Upgrade

1. Upgrade the plugin on each host and restart it: Claude Code `claude plugin marketplace update magos`, then `claude plugin update magos@magos`; Codex `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos`; Hermes `hermes plugins update magos`.
2. Re-run `install --host <host>` to refresh copies under `~/.magos/guard`; `doctor` names a stale copy.
