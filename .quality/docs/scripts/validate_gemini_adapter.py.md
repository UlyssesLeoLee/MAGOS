# Technical Design: `scripts/validate_gemini_adapter.py`

Source: `scripts/validate_gemini_adapter.py`

Source-SHA256: `c3f646f8cee71cdebc0a15ea64425163befdcc81d6ff91f5f43475fb318e720a`

## Responsibility

An offline consistency check of the Gemini CLI adapter of MAGOS against the repository that carries it. It reads files only (standard library, no network, no process) and answers PASS or FAIL.

The adapter consists of the extension manifest `gemini-extension.json`, the context file `GEMINI.md`, the policy `policies/magos-git-confirm.toml` and one TOML custom command for each of the eight MAGOS commands, `commands/<Name>.toml` for GitRecon, GitAnalyze, GitRecommend, GitIntegrate, GitCleanup, GitConverge, GitSweep and GitPlan.

## Dependencies

- Standard library only: `argparse`, `json`, `sys`, `pathlib`, and `tomllib` (Python 3.11 and later).
- Python 3.9 and 3.10 have no TOML reader in the standard library. There the module sets `tomllib` to None, so that it imports on every interpreter the package supports (3.9 and later); the TOML files are then read (so a missing file is still an error) but their content is not checked, and the PASS line says so.
- Upstream: the adapter files named above; unless `--overlay-only` is given, also the original Claude commands `commands/<Name>.md`, `SKILL.md`, `references/commands.md`, `skills/git-orchestrator/SKILL.md` and `plugin.json`.
- Downstream: the owner runs it before publishing the adapter; `tests/codex/guard/test_gemini_adapter.py` runs it on copies of the repository files.

## Public Contract

- `validate(base, overlay_only=False)` returns None when every check holds and prints one `PASS:` line. A failed check raises AssertionError with the message of the check, a missing manifest key raises KeyError, invalid JSON or TOML raises ValueError, an unreadable or missing file raises OSError.
- The checks, in order:
  1. `gemini-extension.json` has the name `magos` and the `contextFileName` `GEMINI.md`, and `GEMINI.md` exists.
  2. The policy file has at least one `rule`, and every rule has the decision `ask_user` (TOML content: Python 3.11 and later).
  3. For each of the eight names, `commands/<Name>.toml` exists and, on Python 3.11 and later, has a non-empty `description` and a `prompt` that holds the Gemini arguments marker, `--help`, `activate_skill`, `--lang`, `SKILL.md`, `references/commands.md` and the command name.
  4. Unless `overlay_only`: the original `commands/<Name>.md` exists for each name; `SKILL.md`, `references/commands.md` and `skills/git-orchestrator/SKILL.md` exist; `plugin.json` has the name `magos` and a `version` equal to the `version` of `gemini-extension.json`.
- `main()` takes `--repo PATH` (default: the parent of the `scripts` directory) and `--overlay-only`. It exits with status 0 after PASS. On AssertionError, KeyError, ValueError or OSError it writes `FAIL: <message>` to stderr and exits with status 1.
- Invariant: nothing is written, no process is started, no network is used.

## Change Notes

The TOML reader is optional below Python 3.11, so that the module imports and runs under the supported minimum, 3.9, where it checks everything but the TOML content; on 3.11 and later its behaviour is unchanged. The `version` of `gemini-extension.json` equals the package version.
