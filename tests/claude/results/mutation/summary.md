# Mutation checks

- Killed: **29/30**; unexpected outcomes: **0**

| Mutation | Verdict | Expected | Caught by |
|---|---|---|---|
| `global-prune` — run a repository-wide `git worktree prune` after deleting | KILLED | killed | `detached-and-prunable`: the detached worktree entry is still listed, command policy: no forbidden git command |
| `force-delete-D` — delete branches with `git branch -D` | KILLED | killed | `upstream-behind`: command policy: no forbidden git command |
| `force-remove-dirty` — drop the dirty/locked gates and pass --force to worktree remove | KILLED | killed | `dirty-source-worktree`: the held branch is kept, its worktree directory is kept, branches are main, the target, and the held branch, uncommitted edit is intact, untracked file is intact, command policy: no forbidden git command |
| `move-main` — force main onto the target after the run | KILLED | killed | `happy-path`: main was not moved, invariant: main did not move |
| `merge-by-name` — merge the bare branch name instead of the recorded SHA | KILLED | killed | `tag-shadow`: the branch content was merged, the branch was deleted and only main and the target remain |
| `no-abort` — leave a conflicted merge in progress | KILLED | killed | `conflict-stops`: no merge is left in progress, the working tree is clean, invariant: no merge left in progress; `conflict-predicted`: no merge is left in progress, the working tree is clean, invariant: no merge left in progress |
| `merge-X-theirs` — resolve conflicts with -X theirs | KILLED | killed | `conflict-stops`: no branch was deleted, the two conflicting sources are not both merged, the stop reason is MERGE_FAILED, command policy: no forbidden git command |
| `case-insensitive-target` — accept a differently-cased target name | KILLED | killed | `case-variant-target`: a stopped command changes nothing, the gate is TARGET_CASE_MISMATCH and suggests the real name |
| `no-ignored-overlap-check` — skip the ignored-file overwrite check before a merge | KILLED | killed | `ignored-overwrite-merge`: the local ignored file is untouched, the source branch is kept, the target did not move, the stop reason is BLOCKED_IGNORED_OVERWRITE |
| `no-rebase-detection` — ignore a rebase in progress | KILLED | killed | `rebase-in-progress`: its stale tip was not merged, the rebasing branch is BLOCKED_IN_PROGRESS |
| `no-unrelated-check` — treat an orphan branch as mergeable | KILLED | killed | `unrelated-history`: the ordinary source was merged and deleted, branches are main, the target, and gh-pages, gh-pages is BLOCKED_UNRELATED_HISTORY, the residual list names gh-pages |
| `ascending-order` — merge the smallest source first | KILLED | killed | `ordering-and-containment`: three merges: big (which carries mid), t1, t2, order is big, then the 2-commit tie by name, then mid; `preview-readonly`: main merges first, then by descending unique commits |
| `delete-without-recheck` — delete with -D and no tip/ancestry recheck | KILLED | killed | `tip-moves-mid-run`: the moved branch keeps its new commit, command policy: no forbidden git command |
| `delete-main` — put main in the delete set | KILLED | killed | `happy-path`: only main and the target remain, main was not moved, invariant: main did not move |
| `ignore-harness-owner` — treat an agent-harness worktree as free | KILLED | killed | `harness-owned-worktree`: the held branch is kept, its worktree directory is kept, branches are main, the target, and the held branch |
| `no-stale-check` — ignore an earlier preview | KILLED | killed | `stale-preview`: nothing changed after the stale-preview stop, the stop reason is STALE_PREVIEW |
| `no-ignored-files-gate` — remove worktrees that hold ignored files | KILLED | killed | `ignored-files-kept`: the branch is kept, the worktree and its ignored file are intact |
| `no-invoking-clean-gate` — run from a dirty invoking worktree | KILLED | killed | `invoking-dirty`: a stopped command changes nothing |
| `mask-remove-failure` — delete the branch even when worktree remove failed | KILLED | killed | `worktree-remove-failure`: the branch whose worktree could not be removed is kept, the skip names the failed worktree removal |
| `bare-target-name` — use the bare target name in revision arguments | KILLED | killed | `target-tag-shadow`: the source's commits reached the target branch, only main and the target remain, the source is MERGE, not CONTAINED |
| `no-sequencer` — ignore a paused cherry-pick sequence | KILLED | killed | `sequencer-in-progress`: the topic branch is BLOCKED_IN_PROGRESS |
| `no-hidden-edits` — treat skip-worktree edits as clean | KILLED | killed | `skip-worktree-edits`: the hidden edit survives, the branch is kept |
| `no-project-harness-root` — forget <repo>/.claude/worktrees as a harness root | KILLED | killed | `claude-session-worktree`: the session branch is kept, the session worktree is kept |
| `no-dependency-fixpoint` — ignore branches that a remaining lane tracks | KILLED | killed | `dependency-of-remaining-lane`: the branch it tracks is kept, the lane's upstream still resolves; `upstream-of-kept`: the tracked branch is kept |
| `exact-ignored-overlap` — compare ignored paths by exact string only | KILLED | killed | `ignored-overwrite-dir-file`: every ignored local file is intact, the source branch is kept, the target did not move, the stop reason is BLOCKED_IGNORED_OVERWRITE; `ignored-overwrite-file-dir`: every ignored local file is intact, the source branch is kept, the target did not move, the stop reason is BLOCKED_IGNORED_OVERWRITE |
| `quoted-ignored-paths` — compare paths in Git's default C-quoted form, with no quoted-name guard | KILLED | killed | `ignored-overwrite-nonascii`: every ignored local file is intact, the source branch is kept, the target did not move, the stop reason is BLOCKED_IGNORED_OVERWRITE |
| `default-quotepath` — list paths without core.quotePath=false (the guard alone) | KILLED | killed | `ignored-nonascii-no-overlap`: the source content was merged, the source branch was deleted, the run did not stop |
| `no-case-collision-check` — ignore branch names that differ only in case | KILLED | killed | `case-colliding-sources`: agent/Feat is kept at its tip, agent/feat is kept at its tip, agent/Feat's commit was not merged, both colliding names are UNKNOWN; `case-colliding-target`: the gate is NAME_CASE_COLLISION |
| `target-move-always-stale` — treat the target's own merges as a stale preview | KILLED | killed | `rerun-after-interrupted-apply`: only main and the target remain, the rerun is not treated as a stale preview |
| `ignore-lock-gate` — drop the lock gate (Git still refuses to remove a locked worktree) | SURVIVED | survive (Git enforces it) | - |
