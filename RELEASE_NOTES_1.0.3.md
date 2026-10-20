# MAGOS 1.0.3 — 加固与 GitSweep 改进版 / Hardening and GitSweep release

A hardening release of the lane guard (`scripts/magos_guard.py`, `hooks/run-guard.cmd`) and an improvement of `/GitSweep`: `--push`, a readiness verdict with a recommended command, a remedy for every failed gate, and a run state whose `PARTIAL` form ends with a `Next preview:` line and a `Next command:` line. **Every install of an earlier version should upgrade**, including the guard copies under `~/.magos/guard` that the Codex and Hermes hooks run. Full detail and upgrade steps: [CHANGELOG.md, section 1.0.3](https://github.com/UlyssesLeoLee/MAGOS/blob/v1.0.3/CHANGELOG.md).

## 版本概述

1.0.3 继续加固 lane guard（分支/工作树“车道”守卫），并让 `/GitSweep` 能一次做完。守卫读取以下十余类写法：`git update-ref --stdin` 的记录、被反斜杠/反引号/脱字符转义的程序名、`git rebase --ex`/`--exe`、`git --shallow-file`、大小写不同的 `refs/HEADS`、`git update-ref` 的选项、`Start-Process -WorkingDirectory`、`powershell`/`pwsh` 的各种选项拼写与 PowerShell 的反引号、不存在目录之后的创建、以及启动器在 `py` 退出 103/112 时改用下一个解释器。`/GitSweep` 新增 `--push`：收敛之后把 `<branch>` 以一次快进推送发布到远端，只合并进本地 `<branch>` 的远端分支就能在同一次运行里清除；远端已经停在本地位置时不推送（`PUBLISH_NOT_NEEDED`）。预览末尾给出“一次完成就绪度”（`ONE_SHOT` / `PARTIAL` / `BLOCKED`）、推荐命令（`--remote`、`--lang` 照抄，有 `PUSH_THEN_DELETE` 的分支时不管有没有写 `--push` 都带上它，写了 `--push` 且推送预计会执行时也带上它）和每个遗留项的处理办法；判定评判的是推荐命令，而不是你敲的命令；目标状态里不含命令从不去碰的工作区，报告会把它们列出来。执行报告以 `COMPLETE` 或 `PARTIAL` 收尾，`PARTIAL` 时以 `Next preview:` 与 `Next command:` 两行收尾：先运行预览，再运行命令。

## Highlights

- **Update-ref records read.** The names of `git update-ref --stdin` records, with printf escapes, are read up to a backslash; an unreadable record is dynamic and denied as unparseable.
- **Escaped program words read.** `g\it`, ``g`it`` and `g^it` in a shell the hook cannot name are read as `git`; PowerShell's backtick is its escape character with its special sequences, and the gate that decides whether a line is read sees words without escapes and quotes and words that run a script or a shell.
- **More git spellings read.** `git rebase --ex` and `--exe`, `git --shallow-file <value>`, the options of `git update-ref`, and `refs/HEADS/x` in any letter case (host hook and the `reference-transaction` backstop) are judged like their plain forms; the alias check reads the subcommand after the values of every global option in one pass.
- **PowerShell read more completely.** `Start-Process git` runs in its `-WorkingDirectory`; every spelling of `-Command`, `-CommandWithArgs` and `-EncodedCommand` of `powershell` and `pwsh` is read in the walk, the tamper filter and a Codex argv.
- **Directories and claims.** A creation after a `cd` to a missing directory is judged in the directory the shell is in at that point; a claim stored under a name the Windows alias rule refuses allows the creation of its branch, and `list` and `doctor` name it.
- **Launcher.** Both halves pass on to the next interpreter when `py` exits 103 or 112.
- **`/GitSweep --push`.** With `--apply`, one fast-forward push of `<branch>` (`git push --recurse-submodules=no --no-follow-tags <remote> refs/heads/<branch>:refs/heads/<branch>`, never forced, never `--no-verify`) runs after the converge phase and before the remote deletions, so remote branches merged only into the local `<branch>` are deleted in the same run. When the remote's `<branch>` already equals the local tip nothing is pushed (`PUBLISH_NOT_NEEDED`); otherwise the push runs even when no remote branch depends on it.
- **One-shot readiness.** The `/GitSweep` preview ends with `ONE_SHOT`, `PARTIAL` or `BLOCKED`, a recommended command (with `--remote` and `--lang` as given) that carries exactly the flags that lift something, `--push` included whether or not it was typed when a remote branch is `PUSH_THEN_DELETE`, and when it was typed and the push is predicted to run, and the remaining items with their remedies; the verdict judges the recommended command, not the command as typed. Every failed gate is reported at once with its remedy, in `/GitConverge` too, and a `--remote` that `git remote` does not list is a gate of `/GitSweep`.

## New

- `/GitSweep <branch> --apply --push`, with `PUBLISH_NOT_NEEDED` when the remote branch already sits at the local tip, and `PUSH_SKIPPED`, `PUSH_FAILED` and `PUSH_UNCONFIRMED` for a push that does not run, fails, or does not move the remote branch to the local tip; the preview predicts the push from local refs, with or without `--push`, without the network.
- The readiness block of the `/GitSweep` preview: verdict, recommended command (`--discard-ignored` with the ignored files it deletes listed, `--push` with the commits it publishes), remaining items.
- The **Remedies** table of `references/commands.md` section 6, used by `/GitConverge` and `/GitSweep`, and the remedies for remote findings in section 7.
- The run state `COMPLETE` or `PARTIAL` at the end of the `/GitSweep` apply report, with two lines for `PARTIAL`, `Next preview:` (the same line without `--apply`, to run first so that the preview becomes the earlier plan) and `Next command:` (the line to run after that preview), whose flags come in the order `--apply`, `--discard-ignored`, `--push`, `--remote`, `--lang` with `--remote` and `--lang` as given. The `Next command:` line carries `--push` when some remote branch ended `PUSH_THEN_DELETE` or `PENDING_PUSH` for a reason that a rerun with `--push` can clear, or when `--push` was typed and the publish prediction says the push would still run; it never carries `--push` when the only reason is that `<branch>` is the remote default; with phase 2 `UNKNOWN` it carries `--push` only when it was typed. The end state leaves out a worktree the command never touches (a detached one, or one that holds `main` or another kept branch); the report lists it.
- Remote sweep safety: every git command runs as an argument list, never as a shell string; the name of a source branch, or of a remote branch that is not `NOT_TOUCHED`, outside ASCII letters, ASCII digits and `.` `_` `/` `+` `-` (or starting with `-` or `+`) is never passed to a command (`UNKNOWN` for a local source, `BLOCKED_BAD_NAME` for a remote branch); a remote with several URLs, or a push URL that differs from the fetch URL, and a live remote `HEAD` that names no branch make the sweep `UNKNOWN`; both push commands carry `--recurse-submodules=no`.
- `BLOCKED_SUBMODULE` follows git's own test (a `modules` directory in the worktree's git directory, or a populated submodule path), deinitializing does not lift it, and its remedy is to remove the worktree yourself or keep it; `PREDICTED_IGNORED_OVERLAP` marks in the preview the ignored-file overlap that stops an apply.
- Documentation: `README.ja.md`, a Japanese edition that follows the Chinese README section for section; all three READMEs share one language switcher and describe the 1.0.3 commands, the command names per host and the install steps.

## Changed

- A remote branch is classified against the converged target, so a preview and the apply after it agree: `PUSH_THEN_DELETE` when the publish step is predicted to run, in a preview with or without `--push` (an apply without `--push` leaves it and reports "kept: `--push` not typed"), and `PENDING_PUSH` when no push of the run clears it (the publish is not predicted to run, or the push was skipped, failed or unconfirmed). The remedies differ: rerun with `--push` or, once local `<branch>` holds its tip, push `<branch>` by hand for the first, clear the condition the report names for the second.
- The gates of `/GitConverge` and `/GitSweep` are evaluated all at once, each failed gate with its remedy; `/GitSweep` adds the gate `--remote <name>` not listed by `git remote`, and a failed gate makes its verdict `BLOCKED`.
- The `/GitSweep` hard stop on pushing reads: no commits or tags except the one fast-forward push of `<branch>` that `--push` makes; the other push is the lease-guarded deletion of one named remote branch at a time, and `/GitConverge` pushes nothing.
- The `Default` line of the `/GitConverge` help says that every failed gate and blocker is followed by the action that lifts it.
- The one-line hints of `git-sweep` list `[--apply] [--push] [--help]`; the full usage lists every option.

## 升级 / Upgrade

1. Upgrade the plugin on each host (`references/installation.md`) and **restart every running Claude Code session**. A Hermes install pinned with `--ref` must move its pin: `hermes plugins install UlyssesLeoLee/MAGOS --ref <40-char SHA of v1.0.3> --force --enable`.
2. Run `doctor` from the new version, then the `install --host <host>` commands it prints in your own terminal; compare each printed snippet with your host config and replace the entry if it differs.
3. In armed repositories, run `doctor` and re-run `arm`: the git-layer hook reads `heads` in any case, so `doctor` reports the installed hook as different until `arm` runs again.
4. Nothing else changes for scripts.

Claim files of 1.0.0 to 1.0.2 are read unchanged.

## Known issues

- Every host receives the whole repository (including `tests/`, `.quality/`, `.github/`) because the marketplace source is the repo root; a slim runtime payload is not part of 1.0.3.
- The lane guard's own limits are listed in `references/lane-split.md`, section 12.
- `/GitSweep --push` publishes with a plain fast-forward push and cannot undo it; undoing a publish takes a force push, which the command never makes.
