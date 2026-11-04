# MAGOS — Gemini CLI integration (overlay for the existing repo)

## Scope and source

The files in this ZIP are NEW Gemini-specific files to merge into
https://github.com/UlyssesLeoLee/MAGOS, based on the upstream v1.0.5
`plugin.json`, `plugin.yaml`, `skills/git-orchestrator/SKILL.md` and the eight
existing `commands/Git*.md` command definitions as reviewed on 2026-10-23.
The purpose is to **reuse** the original MAGOS implementation/contracts,
not fork or replace them. No existing Claude/Codex/Hermes file is modified.

## Files to copy

- `gemini-extension.json`: official Gemini extension manifest.
- `GEMINI.md`: short always-on Gemini host guidance and safety defaults.
- `commands/GitRecon.toml` ... `commands/GitPlan.toml`: eight custom slash
  command adapters. The existing `commands/Git*.md` remain untouched and
  continue serving Claude Code.
- `policies/magos-git-confirm.toml`: additive confirmation rules for selected
  risky shell Git commands (defense in depth, not a guard replacement).
- `scripts/validate_gemini_adapter.py`: stdlib offline structural QA for the
  merged repository, with optional standalone overlay mode.

## Local integration (Windows PowerShell)

```powershell
# (1) Back up changes, and unzip the contents into E:\MAGOS (not into an extra level)
cd E:\MAGOS
python scripts\validate_gemini_adapter.py --repo .

# (2) Requires installed Gemini CLI
# npm.cmd install -g @google/gemini-cli@latest
# npm.cmd list -g @google/gemini-cli --depth=0

gemini extensions validate .
gemini extensions link E:\MAGOS
# Restart Gemini CLI, and in the Gemini interactive console:
# /commands list
# /skills list
# /GitRecon --help
# /GitRecon
# /GitPlan sample-set --into develop (preview only)
```

When `/Git*` commands collide with user/project slash commands, Gemini may
prefix the extension name. Check `/commands list` for the actual spelling.
After local testing, commit the new files on the release branch and publish
via GitHub. Set the GitHub repository topic `gemini-cli-extension`; the gallery
indexes public extension repositories periodically.

## How this maps to existing MAGOS commands

| Gemini command | Original file | Write behavior |
|---|---|---|
| `/GitRecon` | `commands/GitRecon.md` | Read only; `--remote` opt-in fetch |
| `/GitAnalyze` | `commands/GitAnalyze.md` | Read only; `--remote` opt-in fetch |
| `/GitRecommend` | `commands/GitRecommend.md` | Read only; `--remote` opt-in fetch |
| `/GitIntegrate` | `commands/GitIntegrate.md` | Explicit user intent, protected integration gates |
| `/GitCleanup` | `commands/GitCleanup.md` | Preview; `--apply` writes |
| `/GitConverge` | `commands/GitConverge.md` | Preview; `--apply` writes |
| `/GitSweep` | `commands/GitSweep.md` | Preview; `--apply` changes local and safe remote branches; `--push` separately required for publishing |
| `/GitPlan` | `commands/GitPlan.md` | Preview for planning/convergence; `--apply` / `--release` write |

## Safety notes / known limitations

1. **No native Gemini guard equivalence yet.** The source Claude `hooks/hooks.json`
   has `PreToolUse` and a Claude-specific payload. Gemini uses `BeforeTool` and
   a different JSON protocol. Overwriting the shared hook file could break
   Claude; intentionally not done. Gemini CLI may discover that same legacy
   `hooks/hooks.json` when validating an extension. Whether it ignores the
   unsupported Claude `PreToolUse` event depends on its installed version;
   verify with `gemini extensions validate .` and inspect any warnings. If
   validation fails due to the shared hook file, do not delete or overwrite
   the Claude hook in your primary branch merely to pass Gemini validation;
   isolate the Gemini distribution into its own branch/build until the
   cross-host hook mapping has been tested. To obtain full parity, separately implement
   a tested Gemini `BeforeTool` adapter mapping Gemini's `tool_input` and the
   MAGOS guard protocol. The provided `policies/` rule covers selected risk
   patterns only. It is not a security boundary, and a shell can express Git
   modifications in many other forms.
2. Command adapters preserve the public names and argument contracts and
   delegate detailed validations to the **existing** `SKILL.md` and
   `references/commands.md`; they do not recreate the Git algorithm.
3. Gemini custom-command `{{args}}` is provided to the model as command text.
   Do not add eager `!{...}` shell execution to a custom command; it could
   violate `--help`'s no-tool requirement.
4. Agent Skills in `skills/` are already included in the upstream repo;
   this overlay does not duplicate, patch, or remove them. Validate actual
   `activate_skill` availability in your installed Gemini CLI.
5. Depending on Gemini CLI version, policy matching can be bypassed by a
   differently shaped command or unsupported tool. Test on Windows and Linux
   before claiming cross-platform guard parity.
6. Launching Gemini's CLI validates configuration only; integration, cleanup,
   sweep and plan workflows still need live manual acceptance tests in a
   throwaway Git repository before treating this as production-ready.
7. This ZIP is an **overlay**, NOT an independently installable extension:
   combine it with the original MAGOS repository first.

## QA checklist

- [ ] `python scripts/validate_gemini_adapter.py --repo .` passes.
- [ ] `gemini extensions validate .` passes on the merged repo.
- [ ] `/commands list` includes all eight `/Git*` entries.
- [ ] `/skills list` exposes `git-orchestrator`.
- [ ] `/GitPlan --help` performs no Git/tool operations.
- [ ] `/GitRecon` is read only, and `/GitRecon --remote` obeys consent.
- [ ] `/GitCleanup` produces preview and does not delete anything.
- [ ] Write-path guard/review verification in a disposable repository.
- [ ] Claude `plugin validate` and Hermes `plugins validate .` still pass.

## References

- Gemini extension reference: https://geminicli.com/docs/extensions/reference/
- Gemini custom commands: https://geminicli.com/docs/cli/custom-commands/
- Gemini policy engine: https://geminicli.com/docs/reference/policy-engine/
- Gemini release flow: https://geminicli.com/docs/extensions/releasing/
