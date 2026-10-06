# GitConverge tuning log

Every round: what the tests showed, which of the three things was wrong (the **contract**, the **reference executor**, or the
**test itself**), what was changed, and what the rerun showed. Environment: Git 2.41.0.windows.1, Windows 11, Python 3.13,
Claude Code 2.1.284 with `claude-sonnet-5-5` for the runtime layer.

## Round 1: Git behavior probes

| | |
|---|---|
| Symptom | 12/12 probes passed, but the `ignored_overwrite` probe recorded `overlap_before_merge: []` |
| Cause | **Test bug.** The overlap between "paths the source changes" and "ignored local files" was computed after the merge, when `.env` had become tracked |
| Change | Compute the overlap before the merge and assert it equals `[".env"]` |
| Result | The contract's detection formula (`diff --name-only <merge-base> <sha>` ∩ `ls-files -o -i --exclude-standard`) is now itself verified |

Two probes also confirmed platform facts worth keeping: `refs/heads/Target` resolves on this NTFS checkout while a differently
cased name is not in the exact `for-each-ref` listing (so the exact-match rule is needed), and removing the worktree you stand in
exits 255 after Git has already dropped its metadata (so a non-zero `worktree remove` must keep the branch).

## Round 2: reference scenarios, first run (29/31)

| Failure | Cause | Change |
|---|---|---|
| `upstream-behind`: `branch -d` refused | **Reference bug.** It read the upstream with `rev-parse refs/heads/x@{upstream}`, which Git rejects ("no such branch") | Contract now records the upstream with `git for-each-ref --format='%(upstream)\|%(upstream:short)'`, which works with full refnames and is empty when there is none. Probe `upstream_read` locks this in, including restoring with `--set-upstream-to=<short>` |
| `conflict-stops`: expected `merge-tree` to predict the x1/x2 clash | **Contract wording and test both overstated.** `merge-tree` tests a source against the current target tip only, so it cannot see a clash between two sources | Contract: "a hint only; it cannot see a clash between two sources". Test now asserts that blind spot explicitly. New scenario `conflict-predicted` covers a source that clashes with the target tip itself |

Result: 32/32.

## Round 3: do the tests have teeth? (mutation checks)

All-green runs say nothing about whether the oracles would catch a wrong implementation, so 20 rules were broken on purpose.

| Finding | Cause | Change |
|---|---|---|
| `branch -D` and `branch -d` leave identical repositories | **Test gap.** State oracles cannot see several hard stops | Added the command trace and `command_policy.py`: forbidden commands in any mode, read-only commands in preview. `force-delete-D` is now killed by the policy alone |
| 6 mutations "killed" only because an oracle crashed (`KeyError: 'main'` after main was deleted, `None["code"]` after a run that should have stopped) | **Test bug.** A crash is not a diagnosis | Oracles read with `.get()`; `stop_code()` tolerates runs that did not stop |
| `no-unrelated-check` died with a Git usage error, not a scenario failure | **Mutation was unrealistic** | The fake `merge-base` now returns a real ref so the merge itself fails |

Result: 19/20 killed. The survivor, `ignore-lock-gate`, is expected: Git refuses to remove a locked worktree, so the end state
does not change. That gate is defence in depth and is checked at the source-contract layer.

## Round 4: the real Claude CLI

First run of `/GitConverge agent/release` through `claude -p` in a disposable repository: the agent loaded the skill, read
section 6, inspected, and produced a correct plan (17 turns, $0.47). Infrastructure defects found on the way:

| Symptom | Cause | Change |
|---|---|---|
| The git trace held only 6 calls; none were the agent's | **Harness bug.** A PATH shim is bypassed because Git Bash's `/etc/profile` puts `/mingw64/bin` first | Replaced the shim with `GIT_TRACE2_EVENT`, which logs every git process however it is launched (25 calls in the same case) |
| Policy flagged Claude Code's own `git config user.name` as a config write | **Policy bug.** A single-key `config` is a read | `config <key>` with no value and no write flag is read-only |
| Policy flagged `git --exec-path` | **Policy bug.** The parser treated `--exec-path` as an option to skip | Query globals (`--exec-path`, `--version`, ...) are subcommands; two-token globals (`--git-dir x`) are skipped properly |
| `fixture-check` failed `dirty-source-worktree` | **Test bug.** That fixture is dirty on purpose | The check now asserts only that `.claude` appears in no worktree status |
| `echo git is great` parsed as a git call | **Parser bug** | A git call must be in command position (after assignments, `do`/`then`, and wrappers such as `rtk`) |

Core scenarios on the real CLI, before any wording change: **8/8 PASS** (~$2 total, 5 to 34 turns each). The agent rejected
`Agent/Release` with the exact name suggested, stopped before an ignored-file overwrite, left the orphan `gh-pages` alone, kept a dirty
worktree's branch, merged `feat` rather than the same-named tag, and aborted a conflicting merge without deleting anything.

## Round 5: something the end state cannot show

Reading the transcripts of the apply runs showed that the agent surveyed silently and **merged after only a status line**
(0 to 199 characters before the first write), although the contract says `--apply` acts on "the plan printed by that run", which is
the user's acceptance. Every state oracle passed because the final repositories were right.

| | |
|---|---|
| Measure | New check `the plan is printed before the first write`: at least 300 characters of assistant text, naming every local branch, before the first git call that can change the repository (found by parsing each Bash command with the policy classifier) |
| Baseline | 0 of 6 apply runs that wrote anything complied |
| Change | Rounds 7 and 8 |

## Round 6: max-effort code review of the implementation

Ten finder angles, one verifier vote per candidate, and a gap sweep produced 48 confirmed or plausible findings. The 15 most
severe were fixed. Every row of `review-findings.md` names the test that now catches a regression. The fixes changed all
three layers:

| Layer | Changes |
|---|---|
| Contract (section 6) | full refnames or SHAs in every revision argument; two-axis classification with explicit precedence; `sequencer/` and skip-worktree/assume-unchanged in "in progress" and "clean"; `<repo>/.claude/worktrees/` as a harness root; the unknown-owner exception made explicit; dependency fixpoint over every remaining branch; target movement from an interrupted apply is not stale; ignored-file overlap with prefix and case rules; never push |
| Reference executor | same rules; no crash when `main` is mid-merge; worktrees that appear after the preview keep their branch; hooks run untraced; fewer git processes |
| Harness | shared invariants on every scenario; liveness from the transcript, not the git trace; result event checked; report words; policy option normalization and an apply-mode allow-list; strict `is_ancestor`; exit 2 for UNVERIFIED; `claude` resolved outside PATH |

New probes (`sequencer_paused`, `skip_worktree_hidden`, `target_tag_shadow`) confirm the Git facts behind the new rules.
Eleven new scenarios and seven new mutations cover them.

| Measure | Result |
|---|---|
| Reference scenarios | 45/45 |
| Mutations | 25/27 at first. `no-ignored-overlap-check` survived because the executor now lists ignored entries with `--directory` and the mutation still blanked the old call. The mutation was retargeted at `ignored_overlap` and is killed again. `ignore-lock-gate` is the expected survivor. |
| Contracts | 17/17 GitConverge, 21/21 codex |

## Round 7: real CLI after the review fixes

Six cases on the real CLI (`claude-sonnet-5-5`). The first attempt reported all six as UNVERIFIED, "could not start the CLI":
the resumed session's PATH no longer held `~/.local/bin`. The runner now resolves the CLI from `--claude-bin`, `$CLAUDE_BIN`,
PATH, then `~/.local/bin`. The old runner would have crashed on this; the new one labelled it correctly.

| Case | End state, invariants, policy | Plan printed before the first write |
|---|---|---|
| `rebase-in-progress` | PASS (it failed on the real CLI in round 4) | FAIL: printed text did not name `agent/ok` or `agent/release` |
| `sequencer-in-progress` | PASS | FAIL: 67 characters |
| `claude-session-worktree` | PASS | FAIL: 110 characters |
| `target-tag-shadow` | PASS | FAIL: 146 characters |
| `happy-path` | PASS | FAIL: 146 characters ("...before printing the plan", then the merge) |
| `preview-readonly` | PASS, report names every branch | n/a |

The contract fix for detached in-progress worktrees ("check every worktree, including detached ones") worked: the agent now
says `agent/topic` is being rebased in `wt-topic`, so it is `BLOCKED_IN_PROGRESS`. Two other findings:

- **Test bug.** `git patch-id` was not in the read-only set, so the plan check took it for the first write. Added, along
  with `check-mailmap`, `verify-commit`, and `verify-tag`.
- **Contract wording.** Agents read "print the whole plan" as satisfied by a status line. Section 6 step 1 and both adapters
  now list what the plan must contain and say that a one-line status update is not the plan. The Claude adapter, which the
  agent reads first, puts it ahead of the safety rules.


## Round 8: does stronger wording make the agent print the plan first?

Four cases were rerun on the real CLI after the round-7 wording change.

| Case | End state, invariants, policy | Text before the first write |
|---|---|---|
| `happy-path` | PASS | 152 characters: "... checking the `wt-b` worktree state before printing the plan", then the merges |
| `rebase-in-progress` | PASS | 296 characters; it again correctly blocks `agent/topic` as mid-rebase |
| `sequencer-in-progress` | PASS | 264 characters; it notices `sequencer/` and blocks the branch |
| `claude-session-worktree` | PASS | 88 characters |

**Result: no change.** The agent says it will print the plan, then issues the merge in its next tool call. It reports the
full plan only in its final answer. Two rounds of tighter wording have not moved this, while every safety property holds.

**Decision (the user chose option 2).** The plan is recorded before the first write and appears in the run's final report; it
no longer has to be printed before the first merge. The acceptance is of the tips in that report. Changes:

- Section 6 step 1 says "record the plan"; step 7 puts "the plan it acted on" first in the report; the acceptance rule in
  section 6 and `SKILL.md` says "records and reports".
- Both adapters say "record the full plan first and include it in the final report".
- The harness drops the plan-before-write check. Every runtime case now checks that the final report names every local
  branch, which is where the plan lives. `command_policy.writes()` and its tests were removed with it.

`results/claude/runtime/` holds the latest run of each case. Cases last run in rounds 4–5 (for example `conflict-stops`,
`unrelated-history`, `dirty-source-worktree`) predate the review fixes. Cases rerun in rounds 7–8 use the current contract.

## Round 9: the `--lang <language>` option on the real CLI

The user asked for an optional `--lang <language>` on every command: it sets the reply language, Chinese when absent. The
contract, all six Claude wrappers, all six Codex/Hermes adapters, `SKILL.md`, both READMEs, and the pressure tests were
updated; a contract case pins it for every command. The runtime runner gained a language check (at least 20% Han and at
most 2% kana/Hangul for Chinese, at most 3% CJK for English) and read-only scenarios for GitRecon, GitAnalyze, and
GitRecommend, including `--lang` written in the middle of GitRecommend's free-text goal (`recommend-goal-lang`) and a
`--lang` with no value (`recon-lang-missing`, which must answer in Chinese without running any git command).

| Attempt | Result |
|---|---|
| First batch of 9 cases | All UNVERIFIED: the CLI had hit a usage limit. The runner labelled them correctly; none counted as a pass |
| After the limit reset: `--lang English` | 4/4 replied in English (`recon`, `analyze`, `recommend` with `--lang` inside the goal, `preview`) |
| After the limit reset: default Chinese | 3 of 5 replied in Chinese. The two long `--apply` runs (`happy-path`, `conflict-stops`) and `tag-shadow` ended their report in English |
| Fix 1: put the language rule last in each wrapper, and in the contract's report step | `happy-path` switched to Chinese; `conflict-stops` and `tag-shadow` still English (1 of 3) |
| Fix 2: add an explicit step "before you write the final report, check the reply language again" to every wrapper, and name headings and tables in the contract | `conflict-stops`, `tag-shadow`, and `unrelated-history`: 3 of 3 in Chinese |
| Confirmation batch of 8 (`happy-path`, `dirty-source-worktree`, `ignored-overwrite-merge`, `case-variant-target`, `preview-readonly`, `recon-default-chinese`, `preview-lang-english`, `analyze-lang-english`) | 8/8 PASS; Chinese replies were 37% to 52% CJK, English replies 0% |

**Cause of the drift.** A rule stated once near the top is forgotten by the end of a long, tool-heavy run, and the tool output
and the contract are English. A checkpoint right before the report fixes it. The samples are small and the behavior is
statistical, so the runtime check stays in the suite; a regression would show up there.

**Known limit.** Codex and Hermes show a one-line description with a character cap (64 for Codex, 77 for Hermes). `--lang` is
in their usage lines and `--help`, not in that one-liner. The language check only tells Chinese and English apart; other
languages are not verified.

