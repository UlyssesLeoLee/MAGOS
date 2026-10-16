# Technical Design: `scripts/sync_hosts.py`

Source: `scripts/sync_hosts.py`

Source-SHA256: `f5b65edb9e55248dfa2601c6bee3b201f0f12d6443b52f8e8e4c47f4f5906701`

## Responsibility

`sync_hosts.py` compares or synchronizes the MAGOS files that each AI host loads from the user's home with the bytes in
this repository. It serves three hosts:

- **Claude Code**: the seven command files `commands/GitRecon.md`, `GitAnalyze.md`, `GitRecommend.md`,
  `GitIntegrate.md`, `GitCleanup.md`, `GitConverge.md` and `GitSweep.md`, installed under `~/.claude/commands/`.
- **Codex** and **Hermes**: the host-neutral skill package, the same list for both (`package_files()`): the root
  `SKILL.md`, every `references/*.md`, and every `skills/<name>/SKILL.md` with its `skills/<name>/agents/openai.yaml`
  when present, except the plugin-only entry skill `git-orchestrator`. The adapters resolve `../../SKILL.md` and
  `../../references/*.md`, so the installed tree keeps the repository layout. `plugin.json`, `commands/`, `scripts/`
  (including the lane guard), `hooks/`, `tests/` and the READMEs are not part of the package.

It never deletes an installed file, never writes outside a selected install root, writes nothing when its preflight
fails, and has no network access. It also detects a MAGOS plugin that Claude Code already loads, because the plugin
provides `/magos:GitXxx` and copied command files would add a second, older `/GitXxx` set.

## Dependencies

Upstream: Python 3.9+ standard library only (`argparse`, `hashlib`, `json`, `os`, `pathlib`, `sys`, `tempfile`;
`Path.is_relative_to` needs 3.9). The repository is the parent of the script's own directory
(`Path(__file__).resolve().parents[1]`). Environment: `CODEX_HOME`, `HERMES_HOME` and, on Windows, `LOCALAPPDATA`;
all three are ignored when `--home` is given, so a run against a scratch home never reaches the real one. Files read
from the home: Codex and Hermes install roots, Hermes' `active_profile`, `~/.claude/skills/*/.claude-plugin/plugin.json`,
`~/.claude/plugins/installed_plugins.json` and `~/.claude/plugins/cache/*/*/*/.claude-plugin/plugin.json`.

Downstream callers:

- Users, through the install and update steps of `README.md`, `README.en.md` and `references/installation.md`
  (`python -X utf8 scripts/sync_hosts.py [--host ...] [--verify | --apply [--create-roots]]`).
- `tests/codex/run_host_cases.py` loads the module and provisions its fixtures with `package_files()` and reads the
  Hermes configuration location with `hermes_home()`, so the test layout equals a real install.
- `tests/codex/contracts/install_layout.py` checks the package containment rules against the same list.
- The Claude source-contract case `git-converge/package-wiring` (`tests/claude/contracts/cases.json`) pins the text
  `"GitCleanup", "GitConverge", "GitSweep")` of `COMMAND_NAMES`.
- `scripts/magos_guard.py install` copies the lane guard for Codex and Hermes, because this script never ships it.

## Public Contract

Invocation: `python -X utf8 scripts/sync_hosts.py [--host claude|codex|hermes]... [--home DIR] [--codex-root DIR]
[--hermes-root DIR] [--verify | --apply] [--create-roots] [--json]`.

Options:

- `--host H` (repeatable) limits the run to the named hosts. Without `--host` the run selects `claude`, `codex` and
  `hermes`, except that it leaves `claude` out when a Claude Code plugin of MAGOS is detected (plugin detection below);
  the report then starts with the detection notes and
  `Skipping the claude host for that reason; pass --host claude to copy the commands anyway.` An explicit
  `--host claude` copies the commands and still reports the detection notes.
- `--home DIR`: the user home that holds `.claude`, `.agents`/`.codex` and the Hermes home (default `~`). With `--home`
  the environment overrides are ignored.
- `--codex-root DIR` and `--hermes-root DIR`: use this package root for the host instead of resolving one; no root note
  is produced for it.
- Mode: the default inventories and reports only; `--verify` reports and exits 1 when any file is missing or differs;
  `--apply` copies every missing or different file. `--verify` and `--apply` exclude each other (usage error, exit 2).
- `--create-roots`: with `--apply`, creates the missing install roots, but only when nothing else fails the preflight,
  so a refused run writes nothing. Without `--apply` it has no effect.
- `--json`: print the report as one JSON object instead of text.

Install roots:

- Claude: root `~/.claude`; the required directory is `~/.claude/commands`.
- Codex: `~/.agents/skills/MAGOS` (current location). When only the legacy `<CODEX_HOME or ~/.codex>/skills/MAGOS`
  exists it is used, with a note that `~/.agents/skills` is current; when both exist the current one is used, with a
  note that Codex loads both and sees duplicate skills. The required directory is the root itself.
- Hermes: the Hermes home is `HERMES_HOME`, else `%LOCALAPPDATA%\hermes` on Windows (`<home>/AppData/Local/hermes` with
  `--home` or an empty `LOCALAPPDATA`), else `<home>/.hermes`. When the home comes from neither `HERMES_HOME` nor
  `--home`, a sticky profile named in `<base>/active_profile` (not `default`, with an existing
  `<base>/profiles/<name>`) selects that profile directory. The root is
  `<Hermes home>/skills/multi-agent-git-orchestrator`, or an existing `<Hermes home>/skills/MAGOS` (with a note); when
  both exist the first is used, with a note that Hermes keeps the first skill of each name. The required directory is
  the root itself.

Plugin detection (`claude_plugin_notes(<home>/.claude)`), one note per detected install:

- A skills-directory clone: `~/.claude/skills/<dir>/.claude-plugin/plugin.json` whose `name` is `magos`. The note names
  the clone, says it gives `/magos:GitXxx` and is updated with `git pull`, and that copies in `~/.claude/commands` would
  add a second `/GitXxx` set.
- A marketplace install: when `~/.claude/plugins/installed_plugins.json` parses as a JSON object whose `plugins` value
  is an object, each key whose plugin part (the text before the first `@`) is `magos` and that lists at least one
  install entry with `"scope": "user"` is detected, whatever the marketplace part is. Entries of any other scope
  (`project`, `local`) cover only their project and are not detected. When that file is absent or does not parse to
  that shape, the plugins cache decides instead: a `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/.claude-plugin/plugin.json`
  whose `name` is `magos` is detected. The note names the key or the cache manifest, says the plugin gives
  `/magos:GitXxx` and is updated through the Claude Code plugin manager, and that copies in `~/.claude/commands` would
  add a second `/GitXxx` set.
- Unreadable or malformed manifests, index files and entries are ignored without an error.

Inventory and statuses. For every selected host the report gives `ready`, `missing-root` (the required directory does
not exist) or `git-checkout` (the root contains `.git`: update it with git instead of copying; for Codex a checkout that
also carries `.claude-plugin/` is named as the reason its skills appear as `$magos:git-*`). For every file of a ready
host: `matched`, `missing`, `different` or `blocked` (the repository source is unavailable, the destination resolves
outside the root, or the destination is a symlink or not a regular file), with the source and installed sha256. A
repository source that is missing, not a regular file or a symlink is a source error.

Writes (`--apply`): each file is re-read and its sha256 compared with the inventory, the destination is re-checked to
lie inside the root and not be a symlink, then the bytes go to a temporary file in the destination directory that
`os.replace` moves into place; a leftover temporary file is removed. After writing, the inventory runs again and every
file must be `matched`.

Report (`--json`): `{home, selected_hosts, hosts:[{host, status, required_directory, reason?}], files:[{host,
relative_path, destination, source_sha256, installed_sha256, status, reason?}], source_errors, notes,
summary:{matched, missing, different, blocked, missing_roots, git_checkouts, source_errors}, mode: plan|verify|apply,
created_roots, written?, error?}`. The text form prints `MAGOS install <mode>: <home>`, `NOTE`, `SOURCE ERROR`, one
line per host and per file, `Created roots`, `Written: N`, `ERROR` and `Summary`.

Exit codes: 0 when the preflight passes and nothing else fails (the default mode reports missing or different files
without failing), after a successful `--apply`, and for a `--verify` in which every file matches; 1 `--verify` found a missing or different file; 2 preflight failure
(missing root, git-checkout root, source error or blocked file: "Preflight failed; ... No files were written."), a write
error ("Sync stopped after a write error: ... Rerun --verify or --apply."), a file that does not match after writing,
or a usage error.

## Change Notes

Version 1.0.2 of the script detects a MAGOS plugin installed from a Claude Code marketplace as well as a
skills-directory clone: a user-scope entry of a `magos@<marketplace>` key in `~/.claude/plugins/installed_plugins.json`,
or, when that index is absent or malformed, a `magos` manifest in the plugins cache. A detected marketplace install is
reported with a note and leaves the Claude commands out of a default run exactly like a clone; an explicit
`--host claude` copies them. The package list, install roots, modes, statuses, report and exit codes are those of 1.0.1.
Compatibility: a home without a MAGOS plugin, or with only a project-scoped or local-scoped install, gets the Claude
commands by default.
