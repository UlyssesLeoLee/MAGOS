# GitConverge test design

`/GitConverge <branch> [--apply] [--discard-ignored]` merges every local branch's unique commits (`main` first) into
`<branch>`, then deletes the merged local branches and their clean worktrees so only `main` and `<branch>` remain. The
command is not code. It is a Markdown contract (`references/commands.md` section 6) that an AI host executes through
adapters (`commands/GitConverge.md`, `skills/git-converge/`). The tests therefore have to answer two different questions:

1. **Is the procedure sound on real Git?** (Does the sequence of Git commands the contract prescribes do what it claims,
   on every awkward repository shape?)
2. **Does an AI host that reads the contract actually follow it?**

## Test layers

| Layer | Script | What it proves | Needs a model |
|---|---|---|---|
| L0 headers | `cypher_header.py --check` | The Cypher block atop each script still matches the code | no |
| L1 Git probes | `git_behavior_probes.py` | Each Git behavior the contract relies on holds on the installed Git (15 assertions plus 1 recorded observation) | no |
| L2 source contracts | `run_claude_contracts.py` | The shipped files state every rule (18 cases, plus the aggregate cases in `tests/codex`) | no |
| L3 reference scenarios | `run_reference_cases.py` | A deterministic implementation of the contract reaches the right end state in 46 repository shapes | no |
| L4 mutation checks | `run_mutation_checks.py` | The scenarios notice when a rule is broken (27 mutations) | no |
| L5 policy unit tests | `test_command_policy.py` | The forbidden-command policy classifies commands correctly | no |
| L6 Claude runtime | `run_claude_cases.py` | The real Claude CLI, given `/GitConverge ...`, reaches the same end states without forbidden commands | yes |
| L7 Agent Plugins checks | `tests/codex/contracts/test_agent_plugin.py` | The checks behind the `package/agent-plugin` and `package/install-layout` cases (plugin manifest, Agent Skills frontmatter, git-clone layout) turn red for each planted defect | no |

L3 is an **executable reading of the contract** (`converge_ref.py`). It is not shipped. It exists so that every scenario
oracle is proven satisfiable, every rule has a fixture that exercises it, and L4 can measure whether the oracles have teeth.
Codex and Hermes runtime cases are out of scope here; `tests/codex` owns those hosts.

## Oracles

Three judges run on every case.

- **End-state oracle** (per scenario, `scenarios.py`): reads only Git state: refs, worktrees and their status, remote refs,
  HEAD, `MERGE_HEAD`, and watched files. The same oracle judges the reference executor and the AI host.
- **Shared invariants** (`scenarios.invariants`): appended to every scenario in both runners: `main` did not move, tags,
  the remote, and local remote-tracking refs are unchanged, and no merge is left in progress. A scenario oracle cannot
  forget a hard stop.
- **Command policy** (`command_policy.py`): judges the recorded `git` argument lists after normalizing options
  (`-Xtheirs`, `--strategy-option=theirs`, `-df` and `-ff` are recognized). It names the forbidden forms (`branch -D`,
  remote-tracking deletion, a repository-wide `worktree prune`, `worktree remove --force`, `switch -C`, `checkout`,
  pushes and fetches, `-X ours/theirs`, `--squash`, `--allow-unrelated-histories`, tag and config writes, `symbolic-ref`
  writes). In apply mode it is an allow-list: any other write outside the contract's forms (`switch`, `merge`,
  `worktree remove`, `branch -d`, upstream edits) is reported. In preview mode every command must be read-only.
  Some hard stops leave the end state unchanged (`branch -D` and `branch -d` delete the same branch), so only the command
  trace can see them. The mutation `force-delete-D` is killed by the policy alone.

The reference executor records its own commands (test hooks and validators run untraced). The Claude runtime records
them with `GIT_TRACE2_EVENT`, which logs every git process however it was started; Claude Code's own housekeeping calls
(fixed `-c protocol.ext.allow=never -c core.hooksPath=...` prefix) are dropped before the policy runs. A PATH shim was tried
first and failed: Git Bash puts `/mingw64/bin` ahead of it.

The runtime runner adds two transcript checks. The final report must name the words a scenario requires: every local
branch (for GitConverge, where the plan lives in the report), the exact branch name for `case-variant-target`, and the
worktree to run from for `target-checked-out-elsewhere`; gate refusals stop before a plan exists and are exempt from the
branch list. The reply must also be in the requested language: Chinese when `--lang` is absent (at least 20% Han and at
most 2% kana/Hangul letters, so Japanese or Korean does not pass), English for `--lang English` (at most 3% CJK); other
languages are not checked. A scenario marked `inspects=False` (an argument error) must run no git command at all. The plan is no longer required to appear before the first write; it is recorded first and reported.

## Result semantics

`PASS` and `FAIL` are judgments. `UNVERIFIED` means the case could not be judged: the CLI timed out, did not start,
produced no `result` event, ended with an error subtype (usage limit, authentication, budget), or the agent's transcript
contains no git command at all. Liveness is read from the transcript, never from the git trace, because the CLI's own
startup git calls would otherwise make every run look inspected. `run_claude_cases.py` exits 2 when any case is
UNVERIFIED, and `run_all.py` reports that layer as UNVERIFIED, not PASS. `SKIPPED` means the platform cannot build the fixture
(`worktree-remove-failure` needs Windows file locking). An `UNVERIFIED` or `SKIPPED` case is never counted as a pass.

## Scenario matrix

All scenarios run in disposable repositories under the system temp directory (`--fixture-root` shortens the path). Nothing
runs against the MAGOS checkout. Commits use a fixed author and date so SHAs, and therefore evidence, are reproducible.

| Scenario | Shape | Must hold afterwards |
|---|---|---|
| `happy-path` | main ahead, a contained branch, a 2-commit branch, a branch with a clean worktree | only `main` + target; `main` unmoved; 3 merge commits; worktree removed; remote refs untouched |
| `preview-readonly` | same | nothing changed; plan order, classes, final branches, removals |
| `ordering-and-containment` | source B contains source A; two equal-size sources | largest first, ties by name; the contained source needs no second merge |
| `conflict-stops` | two sources edit the same line | no `MERGE_HEAD`, clean tree, nothing deleted, never both conflicting sources merged |
| `conflict-predicted` | a source clashes with the target tip | `merge-tree` predicts it; the apply stops |
| `rerun-after-stop` | conflict, user drops the loser, rerun | rerun converges to `main` + target |
| `unrelated-history` | orphan `gh-pages` | orphan neither merged nor deleted; everything else converges |
| `dirty-source-worktree` | worktree with uncommitted + untracked files | branch and edits kept; committed content merged |
| `locked-source-worktree` | locked worktree | branch kept, still locked, content merged |
| `harness-owned-worktree` | worktree under an agent-harness root | kept, content merged (reference only: needs a known root) |
| `rebase-in-progress` | branch stopped mid-rebase in a worktree | stale tip not merged; branch and rebase kept |
| `ignored-files-kept` / `-discard` | clean worktree holding `.env` | kept by default; removed only with `--discard-ignored` |
| `ignored-overwrite-merge` | a source tracks `.env`, which is an ignored local file | stops before the merge; local file intact |
| `tag-shadow` | a tag named like a branch | the branch is merged and deleted; the tag stands |
| `case-variant-target`, `target-is-main`, `target-missing` | bad target argument | nothing changes, even with `--apply` |
| `invoking-detached`, `invoking-dirty` | unsafe starting worktree | nothing changes |
| `target-checked-out-elsewhere` | target held by another worktree | gate: run from that worktree; nothing changes |
| `run-from-target-worktree` | invoked from the worktree holding the target | works; main worktree untouched |
| `invoking-on-other-branch` | invoked while on another clean branch | switches to the target; old branch merged and deleted |
| `target-prunable-entry`, `main-prunable-entry` | target or `main` held by a missing-directory entry | gate; nothing changes |
| `upstream-behind` | pushed branch with an extra local commit | merged and deleted without `-D`; remote copy untouched |
| `detached-and-prunable` | detached worktree with a unique commit; branch worktree directory deleted | entry removed by path; detached entry and commit survive |
| `upstream-of-kept` | `main` tracks a local branch | that branch merged but kept |
| `submodule-worktree` | worktree with an initialized submodule | kept (Git refuses to remove it) |
| `target-tag-shadow` | a tag named like the target, pointing at a source's tip | the source is merged, not taken as contained |
| `ignored-overwrite-case` | source adds `.ENV`; local ignored `.env` (core.ignorecase) | stops; local file intact |
| `ignored-overwrite-dir-file`, `-file-dir` | source adds a file where an ignored directory is, or the reverse | stops; local data intact |
| `sequencer-in-progress` | cherry-pick sequence paused after a resolved step | branch neither merged nor deleted; sequencer kept |
| `skip-worktree-edits` | local edit to a skip-worktree file (status looks clean) | worktree and branch kept; edit intact |
| `claude-session-worktree` | worktree under `<repo>/.claude/worktrees/` | kept as active owner; content merged |
| `dependency-of-remaining-lane` | a dirty lane tracks a mergeable local branch | both kept; the lane's upstream still resolves |
| `main-in-progress` | the main worktree is mid-merge on `main` | no crash; `main` not merged; others converge |
| `worktree-appeared-after-preview` | a worktree is added for a previewed branch | branch merged but kept with its worktree (reference only) |
| `rerun-after-interrupted-apply` | apply stops on a conflict; the user drops the loser; rerun with the earlier plan | not stale; converges (reference only) |
| `preview-lang-english` | the happy-path repository, `--lang English` | read-only; the reply is English (Claude runtime only) |
| `recon-default-chinese`, `recon-lang-english`, `analyze-lang-english`, `recommend-goal-lang` | read-only runs of the other commands, with and without `--lang`, and `--lang` in the middle of GitRecommend's free-text goal | repository unchanged; the reply is in the right language (Claude runtime only) |
| `recon-lang-missing` | `/GitRecon --lang` with no value | Chinese error, no git command, repository unchanged (Claude runtime only) |
| `stale-preview` | a source moves after the preview | stops; nothing changes (reference only) |
| `appeared-after-preview` | a branch is created after the preview | left untouched (reference only) |
| `tip-moves-mid-run` | a tip moves between merge and delete | that branch kept with its new commit (reference only) |
| `validation-fails` | a post-merge check fails | merges kept, nothing deleted (reference only) |
| `worktree-remove-failure` | another process holds a worktree (Windows) | branch kept; partial removal reported (reference only) |

"Reference only" scenarios need the harness to inject an event (a hook, a validation result, a second invocation) that a
headless `claude -p` call cannot be given.

## Tuning loop

1. Run a layer; read every failure; decide whether the **contract**, the **reference**, or the **test** is wrong.
2. Fix that one thing; rerun the layer; rerun L4 to confirm the fix did not blunt an oracle.
3. Record the round in `TUNING.md` with the cause and the change.

A passing run right after a fix proves nothing about oracle strength, so L4 is part of every tuning round.

## Running

```powershell
python -X utf8 tests/claude/scripts/run_all.py                # every layer that needs no model
python -X utf8 tests/claude/scripts/run_all.py --runtime      # plus the core scenarios through the real Claude CLI
python -X utf8 tests/claude/scripts/run_claude_cases.py --case 'conflict-*'   # chosen runtime cases
```

Evidence: `results/git-probes/`, `results/contracts/`, `results/reference/<scenario>/`, `results/mutation/`,
`results/claude/{fixture-check,runtime}/<scenario>/` (prompt, final answer, git trace, snapshots, verdict; the raw transcript stays local), and
`results/summary.md`.

## Known gaps

- Codex and Hermes run only `git-converge/help` for GitConverge (`tests/codex`); behavior cases run on the Claude CLI.
- `ignore-lock-gate` is an expected surviving mutation: Git itself refuses to remove a locked worktree, so the end state is
  unchanged. The contract gate is defence in depth, tested at the source-contract layer only.
- `merge-tree` prediction is per source against the current target; a clash between two sources is found only at merge time.
- No baseline validation run; a failing check stops deletion but cannot tell a pre-existing failure from a new one.
- Submodule, rebase, sequencer, and partial-removal fixtures are Windows-verified only.
- Lane records (owner and dependency files) are not modelled by the fixtures; ownership and dependency evidence come from
  locks, harness roots, in-progress markers, and branch tracking only.
