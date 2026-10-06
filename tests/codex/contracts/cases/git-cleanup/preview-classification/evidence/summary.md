# git-cleanup/preview-classification

- Skill: `git-cleanup`
- Feature: Preview classifies safe and blocked candidates without changes
- Result: **PASS**

## Expected behavior

- Shows evidence for each candidate and its block reason.
- Leaves all refs and worktrees unchanged in preview mode.
- Never lists main, the integration target, or the invoking worktree as a candidate; blocks worktrees that are dirty (untracked files included), in progress, or hold ignored files.

## Contract checks

- PASS `references/commands.md`
- PASS `skills/git-cleanup/SKILL.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
