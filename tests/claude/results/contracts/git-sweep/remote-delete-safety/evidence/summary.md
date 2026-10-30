# git-sweep/remote-delete-safety

- Skill: `git-sweep`
- Feature: Remote branches are deleted only when merged into a branch the remote keeps, one lease-guarded delete at a time
- Result: **PASS**

## Expected behavior

- Deletes only SAFE_CANDIDATE remote branches whose tip is an ancestor of the remote default or origin/<branch>.
- Leaves PENDING_PUSH, KEPT_NOT_MERGED, STALE and protected branches alone; a branch merged only into the local <branch> is PUSH_THEN_DELETE while the publish is predicted to run, in the preview with or without --push, and is deleted only after --push has published <branch> in the same run (it becomes SAFE_CANDIDATE); without --push the apply leaves it and reports "kept: --push not typed"; it is PENDING_PUSH only when the publish is not predicted to run or was skipped, failed or unconfirmed.
- Deletes with only the lease-guarded single-branch delete push (git push --recurse-submodules=no --force-with-lease=refs/heads/<name>:<sha> <remote> :refs/heads/<name>) and, only with --push, the one fast-forward push of <branch>; it never pushes other commits or tags, never force-pushes, never lets a push reach another repository than the remote or recurse into submodules, and runs every git command as an argument list.
- A remote with several URLs (or a push URL that differs from the fetch URL), a live remote HEAD that names no branch, and a name outside ASCII letters, digits and . _ / + - (BLOCKED_BAD_NAME) each keep a remote branch from being deleted; a long-lived role needs a policy file, CI filters, release tags or at least two merge commits between the branch and a survivor, and one merge is a lane merge.

## Contract checks

- PASS `references/commands.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-sweep/agents/openai.yaml`
- PASS `references/commands.md`
- PASS `references/pressure-tests.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `SKILL.md`
- PASS `README.en.md`
- PASS `README.md`
- PASS `README.ja.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
