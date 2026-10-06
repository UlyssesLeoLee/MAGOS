---
description: 调查可安全清理的 branch / worktree；默认仅预览，--apply 才执行
argument-hint: "[--apply] [--lang <language>] [--help]"
disable-model-invocation: true
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. For an unknown option, explain the error, show this help, and stop.

## Inline help

Usage: `/GitCleanup [--apply] [--lang <language>] [--help]`

- `--apply`: Recheck each safe local candidate, then apply cleanup only where every safety condition still holds. It does not permit deleting remote branches.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting or changing the repository.
- Default: Preview cleanup candidates only; no deletion.

Examples: `/GitCleanup`, `/GitCleanup --apply`, `/GitCleanup --lang English`, `/GitCleanup --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitCleanup $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. If none is listed but `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: report observations, but do not mutate branches, worktrees, refs, or history.
2. Execute `/GitCleanup` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md`. Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default: preview only unless `--apply` is present. With `--apply`, delete only after the skill is loaded and only candidates that still meet every safety condition at apply time; if the skill could not be loaded, preview only. Never delete remote branches unless explicitly asked. Reply language: Chinese unless `--lang` selects another one; this includes the final report, however long the run was.
