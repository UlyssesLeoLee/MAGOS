# Claude tests for `/GitConverge`

Test design, scripts, evidence, and the tuning log for the GitConverge command
(`commands/GitConverge.md`, `skills/git-converge/`, `references/commands.md` section 6).

| File | Purpose |
|---|---|
| [`test-design.md`](test-design.md) | What is tested, the seven test layers, the oracles, the scenario matrix, known gaps |
| [`review-findings.md`](review-findings.md) | The design review and the max-effort code review: every finding and what was done about it |
| [`TUNING.md`](TUNING.md) | Each tuning round: symptom, cause, what was changed, and the result |
| [`contracts/cases.json`](contracts/cases.json) | 18 source-contract cases for the shipped files |
| [`scripts/`](scripts) | Fixtures, probes, reference executor, scenarios, runners, mutation checks, policy |
| [`results/`](results) | Evidence from the latest runs (summary in `results/summary.md`) |

## Run

Everything that needs no model, in one command:

```powershell
python -X utf8 tests/claude/scripts/run_all.py
```

Add the real Claude CLI (uses model quota; each case is a separate `claude -p` call in a disposable repository):

```powershell
python -X utf8 tests/claude/scripts/run_all.py --runtime
python -X utf8 tests/claude/scripts/run_claude_cases.py --case 'happy-path' --model sonnet
```

Individual layers:

```powershell
python -X utf8 tests/claude/scripts/git_behavior_probes.py      # Git behaviors the contract relies on
python -X utf8 tests/claude/scripts/run_claude_contracts.py     # source contracts
python -X utf8 tests/claude/scripts/run_reference_cases.py      # reference executor, 50 scenarios
python -X utf8 tests/claude/scripts/run_mutation_checks.py      # do the scenarios notice broken rules?
python -X utf8 tests/claude/scripts/test_command_policy.py      # forbidden-command policy
python -X utf8 tests/claude/scripts/run_claude_cases.py --fixture-check --case '*'   # harness self-check, no model
python -X utf8 tests/claude/scripts/cypher_header.py            # refresh the Cypher headers (--check to verify)
```

`--fixture-root <short path>` keeps fixture paths short if Windows reports `Filename too long`.

## Safety

Every case builds its own repository under the system temp directory and deletes it afterwards. No script runs
GitConverge, `git branch -d`, `git worktree remove`, or a merge against this checkout or any linked worktree
(including the Codex worktree). The runtime harness installs the command into the fixture's own `.claude/` folder and hides it with
`.git/info/exclude`; it never writes to `~/.claude`.

The runtime harness restricts the agent to `Bash(git:*)`, `ls`, `cat`, `test`, `pwd`, `Read`, `Glob`, `Grep`, and `Skill`, loads only
project and local settings (none of the user's hooks), and caps spend per case.

## Reading a result

`PASS` and `FAIL` are judgments. `UNVERIFIED` (limit, authentication, timeout, or an agent that never inspected the repository)
and `SKIPPED` (platform) are never passes. The reference executor proves the procedure and the oracles; only `results/claude/runtime/`
shows what a real agent did.

Committed evidence is deterministic (fixed commit dates, fixture paths replaced by `<root>`), except `results/claude/runtime/`,
which records one real run per case. Its raw transcripts (`transcript.jsonl`) and `stderr.txt` stay local: they list the account's
connected tools and local paths. The committed `result.json` keeps the prompt, the final answer, the git commands, the
snapshots, and the verdict.
