---
name: git-recon
description: "查看仓库状态（只读）；/git-recon [--remote] [--help]."
license: Apache-2.0
metadata:
  short-description: "查看仓库状态；$git-recon [--remote] [--help]."
---

# GitRecon

Command adapter for the canonical `/GitRecon` command of the MAGOS (Multi-Agent Git Orchestrator) package. Use it when the user explicitly invokes `/git-recon` in Hermes or `$git-recon` in Codex.

## Usage

- Hermes: `/git-recon [--remote] [--lang <language>] [--help]`
- Codex: `$git-recon [--remote] [--lang <language>] [--help]`
- `--remote`: Refresh remote-tracking refs before classifying the repository; it does not change branches, worktrees, or commit history.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting the repository.
- Default: Read-only snapshot using existing local refs; no remote refresh.

Examples: `/git-recon --remote`, `$git-recon --remote`, `$git-recon --lang English`, `$git-recon --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-recon` in the user's message.
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. For an unknown option, explain the error, show the same help, and stop. Read the shared files below only for a normal invocation.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` section **1. GitRecon**: command contract and output format.
3. `../../references/reconnaissance.md`: repository inspection steps.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line, go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` and view its `references/commands.md` and `references/reconnaissance.md` files.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If a shared file cannot be read, name the missing path, report that the MAGOS installation is incomplete, and continue read-only with the safety defaults below.

## Execution

Execute the canonical `/GitRecon` command with the supplied arguments. Inspect the current repository before reporting state-dependent findings. Default to read-only; `--remote` only permits refreshing remote-tracking refs. Never change branches, worktrees, or commit history. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
