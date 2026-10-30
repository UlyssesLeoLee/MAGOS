# claude/skill-lookup

- Skill: `claude-commands`
- Feature: Claude Code commands find the orchestrator under any installed name and never write without the loaded skill
- Result: **PASS**

## Expected behavior

- Each command accepts magos, MAGOS, multi-agent-git-orchestrator, or MAGO-Skill as the orchestrator skill.
- GitIntegrate does not integrate, and GitCleanup, GitConverge, GitSweep and GitPlan only preview when the skill cannot be loaded.

## Contract checks

- PASS `commands/GitRecon.md`
- PASS `commands/GitAnalyze.md`
- PASS `commands/GitRecommend.md`
- PASS `commands/GitIntegrate.md`
- PASS `commands/GitCleanup.md`
- PASS `commands/GitConverge.md`
- PASS `commands/GitSweep.md`
- PASS `commands/GitPlan.md`
- PASS `commands/GitIntegrate.md`
- PASS `commands/GitCleanup.md`
- PASS `commands/GitConverge.md`
- PASS `commands/GitSweep.md`
- PASS `commands/GitPlan.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
