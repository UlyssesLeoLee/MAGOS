# git-protect/package-wiring

- Skill: `git-protect`
- Feature: The ninth command is wired into the sync script, the Hermes index, the adapters, the Gemini command, the install guide and the three READMEs
- Result: **PASS**

## Expected behavior

- COMMAND_NAMES ends with GitSweep, GitPlan, GitProtect, so sync_hosts.py installs commands/GitProtect.md for Claude, and the Codex and Hermes packages carry skills/git-protect with its openai.yaml.
- The Hermes plugin index describes git-protect as a command that sets or lifts a branch protection and must never be loaded by the model.
- The Gemini adapter lists GitProtect and its TOML command activates git-orchestrator.
- Docs list /GitProtect, /git-protect and $git-protect and say nine commands.

## Contract checks

- PASS `scripts/sync_hosts.py`
- PASS `scripts/validate_gemini_adapter.py`
- PASS `__init__.py`
- PASS `commands/GitProtect.md`
- PASS `commands/GitProtect.toml`
- PASS `skills/git-protect/SKILL.md`
- PASS `skills/git-protect/agents/openai.yaml`
- PASS `references/installation.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
