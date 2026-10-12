---
description: 先执行 GitConverge 把所有本地分支收敛进指定分支，再一并清除远端已合并分支；默认仅预览，--apply 才执行
argument-hint: "<branch> [--apply] [--discard-ignored] [--remote <name>] [--lang <language>] [--help]"
disable-model-invocation: true
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. If the branch is missing, show this help and ask for it before proceeding. For an unknown option, explain the error, show this help, and stop.

## Inline help

Usage: `/GitSweep <branch> [--apply] [--discard-ignored] [--remote <name>] [--lang <language>] [--help]`

- `<branch>`: Required local branch that receives everything. Matched exactly (case-sensitive); it must not be `main`.
- `--apply`: Run `/GitConverge <branch> --apply` first (merge every local branch's unique commits into `<branch>`, delete the merged local branches and their clean worktrees), then delete the remote branches that are already merged into a branch the remote keeps. A conflict or failed check stops the command before any deletion. It never moves or deletes `main` and never pushes commits.
- `--discard-ignored`: Passed through to the converge phase: also allow removing worktrees that hold ignored files (for example `.env`). Without it those worktrees and their branches are kept.
- `--remote <name>`: The remote whose merged branches are swept (`origin` when absent).
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting or changing the repository.
- Default: Preview the converge plan and the remote branches that would be deleted; nothing is changed and the network is not contacted.

A remote branch is deleted only when its tip is already contained in the remote's own copy of `<branch>` or its default branch, so a branch merged only locally stays on the remote until you push `<branch>` and run `/GitSweep` again.

Examples: `/GitSweep agent/release`, `/GitSweep agent/release --apply`, `/GitSweep agent/release --apply --remote upstream`, `/GitSweep --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitSweep $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `magos` (plugin clone directory), `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. If none is listed but `~/.claude/skills/magos/SKILL.md` or `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: report observations, but do not merge, switch, delete, push, or prune anything.
2. Execute `/GitSweep` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md` section **7. GitSweep** (which builds on section **6. GitConverge**). Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default: preview only unless `--apply` is present. With `--apply`, record the full plan first (the converge plan plus every remote candidate with its SHA), then merge and delete only after the skill is loaded, every gate passes, and each deletion still meets its recheck at the moment of deletion; if the skill could not be loaded, preview only. Stop on a conflict and delete nothing, locally or remotely. The only push allowed is deleting one named, fully merged remote branch at a time, guarded by `--force-with-lease` on its recorded SHA; never push commits or tags, never force-push, never use `--mirror` or `--prune`, never run `git remote prune` or `git fetch --prune`, never use `git branch -D` or `git worktree remove --force`, never run a repository-wide `git worktree prune`. If no branch is given, ask for one. Reply language: Chinese unless `--lang` selects another one; this includes the final report, however long the run was.
