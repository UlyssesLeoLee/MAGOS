# git-sweep/preview-and-help

- Skill: `git-sweep`
- Feature: Preview and help neither write nor contact the network
- Result: **PASS**

## Expected behavior

- Help stops before any inspection.
- Default run previews the converge plan and remote candidates without fetching or contacting the remote.

## Contract checks

- PASS `commands/GitSweep.md`
- PASS `references/commands.md`
- PASS `SKILL.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
