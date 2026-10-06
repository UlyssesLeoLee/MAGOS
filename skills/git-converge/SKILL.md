---
name: git-converge
description: "收敛分支（仅显式调用，写操作）；/git-converge BRANCH [--apply] [--discard-ignored] [--help]."
license: Apache-2.0
metadata:
  short-description: "收敛分支；$git-converge BRANCH [--apply] [--discard-ignored] [--help]."
---

# GitConverge

Command adapter for the canonical `/GitConverge` command of the MAGOS (Multi-Agent Git Orchestrator) package. Use it only when the user explicitly invokes `/git-converge` in Hermes or `$git-converge` in Codex.

## Usage

- Hermes: `/git-converge <branch> [--apply] [--discard-ignored] [--lang <language>] [--help]`
- Codex: `$git-converge <branch> [--apply] [--discard-ignored] [--lang <language>] [--help]`
- `<branch>`: Required local branch that receives everything. Matched exactly (case-sensitive); it must not be `main`.
- `--apply`: Merge every local branch's unique commits (`main` first) into `<branch>`, then delete the merged local branches and their clean worktrees so only `main` and `<branch>` remain. A conflict stops the command and deletes nothing. It never moves or deletes `main` and never touches remote branches.
- `--discard-ignored`: With `--apply`, also allow removing worktrees that hold ignored files (for example `.env`). Without it those worktrees and their branches are kept.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Preview the merge plan, blocked items, and the expected final branch list; nothing is changed.

Examples: `/git-converge agent/release`, `$git-converge agent/release --apply`, `$git-converge <branch> --lang English`, `$git-converge --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-converge` in the user's message.
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. If the branch is missing, show this help and ask for it; for an unknown option, explain the error and show this help. Do not inspect or change the repository in these error cases. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Codex disables implicit selection for this adapter through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-converge` command (Hermes renders it as "The user has invoked the "git-converge" skill" followed by the arguments) or `$git-converge` in Codex. If this adapter was selected without such an invocation, preview at most and merge and delete nothing.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` section **6. GitConverge**: command contract, classifications, gates, and apply procedure.
3. `../../references/reconnaissance.md` and `../../references/decision-matrix.md`: inspection steps and cleanup criteria.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line, go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and do not merge, switch, or delete anything; a read-only preview is still allowed.

## Execution

Execute the canonical `/GitConverge` command only when the user explicitly invoked this command skill. Preview by default; merge and delete only when the explicit command includes `--apply` and every gate still passes, and record the full plan first (every local branch with its tip, merge status and blockers, the merge order, and the expected final branches) and include it in the final report. Stop on a conflict and delete nothing. Never push, force-push, or delete remote branches; never use `git branch -D` or `git worktree remove --force`; never run a repository-wide `git worktree prune`. Ask for a branch if none is provided. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
