# Repository Reconnaissance and Advice

Load this reference when the user asks for repository-specific advice about current worktrees, branches, divergence, integration order, cleanup, or where a new agent should work. For questions about the branching model itself, load `branch-strategy.md` after the Quick Scan.

## Principle

**Observe first, advise second, mutate only after the advice/decision is accepted or the task explicitly requires action.**

The survey should be proportional. Start with a quick topology scan; deepen only the branches/worktrees relevant to the user's decision.

## Quick Scan Inventory

Collect:

1. repository root and current branch/HEAD;
2. linked worktrees and their paths, branches, HEAD SHAs, detached/locked/prunable status;
3. local branches, upstreams, tracking state, commit date, and tip SHA;
4. dirty/untracked/unmerged state of active/relevant worktrees;
5. remotes and configured remote default branch if available;
6. repository policy clues that identify the integration branch.

Recommended portable Git commands:

```text
git rev-parse --show-toplevel
git status --porcelain=v1 --branch --untracked-files=normal
git worktree list --porcelain
git for-each-ref --sort=-committerdate --format="%(refname:short)%09%(objectname:short)%09%(upstream:short)%09%(upstream:track)%09%(committerdate:iso8601)" refs/heads
git remote -v
git symbolic-ref --quiet --short refs/remotes/origin/HEAD
```

For every relevant linked worktree:

```text
git -C <worktree-path> status --porcelain=v1 --branch --untracked-files=normal
git -C <worktree-path> diff --name-only --diff-filter=U
```

Do not parse human-decorated `git branch -vv` if stable structured alternatives are available.

## Deep Scan Per Candidate Branch

Given integration target `<target>` and candidate `<branch>`:

```text
git rev-list --left-right --count <target>...<branch>
git merge-base <target> <branch>
git merge-base --is-ancestor <branch> <target>
git merge-base --is-ancestor <target> <branch>
git diff --name-only <target>...<branch>
git log --oneline --decorate <target>..<branch>
```

Interpret `git rev-list --left-right --count <target>...<branch>` as:

```text
<target-only-count> <branch-only-count>
       behind              ahead
```

Use only enough history to answer the question. Do not scan every file or every commit by default.

## Worktree Classification

Classify a worktree using observed evidence:

| State | Evidence | Advice |
|---|---|---|
| CLEAN_ACTIVE | clean, assigned/clearly active branch | keep; eligible for normal workflow |
| DIRTY | modified/untracked files | do not reassign/delete; inspect ownership and intent |
| CONFLICTED | unmerged paths or operation conflict | BLOCKED until resolved/aborted |
| DETACHED | detached HEAD | determine intent before assigning new work |
| LOCKED | worktree lock present | respect lock; inspect reason |
| PRUNABLE | Git marks administrative entry prunable | cleanup candidate, never auto-prune solely from this scan |
| IDLE_CLEAN | clean and no known active task | possible reusable lane if base/scope/ownership fit |
| UNKNOWN_OWNER | worktree exists but owner/task is not recorded | do not assume it is free |

## Branch Classification

Relative to the integration target:

| State | Typical evidence | Advice |
|---|---|---|
| SYNCED | ahead=0, behind=0 | no sync needed |
| AHEAD_ONLY | ahead>0, behind=0 | review/validate for integration |
| BEHIND_ONLY | ahead=0, behind>0 | likely stale/no unique work; inspect before cleanup |
| DIVERGED | ahead>0, behind>0 | sync strategy required; check rewrite safety |
| FULLY_INTEGRATED | branch is ancestor of target | cleanup candidate if no active dependency/worktree |
| UPSTREAM_GONE | configured upstream no longer exists | inspect whether branch is obsolete or intentionally local |
| REWRITE_FROZEN | another active lane depends on current commit IDs | no uncoordinated rebase/reset |
| UNKNOWN_BASE | integration target/base cannot be established | do not recommend destructive/history-rewriting action |

Age is context, not proof. A branch with an old commit date is not automatically stale or deletable.

## Overlap / Conflict Risk

For active lanes, compare changed-file sets relative to their bases/target. Flag intersections as **overlap hotspots**.

File overlap increases conflict risk but does not prove a semantic conflict. Non-overlap reduces textual conflict risk but does not prove semantic independence (for example schema/API/config changes can affect distant files).

Suggested risk labels:

- LOW: independent files/modules and no known dependency;
- MEDIUM: shared interfaces/config/generated artifacts or uncertain dependency;
- HIGH: same files/hot functions/schema/migrations, or one lane consumes another's unpublished behavior.

## Recommendation Rules

### Starting a new agent

Prefer, in order:

1. an existing clean idle worktree only when ownership is explicitly free and its branch/base can be safely repurposed;
2. otherwise a new branch + worktree based on the correct integration/base commit;
3. do not assign new work into a dirty, conflicted, detached-unknown, or rewrite-frozen lane.

### Merge / integration advice

Before recommending merge/squash/cherry-pick:

- establish target branch and freshness;
- inspect ahead/behind and unique commits;
- inspect dirty/conflicted state;
- check recorded dependencies and commit dependency for selective integration;
- consider changed-file overlap with already queued lanes;
- require validation evidence before declaring safe to integrate.

### Rebase advice

Recommend rebase only when the lane is rewrite-safe. If downstream consumers depend on its commit IDs, prefer merging the updated target into the lane or coordinated retargeting.

### Branch strategy advice

When asked which branching model to use, or whether the current one fits: finish the Quick Scan, classify the model the repository actually follows, and judge it with the fit checklist in `branch-strategy.md`. Existing model and policy win over a preferred one. Propose the smallest change, report remote protection as `unknown` unless it was stated, and do not rename, move, or delete branches while advising.

### Cleanup advice

A branch/worktree is a strong cleanup candidate only when relevant evidence is positive, e.g.:

- worktree is clean and no task/owner depends on it;
- branch is fully integrated or intentionally abandoned;
- no downstream lane references its commits;
- no unique unpushed/unintegrated work would be lost.

Never delete/prune/reset automatically merely because the branch is old, behind, upstream-gone, or not currently checked out.

## Remote Freshness

A local scan can only describe local refs. If remote-current truth materially affects advice:

- identify the remote;
- if authorized and appropriate, run the repository's normal fetch workflow (commonly `git fetch --prune`);
- re-run relevant ahead/behind checks afterward;
- otherwise mark remote freshness as `local-only` or `unknown`.

Fetching updates refs and is therefore not part of the strict read-only phase.

## Advice Report Format

Use a compact report rather than dumping raw Git output:

```text
Repository snapshot
- integration target: main@abc123 (confidence: high)
- worktrees: 5 total / 1 dirty / 0 conflicted / 1 detached
- branches: 8 local / 2 ahead / 1 diverged / 3 fully integrated
- remote freshness: local-only

High-risk findings
1. agent/auth is DIVERGED and is a dependency source for agent/api -> do not rebase it.
2. wt-payment is DIRTY -> do not reuse or remove it.

Recommendations
1. Integrate agent/logging first: AHEAD_ONLY, clean, no recorded dependency.
2. Sync agent/ui after logging integration because both touch app config.
3. Keep agent/auth history frozen; update via merge from target if synchronization is required.
4. Review fully integrated branch agent/old-test as a cleanup candidate; do not delete until ownership is confirmed.
```

Each recommendation should identify the observed evidence, proposed operation, and relevant risk/condition.

## Confidence Discipline

Separate facts from inferences:

- **Observed:** Git directly reports branch, SHA, status, worktree, ancestry, upstream.
- **Recorded:** lane metadata says owner/task/dependency.
- **Inferred:** likely target, likely idle lane, possible semantic overlap.
- **Unknown:** no evidence available.

Never present an inference as a Git fact.
