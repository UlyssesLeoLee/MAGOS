# MAGOS 1.1.1 — 1.1.0 维护版 / Maintenance release of 1.1.0

A maintenance release of 1.1.0: the guard, the commands and every verdict are unchanged; the test workflow tests Python 3.9 on Linux again.

## 版本概述

1.1.1 的守卫、命令和所有判定都与 1.1.0 相同。GitHub 的 `ubuntu-latest` 已换成 Ubuntu 26.04，上面没有 Python 3.9，导致 Linux 上的 3.9 测试无法启动；测试工作流的 Linux 部分改在 `ubuntu-24.04` 上运行，最低版本 Python 3.9 重新在 Linux 和 Windows 上都受测试。分支保护 `/GitProtect` 等 1.1.0 的内容见 1.1.0 的发布说明。

## Highlights

- **Same guard as 1.1.0**: `/GitProtect`, the walker fixes and every verdict are unchanged.
- **CI**: the Linux test legs run on `ubuntu-24.04`, the last Ubuntu image with a Python 3.9 build.

## 升级 / Upgrade

1. Upgrade the plugin on each host and restart it: Claude Code `claude plugin marketplace update magos`, then `claude plugin update magos@magos`; Codex `codex plugin marketplace upgrade magos`, then `codex plugin add magos@magos`; Hermes `hermes plugins update magos`.
2. Re-run `install --host <host>` to refresh copies under `~/.magos/guard`; `doctor` names a stale copy.
