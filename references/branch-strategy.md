# Branch Strategy

Load this reference when the user asks to choose, audit, explain, or change the branching model of the **current repository**: how branches relate, which are long-lived, how lanes are named and retired, how release and hotfix work flows, and what should be protected.

Pure concept questions ("explain gitflow") do not need it. Execution (renaming, deleting, merging, collapsing branches) is never done from here; see **Strategy Changes**.

## Principle

**Observe the model the repository follows, judge it against the parallel-writer invariants, propose the smallest change, and stop at advice.**

- The repository's existing model and policy are authoritative. This reference never replaces a working model with a preferred one. It supplies a vocabulary, a fit checklist, and a default for repositories that have no model.
- The orchestrator decides what is accepted; repository policy decides how branches and history are shaped. This is the same split as the merge-strategy rule in `decision-matrix.md`.
- Apply the confidence discipline from `reconnaissance.md`: **observed**, **recorded**, **inferred**, **unknown**. A role read from a branch name is inferred.

## Observe the Existing Model

Start from the Quick Scan in `reconnaissance.md`, then add:

```text
git for-each-ref --format="%(refname)%09%(objectname:short)%09%(*objectname:short)%09%(upstream:short)%09%(symref)" refs/heads refs/remotes refs/tags
git log --first-parent --merges --format="%h %p %s" -n 30 <candidate>
git tag --list --sort=-creatordate
```

`%(*objectname:short)` is the commit an annotated tag points to (empty for lightweight tags and branches); compare that, not the tag object, with a branch tip. Run the `git log` line once per candidate integration branch: it needs a candidate as input and cannot find the target by itself. It lists merge commits only, so under squash, rebase, or fast-forward integration it is empty, and an empty result is "no evidence", not proof that the branch is not an integration branch. Lane merges and back-merges of the integration branch both appear; read the parents (`%p`) and subjects to tell them apart.

Policy clues, in order of strength: files that state a branching policy (`CONTRIBUTING.md`, `AGENTS.md`, `CLAUDE.md`, a docs page on releases), CI trigger filters (`on: push: branches:`), CODEOWNERS and merge-queue configuration, the remote default branch, then branch and tag naming habits (corroboration only; see **Naming**).

`refs/remotes/origin/HEAD` is written at clone time and can be missing or stale, so treat it as recorded, not observed. `git ls-remote --symref origin HEAD` reads the remote's current default but needs the network, so it falls under the remote-freshness rule in `SKILL.md`. Without a fresh read, state the integration target at lower confidence.

Remote branch-protection settings are **not visible from local Git**. Report them as `unknown` unless the user states them or an authorized API read shows them. Never present a protection rule as fact from local refs.

### Branch roles

Assign each relevant branch one role, with the evidence behind it:

| Role | Typical evidence | Notes |
|---|---|---|
| INTEGRATION | remote default branch (recorded, see above); the branch that receives lane merges in `--first-parent` history; named in policy or CI filters | The branch workers must not write directly (Invariant 2). Not necessarily `main`. |
| LANE | one task, recorded owner and base, cut from its integration target (usually the integration branch), one writable worktree | Short-lived by design. One writable worktree. |
| STAGING | long-lived, not the default branch, periodically merged into or from the integration branch (for example one `develop_<host>` per agent host; a long-lived `develop` that lanes are cut from is INTEGRATION, not STAGING) | Needs a stated purpose, one owner, and a hub-and-spoke flow. |
| RELEASE | long-lived line for a shipped version, matching tags | Receives fixes by backport. History is never rewritten. In a gitflow-style repository `main` plays this role but receives release and hotfix merges instead of backports. |
| ARCHIVE | kept for reference on purpose, and that intent is recorded (a policy file, the user, or a lane record) together with no active owner or dependent lane; without such a record the branch is UNKNOWN_ROLE | Never deleted from here. Offer it to `GitCleanup` only when it is fully integrated and the user has decided it is no longer needed, including removing any policy entry that keeps it (`GitCleanup` never touches a branch documented as long-lived). If it holds unique or unintegrated work it stays. |
| UNKNOWN_ROLE | evidence does not decide | Say so. Do not guess from the name. |

**Hub-and-spoke flow:** the integration branch is the hub. A STAGING branch may merge into the hub and may receive the hub by merge; it never merges into or from another STAGING branch. Merging the hub into a staging branch to sync it is normal and is not a finding.

### Model classification

Describe the model the evidence supports. Use `mixed` or `unclassified` rather than forcing a fit.

| Model | Observed pattern | What it means for parallel agents |
|---|---|---|
| Trunk-based | one long-lived branch; the rest short-lived lanes, either ahead of it or already integrated | Best fit. Keep lanes short and integration serialized. |
| Release-line | trunk plus long-lived `release/*` (or version-named) branches with matching tags | Sound if fixes are traceable to a trunk commit. Needs a backport rule. |
| Gitflow-style | long-lived `develop` plus `main`, with feature, release, and hotfix branches | Workable. The integration target for lanes is `develop`, so never assume `main`; `main` carries releases. Two long-lived branches double the freshness checks. |
| Per-owner staging | several long-lived non-default branches (per agent host or per person), each ahead of trunk, merged on a cadence | Acceptable only with one owner per branch and a hub-and-spoke flow. Otherwise they drift and criss-cross. |
| Mixed / unclassified | more than one pattern, or no pattern | Report the conflicting evidence. Do not choose for the user. |

## Fit Checklist for Parallel Agents

Judge the observed model against these. Each failed item is a finding.

1. Exactly one integration branch, known with stated confidence, and every lane has exactly one recorded integration target: the integration branch, its owner's STAGING branch in a per-owner staging model, or, for a hotfix lane, the release line it fixes (see **Release, Hotfix, and Backport**).
2. No worker writes the integration branch. Workers change only their lane.
3. Every lane has one write owner and one writable worktree, and the owner is recorded, not inferred.
4. Dependency edges between lanes are recorded; a lane that another active lane is based on is rewrite-frozen.
5. Each STAGING branch has a stated purpose, one owner, and a hub-and-spoke flow.
6. No two branches carry the same logical work without an explicit reason.
7. Integrated lanes are retired. A growing count of fully integrated branches is hygiene debt.
8. Branch names cannot collide (see **Naming**).
9. Every release line has a rule for how fixes reach it (backport, or the model's own release and hotfix merges).
10. The integration branch has protection that matches the model, or its state is reported as `unknown`.

Label findings **BLOCKER** (a rule above is violated and parallel work can corrupt state, for example two writers on one branch), **RISK** (works today but fails under load or turnover), or **HYGIENE** (cost without danger).

## Default Model When None Exists

Use this only when the repository has no discernible model and the user wants one:

- one protected integration branch;
- short-lived lanes, one branch and one worktree each, cut from the integration branch's current tip (or from a dependency lane's tip, with the edge recorded);
- every lane ends in one of two ways: integrated through the gates in `SKILL.md`, or retired;
- long-lived branches are added only for a stated need (a supported release line, a verification gate that must run apart from trunk), each with one owner and a hub-and-spoke flow;
- merge, squash, or fast-forward follows repository policy.

This default is not a preference for trunk-based development over other models; it is the smallest model that satisfies the invariants. If the repository already works in another model, keep it and fix only the failed checklist items.

## Lane Lifecycle and Lifetime

- **Create** from the current tip of the lane's integration target (usually the integration branch; a hotfix lane: the release line it fixes), after the Preflight in `SKILL.md`. Record base branch and base SHA.
- **Stack** (a lane based on another lane) only when the dependency is real. Record the edge. Keep chains short; every extra level multiplies the rewrite-freeze and retarget cost.
- **Staleness signals:** the behind count against the target keeps growing, newly integrated lanes touch the same files (overlap hotspots), or the base is several integrations old. Age alone is not a signal.
- **When a lane drifts:** sync by rewrite safety (`SKILL.md` section 6). When its commits form independent reviewable groups, split it into separate lanes rather than carrying one large lane.
- **Retire** after integration, once no active lane depends on it. Hand the deletion to `GitCleanup`.

## Release, Hotfix, and Backport

- **Fix on the integration target first** when the bug exists there and the repository's own hotfix rule does not say otherwise, then bring the fix to each release line by cherry-pick, applying the Cherry-Pick Safety Test in `decision-matrix.md`. Use `git cherry-pick -x` so each release commit names its trunk origin.
- **Fix that exists only on a release line** (an emergency fix made there first, or a bug the integration target never had): forward-port it to the integration target before the next release is cut from that target, and in any case before the release line is retired; record the pair. Do not leave a fix that exists only on a release branch.
- **Hotfix cut:** branch from the release tag or line tip that shipped, not from a trunk that has moved on. A gitflow-style repository merges the hotfix into both its release branch and `develop`.
- **A failing shared change** is reverted, not reset. Release-line and integration history is not rewritten.
- A release line with no backport rule is a RISK finding.

## Protection

Recommend, for the integration branch and each release line: changes arrive through review or the merge queue, required checks must pass, force-push and deletion are blocked. Lane branches stay unprotected so the owner can sync them, and force-push on a lane is acceptable only while it is rewrite-safe.

These are recommendations for a person to apply in the hosting settings. This skill does not change remote settings and does not claim a setting exists without evidence. Whether history is linear is repository policy, not a requirement of this skill.

## Naming

- Follow the repository's existing convention. When there is none, use `agent/<task-id>-<short-name>`; add an owner or host segment only if several hosts share lanes, and keep the segment depth fixed.
- A name must pass `git check-ref-format --branch`; that checks syntax only. On Windows also avoid reserved device names (`aux`, `con`, `nul`, `prn`, `com1`..`com9`, `lpt1`..`lpt9`, also with an extension such as `con.tmp`) as any path component: they pass the syntax check but cannot be created.
- **Prefix clash:** a branch `agent` blocks `agent/x`, and `agent/x` blocks `agent/x/y`. Git refuses the clash only among local branches: a name that exists only on the remote is accepted locally whether or not it has been fetched (remote-tracking refs live under `refs/remotes/`), and the push is rejected later. Check local branches and remote-tracking refs, and, when remote freshness matters and a fetch is authorized, the remote (`git ls-remote --heads origin`), before proposing a scheme.
- **Case collision:** names that differ only by case collide on case-insensitive filesystems (the Windows and macOS defaults). Compare lowercased names for duplicates across the same sets and avoid them.
- **Tag shadow:** do not reuse a tag name as a branch name; `<name>` becomes ambiguous.
- A name alone never establishes role, owner, or status; it may corroborate refs, tags, merge history, and recorded metadata. `agent/old-fix` may be a live dependency source, and `release/1.0` may be an abandoned experiment.

## Strategy Changes

Advice on a strategy change is advisory. In order:

1. **Snapshot** the current state (a fresh reconnaissance).
2. **Classify** the model and list the failed checklist items.
3. **Choose the smallest change** that fixes them. Prefer retiring and tightening over inventing new long-lived branches.
4. **Sequence:** stop starting lanes on the old layout; integrate or park in-flight lanes; retarget dependents; only then rename or retire branches.
5. **Re-snapshot** after each step.

Renaming or moving a published branch is a rewrite of its ref name for every dependent. Local `git branch -m` renames the local ref and its `branch.<name>` config, and recent Git versions also repoint HEAD in every worktree that has the branch checked out. The upstream setting still names the old remote branch, so a plain `git push` fails under `push.default=simple`; the remote branch, CI filters, and other lanes' recorded base do not change. Treat it like rewriting dependency-source history: coordinate every dependent first.

This paragraph is the single source for which command executes what; other files point here. No command renames or moves a branch; a rename is a manual step for the user, after the coordination above and a fresh snapshot. Deleting and merging go through the explicit commands and keep their gates: `GitIntegrate` brings a specific lane or branch into the integration target; `GitCleanup` retires branches and worktrees that are already integrated and not documented as long-lived; `GitConverge <branch>` is a whole-repository option that tries to merge every other local branch (`main` included as a source) into one non-`main` target and then keep only `main` and that target; branches its gates block (unrelated history, in progress, active owner, dirty or locked worktrees) are kept and reported, and a conflict stops the run, so the two-branch result is not guaranteed. Offer it only when that result is what the user wants. A request to "apply the new strategy" does not authorize skipping a gate or touching `main`.

## Strategy Report Format

```text
Branching model (observed)
- integration target: <branch@sha | uncertain> (confidence: high | medium | low)
- model: trunk-based | release-line | gitflow-style | per-owner staging | mixed | unclassified
- evidence: <refs, tags, policy files, CI filters>
- remote protection: unknown (not visible from local Git) | <stated by user or API>

Fit for parallel agents
1. [BLOCKER|RISK|HYGIENE] <finding> -> <evidence>

Recommendations (smallest change first)
1. <operation or policy change> -> <evidence, condition, who applies it>

Unknowns
- <what could not be observed and what would settle it>
```

Under an explicit `/GitRecommend`, the command's own Output block in `commands.md` applies and this report supplies its content: Branching model becomes Observed facts, Fit findings become Top risks, Recommendations become Recommended next actions (ordered by risk and dependency first, then smallest change) with Why, and Unknowns become Blocked/unknown items.

## Anti-patterns

| Anti-pattern | Why it fails | Instead |
|---|---|---|
| A shared long-lived dev branch with several writers | breaks one-owner-per-lane; races and clobbering | one owner per branch, or lanes integrated through the queue |
| Per-agent long-lived branches that merge into each other both ways | criss-cross merges, unclear source of truth | hub-and-spoke flow: merge into the integration branch, sync it back by merge, never peer to peer |
| Workers committing straight to the integration branch | bypasses review and the freshness gate | lane, then the integration gates |
| A lane based on another unpublished lane with no recorded edge | a rebase of the base silently breaks the dependent | record the edge; rewrite-freeze the base |
| Lanes that never integrate or retire | sprawl; stale approvals and duplicate work | integrate-or-retire; hand cleanup to `GitCleanup` |
| Deleting or renaming branches to "clean up the strategy" during advice | destroys unique work and breaks dependents | advise only; delete and merge through the gated commands, rename manually after coordination |
| Reading role or ownership from a branch name | names are conventions, not facts | classify from refs and recorded metadata |
