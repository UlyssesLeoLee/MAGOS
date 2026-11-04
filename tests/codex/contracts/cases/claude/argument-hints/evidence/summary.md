# claude/argument-hints

- Skill: `claude-commands`
- Feature: Claude Code slash commands keep the frontmatter and inline help the / menu and --help depend on
- Result: **PASS**

## Expected behavior

- Each commands/Git*.md has a description and the exact argument-hint shown in the Claude Code / menu.
- Each command handles --help from its inline help before loading the skill.
- GitIntegrate, GitCleanup, GitConverge, GitSweep and GitPlan set disable-model-invocation: true so only the user can run them.

## Contract checks

- PASS `commands/GitRecon.md`
- PASS `commands/GitAnalyze.md`
- PASS `commands/GitRecommend.md`
- PASS `commands/GitIntegrate.md`
- PASS `commands/GitCleanup.md`
- PASS `commands/GitConverge.md`
- PASS `commands/GitSweep.md`
- PASS `commands/GitPlan.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
