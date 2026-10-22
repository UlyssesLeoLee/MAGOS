# MAGOS 1.0.4 — /GitPlan 版 / The /GitPlan release

A feature release: the new command `/GitPlan`, which plans, before any sub-agent starts, how one task is divided into lanes that own different files and are merged back as one whole, lists the requirements, the lanes and their outcomes in tables, and later converges them and supplements that list with what each lane changed. It is backed by four new subcommands of the lane guard (`scripts/magos_guard.py`): `set-plan`, `set-show`, `set-update` and `set-release`. **Every install should upgrade and refresh its guard copy**, including the copies under `~/.magos/guard` that the Codex and Hermes hooks run: a guard of 1.0.3 has no set subcommand, and `/GitPlan` stops at its version check. Full detail and upgrade steps: [CHANGELOG.md, section 1.0.4](https://github.com/UlyssesLeoLee/MAGOS/blob/v1.0.4/CHANGELOG.md).

## 版本概述

1.0.4 新增第八个命令 `/GitPlan`：在子 Agent 开工之前，先调查 Git 与代码，把任务拆成文件互斥的若干 lane（子 Agent 的 worktree），写出任务的需求，并给出一份简明清单（sheet）：用需求表和 lane 表列出需求、承担它的 lane 与计划成果的对应关系。lane 的 id、分支与 worktree 目录名都以修改内容的主题命名，从不用序号（守卫拒绝序号式和泛称的 id）。这份清单既是你审阅的计划，也是任务完成后合并时的 TODO 参考：`--status` 与 `--converge` 会按记录重新打印这两张表，标出每个 lane 的状态，并列出“还剩什么”；lane 合并之后，守卫把每个 lane 的修改内容（提交数、提交标题、文件数、增删行数、路径）存进记录，清单在原来的基础上补充修改内容概要。车道守卫证明各 lane 的文件清单两两不相交（`set-plan`），并以乐观锁登记：没有人持锁，记录带着 `revision` 与计划所依据的目标分支提交（`base`），过期的计划只会被发现，不会被覆盖。登记同时为集成分支 `agent/<set>/integration` 登记一份不占用任何文件的 claim，使守卫允许用普通的 `git switch -c` 创建它。之后 `--converge --apply` 按依赖顺序把 `READY` 的 lane 合并进集成分支（每个 lane 只合并它登记的那个提交，遇到冲突就 `git merge --abort` 并停下，从不用 ours 或 theirs），运行仓库自己的检查；`--land` 再以一次 `--ff-only` 快进把它落到 `<branch>`；`--release` 收尾。默认只预览，只有 `--apply`（以及 `--release`）才写入，写入只经过守卫的 `set-*` 子命令；从不推送、从不强推、从不删除分支或工作区、从不动 `main`。守卫新增退出码 19 到 24（过期、已存在、不存在、越界、记录来自更新版本、规划无效）；计划存在期间，普通的 `plan --amend` 与 `release` 会拒绝它的登记。

## Highlights

- **A plan in two tables that is also the merge TODO.** The requirements of the task, the lanes that serve them and the outcomes they deliver are listed in a Requirements table (`Req`, `Requirement`, `Lane(s)`, `Planned outcome`) and a Lanes table (`Lane`, `Branch`, `Worktree`, `Owns`, `Needs`, `Acceptance`), with a merge line, the owner of every shared file and at most five risks (the sheet, at most 8192 characters); every requirement is served by a lane and every lane serves a requirement, or the guard refuses the plan. `--status` and `--converge` regenerate the tables from the record with the state and the head of every lane and a **Remaining TODO** list.
- **Names show the topic of the change.** A lane id is a topic slug (`claim-store`, `sweep-docs`), the branch is exactly `agent/<set>/<id>` and the worktree directory name ends with `-<set>-<id>`, so `git branch` and `git worktree list` read as a list of topics; the guard refuses an ordinal or generic id such as `l1`, `lane-2` or `task3` with exit 24.
- **The original list, supplemented after the merge.** When a lane is recorded `integrated`, the guard stores a summary of what it changed (commits, subjects, files, insertions, deletions, paths); the converge apply report, `--status` and `--release` print the same tables with a `Changes` column, a `Result` column, a **Changes summary** and a `Total` line added, and nothing of the plan removed.
- **Exclusive file ownership, proved.** `set-plan` checks that the manifests of the lanes are pairwise disjoint (exact glob intersection), that `depends_on` forms a DAG, that every shared file lies inside exactly one lane, and that each lane is judged against the other claimants; it registers every lane claim, the integration claim and the record in one atomic write, or nothing.
- **Optimistic lock.** The record carries a `revision` and a `base`; a stale plan (exit 19 `STALE`, or the finding `STALE_PLAN`) is detected and never overwritten, and `--amend` and `--converge --apply` take `--expect-revision <n>`.
- **Convergence in dependency order.** `--converge --apply` merges each recorded lane head with `git merge --no-ff` into `agent/<set>/integration`, records each lane `integrated`, runs the repository's checks, and with `--land` fast-forwards `<branch>` once, only while it still sits where the integration branch was cut from.
- **Remedies for everything.** Every failed gate, failing lane finding, guard exit code and stop of an apply is followed by the action that lifts it; the command never performs these actions itself.
- **Read-only by default.** The preview fetches nothing, registers nothing and writes only a scratch spec file outside every worktree; `--apply` registers exactly the spec of the latest preview.

## New

- `/GitPlan <set> --into <branch>` with `--apply [--create]`, `--status`, `--amend --expect-revision <n> [--apply [--create]]`, `--converge [--include-active]`, `--converge --apply [--include-active] [--land] [--expect-revision <n>]` and `--release`; the adapters `commands/GitPlan.md` and `skills/git-plan/`; the contract `references/commands.md` section 8.
- The spec keys `requirements` (1 to 12 items) and, per lane, `serves` and `outcome`; the Requirements table and the Lanes table (with `State` and `Head` once the plan has state, and `Changes` and `Result` after the merge); the sheet limit of 8192 characters. Topic-slug lane ids, the branch `agent/<set>/<id>` and a worktree directory name ending with `-<set>-<id>`, enforced by the guard (exit 24: `GENERIC_ID`, `RESERVED`, `FORMAT`, `DUPLICATE`, `BRANCH_FORM`, `WORKTREE_FORM`, `UNSERVED`, `UNKNOWN_REQUIREMENT`, `RANGE`, `MISSING`). The `changes` summary stored per lane when it is recorded `integrated` (`set-show --json`), and the supplemented list with the Changes summary and the Total line.
- The guard subcommands `set-plan`, `set-show`, `set-update` and `set-release`, the set record `<git-common-dir>/magos/sets/<set>.json`, the integration claim of a set, the exit codes 19 `STALE`, 20 `SET_EXISTS`, 21 `SET_UNKNOWN`, 22 `OUT_OF_LANE`, 23 `SET_NEWER_FORMAT` and 24 `INVALID_SPEC`, and the `set` and `lane` (or `role`) of a claim in `list`.
- `doctor` reports sets: `sets: <n>, unreadable: <n>, newer-format: <n>`, a lane claim that is missing or differs from the record, an `active` or `ready` lane whose branch vanished, a set whose target is gone, claims without a record, and an unreadable or newer-format record.
- The lane findings `INTEGRATED`, `READY`, `BLOCKED`, `NOT_READY`, `WAITING`, `MISSING_BRANCH`, `DIRTY`, `IN_PROGRESS`, `NO_MERGE_BASE`, `OUT_OF_LANE`, `SHARED_CHANGE`, `MOVED`, `CLAIM_DRIFT`, `STALE_PLAN` and `PREDICTED_CONFLICT`, the converge readiness `READY` / `PARTIAL` / `BLOCKED` and `LAND_REFUSED`.
- Documentation: `/GitPlan` in the three READMEs, the **GitPlan pressure tests (v1.0.4)** in `references/pressure-tests.md` (among them ordinal lane ids, a requirement that nobody serves, a branch or worktree that does not carry the topic and the supplemented list after the merge), and the source-contract cases `git-plan/forms-and-help`, `git-plan/exclusive-lanes-and-optimistic-lock`, `git-plan/converge-and-hard-stops` and `git-plan/package-wiring`.

## Changed

- While the record of a set exists, a plain `plan --amend` of one of its lane claims is refused (exit 14, `lane_in_set`) and so is a plain `release` of any claim of the set (exit 16, `blocked_set`): a set is changed only through `/GitPlan`.
- The open lane claims of a set make `/GitCleanup`, `/GitConverge` and `/GitSweep` report their branches as `BLOCKED_ACTIVE_OWNER` while the set is open; `--release` lifts it.
- Every git call of the guard carries `-c diff.relative=false`: under `diff.relative=true`, the hook in a session directory below the top of the work tree and `plan`, `check` and the set subcommands with a `--repo` below the top read every committed path from the top and judge it against the manifests.
- `GUARD_VERSION` is 1.0.4, and `/GitPlan` stops when the guard is older.
- Every text that enumerates the commands says eight; the five write adapters (`git-integrate`, `git-cleanup`, `git-converge`, `git-sweep`, `git-plan`) set `disable-model-invocation: true` in Claude Code.

## 升级 / Upgrade

1. Upgrade the plugin on each host (`references/installation.md`) and **restart every running Claude Code session**. A Hermes install pinned with `--ref` must move its pin: `hermes plugins install UlyssesLeoLee/MAGOS --ref <40-char SHA of v1.0.4> --force --enable`.
2. Run `doctor` from the new version, then the `install --host <host>` commands it prints in your own terminal; compare each printed snippet with your host config and replace the entry if it differs.
3. Nothing else changes for scripts.

Claim files of 1.0.0 to 1.0.3 are read unchanged; a claim of a set carries the extra keys `set=` and `lane=` (the integration claim `set=` and `role=integration`), which older guards ignore.

## Known issues

- Sets live in one clone: the set record and the claims of its lanes are in the git directory that registered them, and fetch and push do not share them.
- Topic names are checked for form, not for meaning: the guard refuses the ordinal and generic ids and checks that an id is a topic slug, but it neither counts the words nor judges whether the name fits the change.
- Semantic coupling between files is not detected: the guard proves that the file lists are disjoint, not that the code of two lanes is independent, so files that import each other belong in one lane.
- A guard of 1.0.3 cannot see the set record: it has no `set-*` subcommand, does not show sets in `list` or `doctor`, judges the marker entry of the integration claim as a lane manifest, and cannot refuse `release` or `plan --amend` of a claim of a set. Refresh the guard copy.
- Every host receives the whole repository (including `tests/`, `.quality/`, `.github/`) because the marketplace source is the repo root; a slim runtime payload is not part of 1.0.4.
- The lane guard's own limits, unchanged since 1.0.3, are listed in `references/lane-split.md`, section 12.
