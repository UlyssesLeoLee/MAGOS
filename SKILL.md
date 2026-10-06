---
name: multi-agent-git-orchestrator
description: "Automatically use for multi-agent or multi-worktree Git coordination, dependency-aware branch planning, review/integration, merge queues, cherry-pick/rebase/squash decisions, conflict ownership, rollback, and repository-specific advice about existing branches/worktrees. Also activate on help-seeking symptom language, not just coordination tasks — agents overwriting or clobbering each other, lost or reverted work, worktrees fighting over a branch, branch or worktree sprawl, not knowing which branch is safe to merge or delete, agents breaking main, or building a custom multi-agent orchestrator instead of reusing one. When a user describes one of these symptoms, say that this skill exists and covers it before offering ad-hoc Git advice. Explicit commands: GitRecon, GitAnalyze, GitRecommend, GitIntegrate, GitCleanup, GitConverge. Inspect the repository before state-dependent advice. Do not use for ordinary conceptual or single-branch Git questions unless topology, coordination, or shared-history safety matters."
license: Apache-2.0
compatibility: "Requires Git 2.30+ or harness-native workspace isolation; intended for Agent Skills-compatible coding agents."
metadata:
  version: "3.4"
  domain: "engineering-process"
  scope: "multi-agent-git"
---

# Multi-Agent Git Orchestrator

Coordinate parallel development without corrupting workspaces, rewriting shared history, or integrating stale/unverified agent output. When advice depends on the current repository, inspect the repository first and base recommendations on observed Git state rather than assumptions.

## Activation Scope

Activate automatically for either mode below.

### A. Orchestration Mode

Use when multiple development actors share one Git repository and work involves any of:

- parallel coding agents or developers;
- one task/agent per branch or worktree;
- task-lane or dependency-DAG planning;
- worktree isolation or branch ownership;
- merge queues or protected integration branches;
- deciding between merge, squash merge, cherry-pick, rebase, reset, or revert;
- selective acceptance of agent commits;
- cross-agent conflicts, branch divergence, stale approvals, or shared rollback.

### B. Reconnaissance / Advice Mode

Use proactively when the user asks what should be done with the **current repository**, including:

- inspect/list/analyze worktrees or branches;
- recommend which branch/worktree should receive a task;
- decide what can be merged, rebased, cherry-picked, archived, or deleted;
- explain divergence, stale branches, detached worktrees, dirty lanes, or overlapping work;
- advise how to simplify or reorganize current multi-branch/worktree topology;
- assess whether it is safe to start another agent/lane.

For repository-specific advice, **inspect before recommending** when repository shell/tool access is available. Do not ask the user to manually paste branch/worktree state that can be observed directly.

Do **not** activate merely because Git is mentioned. Pure conceptual questions such as “what does commit mean?” or ordinary single-branch operations do not require this skill unless repository-specific topology or shared-history safety matters.

## Explicit Command Interface

Treat the following names as explicit invocation intents. The canonical command names are `/Git...`; host-native skill adapters may map them to another selector. Explicit invocation selects the command mode but does not bypass safety gates.

### Host Invocation Names

| Canonical command | Claude Code | Hermes | Codex |
|---|---|---|---|
| `/GitRecon` | `/GitRecon` | `/git-recon` | `$git-recon` |
| `/GitAnalyze` | `/GitAnalyze` | `/git-analyze` | `$git-analyze` |
| `/GitRecommend` | `/GitRecommend` | `/git-recommend` | `$git-recommend` |
| `/GitIntegrate` | `/GitIntegrate` | `/git-integrate` | `$git-integrate` |
| `/GitCleanup` | `/GitCleanup` | `/git-cleanup` | `$git-cleanup` |
| `/GitConverge` | `/GitConverge` | `/git-converge` | `$git-converge` |

Claude Code reads the command Markdown files in `commands/`. Codex and Hermes discover the six Agent Skills in `skills/` (nested under this package) in addition to this root skill: Codex exposes them as `$git-*` skills (or browse with `/skills`) and does not register arbitrary custom `/Git...` slash commands; Hermes registers each as a `/git-*` slash command. The `skills/` adapters are host-neutral: they read this file and `references/` directly and never route through `commands/`, whose loading steps are Claude-specific. Codex adapters disable implicit selection in `agents/openai.yaml`; Hermes has no per-skill switch, so the write adapters (`git-integrate`, `git-cleanup`, `git-converge`) enforce explicit invocation by instruction. Agent Plugins clients (the root `plugin.json`, specification 1.0.0) discover only these six adapters in `skills/`; for them this root skill is shared package content that the adapters read, not a plugin skill. Only that discovery is verified: Hermes plugin skills get no `/git-*` commands, so the write adapters (which act only on an explicit invocation) are for the skills-directory installs there. See `references/commands.md` **Host Adapter Contract** for argument passing and file resolution per host.

| Command | 中文调用说明 | Default effect |
|---|---|---|
| `/GitRecon [--remote]` | **调查当前 Git 仓库整体状态。** 主动检查 branch、worktree、HEAD、ahead/behind、dirty、detached、upstream、已合并情况和高风险点，生成仓库快照。 | Read-only locally. `--remote` may refresh remote-tracking refs before reporting. |
| `/GitAnalyze <branch|worktree> [--remote]` | **深入分析指定分支或 worktree。** 检查其与集成分支的共同祖先、ahead/behind、独有 commit、修改文件、依赖与 rewrite 风险，并评估 merge/rebase/cherry-pick/delete 等操作是否安全。 | Read-only locally. `--remote` may refresh remote-tracking refs. |
| `/GitRecommend [<goal>] [--remote]` | **基于当前仓库真实状态给出下一步 Git / 多 Agent 编排建议。** 建议哪些任务可并行、哪些分支应同步或集成、哪些 Lane 应暂停、下一个 Agent 应放哪里，以及哪些对象仅适合作为清理候选。 | Advisory only; inspect first. |
| `/GitIntegrate <lane|branch> [--strategy auto|merge|squash|cherry-pick]` | **安全集成指定 Agent Lane 或分支。** 在写入集成分支前检查 review、dependency、freshness、commit 完整性和目标分支状态，再按仓库策略或指定策略完成集成，并重新验证主线。 | Write intent; may mutate only after gates pass. |
| `/GitCleanup [--apply]` | **调查并整理可安全清理的 branch 和 worktree。** 默认只列出候选、证据和阻塞项；只有 `--apply` 才删除满足安全条件的对象。 | Preview by default; mutation only with `--apply`. |
| `/GitConverge <branch> [--apply] [--discard-ignored]` | **把所有本地分支的领先内容合并进指定分支，然后只保留 `main` 和该分支。** 默认只预览计划、阻塞项和最终分支集合；只有 `--apply` 才合并并删除已合并的本地分支及其干净 worktree。`main` 只作为合并来源，从不被移动或删除。 | Preview by default; merges and deletes only with `--apply`. |

### Command Semantics

- **Explicit command wins over automatic mode selection.** `/GitRecon`/`/GitAnalyze`/`/GitRecommend` do not mutate repository topology by default.
- `--remote` authorizes a remote-ref refresh when needed (for example `git fetch --prune`); it does not authorize branch/history mutation.
- `/GitRecommend` MUST run or reuse a **fresh** reconnaissance snapshot. A snapshot is stale if relevant HEADs, refs, worktree cleanliness, or integration target changed after observation.
- `/GitIntegrate` is authorization to attempt a safe integration, not permission to bypass review, freshness, dependency, protected-branch, or repository-policy gates. If gates fail, stop and report the blocker rather than forcing integration.
- `--strategy auto` is the default. Choose the repository-consistent strategy from observed evidence. A requested explicit strategy is still rejected if unsafe or incompatible with repository policy.
- `/GitCleanup` without `--apply` MUST NOT delete, prune, reset, force-delete, or rewrite anything.
- `/GitCleanup --apply` may remove only candidates that are clean, fully integrated or otherwise explicitly disposable, have no active owner/dependent lane, and contain no unique unpreserved work. Never use forced deletion merely to make cleanup succeed.
- `/GitConverge` without `--apply` MUST NOT merge, switch, delete, prune, or fetch anything.
- `/GitConverge <branch> --apply` is the user's explicit acceptance of the source tips in the plan that run records and reports (or in an earlier GitConverge preview in the same conversation). That acceptance stands in for per-lane review of exactly those tips; it is not permission to write any branch other than `<branch>`, to move, reset, or delete `main`, to push or delete remote branches, to touch a worktree with an active owner (`references/commands.md` section 6), or to bypass the gates in `references/commands.md` section 6. If a gate fails, stop and report; never force.
- All six commands accept `--lang <language>`: it sets the language of every reply (Chinese when absent) and never translates command names, options, branch or worktree names, paths, SHAs, or status codes. See `references/commands.md`.
- When a target name is ambiguous between a branch and worktree, resolve it from observed repository state; if ambiguity materially changes the action and cannot be resolved safely, report the ambiguity instead of guessing.

Load `references/commands.md` when command-specific arguments, output contracts, or safety behavior are needed.

## Operating Invariants

1. **One active lane = one writable workspace.** Never run parallel writers in the same checkout.
2. **The integration branch is not a worker workspace.** Workers change only their assigned lane.
3. **One lane has one write owner at a time.** Transfer ownership explicitly.
4. **Every managed lane records:** task, owner, base branch, base SHA, dependencies, acceptance criteria.
5. **Evidence beats claims.** Repository state and executed checks determine readiness.
6. **Rewrite only rewrite-safe history.** Published/shared/dependency-source history is not rewritten by default.
7. **Integration is serialized.** Only one actor writes the protected integration branch at a time.
8. **Reconnaissance is non-destructive by default.** Investigate before mutating.
9. **Unknown is not safe.** Do not infer ownership, remote freshness, semantic dependencies, or merge safety without evidence.

## 1. Repository Reconnaissance

When advice depends on current Git state, perform a read-only survey before proposing changes.

### Quick Scan

Collect at minimum:

- repository root and current HEAD/branch;
- all linked worktrees, paths, branches, HEADs, detached/locked/prunable state;
- local branches, commit IDs, upstreams, tracking status, and recent activity;
- dirty/untracked/unmerged state for relevant worktrees;
- likely integration target and whether that target is confidently known.

Prefer stable machine-readable Git output such as:

```text
git rev-parse --show-toplevel
git status --porcelain=v1 --branch
git worktree list --porcelain
git for-each-ref --sort=-committerdate --format="%(refname:short)%09%(objectname:short)%09%(upstream:short)%09%(upstream:track)%09%(committerdate:iso8601)" refs/heads
git remote -v
git symbolic-ref --quiet --short refs/remotes/origin/HEAD
```

For each relevant linked worktree, inspect its local state with `git -C <path> status --porcelain=v1 --branch`.

Do not assume `main` is the integration target. Infer it from repository policy/configuration or clearly report uncertainty.

### Deep Scan

Only when needed for a decision, compare candidate branches with the integration target using:

```text
git rev-list --left-right --count <target>...<branch>
git merge-base <target> <branch>
git merge-base --is-ancestor <branch> <target>
git diff --name-only <target>...<branch>
git log --oneline --decorate <target>..<branch>
```

Use these to determine ahead/behind state, whether a branch is already integrated, likely changed-file overlap, and the commits unique to a lane.

Git topology can prove commit ancestry; it cannot by itself prove business/semantic dependency. Label inferred dependencies separately from recorded dependencies.

### Remote Freshness

Local reconnaissance does not prove remote freshness. Do not silently hide a network mutation inside a “read-only” survey.

- If local state is sufficient, advise from local facts and mark remote freshness as unknown where relevant.
- If the user asks for current remote truth, or an integration decision requires it, refresh remotes with the environment's authorized Git workflow (for example `git fetch --prune`) before final advice.
- If network access is unavailable, say the recommendation is based on local remote-tracking refs.

### Reconnaissance Output

Before recommendations, summarize the observed state compactly:

```text
Integration target: <branch@sha | uncertain>
Worktrees: <count>; dirty: <count>; detached: <count>; prunable: <count>
Active branches: <count>; diverged: <count>; merged candidates: <count>
Remote freshness: current | local-only | unknown
High-risk findings: <items>
```

Then provide prioritized recommendations with the evidence behind each recommendation. Load `references/reconnaissance.md` for the full classification and advice matrix.

## 2. Preflight for New Work

Before creating anything:

- detect whether the harness already provided an isolated workspace; prefer harness-native isolation;
- inspect current branch/worktree state and existing lane ownership;
- require a clean or explicitly understood baseline;
- run the repository's normal baseline checks and record pre-existing failures;
- capture `<base-branch>` and `<base-SHA>`.

Do not create a nested/redundant worktree when already isolated.

## 3. Plan Lanes as a Dependency DAG

Parallelize only independently reviewable work.

```text
A ──┐
B ──┼─> integration
C ──┘

A -> B    means B depends on A
```

If B is based on A, record that edge. Once another active lane depends on A's commit IDs, treat A as **rewrite-frozen** unless all dependents are explicitly retargeted.

When recommending a new lane, first inspect existing worktrees/branches and reuse an appropriate clean idle lane only if ownership, base, and scope are compatible. Otherwise create a new isolated lane.

## 4. Create the Lane

Use one branch/worktree per lane, for example:

```text
agent/<task-id>-<short-name>
```

Fallback when no native isolation exists:

```bash
git worktree add <path> -b agent/<task-id>-<short-name> <base-branch>
```

Keep unrelated refactors outside the lane unless approved as separate scope.

## 5. Implement with Integratable Commits

Checkpoint commits are allowed. Prefer logical commits that are understandable, reversible, and dependency-clear.

Do not combine unrelated changes when selective integration may be needed later.

Before handoff, identify which commits depend on earlier lane commits.

## 6. Sync Safely

Fetch/refresh the integration target as required by repository policy before final review.

Choose synchronization by **rewrite safety**:

- **Private lane, no downstream consumer:** rebase onto the integration branch.
- **Published lane or dependency source:** do not casually rebase; merge the integration branch into the lane, or coordinate/retarget every dependent lane.
- **Architectural incompatibility:** stop and return the lane to planning rather than forcing conflict resolution.

Resolve conflicts in the lane, then re-run validation.

## 7. Validation and Independent Review

A lane is not `READY` until required build/test/lint/type/security checks pass and the diff contains no accidental scope, secrets, generated junk, or environment artifacts.

For non-trivial work, separate:

- **Worker:** implementation;
- **Reviewer:** requirement/scope/design/code review;
- **Verifier:** executes checks independently when practical;
- **Orchestrator:** dependency and integration decisions.

A worker's statement that tests passed is not evidence by itself.

## 8. Approval and Freshness Gate

Use states:

```text
PLANNED -> ACTIVE -> READY -> APPROVED -> INTEGRATING -> INTEGRATED
                      \-> BLOCKED / REJECTED
```

Before writing the integration branch:

1. acquire exclusive integration ownership / merge-queue position;
2. refresh required refs;
3. confirm the reviewed lane HEAD is unchanged;
4. confirm the integration target is unchanged since approval;
5. if either changed, sync and re-run affected validation/review before integration.

Never integrate a stale approval.

## 9. Choose the Integration Operation

| Reviewed outcome | Preferred operation |
|---|---|
| Whole lane accepted; preserve accepted commit structure | `merge` / repository PR policy |
| Whole lane accepted as one delivery unit | squash merge, if repository policy uses it |
| Only dependency-safe selected commits accepted | `cherry-pick` |
| Private rewrite-safe lane is noisy | interactive rebase/squash before approval |
| Private lane took the wrong direction | `reset` or recreate lane |
| Published/shared integrated change is wrong | `revert` |

Before cherry-picking, verify selected commits do not depend on rejected commits. When uncertain, apply the candidate set to a temporary integration candidate and validate it there.

Do not invent a per-agent merge policy; follow repository policy.

## 10. Conflict Policy

Never resolve by blindly choosing `ours` or `theirs`.

Preserve current integration behavior unless requirements intentionally replace it, then reapply the lane's intended semantics and test the result.

If integration itself produces a non-trivial semantic conflict, return it to the responsible lane or designated integrator rather than improvising on the protected branch.

## 11. Post-Integration Gate

After merge/cherry-pick/squash merge:

- validate the integration branch again;
- record source lane and integrated commit(s);
- only then mark `INTEGRATED`;
- cleanup the worktree/branch when no active dependency needs it.

If a shared result later fails, use `revert`; do not rewrite protected history by default.

## Handoff Contract

Every lane must provide:

```text
Task:
Owner:
Branch / Worktree:
Base branch / Base SHA:
Current HEAD:
Dependencies:
Commits + dependency notes:
Files changed:
Validation commands + results:
Known risks:
Recommended integration: merge | squash-merge | cherry-pick <commits> | reject
```

## Hard Stops

Never:

- let parallel agents edit the same writable checkout;
- give repository-specific branch/worktree advice without inspecting available state first;
- mutate/reset/delete/prune branches or worktrees during reconnaissance merely to make the topology cleaner;
- infer that an old branch is disposable solely from age;
- infer semantic independence solely from non-overlapping commit topology;
- let a worker bypass the review/integration gate onto a protected branch;
- rewrite a dependency-source branch without coordinating dependents;
- force-push or destructively reset shared history by default;
- integrate because an agent merely says "done";
- cherry-pick without dependency checking;
- integrate from an approval whose lane HEAD or target branch has changed.

For explicit command contracts, read `references/commands.md`. For repository investigation and recommendation rules, read `references/reconnaissance.md`. For edge cases and the full operation matrix, read `references/decision-matrix.md`. For lifecycle data, read `references/handoff-and-state.md`. For rationale and source patterns, read `references/design-rationale.md` only when needed.
