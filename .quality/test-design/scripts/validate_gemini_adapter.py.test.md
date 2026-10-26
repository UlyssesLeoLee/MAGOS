# Test Design: `scripts/validate_gemini_adapter.py`

Source: `scripts/validate_gemini_adapter.py`

Source-SHA256: `8b750352b1a1acbcc72faac1b269f96a9ae77c883a4a3de4cebe9f3ed277052b`

## Test Strategy

Unit and command-line tests in `tests/codex/guard/test_gemini_adapter.py`. The module is loaded with `importlib` from `scripts/`. Every case but the first works on a temporary copy of the adapter files and of the source files they depend on (the repository's own files, a few dozen kilobytes), never on the repository itself, and changes one fact at a time. `main()` runs through `runpy` as `__main__` with a patched `sys.argv`, and `PASS` and `FAIL` lines are read from the captured streams. Cases that read TOML content run on Python 3.11 and later; the fallback is tested on every interpreter by setting `tomllib` to None on the loaded module.

## Test Cases

| Case ID | Input / Setup | Expected Outcome | Test Location |
| --- | --- | --- | --- |
| TC-001 | The repository as it is: `validate(repo)` and `validate(repo, overlay_only=True)` | Both return None and print one `PASS:` line each | tests/codex/guard/test_gemini_adapter.py::test_the_repository_passes |
| TC-002 | A copy whose `gemini-extension.json` has another `name`; another `contextFileName`; no `name` key; with `GEMINI.md` removed; with invalid JSON | AssertionError for the name, the context file name and the missing `GEMINI.md`; KeyError for the missing key; ValueError for the invalid JSON | tests/codex/guard/test_gemini_adapter.py::test_manifest_and_context_failures |
| TC-003 | Python 3.11 and later: the policy with a rule whose decision is `allow`; the policy without any rule; the policy removed | AssertionError for the first two, OSError for the third | tests/codex/guard/test_gemini_adapter.py::test_policy_failures |
| TC-004 | Python 3.11 and later: a command whose prompt lacks the Gemini arguments marker, `--help`, `activate_skill`, `--lang`, `SKILL.md`, `references/commands.md` or its own name (one case each); a command without `description` | AssertionError whose message names the missing marker or command | tests/codex/guard/test_gemini_adapter.py::test_command_prompt_failures |
| TC-005 | `commands/GitSweep.toml` removed; `commands/GitSweep.md` removed, with and without `overlay_only` | AssertionError naming the path; AssertionError "missing original Claude command GitSweep" without `overlay_only`, PASS with it | tests/codex/guard/test_gemini_adapter.py::test_missing_command_files_and_overlay_only |
| TC-006 | `SKILL.md`, `references/commands.md` or `skills/git-orchestrator/SKILL.md` removed; `plugin.json` with another name; `plugin.json` with another version than `gemini-extension.json` | AssertionError for each, naming the file or the version rule; PASS with `overlay_only` | tests/codex/guard/test_gemini_adapter.py::test_source_dependencies_and_the_version |
| TC-007 | `tomllib` set to None on the loaded module: the repository; a copy whose command prompt lacks the Gemini arguments marker; a copy without `commands/GitSweep.toml` | The repository and the first copy pass with a PASS line that says the TOML content was not checked; the missing file is still an AssertionError | tests/codex/guard/test_gemini_adapter.py::test_without_a_toml_reader |
| TC-008 | `main()` as `__main__`: no argument (the repository), `--repo <copy>`, `--overlay-only` on a copy without the original commands, a copy with a changed name, with invalid JSON and with `gemini-extension.json` removed | Exit status 0 and `PASS:` on stdout for the first three; `SystemExit(1)` and `FAIL: ` on stderr for AssertionError, ValueError and OSError | tests/codex/guard/test_gemini_adapter.py::test_main_exit_codes |

## Boundary & Failure Cases

- A TOML file that is present but not valid TOML is a ValueError and a `FAIL:` line (Python 3.11 and later).
- On Python 3.9 and 3.10 an absent policy or command file is still an error, because the file is read before the TOML reader is consulted.
- `--repo` accepts a relative path; the module resolves it.

## Regression Scope

`tests/codex/guard/test_package.py::test_sources_parse_as_python_3_9_and_tests_use_no_newer_api` (the import of `tomllib` is allowed only inside `if sys.version_info >= (3, 11)`), the coverage gate of `.quality/qguard.json` (every source file above 90 percent), and the package version agreement (`gemini-extension.json` follows `plugin.json`).
