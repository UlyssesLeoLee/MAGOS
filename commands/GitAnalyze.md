---
description: 深入分析指定分支或 worktree，评估 merge / rebase / cherry-pick / delete 是否安全
argument-hint: "<branch|worktree> [--remote] [--lang <language>] [--help]"
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. If the target is missing, ask for it and show this help. For an unknown option, explain the error, show this help, and stop.

## Inline help

Usage: `/GitAnalyze <branch|worktree-path> [--remote] [--lang <language>] [--help]`

- `<branch|worktree-path>`: Required branch name or worktree path to analyze.
- `--remote`: Refresh remote-tracking refs before analysis. It does not change branches, worktrees, or commit history.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting the repository.
- Default: Read-only analysis using existing local refs; no remote refresh.

Examples: `/GitAnalyze feature/auth`, `/GitAnalyze feature/auth --remote`, `/GitAnalyze <branch> --lang English`, `/GitAnalyze --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitAnalyze $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. If none is listed but `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: report observations, but do not mutate branches, worktrees, refs, or history.
2. Execute `/GitAnalyze` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md`. Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default (applies even if the skill fails to load): read-only. `--remote` only permits refreshing remote-tracking refs; never mutate branches, worktrees, or history. If no target is given, ask for one. Reply language: Chinese unless `--lang` selects another one; this includes the final report, however long the run was.
