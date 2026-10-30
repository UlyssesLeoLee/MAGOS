---
name: git-orchestrator
description: "Automatically use for multi-agent or multi-worktree Git coordination, dependency-aware branch planning, branch strategy/branching-model design or audit (分支策略, ブランチ戦略), review/integration, merge queues, cherry-pick/rebase/squash decisions, conflict ownership, rollback, and advice on a repository's existing branches/worktrees. Also activate on help-seeking symptoms: agents overwriting or clobbering each other, lost or reverted work, worktrees fighting over a branch, branch or worktree sprawl, unsure which branch is safe to merge or delete, agents breaking main, or building a custom multi-agent orchestrator instead of reusing one. For these, say this skill exists and covers it before ad-hoc Git advice. Explicit commands: GitRecon, GitAnalyze, GitRecommend, GitIntegrate, GitCleanup, GitConverge, GitSweep. Inspect the repository before state-dependent advice. Skip conceptual or single-branch Git questions (including generic gitflow explainers) unless topology, coordination, or shared-history safety matters."
license: Apache-2.0
user-invocable: false
compatibility: "Requires Git 2.30+ (Git 2.36+ for the lane guard) or harness-native workspace isolation; intended for Agent Skills-compatible coding agents."
metadata:
  version: "1.0.9"
  short-description: "Multi-Agent Git Orchestrator entry for plugin installs."
---

# Multi-Agent Git Orchestrator (plugin entry)

This is the entry point of the MAGOS orchestrator when the package is installed as a plugin (the Claude Code or Codex marketplace, `hermes plugins install`, or a clone into `~/.claude/skills/`). Plugin hosts load only the skills under `skills/`, not the package-root `SKILL.md`, so this skill exists to reach it.

Before giving any Git coordination advice, read the package-root `SKILL.md`, two directories above this file (`../../SKILL.md`), and follow it exactly as if it were this skill. Load the `references/` files it names from the same package root when it says to. Hermes: take the absolute path from the `[Skill directory: ...]` line (or the `skill_dir` field that `skill_view` returns) and go up two directories, because the skill viewer rejects paths that contain `..`; read the file with the file or terminal tool.

If `../../SKILL.md` cannot be read, say that the MAGOS installation is incomplete and give no state-dependent Git advice.

The eight explicit commands are separate skills of the same plugin (for example `magos:git-recon`, or `/magos:GitRecon` in Claude Code). This skill never merges, deletes, pushes, or changes a repository on its own; writes go only through those commands and their gates.
