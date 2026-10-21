# Explicit Command Contracts

This reference defines the command-layer behavior for `multi-agent-git-orchestrator` v1.0.3.

These are **semantic command intents**. Canonical names use a leading `/`. A host may expose them as slash commands, palette actions, prompt aliases, or plain-text invocations. If slash commands are unsupported, accept the same name without `/`. The behavior must remain the same.

## Argument and Help Behavior

All eight commands accept `--help`. When it is present, show that command's usage, argument descriptions, defaults, and examples, then stop before inspecting or changing a repository. `--help` takes precedence over other arguments.

**Reply language.** All eight commands accept `--lang <language>`. It selects the language of everything the command says to the user: help text, questions, errors, reports (including the final report of a write command after a long run), and recommendations. When it is absent the reply is in Chinese (简体中文). The value is the next token: a language name or a common code (`English`, `en`, `日本語`, `ja`, `Français`); put a multi-word name in quotes. The option may appear anywhere among the arguments and may be combined with `--help`; help is then shown in the requested language, with flags and examples left untouched. Never translate command names, option names, branch or worktree names, paths, SHAs, Git commands, or status codes such as `BLOCKED_DIRTY`; a short gloss in the reply language next to a code is fine. Remove `--lang` and its value from the arguments before any other parsing, so it never becomes part of a goal, target, or branch name. If `--lang` has no value, or the value is not a language, explain the problem (in Chinese) and show the usage without executing the command.

Recognize only the options listed for each command. For an unknown option or a required option value that is missing or invalid, explain the issue and show the relevant usage without executing the command. If a required positional target is missing, ask the user for it. Host adapters should preserve the supplied argument text and route `--help` to this reference.

Host entry points are Claude Code `/GitRecon`, Hermes `/git-recon`, and Codex `$git-recon` (use the corresponding command name for the other seven). Append the same arguments after the host-specific entry point.

## Host Adapter Contract

Each host reaches the same canonical command through its own adapter. Adapters differ only in how they receive arguments and locate shared files; the command behavior below is identical.

| Host | Adapter | Arguments arrive as | Shared files are located by |
|---|---|---|---|
| Claude Code | `commands/Git*.md`, loaded as `/magos:GitXxx` by the `magos` plugin (marketplace install through `.claude-plugin/marketplace.json`, or a clone in `~/.claude/skills/magos`), or copied into `~/.claude/commands/` as `/GitXxx` | `$ARGUMENTS` in the command template | loading the orchestrator skill (listed as `magos`, `MAGOS`, `multi-agent-git-orchestrator`, or `MAGO-Skill`) |
| Codex | `skills/git-*/SKILL.md` + `agents/openai.yaml` | the text after `$git-*` in the user's message | resolving `../../SKILL.md` and `../../references/*.md` relative to the adapter's `SKILL.md` |
| Agent Plugins client | `skills/git-*/SKILL.md`, found through the root `plugin.json` (Codex marketplace installs use it; Hermes `plugins install` uses `plugin.yaml` instead), invoked as `$magos:git-*` (Codex) or `/magos:git-*` (Hermes) | as the client passes skill input | resolving `../../SKILL.md` and `../../references/*.md` inside the plugin root; the root `SKILL.md` is not a plugin skill. Only discovery is verified. The write adapters act only on an explicit invocation, which a plugin client may not be able to express (Hermes plugin skills have no `/git-*` command and no `[Skill directory: ...]` line) |
| Hermes | `skills/git-*/SKILL.md` | the instruction Hermes appends after the skill content ("...alongside the skill invocation:" for one command, `User instruction:` for stacked commands) | the absolute `[Skill directory: ...]` path plus `../..`, read with the file or terminal tool (the skill viewer rejects `..`), or the root skill `multi-agent-git-orchestrator` and its `references/` files |

Rules for every adapter:

- `skills/` adapters must not read `commands/*.md`; those wrappers contain Claude-specific loading steps.
- Codex adapters set `policy.allow_implicit_invocation: false`, so they run only when selected explicitly; the root skill keeps semantic activation. Hermes has no per-skill switch, so `git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, and `git-plan` refuse to write unless invoked explicitly.
- If the shared rules (`SKILL.md`, `references/commands.md`) cannot be read, read-only commands may continue read-only and report the incomplete installation; `GitIntegrate` must not integrate, `GitCleanup` must not delete, `GitConverge` must not merge or delete, `GitSweep` must not merge, delete, or push, and `GitPlan` must not register a plan, create a branch or worktree, merge, or release a set (preview only).
- An installed package must contain `SKILL.md`, every file under `references/`, and every `skills/git-*/SKILL.md` with its `agents/openai.yaml`, laid out exactly as in this repository, so that the relative paths above resolve. The root `plugin.json` belongs to the Agent Plugins package (the whole repository), not to the Codex and Hermes skills-directory package.

## 1. GitRecon

### Invocation

```text
/GitRecon
/GitRecon --remote
/GitRecon --lang English
/GitRecon --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `--remote` | No | Refresh remote-tracking refs before classification. It does not change branches, worktrees, or commit history. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting the repository. |

Examples: `/GitRecon --remote`, `/GitRecon --help`.

### 中文描述

调查当前 Git 仓库整体状态。主动检查 branch、worktree、HEAD、ahead/behind、dirty、detached、upstream、已合并情况和潜在风险，并生成仓库现状摘要。默认只读，不修改分支、worktree 或提交历史。

### Required behavior

1. Run the Quick Scan from `reconnaissance.md`; when the lane guard is installed, add `magos_guard.py list` (open claims).
2. Deep-scan only branches/worktrees needed to explain risks or topology.
3. Classify worktrees and branches.
4. Report integration-target confidence and remote freshness.
5. Do not mutate repository topology.

`--remote` permits a remote refresh before classification. Report if refresh fails or is unavailable.

### Output

```text
Repository Snapshot
- integration target
- worktrees summary
- branches summary
- remote freshness
- high-risk findings
- unknowns
```

## 2. GitAnalyze

### Invocation

```text
/GitAnalyze <branch>
/GitAnalyze <worktree-path>
/GitAnalyze <target> --remote
/GitAnalyze <branch> --lang English
/GitAnalyze --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `<target>` | Yes | Branch name or worktree path to analyze. |
| `--remote` | No | Refresh remote-tracking refs before analysis. It does not change branches, worktrees, or commit history. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting the repository. |

Examples: `/GitAnalyze feature/auth`, `/GitAnalyze feature/auth --remote`, `/GitAnalyze --help`.

### 中文描述

深入分析指定 branch 或 worktree。调查它与集成分支之间的共同祖先、ahead/behind、独有提交、修改文件、是否已被集成、下游依赖、rewrite 安全性，以及 merge、rebase、cherry-pick、归档或删除等操作的安全性。

### Required behavior

1. Resolve target identity and current HEAD.
2. Establish the integration target or mark it uncertain.
3. Compute ancestry/ahead-behind and unique commits.
4. Inspect worktree cleanliness if the target has a linked worktree.
5. Inspect recorded downstream dependencies and clearly separate inferred semantic risks; include the lane's guard manifest (`magos_guard.py list`) when the guard is installed.
6. Produce an operation-by-operation safety assessment.

### Output

```text
Target
Observed state
Dependencies
Risk findings
Operation safety:
- merge
- rebase
- cherry-pick
- squash/rewrite
- cleanup/delete
Recommendation
```

## 3. GitRecommend

### Invocation

```text
/GitRecommend
/GitRecommend <goal>
/GitRecommend <goal> --remote
/GitRecommend --lang English
/GitRecommend --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `[goal]` | No | Natural-language question or desired outcome. Omit it for general next-step recommendations. |
| `--remote` | No | Refresh remote-tracking refs before making recommendations. It does not change branches, worktrees, or commit history. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting the repository. |

Examples: `/GitRecommend`, `/GitRecommend 哪些分支可以先集成`, `/GitRecommend --remote`, `/GitRecommend --help`.

Example goals:

```text
/GitRecommend 下一步怎么安排3个Agent
/GitRecommend 哪些分支应该先合并
/GitRecommend 给新任务找最合适的worktree
```

### 中文描述

基于当前仓库真实状态给出下一步 Git / 多 Agent 编排建议。主动调查必要的 branch、worktree、依赖和风险，并按优先级建议并行/串行关系、同步顺序、集成候选、阻塞 Lane、下一 Agent 落点和清理候选。

### Required behavior

1. Reuse a reconnaissance snapshot only if it is still fresh; otherwise refresh it.
2. Deep-scan only entities material to the user's goal.
3. Rank recommendations by risk and dependency, not by branch age alone.
4. Each recommendation must include evidence and expected next action; when the lane guard is installed, base lane advice on its open claims (`magos_guard.py list`).
5. Do not mutate repository state.

### Output

```text
Observed facts
Top risks
Recommended next actions (ordered)
Why
Blocked/unknown items
```

## 4. GitIntegrate

### Invocation

```text
/GitIntegrate <lane-or-branch>
/GitIntegrate <lane-or-branch> --strategy auto
/GitIntegrate <lane-or-branch> --strategy merge
/GitIntegrate <lane-or-branch> --strategy squash
/GitIntegrate <lane-or-branch> --strategy cherry-pick
/GitIntegrate <lane-or-branch> --lang English
/GitIntegrate --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `<lane-or-branch>` | Yes | Source lane or branch to integrate. |
| `--strategy <value>` | No | Integration strategy: `auto`, `merge`, `squash`, or `cherry-pick`. Defaults to `auto`. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting or changing the repository. |

Examples: `/GitIntegrate agent/auth`, `/GitIntegrate agent/auth --strategy squash`, `/GitIntegrate --help`.

### 中文描述

安全集成指定 Agent Lane 或 branch。在实际写入集成分支前检查审核状态、commit 依赖、目标分支 freshness、当前 HEAD、验证结果和仓库集成策略；通过门禁后才执行 merge、squash merge 或 cherry-pick，并在集成后重新验证。

### Required behavior

1. Resolve lane/branch and intended integration target.
2. Confirm review/acceptance evidence and validation state.
3. Refresh refs as required by repository policy.
4. Acquire serialized integration ownership or equivalent merge-queue position.
5. Re-check lane HEAD and target HEAD immediately before integration.
6. Select strategy:
   - `auto`: follow repository policy and reviewed acceptance shape;
   - `merge`: whole-lane integration while preserving accepted commits;
   - `squash`: whole-lane delivery as one logical commit when policy allows;
   - `cherry-pick`: only dependency-safe accepted commits; if the accepted commit set is not known, stop and report what is needed.
7. Run post-integration validation.
8. Record source lane/commits and resulting integration commit(s).
9. When the lane guard is installed, run `magos_guard.py release --branch <lane> --reason integrated` after a successful integration.

### Hard stop conditions

Do not integrate when:

- review/acceptance is missing for non-trivial work;
- lane HEAD or integration target changed after approval and required revalidation is incomplete;
- selected cherry-picks have unresolved dependencies;
- protected-branch/repository policy forbids the operation;
- semantic conflict cannot be resolved from requirements/evidence;
- required validation is failing due to the candidate change.

Never convert this command into force-push, destructive reset, or blind conflict resolution.

## 5. GitCleanup

### Invocation

```text
/GitCleanup
/GitCleanup --apply
/GitCleanup --lang English
/GitCleanup --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `--apply` | No | Apply safe local cleanup candidates after rechecking their state. Without it, only show a preview. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting or changing the repository. |

Examples: `/GitCleanup`, `/GitCleanup --apply`, `/GitCleanup --help`.

### 中文描述

调查并整理可安全清理的 branch 和 worktree。默认只生成清理候选清单；只有显式 `--apply` 才实际删除已经证明安全的对象。

### Preview behavior (default)

Classify every relevant cleanup candidate with evidence:

```text
SAFE_CANDIDATE
BLOCKED_DIRTY
BLOCKED_UNIQUE_WORK
BLOCKED_ACTIVE_OWNER
BLOCKED_DEPENDENCY
BLOCKED_NOT_INTEGRATED
BLOCKED_IN_PROGRESS
BLOCKED_IGNORED_FILES
UNKNOWN
```

A branch/worktree is not safe merely because it is old or inactive. The section 6 definitions of **clean**, **in progress**, **active owner**, **Names vs SHAs**, and **Case collisions** apply here unchanged. A case collision is never a gate here: both names are `UNKNOWN`, and the run continues for the other branches. Its **unknown owner** exception does not: a linked worktree with no active-owner evidence and no lane record is `UNKNOWN` ("owner: not recorded"), because the reconnaissance rule `UNKNOWN_OWNER` (do not assume it is free) governs GitCleanup.

- **Never a candidate**: `main`, the integration target, the remote default branch (`origin/HEAD`), any branch the repository documents as long-lived or protected, the invoking worktree (the one that contains the current directory), and its branch. List them under "Not touched", not as blocked.
- `BLOCKED_DIRTY`: the worktree is not clean as section 6 defines it. `git -C <worktree> status --porcelain=v1 --untracked-files=all` must be empty (always pass the flag: `status.showUntrackedFiles=no` hides untracked files, and `git worktree remove` then deletes them), and no `ls-files -v` entry may hide edits (skip-worktree or assume-unchanged while its file exists on disk; entries absent from disk, as in a sparse checkout, do not count).
- `BLOCKED_IN_PROGRESS`: the worktree is in progress, or the branch is named as the one a rebase or bisect in another worktree is working on. A worktree stopped mid-rebase looks clean and detached; removing it orphans the rewritten commits.
- `BLOCKED_IGNORED_FILES`: the worktree holds ignored files (paths listed in full). `git worktree remove` deletes them without asking (for example `.env`). GitCleanup has no override: move or delete them by hand, then run GitCleanup again.
- `BLOCKED_UNIQUE_WORK` also covers a detached worktree whose HEAD is not reachable from any branch or tag.
- `UNKNOWN` also covers both branches when two local branch names are equal ignoring case (section 6, **Case collisions**).

### Apply behavior

`--apply` may clean only `SAFE_CANDIDATE` entries. Re-check each candidate immediately before mutation.

Typical safe operations may include:

```text
git worktree remove <path>
git branch -d <branch>
```

`git worktree remove <path>` removes one linked worktree: never the invoking one, never with `--force`. A prunable entry (directory missing) has nothing on disk to check: it is a candidate only when it is on a branch (not detached) that is otherwise a `SAFE_CANDIDATE`, and a detached prunable entry is `UNKNOWN`. A prunable entry is removed the same way, by its path, for that entry only. If it exits non-zero, keep the branch and report whether the entry is still listed in `git worktree list --porcelain`. Run `git branch -d <branch>` from the invoking worktree after the branch's worktree is gone.

Constraints:

- do not use `git branch -D` by default;
- do not delete dirty worktrees;
- never run a repository-wide `git worktree prune`: it also drops unclassified prunable entries, including detached worktrees whose commits no branch reaches, and orphans those commits;
- never remove the invoking worktree, and never delete `main` or the integration target;
- do not remove a worktree that is in progress or holds ignored files;
- do not remove branches with unique unpreserved commits;
- do not remove dependency-source branches required by active lanes;
- do not treat remote deletion as implied by local cleanup;
- if state changed between preview and apply, skip the candidate and report it.

### Output

```text
Cleanup candidates
Blocked items + reasons
Not touched (main, the integration target, the invoking worktree)
Applied operations (only with --apply)
Skipped items + reasons
Remaining risks
```

## 6. GitConverge

### Invocation

```text
/GitConverge <branch>
/GitConverge <branch> --apply
/GitConverge <branch> --apply --discard-ignored
/GitConverge <branch> --lang English
/GitConverge --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `<branch>` | Yes | Local branch that receives everything. Matched exactly and case-sensitively against `refs/heads/`; it must not be `main`. |
| `--apply` | No | Merge the planned sources into `<branch>`, then delete the merged local branches and their clean worktrees. Without it, only show a preview. |
| `--discard-ignored` | No | With `--apply`, allow removing a worktree that holds ignored files (for example `.env`, `node_modules/`). Without it such a worktree and its branch are kept. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting or changing the repository. |

Examples: `/GitConverge agent/release`, `/GitConverge agent/release --apply`, `/GitConverge --help`.

### 中文描述

把所有本地分支（含 `main`）里 `<branch>` 还没有的提交合并进 `<branch>`，然后只保留 `main` 和 `<branch>` 两个本地分支。默认只预览；只有 `--apply` 才合并并删除。`main` 只作为合并来源，不会被移动、重置或删除；远端分支、tag、detached worktree 不会被改动。

### Definitions

- **target**: `<branch>`, resolved by exact match in `git for-each-ref --format=%(refname) refs/heads`. A name that only matches when case is ignored is rejected with the exact name suggested; `rev-parse` success is not a match (case-insensitive filesystems resolve the wrong case).
- **kept set**: `main` and target. Every other local branch is a **source**; `main` is also a merge source (it is merged and classified, and never deleted).
- **Names vs SHAs**: resolve every branch through its full refname (`refs/heads/<name>`) and record its SHA. Take the SHAs from one `git for-each-ref --format='%(refname) %(objectname)' refs/heads` listing, which reads each ref exactly; `rev-parse refs/heads/<name>` can read another branch's loose ref file on a case-insensitive filesystem. In every git command in this section, `<target>` and `<source>` in a revision argument mean `refs/heads/<name>` or the recorded SHA, never the bare name: a same-named tag wins bare-name resolution (`refname '<name>' is ambiguous`). Merge the recorded SHA.
- **Case collisions**: when two local branch names are equal ignoring case (`Feat` and `feat`), both are `UNKNOWN` whatever else applies (this is decided before the ordered classification below): neither is merged or deleted, because on a case-insensitive filesystem `refs/heads/<name>` can resolve to the other one and `git branch -d` on one can remove both. The report asks the user to make the names distinct safely: run `git pack-refs --all` first (then no name is a loose ref file, so each resolves exactly), rename one with `git branch -m`, and compare both tips with the recorded SHAs. A plain `git branch -m` on a colliding name can give the new name the other branch's tip and delete both old refs. If the target or `main` is one of them, that is a gate failure.
- **Names**: a local branch name is safe to pass to a command only when it consists of ASCII letters, ASCII digits and the characters `.` `_` `/` `+` `-`, and starts with neither `-` nor `+`. A source whose name is not safe is `UNKNOWN` whatever else applies (decided before the ordered classification below, like a case collision): neither merged nor deleted; the remedy is to rename it.
- **Argument safety**: every git command this contract names is run as an argument list, never as a shell string or a PowerShell expandable string, and each ref name, remote name, path and SHA is exactly one argument (an option value that holds one, such as `--force-with-lease=refs/heads/<name>:<sha>`, is part of one argument). Any command printed in a report is printed with each such argument in POSIX single quotes, as a whole (`'refs/heads/<name>'`). The command lines written in this contract are templates for that rule. Section 7 applies it to every command it names.
- **invoking worktree**: the worktree that contains the current directory. It is the only worktree this command writes into or switches.
- **clean**: both hold. (1) `git -C <worktree> status --porcelain=v1 --untracked-files=all` is empty; always pass the flag, because `status.showUntrackedFiles=no` would otherwise hide untracked files. (2) No entry of `git -C <worktree> ls-files -v` is tagged `S` (skip-worktree) or with a lowercase letter (assume-unchanged) while its file exists on disk; status cannot see edits to those files, and `git worktree remove` deletes them. Entries absent from disk (sparse checkout) do not count. Ignored files are not covered by "clean".
- **in progress**: a worktree has a merge, cherry-pick, revert, rebase, am, or bisect underway, or a paused cherry-pick/revert sequence (`MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `sequencer/`, `rebase-merge/`, `rebase-apply/`, `BISECT_LOG`, each located with `git -C <worktree> rev-parse --git-path <name>`; for the main worktree the result is relative to `<worktree>`, so resolve it against that path before testing whether it exists). Check every worktree, including detached ones. A rebase or bisect shows its worktree as `detached`; the branch it is working on is named in `rebase-merge/head-name`, `rebase-apply/head-name`, or `BISECT_START`, and that branch counts as checked out there.
- **active owner**: a worktree that is locked, lies under an agent-harness worktree root (`<main worktree>/.claude/worktrees/`, where Claude Code keeps its session worktrees; `~/.codex/worktrees/`; or a root the repository documents), or has a lane record naming another owner, or holds an open lane-guard claim (`magos_guard.py list`: `planned` or `active`). Clean is not proof that nobody is using it.
- **unknown owner**: a linked worktree with no active-owner evidence and no lane record. GitConverge may remove it: this is the one exception to the reconnaissance rule "UNKNOWN_OWNER: do not assume it is free", and `--apply` is the authorization. The plan must list such a removal as "owner: not recorded".

### Acceptance rule

`/GitConverge <branch> --apply` is the user's explicit acceptance of the source tips listed in the plan that run records and puts in its report, or in a GitConverge preview earlier in the same conversation. It replaces per-lane review for exactly those tips and meets the freshness gate for them. It does not permit writing any branch other than `<branch>`, and it never moves, resets, or deletes `main`.

### Classification

Every source gets exactly one **merge status**, decided in this order (the first match wins):

```text
BLOCKED_UNRELATED_HISTORY     no merge base with target (for example an orphan gh-pages); never merged, never deleted
BLOCKED_IN_PROGRESS           checked out in a worktree that is in progress; its tip is stale, so it is neither merged nor deleted
CONTAINED                     already in target (`git merge-base --is-ancestor <sha> refs/heads/<target>`); delete only
MERGE                         unique commits to merge, then delete
UNKNOWN                       a needed fact could not be established, or the name is not safe (**Names**); neither merged nor deleted
```

and zero or more **delete blockers**. A delete blocker never stops a `MERGE` source from being merged; it only keeps the branch and its worktree:

```text
BLOCKED_DIRTY                 its worktree is not clean
BLOCKED_LOCKED                its worktree is locked
BLOCKED_ACTIVE_OWNER          its worktree has an active owner, or it is checked out in the main worktree that is not the invoking one
BLOCKED_IGNORED_FILES         its worktree holds ignored files (paths listed in full); lifted by --discard-ignored
BLOCKED_SUBMODULE             its worktree holds submodules that `git worktree remove` refuses: its git directory (`git -C <path> rev-parse --git-dir`) contains a `modules` directory, or a gitlink path of the worktree (mode 160000 in `git -C <path> ls-files --stage`) is populated; deinitializing does not lift it
BLOCKED_UPSTREAM_OF_KEPT      a branch that will remain tracks this branch (`branch.<x>.remote` is `.` and `branch.<x>.merge` is `refs/heads/<this>`), or a lane record names it as a dependency of a branch that will remain
```

A branch **will remain** when it is `main`, the target, a source whose merge status is not `MERGE` or `CONTAINED`, or a source with a delete blocker that no flag in effect lifts (`--discard-ignored` lifts `BLOCKED_IGNORED_FILES`). Re-evaluate `BLOCKED_UPSTREAM_OF_KEPT` until nothing changes, so a chain `c -> b -> a` with `c` dirty keeps both `b` and `a`.

### Remedies

Every failed gate, delete blocker, `UNKNOWN` status, `PREDICTED_CONFLICT`, `PREDICTED_IGNORED_OVERLAP`, and stop of an apply (a conflict, an ignored-file overlap, a refused switch, a failed merge or check) in a report is followed by the action that lifts it. The command never performs these actions; they are the user's, and the report writes each with the real path or name. A remedy changes the repository, and an apply whose plan is older than the repository stops with a new preview (apply step 1), so **rerun** in this table means: run the preview again, then the apply (a GitSweep report gives both lines as `Next preview:` and `Next command:`).

| Finding | Remedy |
|---|---|
| gate: target missing locally (no local branch of that name, even ignoring case) | name an existing local branch (`git branch --list`), or create it deliberately with `git branch <name> <start>` after `git for-each-ref --format=%(refname) refs/heads` shows that no local branch equals the name ignoring case (where the lane guard is armed, register the branch first with `magos_guard.py plan`, see `references/lane-split.md`) |
| gate: target matches an existing branch only when case is ignored | rerun with the exact existing name (`git for-each-ref --format=%(refname) refs/heads`); never create a branch that differs from an existing one only by case |
| gate: target is `main` | name the integration branch instead of `main` |
| gate: local `main` missing | `git branch main <remote>/main` once the remote-tracking ref exists, after the same case check as for a missing target (where the lane guard is armed, register the branch first with `magos_guard.py plan`); a repository whose trunk has another name, such as `master`, has no `<remote>/main`: this command needs a branch named `main`, so create it deliberately at the trunk's tip (`git branch main <trunk>`) or do not use this command |
| gate: a name equals another when case is ignored | make the names distinct with the procedure under **Case collisions** |
| gate: prunable (missing-directory) worktree entry for the target or `main` | check `git worktree list --porcelain`, then `git worktree remove <path>` or restore the directory |
| gate: target checked out in another worktree | run the command from that worktree (`cd <path>`) |
| gate: invoking worktree detached | `git switch <target>` when the target is checked out nowhere; when the target is checked out in another worktree as well, run the command from that worktree (`cd <path>`, the row above), which is not detached |
| gate: invoking worktree dirty | commit the changes, or `git stash push --include-untracked`; `git status --short --untracked-files=all` lists what counts |
| gate: invoking worktree or target in progress | finish or abort the merge, cherry-pick, revert, rebase, am or bisect in that worktree |
| `BLOCKED_DIRTY` | commit, stash or discard the changes in the worktree, then rerun |
| `BLOCKED_LOCKED` | `git worktree unlock <path>` once nobody uses it |
| `BLOCKED_ACTIVE_OWNER` | let the owner finish, or release the lane's claim when its lane is merged or abandoned; for a branch checked out in the main worktree that is not the invoking one, switch that worktree to another branch (`git -C <path> switch <other>`) or run the command from it |
| `BLOCKED_IGNORED_FILES` | add `--discard-ignored` (the listed files are lost) or move the files out of the worktree |
| `BLOCKED_SUBMODULE` | this command cannot remove that worktree; after confirming that it holds nothing unique, remove it yourself (`git worktree remove --force <path>`) or keep it; the branch stays as long as the worktree does |
| `BLOCKED_UPSTREAM_OF_KEPT` | `git branch --unset-upstream <x>` on the branch that tracks it, or retarget that branch |
| `BLOCKED_IN_PROGRESS` | finish or abort the operation in its worktree |
| `BLOCKED_UNRELATED_HISTORY` | none: the branch stays; merge it by hand only on purpose |
| `PREDICTED_CONFLICT` | merge that source into the target by hand and resolve it (`git merge refs/heads/<source>`), then rerun; a conflict stops the apply |
| `UNKNOWN` | establish the fact its evidence names; for a case collision, the rename procedure |
| `UNKNOWN`: a local name that is not safe (**Names**) | rename it (`git branch -m <old> <new>`, the new name within the class of **Names**) |
| `PREDICTED_IGNORED_OVERLAP`, apply stopped by an ignored-file overlap | move or delete the ignored entries that the report names in the invoking worktree (they are untracked, so keep a copy first), then rerun; `--discard-ignored` does not apply to them; completed merges stay |
| apply stopped by a conflict | the report names the failing source, the error text and the target's start SHA; merge that source into the target by hand and resolve it (`git merge refs/heads/<source>`), or restore the start SHA, then rerun; completed merges stay |
| apply stopped by a refused switch, or by a merge that failed without a conflict (a hook, a lock file) | fix what the git error text in the report names (for a refused switch, the ignored files that the target would overwrite), then rerun; completed merges stay and nothing was deleted |
| apply stopped by a failed check | fix what the check names (it ran on the merged result), then rerun; completed merges stay and nothing was deleted |

### Preview behavior (default, read-only)

Collect and report:

1. **Gates** (any failure stops the whole command, even for a preview, and nothing is written): target missing locally (a name that matches an existing branch only when case is ignored counts as missing); target is `main`; local `main` missing; the target or `main` equals another local branch name when case is ignored; target or `main` is checked out only in a prunable (missing-directory) worktree entry; target is checked out in a worktree other than the invoking one (run the command from that worktree); the invoking worktree is detached, dirty (untracked files count), or in progress; target is in progress anywhere. Every gate is evaluated, and the report names every failed gate with its remedy (**Remedies** below), so one run shows everything the user must clear before the next one. A report with a failed gate has no plan: the rest of the preview is not made.
2. **Plan header**: target and `main` with SHAs, the invoking worktree, and the recorded tip of every local branch. Report a same-named tag for any branch, the target included. Report `main` being behind or ahead of `origin/main` when the remote-tracking ref exists; remote freshness is local-only.
3. **Sources to merge**, in merge order: `main` first, then the rest by descending unique-commit count (`git rev-list --count refs/heads/<target>..<sha>`), ties by refname. For each: SHA, exact unique-commit count, and its commit list. A commit list may be shortened only with an explicit "(N more)"; counts and branch sets are never truncated. When `git merge-tree --write-tree` exists, test each source against the current target tip and mark it `PREDICTED_CONFLICT` if it exits 1. For every source to merge, also run the ignored-file overlap test of apply step 4.3 against the current target tip (read-only: the same two listings, run the same way) and mark a hit `PREDICTED_IGNORED_OVERLAP`, with the source, the changed path and the ignored entry. Both marks are hints only: neither can see a clash between two sources, which appears when the second one merges.
4. **Contained sources**: delete only (never `main`).
5. **Classification of every source**: its merge status and every delete blocker, each with evidence. For every worktree that will be removed, its path and whether its owner is recorded ("owner: not recorded" otherwise).
6. **Expected final state**: the local branches that will remain (each with its reason and next step) and the worktrees that will be removed. If any source remains, say plainly that "only `main` and `<branch>`" will not be reached.
7. **Not touched**: remote branches and remote-tracking refs (listed), tags, stashes, detached worktrees, and the main worktree unless it is the invoking one.
8. **Validation**: the repository's normal checks if they can be identified, or "not identifiable".

The preview does not merge, switch, delete, prune, or fetch. `git merge-tree --write-tree` may create unreachable objects but no refs, index, or worktree changes.

### Apply behavior (`--apply`)

1. **Re-survey and record the plan.** Run the preview logic fresh and record the whole plan before running any command that changes the repository: every local branch with its tip SHA, merge status, and delete blockers; the merge order; the expected final branches; and the worktrees to be removed. The plan goes into the final report (step 7); it need not be printed before the first write. Compare it with the most recent GitConverge preview or apply report earlier in this conversation, if any. Stop and show a new preview when any source tip or `main` differs from it, or when the target moved in any way other than through merge commits whose second parent is a source tip recorded in that plan (an earlier `--apply` that was interrupted). A branch that is not in that plan, and a worktree that appeared since it, are reported as "appeared after preview, untouched": such a branch is neither merged nor deleted, and a previewed branch that gained a worktree is still merged as planned but neither it nor its worktree is deleted. Stop on any gate failure or `UNKNOWN` needed for a write. Without an earlier plan the recorded plan is the plan; the run acts on exactly that plan and nothing that appears later.
2. **Record** the target's start SHA and every source and delete-set tip.
3. **Switch** the invoking worktree to target if it is on another branch, using `git switch --no-overwrite-ignore <target>`. A refusal stops the command before any merge, and the report gives git's error text. The command never switches any other worktree and never switches to `main`.
4. **Merge every source whose merge status is `MERGE`, in order, whatever its delete blockers**, inside the invoking worktree:
   1. Recheck that the source tip still equals the recorded SHA; if not, skip it and report.
   2. Skip it if it is now an ancestor of target (an earlier source contained it).
   3. List the paths the source changed since the merge base (`git diff --name-only <merge-base> <sha>`) and the ignored entries in the invoking worktree (`git ls-files --others --ignored --exclude-standard --directory`; a trailing `/` marks an ignored directory). Run both listings from the top level of the invoking worktree as `git -C <top-level> -c core.quotePath=false <command>` (`<top-level>` from `git rev-parse --show-toplevel`): then both list paths relative to the worktree root, and neither prints a non-ASCII path C-quoted (`"\346\236\204..."`, which none of the comparisons below can match). If the worktree has ignored entries and a line of either listing is still wrapped in double quotes (a quote, backslash, or control character in the name), count every changed path as overlapping. They overlap when a changed path equals an ignored entry, when one lies under the other (a directory/file clash), or, if `git config --bool core.ignorecase` is true, when they match ignoring case. If they overlap, stop: a merge silently overwrites ignored files (`--no-overwrite-ignore` is not honored by merge). Completed merges stay, and the report names the source, the changed path and the ignored entry.
   4. Run `git merge --no-ff -m "Merge branch '<name>' into <target>" <recorded-sha>`. Use another merge shape only when repository policy requires it, and never squash or rebase, because the later ancestry check needs real merge ancestry. Never pass `--no-verify`, `-X ours`, `-X theirs`, or `--allow-unrelated-histories`.
   5. On any failure: run `git merge --abort` if a merge is in progress, then **stop the whole command and delete nothing**. Keep completed merges and report the failing source, the error text, the target's start SHA, and how to restore it.
5. **Validate** with the repository's normal checks when identifiable. If they fail because of the merge, stop before any deletion and report. If they cannot be identified, report "not validated" and continue; deletion is still gated by the ancestry check below.
6. **Delete** every source other than `main` whose merge status is `MERGE` or `CONTAINED` and that has no delete blocker. Recheck immediately before each write: (a) the tip still equals the recorded SHA, (b) `git merge-base --is-ancestor <sha> refs/heads/<target>` succeeds, and (c) for a source with a linked worktree, that worktree is still clean, unlocked, not in progress, and has no ignored files unless `--discard-ignored` was given.
   1. **Remove the worktree** (linked, not invoking): `git worktree remove <path>`, never `--force`, never retried with it. A prunable entry (directory missing) is removed the same way, for that entry only. Never run a repository-wide `git worktree prune`; it would also drop detached worktrees and orphan their commits. If the command exits non-zero, keep the branch, run `git worktree list --porcelain`, and report whether the entry is still listed; an entry that vanished while the directory remains is a partial removal that needs manual cleanup.
   2. **Unset a lagging upstream.** `git branch -d` judges a branch against its upstream when one exists. If the branch has an upstream that does not contain the branch tip, record it (`git for-each-ref --format='%(upstream)|%(upstream:short)' refs/heads/<name>`; empty means no upstream) and run `git branch --unset-upstream <name>` first.
   3. **Delete the branch** with `git -C <invoking-worktree> branch -d <name>`. On failure, restore the upstream (`git branch --set-upstream-to=<saved short name> <name>`), skip the branch, and report. Never use `git branch -D`, never `git worktree remove --force`, never `remove -f -f`.
7. **Report** (write it in the reply language, Chinese unless `--lang` selects another one, headings and tables included): the plan it acted on (as recorded in step 1), applied operations, skipped items with reasons, the target's start and end SHA, the final local branch list, the validation result, and every deleted branch with its tip SHA (recreate with `git branch <name> <sha>`; the deleted branch's reflog is not kept). State that remote branches still exist and lack the commits that are now only in local `<branch>`; pushing is the user's decision.

A rerun after an interruption starts from a fresh survey: merged sources are then `CONTAINED` and only get deleted, and the target movement caused by the interrupted run's merges does not make the earlier plan stale (step 1).

### Hard stop conditions

Never: move, reset, or delete `main`; push, force-push, or delete remote branches, or delete remote-tracking refs (`git branch -d -r`, `git remote prune`); run a repository-wide `git worktree prune`; touch a detached worktree or any worktree other than the invoking one, except removing a clean, unlocked worktree without an active owner whose branch is being deleted; merge a branch whose worktree is in progress; resolve a conflict with ours/theirs; force anything. Do not proceed when the skill or this reference could not be loaded; preview only.

### Output

```text
Plan / Preview header (with --apply: the plan acted on)
Gates (every failed gate with its remedy)
Sources to merge (ordered)
Contained sources
Blocked items + reasons + remedies
Expected final local branches
Not touched
Applied operations (only with --apply)
Skipped items + reasons
Target start SHA -> end SHA
Deleted branches + tip SHAs
Validation
Remaining risks
```

## 7. GitSweep

### Invocation

```text
/GitSweep <branch>
/GitSweep <branch> --apply
/GitSweep <branch> --apply --discard-ignored
/GitSweep <branch> --apply --push
/GitSweep <branch> --apply --discard-ignored --push
/GitSweep <branch> --apply --remote upstream
/GitSweep <branch> --lang English
/GitSweep --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `<branch>` | Yes | Local branch that receives everything; same rules as section 6. |
| `--apply` | No | Run the section 6 apply procedure, then delete the merged remote branches below. Without it, only show a preview. |
| `--discard-ignored` | No | Passed through to the section 6 phase unchanged. It has no effect on remote branches. |
| `--push` | No | With `--apply`, after phase 1 and before the remote deletions, publish `<branch>` to the remote with one fast-forward push (**Publish step**), so that remote branches merged only into the local `<branch>` are deleted in the same run. Without `--apply` the preview only reports what the push would do. |
| `--remote <name>` | No | The remote to sweep. Default: `origin`. It must be listed by `git remote`; the value is never used as a revision or a path. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting or changing the repository. |

Examples: `/GitSweep agent/release`, `/GitSweep agent/release --apply`, `/GitSweep agent/release --apply --push`, `/GitSweep --help`.

### 中文描述

在 `/GitConverge` 的基础上多做一步：本地收敛完成后，再删除远端上已经合并的分支。第一阶段与 `/GitConverge` 完全相同（同样的门槛、分类、合并顺序和本地删除规则）；第二阶段只删除"提交已经被远端自己保留的分支包含"的远端分支。默认只预览；只有 `--apply` 才会合并、删除并推送删除。预览末尾给出"一次完成就绪度"：推荐命令、仍需用户处理的阻塞项及其处理办法；加上 `--push`（需要 `--apply`）时，收敛后把 `<branch>` 以一次快进推送发布到远端，只合并进本地 `<branch>` 的远端分支就能在同一次运行里清除，不需要手动推送再重跑。

### Phase 1: converge

Run section 6 unchanged, with its Definitions, Acceptance rule, Classification, gates, apply steps 1-7, and Hard stop conditions, except for the points below. `/GitSweep <branch> --apply` is the same explicit acceptance as `/GitConverge <branch> --apply`, and it also accepts the phase 2 deletions recorded in its plan; `--push` also accepts the publish step (**Publish step**).

- **Earlier plan.** In section 6 apply step 1 and its Acceptance rule, the most recent GitSweep or GitConverge preview or apply report for the same `<branch>` earlier in this conversation is the earlier plan. A source tip or `main` that differs from the GitSweep preview the user saw stops the run with a new preview.
- **Remote writes.** Section 6 bans pushing and deleting remote branches or remote-tracking refs. That ban does not cover the lease-guarded deletions of phase 2, nor, only with `--push`, the one fast-forward push of `<branch>` (**Publish step**); a successful deletion also removes the matching `refs/remotes/<remote>/<name>`, which is expected, and the push moves `refs/remotes/<remote>/<branch>`. Every other part of the ban stands.
- **Not touched.** Section 6 preview item 7 lists remote branches as not touched; here they appear in the remote classification table instead.
- **Report.** The section 6 step 7 statement that remote branches still exist applies only to the remote branches phase 2 kept; the report also carries the run state (**One-shot readiness**).
- **Gates.** Section 6 gates are evaluated all at once, as there, and the sweep adds one: `--remote <name>` not listed by `git remote`. A failed gate makes the readiness verdict `BLOCKED`.
- **Flags in a preview.** A preview computes everything that depends on `--discard-ignored` as if the recommended command had been typed (**One-shot readiness**): `BLOCKED_IGNORED_FILES` counts as lifted whenever `--discard-ignored` is recommended, so the will-remain set, `BLOCKED_UPSTREAM_OF_KEPT`, the expected final local branches and the remote classification (`KEPT_LOCAL`, `BLOCKED_UPSTREAM`) show the state that command reaches. An apply uses the flags it was given: without `--discard-ignored` such a worktree and its branch stay, and the remote branch of the same name is `KEPT_LOCAL`.

Phase 2 starts only after phase 1 finished without stopping: a gate failure, a conflict, a failed check, an `UNKNOWN` needed for a write, or a stale preview stops the whole command and no remote branch is touched. Branches that phase 1 kept (blocked, unrelated history, in progress) are not remote candidates either (`KEPT_LOCAL` below).

### Phase 2: remote sweep

**Definitions.**

- **remote**: `--remote <name>` or `origin`. If it is not in `git remote`, stop before phase 1 (a gate failure). Section 6 **Argument safety** holds for every command of this section.
- **remote default**: the branch named by `git symbolic-ref refs/remotes/<remote>/HEAD`. That ref is written at clone time and can be stale (`references/branch-strategy.md`), so apply step 2 checks it against the live remote. If that ref is missing, or names a branch with no remote-tracking ref, the remote default is unknown and the whole phase 2 is `UNKNOWN`: report it and suggest `git remote set-head <remote> --auto`. Phase 1 still completes.
- **mapping**: `git config --get-all remote.<remote>.fetch` must include `refs/heads/*:refs/remotes/<remote>/*` (with or without a leading `+`), so that `refs/remotes/<remote>/<name>` is the remote's `refs/heads/<name>`; without it, phase 2 is `UNKNOWN`. A remote-tracking ref that matches the destination of another fetch refspec (for example `refs/remotes/<remote>/pr/*` from `+refs/pull/*/head:refs/remotes/<remote>/pr/*`) is `NOT_TOUCHED`.
- **URL**: phase 2 and the publish step are `UNKNOWN` unless `git remote get-url --all <remote>` and `git remote get-url --all --push <remote>` each print exactly one URL and the two are identical. A fetch and `git ls-remote` read one URL, but a push goes to every URL, so with several URLs, or a push URL that differs from the fetch URL, the deletions and the publish would reach a repository that was not checked.
- **survivors**: the remote branches the remote keeps, as the ancestry anchor for "merged": the remote default and `refs/remotes/<remote>/<target>` when it exists. A remote branch is **merged** only when its tip is an ancestor of a survivor tip (`git merge-base --is-ancestor <sha> <survivor-sha>`), never merely of the local target. Work that exists only in the local target is not on the remote, so deleting the remote branch would remove the last remote copy; such a branch is `PENDING_PUSH` until the publish step has put that work on the remote.
- **converged target**: what local `<branch>` holds once phase 1 has finished: in an apply after phase 1, its tip; in a preview, its current tip together with the tips of every source whose merge status is `MERGE` (a hint, as `PREDICTED_CONFLICT` is). Every test below that says "the converged target" uses it, in the preview and in the apply, so a preview and the apply after it classify a remote branch alike.
- Resolve every remote branch through its full refname (`refs/remotes/<remote>/<name>`) and take SHAs from one `git for-each-ref --format='%(refname) %(objectname)' refs/remotes/<remote>` listing. **Names vs SHAs** and **Case collisions** from section 6 apply: two remote names equal ignoring case are both `UNKNOWN`.

**Remote classification** (the first match wins; a case collision is decided before it, as in section 6, and makes both names `UNKNOWN` whatever else applies):

```text
NOT_TOUCHED          the remote default, `main`, the target, `HEAD`, a ref written by another fetch refspec (see mapping), any branch the repository documents as long-lived or protected, and any branch with a long-lived role (below)
BLOCKED_BAD_NAME     the name holds a character outside ASCII letters, ASCII digits and `.` `_` `/` `+` `-`, starts with `-` or `+`, or fails `git check-ref-format --branch`; never passed to a command
BLOCKED_UPSTREAM     a local branch that will remain tracks it (`branch.<x>.remote` is the remote and `branch.<x>.merge` is `refs/heads/<name>`)
KEPT_LOCAL           the local branch of the same name remains after phase 1 (blocked, unrelated history, in progress, `UNKNOWN`, or appeared after preview)
KEPT_NOT_MERGED      its tip is not an ancestor of any survivor and not of the converged target; it holds work the remote does not have elsewhere
PUSH_THEN_DELETE     its tip is an ancestor of the converged target but not of any survivor, and the publish step is predicted to run (its conditions that the local refs can show hold), whether or not `--push` was typed: with `--push` the apply publishes `<branch>` first and deletes this branch after it; without `--push` the apply leaves it and reports "kept: --push not typed"
PENDING_PUSH         its tip is an ancestor of the converged target but not of any survivor, and the publish step is not predicted to run, or in an apply it was skipped, failed or was not confirmed (the report names the condition); delete it after `<branch>` is pushed and GitSweep is run again
STALE                the live remote tip differs from the remote-tracking SHA (checked in apply only); skip it
SAFE_CANDIDATE       merged into a survivor, and none of the above applies
UNKNOWN              a needed fact could not be established
```

A **long-lived role** is one of INTEGRATION, STAGING, RELEASE, or ARCHIVE in `references/branch-strategy.md` **Branch roles**. It needs recorded or observed evidence: a policy file, CI trigger filters, matching release tags, or at least two merge commits between the candidate and a survivor, read from `git log --first-parent --merges` of each of the two, run on their recorded SHAs (as in `references/branch-strategy.md`): a merge on the survivor's `--first-parent` chain whose second parent lies on the candidate's `--first-parent` chain, or a merge on the candidate's chain, and not on the survivor's, whose second parent lies on the survivor's chain. One merge is a lane merge, not role evidence, and merges the candidate inherited from before it was cut do not count. A role inferred only from the name does not count; report the name as the evidence. Such a branch is often fully merged right after a sync, and deleting it on the remote also closes or retargets pull requests that use it as their base.

**Preview (default, read-only).** After the section 6 preview, list every remote branch with its SHA and remote classification, the survivors with their SHAs, and the exact `git push` that would be run for each `SAFE_CANDIDATE` (printed as section 6 **Argument safety** says). Also the **publish prediction**, from local refs only and with or without `--push`: the push would run when every condition of the **Publish step** that the local refs can show holds (`<branch>` is not `main` and not the remote default, phase 2 is not `UNKNOWN`, and `refs/remotes/<remote>/<branch>` is absent or a proper ancestor of the converged target), and the report then gives the exact push command, the commits it would publish (the commits of the converged target that no `refs/remotes/<remote>/*` ref holds yet, `git rev-list <converged tips> --not --remotes=<remote>`, the sources to merge among them, each commit list shortened only with an explicit "(N more)"; the count is N existing commits, and phase 1 adds at most one `--no-ff` merge commit per source to merge, so the apply publishes at most N plus the number of sources to merge and its report gives the exact range and count), whether it creates the remote branch, and the `PUSH_THEN_DELETE` branches that depend on it; when it would not run, the report names the failed condition, or says that nothing needs publishing when the remote tip already equals the converged target. A `PUSH_THEN_DELETE` branch is listed with its two ways forward: run with `--push`, or, once local `<branch>` holds its tip (after an `--apply` without `--push` when the tip is covered only through a source that phase 1 has yet to merge), push `<branch>` by hand (`git push <remote> refs/heads/<branch>:refs/heads/<branch>`) and rerun; a `PENDING_PUSH` branch is listed with the condition that keeps the publish from running. The preview does not contact the network and does not fetch: remote freshness is local-only, so the report says that `refs/remotes/<remote>/*` may be behind the live remote and that `--apply` rechecks it. The report also says that each remote deletion closes the open pull requests that use the branch as their head, and on some hosts closes or retargets those that use it as their base; the preview cannot see them.

**Publish step (`--push`).** It publishes the local `<branch>` and no other ref, with this one command and no variation:

`git push --recurse-submodules=no --no-follow-tags <remote> refs/heads/<branch>:refs/heads/<branch>`

It is a fast-forward push: never `--force`, `-f`, a `+` refspec or `--force-with-lease`, never `--no-verify`, `--tags`, `--all`, `--mirror`, `--prune`, `--delete`, `--set-upstream` or a refspec pattern. A `pre-push` hook of the repository runs as git runs it. The push creates `refs/heads/<branch>` on the remote when it does not exist there; the plan and the report say so. It is the one push of commits that this command makes, and `--apply --push` is the user's acceptance of publishing the local `<branch>` as phase 1 leaves it: the commits that no ref of the remote holds yet, which the preview listed as existing commits and sources to merge (the merge commits of phase 1 are the only others), and the report lists by range and count.

**Apply.** After phase 1:

1. Record the remote candidate list in the plan (included in the final report), each candidate classified against the actual local `<branch>` tip. Compare it with the most recent GitSweep preview or apply report for the same `<branch>` earlier in this conversation, if any. A candidate that was neither a `SAFE_CANDIDATE` nor a `PUSH_THEN_DELETE` there, or whose SHA differs from the one shown there, is reported as "appeared after preview, untouched". Without an earlier GitSweep preview or report, the recorded list is the plan.
2. Run `git ls-remote --symref <remote> HEAD 'refs/heads/*'` once. This is a network read and changes no refs; it is the only network read before the deletions. Phase 2 is `UNKNOWN` unless the `ref:` line for `HEAD` names exactly the remote default (a live `HEAD` that is detached, unborn or missing has no `ref:` line), and also when a survivor's live tip differs from its remote-tracking SHA or when a survivor is missing. A candidate whose live tip differs, or that is missing, is `STALE` and skipped. Do not fetch to resolve either. Tell the user to run `git fetch <remote>` (and `git remote set-head <remote> --auto` if the default changed), then rerun. Record the live tip of `refs/heads/<branch>` (or that it is absent) for the next step.
3. **Publish** (only with `--push`; otherwise go to step 4, which leaves every `PUSH_THEN_DELETE` and `PENDING_PUSH` branch). Run the publish command above only when all of these hold: phase 1 finished and its validation did not fail (a validation that could not be identified does not stop the push; the report then says that the published merge is not validated); phase 2 is not `UNKNOWN`; `<branch>` is not `main` and not the remote default; and the live tip recorded in step 2 is absent or an ancestor of the local `<branch>` tip (`git merge-base --is-ancestor <live-sha> refs/heads/<branch>`; a live tip whose object the local repository lacks is not an ancestor: tell the user to `git fetch <remote>` and merge it). When the live tip equals the local tip there is nothing to publish: no push is made and the report says `PUBLISH_NOT_NEEDED`; the `PUSH_THEN_DELETE` candidates are then judged against that tip like any other. Otherwise the push runs even when no candidate depends on it, because `--push` is the user's request to publish `<branch>` and the preview listed the commits. If a condition fails, skip the push, report `PUSH_SKIPPED` with the failed condition, and go on to step 4 with the candidates as they are. On a non-zero exit (a protected branch, a hook, a rejection, the network), record the error text, do not retry and do not alter the command, report `PUSH_FAILED`, and go on to step 4. On success, `git rev-parse refs/remotes/<remote>/<branch>` must equal the local tip, which is then the survivor tip of `<branch>`; when it does not, report `PUSH_UNCONFIRMED` and treat the push as failed. Each `PUSH_THEN_DELETE` candidate whose tip is an ancestor of that tip becomes `SAFE_CANDIDATE`; when the push was skipped, failed or unconfirmed, it is reported as `PENDING_PUSH` with that reason. A live `<branch>` that moved or vanished since the remote-tracking ref was written makes phase 2 `UNKNOWN` in step 2, so the push is skipped for that reason; the ancestor condition catches a diverged branch whose live tip still equals the remote-tracking ref.
4. For each remaining `SAFE_CANDIDATE`, one at a time, delete it with exactly:
   `git push --recurse-submodules=no --force-with-lease=refs/heads/<name>:<sha> <remote> :refs/heads/<name>`
   The lease is the per-branch recheck at the moment of deletion: the remote refuses the deletion if the branch moved since it was recorded. On a non-zero exit, record the error text, leave that branch, and continue with the next candidate.
5. Report the publish result (the push, or `PUSH_SKIPPED`, `PUSH_FAILED` or `PUSH_UNCONFIRMED` with its reason; the remote tip before and after and the commit count; undoing a publish needs a force push, which this command never makes), each deleted remote branch with its tip SHA (recreate with `git push <remote> <sha>:refs/heads/<name>`) and each skipped one with its classification. Say that a remote deletion also closes any open pull request that uses the branch as its head, and on some hosts closes or retargets pull requests that use it as their base. Then the run state (**One-shot readiness**).

### One-shot readiness

A preview ends with a readiness verdict and a recommended command, and an apply report ends with the run state it reached, so the user sees whether one run of the **recommended command** reaches the **end state**: only `main` and `<branch>` remain as local branches, the worktrees of the deleted branches are removed, and every remote branch is deleted or `NOT_TOUCHED`. A worktree the command never touches (a detached one, or one that holds `main` or another kept branch) is not part of the end state; the report lists it. The verdict judges the recommended command, not the command as typed: the recommended flags are chosen first, from the blockers and the publish prediction, and everything the verdict and the remote classification depend on is then computed as if that command had been typed (**Flags in a preview**). It is one of:

- `ONE_SHOT`: no gate fails; every source is `MERGE` or `CONTAINED` and its only delete blocker, if any, is `BLOCKED_IGNORED_FILES`, which `--discard-ignored` lifts; no source is `PREDICTED_CONFLICT` or `PREDICTED_IGNORED_OVERLAP`; phase 2 is not `UNKNOWN`; and every remote branch is `SAFE_CANDIDATE`, `PUSH_THEN_DELETE` or `NOT_TOUCHED`. One run of the recommended command then reaches the end state, as far as the local refs can show: the apply rechecks the live remote.
- `PARTIAL`: no gate fails, but something remains that no flag lifts (any other delete blocker, `BLOCKED_IN_PROGRESS`, `BLOCKED_UNRELATED_HISTORY`, `UNKNOWN`, a `PREDICTED_CONFLICT`, a `PREDICTED_IGNORED_OVERLAP`, `KEPT_NOT_MERGED`, `KEPT_LOCAL`, `BLOCKED_UPSTREAM`, `BLOCKED_BAD_NAME`, a `PENDING_PUSH` whose publish step is not predicted to run, phase 2 `UNKNOWN`). The recommended command still does everything it can.
- `BLOCKED`: a gate fails, so nothing can run; the report lists every failed gate with its remedy.

**Recommended command.** For `ONE_SHOT` and `PARTIAL`, the full line `/GitSweep <branch> --apply` (with `--remote <name>` and `--lang <language>` as given, and the flags in the order `--apply`, `--discard-ignored`, `--push`, `--remote`, `--lang`), with exactly the flags that lift something: `--discard-ignored` only when a worktree's only delete blocker is `BLOCKED_IGNORED_FILES`, with every ignored path that it deletes listed next to the line; `--push` only when at least one remote branch is `PUSH_THEN_DELETE` (whether or not `--push` was typed), or when `--push` was typed and the publish prediction says the push will run, with the publish prediction (commit count, whether it creates the remote branch) next to the line. A typed `--push` whose publish will not run (the prediction names a failed condition, or nothing needs publishing) is dropped from the line, and the report says why. Apart from a typed `--push` that will run, a flag that lifts nothing is never recommended, and a flag that discards files or publishes commits is never added silently.

**Remaining items.** For `PARTIAL`, every item that stays: the branch or worktree, its classification, its evidence, its remedy and whether the user must rerun afterwards. The remedies for local findings are the **Remedies** table of section 6, which also defines **rerun**. For remote findings:

| Finding | Remedy |
|---|---|
| phase 2 `UNKNOWN`: remote default unknown | `git remote set-head <remote> --auto` |
| phase 2 `UNKNOWN`: no `refs/heads/*:refs/remotes/<remote>/*` mapping | `git config --add remote.<remote>.fetch '+refs/heads/*:refs/remotes/<remote>/*'`, then `git fetch <remote>` |
| phase 2 `UNKNOWN`: the remote has several URLs, or a push URL that differs from the fetch URL | leave exactly one URL, the same for fetch and push: `git remote set-url --delete <remote> <extra-url>` for each extra URL, and for a separate push URL `git config --unset-all remote.<remote>.pushurl` |
| phase 2 `UNKNOWN`: the live remote `HEAD` names no branch (detached or unborn) | set the remote's default branch on the remote or its host (`git remote set-head <remote> --auto` cannot fix it), then rerun |
| phase 2 `UNKNOWN` or `STALE` after the live check | `git fetch <remote>` (and `git remote set-head <remote> --auto` when the default changed), then rerun |
| gate: `--remote <name>` not listed by `git remote` | name a listed remote (`git remote -v`), or add it with `git remote add <name> <url>` |
| `PUSH_THEN_DELETE` (kept: `--push` not typed) | rerun with `--push` (the `Next preview:` line, then the `Next command:` line), or publish `<branch>` yourself (`git push <remote> refs/heads/<branch>:refs/heads/<branch>`; local `<branch>` holds the tip after phase 1), then rerun |
| `PENDING_PUSH` | clear the condition the report names, then rerun: if `<branch>` is the remote default, publish it by hand or through your review process (the command never pushes the remote default); if the remote tip is not an ancestor, `git fetch <remote>` and merge it into `<branch>`, then rerun with `--push`; if the push failed or was refused, satisfy the host's rule (branch protection, a hook) and rerun with `--push`, or publish by hand; if phase 2 is `UNKNOWN`, see its rows |
| `PUSH_SKIPPED`, `PUSH_FAILED`, `PUSH_UNCONFIRMED` | clear the named condition: fetch and merge a newer remote tip; satisfy the host's branch protection or hook; fix the failed validation (see the failed-check row); for `<branch>` being `main` or the remote default, publish it by hand or through your review process; or publish by hand, then rerun |
| two remote names equal ignoring case (`UNKNOWN`) | rename or delete one of them on the host; the command leaves both untouched |
| `KEPT_LOCAL` | clear the local blocker named for that branch |
| `BLOCKED_UPSTREAM` | `git branch --unset-upstream <x>` on the local branch that tracks it |
| `KEPT_NOT_MERGED` | review it and merge it into `<branch>`, or delete it on the host yourself; the command never deletes it. After the merge, the preview lists the branch as `PUSH_THEN_DELETE` and recommends `--apply --push` (as `PENDING_PUSH` with its condition when the publish is not predicted to run) |
| `BLOCKED_BAD_NAME` | delete or rename it on the host |

**Run state (apply report).** `COMPLETE` when the end state was reached; otherwise `PARTIAL` with the same remaining items and, as the last two lines, in this order, `Next preview:` and `Next command:`. A remedy changes the repository, and an apply whose plan is older than the repository stops with a new preview (**Earlier plan**), so the report cannot promise that one run follows a remedy: `Next preview:` is the same line without `--apply`, to run once the remedies are done, so that the preview becomes the earlier plan, and `Next command:` is the line to run after that preview (when that preview recommends another line, run the recommended one). Both are built by the rules above from the final survey, with the flags in the order `--apply`, `--discard-ignored`, `--push`, `--remote`, `--lang`, except for `--push`, which follows the next sentence. The `Next command:` line carries `--push` when some remote branch ended `PUSH_THEN_DELETE` or `PENDING_PUSH` for a reason that a rerun with `--push` can clear, or when `--push` was typed and the publish prediction says the push would still run; it never carries `--push` when the only reason is that `<branch>` is the remote default; with phase 2 `UNKNOWN` it carries `--push` only when it was typed. With phase 2 `UNKNOWN` no remote branch is classified and the report shows the phase 2 rows. Both lines are left out when no rerun would change anything.

### Hard stop conditions

All of section 6, except that the lease-guarded deletion above and, only with `--push`, the publish step replace its ban on pushing and on deleting remote branches and remote-tracking refs. In addition: never push commits or tags except the one fast-forward push of `<branch>` that `--push` makes; a push never reaches a repository other than `<remote>` (a remote with several URLs makes phase 2 `UNKNOWN`) and never recurses into submodules (`--recurse-submodules=no` in both push commands); never run a git command as a shell string (section 6 **Argument safety**), or pass the name of a `BLOCKED_BAD_NAME` branch to one; never force-push (the only pushes are the lease-guarded deletion above, one named branch per command, and that publish command); never use `--mirror`, `--prune`, `--all`, `--tags`, `--no-verify`, or a refspec pattern (in a push; the pattern in the step 2 `ls-remote` only selects what to read); never publish without `--push`, publish when phase 1 stopped or its validation failed, publish `main` or the remote default, or retry a failed publish with another command; never run `git remote prune`, `git fetch --prune`, or `git branch -d -r`; never delete the remote default, `main`, the target's remote branch, a branch with a long-lived role, a branch on any remote other than `--remote`, or a branch that is not merged into a survivor; never delete a remote branch when phase 1 stopped. Do not proceed when the skill or this reference could not be loaded; preview only.

### Output

```text
Plan / Preview header (section 6 output, plus remote and survivors)
Gates (every failed gate with its remedy)
Sources to merge (ordered)
Contained sources
Blocked items + reasons + remedies
Expected final local branches
Remote branches: classification table (SAFE_CANDIDATE / PUSH_THEN_DELETE / PENDING_PUSH / KEPT_NOT_MERGED / ...)
Publish prediction (with or without --push)
Not touched
Readiness: ONE_SHOT / PARTIAL / BLOCKED, recommended command, remaining items + remedies
Applied operations (only with --apply)
Skipped items + reasons
Target start SHA -> end SHA
Published branch: remote tip before -> after, commit count (only with --push)
Deleted local branches + tip SHAs
Deleted remote branches + tip SHAs
Validation
Run state: COMPLETE / PARTIAL, remaining items + remedies, Next preview and Next command (only with --apply)
Remaining risks (including: without a successful publish, the remote lacks the commits now only in local <branch>)
```

## 8. GitPlan

### Invocation

```text
/GitPlan <set> --into <branch>
/GitPlan <set> --into <branch> --apply
/GitPlan <set> --into <branch> --apply --create
/GitPlan <set> --status
/GitPlan <set> --amend --expect-revision <n>
/GitPlan <set> --amend --expect-revision <n> --apply [--create]
/GitPlan <set> --converge [--include-active]
/GitPlan <set> --converge --apply [--include-active] [--land] [--expect-revision <n>]
/GitPlan <set> --release
/GitPlan <set> --into <branch> --lang English
/GitPlan --help
```

### Arguments

| Argument | Required | Description |
|---|---:|---|
| `<set>` | Yes | Name of the plan: `[a-z0-9][a-z0-9-]{0,23}`, matched case-sensitively, and not a Windows device name (`con`, `nul`, `com1`, ...). It names the set record and the claims of its lanes. |
| `--into <branch>` | Yes, to plan | Local branch the plan is made against and that `--land` later fast-forwards. Same rules as the section 6 `<branch>` (matched exactly in `refs/heads/`, not `main`). The other forms read it from the set record. |
| `--apply` | No | With `--into`: register the plan the preview showed. With `--amend`: register the amended plan. With `--converge`: merge the lanes into the integration branch. Without it, only show a preview. |
| `--create` | No | With `--apply` of a plan or an amendment: also create the branches and worktrees of the registered lanes that do not exist yet. |
| `--status` | No | Read-only checklist: the sheet with the state of every lane and what remains. |
| `--amend` | No | Re-plan a registered set. Needs `--expect-revision`. |
| `--expect-revision <n>` | With `--amend` | The record revision (a positive integer) the amendment, or with `--converge --apply` the previewed convergence, was made against; a record at another revision stops the command. |
| `--converge` | No | Preview the merge of the lanes, in dependency order, into one integration branch; with `--apply`, run it. |
| `--include-active` | No | With `--converge`: treat a lane in state `active` that holds commits as ready at its current tip. In an apply this is the user's acceptance of those tips. |
| `--land` | No | With `--converge --apply`: after the merges and the checks, fast-forward `<branch>` to the integration branch. |
| `--release` | No | Retire the set once its lanes are integrated: remove its claims and its record. |
| `--lang <language>` | No | Language of the reply, a name or code such as `English` or `ja`. Default: Chinese. See Argument and Help Behavior. |
| `--help` | No | Show this command's usage and stop without inspecting or changing the repository. |

The selecting option (`--into`, `--status`, `--amend`, `--converge`, `--release`) chooses the form. Two selecting options together, or an option the form does not list in **Invocation** (`--lang` and `--help` are handled first, as in Argument and Help Behavior), is a usage error: explain it, show the usage, and execute nothing.

Examples: `/GitPlan feat-x --into develop`, `/GitPlan feat-x --into develop --apply --create`, `/GitPlan feat-x --status`, `/GitPlan feat-x --converge --apply --land`, `/GitPlan --help`.

### 中文描述

在任何子 Agent 开工之前，调查 Git 与代码，把一个任务拆成若干文件互斥的 lane（子 Agent 的 worktree），并给出一份简明清单：它既是你审阅的计划，也是任务完成后合并时的 TODO 参考。`magos_guard.py` 证明各 lane 的文件清单两两不相交，并以乐观锁登记（revision 与 base，没有人持锁）；过期的计划只会被发现，不会被覆盖。登记同时为集成分支 `agent/<set>/integration` 登记一份 claim，使守卫允许用普通 `git switch -c` 创建它；这份 claim 不占用任何文件，也不限制任何 lane 的 manifest。之后 `--status` 与 `--converge` 重新打印这份清单并勾选每个 lane 的状态，`--converge --apply` 按依赖顺序把 lane 合并进集成分支（"整体"），`--land` 再以一次快进把它落到 `<branch>`，`--release` 收尾。默认只预览；只有 `--apply`（以及 `--release`）才写入：登记写 claim 与 set 记录，`--create` 才创建分支和 worktree。从不推送、从不强制、从不删除分支或 worktree，也从不动 `main`。

### Definitions

- **set**: one plan, named `<set>`. Its **record** is the file `<git-common-dir>/magos/sets/<set>.json`. Each lane has one claim (the claim format of `references/lane-split.md`, plus `set=<set>` and `lane=<id>`), and the integration branch has one (`set=<set>`, `role=integration`, one marker entry `.magos/integration/<set>/`, because a claim needs a non-empty manifest): that claim is why a plain `git switch -c` may create `agent/<set>/integration` in a guarded repository. It is exempt from overlap judgement in both directions: it claims no files, so it restricts no lane manifest and is never a claimant, and the creation of that branch is judged only for its name and the existence of the claim. Only the guard's `set-plan`, `set-update` and `set-release` write the record and these claims, and `set-show` reads them. While the record exists, a plain `plan --amend` of a lane claim is refused (exit 14, `lane_in_set`) and so is a plain `release` of any claim of the set (exit 16, `blocked_set`): a set is changed only through this command. An open lane claim (`planned` or `active` in `<guard> list`) is active-owner evidence, so `/GitCleanup`, `/GitConverge` and `/GitSweep` report its lane as `BLOCKED_ACTIVE_OWNER`; `--release` removes the claims.
- **guard**: `magos_guard.py`, run as `<guard>` (`references/lane-split.md` section 5). It must report version 1.0.4 or later (`<guard> version --json`, field `version`), because older guards lack the `set-*` subcommands; no guard, or an older one, is a gate failure.
- **Guard call**: every call is an argument list, `<guard> <subcommand> --repo '<top>' --json --lang <zh or en> ...`, with `<top>` the top level of the invoking worktree and `--lang zh` when the reply language is Chinese, else `--lang en`. Section 6 **Argument safety** applies to it, and the command lines of this section leave `--repo`, `--json` and `--lang` out. The result is one JSON object with `decision`, `code`, `message`, `exit_code` and, for a denial, the keys of its kind: `errors` (`field`, `code`, `text`), `overlaps`, `lanes`, `blocked` (`lane`, `reason`), `unknowns` (`code`, `text`), `kind` with `expected` and `current`, `files`. Exit code 0 proceeds. Any other code stops the command at that call, except where a step gives a code another meaning (exit 21 of a preview's `set-show`, and a dry-run failure that **Preview behavior** step 3 fixes in the partition): completed steps stay, and the report quotes the guard's message and the row of **Remedies** for that code. The only retry is one repeat of a call that exited 13. The record and the claim files are never read or written except through the guard.
- **view**: what `set-show --drift` prints with `--json`: besides the common keys, `record`, `view` and `warnings`. `record` is the stored record (`revision`, `target`, `base`, `integration`, and per lane `id`, `branch`, `worktree`, `paths`, `depends_on`, `acceptance`, `state`, `head`, `note`). `view` has `target_tip` (null when the target branch is gone), `target_moved`, `lanes` (per lane, in record order: `id`, `branch_exists`, `tip`, `ahead` (commits since `base`), `descends_from_base`, `worktree_present`, `worktree_clean`, `operation` (the operations in progress in its worktree, a list that is also non-empty when its metadata cannot be read), `state`, `head`, `claim` (`ok`, `missing` or `mismatch`), `changed` (the files it changed against the merge base with the current target tip; null when the branch shares no history with the target), `out_of_lane` and `moved_since_ready`) and `drift` (`shared_changes` and `target_overlap`, each a list of `{path, lanes}`, `stale` and `merge_order`, the lane ids in dependency order). `descends_from_base` is informational: no finding uses it.
- **target**: `<branch>` of `--into`, or the `target` of the record for the other forms. It is gated as in section 6 (exact match in `refs/heads/`, not `main`, no case collision), and its tip SHA is read from one `git for-each-ref` listing. Every git command of this section names the target as `refs/heads/<name>` or by that SHA, never by the bare name, except `git switch`, which takes the bare name and resolves only branches.
- **base**: the target tip SHA (the full SHA) the plan was made against. Every lane branch is cut from it, and an amendment moves it to the live target tip. A lane need not descend from the current `base`: the guard measures what a lane changed against the merge base with the current target tip, so an amendment that moves `base`, or a target that moved, never fails a lane by itself.
- **lane**: `id`, `title`, `branch`, `worktree`, `paths` (a manifest of `references/lane-split.md` section 4), `depends_on`, `acceptance`, `state` and `head`. Its worktree is the one the view reports (`worktree_present`: at the registered path or holding its branch). The **lane state** is `planned` (registered, its branch may not exist), `active` (its owner works on it), `ready` (its owner recorded `--head <tip>`: committed, inside the manifest, worktree clean), `integrated` (its recorded head was merged; the guard needs `--head` equal to the head recorded at ready and `--integration agent/<set>/integration`) or `blocked`. The guard allows `planned` to `active` or `blocked`, `active` to `ready` or `blocked`, `ready` to `active`, to `ready` with a new head, to `integrated` or to `blocked`, `integrated` to `integrated` (a note) or `blocked`, and `blocked` to `active`; `active` and `blocked` may also repeat to change only the note, and any other transition is exit 24 on `--state`. A lane owner records progress with `set-update`; this command records `integrated`, and `ready` only for `--include-active`.
- **integration branch**: `agent/<set>/integration`. Its **integration start SHA** is the target tip it was cut from (for a branch that exists, `git merge-base 'refs/heads/<target>' 'refs/heads/agent/<set>/integration'`).
- **spec**: the JSON that `set-plan` reads. **sheet**: the checklist text built from it (**The spec and the sheet**).
- **repository normal checks**: the build, test and lint commands the investigation read from the repository's own files (step 8 of **Investigation**), or "not identifiable".
- **Unchanged from section 6**: **Names vs SHAs**, **Case collisions**, **Names**, **Argument safety** (for every command this section names and prints), **invoking worktree**, **clean**, **in progress**, the target gates, and the ignored-file overlap test of apply step 4.3.

### Acceptance rules

- **Plan and amendment.** `--apply` registers exactly the spec of the latest preview of the same set and target earlier in this conversation, byte for byte, and nothing else. With no such preview, after a change the user asked for since that preview, or when its `base` differs from the live target tip, the command makes a new preview and stops. The plan is generated, so the user's acceptance attaches to the previewed spec, not to the command line.
- **Convergence.** `--converge --apply` is the user's acceptance of the lane heads listed in the plan that the run records and puts in its report, or in a converge preview of the same set earlier in this conversation, and with `--land` of one fast-forward of `<branch>` to the integration branch. It permits no write to any branch except the integration branch and, with `--land`, the target, and never to `main`.

### Lane findings

A lane recorded `integrated` is `INTEGRATED` and has no findings. Every other lane gets zero or more findings, evaluated in this order from the view. **Pending** findings leave the lane out of this run and stop nothing; a **failing** finding stops the whole command, in the preview as a failed gate, so a ready lane that is inconsistent is never merged around. A lane in state `planned` or `active` (and not included by `--include-active`) or `blocked` shows only its pending finding. A lane with no finding is `READY`.

```text
BLOCKED             pending   the recorded state is blocked
NOT_READY           pending   the recorded state is planned or active; with --include-active an active lane whose ahead is above 0 is evaluated as ready at its current tip, and one whose ahead is 0 stays NOT_READY
WAITING             pending   a dependency is neither INTEGRATED nor READY in this run
MISSING_BRANCH      failing   branch_exists is false
DIRTY               failing   worktree_clean is false
IN_PROGRESS         failing   operation is not empty
NO_MERGE_BASE       failing   the branch exists and changed is null: it shares no history with the target (the guard refuses to record it ready, exit 16)
OUT_OF_LANE         failing   out_of_lane is not empty (the files are listed)
SHARED_CHANGE       failing   the lane is named in an entry of drift.shared_changes (both lanes and the files are listed)
MOVED               failing   moved_since_ready is true
CLAIM_DRIFT         failing   claim is missing or mismatch
PREDICTED_CONFLICT  hint      git merge-tree --write-tree exits 1 for its tip against the current target tip, tested as in section 6 preview item 3; a hint only, which cannot see a clash between two lanes
```

One plan-level finding, `STALE_PLAN` (failing), is added when `drift.stale` is true: the target moved since `base` and the files it changed intersect a lane manifest (`target_overlap`), so the lanes are no longer independent of what landed. A target that moved with an empty `target_overlap` is reported, and the plan stays valid.

### Remedies

Every failed gate, failing finding, guard exit code and stop of an apply in a report is followed by the action that lifts it. The command never performs these actions; they are the user's (or the lane owner's, the agent or person working in that lane's worktree), and the report writes each with the real path or name. **Rerun** means: run the preview again, then the apply (section 6).

| Finding | Remedy |
|---|---|
| gate: no guard, or a guard older than 1.0.4 | install or refresh the guard (`references/installation.md`); `<guard> version` must print 1.0.4 or later |
| gate: `<set>` is not `[a-z0-9][a-z0-9-]{0,23}`, or is a Windows device name | name the set within that class |
| gate: target missing locally, matching only when case is ignored, `main`, or equal to another local branch ignoring case | the section 6 rows of the same name |
| gate: invoking worktree detached, dirty or in progress; target in progress anywhere | the section 6 rows of the same name |
| gate: invoking worktree is on neither the target nor (for a resume) the integration branch; target checked out in another worktree | `git switch '<target>'` when it is checked out nowhere else, or run the command from the worktree that holds it (`cd <path>`) |
| gate: `agent/<set>/integration` exists and shares no history with the target | it is not this set's: rename it (`git branch -m '<old>' '<new>'`) or, after reviewing it, delete it yourself, then rerun; the command never deletes it |
| gate: the record's `integration` names a branch that no longer exists | its merges are lost: restore the branch at the tip you trust (`git branch 'agent/<set>/integration' '<sha>'`), or record the lanes it held `blocked` and re-plan with `--amend` |
| gate: the integration branch does not exist and its claim is missing from `<guard> list` | `--amend --expect-revision <n>` with the lanes unchanged writes the claim again |
| gate: `--land` while a lane is not `READY` or `INTEGRATED` | run without `--land` to merge the lanes that are ready, and land when every lane is done |
| exit 21 (set unknown) | check the name (`<guard> list` shows the set of every claim) or plan it first with `/GitPlan <set> --into <branch>` |
| exit 20 (set exists; the preview finds it with `set-show`) | read it with `--status`, change it with `--amend --expect-revision <n>`, retire it with `--release`, or name another set |
| exit 23 (a record written by a newer MAGOS) | upgrade the guard (`references/installation.md`); the record is never read or changed meanwhile |
| exit 11, `unknowns` code `SET_UNREADABLE` | inspect the record file the message names yourself; the guard never overwrites or removes it, and nothing was changed |
| exit 11, `unknowns` code `TARGET_UNCERTAIN` (from `set-plan`: the target is behind or diverged from its remote-tracking copy) | bring the local target up to date with a fast-forward (for example `git merge --ff-only '<remote-tracking refname>'` in the worktree that holds it; a diverged target is reconciled by you first), then plan again; nothing is fetched by this command |
| exit 19, `kind` `base` (the target moved since the investigation, so `base` is not its live tip) | rerun: the new preview investigates the new tip |
| exit 19, `kind` `revision` (the record changed after it was read), or a failed `--expect-revision` check | run `--status`, then redo with the revision it shows; after a converge apply that stopped on it, rerun: merges already made are recorded without merging again |
| exit 12 or 24 (invalid spec or a name clashing with the repository; the message names the field) | fix that field in the partition and prove it again; a plan over a limit (more than 12 lanes, a sheet over 4096 characters, more than 200 manifest entries) must be smaller |
| exit 10 or 11 from `set-plan` (a lane conflicts with, or could not be compared with, another claimant) | the guard names the lane, the claimant and the files: shrink or split that lane's manifest, wait until the other branch is merged, retire dead branches with `/GitCleanup`, or release the other claim yourself (`<guard> release --branch '<branch>'`, refused while its branch has unmerged work); `set-plan` never reads an override; for an unknown, establish the fact it names |
| exit 13 (claim lock timeout) after its one retry | wait until the other guard call is done, then rerun |
| exit 14 or 15 naming a lane, or a planned worktree path already in use | choose another branch name or worktree path in the partition; never reuse an existing branch |
| exit 15 naming `agent/<set>/integration` (a fresh `set-plan` refuses while it exists) | rename it yourself (`git branch -m '<old>' '<new>'`) or, after reviewing it, delete it yourself, or name another set |
| exit 14 `lane_in_set` or exit 16 `blocked_set` from a plain `plan --amend` or `release` of a claim of a set | use the set's own forms: `/GitPlan <set> --amend --expect-revision <n>`, `/GitPlan <set> --release` |
| exit 16 from `--amend` (`blocked`: `UNMERGED_WORK` or `DIRTY_WORKTREE` for a lane to remove, `SHRINK` for a manifest cut below files the lane changed) | keep the lane, or keep those files in its manifest, or have its owner merge, commit or revert that work first |
| exit 16 from `--release` (`blocked` names each lane: `NOT_INTEGRATED`, `UNMERGED_WORK`, `DIRTY_WORKTREE`, `CLAIM_UNUSABLE`) | integrate the lane with `--converge --apply` and land it (`--land`, or yourself): a lane branch not yet in the target is `UNMERGED_WORK`; commit, stash or discard in a dirty worktree; to give the plan up instead, run `<guard> set-release --set <set> --abandon` yourself, which the guard allows only while no lane branch holds commits that are not in the target and no lane worktree is dirty; the command never abandons |
| exit 16 from `set-update` (`blocked` reason) | `HEAD_MISMATCH` or `NOT_MERGED`: the lane or the integration branch moved since the survey, so run `--status` and rerun; `BRANCH_MISSING`, `DIRTY_WORKTREE`, `OPERATION_IN_PROGRESS`, `NO_MERGE_BASE`: the row of the finding of the same name |
| exit 22, `OUT_OF_LANE`, `SHARED_CHANGE` | the lane owner reverts the files outside its manifest, or `--amend` adds them to the lane that owns them by design (never to two lanes); then the owner records `ready` again |
| `STALE_PLAN` | `--amend --expect-revision <n>`: the new preview investigates the new tip and the amendment moves `base` to it; a lane whose files `target_overlap` lists should take the new tip: its owner merges `'<target sha>'` into the lane branch in its worktree, then records `ready --head '<tip>'` again (a lane is never rebased) |
| `BLOCKED` | clear what blocked the lane (its note in the view), then record it `--state active` and continue as for `NOT_READY`; the guard decides which transitions it accepts |
| `NOT_READY` | the owner finishes the lane and records it: `<guard> set-update --set <set> --expect-revision <rev> --lane <id> --state ready --head '<tip>'` (first `--state active` for a planned lane; `<rev>` is `record.revision` of `<guard> set-show --set <set> --json`, and exit 19 means read it again); an active lane that holds commits can instead be included with `--include-active` |
| `WAITING` (a dependency is not integrated) | finish and integrate the dependency first, or `--amend` the dependency away if it is not real |
| `MISSING_BRANCH` | create the lane with the `git worktree add` line the apply report printed, or `--amend` the lane away |
| `DIRTY`, `IN_PROGRESS` | in the lane's worktree commit, stash or discard the changes, or finish or abort the merge, cherry-pick, revert, rebase, am or bisect; when the tip changed, record `ready` again |
| `NO_MERGE_BASE` | the lane branch was not cut from the target: `--amend` the lane to a new branch name and have its owner redo the work there |
| `MOVED` | the lane gained commits after it was recorded ready: the owner records `--state ready --head '<tip>'` again (a ready lane may record a new head) |
| `CLAIM_DRIFT` | `--amend --expect-revision <n>` with the lanes unchanged rewrites the claim from the record |
| `PREDICTED_CONFLICT` | the owner merges the target tip into the lane, resolves it there and records `ready` again; a conflict stops the apply |
| apply stopped by a conflict | the report names the lane, the files, the error text and the integration start SHA; completed merges stay on the integration branch and their lanes stay `integrated`. To resolve it, the lane owner merges the integration start SHA into the lane branch in its worktree (`git merge '<sha>'`), resolves and commits there, records `ready --head '<tip>'` again, and the rerun resumes. To undo the run instead, restore the integration branch to its start SHA yourself, record every lane this run integrated with `<guard> set-update ... --state blocked` (and `--state active` again when it resumes), and re-plan with `--amend` if the partition must change |
| apply stopped because a `set-update` failed after a merge | the merge stays on the integration branch and is not recorded: run `--status`, then rerun, which records the lane without merging it again |
| apply stopped by a refused switch, by a guard denial of the integration branch's creation, or by a merge that failed without a conflict (a hook, a lock file) | fix what the quoted text names (a denial is the guard's: never `override`, ask the user; the claim of that branch is the one `set-plan` registered, see the missing-claim gate row); completed merges stay and nothing was landed |
| apply stopped by a failed check | fix what it names, on the integration branch by a commit of your own or in the lane (then record the lane `ready` again), then rerun; the check ran on the merged result; completed merges stay and nothing was landed |
| `LAND_REFUSED`: the target moved since the integration start SHA (the lanes are independent of what landed, `target_overlap` was empty) | merge the target tip into the integration branch yourself while it is checked out (`git merge '<target sha>'`), then rerun with `--land`: the checks run on the combined result, and `--ff-only` then succeeds |
| `LAND_REFUSED`: a recorded head is not in the integration branch | the integration branch lost a merge: restore it as in the row for a missing integration branch |
| creation stopped: a lane's worktree path or branch exists (only one of the two), or git or the guard hook refuses it | move or remove the directory yourself (the command never deletes), or `--amend` the lane to another path or branch name; the claims of the set cover exactly the registered branches and paths, so a guard denial is quoted, never worked around and never overridden by the command |

### Investigation

Read-only: nothing is fetched, no network is used and nothing is written. The task to split is the work the user described in this conversation; when none can be identified, ask for it once before step 7 (steps 1 to 6 do not need it). Every command below is run as an argument list from the invoking worktree (`<top>` is its top level, from `git rev-parse --show-toplevel`), takes its SHAs from the listing of step 3, and reads code only from the target commit `<sha>`, never from a working tree, so the plan describes one commit.

1. `<guard> version --json`: the gate on the guard.
2. `git -C <top> status --porcelain=v1 --branch --untracked-files=all` and `git -C <top> worktree list --porcelain`: every worktree with its branch, HEAD, locked, prunable and detached state, and the in-progress state of each as section 6 defines it.
3. `git -C <top> for-each-ref --format='%(refname)%09%(objectname)%09%(upstream)%09%(upstream:track)' refs/heads`, and `git -C <top> for-each-ref --format='%(refname)%09%(objectname)' refs/remotes refs/tags`: branches with SHAs, upstream refnames and ahead/behind, remote-tracking refs and tags. The target's SHA is `<sha>`.
4. `<guard> list --json`: every open claim (`branch`, `state`, `entries`, and `set` with `lane` or `role` for the claim of a set), which is what the plan is judged against, except a claim with `role` `integration`, which claims no files and is never a claimant.
5. Remote freshness, local only: for the target's upstream and for every remote-tracking ref `<remote>/<target>` of step 3, `git -C <top> rev-list --left-right --count 'refs/heads/<target>...<remote-tracking refname>'`; the report says "remote freshness: local-only". A target behind or diverged from one of them is refused by the guard (exit 11, `TARGET_UNCERTAIN`).
6. Names already taken: from steps 2 and 3, every branch, tag and worktree path that a planned name must not equal, collide with by case, or share as a ref prefix, and the integration branch `agent/<set>/integration`, which must not exist.
7. Layout: `git -C <top> -c core.quotePath=false ls-tree -r --name-only <sha>` (for a tree too large to read, `ls-tree --name-only <sha>` and the same with `<dir>/` for the directories that matter): top-level directories, packages, modules, test directories and file counts.
8. Entry points and the repository normal checks: `git -C <top> show <sha>:<path>` for `README*`, `CONTRIBUTING*`, `AGENTS.md`, `CLAUDE.md`, the build and test files (`package.json`, `Makefile`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`, `*.csproj`) and the CI definition (`.github/workflows/`, `.gitlab-ci.yml`); the build, test and lint commands they name are the checks.
9. Ownership and shared files, from the step 7 listing and `git show` where a file must be read: `CODEOWNERS` (also under `.github/` and `docs/`), lockfiles, generated files (`git -C <top> grep -l -I -i -E 'do not edit|auto-generated' <sha> -- '<dir>'`), registries and barrel files (`__init__.py`, `index.*`, `mod.rs`, route, plugin and command tables), migration directories and their numbering, version files, changelogs.
10. Churn: `git -C <top> log --since='90 days ago' --no-merges --name-only --pretty=format: -n 500 <sha>`; the files and directories changed most often are hot spots and go whole into one lane.
11. Coupling: `git -C <top> grep -n -I -E '<import pattern of the language>' <sha> -- '<dir>'` for each candidate boundary. Imports across a boundary are hints, not proof: the guard does not detect semantic coupling across files, so coupled files go into the same lane.

### Partition rules

1. A plan has at most 12 lanes, and aims at 2 to 6.
2. A lane owns whole directories where it can, and its manifest lists everything the lane writes (`references/lane-split.md` section 4: at most 200 entries, globs only as that section allows).
3. Tests go with the code they test, and coupled files (imports across a boundary, a hot spot, files that must change together) go into the same lane.
4. Every shared file (lockfile, generated file, registry, barrel file, migration numbering, version file, changelog) belongs to exactly one lane and lies inside that lane's manifest, or it is a post-merge task of the integration step, listed in the sheet and in `notes`.
5. A dependency is declared only where one lane needs the result of another (interface first), and dependency chains are kept short.
6. Every lane owns at least one file, and every path the task changes lies in exactly one lane or is shared.
7. Lane ids are `L1`, `L2`, ... (the pattern is `[A-Za-z0-9_-]{1,16}`, unique ignoring case, and `integration` is never an id). The lanes are listed in merge order, dependencies before dependents, so that the guard's `merge_order` is the listed order. A lane branch is `agent/<set>/<id lower-cased>`, a lane worktree is `<parent directory of the main worktree>/<repository directory name>-<set>-<id lower-cased>`, unless the user names them.
8. A branch name is safe as section 6 **Names** defines it, equals no existing branch or tag, collides with none by case or as a ref prefix, and is neither `agent/<set>/integration` nor under it; a worktree path is absolute, does not exist, and neither lies inside nor contains any worktree of the repository.

### The spec and the sheet

The spec is JSON, written to a scratch file outside every worktree (the session scratchpad or the system temporary directory) and passed as `--spec '<file>'`; where no such directory is writable it is given on standard input with `--spec -`. The scratch file is no part of the record and is the preview's only write.

```json
{"v":1,"title":"<the task, one line, at most 120 characters>","base":"<target sha>","sheet":"<the sheet text, at most 4096 characters>","notes":["<risk, or post-merge: task>"],
 "shared":[{"path":"<file>","owner":"<lane id>"}],
 "lanes":[{"id":"L1","title":"<at most 60 characters>","branch":"<branch>","worktree":"<absolute path>","paths":["<manifest entry>"],"depends_on":["<lane id>"],"acceptance":"<at most 300 characters>"}]}
```

`notes` holds at most 5 items of at most 200 characters: the risks and the post-merge tasks (each starting `post-merge:`). The sheet is built from the spec and says nothing the spec does not:

```text
# Plan <set> -> <branch>  rev <n>  base <sha7>
- [ ] L1 <title> | branch <branch> | owns <paths> | needs <ids or -> | accept <one short phrase>
- [ ] L2 ...
- [ ] merge L1 -> L2 -> L3 into agent/<set>/integration; run <repository checks>; land on <branch>
Shared: <file> -> L1 ; <file> -> L2 ; <post-merge task> -> merge step
Risks: <at most 5 short items>
```

- The lane lines are in merge order; `owns` lists the manifest entries separated by commas (a long list shortens to directories, then ends with `+N more`); `rev` is the revision the registration records (1 for a new set, `<n>+1` for an amendment); the merge line names the checks found, or `not identifiable`.
- `--status` and `--converge` regenerate the checklist from the record, never from the stored sheet text: the header carries the record's revision and base, and a lane line is `- [x] <id> <title> | <state> | head <sha7> | branch <branch>` when the lane is `ready` or `integrated` and `- [ ] ...` with `head -` when it has none. The merge line is `[x]` once every lane is `integrated`.
- Below the checklist, **Remaining TODO** is a numbered list in this order, an empty part left out and an empty list written `nothing remains`: each lane that is not `ready` or `integrated` (`finish <id>: <state>; accept <acceptance>`); each `ready` lane that is not `integrated` (`merge <id> <head7>`, in merge order); `run the repository checks on agent/<set>/integration` while a lane is `integrated` and the target does not contain the integration branch tip; each `post-merge:` note; `land agent/<set>/integration on <branch>` when every lane is `integrated` and the target does not contain the integration tip; `release the set` when every lane is `integrated`, every lane worktree is clean and the target contains every recorded head (`git merge-base --is-ancestor '<head>' '<target sha>'`).

### Preview behavior (`<set> --into <branch>`, default, read-only)

1. **Gates** (any failure stops the whole command, and nothing is written; every gate is evaluated, and the report names every failed gate with its remedy): the guard; the `<set>` name; the target gates of section 6; and the set not existing (`<guard> set-show --set <set> --json` exits 21 when it is free; 0 means it exists, 23 a newer format, 11 an unreadable record). The invoking worktree's state is no gate here: a plan writes no worktree.
2. **Investigate** (**Investigation**), partition (**Partition rules**), write the spec and the sheet.
3. **Prove** the plan: `<guard> set-plan --set <set> --target '<branch>' --spec '<file>' --dry-run`. Exit 0 means all of this held and nothing was written: the spec version, at most 12 lanes, unique ids and branches, valid names, distinct worktrees outside each other and outside every worktree of the repository, every manifest valid, every pair of manifests disjoint (exact glob intersection), `depends_on` ids existing and acyclic, every shared path inside its owner's manifest, the target a local branch that is not behind or diverged from a remote-tracking copy, `base` equal to the live target tip, no lane branch and not `agent/<set>/integration` existing yet, and every lane judged against the other claimants (conflicts and unknowns deny the whole set and name the lane). A failure the partition can fix (exit 24 or 12, exit 14 or 15 naming a lane, exit 10 with `overlaps`: two of its own lanes) is fixed in the partition and proved again; a failure caused by something outside the plan (another claimant in `lanes`, a moved target, a target behind or diverged from its remote-tracking copy, an existing integration branch) is reported with its remedy and the readiness is `BLOCKED`. The report shows only the proved plan.
4. **Report** with the readiness: `READY` when every gate holds and the proof exited 0, with the next command `/GitPlan <set> --into <branch> --apply` (`--lang` as given), and the note that `--create` adds the lane branches and worktrees (without it the apply prints the commands); otherwise `BLOCKED` with every failure and its remedy.

The preview does not fetch, register, create or merge anything.

### Apply behavior (`--into <branch> --apply [--create]`)

1. **Re-check** under the Acceptance rule: the gates, that `base` still equals the live target tip, and that the previewed spec file is still there and unchanged (with `--spec -`, the previewed text is given again, unchanged). A difference stops with a new preview.
2. **Register**: `<guard> set-plan --set <set> --target '<branch>' --spec '<file>'`. Exit 0 writes every lane claim (each with `set=<set>` and `lane=<id>`), the claim of the integration branch and the record at revision 1, every lane `planned`, atomically: on any failure the guard leaves no partial state. Read the record back with `<guard> set-show --set <set> --json` and stop if a lane's id, branch, worktree (compared with `/` separators) or manifest differs from the spec.
3. **Create** (only with `--create`), for each lane of the record in order, only a registered lane, at its registered worktree path, from the recorded `base` (checked with `git -C <top> cat-file -e '<base>^{commit}'`): a lane whose branch and path both exist is already created and is skipped, and when only one of them exists the step stops; otherwise run `git -C <top> worktree add -b '<branch>' '<worktree>' '<base>'`, then confirm that `git -C '<worktree>' rev-parse HEAD` prints the base. A guard denial or a git failure stops the step: lanes already created stay and are reported, and nothing is retried in another form. A created lane stays `planned`; its owner records `active` when it starts. Without `--create` the report prints that same `git worktree add` line for each lane (ref names and paths in single quotes), for the user to run. The integration branch is never created here.
4. **Report**: the revision, the registered lanes, what was created or printed, the checklist, and for each lane a handoff (branch, worktree, manifest, dependencies, acceptance, and the two `set-update` lines of **Remedies** `NOT_READY`).

### Status (`--status`, read-only)

1. Gates: the guard; the `<set>` name; `<guard> set-show --set <set> --drift --json` exits 0 (21 unknown, 23 newer format, 11 unreadable).
2. From that output take the **view**: the record, and per lane whether its branch exists, its tip, its commits ahead of `base`, its worktree, clean and in-progress state, its recorded state and head and its claim; the files each lane changed outside its manifest, the files changed by two lanes, whether the target moved since `base` and the files it changed that intersect a lane manifest, the lanes whose tip differs from the recorded head, and the merge order. A `target_tip` of null is reported (the target branch is gone), and so are the guard's `warnings`. Add, read-only, whether the integration branch exists and whether the target contains it, and for each `integrated` lane whether its head is an ancestor of the target.
3. Evaluate every lane with the **Lane findings** and print the regenerated checklist and **Remaining TODO** (**The spec and the sheet**). The next command is `/GitPlan <set> --converge` when a lane is `ready` and not `integrated`, or when only the land remains; `/GitPlan <set> --release` when only the release remains; and none otherwise (the report names what the lane owners must do).

### Amend (`--amend --expect-revision <n> [--apply [--create]]`)

1. **Gates**: the guard; the set exists; `<n>` equals the record's `revision` (else stop with the `kind` `revision` row of **Remedies**, naming the current revision); the record's target exists locally and is not `main`.
2. **Investigate** again (**Investigation**), then build the amended spec from the record and what the user asked to change: surviving lane ids keep their branch and worktree, new lanes follow the **Partition rules**, and `base` is the live target tip. A lane whose branch holds commits that are not in the target is kept, and its manifest keeps every file it changed (the guard refuses otherwise, exit 16).
3. **Prove**: `<guard> set-plan --set <set> --target '<target>' --spec '<file>' --amend --expect-revision <n> --dry-run` (the checks of the preview, plus the revision). Exit 0 with `unchanged` true means the amendment changes nothing: say so and stop. Otherwise the readiness is `READY` or `BLOCKED` as in the preview, and the next command is the same line with `--apply`.
4. **Apply** (Acceptance rule): the same call without `--dry-run`. Lanes whose id survives keep their state; the revision becomes `<n>+1`; the guard replaces the claims in the same atomic write and moves `base`, and the `base` of every surviving lane claim, to the live target tip. With `--create`, only lanes whose branch and worktree do not exist are created, as in **Apply behavior** step 3. A lane cut from an older `base` needs nothing: the guard measures what it changed against the merge base with the current target tip.

### Converge preview (`--converge [--include-active]`, read-only)

1. **Gates** (every gate is evaluated, the report names every failed one with its remedy, and a report with a failed gate has no merge plan): the guard; the set exists; the record's target exists locally (`target_tip` is not null); the integration branch is consistent with the record (absent while the record's `integration` is empty and `<guard> list --json` has the claim row of this set with `role` `integration`; or present, named by the record or not yet recorded, and sharing history with the target; any other state fails, **Remedies**); the invoking worktree is on the target, or on the integration branch when that exists, and is clean and not in progress, and the target is not in progress anywhere; `STALE_PLAN`; any failing finding of **Lane findings**.
2. **Status report**: everything of **Status** steps 2 and 3, evaluated with `--include-active` when given, so the preview and the apply after it judge a lane alike.
3. **Merge plan**: the lanes to merge (the `READY` ones) in the order of `drift.merge_order`; each with its recorded head, `PREDICTED_CONFLICT` where it applies, and the repository normal checks to run on the result. The preview also says whether `--land` would be possible (it is when the target tip is an ancestor of the integration branch tip, so that `git merge --ff-only` can succeed; a new integration branch is cut from the current tip), and that the record's `post-merge:` tasks are not done by this command.
4. **Readiness**: `READY` when no gate fails and every lane is `READY` or `INTEGRATED`: one run of the next command merges all of them, and `--land` can follow in the same run. `PARTIAL` when no gate fails but some lane is pending: the next command merges the `READY` lanes and the report lists what each pending lane needs. `BLOCKED` when a gate fails. The next command (not for `BLOCKED`) is `/GitPlan <set> --converge --apply --expect-revision <revision shown>` with `--include-active` and `--lang` as given; `--land` is only suggested in words, never added to the line.

The preview does not merge, switch, create, record, fetch or delete; `git merge-tree --write-tree` may create unreachable objects but no refs, index or worktree changes.

### Converge apply (`--converge --apply [--include-active] [--land] [--expect-revision <n>]`)

1. **Re-survey and record the plan** by running the preview logic fresh: the lane order, each lane's recorded head, the target tip, the record's revision and the state of the integration branch. A mismatch of `--expect-revision <n>` with the record stops the run. Compare with the most recent converge preview or apply report of the same set earlier in this conversation, if any: a lane head, the target tip or the revision that differs stops the run with a new preview, except for what an interrupted run of this command recorded itself. Stop on any failed gate or failing finding, and on `--land` while a lane is not `READY` or `INTEGRATED`. Without an earlier plan the recorded plan is the plan.
2. **Include active lanes** (only with `--include-active`): for each such lane run `<guard> set-update --set <set> --expect-revision <rev> --lane <id> --state ready --head '<tip>'`, which also proves that every file the lane changed, measured against the merge base with the current target tip, lies inside its manifest (exit 22 stops the run and names the files). Every successful `set-update` makes the record one revision newer; the next call passes the `revision` of its result.
3. **Integration branch**, only when at least one lane is to be merged or `--land` was typed: when it is absent and the invoking worktree is on the target, run `git -C <top> switch -c 'agent/<set>/integration' '<target sha>'` (the CURRENT target tip; that SHA is the integration start SHA). The guard allows this plain creation because `set-plan` registered the claim of that branch, which is exempt from overlap judgement (the creation is judged for the branch name and the existence of that claim only, never against a lane's manifest or commits); a refusal, or a denial by the guard's hook, stops the run before any merge, is quoted in the report and is never overridden or retried in another form. When the branch exists and the invoking worktree is still on the target, run `git -C <top> switch --no-overwrite-ignore 'agent/<set>/integration'`; on the integration branch already, nothing is needed.
4. **Merge** each `READY` lane in the merge order, inside the invoking worktree:
   1. Recheck that the lane tip still equals the recorded head; if not, stop.
   2. When the head is already an ancestor of the integration branch or of the target (an earlier run merged it, or the lane has no commits of its own), skip to step 4.5.
   3. Run the ignored-file overlap test of section 6 apply step 4.3 against the lane's changed paths since its merge base; an overlap stops the run.
   4. Run `git -C <top> merge --no-ff -m 'Merge lane <id> of plan <set> into agent/<set>/integration' '<recorded head>'`. Never `--no-verify`, `-X ours`, `-X theirs`, `--allow-unrelated-histories`, squash or rebase.
   5. Record it: `<guard> set-update --set <set> --expect-revision <rev> --lane <id> --state integrated --head '<recorded head>' --integration 'agent/<set>/integration'`.
   6. On a conflict list the unmerged paths (`git -C <top> diff --name-only --diff-filter=U`), run `git -C <top> merge --abort`, and stop; never resolve it with ours or theirs, and never by hand. Completed merges stay on the integration branch only. The report names the lane, the files, the error text, the integration start SHA and the conflict row of **Remedies**, which also gives the undo path.
   7. On any other failure of the merge or of the `set-update`, stop; a merge that is made but not recorded is recorded by the next run (step 4.2).
5. **Validate** with the repository normal checks in the invoking worktree, on the integration branch, once at least one lane was merged or recorded, or `--land` was typed. A failed check stops the run before any land; "not identifiable" is reported as "not validated" and does not stop it.
6. **Land** (only with `--land`, after step 5 did not fail): re-read the record and the target tip, and continue only when every lane is `integrated`, every recorded head is an ancestor of the integration branch tip, the target tip is an ancestor of the integration branch tip (it still sits at the integration start SHA), the invoking worktree is clean and not in progress, and the target is checked out nowhere else. Then run `git -C <top> switch --no-overwrite-ignore '<target>'` and `git -C <top> merge --ff-only '<integration tip sha>'`, and confirm that `git rev-parse refs/heads/<target>` equals that SHA. When a condition fails, report `LAND_REFUSED` with the failed condition and both SHAs and do nothing else (**Remedies**); the invoking worktree stays on the integration branch.
7. **Report** in the reply language: the plan acted on, each merge (lane, head, merge commit), each `set-update`, skipped lanes with their findings, where and why the run stopped, the target's start and end SHA, the integration branch tip, the validation result, the land result, the regenerated checklist with **Remaining TODO**, and that nothing was pushed (publishing is the user's decision).

A rerun after an interruption or a conflict starts from a fresh survey and resumes on the same integration branch: lanes already `integrated` are skipped, and the earlier moves of the run do not make its plan stale (step 1).

### Release (`--release`)

1. Gates: the guard; the `<set>` name; `<guard> set-show --set <set> --drift --json` exits 0. Print the final checklist and **Remaining TODO** first, because the record is removed.
2. Run `<guard> set-release --set <set> --reason integrated`. Exit 0 removes the lane claims, the integration claim and the record and appends to the guard's audit log; exit 16 means a lane is not integrated, is not yet in the target or has a dirty worktree, and the guard names it (**Remedies**).
3. Report the released claims (`released`), and that the lane branches, their worktrees and the integration branch are not touched: with the claims gone, nothing of the set blocks `/GitCleanup` any longer, which retires the merged ones.

### Hard stop conditions

Never: push, force-push or touch a remote or remote-tracking ref, and never fetch or use the network; move, reset, merge into or delete `main`, or take `main` as the target; delete a branch or a worktree, or run `git worktree prune`; use `override`, `arm`, `disarm` or `install`, run the guard's plain `plan` or `release` on a claim of a set, or edit `.git/magos`; write the claim store or the set record other than through `magos_guard.py set-plan`, `set-update` and `set-release`; rebase, squash, cherry-pick or reset; merge anything except a recorded lane head into the integration branch, and (with `--land`) the integration branch into the target by one `--ff-only` merge; resolve a conflict with ours or theirs, or by hand; pass `--no-verify`, `-X ours`, `-X theirs` or `--allow-unrelated-histories` to a merge; create any branch or worktree other than a registered lane (at its registered path, from the recorded `base`) and the integration branch (from the target tip, in the invoking worktree); register a plan that no preview of this conversation showed, or any other spec than the previewed one; write inside a lane worktree (a lane is only read, and merged from its recorded head in the invoking worktree); shrink, amend or release the claim of a lane to make a conflict disappear; run a git or guard command as a shell string (section 6 **Argument safety**). Do not proceed when the skill or this reference could not be loaded; preview only.

### Output

Write every report in the reply language (Chinese unless `--lang` selects another one), headings and tables included. Each form prints exactly its own block.

Plan preview and amend preview (`--into`, `--amend`):

```text
Plan header (set, target and base SHA, remote freshness, revision to be recorded)
Gates (every failed gate with its remedy)
Investigation (3 to 6 bullets: git facts, code facts, shared files and hot spots)
Checklist (the sheet)
Lane table (per lane: id, branch, worktree, full manifest, needs, acceptance; shared files with their owner; the spec file path)
Changes (amend only: lanes added, removed or changed against the record, base old and new)
Exclusivity proof (lane pairs checked, shared files with their owner, dependency order, paths of the task in no lane: none, set-plan --dry-run result)
Checks against other claimants (claimants checked, warnings, unknowns, the verdict for each lane)
Not touched (existing branches, worktrees, claims, remotes, main; the preview wrote only the scratch spec file)
Readiness: READY / BLOCKED, failures + remedies, next command
```

Plan apply and amend apply (`--apply`):

```text
Plan acted on (the previewed spec, set, revision recorded)
Registered (lanes, claims including the integration claim, revision)
Created branches and worktrees (only with --create), or the git worktree add lines to run
Skipped or stopped items + reasons
Checklist (the sheet)
Lane handoff (per lane: branch, worktree, manifest, dependencies, acceptance, the set-update lines)
Not touched
Remaining risks
```

Status (`--status`):

```text
Header (set, target, base SHA, revision, integration branch state) and gates
Checklist (regenerated)
Lane table (state, head, findings with their remedies; drift)
Remaining TODO
Next command
```

Converge preview (`--converge`):

```text
Header (set, target tip, base SHA, revision, integration branch state)
Gates (every failed gate with its remedy)
Checklist (regenerated) and lane table
Merge plan (order, PREDICTED_CONFLICT, repository checks to run, land prediction)
Remaining TODO
Not touched
Readiness: READY / PARTIAL / BLOCKED, failures + remedies, next command
```

Converge apply (`--converge --apply`):

```text
Plan acted on (lane order, recorded heads, target tip, revision)
Gates
Applied operations (switches, merges, set-update calls)
Skipped lanes + their findings
Stopped at (only when the run stopped: lane, files, error text, integration start SHA, the row of Remedies)
Target start SHA -> end SHA, integration branch tip
Validation
Land result (only with --land)
Checklist (regenerated) and Remaining TODO
Not touched
Remaining risks (including: nothing was pushed)
```

Release (`--release`):

```text
Gates
Final checklist and Remaining TODO (printed before the record is removed)
Released claims
Not touched (lane branches, worktrees, the integration branch)
```

## Command Relationship

```text
/GitRecon
   ↓ repository map
/GitAnalyze <target>
   ↓ deep single-target evidence
/GitRecommend [goal]
   ↓ decision support
/GitPlan <set> --into <branch> [--apply] [--create]
   ↓ lanes planned up front (lane claims and set record), later merged as one whole by --converge [--apply] [--land]
/GitIntegrate <target>
   ↓ guarded integration mutation
/GitCleanup [--apply]
   ↓ guarded lifecycle cleanup
/GitConverge <branch> [--apply]
   ↓ guarded merge-everything-and-delete convergence
/GitSweep <branch> [--apply] [--push]
   ↓ GitConverge + guarded deletion of merged remote branches
```

`/GitRecon`, `/GitAnalyze`, and `/GitRecommend` are observation/advice commands. `/GitIntegrate` is an integration write-intent. `/GitCleanup` is preview-only unless `--apply` is explicit. `/GitConverge` is preview-only unless `--apply` is explicit; it merges unreviewed local branches only on the user's acceptance of the plan it prints. `/GitSweep` runs the same convergence and is the only command that deletes remote branches, and only those already merged into a branch the remote keeps; with `--push` it is also the only command that pushes commits, one fast-forward push of `<branch>`.

`/GitPlan` is preview-only unless `--apply` (or `--release`) is explicit. It plans the lanes before any sub-agent starts and converges them afterwards: only with `--apply` or `--release` does it write the claim store and the set record (always through the guard's `set-*` subcommands); only with `--apply` does it create lane branches and worktrees (`--create`) and merge the lanes into an integration branch of its own, plus one fast-forward of `<branch>` with `--land`; it never pushes and never deletes a branch or a worktree.
