# Codex skill tests

All test cases for this repository are collected here. Runtime tests invoke the installed Codex CLI against disposable Git repositories in the system temporary directory (`--fixture-root` names another directory); the fixtures are removed after each case. Integration and cleanup never run against this repository.

For each runtime case, the runner installs the host-neutral MAGOS package from the active test checkout into the fixture's project-local `.agents/skills/MAGOS/` root, using the same file list as `scripts/sync_hosts.py` (`package_files()`): `SKILL.md`, every `references/*.md`, and every `skills/git-*/` adapter. The adapters therefore resolve `../../SKILL.md` exactly as in a real install. The runner records the copied-source hash and leaves the user's `.codex/develop_codex` worktree untouched. The fixture check also verifies that the adapter's shared files resolve. Use `--fixture-root <short path>` if Windows reports `Filename too long`. Codex deduplicates skills by path, not by name, so a user-level install (`~/.agents/skills/MAGOS` or `$CODEX_HOME/skills/MAGOS`) stays visible next to the fixture copy; the runner records such installs in `invocation.json` and reports the case as `UNVERIFIED` unless `--allow-user-install` is given.

Run the source-contract checks:

```powershell
python -X utf8 tests/codex/contracts/run_contract_cases.py --check
python -X utf8 tests/claude/scripts/run_claude_contracts.py --check
```

These checks verify that Codex skill metadata, inline help, command contracts, and safety rules remain present; the second runner covers the GitConverge, GitSweep and GitPlan cases in `tests/claude/contracts/cases.json` with the same engine. `--check` runs every case, writes nothing, and exits 1 on any FAIL. Without `--check` each runner also records the case and its evidence under `tests/codex/contracts/cases/` or `tests/claude/results/contracts/`. A snippet that names the package version is written as `{plugin.yaml version}` and is compared with the version `plugin.yaml` states. Their result is labelled `source-contract`; it does not count as a runtime behavior pass.

`package/agent-plugin` checks the repository as an Agent Plugins 1.0.0 package (`contracts/agent_plugin.py`): the root `plugin.json` against the closed manifest schema, version agreement, plugin discovery of exactly the eight command adapters plus `git-orchestrator`, Agent Skills frontmatter rules, and path containment. Frontmatter is read by `contracts/skill_frontmatter.py`, a strict YAML-subset reader that rejects what PyYAML or strictyaml (used by skills-ref) would read differently; `package/install-layout` uses it too and also replays the Codex and Hermes discovery rules over the files a commit would ship (tracked, plus untracked files git does not ignore), as a git clone into a skills directory would see them. `contracts/test_agent_plugin.py` plants one defect at a time in temporary copies (including temporary git work trees, to cover untracked files) and asserts that each turns its check red; it also unit-tests the strict reader:

```powershell
python -X utf8 tests/codex/contracts/test_agent_plugin.py
```

Run the lane guard suite, and the coverage gate of the CI coverage job:

```powershell
python -m pytest tests/codex/guard -q -p no:cacheprovider
python -X utf8 tests/codex/coverage_gate.py
```

`coverage_gate.py` runs the `coverage_commands` of `.quality/qguard.json` exactly as written and exits 1 unless every source file the quality hook counts (tracked code outside `tests/` and the tool directories) and the project as a whole have line coverage strictly above `min_coverage_exclusive` (90); `--report-only` judges the report that is already there. Guard tests that need a POSIX `sh` skip where none is on PATH, and no test depends on the name of the temporary directory.

Validate that the temporary Git fixtures are constructed correctly without using Codex:

```powershell
python -X utf8 tests/codex/run_host_cases.py --fixture-check
```

Run actual Codex behavior cases:

```powershell
python -X utf8 tests/codex/run_host_cases.py
```

The runner calls `$git-*` skills through `codex exec`, records the prompt, CLI transcript, and Git state before and after each invocation, then checks observable output and repository changes. Every case writes evidence under `tests/codex/host_cases/<skill>/<case>/evidence/host-codex/`. Results are `PASS`, `FAIL`, or `UNVERIFIED`; missing CLI access, authentication, quota, sandbox, or timeouts are never reported as passes. Use `--case 'git-integrate/*'` to select cases and `--codex-sandbox workspace-write` to set the child CLI's sandbox. Integration and cleanup write tests only use their disposable fixture.

Hermes cases use the same runner and fixtures:

```powershell
python -X utf8 tests/codex/run_host_cases.py --host hermes --fixture-check
python -X utf8 tests/codex/run_host_cases.py --host hermes --case 'git-integrate/*'
```

The runner installs the package as project-local skills (`.agents/skills/MAGOS/`), runs `hermes skills trust` for the fixture, and removes the trust afterwards with `hermes skills untrust`. It then restores the original `config.yaml` bytes if the parsed config is otherwise unchanged; `hermes_trust.json` records the result. Until then the original bytes are kept in `config.yaml.magos-backup` beside `config.yaml` in the Hermes home, never in this repository, and the next run restores them after an interrupted one. `--fixture-check` runs `hermes_probe.py` with Hermes's own Python and never calls a model. The probe verifies three things: every slash command resolves to the fixture copy, `skills_guard` does not report "dangerous", and the rendered slash message carries the skill directory and the arguments. The runner finds Hermes's Python read-only: it asks Hermes for its launcher interpreter with `hermes --print-runtime-command`, then has that interpreter print `pm.environments.project_python` for the install directory reported by `hermes --version` (this covers installs whose dependency environment lives under `<hermes home>/installs/<id>/environments/`). If Hermes cannot answer, it falls back to `<install directory>/venv/Scripts/python.exe` or `venv/bin/python`; with neither, every case is `UNVERIFIED`. Runtime cases send that rendered message through `hermes -z`, because one-shot mode does not expand slash commands. Help cases stay `UNVERIFIED`: one-shot output has no tool trace, so "no repository inspection" cannot be checked. Evidence goes to `evidence/fixture-check-hermes/` and `evidence/host-hermes/`.

Note: the committed `host-codex` evidence comes from fixtures that held only `skills/<x>` and `references/`, without `../../SKILL.md`; it does not count as a runtime pass, and a new run of the Codex cases replaces it.

The case manifest covers every command (GitConverge only through `git-converge/help`, GitSweep only through `git-sweep/help`, GitPlan only through `git-plan/help`; their source-contract cases are in `tests/claude/contracts/cases.json`, and none has runtime behavior cases), required and optional arguments, branch and worktree targets, all integration strategies, acceptance gates, cleanup preview/apply, and stale-state rechecks. Codex CLI tests verify skill selection and behavior; they do not measure the gray hint rendering in the desktop composer.
