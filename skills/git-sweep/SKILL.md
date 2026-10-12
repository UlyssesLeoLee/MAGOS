---
name: git-sweep
description: "收敛并清除已合并远端分支（仅显式调用，写操作）；/git-sweep BRANCH [--apply] [--remote NAME] [--help]."
license: Apache-2.0
metadata:
  short-description: "收敛并清远端分支；$git-sweep BRANCH [--apply] [--remote NAME] [--help]."
---

# GitSweep

Command adapter for the canonical `/GitSweep` command of the MAGOS (Multi-Agent Git Orchestrator) package. It is `/GitConverge` followed by a guarded sweep of merged remote branches. Use it only when the user explicitly invokes `/git-sweep` in Hermes or `$git-sweep` in Codex.

## Usage

- Hermes: `/git-sweep <branch> [--apply] [--discard-ignored] [--remote <name>] [--lang <language>] [--help]`
- Codex: `$git-sweep <branch> [--apply] [--discard-ignored] [--remote <name>] [--lang <language>] [--help]`
- `<branch>`: Required local branch that receives everything. Matched exactly (case-sensitive); it must not be `main`.
- `--apply`: Run `/GitConverge <branch> --apply` first (merge every local branch's unique commits into `<branch>`, delete the merged local branches and their clean worktrees), then delete the remote branches that are already merged into a branch the remote keeps. A conflict or failed check stops the command before any deletion. It never moves or deletes `main` and never pushes commits.
- `--discard-ignored`: Passed through to the converge phase: also allow removing worktrees that hold ignored files (for example `.env`). Without it those worktrees and their branches are kept.
- `--remote <name>`: The remote whose merged branches are swept (`origin` when absent).
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Preview the converge plan and the remote branches that would be deleted; nothing is changed and the network is not contacted.

A remote branch is deleted only when its tip is already contained in the remote's own copy of `<branch>` or its default branch, so a branch merged only locally stays on the remote until you push `<branch>` and run `$git-sweep` again.

Examples: `/git-sweep agent/release`, `$git-sweep agent/release --apply`, `$git-sweep agent/release --apply --remote upstream`, `$git-sweep --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-sweep` in the user's message.
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. If the branch is missing, show this help and ask for it; for an unknown option, explain the error and show this help. Do not inspect or change the repository in these error cases. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Codex disables implicit selection for this adapter through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-sweep` command (Hermes renders it as "The user has invoked the "git-sweep" skill" followed by the arguments) or `$git-sweep` in Codex. If this adapter was selected without such an invocation, preview at most and merge, delete, and push nothing.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` sections **7. GitSweep** and **6. GitConverge**: command contract, classifications, gates, and apply procedure (GitSweep reuses the GitConverge procedure unchanged).
3. `../../references/reconnaissance.md` and `../../references/decision-matrix.md`: inspection steps and cleanup criteria.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line, go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and do not merge, switch, delete, or push anything; a read-only preview is still allowed.

## Execution

Execute the canonical `/GitSweep` command only when the user explicitly invoked this command skill. Preview by default; merge and delete only when the explicit command includes `--apply` and every gate still passes, and record the full plan first (the converge plan plus every remote candidate with its SHA) and include it in the final report. Stop on a conflict and delete nothing, locally or remotely. The only push allowed is deleting one named, fully merged remote branch at a time, guarded by `--force-with-lease` on its recorded SHA; never push commits or tags, never force-push, never use `--mirror` or `--prune`, never run `git remote prune` or `git fetch --prune`, never use `git branch -D` or `git worktree remove --force`, never run a repository-wide `git worktree prune`. Ask for a branch if none is provided. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
