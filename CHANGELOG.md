# Changelog

Every version of the `magos` package (the `version` in `plugin.json`, `.claude-plugin/plugin.json`, `plugin.yaml`, `SKILL.md` and the lane guard's `GUARD_VERSION`). A release is tagged `v<version>` on its release commit. The tag `v1.0` marks the skill release 3.4.0 from before the package became a plugin and was renumbered; it is not a plugin version. Install, pin, upgrade and roll back as `references/installation.md` describes.

## 1.0.2

Tag `v1.0.2`. A security release of the lane guard (`scripts/magos_guard.py`, `hooks/run-guard.cmd`, `hooks/hooks.json`). Every 1.0.0 and 1.0.1 install should upgrade, including the guard copies under `~/.magos/guard` that the Codex and Hermes hooks run.

### Security

- **Repository redirects.** A creation redirected into another repository with `git --git-dir`, `GIT_DIR` or `GIT_COMMON_DIR` (prefix, `env`, `export`, PowerShell `$env:`, cmd `set`) was allowed without a manifest: the hook judged the session's repository, or none when the session was outside any repository, so a claim there or a session repository with no other lane let an unplanned lane be created in the other repository. Each creation is judged in the repository it acts on, with that repository's mode, engagement and claims; under `GIT_COMMON_DIR`, which makes Git use two repositories at once, it is judged in both; a redirect the hook cannot resolve is denied in every mode. `--work-tree` and `GIT_WORK_TREE` alone leave the judged repository unchanged.
- **Directory changes the shell may not make.** A `cd`, `pushd`, `Set-Location` or `GIT_DIR` change that the shell might never make before the creation moved the hook's judgement into another repository: one after `&&` or `||` followed by `;` (`false && cd other; git branch x`), inside `if`, `case` or a loop, in a function body or a PowerShell script block, in a background job (`&`), in a subshell `( )`, a command substitution `$( )`, a pipeline, `eval`, `source`, a PowerShell `( )`, or written as `env cd` (which changes nothing). The creation is now judged in every directory the shell may be in, and the stricter verdict applies. `cd dir && git switch -c x` and `cd dir; git switch -c x` are still judged in `dir` only.
- **Directories handed to wrappers.** `env -C <dir>` (`--chdir`) and `sudo -D <dir>` (`--chdir`) run git in `<dir>`, but the hook judged the directory the shell was in. They are judged like `git -C <dir>`.
- **`cd` to a missing directory.** `cd` or `Set-Location` to a directory that does not exist, followed by `;` or a newline, let the following branch or worktree creation through, although the shell runs it in the prior directory. For `cd`, `pushd`, `chdir`, `Set-Location` and `sl`, the creation is judged in that prior directory and denied as unparseable when it is guarded, on every platform; the same holds for a `cd` the shell refuses (`cd /d dir` in bash, `cd dir extra`), while cmd's `cd /d dir` is followed into `dir`.
- **Shells and wrappers that hid a creation.** Text piped into a shell was read only when the shell stood right after the pipe, so `| FOO=1 sh`, `| env bash`, `| sudo -E sh`, `| command sh` and `| doas sh` let a creation through; `doas git branch x`, PowerShell `$out = git switch -c x`, `(git switch -c x)` and `@(git switch -c x)`, and `env -S 'git switch -c x'` were not recognised. All of these are read as the creation they run.
- **Unhooked shell tools in Claude Code.** The `Monitor` tool and MCP tools that run commands (`run_in_terminal`, `terminal`, `shell`, `exec_command`, `execute_command`, `start_process`) were not inspected. They are hooked, and the Claude matcher is generated from the guard's tool list. `tool_input.cwd` is read as the session directory.
- **Programs in the working directory (Windows).** The launcher and the guard could run a `py`, `python` or `git` placed in the hook's working directory. Both set `NoDefaultCurrentDirectoryInExePath=1` before starting any program.
- **User-only commands.** `override`, `arm`, `disarm` and `install` passed the host hook when a global option was written as `--repo=.`, `--lang=en` or abbreviated (`--rep .`). They are recognised whatever the option spelling, options are never abbreviated, and `install` needs a real console like `arm` (exit 17).
- **AUTO engagement failures.** When the check for other lanes failed (for example on the time budget), an auto-named worktree (agent isolation, `gh pr checkout`) was allowed. It is denied, a branch-only creation is judged when the repository holds a claim, and every undecided call writes a warning on stderr.
- **Overrides.** The host hook honoured an override record without consuming it. Only `plan` reads override records; after the user's override, a re-plan registers it in the claim, and the hook honours only the claim.
- **Claim store.** `release` with another spelling of the branch (`./x`, a different case) skipped the refusal for unmerged work and could delete a file outside the claim store; branch names that alias on Windows (`foo./bar` and `foo/bar`, names ending in `.claim`) overwrote another lane's claim; a newline in `--worktree` or `user.name` added lines to a claim file; two planners could register clashing names at once. `release` resolves the stored claim and deletes only its file inside the store; aliasing names are refused (exit 12); control characters are refused or replaced and claim keys are whitelisted; the name check runs again under the claim lock.
- **Tamper filter.** Writes aimed at the claim store or the guard home by their absolute path are denied in armed or claimed repositories, as `.git/...` spellings are; `unlink`, `truncate`, `shred`, `ln`, `rmdir`, `rd`, `mklink` and `find -delete` count as writers.
- **Write adapters in Claude Code.** `git-integrate`, `git-cleanup`, `git-converge` and `git-sweep` set `disable-model-invocation: true`: only the user's slash command runs them.

### Added

- `version [--json]`: the running guard's version, the sha256 of its file, its path and the Python version. Read-only; agents may run it.
- `install` is version-aware and atomic: it prints `guard copy <old> -> <new>` or `guard copy unchanged (<version>)`, writes each file through a temporary file, records `guard/VERSION.json` (version, sha256, source, time), and refuses to replace a newer copy with exit 18 (`DOWNGRADE_REFUSED`) unless `--allow-downgrade` is given.
- `doctor` prints the running guard's version, compares the `~/.magos/guard` copy with it and prints the exact `install --host <host>` refresh command (also outside a repository), reports a Git older than 2.36, counts only a MAGOS veto as a passing self-test, and reports a recorded backstop command whose script no longer exists, with the `arm` command to re-run.
- `arm` records the guard command for the backstop's deny message as the `~/.magos` copy when there is one, so a plugin upgrade does not leave it pointing at a removed version; it records the previous `gc.packRefs` and `maintenance.pack-refs.enabled` values in `arm-config.json`, and `disarm` restores them.
- Claim format gate: every claim carries `v=`; a claim written by a newer MAGOS is never misread (creations are denied with `CLAIM_NEWER_FORMAT`, `release` refuses it, `plan` never overwrites it), and `list` shows unreadable and newer-format claim files.
- The Hermes entry that `install --host hermes` writes runs the Hermes plugin's own launcher when the plugin is installed, so it follows `hermes plugins update`; the entry is valid YAML on every platform.
- With `--json`, a Git failure or an internal error prints a deny object on stdout; a Git call that fails without a message names its exit code.
- `scripts/sync_hosts.py` recognises a MAGOS plugin installed from a Claude Code marketplace and leaves the Claude command copies out of a default run, as it does for a clone in `~/.claude/skills`.
- A CI workflow runs the guard suite, the package contract suite and both source-contract runners (`--check`) on Windows and Linux with Python 3.9, 3.12 and 3.14, and checks that a release tag names the package version.

### Changed

- The deny for an auto-named worktree tells the agent to plan `worktree-<name>` and then call `EnterWorktree name=<name>`; a refused `release` names uncommitted changes in the lane's worktree as the reason.
- The launcher's failure warning names the absolute guard path and a stop instruction for every host; its POSIX part reads the payload once and starts Python once.
- The test line that made the Hermes plugin scanner refuse `hermes plugins update magos` for 1.0.1 (text echoed into a shell) moved into a data file the scanner does not read, and a contract test keeps that shape out of every shipped file. When the scan still asks for confirmation, `hermes plugins install UlyssesLeoLee/MAGOS --force --enable` installs the update.
- The Claude Code plugin description no longer tells marketplace users to clone the repository as well.

### Upgrade

1. Upgrade the plugin on each host (`references/installation.md`, "升级"). Restart every running Claude Code session: a session started before the update keeps running the previous guard.
2. Refresh the guard copy: run `doctor` from the new version and, in your own terminal, the `install --host <host>` commands it prints. Compare each printed snippet with the entry in your host configuration and replace the entry when they differ (the Claude matcher of a user-level snippet, and the Hermes command when the Hermes plugin is installed, differ from 1.0.1).
3. In armed repositories, run `doctor` and re-run `arm` when it reports the recorded guard command as missing. The git-layer hook itself is unchanged.
4. Scripts that abbreviate guard options (`--rep`) must spell them out.

Compatibility: claim files of 1.0.0 and 1.0.1 are read unchanged. Exit code 18 is new.

## 1.0.1

Tag `v1.0.1` (commit `bab8606`).

### Security

- On Windows with Python 3.13 or later, a `cd` to a POSIX-rooted directory that cannot be mapped to a drive (`/does/not/exist`) before `git worktree add -b` or `git switch -c` was judged against a repository that does not exist, and the creation was allowed without a manifest. Python 3.13 changed `os.path.isabs` on Windows, and the hooks run under the `python3` found on the machine. The guard maps such a path to no directory and judges the creation in the session's repository.

### Fixed

- The package contract suite runs again (`tests/codex/contracts/skill_frontmatter.py` restored).

### Upgrade

Upgrade the plugin, restart every Claude Code session, and re-run `install --host codex|hermes` for the guard copy under `~/.magos/guard`.

## 1.0.0

Commit `74bf82f`; no tag. Do not install or pin it: its guard has the Windows Python 3.13+ bypass fixed in 1.0.1.

- The package is renumbered from 3.4.0 to 1.0.0 and installs as the plugin `magos` from the Claude Code, Codex and Hermes plugin marketplaces (`.claude-plugin/`, the root `plugin.json`, `plugin.yaml` and `__init__.py`), with the entry skill `skills/git-orchestrator`; Claude Code also loads a clone in `~/.claude/skills/magos` as the plugin.
- `/GitSweep`: `/GitConverge`, then the lease-guarded deletion of merged remote branches.
- The lane guard: a branch or worktree needs a registered file manifest before it is created, and a creation that overlaps another lane is denied (Claude Code plugin hooks, generated Codex and Hermes entries, and the opt-in `reference-transaction` backstop).
