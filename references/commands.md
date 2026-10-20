# Explicit Command Contracts

This reference defines the command-layer behavior for `multi-agent-git-orchestrator` v1.0.3.

These are **semantic command intents**. Canonical names use a leading `/`. A host may expose them as slash commands, palette actions, prompt aliases, or plain-text invocations. If slash commands are unsupported, accept the same name without `/`. The behavior must remain the same.

## Argument and Help Behavior

All seven commands accept `--help`. When it is present, show that command's usage, argument descriptions, defaults, and examples, then stop before inspecting or changing a repository. `--help` takes precedence over other arguments.

**Reply language.** All seven commands accept `--lang <language>`. It selects the language of everything the command says to the user: help text, questions, errors, reports (including the final report of a write command after a long run), and recommendations. When it is absent the reply is in Chinese (简体中文). The value is the next token: a language name or a common code (`English`, `en`, `日本語`, `ja`, `Français`); put a multi-word name in quotes. The option may appear anywhere among the arguments and may be combined with `--help`; help is then shown in the requested language, with flags and examples left untouched. Never translate command names, option names, branch or worktree names, paths, SHAs, Git commands, or status codes such as `BLOCKED_DIRTY`; a short gloss in the reply language next to a code is fine. Remove `--lang` and its value from the arguments before any other parsing, so it never becomes part of a goal, target, or branch name. If `--lang` has no value, or the value is not a language, explain the problem (in Chinese) and show the usage without executing the command.

Recognize only the options listed for each command. For an unknown option or a required option value that is missing or invalid, explain the issue and show the relevant usage without executing the command. If a required positional target is missing, ask the user for it. Host adapters should preserve the supplied argument text and route `--help` to this reference.

Host entry points are Claude Code `/GitRecon`, Hermes `/git-recon`, and Codex `$git-recon` (use the corresponding command name for the other six). Append the same arguments after the host-specific entry point.

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
- Codex adapters set `policy.allow_implicit_invocation: false`, so they run only when selected explicitly; the root skill keeps semantic activation. Hermes has no per-skill switch, so `git-integrate`, `git-cleanup`, `git-converge`, and `git-sweep` refuse to write unless invoked explicitly.
- If the shared rules (`SKILL.md`, `references/commands.md`) cannot be read, read-only commands may continue read-only and report the incomplete installation; `GitIntegrate` must not integrate, `GitCleanup` must not delete, `GitConverge` must not merge or delete, and `GitSweep` must not merge, delete, or push (preview only).
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
- **kept set**: `main` and target. Every other local branch is a **source**; `main` is also a merge source.
- **Names vs SHAs**: resolve every branch through its full refname (`refs/heads/<name>`) and record its SHA. Take the SHAs from one `git for-each-ref --format='%(refname) %(objectname)' refs/heads` listing, which reads each ref exactly; `rev-parse refs/heads/<name>` can read another branch's loose ref file on a case-insensitive filesystem. In every git command in this section, `<target>` and `<source>` in a revision argument mean `refs/heads/<name>` or the recorded SHA, never the bare name: a same-named tag wins bare-name resolution (`refname '<name>' is ambiguous`). Merge the recorded SHA.
- **Case collisions**: when two local branch names are equal ignoring case (`Feat` and `feat`), both are `UNKNOWN` whatever else applies (this is decided before the ordered classification below): neither is merged or deleted, because on a case-insensitive filesystem `refs/heads/<name>` can resolve to the other one and `git branch -d` on one can remove both. The report asks the user to make the names distinct safely: run `git pack-refs --all` first (then no name is a loose ref file, so each resolves exactly), rename one with `git branch -m`, and compare both tips with the recorded SHAs. A plain `git branch -m` on a colliding name can give the new name the other branch's tip and delete both old refs. If the target or `main` is one of them, that is a gate failure.
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
UNKNOWN                       a needed fact could not be established; neither merged nor deleted
```

and zero or more **delete blockers**. A delete blocker never stops a `MERGE` source from being merged; it only keeps the branch and its worktree:

```text
BLOCKED_DIRTY                 its worktree is not clean
BLOCKED_LOCKED                its worktree is locked
BLOCKED_ACTIVE_OWNER          its worktree has an active owner, or it is checked out in the main worktree that is not the invoking one
BLOCKED_IGNORED_FILES         its worktree holds ignored files (paths listed in full); lifted by --discard-ignored
BLOCKED_SUBMODULE             its worktree has initialized submodules (`git worktree remove` refuses them)
BLOCKED_UPSTREAM_OF_KEPT      a branch that will remain tracks this branch (`branch.<x>.remote` is `.` and `branch.<x>.merge` is `refs/heads/<this>`), or a lane record names it as a dependency of a branch that will remain
```

A branch **will remain** when it is `main`, the target, a source whose merge status is not `MERGE` or `CONTAINED`, or a source with a delete blocker. Re-evaluate `BLOCKED_UPSTREAM_OF_KEPT` until nothing changes, so a chain `c -> b -> a` with `c` dirty keeps both `b` and `a`.

### Remedies

Every failed gate, delete blocker, `UNKNOWN` status, `PREDICTED_CONFLICT`, and stop of an apply (a conflict, a failed check) in a report is followed by the action that lifts it. The command never performs these actions; they are the user's, and the report writes each with the real path or name:

| Finding | Remedy |
|---|---|
| gate: target missing locally | name an existing local branch (`git branch --list`), or create it deliberately with `git branch <name> <start>` |
| gate: target is `main` | name the integration branch instead of `main` |
| gate: local `main` missing | `git branch main <remote>/main` once the remote-tracking ref exists |
| gate: a name equals another when case is ignored | make the names distinct with the procedure under **Case collisions** |
| gate: prunable (missing-directory) worktree entry for the target or `main` | check `git worktree list --porcelain`, then `git worktree remove <path>` or restore the directory |
| gate: target checked out in another worktree | run the command from that worktree (`cd <path>`) |
| gate: invoking worktree detached | `git switch <target>` |
| gate: invoking worktree dirty | commit the changes, or `git stash push --include-untracked`; `git status --short --untracked-files=all` lists what counts |
| gate: invoking worktree or target in progress | finish or abort the merge, cherry-pick, revert, rebase, am or bisect in that worktree |
| `BLOCKED_DIRTY` | commit, stash or discard the changes in the worktree, then rerun |
| `BLOCKED_LOCKED` | `git worktree unlock <path>` once nobody uses it |
| `BLOCKED_ACTIVE_OWNER` | let the owner finish, or release the lane's claim when its lane is merged or abandoned; for a branch checked out in the main worktree that is not the invoking one, switch that worktree to another branch (`git -C <path> switch <other>`) or run the command from it |
| `BLOCKED_IGNORED_FILES` | add `--discard-ignored` (the listed files are lost) or move the files out of the worktree |
| `BLOCKED_SUBMODULE` | deinitialize the submodules (`git -C <path> submodule deinit --all`), then rerun |
| `BLOCKED_UPSTREAM_OF_KEPT` | `git branch --unset-upstream <x>` on the branch that tracks it, or retarget that branch |
| `BLOCKED_IN_PROGRESS` | finish or abort the operation in its worktree |
| `BLOCKED_UNRELATED_HISTORY` | none: the branch stays; merge it by hand only on purpose |
| `PREDICTED_CONFLICT` | merge that source into the target by hand and resolve it (`git merge refs/heads/<source>`), then rerun; a conflict stops the apply |
| `UNKNOWN` | establish the fact its evidence names; for a case collision, the rename procedure |
| apply stopped by a conflict | the report names the failing source, the error text and the target's start SHA; merge that source into the target by hand and resolve it (`git merge refs/heads/<source>`), or restore the start SHA, then rerun; completed merges stay |
| apply stopped by a failed check | fix what the check names (it ran on the merged result), then rerun; completed merges stay and nothing was deleted |

### Preview behavior (default, read-only)

Collect and report:

1. **Gates** (any failure stops the whole command, even for a preview, and nothing is written): target missing locally; target is `main`; local `main` missing; the target or `main` equals another local branch name when case is ignored; target or `main` is checked out only in a prunable (missing-directory) worktree entry; target is checked out in a worktree other than the invoking one (run the command from that worktree); the invoking worktree is detached, dirty (untracked files count), or in progress; target is in progress anywhere. Every gate is evaluated, and the report names every failed gate with its remedy (**Remedies** below), so one run shows everything the user must clear before the next one. A report with a failed gate has no plan: the rest of the preview is not made.
2. **Plan header**: target and `main` with SHAs, the invoking worktree, and the recorded tip of every local branch. Report a same-named tag for any branch, the target included. Report `main` being behind or ahead of `origin/main` when the remote-tracking ref exists; remote freshness is local-only.
3. **Sources to merge**, in merge order: `main` first, then the rest by descending unique-commit count (`git rev-list --count refs/heads/<target>..<sha>`), ties by refname. For each: SHA, exact unique-commit count, and its commit list. A commit list may be shortened only with an explicit "(N more)"; counts and branch sets are never truncated. When `git merge-tree --write-tree` exists, test each source against the current target tip and mark it `PREDICTED_CONFLICT` if it exits 1. This is a hint only: it cannot see a clash between two sources, which appears when the second one merges.
4. **Contained sources**: delete only.
5. **Classification of every source**: its merge status and every delete blocker, each with evidence. For every worktree that will be removed, its path and whether its owner is recorded ("owner: not recorded" otherwise).
6. **Expected final state**: the local branches that will remain (each with its reason and next step) and the worktrees that will be removed. If any source remains, say plainly that "only `main` and `<branch>`" will not be reached.
7. **Not touched**: remote branches and remote-tracking refs (listed), tags, stashes, detached worktrees, and the main worktree unless it is the invoking one.
8. **Validation**: the repository's normal checks if they can be identified, or "not identifiable".

The preview does not merge, switch, delete, prune, or fetch. `git merge-tree --write-tree` may create unreachable objects but no refs, index, or worktree changes.

### Apply behavior (`--apply`)

1. **Re-survey and record the plan.** Run the preview logic fresh and record the whole plan before running any command that changes the repository: every local branch with its tip SHA, merge status, and delete blockers; the merge order; the expected final branches; and the worktrees to be removed. The plan goes into the final report (step 7); it need not be printed before the first write. Compare it with the most recent GitConverge preview or apply report earlier in this conversation, if any. Stop and show a new preview when any source tip or `main` differs from it, or when the target moved in any way other than through merge commits whose second parent is a source tip recorded in that plan (an earlier `--apply` that was interrupted). A branch that is not in that plan, and a worktree that appeared since it, are reported as "appeared after preview, untouched": such a branch is neither merged nor deleted, and a previewed branch that gained a worktree is still merged as planned but neither it nor its worktree is deleted. Stop on any gate failure or `UNKNOWN` needed for a write. Without an earlier plan the recorded plan is the plan; the run acts on exactly that plan and nothing that appears later.
2. **Record** the target's start SHA and every source and delete-set tip.
3. **Switch** the invoking worktree to target if it is on another branch, using `git switch --no-overwrite-ignore <target>`. A refusal stops the command before any merge. The command never switches any other worktree and never switches to `main`.
4. **Merge every source whose merge status is `MERGE`, in order, whatever its delete blockers**, inside the invoking worktree:
   1. Recheck that the source tip still equals the recorded SHA; if not, skip it and report.
   2. Skip it if it is now an ancestor of target (an earlier source contained it).
   3. List the paths the source changed since the merge base (`git diff --name-only <merge-base> <sha>`) and the ignored entries in the invoking worktree (`git ls-files --others --ignored --exclude-standard --directory`; a trailing `/` marks an ignored directory). Run both listings from the top level of the invoking worktree as `git -C <top-level> -c core.quotePath=false <command>` (`<top-level>` from `git rev-parse --show-toplevel`): then both list paths relative to the worktree root, and neither prints a non-ASCII path C-quoted (`"\346\236\204..."`, which none of the comparisons below can match). If the worktree has ignored entries and a line of either listing is still wrapped in double quotes (a quote, backslash, or control character in the name), count every changed path as overlapping. They overlap when a changed path equals an ignored entry, when one lies under the other (a directory/file clash), or, if `git config --bool core.ignorecase` is true, when they match ignoring case. If they overlap, stop: a merge silently overwrites ignored files (`--no-overwrite-ignore` is not honored by merge). Completed merges stay.
   4. Run `git merge --no-ff -m "Merge branch '<name>' into <target>" <recorded-sha>`. Use another merge shape only when repository policy requires it, and never squash or rebase, because the later ancestry check needs real merge ancestry. Never pass `--no-verify`, `-X ours`, `-X theirs`, or `--allow-unrelated-histories`.
   5. On any failure: run `git merge --abort` if a merge is in progress, then **stop the whole command and delete nothing**. Keep completed merges and report the failing source, the error text, the target's start SHA, and how to restore it.
5. **Validate** with the repository's normal checks when identifiable. If they fail because of the merge, stop before any deletion and report. If they cannot be identified, report "not validated" and continue; deletion is still gated by the ancestry check below.
6. **Delete** every source whose merge status is `MERGE` or `CONTAINED` and that has no delete blocker. Recheck immediately before each write: (a) the tip still equals the recorded SHA, (b) `git merge-base --is-ancestor <sha> refs/heads/<target>` succeeds, and (c) for a source with a linked worktree, that worktree is still clean, unlocked, not in progress, and has no ignored files unless `--discard-ignored` was given.
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

Phase 2 starts only after phase 1 finished without stopping: a gate failure, a conflict, a failed check, an `UNKNOWN` needed for a write, or a stale preview stops the whole command and no remote branch is touched. Branches that phase 1 kept (blocked, unrelated history, in progress) are not remote candidates either (`KEPT_LOCAL` below).

### Phase 2: remote sweep

**Definitions.**

- **remote**: `--remote <name>` or `origin`. If it is not in `git remote`, stop before phase 1 (a gate failure).
- **remote default**: the branch named by `git symbolic-ref refs/remotes/<remote>/HEAD`. That ref is written at clone time and can be stale (`references/branch-strategy.md`), so apply step 2 checks it against the live remote. If that ref is missing, or names a branch with no remote-tracking ref, the remote default is unknown and the whole phase 2 is `UNKNOWN`: report it and suggest `git remote set-head <remote> --auto`. Phase 1 still completes.
- **mapping**: `git config --get-all remote.<remote>.fetch` must include `refs/heads/*:refs/remotes/<remote>/*` (with or without a leading `+`), so that `refs/remotes/<remote>/<name>` is the remote's `refs/heads/<name>`; without it, phase 2 is `UNKNOWN`. A remote-tracking ref that matches the destination of another fetch refspec (for example `refs/remotes/<remote>/pr/*` from `+refs/pull/*/head:refs/remotes/<remote>/pr/*`) is `NOT_TOUCHED`. If `git remote get-url --push <remote>` differs from `git remote get-url <remote>`, the deletions would go to another repository than the one checked, so phase 2 is `UNKNOWN`.
- **survivors**: the remote branches the remote keeps, as the ancestry anchor for "merged": the remote default and `refs/remotes/<remote>/<target>` when it exists. A remote branch is **merged** only when its tip is an ancestor of a survivor tip (`git merge-base --is-ancestor <sha> <survivor-sha>`), never merely of the local target. Work that exists only in the local target is not on the remote, so deleting the remote branch would remove the last remote copy; such a branch is `PENDING_PUSH` until the publish step has put that work on the remote.
- **converged target**: what local `<branch>` holds once phase 1 has finished: in an apply after phase 1, its tip; in a preview, its current tip together with the tips of every source whose merge status is `MERGE` (a hint, as `PREDICTED_CONFLICT` is). Every test below that says "the converged target" uses it, in the preview and in the apply, so a preview and the apply after it classify a remote branch alike.
- Resolve every remote branch through its full refname (`refs/remotes/<remote>/<name>`) and take SHAs from one `git for-each-ref --format='%(refname) %(objectname)' refs/remotes/<remote>` listing. **Names vs SHAs** and **Case collisions** from section 6 apply: two remote names equal ignoring case are both `UNKNOWN`.

**Remote classification** (the first match wins; a case collision is decided before it, as in section 6, and makes both names `UNKNOWN` whatever else applies):

```text
NOT_TOUCHED          the remote default, `main`, the target, `HEAD`, a ref written by another fetch refspec (see mapping), any branch the repository documents as long-lived or protected, and any branch with a long-lived role (below)
BLOCKED_BAD_NAME     the name fails `git check-ref-format --branch` or starts with `-`; never passed to a command
BLOCKED_UPSTREAM     a local branch that will remain tracks it (`branch.<x>.remote` is the remote and `branch.<x>.merge` is `refs/heads/<name>`)
KEPT_LOCAL           the local branch of the same name remains after phase 1 (blocked, unrelated history, in progress, `UNKNOWN`, or appeared after preview)
KEPT_NOT_MERGED      its tip is not an ancestor of any survivor and not of the converged target; it holds work the remote does not have elsewhere
PUSH_THEN_DELETE     its tip is an ancestor of the converged target but not of any survivor, and the publish step is predicted to run (its conditions that the local refs can show hold), whether or not `--push` was typed: with `--push` the apply publishes `<branch>` first and deletes this branch after it; without `--push` the apply leaves it and reports "kept: --push not typed"
PENDING_PUSH         its tip is an ancestor of the converged target but not of any survivor, and the publish step is not predicted to run, or in an apply it was skipped, failed or was not confirmed (the report names the condition); delete it after `<branch>` is pushed and GitSweep is run again
STALE                the live remote tip differs from the remote-tracking SHA (checked in apply only); skip it
SAFE_CANDIDATE       merged into a survivor, and none of the above applies
UNKNOWN              a needed fact could not be established
```

A **long-lived role** is one of INTEGRATION, STAGING, RELEASE, or ARCHIVE in `references/branch-strategy.md` **Branch roles**. It needs recorded or observed evidence: a policy file, CI trigger filters, matching release tags, or repeated merges into or from the integration branch in its `--first-parent` history. A role inferred only from the name does not count; report the name as the evidence. Such a branch is often fully merged right after a sync, and deleting it on the remote also closes or retargets pull requests that use it as their base.

**Preview (default, read-only).** After the section 6 preview, list every remote branch with its SHA and remote classification, the survivors with their SHAs, and the exact `git push` that would be run for each `SAFE_CANDIDATE`. Also the **publish prediction**, from local refs only and with or without `--push`: the push would run when every condition of the **Publish step** that the local refs can show holds (`<branch>` is not `main` and not the remote default, phase 2 is not `UNKNOWN`, and `refs/remotes/<remote>/<branch>` is absent or a proper ancestor of the converged target), and the report then gives the exact push command, the commits it would publish (the commits of the converged target that `refs/remotes/<remote>/<branch>` lacks, the sources to merge among them, each commit list shortened only with an explicit "(N more)"), whether it creates the remote branch, and the `PUSH_THEN_DELETE` branches that depend on it; when it would not run, the report names the failed condition, or says that nothing needs publishing when the remote tip already equals the converged target. A `PUSH_THEN_DELETE` branch is listed with its two ways forward: run with `--push`, or push `<branch>` by hand (`git push <remote> refs/heads/<branch>:refs/heads/<branch>`) and rerun; a `PENDING_PUSH` branch is listed with the condition that keeps the publish from running. The preview does not contact the network and does not fetch: remote freshness is local-only, so the report says that `refs/remotes/<remote>/*` may be behind the live remote and that `--apply` rechecks it.

**Publish step (`--push`).** It publishes the local `<branch>` and no other ref, with this one command and no variation:

`git push --no-follow-tags <remote> refs/heads/<branch>:refs/heads/<branch>`

It is a fast-forward push: never `--force`, `-f`, a `+` refspec or `--force-with-lease`, never `--no-verify`, `--tags`, `--all`, `--mirror`, `--prune`, `--delete`, `--set-upstream` or a refspec pattern. A `pre-push` hook of the repository runs as git runs it. The push creates `refs/heads/<branch>` on the remote when it does not exist there; the plan and the report say so. It is the one push of commits that this command makes, and `--apply --push` is the user's acceptance of publishing the local `<branch>` as phase 1 leaves it: the commits the remote lacks (all of the branch when it is absent), which the preview listed as existing commits and sources to merge, and the report lists by range and count.

**Apply.** After phase 1:

1. Record the remote candidate list in the plan (included in the final report), each candidate classified against the actual local `<branch>` tip. Compare it with the most recent GitSweep preview or apply report for the same `<branch>` earlier in this conversation, if any. A candidate that was neither a `SAFE_CANDIDATE` nor a `PUSH_THEN_DELETE` there, or whose SHA differs from the one shown there, is reported as "appeared after preview, untouched". Without an earlier GitSweep preview or report, the recorded list is the plan.
2. Run `git ls-remote --symref <remote> HEAD 'refs/heads/*'` once. This is a network read and changes no refs; it is the only network read before the deletions. Phase 2 is `UNKNOWN` when the live `HEAD` names a branch other than the remote default, when a survivor's live tip differs from its remote-tracking SHA, or when a survivor is missing. A candidate whose live tip differs, or that is missing, is `STALE` and skipped. Do not fetch to resolve either. Tell the user to run `git fetch <remote>` (and `git remote set-head <remote> --auto` if the default changed), then rerun. Record the live tip of `refs/heads/<branch>` (or that it is absent) for the next step.
3. **Publish** (only with `--push`; otherwise go to step 4, which leaves every `PUSH_THEN_DELETE` and `PENDING_PUSH` branch). Run the publish command above only when all of these hold: phase 1 finished and its validation did not fail (a validation that could not be identified does not stop the push; the report then says that the published merge is not validated); phase 2 is not `UNKNOWN`; `<branch>` is not `main` and not the remote default; and the live tip recorded in step 2 is absent or an ancestor of the local `<branch>` tip (`git merge-base --is-ancestor <live-sha> refs/heads/<branch>`; a live tip whose object the local repository lacks is not an ancestor: tell the user to `git fetch <remote>` and merge it). When the live tip equals the local tip there is nothing to publish: no push is made and the report says `PUBLISH_NOT_NEEDED`; the `PUSH_THEN_DELETE` candidates are then judged against that tip like any other. Otherwise the push runs even when no candidate depends on it, because `--push` is the user's request to publish `<branch>` and the preview listed the commits. If a condition fails, skip the push, report `PUSH_SKIPPED` with the failed condition, and go on to step 4 with the candidates as they are. On a non-zero exit (a protected branch, a hook, a rejection, the network), record the error text, do not retry and do not alter the command, report `PUSH_FAILED`, and go on to step 4. On success, `git rev-parse refs/remotes/<remote>/<branch>` must equal the local tip, which is then the survivor tip of `<branch>`; when it does not, report `PUSH_UNCONFIRMED` and treat the push as failed. Each `PUSH_THEN_DELETE` candidate whose tip is an ancestor of that tip becomes `SAFE_CANDIDATE`; when the push was skipped, failed or unconfirmed, it is reported as `PENDING_PUSH` with that reason. A live `<branch>` that moved or vanished since the remote-tracking ref was written makes phase 2 `UNKNOWN` in step 2, so the push is skipped for that reason; the ancestor condition catches a diverged branch whose live tip still equals the remote-tracking ref.
4. For each remaining `SAFE_CANDIDATE`, one at a time, delete it with exactly:
   `git push --force-with-lease=refs/heads/<name>:<sha> <remote> :refs/heads/<name>`
   The lease is the per-branch recheck at the moment of deletion: the remote refuses the deletion if the branch moved since it was recorded. On a non-zero exit, record the error text, leave that branch, and continue with the next candidate.
5. Report the publish result (the push, or `PUSH_SKIPPED`, `PUSH_FAILED` or `PUSH_UNCONFIRMED` with its reason; the remote tip before and after and the commit count; undoing a publish needs a force push, which this command never makes), each deleted remote branch with its tip SHA (recreate with `git push <remote> <sha>:refs/heads/<name>`) and each skipped one with its classification. Say that a remote deletion also closes any open pull request that uses the branch as its head, and on some hosts closes or retargets pull requests that use it as their base. Then the run state (**One-shot readiness**).

### One-shot readiness

A preview ends with a readiness verdict and a recommended command, and an apply report ends with the run state it reached, so the user sees whether one run of the **recommended command** reaches the **end state**: only `main` and `<branch>` remain as local branches, the worktrees of the deleted branches are removed, and every remote branch is deleted or `NOT_TOUCHED`. A worktree the command never touches (a detached one, or one that holds `main` or another kept branch) is not part of the end state; the report lists it. The verdict judges the recommended command, not the command as typed, and is one of:

- `ONE_SHOT`: no gate fails; every source is `MERGE` or `CONTAINED` and its only delete blocker, if any, is `BLOCKED_IGNORED_FILES`, which `--discard-ignored` lifts; no source is `PREDICTED_CONFLICT`; phase 2 is not `UNKNOWN`; and every remote branch is `SAFE_CANDIDATE`, `PUSH_THEN_DELETE` or `NOT_TOUCHED`. One run of the recommended command then reaches the end state, as far as the local refs can show: the apply rechecks the live remote.
- `PARTIAL`: no gate fails, but something remains that no flag lifts (any other delete blocker, `BLOCKED_IN_PROGRESS`, `BLOCKED_UNRELATED_HISTORY`, `UNKNOWN`, a `PREDICTED_CONFLICT`, `KEPT_NOT_MERGED`, `KEPT_LOCAL`, `BLOCKED_UPSTREAM`, a `PENDING_PUSH` whose publish step is not predicted to run, phase 2 `UNKNOWN`). The recommended command still does everything it can.
- `BLOCKED`: a gate fails, so nothing can run; the report lists every failed gate with its remedy.

**Recommended command.** For `ONE_SHOT` and `PARTIAL`, the full line `/GitSweep <branch> --apply` (with `--remote <name>` and `--lang <language>` as given, and the flags in the order `--apply`, `--discard-ignored`, `--push`, `--remote`, `--lang`), with exactly the flags that lift something: `--discard-ignored` only when a worktree's only delete blocker is `BLOCKED_IGNORED_FILES`, with every ignored path that it deletes listed next to the line; `--push` only when at least one remote branch is `PUSH_THEN_DELETE` (whether or not `--push` was typed), with the publish prediction (commit count, whether it creates the remote branch) next to the line. A flag that lifts nothing is never recommended, and a flag that discards files or publishes commits is never added silently.

**Remaining items.** For `PARTIAL`, every item that stays: the branch or worktree, its classification, its evidence, its remedy and whether the user must rerun afterwards. The remedies for local findings are the **Remedies** table of section 6. For remote findings:

| Finding | Remedy |
|---|---|
| phase 2 `UNKNOWN`: remote default unknown | `git remote set-head <remote> --auto` |
| phase 2 `UNKNOWN`: no `refs/heads/*:refs/remotes/<remote>/*` mapping | `git config --add remote.<remote>.fetch '+refs/heads/*:refs/remotes/<remote>/*'`, then `git fetch <remote>` |
| phase 2 `UNKNOWN`: push URL differs from the fetch URL | make them the same (`git config --unset-all remote.<remote>.pushurl`) or sweep the remote that the push URL names |
| phase 2 `UNKNOWN` or `STALE` after the live check | `git fetch <remote>` (and `git remote set-head <remote> --auto` when the default changed), then rerun |
| gate: `--remote <name>` not listed by `git remote` | name a listed remote (`git remote -v`), or add it with `git remote add <name> <url>` |
| `PUSH_THEN_DELETE` (kept: `--push` not typed) | rerun with `--push`, or `git push <remote> refs/heads/<branch>:refs/heads/<branch>` yourself, then rerun |
| `PENDING_PUSH` | clear the condition the report names, then rerun: if `<branch>` is the remote default, publish it by hand or through your review process (the command never pushes the remote default); if the remote tip is not an ancestor, `git fetch <remote>` and merge it into `<branch>`, then rerun with `--push`; if the push failed or was refused, satisfy the host's rule (branch protection, a hook) and rerun with `--push`, or publish by hand; if phase 2 is `UNKNOWN`, see its rows |
| `PUSH_SKIPPED`, `PUSH_FAILED`, `PUSH_UNCONFIRMED` | clear the named condition: fetch and merge a newer remote tip; satisfy the host's branch protection or hook; fix the failed validation (see the failed-check row); for `<branch>` being `main` or the remote default, publish it by hand or through your review process; or publish by hand, then rerun |
| two remote names equal ignoring case (`UNKNOWN`) | rename or delete one of them on the host; the command leaves both untouched |
| `KEPT_LOCAL` | clear the local blocker named for that branch |
| `BLOCKED_UPSTREAM` | `git branch --unset-upstream <x>` on the local branch that tracks it |
| `KEPT_NOT_MERGED` | review it and merge it into `<branch>`, or delete it on the host yourself; the command never deletes it |
| `BLOCKED_BAD_NAME` | delete or rename it on the host |

**Run state (apply report).** `COMPLETE` when the end state was reached; otherwise `PARTIAL` with the same remaining items and, as the last line, `Next command:` with the exact line to run once the remedies are done, built by the rules above from the final survey, with the flags in the order `--apply`, `--discard-ignored`, `--push`, `--remote`, `--lang`; it carries `--push` when `--push` was typed in this run, or some remote branch ended `PUSH_THEN_DELETE` or `PENDING_PUSH` for a reason the user can clear (the publish was skipped, failed or unconfirmed, or the remote tip needs a fetch and merge), and not when the only reason is that `<branch>` is the remote default; when phase 2 is `UNKNOWN` no remote branch is classified, the report shows the phase 2 rows, and `--push` is carried only when it was typed; the line is left out when no rerun would change anything.

### Hard stop conditions

All of section 6, except that the lease-guarded deletion above and, only with `--push`, the publish step replace its ban on pushing and on deleting remote branches and remote-tracking refs. In addition: never push commits or tags except the one fast-forward push of `<branch>` that `--push` makes; never force-push (the only pushes are the lease-guarded deletion above, one named branch per command, and that publish command); never use `--mirror`, `--prune`, `--all`, `--tags`, `--no-verify`, or a refspec pattern (in a push; the pattern in the step 2 `ls-remote` only selects what to read); never publish without `--push`, publish when phase 1 stopped or its validation failed, publish `main` or the remote default, or retry a failed publish with another command; never run `git remote prune`, `git fetch --prune`, or `git branch -d -r`; never delete the remote default, `main`, the target's remote branch, a branch with a long-lived role, a branch on any remote other than `--remote`, or a branch that is not merged into a survivor; never delete a remote branch when phase 1 stopped. Do not proceed when the skill or this reference could not be loaded; preview only.

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
Run state: COMPLETE / PARTIAL, remaining items + remedies, Next command (only with --apply)
Remaining risks (including: without a successful publish, the remote lacks the commits now only in local <branch>)
```

## Command Relationship

```text
/GitRecon
   ↓ repository map
/GitAnalyze <target>
   ↓ deep single-target evidence
/GitRecommend [goal]
   ↓ decision support
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
