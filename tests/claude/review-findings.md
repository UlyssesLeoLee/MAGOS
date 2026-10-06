# Design review of GitConverge: findings and dispositions

The first GitConverge design was attacked by five reviewers (request fidelity, Git mechanics, safety against the repository's
own rules, edge cases, repository consistency). Each confirmed finding was then checked by a skeptic. Part of that second pass
died on a usage limit, so 36 findings went unverified; those were triaged by hand and the Git claims among them were
reproduced with `git_behavior_probes.py` before being accepted.

Dispositions: **adopted** (contract changed), **modified** (adopted in a different form), **deferred** (known gap),
**rejected** (kept as designed). "Covered by" names the test that would notice a regression.

## Confirmed by a skeptic (24)

| Finding | Disposition | Covered by |
|---|---|---|
| Repository-wide `git worktree prune` also drops detached worktrees and orphans their commits | adopted: worktrees are removed by path, never pruned | `detached-and-prunable`, probe `prune_scope`, mutation `global-prune` |
| `BLOCKED_ACTIVE_OWNER` / `UNKNOWN` had no evidence rule | adopted: "active owner" defined (locked, in progress, agent-harness root, other lane owner) | `harness-owned-worktree`, `locked-source-worktree`, mutation `ignore-harness-owner` |
| A detached invoking worktree would be switched, orphaning its commits | adopted: gate `INVOKING_DETACHED` | `invoking-detached` |
| `/GitConverge main` undefined, conflicts with "main is never moved" | adopted: gate `TARGET_IS_MAIN` | `target-is-main` |
| Validation has no baseline and is not shown in the preview | modified: preview reports the checks; a failing check stops deletion; "not validated" continues. Baseline run deferred | `validation-fails` |
| Preview never states the final branch set | adopted: "Expected final state" with reasons | `happy-path` (plan oracle) |
| Commits on a source's upstream that are missing locally vanish silently | modified: the report states that remote branches keep their copy and lack the new commits | `upstream-behind` |
| `--no-ff` hard-coded against repository merge policy | modified: `--no-ff` by default, another shape only by policy, never squash/rebase | `git-converge/merge-procedure` |
| Stale-preview rule ignores a moved target | adopted: any moved tip stops the whole command | `stale-preview`, mutation `no-stale-check` |
| `--apply` not tied to a preview | modified: `--apply` acts on the plan it prints; an earlier preview is compared; new branches are left alone. **Judgment call, see below** | `stale-preview`, `appeared-after-preview` |
| Another actor's worktree can be removed, used as the merge workspace, or switched | adopted: only the invoking worktree is written to or switched | `target-checked-out-elsewhere`, `run-from-target-worktree` |
| A failed `git worktree remove` leaves a half-deleted worktree and the branch is then deleted | adopted: keep the branch, report the partial state, never `--force` | `worktree-remove-failure`, mutation `mask-remove-failure` |
| Ignored files (`.env`) in removed worktrees are listed but never gate `--apply` | adopted: `BLOCKED_IGNORED_FILES`; `--discard-ignored` is the explicit consent | `ignored-files-kept`, `ignored-files-discard`, mutation `no-ignored-files-gate` |
| A branch mid-rebase/bisect looks free; its stale tip would be merged | adopted: mapped through `rebase-merge/head-name` etc. | `rebase-in-progress`, probe `rebase_in_progress`, mutation `no-rebase-detection` |
| Short names let a same-named tag stand in for a branch | adopted: full refnames and recorded SHAs | `tag-shadow`, mutation `merge-by-name` |
| Design contradicts `SKILL.md` Hard Stops and the GitIntegrate gates | adopted: explicit acceptance rule in `SKILL.md` and section 6 | `git-converge/acceptance-and-freshness` |
| No rule for an unloadable skill on a writing command | adopted: preview only | `git-converge/explicit-invocation-only` |
| `run_host_cases.py`: an unknown assertion silently passes | deferred: no GitConverge host cases were added there; noted for that runner | none |
| One fixture cannot serve apply and conflict cases | adopted: one builder per scenario | scenario registry |
| Missing files in the change list (counts, versions, probes) | adopted | `git-converge/package-wiring`, aggregate cases in `tests/codex` |

## Triaged by hand (the 36 that lost their skeptic)

| Finding | Disposition | Covered by |
|---|---|---|
| Case-variant `<branch>` resolves on NTFS and deletes its own target | adopted: exact match against `for-each-ref`; probe showed `refs/heads/Target` resolves here | `case-variant-target`, probe `case_refs`, mutation `case-insensitive-target` |
| An orphan branch stops the command forever | adopted: `BLOCKED_UNRELATED_HISTORY`, kept, not a stop | `unrelated-history`, mutation `no-unrelated-check` |
| Merges silently overwrite ignored files; `--no-overwrite-ignore` does not apply to merge | adopted: path overlap check before each merge; `switch --no-overwrite-ignore` | `ignored-overwrite-merge`, probe `ignored_overwrite`, mutation `no-ignored-overlap-check` |
| `branch -d` judges a branch against its upstream; `-D` has a check/delete gap | adopted: `--unset-upstream` then `-d`, restore on failure; never `-D` | `upstream-behind`, probes `upstream_behind` / `upstream_read`, mutations `force-delete-D`, `delete-without-recheck` |
| Clean check hides untracked files under `status.showUntrackedFiles=no` | adopted: always `--untracked-files=all` | probe `untracked_hidden`, `invoking-dirty` |
| Ordering by committer date merges a contained source first | adopted: descending unique-commit count, ties by name | `ordering-and-containment`, mutation `ascending-order` |
| A kept branch that tracks a deleted local branch breaks `-d` | adopted: `BLOCKED_UPSTREAM_OF_KEPT` | `upstream-of-kept` |
| Worktrees with initialized submodules refuse removal | adopted: `BLOCKED_SUBMODULE` | `submodule-worktree` |
| Target or `main` held only by a prunable entry cannot be switched to | adopted: gates | `target-prunable-entry`, `main-prunable-entry` |
| Truncated commit lists are silent caps | adopted: counts exact; shortening only with "(N more)" | `git-converge/preview-default` |
| Reflog-only commits make "restorable by SHA" overstated | modified: report says the deleted branch's reflog is not kept | `git-converge/delete-safety` |
| Rerun after interruption is not idempotent | modified: a rerun starts from a fresh survey; merged sources become CONTAINED | `rerun-after-stop` |
| Bare main repository can leave `HEAD` dangling | deferred: bare layouts are out of scope | none |
| `merge-tree` cannot see a clash between two sources | adopted as a documented limit and tested | `conflict-stops` (plan oracle) |

## Refuted by a skeptic (3)

| Finding | Why it stays as designed |
|---|---|
| Sources in a dirty or locked worktree should not be merged | The user asked for "all ahead content". Only the worktree and branch are kept; committed content is merged. Tested by `dirty-source-worktree`, `locked-source-worktree` |
| Adapter description strings are unpinned | The aggregate contract cases already pin the 77- and 120-character limits |
| Codex `workspace-write` sandbox may block fixture worktrees | Not a GitConverge defect; `tests/codex` owns that runner |

## Judgment call left for the user

`--apply` with no earlier preview in the conversation **runs on the plan it records itself and reports at the end**, rather
than refusing until a preview exists or printing the plan before the first merge. That matches "preview by default, `--apply`
executes". The user chose this (option 2) after two rounds of real-CLI runs showed that agents report the plan but do not
print it first. The stricter alternative (print the plan and stop until a second `--apply`) is a small change in section 6
step 1 and in `SKILL.md`.

# Code review of the implementation (max effort)

After implementation, the working-tree changes were reviewed by 10 finder angles: line scan, removed behavior,
cross-file, language pitfalls, wrappers, reuse, simplification, efficiency, altitude, and conventions. That produced 67
candidates, 43 after dedup. One verifier per batch voted on each; 42 survived and 1 was refuted. A gap sweep added 7 more,
all confirmed. The 15 most severe were reported; every fix below is covered by a test that was shown to fail without it
(probe, scenario, contract case, or mutation).

## Reported findings and fixes

| # | Finding | Fix | Covered by |
|---|---|---|---|
| 1 | Gate 6(b) and the preview count used the bare target name; a target-named tag made an unmerged branch look contained | every revision argument is `refs/heads/<name>` or a recorded SHA; tag collisions with the target are reported | `target-tag-shadow`, probe `target_tag_shadow`, mutation `bare-target-name` |
| 2 | Ignored-file overwrite check compared exact strings; case variants and directory/file clashes slipped through | listing uses `--directory`; overlap = equal, nested either way, or case-folded when `core.ignorecase` | `ignored-overwrite-case`, `-dir-file`, `-file-dir`, mutation `exact-ignored-overlap` |
| 3 | Harness root named `~/.claude/worktrees/`; Claude Code session worktrees live in `<repo>/.claude/worktrees/` | project-local root added to the contract and the executor | `claude-session-worktree`, mutation `no-project-harness-root` |
| 4 | `sequencer/` missing from the in-progress markers | added; every worktree, detached ones included, is checked | `sequencer-in-progress`, probe `sequencer_paused`, mutation `no-sequencer` |
| 5 | "Clean" was blind to skip-worktree / assume-unchanged edits | `ls-files -v` flags present on disk make a worktree dirty | `skip-worktree-edits`, probe `skip_worktree_hidden`, mutation `no-hidden-edits` |
| 6 | Dependency guard only looked at `main` and the target | evaluated against every branch that will remain, to a fixpoint | `dependency-of-remaining-lane`, mutation `no-dependency-fixpoint` |
| 7 | One class per source, no precedence, and step 4 skipped blocked sources | two axes: one merge status (UNRELATED > IN_PROGRESS > CONTAINED > MERGE) plus delete blockers; step 4 merges every `MERGE` | contract case `two-axis-classification`; dirty/locked/owned scenarios |
| 8 | Unknown-owner worktrees removed silently, against reconnaissance UNKNOWN_OWNER | stated as the single exception; the plan marks such removals "owner: not recorded" | contract case `ownership-roots` |
| 9 | A rerun after an interrupted apply always looked stale | the target may move only through merges of tips recorded in the earlier plan | `rerun-after-interrupted-apply`, mutation `target-move-always-stale` |
| 10 | Adapters forbade only force-push | both adapters and `SKILL.md`: never push, force-push, or delete remote branches | contract case `delete-safety` |
| 11 | Runtime PASS possible for runs that never worked (CLI startup git calls satisfied the liveness guard; result event unread) | liveness from the transcript; result subtype checked; CLI-internal git calls dropped; report words checked; exit 2 for UNVERIFIED | runtime evidence: a missing CLI now yields UNVERIFIED |
| 12 | `KeyError: 'main'` when `main` was mid-merge or mid-rebase | holder lookups are safe; `main` gets its own status | `main-in-progress` |
| 13 | Policy missed `-Xtheirs`, `--strategy-option=theirs`, `branch -df`, `worktree remove -ff`, `switch -C`, `checkout -B/-f`, remote-tracking deletion | options normalized; apply mode is an allow-list of contract writes with named forbidden forms | `test_command_policy.py` (attached/bundled rows) |
| 14 | `rebase-in-progress` could never fail its "stale tip not merged" check | fixture stops the rebase with `--exec false`, so the stale tip would merge cleanly if ignored | `rebase-in-progress`, mutation `no-rebase-detection` |
| 15 | Read-only classification wrong both ways (`symbolic-ref` writes passed; `check-ignore`, `cherry`, `tag --contains` failed) | per-subcommand rules; values of options are not positionals | `test_command_policy.py` |

## Also fixed (beyond the reported 15)

- Worktrees that appear after the preview keep their branch (`worktree-appeared-after-preview`).
- Shared invariants (`main`, tags, remote, remote-tracking refs, no merge in progress) run on every scenario.
- `gitlab.is_ancestor` raises on Git errors instead of reading them as "not an ancestor".
- Test hooks and validators run untraced; the runtime runner handles a CLI that cannot start, timeouts with bytes output,
  a missing `claude` on PATH, flow-only scenarios (now excluded), and an empty `--case` selection.
- Stale counts: `tests/codex` install-layout case (six adapters), codex README coverage claim, a `git-converge/help` host case.
- Adapter descriptions list `--discard-ignored` (76/77 and 64/64 characters).
- Fewer git processes: one `rev-parse --git-path` per worktree, one tracking read, and one inventory per deletion.
- `remove_current` is an observation, not counted as a passing probe; the mutation docstring counts one survivor.

## Not changed

- **AGENTS.md says test evidence lives under `tests/codex`.** You asked for `tests/claude/`, so `AGENTS.md` was left as is.
  Say if you want a line added there.
- **Parallel scenario execution (efficiency).** The trace is process-global, so running scenarios in parallel would mix
  traces. It was left sequential.

# Full-package review (2026-10)

Eight reviewers (core rules, Claude commands, Codex/Hermes adapters, Git semantics, installer, docs and package, both test
harnesses) and a completeness critic produced 74 findings. Each was checked by one or two skeptics, who reproduced the Git
claims in disposable repositories: 59 confirmed, 15 refuted. This round fixed the four high-severity findings, three missing
GitCleanup protections, and the Claude Code install text. The remaining medium and low findings are open.

| Finding | Disposition | Covered by |
|---|---|---|
| GitCleanup listed a repository-wide `git worktree prune` as a safe operation (it orphans detached commits whose directory is missing) | adopted: removed; worktrees, prunable entries included, are removed by path only (a detached prunable entry is `UNKNOWN`); the ban is repeated in the wrapper and the adapter | `git-cleanup/apply-safe-only` pins the exact safe-operations block, so re-adding the command fails it |
| GitCleanup never defined "dirty": `status.showUntrackedFiles=no` hides untracked files, and `git worktree remove` deletes ignored files such as `.env` | adopted: section 6's **clean** applies; new `BLOCKED_IGNORED_FILES` with no override (move or delete the files by hand, then run GitCleanup again) | `git-cleanup/preview-classification` |
| GitCleanup had no in-progress rule: a worktree stopped mid-rebase looks clean and detached | adopted: new `BLOCKED_IN_PROGRESS`, using section 6's **in progress** | `git-cleanup/preview-classification` |
| GitCleanup could list `main`, the integration target, or the invoking worktree | adopted: "never a candidate" | `git-cleanup/preview-classification`, `git-cleanup/apply-safe-only` |
| The ignored-file overlap check compared raw output: with the default `core.quotePath` a non-ASCII path is C-quoted and never matches | adopted: both listings run from the worktree top level with `-c core.quotePath=false`; when the worktree has ignored entries, a name Git still quotes makes every changed path count as overlapping | `ignored-overwrite-nonascii`, `ignored-nonascii-no-overlap`, mutations `quoted-ignored-paths` and `default-quotepath`, `git-converge/ignored-files` |
| Two branches whose names differ only in case: `refs/heads/<name>` can read the other one's loose ref, and `git branch -d` can remove both | adopted: SHAs come from one `for-each-ref` listing; both names are `UNKNOWN`; a collision with the target or `main` is gate `NAME_CASE_COLLISION`; the report gives a safe rename (`git pack-refs --all` first: a plain `git branch -m` on a colliding packed name gave the new name the other branch's tip and deleted both refs in a scratch repository) | `case-colliding-sources`, `case-colliding-target`, mutation `no-case-collision-check`, `git-converge/refname-safety` |
| `rev-parse --git-path` is relative for the main worktree, so an existence test from another directory misses its in-progress markers | adopted in the contract text (the executor already resolved it against the worktree) | `git-converge/hidden-state` |
| README.en.md said dropping the skill into `~/.claude/skills/` gives the `/Git` commands; no install text said the copies go stale after an update | adopted: both READMEs and the root `SKILL.md` say the commands come only from `~/.claude/commands/` and must be re-synced after every update (`sync_hosts.py --host claude`) | not tested (documentation) |

A second, two-reviewer pass over these fixes found the gaps that the rows above already include: the rename advice, the
quoted-name guard covering only one listing and firing without ignored entries, listings not anchored to the top level,
an H1 pin that could not fail, a misleading `/GitConverge --discard-ignored` hint, and a missing rule for prunable entries.
It also found that importing section 6's **active owner** would have let GitCleanup remove worktrees whose owner is not
recorded (GitConverge's **unknown owner** exception); GitCleanup now reports them as `UNKNOWN` instead.

Trade-offs: GitCleanup now keeps every worktree that holds ignored files, including `node_modules/` or `.venv/`, because
it cannot tell a cache from a secret; and it keeps every linked worktree whose owner is not recorded, as the
reconnaissance rule `UNKNOWN_OWNER` already required.
