# codex/argument-discovery

- Skill: `all`
- Feature: Codex exposes all eight skills with compact usage hints
- Result: **PASS**

## Expected behavior

- All eight skill directories have Codex-recognized names and invocation syntax.
- Each openai.yaml short description includes its $skill selector and --help.

## Contract checks

- PASS `skills/git-recon/SKILL.md`
- PASS `skills/git-recon/agents/openai.yaml`
- PASS `skills/git-analyze/SKILL.md`
- PASS `skills/git-analyze/agents/openai.yaml`
- PASS `skills/git-recommend/SKILL.md`
- PASS `skills/git-recommend/agents/openai.yaml`
- PASS `skills/git-integrate/SKILL.md`
- PASS `skills/git-integrate/agents/openai.yaml`
- PASS `skills/git-cleanup/SKILL.md`
- PASS `skills/git-cleanup/agents/openai.yaml`
- PASS `skills/git-converge/SKILL.md`
- PASS `skills/git-converge/agents/openai.yaml`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-sweep/agents/openai.yaml`
- PASS `skills/git-plan/SKILL.md`
- PASS `skills/git-plan/agents/openai.yaml`

Evidence scope: source-contract check; no AI host CLI is invoked.
