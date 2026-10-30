# git-protect/hard-stops

- Skill: `git-protect`
- Feature: /GitProtect writes no branch, and only the user sets or lifts a protection
- Result: **PASS**

## Expected behavior

- The command never commits, merges, creates, switches, deletes or pushes a branch.
- protect is a user-only guard subcommand: the agent runs it as one direct invocation so the host asks the user, in Codex through magos_approve with subcommand protect, never passes --approval, and prints the command for the user's terminal when there is no prompt.
- The agent never lifts a protection on its own to make a refused write pass, never writes .git/magos or magos.* config, and never retries a refused or declined protect in another form.
- The user-only lists of SKILL.md and references/lane-split.md name protect, and lane-split.md section 15 states what a protection refuses and allows.

## Contract checks

- PASS `commands/GitProtect.md`
- PASS `skills/git-protect/SKILL.md`
- PASS `skills/git-protect/agents/openai.yaml`
- PASS `references/commands.md`
- PASS `SKILL.md`
- PASS `references/lane-split.md`
- PASS `references/pressure-tests.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
