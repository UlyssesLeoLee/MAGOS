# git-sweep/remote-delete-safety

- Skill: `git-sweep`
- Feature: Remote branches are deleted only when merged into a branch the remote keeps, one lease-guarded delete at a time
- Result: **PASS**

## Expected behavior

- Deletes only SAFE_CANDIDATE remote branches whose tip is an ancestor of the remote default or origin/<branch>.
- Leaves PENDING_PUSH, KEPT_NOT_MERGED, STALE and protected branches alone; a branch merged only into the local <branch> is PUSH_THEN_DELETE while the publish is predicted to run, in the preview with or without --push, and is deleted only after --push has published <branch> in the same run (it becomes SAFE_CANDIDATE); without --push the apply leaves it and reports "kept: --push not typed"; it is PENDING_PUSH only when the publish is not predicted to run or was skipped, failed or unconfirmed.
- Deletes with only the lease-guarded single-branch delete push and, only with --push, the one fast-forward push of <branch>; it never pushes other commits or tags and never force-pushes.

## Contract checks

- PASS `references/commands.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-sweep/agents/openai.yaml`

Evidence scope: source-contract check; no AI host CLI is invoked.
