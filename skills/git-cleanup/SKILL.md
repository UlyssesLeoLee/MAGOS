---
name: git-cleanup
description: "预览清理（仅限用户显式调用；--apply 才删除）；/git-cleanup [--apply] [--help]."
license: Apache-2.0
metadata:
  short-description: "预览清理；$git-cleanup [--apply] [--help]."
---

# GitCleanup

Command adapter for the canonical `/GitCleanup` command of the MAGOS (Multi-Agent Git Orchestrator) package. Use it only when the user explicitly invokes `/git-cleanup` in Hermes or `$git-cleanup` in Codex.

## Usage

- Hermes: `/git-cleanup [--apply] [--lang <language>] [--help]`
- Codex: `$git-cleanup [--apply] [--lang <language>] [--help]`
- `--apply`: Recheck each safe local candidate, then apply cleanup only where every safety condition still holds. It does not permit deleting remote branches.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Preview cleanup candidates only; no deletion.

Examples: `/git-cleanup`, `$git-cleanup --apply`, `$git-cleanup --lang English`, `$git-cleanup --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-cleanup` in the user's message.
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. For an unknown option, explain the error, show this help, and stop. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Codex disables implicit selection for this adapter through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-cleanup` command (Hermes renders it as "The user has invoked the "git-cleanup" skill" followed by the arguments) or `$git-cleanup` in Codex. If this adapter was selected without such an invocation, preview at most and delete nothing.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` section **5. GitCleanup**: command contract, cleanup classes, and apply constraints.
3. `../../references/reconnaissance.md` and `../../references/decision-matrix.md`: inspection steps and cleanup criteria.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line, go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and do not delete anything; a read-only preview is still allowed.

## Execution

Execute the canonical `/GitCleanup` command only when the user explicitly invoked this command skill. Preview candidates by default; delete only when the explicit command includes `--apply` and every safety condition still passes. Never delete remote branches unless explicitly asked. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
