# git-sweep/push-target

- Skill: `git-sweep`
- Feature: --push publishes the local branch with one fixed fast-forward push, only when every condition holds; nothing else ever pushes commits
- Result: **PASS**

## Expected behavior

- Publishes only refs/heads/<branch>, with exactly git push --no-follow-tags <remote> refs/heads/<branch>:refs/heads/<branch>: a fast-forward push, never forced, never --no-verify, never tags.
- Skips the push and reports PUSH_SKIPPED when the live remote tip is not an ancestor of the local branch, when <branch> is main or the remote default, when the converge phase stopped or its validation failed, or when the remote sweep is UNKNOWN.
- A push that exits non-zero is PUSH_FAILED and one whose remote-tracking ref does not match is PUSH_UNCONFIRMED; neither is retried with another command, and the branches that waited for it are reported as PENDING_PUSH with that reason.
- Publishes nothing and reports PUBLISH_NOT_NEEDED when the live remote tip already equals the local tip; otherwise the push runs even when no remote branch depends on it, because --push is the request to publish <branch>.
- A remote branch merged only into the converged target is PUSH_THEN_DELETE when the publish step is predicted to run, whether or not --push was typed (with --push the apply publishes first and deletes after; without --push it leaves the branch and reports "kept: --push not typed"), and PENDING_PUSH otherwise or when the publish was skipped, failed or unconfirmed; both are decided against the converged target, so a preview and the apply after it agree; without --apply the push is only predicted, and the preview gives that prediction whether or not --push was typed.
- The hard stop reads: except the one fast-forward push of <branch> that --push makes, never push commits or tags and never force-push; /GitConverge never pushes.
- When the push cannot run, the apply says so: phase 1 stopped or phase 2 UNKNOWN delete no remote branch at all, while a live remote tip that is not an ancestor, or a <branch> that is main or the remote default, skips only the push and the SAFE_CANDIDATE deletions go on.
- When <branch> is the remote default the publish is never predicted to run: a remote branch merged only into the local <branch> is PENDING_PUSH with or without --push, the report names that condition, the recommended command and the Next command: line carry no --push, and the remedy is to publish <branch> by hand or through the review process, because the command never pushes the remote default.

## Contract checks

- PASS `references/commands.md`
- PASS `references/commands.md`
- PASS `references/commands.md`
- PASS `references/commands.md`
- PASS `references/commands.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `SKILL.md`
- PASS `commands/GitConverge.md`
- PASS `skills/git-converge/SKILL.md`
- PASS `references/pressure-tests.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
