# Test Design: `scripts/magos_guard.py`

Source: `scripts/magos_guard.py`

Source-SHA256: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Test Strategy

All tests live under `tests/codex/guard/` and run with `pytest` in the lane worktree (runtime host cases stay in the
separate project test worktree described in `AGENTS.md`). Three levels:

1. **Pure unit tests** import `scripts/magos_guard.py` as a module: manifest parsing, normalisation, the glob-intersection
   dynamic programme (checked against a brute-force oracle that enumerates a universe of candidate paths), the decision
   table, message rendering in both languages, the command lexer and detector.
2. **Real-Git integration tests** build throw-away repositories in `tmp_path` with real linked worktrees (committed-ahead
   branch, dirty worktree, untracked file, rename, delete, merge or rebase in progress, locked and prunable worktree,
   remote-tracking branch ahead of the target, case collision, unborn repository, detached HEAD) and drive the CLI in
   process (`main(argv)`) and as a subprocess. Git runs with an isolated `HOME`, `GIT_CONFIG_GLOBAL` and
   `GIT_CONFIG_NOSYSTEM`.
3. **Host-protocol and process tests** feed Claude, Codex and Hermes PreToolUse payloads (including PowerShell BOM and
   CRLF stdin) to `hook`, run the embedded `HOOK_SH` under Git's `sh`, run `run-guard.cmd` through cmd.exe and `sh`, and
   run two concurrent planners in separate processes.

The frozen detector corpus (`tests/codex/guard/data/corpus.jsonl`, 150 or more labelled command strings) is replayed with
precision and recall floors; every row is replayed again against an armed repository with the host hook disabled to prove
the git layer catches what the lexer misses. Coverage is measured with line coverage for `scripts/magos_guard.py` and for
every tracked source of the project (`__init__.py`, `scripts/sync_hosts.py`), each strictly above 90 percent; the two
older files are exercised in process by `test_project_sources.py`.

## Test Cases

| Case ID | Input / Setup | Expected Outcome | Test Location |
| --- | --- | --- | --- |
| TC-001 | Manifest entries `src/a/`, `src\a\x.py`, `./src//a`, `Src/A`, NFD and NFC spellings | Normalised to one canonical, case-folded NFC form; directory entries also match everything below | tests/codex/guard/test_manifest.py::test_normalisation |
| TC-002 | Entries that are empty, start with `:` or `!`, are absolute (`/x`, `C:x`, UNC), contain `..`, `.git`, `**` inside a segment, match everything (`**`, `*/*`), or exceed 200 entries or 1024 characters | Exit 12 with every reason listed; nothing is written | tests/codex/guard/test_manifest.py::test_invalid_entries |
| TC-003 | `pages/[id].tsx` against its literal path and against `pages/i.tsx` | Brackets are ordinary characters: literal path overlaps, one-character path does not; the optional class alternative over-approximates | tests/codex/guard/test_manifest.py::test_brackets |
| TC-004 | Randomised pairs of patterns over a small alphabet, 500 or more, including `docs/**` vs `**/*.md`, `src/*.py` vs `src/a?.py`, `a/**/b` vs `a/x/y/b`, `*.lock` vs `web/package-lock.json` | Overlap predicate equals the brute-force oracle on every pair | tests/codex/guard/test_manifest.py::test_overlap_matches_oracle |
| TC-005 | Changed file `src/c` against entry `src/c/x.py`; `src/a` against `src/ab.py` | File equal to a proper prefix of the entry overlaps; `src/a` does not overlap `src/ab.py` | tests/codex/guard/test_manifest.py::test_file_dir_rule |
| TC-006 | Branch ahead of the target by a commit touching `src/x.py`; manifest names `src/x.py` | Deny exit 10, branch named, evidence kind committed, file listed | tests/codex/guard/test_evidence.py::test_committed_overlap |
| TC-007 | Sibling worktree with an unstaged edit, a staged edit and an untracked file inside the manifest | Deny, evidence kind uncommitted with the three paths; the sibling worktree is byte-identical afterwards | tests/codex/guard/test_evidence.py::test_uncommitted_overlap |
| TC-008 | Rename `a.py` to `b.py` committed on another branch; manifest names `a.py` or `b.py` | Both names are in the footprint; either manifest is denied | tests/codex/guard/test_evidence.py::test_rename_both_sides |
| TC-009 | Branch squash-merged into the target (tip not an ancestor) | Stops claiming; a later divergent edit claims again | tests/codex/guard/test_evidence.py::test_squash_merged_branch |
| TC-010 | Merge, rebase, cherry-pick or revert in progress in a worktree; `git am` in progress; unreadable operation state | Warning OP_IN_PROGRESS for the first group; UNKNOWN for `am` or unreadable state | tests/codex/guard/test_evidence.py::test_in_progress_operations |
| TC-011 | Remote-tracking branch ahead of the target with no local copy; remote copy diverged from the local copy | Claimant with warning REMOTE_AS_OF_LAST_FETCH; diverged copy is UNKNOWN | tests/codex/guard/test_evidence.py::test_remote_tracking |
| TC-012 | Target resolution: `--target`, `magos.target`, `origin/HEAD`, `init.defaultBranch`, exactly one of main/master/develop/trunk, several candidates, none | Confidence high or medium (TARGET_INFERRED); several or none gives UNKNOWN TARGET_UNCERTAIN naming `git config magos.target <branch>` | tests/codex/guard/test_evidence.py::test_target_resolution |
| TC-013 | Dirty primary worktree with 1,000 deleted paths under `tests/`; manifest under `references/` | Allow (presence in a checkout claims nothing); manifest naming one of the deleted paths is denied | tests/codex/guard/test_evidence.py::test_dirty_primary_replica |
| TC-014 | `plan` with no claimant overlap | Exit 0, claim file written with all fields, audit line appended, creation command printed | tests/codex/guard/test_plan_store.py::test_plan_registers_claim |
| TC-015 | Second `plan` with identical entries; with different entries; with different entries and `--amend`; removal-only amend | No-op exit 0; exit 14; re-judged with own claim excluded; removal-only skips overlap | tests/codex/guard/test_plan_store.py::test_amend_semantics |
| TC-016 | Two lanes with overlapping declared manifests, lane two planned second | Deny naming lane one as `declared`, planned only | tests/codex/guard/test_plan_store.py::test_declared_overlap |
| TC-017 | Two processes plan overlapping manifests at the same instant; two plan disjoint manifests | Exactly one overlapping planner wins and the loser is denied naming it; both disjoint planners win | tests/codex/guard/test_plan_store.py::test_concurrent_planners |
| TC-018 | `release` of a planned claim, of an active lane, of an unknown claim | Deleted and audited; exit 16 with the claim kept; exit 0 with a note | tests/codex/guard/test_plan_store.py::test_release |
| TC-019 | `list` and `list --drift --json` | States planned, active, idle; drift lists footprint files matched by no entry; exit 0 | tests/codex/guard/test_plan_store.py::test_list_states_and_drift |
| TC-020 | `override` without a console, with a wrong retyped fingerprint, with a right one; replanning after a changed repository | Exit 17 without hang; refusal; one-shot record used once; changed target sha voids it | tests/codex/guard/test_plan_store.py::test_override_gate |
| TC-021 | Lock file held by another process for longer than the timeout; claim file replaced while a reader reads | Exit 13 after 30 s (shortened by a test hook); reader retries `PermissionError` and never sees a partial claim | tests/codex/guard/test_plan_store.py::test_lock_timeout_and_atomic_write |
| TC-022 | Branch names: reserved device names, `D/F` prefix clash with a claim or branch, NFC or case collision, forbidden characters, over 100 characters | Rejected with the exact reason before any claim is written | tests/codex/guard/test_plan_store.py::test_branch_names |
| TC-023 | Detector on every lane-creating form (`worktree add -b`, `switch -c`, `checkout -b`, `branch new`, `branch -m`, `update-ref refs/heads/x`, `symbolic-ref`, refspec pushes) in bash, PowerShell and cmd, with `-C`, `-c`, env prefixes, chains, `bash -c`, `-EncodedCommand` | Recognised with kind, names, repository hint and worktree path | tests/codex/guard/test_detector.py::test_lane_creating_forms |
| TC-024 | Detector on negatives: `branch --list`, `branch -d`, `worktree list`, `checkout file`, `log --branches`, strings inside `echo`, comments and heredocs | Not recognised as creation | tests/codex/guard/test_detector.py::test_negatives |
| TC-025 | Frozen corpus replay | Precision at least 0.97 and recall at least 0.85 on non-adversarial rows; residual misses listed in `known_gaps.json` | tests/codex/guard/test_detector.py::test_corpus_floors |
| TC-026 | Dynamic words (`git $CMD`, backticks, `%x%`) in lane position; unresolved repository with a lane verb | Deny UNPARSEABLE in armed repositories; allowed in auto mode for branch-only creation | tests/codex/guard/test_detector.py::test_dynamic_words |
| TC-027 | Claude, Codex and Hermes payloads for Bash, PowerShell, terminal, EnterWorktree, Agent with worktree isolation, session MCP tools | Allow is `{}`; deny is the single universal JSON object, exit 0, empty stderr, full conflict list in the message | tests/codex/guard/test_hook.py::test_host_payloads |
| TC-028 | Named creation with no claim; with a claim; with a claim whose files a sibling dirtied after planning; claim for a different worktree path | NO_MANIFEST with the exact plan command; allow; revalidation denies naming the sibling; path mismatch denied | tests/codex/guard/test_hook.py::test_creation_revalidation |
| TC-029 | Auto-named creations (agent isolation, `claude --worktree`, `gh pr checkout`) with and without another lane | UNPLANNABLE deny when another lane exists or the repository is armed; allow otherwise | tests/codex/guard/test_hook.py::test_unplannable |
| TC-030 | Tamper commands: `core.hooksPath`, `GIT_CONFIG_COUNT`, `git config magos.guard`, writes into `.git/hooks`, `override`, `arm`, `install`, also inside `bash -c`; allowed reads such as `git config --get magos.guard` and `for-each-ref` | PROTECTED deny for the first group; allow for the reads | tests/codex/guard/test_hook.py::test_tamper_protection |
| TC-031 | Hook with a crash after a recognised creation; with a crash on an unrelated command; PowerShell stdin with BOM and CRLF | Deny JSON; `{}` plus a stderr warning; parsed normally | tests/codex/guard/test_hook.py::test_failure_handling |
| TC-032 | `arm`, `arm --strict`, `arm --dry-run`, `arm` twice, with `core.hooksPath` set, with differing worktree hook directories, with an existing `.magos-prev` | Files written and printed; idempotent; exit 3 with the reason in the refusals; nothing written in dry run | tests/codex/guard/test_gitlayer.py::test_arm_disarm |
| TC-033 | In an armed repository: `git branch x`, `switch -c`, `checkout -b`, `checkout --orphan`, `update-ref refs/heads/x`, `worktree add -b`, `fetch . main:x`, DWIM switch of a remote-only name, push creating a branch | Each vetoed with the MAGOS message, no branch, no worktree directory, no admin directory left; the same commands pass once a claim exists | tests/codex/guard/test_gitlayer.py::test_reference_transaction_veto |
| TC-034 | Armed repository: `commit`, `tag`, `stash`, `fetch`, `pull`, `gc`, `pack-refs`, `switch` to an existing branch, `worktree add --detach`, `worktree add <path> <existing-branch>`, rebase | All pass untouched | tests/codex/guard/test_gitlayer.py::test_reference_transaction_passes |
| TC-035 | `HOOK_SH` under Git Bash `sh` and `dash`; run from a linked worktree and a subdirectory; foreign hook chained; strict mode with exempt and non-exempt branches | Same decisions; chained hook receives the original arguments and stdin; strict vetoes the first advance of a non-exempt unclaimed branch | tests/codex/guard/test_gitlayer.py::test_hook_sh_matrix |
| TC-036 | `install --host claude|codex|hermes`, `--dry-run`, `--home` | Canonical copy written with the same relative layout; generated snippet printed; user configuration files untouched | tests/codex/guard/test_gitlayer.py::test_install |
| TC-037 | `doctor` in healthy, missing-hook and mismatched-hook repositories | Reports problems and exits 1; self-test branch removed; exit 0 when healthy | tests/codex/guard/test_gitlayer.py::test_doctor |
| TC-038 | `run-guard.cmd` through cmd.exe and sh with guard exit 0, deny JSON, crash, exit 7, missing script, no Python, `MAGOS_GUARD=off`, a space and CJK directory | Pass-through of stdout and stdin; strict gives exit 2, soft gives warning and exit 0; off gives exit 0 | tests/codex/guard/test_launcher.py::test_launcher_matrix |
| TC-039 | End-to-end replica of this repository: dirty primary worktree, branches `develop_claude`, `test_claude`, `tests_codex`, new lane for `SKILL.md` and `references/lane-split.md` | Allowed; a second lane for `references/` is denied naming the first | tests/codex/guard/test_pressure.py::test_repository_replica |
| TC-040 | Armed replay of the corpus with the host hook disabled | No new `refs/heads/*` except the documented hook-invisible routes | tests/codex/guard/test_pressure.py::test_armed_replay |
| TC-041 | `hooks/hooks.json` parse and matcher anchors; `.gitattributes` endings; the package contract rows | Valid schema, anchored matchers, LF endings; no third file in `.claude-plugin/`; description unchanged at 1017 characters | tests/codex/guard/test_package.py::test_wiring_and_package_rows |
| TC-042 | In-process calls of `scripts/sync_hosts.py` and `__init__.py` | Every statement path of both older files is exercised for the project coverage gate | tests/codex/guard/test_project_sources.py::test_sync_hosts_and_init |

## Boundary & Failure Cases

- Empty manifest, 200 and 201 entries, 1024 and 1025 character entries, a manifest file outside and inside a worktree.
- Repositories with no commits (unborn HEAD), detached HEAD, bare repository, shallow clone, no merge base (unrelated
  history gives UNKNOWN NO_MERGE_BASE), submodule gitlink as a directory claim, more than 120 unmerged branches
  (UNKNOWN TOO_MANY_CLAIMANTS), more than 5,000 paths in one claimant (coarsened to directory prefixes, never dropped).
- Git failures: missing `git`, non-zero exit, timeout, `WinError 1455` retried twice; each ends as UNKNOWN GIT_FAILED or
  GIT_MISSING and a denied `plan` or `check`.
- Locale and encoding: non-ASCII branch and path names with `core.quotepath` forced off, case-insensitive collisions,
  Unicode normalisation forms, trailing dots and spaces, Windows reserved names, long paths.
- Concurrency: a claim written while a reader lists, two lock holders, a claim file removed between the existence test
  and the read in the git layer (treated as absent, transient deny).
- Hostile input: huge stdin, invalid UTF-8, JSON that is not an object, unknown tool names, nested wrappers deeper than 3,
  base64 that is not UTF-16LE.
- Regression: a lane that merely checks out files without modifying them never claims them; a denial never creates a
  branch, directory or administrative directory; an override never survives a changed target sha.

## Regression Scope

The new file is additive. Neighbouring modules and checks that must stay green: `scripts/sync_hosts.py` (package file list
is unchanged and still ships `references/lane-split.md` through the `references/*.md` glob), `__init__.py` (only
`ctx.register_skill`), the package contract rows in `tests/codex/contracts` (frontmatter limits, description length
1017 of 1024, seven adapters plus the entry skill, no third file in `.claude-plugin/`), the Claude contract cases
(`SKILL.md` strings, `references/commands.md` pins, `references/pressure-tests.md` headings), the GitConverge and
command-policy checks, and the host runtime cases that require refs and worktree files to be unchanged after read-only
commands (the guard writes only on `plan`, `release`, `override`, `arm`, `disarm` and `install`).
