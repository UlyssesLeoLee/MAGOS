# hermes/descriptions

- Skill: `hermes-adapters`
- Feature: Hermes slash-command descriptions stay within the width Hermes shows without truncation
- Result: **PASS**

## Expected behavior

- Each adapter description is a single quoted line of at most 77 characters ending with a period.
- The write adapters define what counts as an explicit invocation on each host.

## Contract checks

- PASS `skills/git-recon/SKILL.md`
- PASS `skills/git-analyze/SKILL.md`
- PASS `skills/git-recommend/SKILL.md`
- PASS `skills/git-integrate/SKILL.md`
- PASS `skills/git-cleanup/SKILL.md`
- PASS `skills/git-converge/SKILL.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-plan/SKILL.md`
- PASS `skills/git-integrate/SKILL.md`
- PASS `skills/git-cleanup/SKILL.md`
- PASS `skills/git-converge/SKILL.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `skills/git-plan/SKILL.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
