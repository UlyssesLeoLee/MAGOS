# Test Design: `scripts/magos_guard.py`

Source: `scripts/magos_guard.py`

Source-SHA256: `bc0cdc56507e68c2dabbc2d1aa0ab0bc2746c6b3ac0ec8f70397c6616a8ceb54`

## Test Strategy

All tests live under `tests/codex/guard/` and run with `pytest` in the lane worktree (runtime host cases stay in the
separate project test worktree described in `AGENTS.md`). Three levels:

1. **Pure unit tests** import `scripts/magos_guard.py` as a module: manifest parsing, normalisation, the glob-intersection
   dynamic programme (checked against a brute-force oracle that enumerates a universe of candidate paths), the decision
   table, message rendering in both languages, the command lexer and detector, the tamper filter.
2. **Real-Git integration tests** build throw-away repositories in `tmp_path` with real linked worktrees (committed-ahead
   branch, dirty worktree, untracked file, rename, delete, detached worktree with commits, merge or rebase in progress,
   locked and prunable worktree, remote-tracking branch ahead of the target, bare repository, case collision, unborn
   repository) and drive the CLI in process (`main(argv)`) and as a subprocess. Git runs with an isolated `HOME`,
   `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_NOSYSTEM`.
3. **Host-protocol and process tests** feed Claude, Codex and Hermes PreToolUse payloads (including PowerShell BOM and
   CRLF stdin) to `hook`, run the embedded `HOOK_SH` through real Git (`arm`) and directly under Git's `sh`, run
   `run-guard.cmd` through cmd.exe and `sh`, and run two concurrent planners in separate processes.

The frozen detector corpus (`tests/codex/guard/data/corpus.jsonl`, 1,155 labelled command strings) is replayed with
precision and recall floors; every residual miss and false positive is listed in `data/known_gaps.json`. Coverage is
measured with coverage.py (line coverage) for `scripts/magos_guard.py` and for every tracked source of the project
(`__init__.py`, `scripts/sync_hosts.py`), each strictly above 90 percent; the two older files are exercised in process by
`test_project_sources.py`.

## Test Cases

| Case ID | Input / Setup | Expected Outcome | Test Location |
| --- | --- | --- | --- |
| TC-001 | Manifest entries `src/a/`, `src\a\x.py`, `./src//a`, `Src/A`, NFD and NFC spellings | Normalised to one canonical, case-folded NFC form; directory entries also match everything below | tests/codex/guard/test_manifest.py::test_normalisation |
| TC-002 | Entries that are empty, start with `:` or `!`, are absolute (`/x`, `C:x`, UNC), contain `..`, `.git`, `**` inside a segment, match everything (`**`, `*/*`), or exceed 200 entries or 1024 characters | Exit 12 with every reason listed; nothing is written | tests/codex/guard/test_manifest.py::test_invalid_entries |
| TC-003 | `pages/[id].tsx` against its literal path and against `pages/i.tsx` | Brackets are ordinary characters: literal path overlaps; the class reading over-approximates and can only add conflicts | tests/codex/guard/test_manifest.py::test_brackets_are_ordinary_characters |
| TC-004 | Every pair of 63 patterns over a small alphabet (3,969 pairs), including `**` and `?` combinations | Overlap predicate equals the brute-force oracle on every pair | tests/codex/guard/test_manifest.py::test_overlap_matches_oracle |
| TC-005 | `docs/**` vs `**/*.md`, `*.lock` vs `web/package-lock.json`, `src/a` vs `src/ab.py`, a changed file `src/c` against entry `src/c/x.py` | Exact intersection, not a text prefix; a file equal to a proper prefix of the entry's literal part collides | tests/codex/guard/test_manifest.py::test_file_dir_rule |
| TC-006 | Branch ahead of the target by a commit touching `src/a.py`; manifest names `src/a.py` | Deny exit 10, branch named, evidence kind committed, file listed | tests/codex/guard/test_plan_store.py::test_committed_overlap_names_branch |
| TC-007 | Sibling worktree with an unstaged edit, a staged edit and an untracked file inside the manifest | Deny, evidence kind uncommitted with the three paths; the sibling worktree is byte-identical afterwards | tests/codex/guard/test_plan_store.py::test_uncommitted_overlap_and_sibling_untouched |
| TC-008 | Rename and delete committed or staged on another branch; manifest names the old or the new path | Both names are in the footprint; either manifest is denied | tests/codex/guard/test_plan_store.py::test_rename_claims_both_names_and_delete_claims |
| TC-009 | Branch squash-merged into the target (tip not an ancestor); later divergent edit | Stops claiming after the squash; a later divergent edit claims again | tests/codex/guard/test_plan_store.py::test_squash_merged_branch_stops_claiming |
| TC-010 | Merge in progress in a worktree; `git am` state; unreadable operation state | Warning OP_IN_PROGRESS for the first; UNKNOWN OP_METADATA_UNREADABLE for `am` | tests/codex/guard/test_plan_store.py::test_in_progress_operations |
| TC-011 | Remote-tracking branch ahead of the target with no local copy; same name checked out locally; remote copy ahead of the local one | One claimant per branch; warning REMOTE_AS_OF_LAST_FETCH | tests/codex/guard/test_plan_store.py::test_remote_tracking_branch_ahead |
| TC-012 | Target resolution: `--target`, `magos.target`, `origin/HEAD`, `init.defaultBranch`, exactly one of main/master/develop/trunk, several candidates, none, a `--target` that does not resolve | Confidence high or medium (TARGET_INFERRED); several or none gives UNKNOWN TARGET_UNCERTAIN naming `git config magos.target <branch>`; diverged local and remote copies are UNKNOWN | tests/codex/guard/test_plan_store.py::test_target_resolution |
| TC-013 | Dirty primary worktree with 300 deleted paths; manifests under other directories and naming one deleted path | Allow for the unrelated manifest (presence in a checkout claims nothing); deny for the deleted path | tests/codex/guard/test_plan_store.py::test_dirty_primary_replica |
| TC-014 | `plan` with no claimant overlap | Exit 0, claim file written with all fields, audit line appended, quoted creation command printed | tests/codex/guard/test_plan_store.py::test_plan_registers_claim_and_prints_creation_command |
| TC-015 | Second `plan` with identical entries; with different entries; with different entries and `--amend`; removal-only amend; a new `--worktree` path | No-op exit 0; exit 14; re-judged with own claim excluded; removal-only skips overlap; a different registered path needs `--amend` | tests/codex/guard/test_plan_store.py::test_amend_semantics |
| TC-016 | Two lanes with overlapping declared manifests, lane two planned second | Deny naming lane one as `declared`, planned only; nothing registered for lane two | tests/codex/guard/test_plan_store.py::test_declared_manifests_collide_even_before_any_branch_exists |
| TC-017 | Two processes plan overlapping manifests at the same instant (three rounds); two plan disjoint manifests | Exactly one overlapping planner wins and the loser is denied naming one lane; both disjoint planners win | tests/codex/guard/test_plan_store.py::test_concurrent_planners_one_winner |
| TC-018 | `release` of a planned claim, an unknown claim, a branch with unmerged work, a merged lane with a clean or a dirty worktree, an unreadable claim file | Deleted and audited; exit 0 with a note; exit 16; allowed when clean; exit 16 when dirty; the unreadable file is removed | tests/codex/guard/test_plan_store.py::test_release |
| TC-019 | `list` and `list --drift --json` with planned, active, idle and drifting lanes | States planned, active, idle; drift lists footprint files matched by no entry; exit 0 | tests/codex/guard/test_plan_store.py::test_list_states_and_drift |
| TC-020 | `override` without a console, with a wrong retyped fingerprint, with a right one; replanning; an expired record; a changed repository | Exit 17 without hang; refusal; one-shot record used once; changed target sha voids it | tests/codex/guard/test_plan_store.py::test_override_gate_and_consumption |
| TC-021 | Lock held by another handle past the timeout; claim file replaced while a reader reads; `PermissionError` on replace and on read | Exit 13 (shortened by `MAGOS_LOCK_TIMEOUT`); retries; never a partial claim | tests/codex/guard/test_plan_store.py::test_lock_timeout_and_release |
| TC-022 | Branch names: reserved device names, `D/F` prefix clash with a claim or branch, case collision, forbidden characters, over 100 characters, a leading dash | Rejected with the exact reason before any claim is written | tests/codex/guard/test_plan_store.py::test_branch_name_rules |
| TC-023 | Detector on every lane-creating form in bash, PowerShell and cmd, with `-C`, `-c`, env prefixes, chains, `bash -c`, `-EncodedCommand`, heredocs, aliases, scripts on disk, bundled flags | Recognised with kind, names, repository hint and worktree path | tests/codex/guard/test_detector.py::test_lane_creating_forms |
| TC-024 | Detector on negatives: `branch --list`, `branch -d`, `worktree list`, `checkout file`, strings inside `echo`, comments and heredocs | Not recognised as creation | tests/codex/guard/test_detector.py::test_negatives |
| TC-025 | Frozen corpus replay | Precision at least 0.93 and recall at least 0.88 on non-adversarial rows; residual rows listed in `known_gaps.json` | tests/codex/guard/test_detector.py::test_corpus_floors_and_known_gaps |
| TC-026 | Dynamic words (`git $CMD`, backticks, `%x%`) in lane position; a dynamic subcommand; unresolved repository with a lane verb | Flagged dynamic; denied UNPARSEABLE once the creation is guarded | tests/codex/guard/test_hook.py::test_dynamic_names |
| TC-027 | Claude, Codex and Hermes payloads for Bash, PowerShell, terminal, EnterWorktree, Agent isolation, session MCP tools (also `hand_off_to_session`) | Allow is `{}`; deny is the single universal JSON object, exit 0, empty stderr, full conflict list in the message | tests/codex/guard/test_hook.py::test_every_host_gets_the_same_deny_object |
| TC-028 | Named creation with no claim; with a claim; with a claim whose files a sibling dirtied after planning; claim for a different worktree path | NO_MANIFEST with the exact plan command; allow; revalidation denies naming the sibling; path mismatch denied | tests/codex/guard/test_hook.py::test_revalidation_denies_when_a_sibling_dirties_a_planned_file |
| TC-029 | Auto-named creations (agent isolation, `gh pr checkout`, `hand_off_to_session`) with and without another lane | UNPLANNABLE deny when another lane exists or the repository is armed; allow otherwise | tests/codex/guard/test_hook.py::test_auto_named_worktrees_cannot_be_planned |
| TC-030 | Tamper commands: `core.hooksPath`, `GIT_CONFIG_COUNT`, `git config magos.guard`, writes into `.git/hooks`, `override`, `arm`, `install`; ordinary commands that merely name them | PROTECTED deny for the writers; allow for reads, commit messages, greps and heredoc text | tests/codex/guard/test_detector.py::test_protected_denies_real_writers |
| TC-031 | Hook with a crash after a recognised creation; with a crash on an unrelated command; PowerShell stdin with BOM and CRLF; git missing from PATH | Deny JSON; `{}` plus a stderr warning; parsed normally; deny | tests/codex/guard/test_hook.py::test_internal_errors_fail_closed_only_for_lane_creation |
| TC-032 | `arm`, `arm --dry-run`, `arm` twice, with `core.hooksPath` set, with differing worktree hook directories, with a foreign `.magos-prev`; without a console | Files written and printed; idempotent; exit 3 with the reason; exit 17 without a console; nothing written in dry run | tests/codex/guard/test_gitlayer.py::test_arm_writes_the_hook_and_switches |
| TC-033 | In an armed repository: `git branch`, `switch -c`, `checkout -b`, `checkout --orphan`, `update-ref refs/heads/x`, `fetch . main:x`, `worktree add -b` | Each vetoed with the MAGOS message, no branch, no worktree directory, no admin directory left; the same commands pass once a claim exists | tests/codex/guard/test_gitlayer.py::test_creations_without_a_claim_are_vetoed |
| TC-034 | Armed repository: `commit`, `tag`, `stash`, `fetch`, `gc`, `pack-refs`, `switch` to an existing branch, `worktree add --detach`, `worktree add <path> <existing-branch>`, rebase, merge; commits on a lane that existed before arming | All pass untouched | tests/codex/guard/test_gitlayer.py::test_everything_else_passes |
| TC-035 | `HOOK_SH` from a linked worktree and a subdirectory; foreign hook chained with its original stdin; 5,000-line transaction | Same decisions; chained hook sees prepared and committed; linear time | tests/codex/guard/test_gitlayer.py::test_disarm_restores_a_foreign_hook |
| TC-036 | `install --host` with claude, codex and hermes, `--dry-run`, `--home` | Canonical copy written with the same relative layout; generated snippet printed with a quoted launcher; user configuration files untouched | tests/codex/guard/test_gitlayer.py::test_install_copies_the_guard_and_prints_the_snippet |
| TC-037 | `doctor` in healthy, missing-hook, mismatched-hook, hook-bypassed and broken-backstop repositories | Reports problems and exits 1; self-test branch removed; exit 0 when healthy | tests/codex/guard/test_gitlayer.py::test_doctor |
| TC-038 | `run-guard.cmd` through cmd.exe and `sh` with guard exit 0, deny JSON, crash, exit 7, missing script, no Python, `MAGOS_GUARD=off`, a space and CJK directory | Pass-through of stdout and stdin; strict gives exit 2, soft gives warning and exit 0; off gives exit 0 | tests/codex/guard/test_launcher.py::test_cmd_failure_map |
| TC-039 | End-to-end replica of this repository: dirty primary worktree, branches `develop_claude`, `test_claude`, `tests_codex`, new lane for `SKILL.md` and `references/lane-split.md` | Allowed; a second lane for `references/` is denied naming the first | tests/codex/guard/test_pressure.py::test_replica_of_the_users_repository |
| TC-040 | Work-around attempts in an armed repository (variable subcommand, substitution, `bash -c`, `-C`, other tools through the git layer) | Each denied by the host hook or vetoed by the git layer; no new `refs/heads/*` | tests/codex/guard/test_pressure.py::test_workaround_attempts_in_an_armed_repository |
| TC-041 | `hooks/hooks.json` parse, anchored matchers and `shell`; `.gitattributes` endings; launcher executable bit; package contract rows | Valid schema, LF endings; no third file in `.claude-plugin/`; description unchanged | tests/codex/guard/test_package.py::test_hooks_json_wiring |
| TC-042 | In-process calls of `scripts/sync_hosts.py` and `__init__.py` | Every statement path of both older files is exercised for the project coverage gate | tests/codex/guard/test_project_sources.py::test_plan_verify_apply_cycle |
| TC-043 | Committed work on a detached worktree; `worktree add --detach` and `<path> <commit>` | The detached worktree claims its commits; the creation needs a claim keyed `detached/<directory>` | tests/codex/guard/test_review_fixes.py::test_detached_worktrees_need_a_manifest_keyed_by_their_directory |
| TC-044 | Integrated lane without a workspace, fresh branch without a worktree, case-variant branch spelling | Idle claims stop blocking; fresh lanes keep blocking; spelling does not change the state | tests/codex/guard/test_review_fixes.py::test_fresh_branch_without_a_worktree_is_still_a_lane |
| TC-045 | Bare repository with linked worktrees; submodule layout; locked worktree missing on disk | Guarded; the work tree is the repository top; UNKNOWN WORKTREE_UNREADABLE | tests/codex/guard/test_review_fixes.py::test_bare_repository_layout_is_guarded |
| TC-046 | UTF-16 and ANSI manifest files; no username; a `--target` that does not resolve; an exhausted comparison budget | Read or rejected with a clear exit 12; plan still works; exit 11; BUDGET_EXCEEDED | tests/codex/guard/test_review_fixes.py::test_manifest_encodings |
| TC-047 | `plan --worktree` naming another branch's dirty worktree; a detached lane's own dirty worktree; a re-plan spelling the worktree path in another case | The other branch is still a conflict; the detached lane does not conflict with itself; the re-plan is a no-op | tests/codex/guard/test_second_review.py::test_a_worktree_of_another_branch_at_the_planned_path_is_still_compared |
| TC-048 | 190,000 spaces after `echo`, 18,000 `update-ref` words, 190,000 closing parentheses, 45,000 `-git` options | Detector, tamper filter and alias scan each finish within 5 s | tests/codex/guard/test_second_review.py::test_worst_case_command_lines_parse_in_linear_time |
| TC-049 | `update-ref --stdin` with a here-string; `echo` text piped into `sh`;`git status && git mkwt ...` where `mkwt` is a worktree alias | Names read; the aliased worktree creation is denied for want of a manifest | tests/codex/guard/test_second_review.py::test_every_git_call_is_checked_for_an_alias |
| TC-050 | A command longer than 200,000 characters with a parallel lane, then with a claim | Denied as unparseable naming the length; denied as protected (too long to inspect) | tests/codex/guard/test_second_review.py::test_an_over_long_command_is_denied_with_its_real_reason |
| TC-051 | A planned claimant with declared entries only and an expired deadline; 300 paths with a live deadline | BUDGET_EXCEEDED; all 300 paths compared | tests/codex/guard/test_second_review.py::test_declared_only_claimants_watch_the_clock |
| TC-052 | A hook call whose shared budget is spent; a named-worktree creation whose check fails in auto mode; a vanished working directory | Deny naming the exhausted budget and no budget left behind; deny for the worktree, allow for branch-only; GIT_FAILED, not GIT_MISSING | tests/codex/guard/test_second_review.py::test_one_hook_call_shares_one_git_budget |
| TC-053 | `powershell -ExecutionPolicy Bypass -File x.ps1`, `bash -o pipefail x.sh`, `pwsh -NoProfile -File x.ps1` | The script file is read and its creation found | tests/codex/guard/test_second_review.py::test_the_script_after_option_values_is_read |
| TC-054 | `override --fingerprint ../../x`; `plan --target`; malformed UTF-16 manifests | Exit 2 and no override record; usage error exit 2 (`check --target` works); ENCODING | tests/codex/guard/test_second_review.py::test_override_wants_the_printed_fingerprint |
| TC-055 | A claim file with only `state`, `branch` and `entry`; a claim with an invalid entry under `list --drift` | Listed as planned and usable by the hook; drift is empty and other lanes get UNKNOWN CLAIM_UNPARSEABLE | tests/codex/guard/test_second_review.py::test_a_claim_without_optional_fields_is_read |

## Boundary & Failure Cases

- Empty manifest, 200 and 201 entries, 1024 and 1025 character entries, a manifest file outside and inside a worktree,
  UTF-8 with BOM, UTF-16 and ANSI encodings.
- Repositories with no commits, detached HEAD, bare repository, submodule, no merge base (unrelated history gives the
  warning UNRELATED_HISTORY and the branch is ignored), more than 120 unmerged local branches (UNKNOWN TOO_MANY_CLAIMANTS),
  more than 300 remote-tracking branches (warning REMOTE_TRUNCATED), more than 5,000 paths in one claimant.
- Git failures: missing `git` or an exhausted budget (an error, never "not a repository"), a vanished working directory,
  non-zero exit, timeout, `WinError 1455` retried twice; each ends as UNKNOWN GIT_FAILED, GIT_MISSING or BUDGET_EXCEEDED
  and a denied `plan` or `check`.
- Locale and encoding: non-ASCII branch and path names with `core.quotepath` forced off, case-insensitive collisions,
  Unicode normalisation forms, trailing dots and spaces, Windows reserved names, Git Bash path spellings (`/c/Users/x`).
- Concurrency: a claim written while a reader lists, two lock holders, a claim file removed between the existence test
  and the read in the git layer (treated as absent, transient deny).
- Hostile input: huge stdin, invalid UTF-8, JSON that is not an object, unknown tool names, nested wrappers deeper than 3,
  base64 that is not UTF-16LE, command lines built to trigger regex backtracking (linear time), a command longer than
  200,000 characters (not inspected, denied once lanes exist).
- Regression: a lane that merely checks out files without modifying them never claims them; a denial never creates a
  branch, directory or administrative directory; an override never survives a changed target sha; no hook denies a
  commit, merge, edit or read inside an existing lane.

## Regression Scope

The new file is additive. Neighbouring modules and checks that must stay green: `scripts/sync_hosts.py` (package file list
is unchanged and still ships `references/lane-split.md` through the `references/*.md` glob), `__init__.py` (only
`ctx.register_skill`), the package contract rows in `tests/codex/contracts` (frontmatter limits, description length
1017 of 1024, seven adapters plus the entry skill, no third file in `.claude-plugin/`), the Claude contract cases
(`SKILL.md` strings, `references/commands.md` pins, `references/pressure-tests.md` headings), the GitConverge and
command-policy checks, and the host runtime cases that require refs and worktree files to be unchanged after read-only
commands (the guard writes only on `plan`, `release`, `override`, `arm`, `disarm` and `install`).
