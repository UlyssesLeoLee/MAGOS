# Test Design: `scripts/sync_hosts.py`

Source: `scripts/sync_hosts.py`

Source-SHA256: `77ee18e17694d491d0192dc540a4fbc4612b491e5554387370af41f2553fb51e`

## Test Strategy

All cases live in `tests/codex/guard/test_project_sources.py` and run in process with `pytest` as part of the guard
suite, so the coverage commands in `.quality/qguard.json` measure the real `scripts/sync_hosts.py` (line coverage
strictly above 90 percent for the file and for the project).

- The `pkg` fixture builds a miniature package in `tmp_path`: a copy of the script under `scripts/`, a root `SKILL.md`,
  `references/a.md` and `references/b.md`, the adapter `skills/git-recon/SKILL.md` with `agents/openai.yaml`, the
  plugin-only entry skill `skills/git-orchestrator/SKILL.md`, and one `commands/<name>.md` file for each of the eight
  entries of `COMMAND_PATHS` (the fixture derives them, so a Claude install of the fixture writes eight files). The
  module is loaded from the repository path and `main()` is pointed at the miniature package by patching the module's
  `__file__`. The cases that name the real command and adapter files read the repository itself (`ROOT`).
- `main()` runs with `sys.argv` patched and its output captured with `capsys`; JSON reports are parsed with `json`.
- Every home is a fresh directory under `tmp_path` passed with `--home`; `CODEX_HOME`, `HERMES_HOME` and
  `LOCALAPPDATA` are set or removed with `monkeypatch`, so no case reads or writes the real user home.
- Claude plugin states are built as files: a skills-directory clone (`.claude/skills/magos/.claude-plugin/plugin.json`),
  a plugin index (`.claude/plugins/installed_plugins.json` in the version 2 shape
  `{"version": 2, "plugins": {"<name>@<marketplace>": [{"scope": ..., "installPath": ..., "version": ...}]}}`) and a
  plugins cache manifest (`.claude/plugins/cache/<marketplace>/<plugin>/<version>/.claude-plugin/plugin.json`).
- Write failures are injected by replacing `copy_file` with a function that raises `OSError` or does nothing.
- The suite runs on Python 3.9 and 3.14 on Windows and Linux (CI matrix of `.github/workflows/test.yml`).

## Test Cases

| Case ID | Input / Setup | Expected Outcome | Test Location |
| --- | --- | --- | --- |
| TC-001 | `package_files(pkg)`; `file_sha256` of the root `SKILL.md` | Exactly `SKILL.md`, `references/a.md`, `references/b.md`, `skills/git-recon/SKILL.md`, `skills/git-recon/agents/openai.yaml` in that order (the entry skill is left out); the hash equals `hashlib.sha256` of the bytes | tests/codex/guard/test_project_sources.py::test_package_files_excludes_the_plugin_only_entry |
| TC-002 | `codex_install_root` with no install, with only the legacy `.codex/skills/MAGOS`, with both, and with `CODEX_HOME` set with and without an explicit home | Current root and no note; legacy root with the legacy note; current root with the duplicate note; the explicit home ignores `CODEX_HOME` | tests/codex/guard/test_project_sources.py::test_install_roots |
| TC-003 | `hermes_home` with `HERMES_HOME` set; with `LOCALAPPDATA`; with `active_profile` naming an existing profile; with `default`; with an explicit home | `HERMES_HOME`; `<LOCALAPPDATA>/hermes` on Windows and `<home>/.hermes` elsewhere (where `LOCALAPPDATA` is ignored); `<base>/profiles/work`; the base; `<home>/AppData/Local/hermes` on Windows or `<home>/.hermes` elsewhere | tests/codex/guard/test_project_sources.py::test_install_roots |
| TC-004 | `hermes_install_root` with only `multi-agent-git-orchestrator`, with it and `MAGOS`, with only `MAGOS` | The preferred root; the preferred root with "Keep one install"; the existing `MAGOS` root with its note | tests/codex/guard/test_project_sources.py::test_install_roots |
| TC-005 | `claude_plugin_notes` with skills clones named `magos`, `other`, and one with invalid JSON | One note, mentioning `/magos:GitXxx`; the other clones are ignored without an error | tests/codex/guard/test_project_sources.py::test_claude_plugin_notes |
| TC-006 | Codex and Hermes selected in an empty home: default run; `--apply --create-roots`; `--verify`; a drifted installed `SKILL.md` with `--verify --json`; `--apply`; a reference removed from the source | Exit 2 with "Preflight failed" and `missing-root`; exit 0 with "Created roots" and "Written: 10"; exit 0 and `matched`; exit 1 with `different` 1 and mode `verify`; exit 0 and the file restored; exit 0 | tests/codex/guard/test_project_sources.py::test_plan_verify_apply_cycle |
| TC-007 | `--host claude --apply` into an existing `.claude/commands`; then a skills clone named `magos` and a default run with explicit Codex and Hermes roots | Exit 0, "Written: 8", `GitRecon.md` installed; the default run reports "Skipping the claude host" | tests/codex/guard/test_project_sources.py::test_claude_host_and_plugin_skip |
| TC-008 | Codex root containing `.git` and `.claude-plugin/`; a directory where `SKILL.md` belongs; a source that is a directory | Exit 2 with `git-checkout` and the `$magos:git-*` reason; exit 2 with `blocked`; exit 2 with `SOURCE ERROR` naming `references/b.md` | tests/codex/guard/test_project_sources.py::test_git_checkout_roots_and_blocked_destinations |
| TC-009 | `copy_file` into a new subdirectory; with a wrong expected hash; to a destination outside the root | File written with the source bytes; RuntimeError "changed during sync"; RuntimeError "unsafe" | tests/codex/guard/test_project_sources.py::test_copy_file_guards |
| TC-010 | `--apply` whose second copy raises `OSError`; `--apply` with a copy that writes nothing; `--verify` after the source references are removed | Exit 2 with "Sync stopped after a write error"; exit 2 with "did not match after writing"; a report without a crash | tests/codex/guard/test_project_sources.py::test_apply_stops_on_a_write_error_and_reports_mismatches |
| TC-011 | `package_files` patched to list a file that does not exist | Exit 2 with `SOURCE ERROR` naming the file | tests/codex/guard/test_project_sources.py::test_missing_source_is_a_preflight_error |
| TC-012 | No skills clone; `installed_plugins.json` with `magos@magos` and one entry of scope `user`; `claude_plugin_notes` and a default run with explicit Codex and Hermes roots | One note naming `magos@magos` and `/magos:GitXxx`; the run reports "Skipping the claude host" and selects only `codex` and `hermes` | tests/codex/guard/test_project_sources.py::test_marketplace_user_scope_install_skips_claude |
| TC-013 | `installed_plugins.json` with `magos@magos` whose only entries have scope `project` or `local`; a default run | No note; `claude` is selected and its commands are inventoried | tests/codex/guard/test_project_sources.py::test_marketplace_project_scope_only_keeps_the_claude_commands |
| TC-014 | Index keys `magos@my-fork` (scope `user`), `magosx@magos` and `other@magos` | Only `magos@my-fork` is detected; the other keys give no note | tests/codex/guard/test_project_sources.py::test_a_magos_plugin_from_any_marketplace_counts |
| TC-015 | `installed_plugins.json` holding invalid JSON, a JSON list, a `plugins` value that is a list, and entries that are not lists or not objects; no plugins cache | No exception and no note in every case | tests/codex/guard/test_project_sources.py::test_a_malformed_plugin_index_is_ignored |
| TC-016 | No index and a cache manifest `cache/magos/magos/1.0.1/.claude-plugin/plugin.json` named `magos`; no index and a cache manifest named `other`; a valid index without any `magos` key beside the `magos` cache manifest | Detected with a note naming the cache manifest; no note; no note (the index decides when it parses) | tests/codex/guard/test_project_sources.py::test_the_plugins_cache_counts_only_without_a_plugin_index |
| TC-017 | A user-scope marketplace install and `--host claude --apply` into an existing `.claude/commands` | The note is printed and the eight command files are written ("Written: 8"), exit 0 | tests/codex/guard/test_project_sources.py::test_explicit_claude_host_copies_despite_a_marketplace_install |
| TC-018 | `COMMAND_NAMES`, `COMMAND_PATHS` and `package_files(ROOT)` of the real repository; the source text of `scripts/sync_hosts.py` | `COMMAND_NAMES` is exactly `GitRecon`, `GitAnalyze`, `GitRecommend`, `GitIntegrate`, `GitCleanup`, `GitConverge`, `GitSweep`, `GitPlan` in that order, so the text ends with the pinned tail `"GitConverge", "GitSweep", "GitPlan")`; `COMMAND_PATHS` holds eight paths, the last `commands/GitPlan.md`, and each is a regular file of the repository; for every name the adapter `skills/git-<word>/SKILL.md` (the lowercased text after `Git`) and its `skills/git-<word>/agents/openai.yaml` exist and are listed by `package_files(ROOT)`, which lists no file of `skills/git-orchestrator` | tests/codex/guard/test_project_sources.py::test_eight_commands_and_their_adapters_are_listed |
| TC-019 | `--host claude --apply` into an existing `.claude/commands`, then the installed `GitPlan.md` removed (the home of an install that predates the eighth command); `--verify --json`; `--apply`; `--verify` | Exit 0 with "Written: 8"; exit 1 with `missing` 1 and `matched` 7 in the summary, the one missing file being the `GitPlan.md` entry; exit 0 with "Written: 1" (only the missing file is copied); exit 0 with every file `matched` | tests/codex/guard/test_project_sources.py::test_a_home_without_the_eighth_command_reports_it_missing_and_apply_adds_it |

## Boundary & Failure Cases

- Package list: an empty `references/` directory, an adapter without `agents/openai.yaml`, the plugin-only entry skill
  (never listed), a source that is a symlink or a directory (source error, nothing written), the real `git-plan`
  adapter with its `agents/openai.yaml` (listed by the `skills/*/SKILL.md` glob without a code change).
- Command list: a Claude home that holds only the seven earlier command files (`GitPlan.md` is `missing`, `--verify`
  exits 1, `--apply` writes exactly one file and deletes nothing), a command name without its file in the repository
  (a source error, nothing written).
- Destinations: a destination that is a directory or a symlink, a destination whose parent is a link or junction that
  resolves outside the root (blocked before any write and re-checked inside `copy_file`), a source whose bytes change
  between the inventory and the copy (the copy stops).
- Roots: `--create-roots` while another host is a git checkout or a file is blocked (no root is created and nothing is
  written), `--create-roots` without `--apply` (no effect), an explicit `--codex-root` or `--hermes-root` (no root
  note).
- Environment: `CODEX_HOME` and `HERMES_HOME` set to whitespace or empty, `LOCALAPPDATA` empty, an `active_profile` that
  names a missing profile or `default`, every variable ignored with `--home`.
- Plugin detection: an index entry list that mixes `project` and `user` scopes (detected), a key without `@` (its whole
  text is the plugin part), an index without a `plugins` key (the cache decides), an unreadable cache manifest
  (ignored), several detected installs (one note each).
- Usage: `--verify` together with `--apply` and an unknown `--host` value are argparse usage errors (exit 2).

## Regression Scope

The package list is shared: `tests/codex/run_host_cases.py` provisions its host fixtures with `package_files()` and finds
the Hermes configuration with `hermes_home()`, and `tests/codex/contracts/install_layout.py` checks the containment
rules of the same list (nine skills in an installed package: the root `multi-agent-git-orchestrator` and the eight
adapters, with the plugin-only `git-orchestrator` added in a git checkout), so `package_files()`,
`codex_install_root()`, `hermes_home()` and `hermes_install_root()` keep their results and the host fixtures gain the
`git-plan` adapter. The Claude source-contract case `git-converge/package-wiring` (`tests/claude/contracts/cases.json`,
run by `tests/claude/scripts/run_claude_contracts.py --check`) pins the tail `"GitConverge", "GitSweep", "GitPlan")` of
`COMMAND_NAMES`; `tests/codex/guard/test_package.py` pins that the package list carries `references/lane-split.md` and
neither the guard nor the hooks. The install commands in `README.md`, `README.en.md` and `references/installation.md`
keep their options and exit codes. The lane guard stays outside the package (`scripts/magos_guard.py install` ships it),
and `references/lane-split.md` reaches Codex and Hermes through the `references/*.md` glob. A home without a detected
MAGOS plugin keeps receiving the Claude commands from a default run.
