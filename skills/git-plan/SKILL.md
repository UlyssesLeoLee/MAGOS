---
name: git-plan
description: "规划并收敛多车道任务（仅显式调用，写操作）；/git-plan SET --into BRANCH [--help]."
license: Apache-2.0
disable-model-invocation: true
metadata:
  short-description: "规划并收敛车道；$git-plan SET --into BRANCH [--apply] [--help]."
---

# GitPlan

Command adapter for the canonical `/GitPlan` command of the MAGOS (Multi-Agent Git Orchestrator) package. It plans, before any sub-agent starts, how one task is divided into lanes that are merged back as one whole, and later converges them. Use it only when the user explicitly invokes `/git-plan` in Hermes or `$git-plan` in Codex.

## Usage

- Hermes: `/git-plan <set> (--into <branch> | --status | --amend | --converge | --release) [--apply] [--create] [--expect-revision <n>] [--include-active] [--land] [--lang <language>] [--help]`
- Codex: `$git-plan <set> (--into <branch> | --status | --amend | --converge | --release) [--apply] [--create] [--expect-revision <n>] [--include-active] [--land] [--lang <language>] [--help]`

Forms (the selecting option `--into`, `--status`, `--amend`, `--converge` or `--release` chooses the form; two selecting options together, or an option the form does not list, is a usage error; `--lang <language>` and `--help` go with every form; written for Hermes, Codex uses `$git-plan` in place of `/git-plan`):

- `/git-plan <set> --into <branch>`: preview the plan: investigate Git and the code, divide the task into lanes with exclusive file ownership, prove it and print the checklist (read-only).
- `/git-plan <set> --into <branch> --apply`: register the plan the preview showed.
- `/git-plan <set> --into <branch> --apply --create`: register it and also create the lane branches and worktrees.
- `/git-plan <set> --status`: the checklist with the state of every lane and what remains (read-only).
- `/git-plan <set> --amend --expect-revision <n>`: preview the re-plan of a registered set (read-only).
- `/git-plan <set> --amend --expect-revision <n> --apply [--create]`: register the amended plan.
- `/git-plan <set> --converge [--include-active]`: preview the convergence (read-only).
- `/git-plan <set> --converge --apply [--include-active] [--land] [--expect-revision <n>]`: merge the lanes into the integration branch; `--land` also fast-forwards `<branch>`.
- `/git-plan <set> --release`: retire the set after its lanes are integrated.

Arguments and options:

- `<set>`: Required (except with `--help`). Name of the plan: `[a-z0-9][a-z0-9-]{0,23}`, matched case-sensitively, and not a Windows device name (`con`, `nul`, `com1`, ...). It names the set record and the claims of its lanes.
- `--into <branch>`: Required to plan. Local branch the plan is made against and that `--land` later fast-forwards. Matched exactly (case-sensitive); it must not be `main`. The other forms read it from the set record.
- `--apply`: With `--into`: register the plan the preview showed (the lane claims, the claim of the integration branch and the set record, written only through `magos_guard.py`). With `--amend`: register the amended plan. With `--converge`: merge the lanes into the integration branch. Without it, only a preview is shown.
- `--create`: With `--apply` of a plan or an amendment: also create the branches and worktrees of the registered lanes that do not exist yet. Without it the apply prints the `git worktree add` lines for you to run.
- `--status`: Read-only checklist: the sheet with the state of every lane and what remains.
- `--amend`: Re-plan a registered set. Needs `--expect-revision`.
- `--expect-revision <n>`: The record revision (a positive integer) the amendment, or with `--converge --apply` the previewed convergence, was made against; a record at another revision stops the command.
- `--converge`: Preview the merge of the lanes, in dependency order, into one integration branch `agent/<set>/integration`; with `--apply`, run it: each ready lane's recorded head is merged with `git merge --no-ff` and recorded `integrated`, and the repository checks run on the result. A conflict aborts that merge and stops the run; it is never resolved with ours or theirs.
- `--include-active`: With `--converge`: treat a lane in state `active` that holds commits as ready at its current tip. In an apply this is your acceptance of those tips.
- `--land`: With `--converge --apply`: after the merges and the checks, fast-forward `<branch>` to the integration branch with `git merge --ff-only`, only when `<branch>` still sits where the integration branch was cut from; otherwise it stops and says to rerun. It is refused, before any merge, while a lane is not ready or integrated (run without `--land` first).
- `--release`: Retire the set once its lanes are integrated: remove its claims and its record. The lane branches, their worktrees and the integration branch are not touched.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Investigate Git and the code, then print the plan preview: the checklist (the sheet), the lane table, the proof that the lane manifests are pairwise disjoint (`magos_guard.py set-plan --dry-run`) and a readiness verdict (`READY` or `BLOCKED`) with the next command and the remedy for every failed gate; nothing is registered, created or merged, nothing is fetched, and the only write is a scratch spec file outside every worktree.

The plan divides one task into lanes (sub-agent worktrees) that own disjoint files and are merged back as one whole. The preview investigates Git (branches, worktrees, open claims, the target tip, remote freshness as it is known locally) and the code (layout, entry points, test and build commands, shared files, hot spots, coupling) and prints a concise checklist, the sheet, of at most 4096 characters: one line per lane with its branch, the paths it owns, its dependencies and its acceptance, one merge line, the shared files with their owner lane and at most five risks. `magos_guard.py set-plan --dry-run` proves that the lane manifests are pairwise disjoint, that every shared file lies inside exactly one lane and that the dependencies form a DAG; the guard must be version 1.0.4 or later, otherwise the command stops and says to refresh it. The plan is registered with an optimistic lock: nobody holds a lock while the lanes work, the record carries a revision and the target SHA it was planned against (`base`), a stale plan is detected and never overwritten, and the owner of a lane records it `ready` with its head SHA when it finishes. After the lanes finish, `--status` and `--converge` print the checklist again from the record with every lane ticked, followed by Remaining TODO (the lanes still to finish, the merges, the repository checks, the post-merge tasks, the land and the release), so the sheet is the TODO reference for the merge. Semantic coupling across files is not detected by the guard: coupled files go into the same lane. While the set is open, its lane claims make `/GitCleanup`, `/GitConverge` and `/GitSweep` report those branches as `BLOCKED_ACTIVE_OWNER`; `--release` lifts that. The command never pushes, never forces, never deletes a branch or a worktree, never touches `main`, never uses `override`, never rebases or squashes, and never resolves a conflict with ours or theirs: a conflict aborts the merge and stops the run, with the completed merges kept on the integration branch only.

Examples: `/git-plan feat-x --into develop`, `$git-plan feat-x --into develop --apply --create`, `$git-plan feat-x --status`, `$git-plan feat-x --converge --apply --land`, `$git-plan --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-plan` in the user's message.
- Plugin installs prefix the name with the plugin name: `/magos:git-plan` in Claude Code and Hermes, `$magos:git-plan` in Codex. The arguments follow it the same way (Claude Code appends them as `ARGUMENTS: ...`).
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. If the set name is missing, show this help and ask for it; for an unknown option, or an option the form does not list, explain the error and show this help. Do not inspect or change the repository in these error cases. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Claude Code keeps the model from invoking this adapter through `disable-model-invocation: true` in its frontmatter, and Codex disables implicit selection for it through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-plan` command (Hermes renders it as "The user has invoked the "git-plan" skill" followed by the arguments) or `$git-plan` in Codex. With a plugin install, the user's `/magos:git-plan` (Claude Code, Hermes) or `$magos:git-plan` (Codex) is the same explicit invocation; in Claude Code, the `/magos:GitPlan` command of the same name is the preferred form. If this adapter was selected without such an invocation, preview at most and register, create, merge, and release nothing.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` sections **8. GitPlan** and **6. GitConverge**: command contract, lane findings, gates, remedies, and the preview, apply, status, amend, converge and release procedures (GitPlan reuses the target gates, names, argument safety and worktree rules of GitConverge unchanged).
3. `../../references/lane-split.md`: the lane guard `magos_guard.py`, the manifest syntax, the guard call, the `set-*` subcommands and their exit codes.
4. `../../references/reconnaissance.md` and `../../references/decision-matrix.md`: inspection steps and cleanup criteria.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line (when the skill was loaded with `skill_view` instead of a slash command, from the `skill_dir` field it returns), go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` (`magos:git-orchestrator` under a Hermes plugin install) and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and do not register, create, merge, switch, delete, or push anything; a read-only preview is still allowed.

## Execution

Execute the canonical `/GitPlan` command only when the user explicitly invoked this command skill. Preview by default; write only when the explicit command includes `--apply` (or is `--release`) and every gate still passes. A preview investigates Git and the code read-only, proves the partition with `magos_guard.py set-plan --dry-run`, fetches nothing and uses no network, and writes nothing but a scratch spec file outside every worktree. With `--apply` of a plan or an amendment, register exactly the spec of the latest preview of the same set and target in this conversation (make a new preview and stop when there is none, when the user asked for a change since it, or when its `base` differs from the live target tip); with `--create`, also create only the registered lane branches and worktrees, at their registered paths, from the recorded `base`. With `--converge --apply`, record the plan first (lane order, recorded heads, target tip, revision) and include it in the final report, create the integration branch `agent/<set>/integration` from the current target tip in the invoking worktree when it is absent (that worktree must be on the target and clean), merge each ready lane's recorded head into it with `git merge --no-ff`, record each merge through `magos_guard.py set-update`, run the repository checks, and only with `--land` fast-forward `<branch>` once with `git merge --ff-only`. With `--release`, print the final checklist first, then remove the claims and the record through `magos_guard.py set-release`; no branch, worktree or integration branch is touched. Stop on a conflict: run `git merge --abort`, never resolve it with ours or theirs, and keep the completed merges on the integration branch only. Write the claim store and the set record only through `magos_guard.py set-plan`, `set-update` and `set-release`. Never push, force-push, fetch or use the network; never move, merge into or delete `main`, and never take `main` as the target; never delete a branch or a worktree and never run `git worktree prune`; never use `override`, `arm`, `disarm` or `install`, never run the guard's plain `plan` or `release` on a claim of a set and never edit `.git/magos`; never rebase, squash, cherry-pick or reset; never pass `--no-verify`, `-X ours`, `-X theirs` or `--allow-unrelated-histories` to a merge; never write inside a lane worktree. Merge nothing but a recorded lane head into the integration branch (and, with `--land`, the integration branch into `<branch>` by one `--ff-only` merge); create no branch or worktree other than a registered lane (at its registered path, from the recorded `base`) and the integration branch; never shrink, amend or release the claim of a lane to make a conflict disappear. Git and guard commands run as argument lists, never as shell strings. Ask for a set name if none is provided. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
