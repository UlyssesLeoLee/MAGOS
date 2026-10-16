# Technical Design: `scripts/magos_guard.py`

Source: `scripts/magos_guard.py`

Source-SHA256: `2b6f409215efa0d53d4d721d46dee18cb048ddfec17bedc4c6c2c5fdfae2970a`

## Responsibility

`magos_guard.py` is the lane guard of the MAGOS package. It is a single stdlib-only Python 3.9+ file that makes the
rule "a lane is a registered file manifest before it is a branch" enforceable instead of advisory.

The guard stops the lane that is being created, never a lane that already exists:

- A new branch or worktree must have a planned file manifest registered before the creating command runs.
- If any planned file overlaps a file that another branch, worktree or declared lane has changed, is changing or has
  declared, the creation is denied before it happens and every conflicting branch and worktree is named.
- Existing branches and worktrees are only read. No hook denies a write, commit or merge inside an existing lane.
- "Changed" is measured against the integration target. Every worktree contains every file; a lane claims a file only
  if it differs from the target in that file (committed, staged, unstaged, untracked or in progress) or declared it.

The file holds seven cooperating parts.

1. **Manifest and overlap engine.** Entries are normalised (NFC, case-folded, separators unified, trailing dots and
   spaces stripped) and compared with an exact glob-intersection dynamic programme at character level and at path level.
   A `**` segment matches any number of directories; `*` and `?` never cross `/`; brackets are ordinary characters.
   Entry-versus-path and entry-versus-entry use the same function, so declared manifests of lanes that do not exist yet
   collide with each other.
2. **Evidence gatherer.** A Git runner (argv lists, scrubbed environment, `-z` machine formats, per-call timeout and a
   total deadline that every Git call of one hook invocation shares) enumerates claimants: every non-bare worktree,
   every local branch not merged into the target, every unmerged remote-tracking branch, and every open claim.
   Committed evidence is the three-dot diff against each merge base minus content the target already holds; a detached
   worktree contributes the commits of its own HEAD, and a detached worktree at the lane's own registered path is the
   lane itself and is not compared. Uncommitted evidence is `status --porcelain=v2 -z --untracked-files=all` (a rename
   claims both names). A merge, rebase, cherry-pick or revert in progress is a warning; `git am`, unreadable operation
   metadata or a locked worktree that is missing on disk is unknown; a branch with no history in common with the target
   is ignored with a warning because a merge could not collide. Bare repositories and submodules are opened like any
   other repository. A Git call that exits non-zero without writing to stderr is reported with its exit code
   (`git <args>: exit code N`).
3. **Claim store.** `<git-common-dir>/magos/claims/<branch>.claim` files, written under an OS file lock with a
   temporary file and `os.replace`, plus an append-only `audit.log`. The store is shared by all worktrees, is never part
   of a work tree and is not carried by fetch, push, clone, bundle or mirror. Every claim carries a format number; the
   guard reads format `CLAIM_FORMAT = 1` and refuses to act on a claim written in a newer format instead of misreading
   it.
4. **Command detector.** A lexer for bash, PowerShell and cmd that unwraps `bash -c`, `pwsh -Command`,
   `-EncodedCommand`, `cmd /c`, `env`, `sudo`, `xargs` and similar wrappers (depth 3), tracks `cd` and `git -C`, and
   recognises lane-creating git commands and harness tools. Dynamic words (`$x`, backticks, `%x%`) in a lane-creating
   position are treated as unparseable. The script a shell runs is the `-File` value or the first readable file among
   the first four candidates after option values. Every `git` word's subcommand is checked against the git aliases.
   Command text longer than 200,000 characters is not inspected: it counts as an unparseable creation and, once claims
   or the git layer exist, as a protected command. Every pattern runs in time linear in the command length.
   The detector also records the repository each git invocation acts on:
   - A repository redirect (`--git-dir` or `GIT_DIR`, spellings under Public Contract) is resolved per git invocation,
     as Git resolves it: a relative value is joined to the directory that invocation runs in (the shell directory after
     every earlier `cd` and after every `-C` of the invocation, whatever the option order), not to the directory where
     an exported variable was assigned. The result is carried as the creation's `gitdir`; relative worktree paths still
     resolve against the directory the invocation runs in, never against the redirect. A redirect whose value is
     dynamic or cannot be resolved marks the repository unknown. A removal of the variable ends a redirect recorded
     earlier in the command line, so later invocations are judged in the directory they run in, as Git then finds its
     repository there: `unset GIT_DIR`, `export -n GIT_DIR`, `Remove-Item Env:GIT_DIR`, `$env:GIT_DIR = $null` and
     `$env:GIT_DIR = ''` for every later invocation, and `env -u GIT_DIR` for the invocation it wraps. `--work-tree`
     and `GIT_WORK_TREE` alone do not change the judged repository, because Git writes the ref into the repository it
     finds from the working directory.
   - A `cd`, `pushd`, `chdir`, `Set-Location` or `sl` to a directory that does not exist when the hook runs leaves the
     shell where it was, so later commands are judged in that prior directory and the creation is marked unresolved; a
     later relative `cd` keeps the prior directory. This holds on every platform, for absolute, relative, drive and
     POSIX-rooted targets and for `;`, `&&` and newline separators.
   - Git Bash spellings (`/c/Users/x`, `//c/x`) map to drive paths on Windows. A POSIX-rooted spelling that cannot be
     mapped to a drive (`/does/not/exist`) resolves to no directory and follows the missing-directory rule; the guard
     never classifies these spellings with `os.path.isabs`, whose Windows result differs from Python 3.13 on.
5. **Host hook entry.** `hook <claude|codex|hermes> pre-tool` reads one PreToolUse payload from stdin and prints either
   `{}` (allow) or one deny object that carries the full conflict message. The hooked tools are named in one constant:
   the shell tools `Bash`, `PowerShell`, `Monitor`, `terminal`, `shell` and `local_shell`, every MCP tool whose short
   name (the part after the last `__`) is `run_in_terminal`, `terminal`, `shell`, `exec_command`, `execute_command` or
   `start_process`, and the worktree-creating tools (`EnterWorktree`, `Agent`, `Task` and `Workflow` with worktree
   isolation, and the MCP session tools named `start_session`, `worktree`, `branch` or `hand_off_to_session`). A shell
   tool is inspected when `tool_input.command` is a string; an argv list from Codex is turned into one command line.
   The session directory is `tool_input.workdir`, else `tool_input.cwd`, else the payload's `cwd`, else the process
   directory.
6. **Git layer.** A pure POSIX `sh` `reference-transaction` hook, embedded as a constant and written by `arm`. It needs
   no Python and vetoes the creation of any `refs/heads/*` name that has no claim, whatever tool ran Git. A branch
   rename or copy (`git branch -m/-M/-c/-C`) writes the new ref outside a reference transaction, so the git layer does
   not see it; the host hook denies the literal forms.
7. **Version, installer and doctor.** `GUARD_VERSION` is the single version constant of the guard (1.0.2) and equals
   the package version. `version` reports the running guard; `install` keeps the user-level copy that the Codex hook
   (and the Hermes hook when the Hermes plugin is absent) runs, and records where the copy came from; `doctor` checks
   the interpreter, Git, the copy, the repository and the backstop.

## Dependencies

Upstream: Python 3.9+ standard library only (`argparse`, `base64`, `getpass`, `hashlib`, `json`, `os`, `re`, `shlex`,
`shutil`, `subprocess`, `threading`, `unicodedata`, `concurrent.futures`, `msvcrt` or `fcntl`). On Windows the module
sets `NoDefaultCurrentDirectoryInExePath=1` in its own environment at import, before any subprocess starts, so `git`
and every other child program are never resolved from the hook's working directory. Git 2.36+ (`status --porcelain=v2`,
`worktree list --porcelain -z` (2.36), `rev-parse --path-format=absolute` (2.31), `for-each-ref --merged`,
`reference-transaction`); `doctor` reports an older Git. No network access, no `fetch`, no `push`.

Interpreters: the minimum is Python 3.9; the hooks run under whatever interpreter the launcher finds (`py -3`, `python3`
or `python`; CPython 3.14 on the reference machine), so path handling never depends on version-specific results of
`os.path` functions.

Downstream callers:

- `hooks/hooks.json` (Claude Code plugin hook wiring, loaded from the plugin root next to `.claude-plugin/`) and
  `hooks/run-guard.cmd` (polyglot launcher) call `hook claude pre-tool`. The matcher of the non-strict group equals the
  one `host_snippet('claude')` builds from the hooked-tool constant:
  `^(Bash|PowerShell|Monitor|Agent|Task|Workflow)$|^mcp__.*(start_session|worktree|branch|hand_off_to_session|run_in_terminal|terminal|shell|exec_command|execute_command|start_process)`;
  the strict group matches `^EnterWorktree$`.
- `hooks/run-guard.cmd`: the cmd half sets `NoDefaultCurrentDirectoryInExePath=1` right after `setlocal` and tries
  `py -3`, then `python`. The POSIX half exports the same variable, locates itself with `${0%/*}`, reads stdin once and
  runs the guard directly with each candidate interpreter (`python3`, `python`, `py -3`), moving to the next candidate
  only on exit 127, exit 9009 or the Windows Store stub. A missing script, no Python or a non-zero guard exit prints a
  warning that names the absolute guard path and a host-neutral way to stop the guard.
- The user-level Codex and Hermes hook entries generated by `install` call `hook codex|hermes pre-tool`. The Hermes
  entry runs the Hermes plugin's own launcher (`<hermes home>/plugins/magos/hooks/run-guard.cmd`) when that file
  exists, else the copied launcher.
- `references/lane-split.md` and `SKILL.md` tell agents to run `check`, `plan`, `list` and `release`; `version` is
  read-only and agents may run it as well.
- `/GitIntegrate`, `/GitRecon`, `/GitCleanup`, `/GitConverge` and `/GitSweep` read or release claims through `list` and
  `release` as `references/commands.md` describes; the read-only commands never write claims.
- Package manifests: `plugin.json`, `.claude-plugin/plugin.json`, `plugin.yaml`, `SKILL.md` (`metadata.version`),
  `skills/git-orchestrator/SKILL.md` (when it states a version) and line 3 of `references/commands.md` carry the same
  version as `GUARD_VERSION`; a contract test reads all of them. `__init__.py` registers the skills only.
  `scripts/sync_hosts.py` copies `SKILL.md`, `references/*.md` and the skill adapters, never the guard, so `install`
  copies the guard to `~/.magos/guard/` for the hosts that run it outside the plugin directory.

## Public Contract

Invocation: `py -3 -X utf8 -B scripts/magos_guard.py <command> [options]` (`python3` on POSIX). Global options anywhere:
`--repo DIR` (default cwd), `--lang zh|en` (default `zh`, environment `MAGOS_LANG`), `--json`. Options are never
abbreviated (every parser is built with `allow_abbrev=False`), so `--rep` is a usage error. Input is read as bytes
(UTF-8, BOM tolerated); output is UTF-8.

Commands an agent may run: `check`, `plan`, `list`, `release`, `doctor`, `version`. Commands only the user runs:
`override`, `arm`, `disarm`, `install`. The host hook recognises a user-only command whatever the global options before
it look like: after the `magos_guard` word it skips a `--opt=value` word, a prefix of `--repo` or `--lang` together with
its value, and a prefix of `--json`, and tests the first remaining word.

- `check --branch B (--paths P... | --manifest FILE|-) [--target T]`: read-only verdict, no lock, writes nothing.
- `plan --branch B (--paths P... | --manifest FILE|-) [--worktree PATH] [--amend]`: judges against the resolved
  integration target (the one creation is checked against) and gathers evidence outside the lock, takes the lock,
  re-reads the claims, checks the branch name again against them, judges, writes `claims/B.claim` atomically and appends
  an audit line. Identical entries are a no-op (exit 0). Different entries need `--amend` (exit 14 otherwise); an amend
  is judged with the lane's own claim excluded, and a removal-only amend skips the overlap check. A branch that already
  exists with no open claim is refused (exit 15). A `--worktree` value that contains a control character is refused
  (exit 12). On success it prints the creation command, for example `git worktree add "<path>" -b <B> <target>`.
- `list [--drift] [--json]`: each claim as `planned` (no branch yet), `active` (unmerged work, a workspace, or a fresh
  branch at the target tip or the plan's base) or `idle` (integrated: merged, moved beyond the plan's base and the target
  tip, no worktree). An idle claim stops blocking other lanes. `--drift` reports files in the lane's footprint matched
  by none of its entries; it never denies. Claims the guard cannot use are listed as well: `unreadable <file>` for a
  file that does not parse and `newer-format <branch> (v=N): upgrade this guard` for a claim of a newer format;
  `--json` gives them as rows with state `unreadable` (with `path`) or `newer-format` (with `branch` and `v`).
- `release --branch B [--reason R]`: finds the claim by the folded name of B among the parsed claims and deletes the
  file of the stored canonical branch name after confirming that its real path lies inside `<store>/claims`; the
  refusal for unmerged work therefore holds for every spelling of B. Refused with exit 16 while the branch has unmerged
  work or its worktree has uncommitted changes, with the message "release refused: the branch has unmerged work or its
  worktree has uncommitted changes"; a merged lane whose clean worktree is still there can be released. A claim written
  in a newer format is refused with exit 16. A claim file that cannot be parsed is removed by `release` only when it is
  the claim file of B, appears in the store's list of unreadable files and lies inside `<store>/claims`; otherwise
  `release` prints `no open claim for B` and exits 0.
- `override --fingerprint FP --reason R`: exits 2 unless FP is the 12 lowercase hex digits a denial prints; refuses
  (exit 17) unless stdin and stdout are a real console; the user retypes the fingerprint; writes a one-shot record valid
  for one hour. Only `plan` reads override records: the next `plan` whose denial has the same fingerprint consumes the
  record and stores the fingerprint in the claim's `override` field. The host hook honours only that field, so a re-plan
  is required after an override, and the deny text says so.
- `hook <host> pre-tool`: the PreToolUse entry; it also guards `git worktree add --detach` and `<path> <commit>`, whose
  lane is keyed `detached/<directory name>`. Allow is `{}` with exit 0. Deny is exactly one ASCII-escaped JSON object on
  stdout, exit 0:
  `{"decision":"block","reason":MSG,"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":MSG}}`.
  A deny is never an exit code. Stderr stays empty except for one warning line when engagement could not be decided
  (Invariant 3) and the warning of an internal error on a call that is not a lane creation (Invariant 8). An
  auto-named creation (a tool that names the branch or worktree itself) is denied `UNPLANNABLE` with the instruction to
  plan the branch `worktree-<name>` first and then call `EnterWorktree name=<name>`, or to run `git worktree add`
  directly; `EnterWorktree name=N` creates the branch `worktree-N`.
- `arm [--lang L] [--dry-run]`: needs a real console (exit 17 otherwise, except `--dry-run`). Writes
  `<hooks dir>/reference-transaction` (a foreign hook is chained as `.magos-prev`), `<store>/ARMED`, `lang` and `guard`.
  `guard` holds the command the backstop's deny message prints: the command that runs the copy under the guard home
  (`~/.magos` or `MAGOS_HOME`) when that copy exists, else the running script. Before it sets `maintenance.pack-refs.enabled` and `gc.packRefs` to
  `false` for the repository, it records their previous local values (or that they were unset) in
  `<store>/arm-config.json`; an existing record is kept, so a re-run never records its own `false`. It can be re-run
  over its own hook. Refuses (exit 3, checked before the console) when `core.hooksPath` is set, hook directories differ
  across worktrees, or `.magos-prev` already exists next to a hook that is not MAGOS's. Idempotent.
- `disarm [--dry-run]`: needs a real console except with `--dry-run` (exit 17 otherwise); removes `ARMED`, deletes the hook if it is MAGOS's and restores
  `.magos-prev`; restores both settings from `arm-config.json` (unsetting a key that was unset) and deletes the record;
  without a record both settings stay as they are; keeps claims and audit.
- `install --host claude|codex|hermes [--dry-run] [--home DIR] [--allow-downgrade]`: needs a real console except with
  `--dry-run` (exit 17 otherwise). It compares `scripts/magos_guard.py` and `hooks/run-guard.cmd` with the copies in
  `<home or ~/.magos>/guard/{scripts,hooks}/`. When both copies are byte-identical to the sources it prints
  `guard copy unchanged (<version>)` and copies nothing. When the copy's `GUARD_VERSION` (read from the copy's bytes and
  compared as a tuple of integers) is newer than the source's, it refuses with exit 18 unless `--allow-downgrade` is
  given. Otherwise it writes each file to a temporary name in the destination directory and moves it into place with
  `os.replace`, then writes `guard/VERSION.json` last in the same way, and prints `guard copy <old> -> <new>` (`none`
  when there was no copy). `VERSION.json` records `{version, sha256, source, installed_at}` of the copied guard. Each
  file is replaced whole or not at all: a failed write removes its temporary file, leaves the previous file and
  `VERSION.json` in place and exits 11. `--dry-run` prints what it would copy and the snippet and writes nothing. It
  writes the exact host snippet to `guard/generated/<host>.json|yaml` and prints it. It never edits
  `~/.claude/settings.json`, `~/.codex/hooks.json` or Hermes config. The Hermes snippet is valid YAML on every platform
  (matcher `terminal`, timeout 25, `fail_closed: true`); its command parses to `"<launcher>" hook hermes pre-tool` on
  Windows and to `sh '<launcher>' hook hermes pre-tool` elsewhere, where the launcher is
  `<hermes home>/plugins/magos/hooks/run-guard.cmd` when that file exists (Hermes home: `HERMES_HOME`, else
  `%LOCALAPPDATA%/hermes` on Windows, else `~/.hermes`), else the copied launcher. Only Claude's EnterWorktree group
  carries `--strict`; for the other entries `--strict` is a documented opt-in.
- `doctor`: prints the running guard's version, the first 12 hex digits of its sha256 and its path; checks Python
  (3.9+) and Git, and reports `git X.Y TOO OLD for the lane guard (need 2.36+)` below 2.36. Before it looks for a
  repository it compares the copy under the guard home (`~/.magos` or `MAGOS_HOME`), when there is one, with the running guard by the copy's
  `GUARD_VERSION` and sha256; a difference is reported with the exact refresh command
  (`<guard command> install --host <host>` for each host that has a generated snippet). Outside a repository it then
  reports that the guard is inert there. In a repository it checks mode, hook uniformity, hook content, claim parsing
  (unreadable and newer-format claims), orphan claims, `core.hooksPath` and the backstop command recorded in
  `<store>/guard`: a recorded script that does not exist is reported as missing with the re-arm command, and a hook
  that differs from this version is reported with the re-arm command (`<guard command> arm`, for the user's own
  terminal). In an armed repository whose hook equals this version's it proves the backstop by trying
  `git branch __magos_selftest`: only a non-zero exit
  whose stderr contains `MAGOS` counts as a veto; any other failure, or a `__magos_selftest` branch or claim that already
  exists, is reported as `self-test inconclusive` with Git's message; a branch that is created is deleted and reported
  as a failed self-test. Exit 1 on any problem, 0 otherwise.
- `version [--json]`: read-only, works inside and outside a repository; prints `GUARD_VERSION`, the sha256 of the
  running file, its path and the Python version; `--json` prints `{version, sha256, path, python}`. Exit 0.

Repository of a creation. Each creation is judged in its own repository: the redirect target when the invocation has
one, else the directory the shell is in at that point (after `cd`, `pushd`, `Set-Location` and `git -C`), else the
session directory. The mode, engagement, claims and evidence are those of that repository, so a claim in the session's
repository never allows a creation redirected into another repository. Redirect spellings: `git --git-dir <p>`,
`git --git-dir=<p>`, a `GIT_DIR=<p>` prefix assignment, `env GIT_DIR=<p> git`, a standalone `GIT_DIR=<p>`,
`export GIT_DIR=<p>` and `export GIT_DIR` after an assignment, PowerShell `$env:GIT_DIR='<p>'` or
`$env:GIT_DIR = '<p>'`, and cmd `set GIT_DIR=<p>` (also inside `cmd /c`). A prefix or `env` assignment applies to its
own invocation; an exported, PowerShell or cmd assignment applies to every later git invocation of the command line,
each resolving a relative value against the directory it runs in, until a removal of the variable (see Command
detector) ends it. A standalone POSIX-shell `GIT_DIR=<p>` that is not exported reaches git only when the shell already
exported `GIT_DIR`, which the guard cannot see; a later git invocation is therefore judged in both repositories, the
redirect target and the directory it runs in, and the stricter verdict applies. A creation whose redirect is dynamic or does not open as a repository is denied
`UNPARSEABLE` whatever the mode and engagement of the session repository, with the message "the repository is
redirected by --git-dir/GIT_DIR and cannot be resolved; use git -C <repo>". A `cd` or `-C` whose target is dynamic leaves the repository unknown as well:
the creation is judged in the session directory's repository. A creation left in a prior directory by a `cd` to a
missing directory is judged in that prior directory and marked unresolved; when the prior directory is not a
repository nothing is judged. In both cases an engaged creation is denied `UNPARSEABLE` (`UNPLANNABLE` for an
auto-named creation).

Errors. In every command except `hook`, a Git failure writes `MAGOS guard: <code>: <text>` and an internal error
writes `MAGOS guard internal error: <exception type>: <text>` to stderr; both exit 11 (`doctor` reports a Git that
cannot run its version probe as a problem and exits 1); with `--json` it also prints
`{"decision":"deny","code":"UNKNOWN","unknowns":[{"code":<GIT_MISSING|GIT_FAILED|BUDGET_EXCEEDED|INTERNAL_ERROR>,"text":...}],"message":...,"exit_code":11}`
on stdout.

Exit codes: 0 allow, registered, ok or unchanged; 1 `doctor` found a problem, or a usage error of `hook` (a failure the
launcher maps, never a deny); 2 usage error of any other command, not a git repository, or a malformed fingerprint; 3 arm refused; 10 CONFLICT, NO_MANIFEST, UNPLANNABLE, UNPARSEABLE or PROTECTED; 11 UNKNOWN (also
any engine exception, an exhausted budget or a claim in a newer format: plan and check fail closed); 12 INVALID_MANIFEST
(also an invalid branch name or a `--worktree` with a control character); 13 LOCK_TIMEOUT (30 s); 14 LANE_EXISTS;
15 BRANCH_EXISTS; 16 BLOCKED (release); 17 CONSOLE_REQUIRED (`override`, `arm`, `disarm`, `install`);
18 DOWNGRADE_REFUSED (`install`).

Claim file (LF; the git layer reads only line 1, which is exactly `state=active` in every format): `state=active`,
`v=<format>`, `branch`, `worktree`, `target`, `base`, `created`, `by`, `override`, then one `entry=<raw entry>` line per
manifest entry; a missing optional field reads as empty and a missing `v` reads as 1. The reader keeps the known keys;
a key it does not know is kept aside and written back unchanged when a claim of the same format is amended; a key line
never replaces the entry list, the state or the format, and a repeated scalar key makes the file unreadable. A claim
whose `v` is greater than `CLAIM_FORMAT` is too new: every judgement reports `UNKNOWN` `CLAIM_NEWER_FORMAT`
("<branch> was written by a newer MAGOS (v=N); upgrade this guard", naming the file when it has no `branch` line),
`release` refuses it with exit 16, and `plan` and `plan --amend` never overwrite it. Within one format only additive keys
are allowed; a change an older reader must not ignore raises `CLAIM_FORMAT`. Values never carry a control character:
a branch, worktree or entry with one is refused, and each control character in `by` (the Git user name, e-mail and
login) is replaced with a space. A claim file is written only where no file exists or where the claim of the same folded
branch is, and a failed write leaves no temporary file behind. Branch names that would share a claim file on Windows
are refused: a path component ending in `.` or a space, or ending in `.claim`; claims already stored under such names
stay readable. A worktree path is compared case- and separator-insensitively where the platform is. Store layout:
`<git-common-dir>/magos/{ARMED,lang,guard,arm-config.json,claims/,override/,audit.log,lock}`.

Verdict (`--json`): `{decision, code, conflicts:[{key, branch, worktrees, planned, evidence:[{kind committed|uncommitted|declared,
files, matched, theirs}]}], unknowns, warnings, target:{name,sha,confidence}, fingerprint, overridden, message, exit_code}`.
The fingerprint is the first 12 hex digits of SHA-256 over the canonical denial (the planned lane's key, claimant keys,
evidence kinds and files, the other lanes' declared entries that overlap, unknown codes, target sha); the planned lane's
own manifest entries are not part of it, so changing the repository voids an override.

Invariants:

1. Creation is denied before it happens; a denial leaves no branch, worktree directory or administrative directory.
2. Existing lanes are never stopped, modified, stashed, merged or moved; the guard only reads them.
3. Unknown is not safe: an ambiguous target (or a `--target` that does not resolve), `git am`, unreadable operation
   metadata, a locked worktree missing on disk, more than 120 unmerged local branches, an unreadable claim, a claim in a
   newer format, a Git failure or an exhausted budget (18 s per command or hook call, 30 s per Git call) deny creation
   in `plan`, `check`, an armed repository and for a named worktree. In auto mode, when the engagement check itself
   fails, the host hook treats a branch-only creation as engaged only when the repository holds an open claim (then it
   is judged), allows it otherwise, and denies an auto-named creation (`UNPLANNABLE`, with the failure as the reason);
   in each of these cases it writes a warning on stderr. Opening the repository is the one step that does not fail
   closed: a failure of `rev-parse` there, other than a missing Git or an exhausted budget, reads as "not a repository".
4. Hard overlap is a direct path, directory prefix, glob, rename side, case or Unicode collision, or a declared manifest
   against a manifest. Warnings never deny: inferred target, remote freshness, operation in progress, repository not armed.
5. The only writes are claim and audit files (under the lock), override records, and the files `arm` (including
   `arm-config.json`), `disarm` and `install` (including `VERSION.json` and the generated snippet) print. `check`,
   `list`, `hook` and `version` never write.
6. Engagement: ARMED (marker file) guards every new branch and worktree; AUTO (default) always guards named worktree
   creation and guards branch-only or auto-named creation only when another lane exists; OFF
   (`git config --local magos.guard off`) silences the host hooks of that repository. Mode and engagement are read from
   the creation's own repository. `MAGOS_GUARD=off` is read from the host process environment only.
7. Tamper protection is best-effort matching of words and common writer commands. User-only subcommands (whatever the
   spelling of the global options before them) and `git config magos.*` writes are denied by the host hook in every
   repository and outside any repository. Edits of the guard's state are denied once the repository is armed or holds a
   claim: `core.hooksPath`, `GIT_CONFIG_*`, worktree config, and writers or redirects aimed at `.git/hooks`, `.git/refs`,
   `.git/HEAD`, `.git/config`, `packed-refs`, `.git/magos`, `.magos`, the absolute path of the session repository's
   `<git-common-dir>/magos` (in any separator or case spelling the platform folds) and the absolute path of the guard
   home (`~/.magos` or `MAGOS_HOME`). Other spellings, interpreters and file tools are the limit stated in
   `references/lane-split.md` section 12.
8. Failure handling: any internal error denies only a call that was already recognised as lane creation; otherwise the
   hook prints `{}` and a warning on stderr. The launcher turns a missing script, missing Python or a non-zero guard exit
   into exit 2 for the strict group (EnterWorktree) and a warning with exit 0 for all other tools and hosts, Hermes
   included; Hermes' `fail_closed: true` blocks only a launcher that cannot be started or that times out. The warning
   names the absolute guard path and says how to stop the guard on any host (`MAGOS_GUARD=off` in the host environment
   or removing the MAGOS hook entry; for Claude, `claude plugin disable magos`).

## Change Notes

Version 1.0.2 is a security release of the guard. Relative to the 1.0.1 product it:

- judges a creation in the repository that a `--git-dir` or `GIT_DIR` redirect names (resolved per invocation, as Git
  resolves it, and ended by a removal of the variable), and denies a redirect it cannot resolve with its own message;
  `--work-tree` and `GIT_WORK_TREE` alone leave the judged repository unchanged;
- judges the commands after a `cd` to a missing directory in the prior directory, on every platform and for every
  target spelling;
- inspects the `Monitor` tool and shell-capable MCP tools, reads `tool_input.cwd`, and builds the Claude matcher from
  the same tool list;
- never resolves `git`, `py` or `python` from the hook's working directory on Windows (guard and launcher);
- recognises user-only commands whatever their global option spelling, rejects abbreviated options, and gates `install`
  behind a real console;
- denies an auto-named creation when AUTO engagement cannot be decided, with a stderr warning;
- applies an override only through `plan`;
- prints a JSON deny object for Git and internal errors under `--json`, and names Git's exit code in a silent failure;
- hardens the claim store: canonical `release`, Windows alias names, control characters, key whitelist, name check under
  the lock, the claim format gate and visible unusable claims in `list`;
- adds `version`, the version-aware atomic `install` with `VERSION.json` and exit 18, the Hermes plugin launcher in the
  Hermes snippet, and valid Hermes YAML on every platform;
- extends `doctor` with the running version, the copy comparison, the Git 2.36 check, the MAGOS-only self-test and the
  recorded backstop path; `arm` records and `disarm` restores the pack-refs settings;
- matches the absolute paths of the store and the guard home in the tamper filter, tells an agent denied an auto-named
  worktree to plan `worktree-<name>` before `EnterWorktree name=<name>`, and gives uncommitted changes as the release
  refusal reason.

Compatibility: claim files of format 1 written by 1.0.0 and 1.0.1 are read unchanged, and line 1 of every claim stays
`state=active`, so the git layer reads old and new claims alike. The Codex and Hermes copies under `~/.magos/guard`
receive 1.0.2 only when the user re-runs `install`; `doctor` reports a stale copy with the refresh command, and armed
repositories are refreshed by re-running `arm`. Exit code 18 is new. A Hermes entry that points at the Hermes plugin
launcher follows `hermes plugins update`. `references/lane-split.md` is a flat reference shipped to Codex and Hermes by
the `references/*.md` glob. `hooks/hooks.json` and `hooks/run-guard.cmd` sit at the repository root, outside
`.claude-plugin/`. The root `description` is 1017 characters. The git layer is opt-in per repository (`arm`) and the
Codex and Hermes entries are generated, never merged automatically. Known limits are stated in
`references/lane-split.md` section 12: hooks read command text; the git layer cannot see `-c core.hooksPath`, direct
`.git/refs` writes, libgit2, clones or a branch rename or copy (`git branch -m/-c`); harness-created worktrees are
covered only by the git layer; input sent to a running shell through Hermes `process_manage` and edits made with file
tools are not inspected; the tamper filter is best-effort; claims are per clone; and overrides are not access control.
