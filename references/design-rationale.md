# Design Rationale

The main `SKILL.md` is intentionally policy-oriented rather than tutorial-oriented. Agents load it on activation; detailed edge cases live in references so ordinary tasks spend less context.

## Public patterns combined

1. **Isolation before implementation** — Superpowers' worktree guidance detects existing isolation first, prefers harness-native isolation, and establishes a clean baseline before implementation.
2. **Traceable task decomposition** — CCPM connects specification/task context to parallel work and durable handoff state rather than relying on conversation memory.
3. **Workspace/session isolation** — Claude Squad uses separate agent sessions plus Git worktrees so parallel agents do not share a writable checkout.
4. **Role separation** — Ruflo distinguishes coordination, coding, review, and testing roles; this skill keeps those responsibilities separable without depending on Ruflo itself.
5. **Evidence over claims** — repository state and executed checks are authoritative.
6. **Progressive disclosure** — Agent Skills supports a small `SKILL.md` plus on-demand `references/` resources.
7. **Skill pressure testing** — Superpowers' skill-authoring guidance treats process skills like code: pressure-test failure modes, then close loopholes.

## Additional safeguards introduced here

### Rewrite freeze for dependency sources

A private branch is not automatically safe to rebase once another lane is based on its commit IDs. The skill therefore separates **private** from **rewrite-safe** and freezes dependency-source history unless dependents are coordinated.

### Integration freshness gate

Review and integration are separate moments. A lane or target branch can change after approval. The skill invalidates stale approval rather than assuming the earlier review still applies.

### Serialized integration

Multiple approved lanes can race on a protected branch. A single integration writer or merge queue creates a deterministic order and forces later lanes to re-check freshness.

### Repository policy controls history representation

The orchestrator decides whether to accept a whole lane, a subset, or nothing. It does not globally impose fast-forward, merge-commit, or squash-merge style; that remains repository policy.

## Source references

- Superpowers: https://github.com/obra/superpowers
- CCPM: https://github.com/automazeio/ccpm
- Claude Squad: https://github.com/smtg-ai/claude-squad
- Ruflo: https://github.com/ruvnet/ruflo
- Agent Skills specification: https://agentskills.io/specification

## Proactive repository reconnaissance (v3.2)

Repository-specific Git advice is unsafe when based only on conversation assumptions. v3.2 adds a non-destructive reconnaissance mode that inventories worktrees, local branches, upstream tracking, dirtiness, ancestry, ahead/behind state, and overlap before recommending operations.

The survey uses stable Git plumbing/porcelain intended for machine consumption where practical (`git worktree list --porcelain`, `git for-each-ref`, `git rev-list --left-right --count`, and `git merge-base`). It deliberately separates local read-only observation from remote refresh: fetching changes remote-tracking refs and is therefore performed only when current remote truth materially affects the decision and the environment permits it.

The advice model distinguishes **observed**, **recorded**, **inferred**, and **unknown** facts so an agent does not invent branch ownership or semantic dependencies from topology alone.

## Branch strategy guidance

The skill used to handle branches only after work had started: lane planning, sync, integration, cleanup. It had no layer for the branching model itself, and a question such as "what branch strategy should we use?" matched neither the activation text nor any reference.

**Why the skill does not prescribe a model.** Gitflow, trunk-based, release-line, and per-owner staging layouts all work when the parallel-writer invariants hold. A skill that pushed one of them would override repository policy, the same overreach the merge-strategy rule avoids. `references/branch-strategy.md` therefore classifies what the repository actually does, tests it against a fit checklist, and keeps the smallest-change principle. It gives a default model only when none exists, and states that the default is the smallest model satisfying the invariants, not a preference.

**Why the trigger terms live in the description.** Before activation only the frontmatter `description` is loaded; the body and references are not. Branch-strategy phrasing, including 分支策略 and ブランチ戦略, has to be in the description to start the skill. The description is limited to 1024 characters (and `package/agent-plugin` checks it), so the symptom list was compressed to make room instead of moving the new terms into the body.

Some hosts show only a prefix. Hermes puts the first 57 characters of a description in its skill index (`SKILL_PROMPT_DESC_LIMIT = 60` in its `agent/skill_utils.py`), so there the new terms, like the older symptom triggers, never reach the model. Front-loading them would rewrite the opening that the plugin mutation tests anchor on (`ROOT_DESCRIPTION` in `tests/codex/contracts/test_agent_plugin.py`), and 57 characters cannot hold both the core multi-agent trigger and the new terms, so the limit is documented instead: on Hermes the branch-strategy request is reached by loading the skill by name or by `/git-recommend <goal>`, whose adapter reads `SKILL.md` and `reconnaissance.md`, and `reconnaissance.md` points to `branch-strategy.md`.

**Why generic concept questions stay out.** "Explain gitflow" has no repository state to inspect, so the skill adds nothing. Activation requires a request to choose, audit, or change the branching model of a specific repository, above all one that agents, worktrees, or several developers share (Mode A already counts "parallel coding agents or developers"). The description is deliberately the broadest statement of this boundary because it is all the router sees; a measured A/B over 18 prompts showed a solo greenfield "design a branching strategy" request now triggers it, which is accepted because the body then falls back to the default model after inspecting the repository. The negative case is in the description and in the pressure tests.

**Why the guidance is advisory.** Renaming or deleting branches is a ref rewrite for every dependent, and remote protection cannot be seen from local Git. Strategy advice stops at a report; deleting and merging reuse the explicit commands with their existing gates (routing in **Strategy Changes** in `branch-strategy.md`), so a strategy conversation cannot become a back door around them. None of the six commands renames a branch, so the guidance says so and leaves a rename as a manual step after dependents are coordinated, rather than implying a gated path that does not exist.

**Not changed.** The six command contracts, their adapters, and the Repository Snapshot output are unchanged. A branching-model line in the snapshot, and a `branch-strategy.md` entry in the `GitRecommend` adapter's reading list, are possible later additions that would change command contracts and host evidence.
