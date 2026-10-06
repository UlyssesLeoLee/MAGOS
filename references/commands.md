# Explicit Command Contracts

This reference defines the command-layer behavior for `multi-agent-git-orchestrator` v3.4.

These are **semantic command intents**. Canonical names use a leading `/`. A host may expose them as slash commands, palette actions, prompt aliases, or plain-text invocations. If slash commands are unsupported, accept the same name without `/`. The behavior must remain the same.

## Argument and Help Behavior

All six commands accept `--help`. When it is present, show that command's usage, argument descriptions, defaults, and examples, then stop before inspecting or changing a repository. `--help` takes precedence over other arguments.

**Reply language.** All six commands accept `--lang <language>`. It selects the language of everything the command says to the user: help text, questions, errors, reports (including the final report of a write command after a long run), and recommendations. When it is absent the reply is in Chinese (简体中文). The value is the next token: a language name or a common code (`English`, `en`, `日本語`, `ja`, `Français`); put a multi-word name in quotes. The option may appear anywhere among the arguments and may be combined with `--help`; help is then shown in the requested language, with flags and examples left untouched. Never translate command names, option names, branch or worktree names, paths, SHAs, Git commands, or status codes such as `BLOCKED_DIRTY`; a short gloss in the reply language next to a code is fine. Remove `--lang` and its value from the arguments before any other parsing, so it never becomes part of a goal, target, or branch name. If `--lang` has no value, or the value is not a language, explain the problem (in Chinese) and show the usage without executing the command.

Recognize only the options listed for each command. For an unknown option or a required option value that is missing or invalid, explain the issue and show the relevant usage without executing the command. If a required positional target is missing, ask the user for it. Host adapters should preserve the supplied argument text and route `--help` to this reference.

Host entry points are Claude Code `/GitRecon`, Hermes `/git-recon`, and Codex `$git-recon` (use the corresponding command name for the other five). Append the same arguments after the host-specific entry point.

## Host Adapter Contract

Each host reaches the same canonical command through its own adapter. Adapters differ only in how they receive arguments and locate shared files; the command behavior below is identical.

| Host | Adapter | Arguments arrive as | Shared files are located by |
|---|---|---|---|
| Claude Code | `commands/Git*.md` (installed into `~/.claude/commands/`) | `$ARGUMENTS` in the command template | loading the orchestrator skill (listed as `MAGOS`, `multi-agent-git-orchestrator`, or `MAGO-Skill`) |
| Codex | `skills/git-*/SKILL.md` + `agents/openai.yaml` | the text after `$git-*` in the user's message | resolving `../../SKILL.md` and `../../references/*.md` relative to the adapter's `SKILL.md` |
| Agent Plugins client | `skills/git-*/SKILL.md`, found through the root `plugin.json` | as the client passes skill input | resolving `../../SKILL.md` and `../../references/*.md` inside the plugin root; the root `SKILL.md` is not a plugin skill. Only discovery is verified. The write adapters act only on an explicit invocation, which a plugin client may not be able to express (Hermes plugin skills have no `/git-*` command and no `[Skill directory: ...]` line) |
| Hermes | `skills/git-*/SKILL.md` | the instruction Hermes appends after the skill content ("...alongside the skill invocation:" for one command, `User instruction:` for stacked commands) | the absolute `[Skill directory: ...]` path plus `../..`, read with the file or terminal tool (the skill viewer rejects `..`), or the root skill `multi-agent-git-orchestrator` and its `references/` files |

Rules for every adapter:

- `skills/` adapters must not read `commands/*.md`; those wrappers contain Claude-specific loading steps.
- Codex adapters set `policy.allow_implicit_invocation: false`, so they run only when selected explicitly; the root skill keeps semantic activation. Hermes has no per-skill switch, so `git-integrate`, `git-cleanup`, and `git-converge` refuse to write unless invoked explicitly.
- If the shared rules (`SKILL.md`, `references/commands.md`) cannot be read, read-only commands may continue read-only and report the incomplete installation; `GitIntegrate` must not integrate, `GitCleanup` must not delete, and `GitConverge` must not merge or delete (preview only).
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

1. Run the Quick Scan from `reconnaissance.md`.
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
5. Inspect recorded downstream dependencies and clearly separate inferred semantic risks.
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
4. Each recommendation must include evidence and expected next action.
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
UNKNOWN
```

A branch/worktree is not safe merely because it is old or inactive.

### Apply behavior

`--apply` may clean only `SAFE_CANDIDATE` entries. Re-check each candidate immediately before mutation.

Typical safe operations may include:

```text
git worktree remove <path>
git branch -d <branch>
git worktree prune
```

Constraints:

- do not use `git branch -D` by default;
- do not delete dirty worktrees;
- do not remove branches with unique unpreserved commits;
- do not remove dependency-source branches required by active lanes;
- do not treat remote deletion as implied by local cleanup;
- if state changed between preview and apply, skip the candidate and report it.

### Output

```text
Cleanup candidates
Blocked items + reasons
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
- **Names vs SHAs**: resolve every branch through its full refname (`refs/heads/<name>`) and record its SHA. In every git command in this section, `<target>` and `<source>` in a revision argument mean `refs/heads/<name>` or the recorded SHA, never the bare name: a same-named tag wins bare-name resolution (`refname '<name>' is ambiguous`). Merge the recorded SHA.
- **invoking worktree**: the worktree that contains the current directory. It is the only worktree this command writes into or switches.
- **clean**: both hold. (1) `git -C <worktree> status --porcelain=v1 --untracked-files=all` is empty; always pass the flag, because `status.showUntrackedFiles=no` would otherwise hide untracked files. (2) No entry of `git -C <worktree> ls-files -v` is tagged `S` (skip-worktree) or with a lowercase letter (assume-unchanged) while its file exists on disk; status cannot see edits to those files, and `git worktree remove` deletes them. Entries absent from disk (sparse checkout) do not count. Ignored files are not covered by "clean".
- **in progress**: a worktree has a merge, cherry-pick, revert, rebase, am, or bisect underway, or a paused cherry-pick/revert sequence (`MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `sequencer/`, `rebase-merge/`, `rebase-apply/`, `BISECT_LOG`, each located with `git -C <worktree> rev-parse --git-path <name>`). Check every worktree, including detached ones. A rebase or bisect shows its worktree as `detached`; the branch it is working on is named in `rebase-merge/head-name`, `rebase-apply/head-name`, or `BISECT_START`, and that branch counts as checked out there.
- **active owner**: a worktree that is locked, lies under an agent-harness worktree root (`<main worktree>/.claude/worktrees/`, where Claude Code keeps its session worktrees; `~/.codex/worktrees/`; or a root the repository documents), or has a lane record naming another owner. Clean is not proof that nobody is using it.
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

### Preview behavior (default, read-only)

Collect and report:

1. **Gates** (any failure stops the whole command, even for a preview): target missing locally; target is `main`; local `main` missing; target or `main` is checked out only in a prunable (missing-directory) worktree entry; target is checked out in a worktree other than the invoking one (run the command from that worktree); the invoking worktree is detached, dirty, or in progress; target is in progress anywhere.
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
   3. List the paths the source changed since the merge base (`git diff --name-only <merge-base> <sha>`) and the ignored entries in the invoking worktree (`git ls-files --others --ignored --exclude-standard --directory`; a trailing `/` marks an ignored directory). They overlap when a changed path equals an ignored entry, when one lies under the other (a directory/file clash), or, if `git config --bool core.ignorecase` is true, when they match ignoring case. If they overlap, stop: a merge silently overwrites ignored files (`--no-overwrite-ignore` is not honored by merge). Completed merges stay.
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
Gates
Sources to merge (ordered)
Contained sources
Blocked items + reasons
Expected final local branches
Not touched
Applied operations (only with --apply)
Skipped items + reasons
Target start SHA -> end SHA
Deleted branches + tip SHAs
Validation
Remaining risks
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
```

`/GitRecon`, `/GitAnalyze`, and `/GitRecommend` are observation/advice commands. `/GitIntegrate` is an integration write-intent. `/GitCleanup` is preview-only unless `--apply` is explicit. `/GitConverge` is preview-only unless `--apply` is explicit; it is the only command that merges unreviewed local branches, and it does so only on the user's acceptance of the plan it prints.
