# git-plan/exclusive-lanes-and-optimistic-lock

- Skill: `git-plan`
- Feature: A plan divides a task into lanes with exclusive file ownership proved by the guard and registered under an optimistic lock (revision and base); a stale plan is detected and never overwritten
- Result: **PASS**

## Expected behavior

- The plan has at most 12 lanes with exclusive file ownership: manifests are pairwise disjoint (proved by magos_guard.py set-plan --dry-run, exact glob intersection), every shared file lies inside exactly one lane or is a post-merge task, depends_on forms a DAG, lane ids are L1, L2, ..., and coupled files go into one lane because the guard does not detect semantic coupling.
- The sheet is a checklist of at most 4096 characters: one line per lane (branch, owned paths, dependencies, acceptance), one merge line, the owner of every shared file and at most five risks; --status and --converge regenerate it from the record with [x] for ready or integrated lanes, followed by Remaining TODO.
- --apply registers exactly the spec of the latest preview of the same set and target, byte for byte, and makes a new preview and stops when there is none, when the user asked for a change since, or when its base differs from the live target tip; the guard writes every lane claim, the claim of the integration branch and the record at revision 1 in one atomic operation, or nothing.
- Nobody holds a lock while the lanes work: the record carries a revision and the base the plan was made against, a stale plan is refused and never overwritten (exit 19 with kind base or revision, a failed --expect-revision check, the finding STALE_PLAN when the target moved onto a lane manifest), and --amend moves base to the live target tip.
- The exit codes 19 STALE, 20 SET_EXISTS, 21 SET_UNKNOWN, 22 OUT_OF_LANE, 23 SET_NEWER_FORMAT and 24 INVALID_SPEC each have a remedy that the command never performs; set-plan never reads an override.
- While the record exists, a plain plan --amend of a lane claim (exit 14, lane_in_set) and a plain release of any claim of the set (exit 16, blocked_set) are refused, and the open lane claims make /GitCleanup, /GitConverge and /GitSweep report their branches as BLOCKED_ACTIVE_OWNER until --release.
- The guard must report version 1.0.4 or later; an older guard has no set-* subcommands and the command stops and says to refresh it.

## Contract checks

- PASS `references/commands.md`
- PASS `commands/GitPlan.md`
- PASS `skills/git-plan/SKILL.md`
- PASS `SKILL.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`
- PASS `CHANGELOG.md`
- PASS `RELEASE_NOTES_1.0.4.md`
- PASS `references/pressure-tests.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
