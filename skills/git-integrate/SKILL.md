---
name: git-integrate
description: "集成目标（仅限用户显式调用，写操作）；/git-integrate TARGET [--strategy] [--help]."
license: Apache-2.0
metadata:
  short-description: "集成目标；$git-integrate TARGET [--strategy] [--help]."
---

# GitIntegrate

Command adapter for the canonical `/GitIntegrate` command of the MAGOS (Multi-Agent Git Orchestrator) package. Use it only when the user explicitly invokes `/git-integrate` in Hermes or `$git-integrate` in Codex.

## Usage

- Hermes: `/git-integrate <lane|branch> [--strategy auto|merge|squash|cherry-pick] [--lang <language>] [--help]`
- Codex: `$git-integrate <lane|branch> [--strategy auto|merge|squash|cherry-pick] [--lang <language>] [--help]`
- `<lane|branch>`: Required source lane or branch to integrate.
- `--strategy <value>`: Optional integration strategy. `auto` follows repository policy and reviewed acceptance shape (default); `merge` preserves accepted lane commits; `squash` delivers the lane as one commit when allowed; `cherry-pick` uses only accepted, dependency-safe commits.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Strategy `auto`; integration proceeds only after review, dependency, freshness, protection, and repository-policy gates pass.

Examples: `/git-integrate agent/auth`, `$git-integrate agent/auth --strategy squash`, `$git-integrate <lane-or-branch> --lang English`, `$git-integrate --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-integrate` in the user's message.
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. If the source target or strategy value is missing or invalid, show this help and ask for a valid value; for an unknown option, explain the error and show this help. Do not inspect or change the repository in these error cases. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Codex disables implicit selection for this adapter through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-integrate` command (Hermes renders it as "The user has invoked the "git-integrate" skill" followed by the arguments) or `$git-integrate` in Codex. If this adapter was selected without such an invocation, do not integrate; offer the command instead.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` section **4. GitIntegrate**: command contract and integration gates.
3. `../../references/reconnaissance.md` and `../../references/decision-matrix.md`: inspection steps and operation choice.
4. `../../references/handoff-and-state.md`: lane record and integration receipt format.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line, go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and stop without changing the repository.

## Execution

Execute the canonical `/GitIntegrate` command only when the user explicitly invoked this command skill. Check review, dependency, freshness, target protection, and repository policy before integration; stop if any gate fails. Never force-push or rewrite shared history. Ask for a target if none is provided. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
