# hermes/argument-passing

- Skill: `hermes-adapters`
- Feature: Adapters explain how Hermes passes arguments and how to read shared files without '..' skill-viewer paths
- Result: **PASS**

## Expected behavior

- Each adapter takes Hermes arguments from the 'User instruction:' block.
- Each adapter resolves shared files from the '[Skill directory: ...]' path or the root skill multi-agent-git-orchestrator.

## Contract checks

- PASS `skills/git-recon/SKILL.md`
- PASS `skills/git-analyze/SKILL.md`
- PASS `skills/git-recommend/SKILL.md`
- PASS `skills/git-integrate/SKILL.md`
- PASS `skills/git-cleanup/SKILL.md`
- PASS `skills/git-converge/SKILL.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-plan/SKILL.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
