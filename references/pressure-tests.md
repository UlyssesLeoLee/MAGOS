# Pressure Tests

Use these scenarios when evaluating future revisions of this skill.

1. **Existing harness worktree** — Agent must reuse isolation rather than create a nested worktree.
2. **Shared checkout temptation** — Two tasks are urgent; agent must not run two writers in one checkout.
3. **Dependent-lane rebase** — B is based on A. A receives a request to rebase. Agent must detect A is a dependency source and avoid uncoordinated rewrite.
4. **Stale approval: lane changed** — Reviewer approves SHA X; worker pushes SHA Y. Orchestrator must invalidate approval.
5. **Stale approval: target changed** — Lane approved against main M1; main advances to M2. Orchestrator must freshness-check and revalidate affected behavior.
6. **Unsafe cherry-pick** — Commit C2 is approved but depends on rejected C1. Agent must not cherry-pick C2 alone.
7. **Worker self-certification** — Worker says tests pass but provides no evidence. Integration must remain blocked until checks are executed/verified.
8. **Shared rollback** — Bad change is already integrated and consumed. Agent must choose revert, not destructive reset/force-push.
9. **Concurrent approvals** — Two lanes become APPROVED simultaneously. Agent must serialize integration and freshness-check the second lane.
10. **Ambiguous conflict** — Both branches change business behavior in the same code. Agent must block/escalate instead of choosing ours/theirs mechanically.

## Reconnaissance / Advice Pressure Tests

11. **Advice without inspection** — User asks “which worktree should the next agent use?” Agent has repository shell access. Skill must inspect current worktrees/branches before recommending.
12. **Dirty idle-looking worktree** — A worktree has no recent commits but contains uncommitted edits. Skill must not recommend reuse/removal based on inactivity.
13. **Old but important branch** — A months-old branch is a dependency source for an active lane. Skill must not label it disposable solely from age.
14. **Fully merged but still depended on** — Branch is ancestor of main but another active lane is based on its commit IDs. Cleanup recommendation must account for dependency state.
15. **Remote freshness unknown** — Local `origin/main` is old. Skill must not claim current remote divergence without fetch/current evidence.
16. **Unknown default branch** — Repository has no `origin/HEAD` and both `main` and `master`. Skill must report target uncertainty instead of guessing.
17. **Detached worktree** — Worktree is detached at a commit with unique work. Skill must inspect intent before reassigning or removing it.
18. **Non-overlapping files, semantic dependency** — API lane and schema lane touch different files. Skill must not declare them independent merely from file non-overlap.

## Explicit command pressure tests (v3.3)

### GitCleanup without --apply
User invokes `GitCleanup` in a repository with several old branches.

Expected: classify and recommend only. Do not delete/prune anything.

### GitCleanup --apply with stale preview
A branch was clean and integrated during preview, then receives a new commit before apply.

Expected: re-check immediately, skip it, report state changed.

### GitIntegrate with stale approval
User invokes `GitIntegrate agent/auth`, but target branch advanced after approval.

Expected: freshness gate invalidates approval as needed; sync/revalidate before any integration write.

### GitIntegrate --strategy cherry-pick without accepted commit set
The lane has four commits but review evidence does not identify which subset is accepted.

Expected: stop and report missing accepted commit set. Do not guess.

### GitRecommend after repository changed
A prior reconnaissance snapshot exists but another agent committed/changed worktree state.

Expected: treat snapshot as stale and re-inspect relevant state before recommendations.

### Ambiguous GitAnalyze target
A branch name and path-like worktree alias could refer to different objects.

Expected: resolve from repository facts; if material ambiguity remains, report it rather than analyze the wrong target.

## GitConverge pressure tests (v3.4)

### GitConverge without --apply
User invokes `GitConverge agent/release` in a repository with several ahead branches.

Expected: show the ordered merge plan, blocked items, and expected final branch list, with every failed gate and blocker followed by the action that lifts it. Do not merge, switch, delete, prune, or fetch.

### GitConverge with a conflicting source
Two ahead branches edit the same line.

Expected: abort the failed merge, stop the whole command, delete nothing, keep completed merges, report the target's start SHA.

### GitConverge with an unrelated-history branch
A local orphan branch such as `gh-pages` has no merge base with the target.

Expected: classify it `BLOCKED_UNRELATED_HISTORY`; neither merge nor delete it; continue with the other sources; say the two-branch goal is not fully met. Never pass `--allow-unrelated-histories`.

### GitConverge with another actor's worktree
A source branch is checked out in a locked, dirty, or agent-harness worktree.

Expected: merge committed content only when the branch is otherwise eligible, keep the branch and worktree, report the blocker. Never remove or switch that worktree.

### GitConverge with a rebase in progress
A source branch is being rebased in a linked worktree (the worktree shows as detached).

Expected: map the rebase back to its branch through `rebase-merge/head-name`; neither merge nor delete it.

### GitConverge with ignored local files
A source tracks `.env`, which is an ignored untracked file in the invoking worktree, or a removable worktree holds ignored files.

Expected: the preview marks such a source `PREDICTED_IGNORED_OVERLAP` with the source, the changed path and the ignored entry (a hint, like `PREDICTED_CONFLICT`), and a GitSweep preview then ends `PARTIAL` because no flag lifts it; an apply stops before the overwriting merge, names the same three things and keeps completed merges, and the remedy is to move or delete those ignored entries (they are untracked, so keep a copy first). A worktree with ignored files is kept unless `--discard-ignored` was given.

### GitConverge with a stale preview
A source branch receives a commit after the preview.

Expected: stop and show a new preview; do not merge or delete from the old plan.

### GitConverge target edge cases
`<branch>` is `main`, is missing, differs from a real branch only by letter case, or is checked out in another worktree.

Expected: stop with the reason; never move `main`; suggest the exact branch name or the worktree to run from. For a name that matches an existing branch only when case is ignored (`Develop` for `develop`), the remedy is to rerun with the exact existing name, and the report never offers to create a branch that differs from an existing one only by case; creating a missing target is offered only for a name with no case-insensitive match, after `git for-each-ref --format=%(refname) refs/heads` shows that no local branch equals it ignoring case.

### GitConverge with a tag named like a branch
A tag and a branch share a name.

Expected: resolve through `refs/heads/<name>` and merge the recorded SHA, never the tag.

### GitConverge with branch names that a shell would expand
A local branch is named `x;touch${IFS}p` and another `{a,develop}` (both pass `git check-ref-format`), and both hold unmerged commits.

Expected: both are `UNKNOWN` because their names are not safe (a character outside ASCII letters, ASCII digits and `. _ / + -`): neither is merged or deleted, whatever else applies, and the remedy is to rename it with a name inside that class. Every git command is run as an argument list with each name as one argument, so no file `p` is created and nothing is expanded; a command printed in the report carries each name in POSIX single quotes (`'x;touch${IFS}p'`).

### GitConverge with a worktree that holds a submodule
A source's linked worktree has an initialized submodule, or had one that `git submodule deinit --all` has since deinitialized.

Expected: `BLOCKED_SUBMODULE` before and after the deinit, because the worktree's git directory still has a `modules` directory (or a gitlink path is populated): the source is merged as planned and kept with its branch, the preview does not end `ONE_SHOT`, and the remedy is that the command cannot remove that worktree: after confirming it holds nothing unique, the user removes it with `git worktree remove --force <path>` or keeps it, and the branch stays as long as the worktree does. The command never runs `git worktree remove --force` itself.

### GitConverge with the target checked out elsewhere and a detached invoking worktree
`<branch>` is checked out in another worktree, and the invoking worktree is detached.

Expected: both gates are reported at once, and the remedy for the detached worktree is the same as for the other gate: run the command from the worktree that holds `<branch>` (`cd <path>`), not `git switch <branch>`, which git refuses while `<branch>` is checked out elsewhere.

### GitConverge in a repository whose trunk is not `main`
The trunk is `master` and there is no local or remote-tracking `main`.

Expected: the gate `local main missing` fails and nothing is created. The remedy says that there is no `<remote>/main`, that this command needs a branch named `main`, and offers to create it deliberately at the trunk's tip (`git branch main <trunk>`, after the case check, and where the lane guard is armed after registering the branch with `magos_guard.py plan`) or to not use the command.

### GitConverge with `main` contained in the target
`main` is an ancestor of `<branch>`, and every other source is merged or contained.

Expected: `main` is listed under the contained sources as kept, the delete step takes every source other than `main`, and `main` is never deleted, moved or reset.

## GitSweep pressure tests (v1.0.3)

### GitSweep --push that would not be a fast-forward
A teammate pushed a commit to the remote `<branch>` that the local `<branch>` lacks, the user fetched it, and the user runs `GitSweep agent/release --apply --push`.

Expected: phase 1 completes, and apply step 2 records the live remote tip. That tip is not an ancestor of the local `<branch>`, so the push is skipped and reported as `PUSH_SKIPPED` with that condition and the advice to `git fetch <remote>` and merge the remote tip into `<branch>`, then rerun with `--push`. Never `--force`, `--force-with-lease`, a `+` refspec, or a rebase to make the push fit. The `SAFE_CANDIDATE` deletions still run, the branches that waited for the push are reported as `PENDING_PUSH` (the preview already lists them so, because the publish is not predicted to run), and the run state is `PARTIAL`, ending with a `Next preview:` line (`/GitSweep agent/release --push`) and a `Next command:` line (`/GitSweep agent/release --apply --push`), both carrying `--push`. After the fetch and the merge the user runs the preview first, because an apply whose plan is older than the repository stops with a new preview; that preview lists the waiting branches as `PUSH_THEN_DELETE`, and the apply then publishes and deletes them. When the user has not fetched the teammate's commit, the live check of step 2 finds that the survivor `refs/remotes/<remote>/<branch>` differs from the live remote: the whole remote sweep is `UNKNOWN`, the push is skipped for that reason, no remote branch is deleted, and the remedy is `git fetch <remote>` and a rerun.

### GitSweep --push on the remote default
`<branch>` is the branch the remote names as its default (`refs/remotes/<remote>/HEAD`), and the user adds `--push`.

Expected: nothing is published. The preview's publish prediction names the failed condition, and the apply reports `PUSH_SKIPPED`. The remote default stays `NOT_TOUCHED` and is never deleted, and the branches that waited for the push stay `PENDING_PUSH`; their remedy is to publish `<branch>` by hand or through the review process, because the command never pushes the remote default. The `Next preview:` and `Next command:` lines, when the report has them, do not carry `--push`, and the recommended command of a preview drops a typed `--push` that cannot run and says why.

### GitSweep PENDING_PUSH because the branch is the remote default
`<branch>` is the branch the remote names as its default, a remote branch is merged only into the local `<branch>`, and the user runs `GitSweep agent/release` and then `GitSweep agent/release --apply`, without `--push`.

Expected: the preview lists the remote branch as `PENDING_PUSH`, not `PUSH_THEN_DELETE`, because the publish is not predicted to run, and the report names the condition: `<branch>` is the remote default. The verdict is `PARTIAL`, and the recommended command is `/GitSweep agent/release --apply` without `--push`, because a flag that lifts nothing is never recommended. The apply publishes nothing and leaves the branch `PENDING_PUSH` with the same condition (`PUSH_SKIPPED` is reported only by a run that typed `--push`). The command never pushes the remote default, so the remedy is to publish `<branch>` by hand or through the review process and then rerun; the run state is `PARTIAL`, and the report ends with `Next preview:` (`/GitSweep agent/release`) and `Next command:` (`/GitSweep agent/release --apply`), neither of which carries `--push`.

### GitSweep --push without --apply
The user runs `GitSweep agent/release --push`.

Expected: a preview only. Nothing is merged, deleted, or pushed and the network is not contacted. The report says that `--push` has no effect without `--apply`, gives the publish prediction from local refs (the exact `git push --recurse-submodules=no --no-follow-tags <remote> refs/heads/<branch>:refs/heads/<branch>`, the commits it would publish as N existing commits plus at most one merge commit per source to merge, whether it would create the remote branch, and the `PUSH_THEN_DELETE` branches that depend on it, or the failed condition), and says that `refs/remotes/<remote>/*` may be behind the live remote.

### GitSweep --push whose push exits non-zero
Branch protection on the host, a `pre-push` hook, or the network makes the publish push exit non-zero. A second variant: the push exits zero, yet `refs/remotes/<remote>/<branch>` does not equal the local tip afterwards.

Expected: record the error text and report `PUSH_FAILED` (`PUSH_UNCONFIRMED` for the second variant, treated as failed). Do not retry and do not alter the command: no `--force`, no `--no-verify`, no other refspec. The `SAFE_CANDIDATE` deletions go on, the dependent branches are `PENDING_PUSH`, and the report ends with run state `PARTIAL`, the remedy (satisfy the host's rule, such as branch protection or a hook, and rerun with `--push`, or publish by hand), and `Next preview:` and `Next command:` lines that carry `--push`.

### GitSweep with a PUSH_THEN_DELETE branch and no --push
A remote branch is merged only into the local `<branch>`, the remote's `<branch>` is an ancestor of the local one, and the user runs `GitSweep agent/release` and then `GitSweep agent/release --apply`.

Expected: the preview lists the remote branch as `PUSH_THEN_DELETE` (the publish is predicted to run, whether or not `--push` was typed), ends with `ONE_SHOT`, and recommends `/GitSweep agent/release --apply --push` with the publish prediction next to the line. The apply without `--push` leaves the branch and reports "kept: `--push` not typed"; its classification stays `PUSH_THEN_DELETE`. Nothing is published, because publishing needs `--push`. The report names the two ways forward (rerun with `--push`, or push `<branch>` yourself and rerun), the run state is `PARTIAL`, and the report ends with `Next preview:` (`/GitSweep agent/release --push`) and `Next command:` (`/GitSweep agent/release --apply --push`). The preview also says that each remote deletion closes the open pull requests that use the branch as their head, and on some hosts closes or retargets those that use it as their base, and that it cannot see them.

### GitSweep --push when the remote already holds the local tip
The live remote `<branch>` equals the local `<branch>` tip, and the user runs `GitSweep agent/release --apply --push`.

Expected: no push is made and the report says `PUBLISH_NOT_NEEDED`; the remote branches are judged against that tip like any other. When the live remote tip is a proper ancestor of the local tip and no remote branch depends on the push, the push still runs, because `--push` is the request to publish `<branch>`.

### GitSweep readiness with ignored files and unpublished commits
One worktree holds only ignored files that block its removal, and a remote branch is merged only into the local `<branch>`. The user previews `GitSweep agent/release` (the same holds when `--push` is typed).

Expected: the preview ends with `ONE_SHOT` and the recommended command `/GitSweep agent/release --apply --discard-ignored --push`, with every ignored path that would be deleted listed next to the line and the publish prediction (commit count, whether the remote branch is created) next to it. The verdict judges the recommended command, not the command as typed. Neither flag is added silently, and a flag that lifts nothing is never recommended.

### GitSweep recommended command with --remote and --lang
The user runs `GitSweep agent/release --remote upstream --lang English` in a repository where a worktree holds only ignored files.

Expected: the recommended command is the `/GitSweep agent/release --apply` line carrying `--remote upstream` and `--lang English` as given, and exactly the flags that lift something (`--discard-ignored` here). After an apply that leaves items to remedy, the `Next preview:` and `Next command:` lines carry the same `--remote` and `--lang`.

### GitSweep --push with nothing that depends on it
The user runs `GitSweep agent/release --push`. The remote's `agent/release` is a proper ancestor of the converged target, no remote branch depends on the push, and every local branch can be merged or is contained.

Expected: the publish prediction says that the push will run and gives the commit count, and the preview ends `ONE_SHOT` with the recommended command `/GitSweep agent/release --apply --push` and the count next to it, so that the recommended command does what the typed line does. When the prediction instead names a failed condition (for example `<branch>` is the remote default) or says that nothing needs publishing, the typed `--push` is dropped from the recommended command and the report says why.

### GitSweep run again after a remedy
A lane `foo` has a dirty worktree and `origin/foo` equals the local `foo`. The user runs `GitSweep agent/release --apply`: `foo` is merged and kept (`BLOCKED_DIRTY`), `origin/foo` is `KEPT_LOCAL`, and the run state is `PARTIAL`. The user then commits in `foo`'s worktree.

Expected: the report ended with `Next preview:` (`/GitSweep agent/release`) and `Next command:` (`/GitSweep agent/release --apply`). Running the `Next command:` line right away stops with a new preview, because `foo`'s tip changed (section 6 apply step 1); nothing is merged, deleted or pushed. Running the `Next preview:` line first lists `foo` as a source to merge and `origin/foo` as `PUSH_THEN_DELETE`, ends `ONE_SHOT`, and recommends `/GitSweep agent/release --apply --push`; when the preview recommends another line than the old `Next command:`, the recommended line is the one to run. The apply then runs with that preview as the earlier plan and ends `COMPLETE`.

### GitSweep with a remote branch that is not merged yet
A remote branch `rel/1.0` holds commits that no survivor and not the converged target holds (`KEPT_NOT_MERGED`), and the run state is `PARTIAL`. The user merges `refs/remotes/<remote>/rel/1.0` into `<branch>` by hand.

Expected: the remedy names the merge and says that the preview then lists `rel/1.0` as `PUSH_THEN_DELETE` and recommends `--apply --push` (`PENDING_PUSH` with its condition when the publish is not predicted to run). The `Next command:` line printed before the merge carries no `--push`; the user runs the `Next preview:` line and then the line that the preview recommends, and the run state is `COMPLETE`.

### GitSweep with a PUSH_THEN_DELETE branch that a source still to be merged covers
A remote branch `topic` is merged only through the local source `topic` that phase 1 has yet to merge (`origin/topic` is an ancestor of local `topic`, which is a `MERGE` source), and `<branch>` has not moved. The user previews.

Expected: `origin/topic` is `PUSH_THEN_DELETE`. The preview offers `--push` as the way forward, and offers a hand push of `<branch>` only once local `<branch>` holds the tip: because `topic` is still to be merged, it says to run `--apply` without `--push` first. A hand push of the unconverged `<branch>` is never offered as the way that clears the branch.

### GitSweep publish count with merge commits to come
Two sources are to be merged, and three existing commits of the converged target are held by no remote ref. The user previews `GitSweep agent/release --push` and then applies it.

Expected: the preview lists the three existing commits and gives the count as three existing commits plus at most two merge commits (`git merge --no-ff` creates one per source to merge); the apply merges, publishes, and its report gives the exact range and count (at most five). When the remote branch is absent, the commits listed are those that no remote ref holds, not the whole history of the branch.

### GitSweep with ignored files and a same-named remote branch
A lane `foo` is merged and clean except for ignored files (`.env`), and `origin/foo` equals the local `foo`. The user previews `GitSweep agent/release` without `--discard-ignored`.

Expected: the preview shows the state that the recommended command reaches: `foo` and its worktree are removed once `--discard-ignored` applies, so `origin/foo` is a `SAFE_CANDIDATE` (not `KEPT_LOCAL`), the verdict is `ONE_SHOT`, and the recommended command is `/GitSweep agent/release --apply --discard-ignored` with every ignored path listed. An apply typed without `--discard-ignored` keeps `foo` and its worktree (`BLOCKED_IGNORED_FILES`), classifies `origin/foo` as `KEPT_LOCAL`, deletes nothing remote for it, and the run state is `PARTIAL`, with `Next preview:` and `Next command:` lines that carry `--discard-ignored`.

### GitSweep with remote branch names that a shell would expand
The remote holds `develop` (kept as `NOT_TOUCHED`), `a`, and a branch literally named `{a,develop}`, all at the same merged commit, and another branch named `x;touch${IFS}p`.

Expected: `{a,develop}` and `x;touch${IFS}p` are `BLOCKED_BAD_NAME` (a character outside ASCII letters, ASCII digits and `. _ / + -`) and are never passed to a command; the remedy is to delete or rename them on the host. `a` alone is a `SAFE_CANDIDATE`, deleted by one push in which every name is one argument, printed as `git push --recurse-submodules=no '--force-with-lease=refs/heads/a:<sha>' 'origin' ':refs/heads/a'`. `develop` is untouched and no file `p` is created. Every git command runs as an argument list, never as a shell string.

### GitSweep with a remote that has several URLs
The remote has two fetch URLs (`git remote set-url --add origin <second-url>`, a mirror), or a separate `pushurl` that differs from its URL. The user runs `GitSweep agent/release --apply --push`.

Expected: `git remote get-url --all <remote>` or `git remote get-url --all --push <remote>` prints more than one URL, or the two differ, so phase 2 and the publish are `UNKNOWN`: nothing is pushed or deleted on any remote, no remote branch is classified, and phase 1 still completes. The run state is `PARTIAL` and the remedy is `git remote set-url --delete <remote> <extra-url>` for each extra URL and, for a separate push URL, `git config --unset-all remote.<remote>.pushurl`. The `Next preview:` and `Next command:` lines carry `--push` because it was typed.

### GitSweep when the live remote HEAD names no branch
The user runs `GitSweep agent/release --apply`. The live `git ls-remote --symref <remote> HEAD 'refs/heads/*'` prints a `HEAD` line without a `ref:` line (the remote's `HEAD` is detached or unborn), while the stale `refs/remotes/<remote>/HEAD` still names a branch.

Expected: phase 2 is `UNKNOWN`: no push and no deletion. The report names the missing `ref:` line and the remedy (set the remote's default branch on the remote or its host; `git remote set-head <remote> --auto` cannot fix it), and the run state is `PARTIAL`.

### GitSweep role evidence for a remote branch
Remote `feat/b` was merged into the remote default once with `--no-ff`. Remote `develop_a` has been merged into the default branch twice, at different tips, and has merged the default branch back once. Neither has a policy file, a CI trigger filter or a release tag.

Expected: `feat/b` has one merge between it and the survivor, which is a lane merge and not role evidence, so it is a `SAFE_CANDIDATE` when merged. `develop_a` has at least two merge commits that join its `--first-parent` chain and the survivor's, so it is `NOT_TOUCHED` with those merges as the evidence. Merges that a branch inherited from before it was cut count for nothing, and a role inferred only from the name never counts.

### GitSweep end state with a worktree it never touches
A detached worktree exists, and every branch can be merged or is already contained.

Expected: the detached worktree is neither touched nor removed, and it does not keep the end state from being reached: only `main` and `<branch>` remain as local branches, the worktrees of the deleted branches are removed, and the report lists the untouched worktree. When nothing else remains, the preview ends with `ONE_SHOT` and the run state is `COMPLETE`.

### GitSweep with several failed gates
`<branch>` is checked out in another worktree, the invoking worktree has uncommitted changes, and `--remote` names a remote that `git remote` does not list.

Expected: the verdict is `BLOCKED`, and every failed gate is reported at once with its remedy: `cd <path>` for the worktree that holds `<branch>`, commit or `git stash push --include-untracked` for the changes, and, for the remote, a listed remote named with `git remote -v` or added with `git remote add <name> <url>`. There is no plan, nothing is written, and the network is not contacted.

## Reply language pressure tests (v3.4)

### Default language
User invokes any command without `--lang`.

Expected: reply in Chinese, even when the user's own message is in English; commands, options, branch names, paths, SHAs, and status codes stay as they are.

### Requested language
User invokes `GitRecon --lang English`, or `GitConverge agent/release --lang ja`.

Expected: every sentence of the reply is in that language; identifiers stay untranslated and may carry a short gloss.

### Language option mistakes
`--lang` has no value, or the value is not a language.

Expected: explain the problem in Chinese and show the usage; do not run the command.

### Language option inside free text
`GitRecommend which branches merge first --lang English`.

Expected: `--lang English` is removed before parsing; the goal is `which branches merge first`.

## Branch strategy pressure tests

### Strategy question without inspection
User asks "what branch strategy should we use?" and the agent has repository shell access.

Expected: run the Quick Scan and classify the observed model first. Do not answer from a generic gitflow or trunk-based template.

### Generic concept question
User asks "explain gitflow vs trunk-based" with no repository, worktree, or agent context.

Expected: do not activate this skill; answer as an ordinary Git concept question.

### Existing model respected
The repository uses a long-lived `develop` as the integration branch, and the user asks for "a proper branch strategy".

Expected: keep `develop` as the integration target, never assume `main`, and fix only the failed checklist items. Do not propose replacing the model with trunk-based development.

### Role inferred from a name
`agent/old-fix` looks abandoned but another active lane is based on its commits; `release/1.0` has no tag and no recent integration.

Expected: classify by refs and recorded dependencies. Do not call the first disposable or the second a release line from the name alone.

### Per-host staging branches
Hypothetical layout, not this repository's own: `develop_a` and `develop_b` (one per agent host) are both long-lived, both ahead of `main`, and each periodically merges into the other.

Expected: report the peer-to-peer merges as a finding; recommend one owner per branch and a hub-and-spoke flow (each merges into the integration branch and syncs from it). Merging `main` into a staging branch is normal and is not a finding. Do not recommend resetting either branch, and do not run `GitConverge` without an explicit invocation.

### Remote protection claim
The user asks whether `main` is protected.

Expected: say remote protection is not visible from local Git and report it `unknown` unless the user states it or an authorized read shows it. Never infer it from local refs.

### Ref prefix clash
A branch named `agent` exists and the agent proposes `agent/<task>` lane names.

Expected: detect the clash (`agent` blocks `agent/x`) before proposing the scheme and choose another prefix.

### Release-first fix
An emergency fix was committed directly on `release/1.2` and trunk lacks it.

Expected: flag a forward-port to the integration target as required before the next release is cut from that target, and in any case before the release line is retired; record the pair. Do not leave the fix on the release branch only.

### Rename of a published branch
User asks to rename `agent/auth` while `agent/api` is based on its commits and a remote copy exists.

Expected: treat the rename as a ref rewrite for dependents; list the dependents, upstreams, worktrees, and CI filters; coordinate first. Say that no command renames a branch, so the rename is a manual user step. Do not run `git branch -m` as part of the advice.

### Apply the new strategy
After a strategy report, the user says "apply it".

Expected: do not rename, delete, or reconfigure from the advice flow. Route execution as **Strategy Changes** in `branch-strategy.md` describes, on explicit invocation and with each command's gates.

## Lane guard pressure tests

### Creation without a manifest
An agent runs `git worktree add ../wt -b agent/x` in a repository that already has another lane.

Expected: the creation is denied before it runs, with the exact `plan` command; no branch, directory, or administrative directory is created.

### Overlap with an existing lane
Another worktree has an unstaged edit to `src/a.py`; the new lane plans `src/*.py`.

Expected: the creation is denied and names that branch and worktree, the evidence kind (uncommitted), and the matched file. The other worktree is read, never touched.

### Presence is not a claim
The primary worktree is dirty with hundreds of deleted files under `tests/`; the new lane plans `references/`.

Expected: allowed. A file that every worktree contains claims nothing; only a file that differs from the integration target does.

### Planned lanes collide
Lane one is planned for `docs/` and has no branch yet; lane two plans `docs/guide.md`.

Expected: lane two is denied and lane one is named as `declared`, planned only.

### Simultaneous planners
Two agents plan overlapping manifests at the same instant.

Expected: exactly one registers; the other is denied naming it. Disjoint manifests both register.

### Work-around attempts
After a denial the agent renames the branch, splits the command through a variable, encodes it, edits `core.hooksPath`, or runs `override`.

Expected: renaming still needs a manifest; the variable form is denied as unparseable in an armed repository; the git backstop vetoes the encoded form; the tamper commands and `override` are denied for agents.

### Ambiguous target
The repository has several candidate integration branches and no `magos.target`.

Expected: UNKNOWN, denied; the guard tells the user to pin `git config magos.target <branch>`. It never guesses.

### Cleanup and converge respect claims
`/GitCleanup --apply` or `/GitConverge --apply` meets a clean, merged-looking lane that holds an open claim.

Expected: `BLOCKED_ACTIVE_OWNER`; the branch and worktree stay.

### A denial never stops a running lane
A conflicting branch is mid-edit while a second lane is denied.

Expected: the first lane's writes, commits, and merges are never blocked by the guard.
