# git-sweep/preview-and-help

- Skill: `git-sweep`
- Feature: Preview and help neither write nor contact the network
- Result: **PASS**

## Expected behavior

- Help stops before any inspection and lists --push and a --remote that must be listed by git remote.
- Default run previews the converge plan and remote candidates without fetching or contacting the remote, and only predicts the push.

## Contract checks

- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `references/commands.md`
- PASS `SKILL.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
