# Technical Design: `__init__.py`

Source: `__init__.py`

Source-SHA256: `76db96aa4767e257b2bbcdd172f6cc32b4dabdfef27979750ec439e60b434bb5`

## Responsibility

`__init__.py` is the Hermes native plugin entry of MAGOS. `hermes plugins install UlyssesLeoLee/MAGOS` clones the
repository, `plugin.yaml` is its native manifest (name and version equal to `plugin.json`, `provides_hooks:
[pre_tool_call]`, no tools, capabilities or dependencies), and Hermes calls `register(ctx)` from this file once when it
loads the plugin. The
function registers every `skills/<name>/SKILL.md` under the plugin namespace, so Hermes offers the skills as
`/magos:git-recon` and so on, which Codex spells `$magos:git-recon` and Claude Code hides. Without this file Hermes loads the
package through its portable `plugin.json` and names the commands `/agent-plugin-magos-<digest>:git-recon`.

Nine skills are registered: the entry skill `git-orchestrator` and the eight command adapters `git-recon`,
`git-analyze`, `git-recommend` (read-only) and `git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, `git-plan`
(commands that write to a repository).

Hermes lists every registered plugin skill in the `<available_skills>` index of the system prompt with the description
passed at registration; it does not read a plugin skill's `SKILL.md` description for that index, so a skill registered
without one is shown as a bare name. The module therefore owns `INDEX_DESCRIPTIONS`, one line per skill. The
orchestrator gets a trigger-rich line, so the model loads it on its own when agents overwrite each other's work. A
read-only command gets a line that lets the model use it when the user asks. A command that writes to a repository gets
a line that names what it writes, says it runs only when the user types its command, and ends with
`Never load it yourself.`, so the model leaves it to the user. The skills are read-only instructions.

The module also runs the MAGOS guard in Hermes. It registers two `pre_tool_call` callbacks, the verdict and the
approval, which act only for the `terminal` tool. The verdict callback starts the plugin's own guard
(`scripts/magos_guard.py hook hermes pre-tool --hermes-gate <gate>`) with the call as a shell-hook payload and turns its
answer into Hermes directives: nothing, a `block`, or a `modify` that hands Hermes the command the guard rebuilt with a
one-time approval token. For a user-only guard command the guard also returns a question and a request-unique rule key,
which the approval callback returns as the `approve` directive of the same call, so Hermes asks the user in its own
approval prompt before the rewritten command runs. The section Hermes approval (version 1.0.8) of
`.quality/docs/scripts/magos_guard.py.md` states the guard's side.

## Dependencies

Upstream: Python 3.9+ standard library (`json`, `os`, `pathlib`, `re`, `subprocess`, `sys`, `threading`, `time`,
`inspect`). The module imports no network module and builds no code at run time (no `exec`, `eval`, `compile`,
`__import__`, `importlib`, no `sys.modules`). It starts processes at one place, `_run_guard`, whose argument list is
`sys.executable`, `-X utf8 -B`, the plugin's own `scripts/magos_guard.py` and `hook hermes pre-tool --hermes-gate
<gate>`, without a shell. `os` is used for the environment (`MAGOS_GUARD`, `HERMES_PLUGIN_HOST_PROCESS`, the child's
environment) and the working directory, by attribute only. Host: Hermes passes a context object whose
`register_skill(name, path, description="")` records one skill and whose `register_hook(name, callback)` adds one
callback; the module calls `register_skill` for each skill and `register_hook("pre_tool_call", ...)` exactly twice, no
other `ctx.register_*` method, and `plugin.yaml` declares that hook, because the plugin catalog compares declared
capabilities. Hermes modules are imported inside the gate probe only (`tools.approval`, `tools.approval_context`,
`hermes_cli.plugins`) and for the active home (`hermes_constants.get_hermes_home`), each in a `try`, read, never patched.
Filesystem: the `skills/` directory next to the module, `Path(__file__).parent / "skills"`, the `SKILL.md` file of each
child directory, and `scripts/magos_guard.py` next to the module.

Downstream callers and checks:

- Hermes, when it loads the plugin.
- `tests/codex/guard/test_project_sources.py` loads the module from the repository path in process with a recording
  context, so the coverage gate measures it (line coverage strictly above 90 percent for the file and the project, see
  `.quality/qguard.json`).
- `tests/codex/guard/test_hermes_approval.py` loads the module the same way and drives `verdict`, `approval` and
  `gate` with the real guard as the child of `verdict` and a reimplementation of Hermes's directive aggregation.
- The guard's `doctor` and `install --host hermes` read this file in the Hermes plugin directory as bytes and take the
  text `register_hook("pre_tool_call"` as the sign that the plugin runs the guard (Hermes approval (version 1.0.8) in
  `.quality/docs/scripts/magos_guard.py.md`).
- `tests/codex/contracts/install_layout.py` (`hermes_manifest_problems`, `hermes_index_problems`) reads the module as
  text and syntax tree, without importing it: it needs the literal top-level `INDEX_DESCRIPTIONS` assignment and a
  `description=` argument that reads it in every `ctx.register_skill(` call, exactly two
  `ctx.register_hook("pre_tool_call",` calls and no other `ctx.register_*` call, and `provides_hooks` with the one
  item `pre_tool_call` in `plugin.yaml`. `tests/codex/contracts/test_agent_plugin.py`
  runs those rows on the unmodified package and on mutations of this file.
- `tests/codex/guard/test_supply_chain.py` (no network module and no dynamic code; one process start, in `_run_guard`) and
  `tests/codex/guard/test_package.py` (Python 3.9 grammar, `from __future__ import annotations` when annotations are
  used, the coverage gate's tracked source list).
- `scripts/sync_hosts.py` never ships this file: the Codex and Hermes skill packages carry no host manifest and no
  entry module. Claude Code ignores it and reads `skills/` through `.claude-plugin/plugin.json`.

## Public Contract

`register(ctx) -> None`. For each child of `skills/` in the order of `sorted(skills_dir.iterdir())`, a directory that
holds a regular file `SKILL.md` is registered with `ctx.register_skill(child.name, <path of its SKILL.md>,
description=INDEX_DESCRIPTIONS.get(child.name, ""))`. The skill name is the directory name. Files, directories without a
`SKILL.md` and a `SKILL.md` that is a directory are skipped without an error. Then it calls
`ctx.register_hook("pre_tool_call", verdict)` and `ctx.register_hook("pre_tool_call", approval)`, in this order. The
function returns `None`.

`verdict(tool_name="", args=None, **kw)` and `approval(tool_name="", args=None, **kw)`: both return `None` for a tool
other than `terminal` and when `MAGOS_GUARD` is `off`. `verdict` runs the guard (limit 25 s) and returns `None`,
`{"action": "block", "message": M}` or `{"action": "modify", "args": {"command": C}}` as the section Hermes approval
(version 1.0.8), The plugin callbacks, of the guard's design states; a guard that cannot start, exits non-zero, prints no
JSON object or an object of no known shape, or exceeds 25 s gives a block whose message names the cause and the off
switches (`MAGOS_GUARD=off`, `hermes plugins disable magos`), in Chinese unless `MAGOS_LANG` is `en`. `verdict` keeps a mark for
every call it answers (the approve directive for a question, nothing otherwise); `approval` takes the mark of the same
call once and returns its directive or nothing, and a block when a command that names `magos_guard` has no mark. `gate()` returns `ask`, `bypass` or `absent` as that section states.

`INDEX_DESCRIPTIONS`: a top-level literal `dict` from skill name to one single-line string, with no computed value, so
a check can read it with `ast.literal_eval` without running the module. It holds exactly one non-empty entry for each
directory of `skills/` that carries a `SKILL.md`, no entry for anything else, in this order: `git-orchestrator`,
`git-recon`, `git-analyze`, `git-recommend`, `git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, `git-plan`.
`git-plan` comes last, after the read-only commands and the earlier write commands, in the section order of
`references/commands.md`, so the neighbouring text of the earlier lines stays as it is. The `""` default of the lookup
exists only so that a skill added without a line still registers; the contract check fails that tree.

Line rules, final state:

- `git-orchestrator`: 100 to 400 characters (it sits in every Hermes system prompt); it names the coordination topics
  (lane planning, branch and worktree safety, merge and integration order, cleanup, branch strategy) and the situations
  in which the model loads it on its own.
- Read-only commands (`git-recon`, `git-analyze`, `git-recommend`): start with `Read-only` and say
  `Use /magos:<name> when the user asks`; they do not tell the model to stay away from them.
- Write commands, which are exactly the skills whose `SKILL.md` has the section `## Explicit invocation only`
  (`git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, `git-plan`): the line names what the command writes,
  then `run only when the user types /magos:<name>.`, and ends with `Never load it yourself.`
- `git-plan` reads: `Registers lane claims and, with --converge --apply, merges the lanes: run only when the user types
  /magos:git-plan. Never load it yourself.` (one line, without a line break).
- A line names no command other than its own: every text of the form `/<plugin>:<command>` in a line equals
  `/magos:<its own name>`.
- Every line other than the orchestrator's has at most 160 characters.

The module's other public names are the two callbacks `verdict` and `approval`, `gate`, and the constants `GUARD`
(`scripts/magos_guard.py` next to the module), `GUARD_TOOLS` (`terminal`), `GUARD_LIMIT_S` (25) and `KEPT_S` (120).
Its only state is the marks of `verdict`, kept under a lock and dropped after `KEPT_S` seconds: calling `register`
twice on two contexts registers the same skills and callbacks twice, once per context, and both share the marks.

## Errors

- No `skills/` directory next to the module, or an unreadable one: `skills_dir.iterdir()` raises `FileNotFoundError` or
  `OSError` out of `register` before any call to the context, so Hermes reports a failed plugin load instead of a
  silently empty plugin. The package always ships `skills/`.
- A `ctx` without `register_skill`, or a `register_skill` that raises, propagates its exception (`AttributeError` or
  the host's own error); no skill after the failing one is registered and nothing is rolled back.
- A skill without an `INDEX_DESCRIPTIONS` entry is registered with the empty description, shown to the model as a bare
  name; `tests/codex/contracts/install_layout.py` turns that tree red as `INDEX_DESCRIPTIONS has no line for
  skills/<name>`, and an entry for a name that is not a skill as `INDEX_DESCRIPTIONS names '<name>', which is not a
  skill`.
- A write command whose `SKILL.md` carries `## Explicit invocation only` and whose line lacks `Never load it
  yourself` is a red contract row (`the <name> index line must tell the model never to load it itself`), as is a line
  that names another command and an orchestrator line outside 100 to 400 characters.
- A guard failure raises nothing out of a callback: a guard that cannot start, exits non-zero, prints no JSON object
  or an object of no known shape, or runs longer than 25 s gives a `block` whose message names the cause and the off
  switches (Public Contract). An exception that still leaves a callback, and a callback that exceeds Hermes's own
  limit, is a block by Hermes's rule for `pre_tool_call`.

## Change Notes

Version 1.0.4 registers nine skills: the entry skill and eight command adapters, with `git-plan` as the eighth adapter
and the last entry of `INDEX_DESCRIPTIONS`. The `git-plan` line states that the command registers lane claims and, with
`--converge --apply`, merges the lanes, that it runs only when the user types `/magos:git-plan`, and ends with
`Never load it yourself.`; the adapter `skills/git-plan/SKILL.md` carries the section `## Explicit invocation only`
that makes the contract require this ending. The registration code, the table format and the line rules are those of
1.0.3, and the earlier eight lines keep their text and order, so `/magos:git-recon` and the other commands keep their
names and descriptions. Compatibility: a Hermes install that updates the plugin gains `/magos:git-plan`, and the model
never loads it on its own.

Version 1.0.8 runs the MAGOS guard in Hermes from the plugin: `register` adds the verdict and approval `pre_tool_call`
callbacks for the `terminal` tool, and `plugin.yaml` declares `provides_hooks: [pre_tool_call]`. A user-only guard
command reaches the user as a question in Hermes's own approval prompt; the skills, their table and their order are those
of 1.0.4. Compatibility: the guard runs on every terminal call once the updated plugin is loaded (after `hermes plugins
update magos` and a restart); `MAGOS_GUARD=off`, `hermes plugins disable magos` and `git config --local magos.guard off`
turn it off, and a MAGOS entry under `hooks:` should be removed, because it denies every user-only command before Hermes
can ask.
