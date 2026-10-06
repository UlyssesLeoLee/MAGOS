---
description: 调查当前 Git 仓库整体状态（branch / worktree / HEAD / ahead-behind / dirty / 风险）
argument-hint: "[--remote] [--lang <language>] [--help]"
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. For an unknown option, explain the error, show this help, and stop.

## Inline help

Usage: `/GitRecon [--remote] [--lang <language>] [--help]`

- `--remote`: Refresh remote-tracking refs before classifying the repository. It does not change branches, worktrees, or commit history.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting the repository.
- Default: Read-only snapshot using existing local refs; no remote refresh.

Examples: `/GitRecon`, `/GitRecon --remote`, `/GitRecon --lang English`, `/GitRecon --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitRecon $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. If none is listed but `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: report observations, but do not mutate branches, worktrees, refs, or history.
2. Execute `/GitRecon` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md`. Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default (applies even if the skill fails to load): read-only. `--remote` only permits refreshing remote-tracking refs (e.g. `git fetch --prune`); never mutate branches, worktrees, or history. Reply language: Chinese unless `--lang` selects another one; this includes the final report, however long the run was.
