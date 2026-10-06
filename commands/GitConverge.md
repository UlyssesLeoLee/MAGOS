---
description: 把所有本地分支的领先内容合并进指定分支，只保留 main 和该分支；默认仅预览，--apply 才执行
argument-hint: "<branch> [--apply] [--discard-ignored] [--lang <language>] [--help]"
disable-model-invocation: true
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. If the branch is missing, show this help and ask for it before proceeding. For an unknown option, explain the error, show this help, and stop.

## Inline help

Usage: `/GitConverge <branch> [--apply] [--discard-ignored] [--lang <language>] [--help]`

- `<branch>`: Required local branch that receives everything. Matched exactly (case-sensitive); it must not be `main`.
- `--apply`: Merge every local branch's unique commits (`main` first) into `<branch>`, then delete the merged local branches and their clean worktrees so only `main` and `<branch>` remain. A conflict stops the command and deletes nothing. It never moves or deletes `main` and never touches remote branches.
- `--discard-ignored`: With `--apply`, also allow removing worktrees that hold ignored files (for example `.env`). Without it those worktrees and their branches are kept.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting or changing the repository.
- Default: Preview the merge plan, blocked items, and the expected final branch list; nothing is changed.

Examples: `/GitConverge agent/release`, `/GitConverge agent/release --apply`, `/GitConverge <branch> --lang English`, `/GitConverge --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitConverge $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. If none is listed but `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: report observations, but do not merge, switch, delete, or prune anything.
2. Execute `/GitConverge` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md` section **6. GitConverge**. Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default: preview only unless `--apply` is present. With `--apply`, record the full plan first (every local branch with its tip, merge status and blockers, the merge order, and the expected final branches) and include it in your final report, then merge and delete only after the skill is loaded, every gate passes, and each deletion still meets its recheck at the moment of deletion; if the skill could not be loaded, preview only. Stop on a conflict and delete nothing. Never push, force-push, or delete remote branches; never use `git branch -D` or `git worktree remove --force`; never run a repository-wide `git worktree prune`. If no branch is given, ask for one. Reply language: Chinese unless `--lang` selects another one; this includes the final report, however long the run was.
