# MAGOS 1.1.2 — 覆盖无需指纹 / Override without a fingerprint

A feature release for the override of a denial: nobody has to copy or retype its 12-hex fingerprint any more when the repository has exactly one live denial.

## 版本概述

1.1.2 减轻覆盖（override）的操作负担：仓库里恰好有一条未过期的拒绝记录时，指纹由守卫自动填入。在 Codex 中，代理调用 `magos_approve` 做 `override` 时可以不带指纹；对话框会写明"指纹由守卫自动填入"，并显示这次覆盖放行的 lane、目标和冲突分支，你仍然先勾选 Approve 再接受。在终端里运行 `override --reason ...` 也可以省掉 `--fingerprint`；只要拒绝记录未过期，控制台会显示这次覆盖放行什么，你输入 `y` 即可，不必再敲一遍 12 位指纹（照旧输入指纹也可以）。Claude Code 和 Hermes 仍然要求带指纹。已经处理过、或者 lane 已经不再等待覆盖的拒绝记录会自动清除，损坏的记录也不再让读取出错。分支保护和创建检查的判定与 1.1.1 相同。

## Highlights

- **Codex**: `magos_approve` takes `override` without a fingerprint when there is exactly one live denial; the dialog names the denial it lets through.
- **Terminal**: `override --reason ...` needs no `--fingerprint`; a `y` (or, as before, the fingerprint) confirms while the denial record is live.
- **Claude Code and Hermes**: an `override` without `--fingerprint` is refused (the approval binds the command words).
- **Records**: a denial whose lane no longer waits (answered, re-planned, released, or now creatable) is retired; a damaged denial, override or approval record breaks nothing.

## Known limits

- The click is the 1.0.8 route (tick Approve, then accept). Under Codex's approval policy `never` Codex declines the form itself and the terminal remains; Codex's hooks cannot ask the user.
- A denial with no conflicting branch, and a denial of `check`, leave no record: give their fingerprint.

## 升级 / Upgrade

1. Upgrade the plugin on each host and restart it: Claude Code `claude plugin marketplace update magos`, then `claude plugin update magos@magos`; Codex `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos`; Hermes `hermes plugins update magos`.
2. Re-run `install --host <host>` to refresh copies under `~/.magos/guard`; `doctor` names a stale copy.
