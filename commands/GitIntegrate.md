---
description: 安全集成指定 Agent Lane 或分支（先过 review / dependency / freshness 门禁）
argument-hint: "<lane|branch> [--strategy auto|merge|squash|cherry-pick] [--lang <language>] [--help]"
disable-model-invocation: true
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. If the target is missing, or `--strategy` has a missing or unsupported value, show this help and ask for the required value before proceeding. For an unknown option, explain the error, show this help, and stop.

## Inline help

Usage: `/GitIntegrate <lane-or-branch> [--strategy auto|merge|squash|cherry-pick] [--lang <language>] [--help]`

- `<lane-or-branch>`: Required source lane or branch to integrate.
- `--strategy <value>`: Optional integration strategy. `auto` follows repository policy and reviewed acceptance shape (default); `merge` preserves accepted lane commits; `squash` delivers the lane as one commit when allowed; `cherry-pick` uses only accepted, dependency-safe commits.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting or changing the repository.
- Default: Strategy `auto`; integration proceeds only after review, dependency, freshness, protection, and repository-policy gates pass.

Examples: `/GitIntegrate agent/auth`, `/GitIntegrate agent/auth --strategy squash`, `/GitIntegrate <lane-or-branch> --lang English`, `/GitIntegrate --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitIntegrate $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. If none is listed but `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: report observations, but do not mutate branches, worktrees, refs, or history.
2. Execute `/GitIntegrate` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md`. Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default: write intent, but only after the skill is loaded and review, dependency, freshness, protected-branch, and repository-policy gates pass. If the skill could not be loaded, do not integrate; report what is missing. If any gate fails, stop and report the blocker. Never force-push or rewrite shared history. If no target is given, ask for one. Reply language: Chinese unless `--lang` selects another one; this includes the final report, however long the run was.
