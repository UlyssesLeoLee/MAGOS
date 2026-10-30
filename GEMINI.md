# MAGOS — Gemini CLI extension context

MAGOS is a Git and multi-agent worktree coordination skill. This extension is an
adapter for the existing MAGOS repository, **not** a second implementation.

## Canonical sources

The plugin's existing `skills/git-orchestrator/SKILL.md` points to the
package-root `SKILL.md` and `references/commands.md`, which are the authoritative
contracts. Activate `git-orchestrator` with Gemini CLI's `activate_skill` tool
before executing an actual MAGOS operation; then follow the root skill and its
referenced material, including verification gates, read-only defaults, version
requirements, and tabular output. The eight `skills/git-*/SKILL.md` files are
additional adapters; do not confuse them with the orchestrator entry skill.

Each `/Git*` TOML custom command is intended for **explicit user invocation**.
Never infer that discussing a Git cleanup, integration, sweep, or lane plan is
permission to invoke `/GitIntegrate`, `/GitCleanup --apply`, `/GitConverge
--apply`, `/GitSweep --apply`, `/GitPlan --apply`, or `/GitPlan --release`.
For normal related questions, activate `git-orchestrator` and advise/read only.

- `/GitRecon`, `/GitAnalyze` and `/GitRecommend` are read-only except an
  explicitly requested `--remote` may refresh remote tracking refs.
- `/GitCleanup`, `/GitConverge`, `/GitSweep`, `/GitPlan` default to preview;
  write only with the exact flags/actions specified in the source contracts.
- `/GitIntegrate` is explicitly write-intent on invocation, with mandatory
  dependency, review, freshness, protected-branch and repository-policy gates.
- `/GitSweep --push` is distinct from `--apply` and may publish a branch.
- `/GitPlan --release` writes state; it is not a preview.
- `--help` must be handled from inline usage before repository inspections,
  skill activation, file reads, or Git commands.
- Output language defaults to 简体中文; `--lang` controls response language only.
  Preserve literal Git commands, paths, branch names, flags and status codes.
- Stop on stale revisions, missing dependencies, conflicts, uncertain state,
  unsafe worktrees, or failed checks; never fabricate success.
- A Gemini extension installation does **not** automatically install or activate
  the optional MAGOS Python lane guard. This package is *not* a drop-in port
  of Claude's PreToolUse hook. Its Gemini policies only request approvals for
  selected risky shell actions and are NOT a complete Git or worktree guard.
- Never read credential stores or transmit telemetry. Network Git operations
  require explicit authorization as defined in the source contract.

Do not change Claude Code, Codex or Hermes manifests or hook files.
