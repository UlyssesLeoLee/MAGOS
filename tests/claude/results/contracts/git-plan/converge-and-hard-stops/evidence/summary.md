# git-plan/converge-and-hard-stops

- Skill: `git-plan`
- Feature: --converge merges the recorded lane heads in dependency order into one integration branch, stops on a conflict, lands only by one fast-forward and never pushes, deletes or overrides
- Result: **PASS**

## Expected behavior

- A converge preview evaluates every lane (INTEGRATED, READY, the pending BLOCKED, NOT_READY and WAITING, the failing MISSING_BRANCH, DIRTY, IN_PROGRESS, NO_MERGE_BASE, OUT_OF_LANE, SHARED_CHANGE, MOVED, CLAIM_DRIFT and STALE_PLAN, and the hint PREDICTED_CONFLICT); a failing finding stops the whole command so that a ready lane that is inconsistent is never merged around, and the readiness is READY, PARTIAL or BLOCKED with the next command and the remedy of every failed gate.
- --converge --apply is the user's acceptance of the recorded lane heads it puts in its report: it re-surveys, stops when a lane head, the target tip or the revision differs from the earlier preview, creates agent/<set>/integration with a plain git switch -c from the current target tip in the invoking worktree, merges each READY lane's recorded head with git merge --no-ff in dependency order, records each with set-update, and runs the repository checks before any land.
- A conflict lists the unmerged paths, runs git merge --abort and stops; it is never resolved with ours, theirs or by hand, the completed merges stay on the integration branch only, and the report names the lane, the files, the error text and the integration start SHA.
- --land adds one git merge --ff-only of the integration branch into the target, only while every lane is integrated and the target still sits at the integration start SHA (otherwise LAND_REFUSED with both SHAs and nothing else); --release prints the final supplemented tables and then removes only the claims and the record.
- The hard stops: never push, fetch, force, delete a branch or a worktree, touch main, use override, arm, disarm or install, edit .git/magos or write the record other than through set-plan, set-update and set-release, rebase, squash, cherry-pick, reset, resolve a conflict with ours or theirs, write inside a lane worktree, or merge anything but a recorded lane head; every git and guard command is an argument list.
- Every gate, finding, guard exit code and stop of an apply is followed by its remedy, which the command never performs; a rerun after an interruption resumes on the same integration branch and skips the lanes that are already integrated.
- After the merge the original list is supplemented, not replaced: when a lane is recorded integrated the guard stores the changes of the lane (commits, subjects, files, insertions, deletions, paths) computed from git against the local target branch of that moment, and the converge apply report, --status and --release print the same tables with a Changes column on the Lanes table, a Result column on the Requirements table, the Changes summary (one line per lane) and a Total line.

## Contract checks

- PASS `references/commands.md`
- PASS `commands/GitPlan.md`
- PASS `skills/git-plan/SKILL.md`
- PASS `skills/git-plan/agents/openai.yaml`
- PASS `SKILL.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`
- PASS `CHANGELOG.md`
- PASS `RELEASE_NOTES_1.0.4.md`
- PASS `references/pressure-tests.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
