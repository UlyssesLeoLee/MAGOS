# git-plan/package-wiring

- Skill: `git-plan`
- Feature: The eighth command is wired into the sync script, the Hermes index, the adapters, the install guide, the three READMEs, the changelog, the release notes and the pressure tests
- Result: **PASS**

## Expected behavior

- sync_hosts.py installs commands/GitPlan.md for Claude (the tail of COMMAND_NAMES is GitSweep, GitPlan) and the Codex and Hermes packages carry skills/git-plan with its openai.yaml.
- The Hermes plugin index describes git-plan as a command that registers lane claims and merges the lanes and must never be loaded by the model.
- The Claude Code adapter and the Hermes skill set disable-model-invocation: true, the Codex adapter sets allow_implicit_invocation: false, and the adapters read ../../references/commands.md sections 8 and 6 and never commands/*.md.
- Docs list /GitPlan, /git-plan and $git-plan, say eight commands and eight Agent Skills (five of them write adapters), and pin examples name v1.0.4.
- The three READMEs describe /GitPlan, the changelog has a 1.0.4 section and the release notes of 1.0.4 exist; the pressure tests describe the GitPlan scenarios.
- An older guard copy lacks the set-* subcommands: the install and upgrade notes say to refresh the guard copy with doctor and install.

## Contract checks

- PASS `scripts/sync_hosts.py`
- PASS `__init__.py`
- PASS `commands/GitPlan.md`
- PASS `skills/git-plan/SKILL.md`
- PASS `skills/git-plan/agents/openai.yaml`
- PASS `SKILL.md`
- PASS `plugin.yaml`
- PASS `plugin.json`
- PASS `.claude-plugin/plugin.json`
- PASS `references/commands.md`
- PASS `references/installation.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`
- PASS `CHANGELOG.md`
- PASS `RELEASE_NOTES_1.0.4.md`
- PASS `references/pressure-tests.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
