# git-sweep/remote-delete-safety

- Skill: `git-sweep`
- Feature: Remote branches are deleted only when merged into a branch the remote keeps, one lease-guarded delete at a time
- Result: **PASS**

## Expected behavior

- Deletes only SAFE_CANDIDATE remote branches whose tip is an ancestor of the remote default or origin/<branch>.
- Leaves PENDING_PUSH, KEPT_NOT_MERGED, STALE and protected branches alone.
- Uses only the lease-guarded single-branch delete push and never pushes commits or force-pushes.

## Contract checks

- PASS `references/commands.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-sweep/agents/openai.yaml`

Evidence scope: source-contract check; no AI host CLI is invoked.
