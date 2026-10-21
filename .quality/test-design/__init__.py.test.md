# Test Design: `__init__.py`

Source: `__init__.py`

Source-SHA256: `a386beedea7f62fabc618073ce87e14de53d95bfef8ccb6681c41ef571bd9b07`

## Test Strategy

The in-process cases live in `tests/codex/guard/test_project_sources.py` and run with `pytest` as part of the guard
suite, so the coverage commands in `.quality/qguard.json` measure the real `__init__.py` (line coverage strictly above 90
percent for the file and for the project). The contract rows live in `tests/codex/contracts/` and run with
`python -X utf8 tests/codex/contracts/test_agent_plugin.py`; they read the module as text and syntax tree.

- The module is loaded from the repository path with `importlib.util.spec_from_file_location` under the name
  `magos_plugin_init`; `register()` runs against a recording context whose `register_skill(name, path, description="")`
  appends `(name, Path(path).name, description)` to a list.
- The cases on the real tree read the repository's `skills/` directory and the `SKILL.md` of every adapter, so they
  follow the shipped files. The cases on a synthetic tree build `skills/` in `tmp_path` and point the loaded module at it
  with `monkeypatch.setattr(mod, "__file__", <tmp_path>/__init__.py)`, because `register()` resolves `skills/` from the
  module's `__file__` at call time; the code that runs is still the real file.
- The write commands are derived, not listed in the helper that checks them: a skill is a write command when its
  `SKILL.md` contains the line `## Explicit invocation only`; the expected set is then asserted against the five
  names, so an adapter that loses the section turns the case red.
- No case needs Hermes, a network or a git repository.
- The suite runs on Python 3.9 and 3.14 on Windows and Linux (CI matrix of `.github/workflows/test.yml`).

## Test Cases

| Case ID | Input / Setup | Expected Outcome | Test Location |
| --- | --- | --- | --- |
| TC-001 | `register(ctx)` on the real repository with the recording context | The registered names equal the sorted names of the `skills/` children that hold a `SKILL.md`; every call passes a path whose file name is `SKILL.md` and a non-empty description; the keys of `INDEX_DESCRIPTIONS` equal the registered names | tests/codex/guard/test_project_sources.py::test_init_registers_every_skill_with_a_description |
| TC-002 | `register(ctx)` on the real repository | Exactly nine skills in sorted order: `git-analyze`, `git-cleanup`, `git-converge`, `git-integrate`, `git-orchestrator`, `git-plan`, `git-recommend`, `git-recon`, `git-sweep` (the entry skill and eight command adapters); the `skills/` directory holds no other skill | tests/codex/guard/test_project_sources.py::test_init_registers_the_entry_skill_and_the_eight_command_adapters |
| TC-003 | The source text of `__init__.py` parsed with `ast`; the top-level `INDEX_DESCRIPTIONS` assignment read with `ast.literal_eval` | The literal equals the loaded module's table; its keys are, in order, `git-orchestrator`, `git-recon`, `git-analyze`, `git-recommend`, `git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, `git-plan`; every value is a non-blank string without a line break | tests/codex/guard/test_project_sources.py::test_the_index_table_is_a_literal_in_the_contract_order |
| TC-004 | The write commands derived from the `## Explicit invocation only` section of each adapter; the table lines of every skill | The derived set is exactly `git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, `git-plan`; each of their lines contains `run only when the user types /magos:<name>.` and ends with `Never load it yourself.`; each line of `git-recon`, `git-analyze`, `git-recommend` starts with `Read-only`, contains `when the user asks` and does not contain `Never load it yourself` | tests/codex/guard/test_project_sources.py::test_every_write_command_index_line_says_never_load_it_yourself |
| TC-005 | The `git-plan` line of the loaded table | It equals `Registers lane claims and, with --converge --apply, merges the lanes: run only when the user types /magos:git-plan. Never load it yourself.` and has at most 160 characters | tests/codex/guard/test_project_sources.py::test_the_git_plan_index_line_names_its_writes |
| TC-006 | Every line of the loaded table, scanned for the text `/<plugin>:<command>` | Each such text in a line equals `/magos:<the line's own skill name>`; the `git-orchestrator` line has 100 to 400 characters; every other line has at most 160 characters | tests/codex/guard/test_project_sources.py::test_index_lines_name_only_their_own_command_and_keep_their_length |
| TC-007 | A synthetic `skills/` with `a/SKILL.md`, `z/SKILL.md`, a directory `b/` without `SKILL.md`, a directory `c/` whose `SKILL.md` is a directory, and a plain file `notes.txt` | `register()` records `a` then `z` with the path of their `SKILL.md` and the empty description (neither name is in the table); `b`, `c` and `notes.txt` are skipped without an error | tests/codex/guard/test_project_sources.py::test_register_skips_non_skills_and_defaults_the_description |
| TC-008 | A synthetic tree without any `skills/` directory next to the module | `register()` raises `FileNotFoundError` and the context records no call | tests/codex/guard/test_project_sources.py::test_register_without_a_skills_directory_raises |
| TC-009 | A synthetic `skills/` with `a/SKILL.md` and `z/SKILL.md` and a context whose `register_skill` raises `RuntimeError` on its second call | The `RuntimeError` reaches the caller; only the first skill was recorded; nothing is rolled back and nothing else is registered | tests/codex/guard/test_project_sources.py::test_register_propagates_a_failing_context |
| TC-010 | The syntax tree of `__init__.py` under the supply-chain rules | No network or process module, no dynamic import, no `exec`, `eval` or `compile`, `os`, `subprocess` and `ctypes` unused | tests/codex/guard/test_supply_chain.py::test_the_hook_code_opens_no_network_connection |
| TC-011 | The package copy of the contract tests, unmodified | Every Hermes native row passes: `plugin.yaml` name and version equal `plugin.json`, no `provides_` or capability key, only `ctx.register_skill`, an `INDEX_DESCRIPTIONS` line for each of the nine skills and none for a non-skill, the line passed as `description=`, the orchestrator line 100 to 400 characters, `Never load it yourself` in the line of each write adapter, no line naming another command | tests/codex/contracts/test_agent_plugin.py::AgentPluginChecks::test_unmodified_package_passes |
| TC-012 | The mutations of `__init__.py`: a `ctx.register_tool` call; the `git-recon` line removed; the `git-integrate` line ending with `Load it when useful.`; the `description=` argument dropped, also with a comment that keeps its text; an entry that is not a string; the `git-analyze` line naming `/magos:git-recon` | The row `plugin.yaml is the Hermes native manifest` turns red for every mutation; the anchors stay valid because the earlier lines keep their text and order and `git-plan` is the last entry | tests/codex/contracts/test_agent_plugin.py::AgentPluginChecks::test_each_mutation_turns_its_row_red |
| TC-013 | The shipped `.py` files, parsed with the 3.9 grammar | `__init__.py` parses on Python 3.9 and uses no newer API | tests/codex/guard/test_package.py::test_sources_parse_as_python_3_9_and_tests_use_no_newer_api |
| TC-014 | The coverage gate's tracked source list and the CI job of the quality commands | `__init__.py` is a tracked source gated strictly above 90 percent, per file and for the project | tests/codex/guard/test_package.py::test_ci_coverage_job_runs_the_qguard_commands |
| TC-015 | The contract case `package/install-layout`: the package installed into a scratch home, and the checkout rows | The row `install:plugin.yaml is the Hermes native manifest of plugin.json, and __init__.py registers skills/` passes and the replicas find ten skills in a checkout (the root skill, the entry skill and the eight adapters) and nine in an installed package | tests/codex/contracts/run_contract_cases.py |

## Boundary & Failure Cases

- Children of `skills/`: a plain file, a directory without `SKILL.md`, a `SKILL.md` that is a directory (all skipped), a
  skill added without an `INDEX_DESCRIPTIONS` entry (registered with the empty description at run time, a red
  contract row at test time), an entry for a name that is not a skill (red contract row, no effect at run time).
- Missing or unreadable `skills/`: the exception reaches Hermes, no skill is registered.
- Context: a `register_skill` that raises stops the registration at that skill; a context without `register_skill`
  raises `AttributeError` before anything is recorded.
- Table text: a write command line without `Never load it yourself.`, a line that names another command, an
  orchestrator line of 99 or 401 characters, a line with a line break, a value that is not a string (each a red
  contract row, none can pass the in-process cases).
- Ordering: `sorted()` over the lowercase directory names gives one order on every platform; the table order does not
  affect registration.

## Regression Scope

`skills/git-plan/SKILL.md` must exist with the section `## Explicit invocation only`, otherwise TC-004 and TC-011 turn
red, and its `agents/openai.yaml` and the command file `commands/GitPlan.md` belong to the same command set that
`scripts/sync_hosts.py` lists. `tests/codex/contracts/install_layout.py` (`EXPECTED_SKILLS` and `CHECKOUT_SKILLS`) lists `git-plan`, so the
installed package holds nine skills and a checkout ten; the contract cases `package/install-layout` and
`package/agent-plugin` (with their evidence under `tests/codex/contracts/cases/package/`) follow that list,
`plugin.yaml` keeps the name and version of `plugin.json`, and the eight earlier lines of `INDEX_DESCRIPTIONS` keep their text and order, which the mutation anchors
of `tests/codex/contracts/test_agent_plugin.py` rely on. The Hermes probe and host cases
(`tests/codex/hermes_probe.py`, `tests/codex/run_host_cases.py`) resolve `/git-plan` through the skill package, not
through this module, and are unaffected. The module remains outside the Codex and Hermes skill packages
(`scripts/sync_hosts.py`) and outside the Claude Code plugin.
