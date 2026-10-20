---
name: git-sweep
description: "收敛并清除已合并远端分支（仅显式调用，写操作）；/git-sweep BRANCH [--apply] [--push] [--help]."
license: Apache-2.0
disable-model-invocation: true
metadata:
  short-description: "收敛并清远端分支；$git-sweep BRANCH [--apply] [--push] [--help]."
---

# GitSweep

Command adapter for the canonical `/GitSweep` command of the MAGOS (Multi-Agent Git Orchestrator) package. It is `/GitConverge` followed by a guarded sweep of merged remote branches. Use it only when the user explicitly invokes `/git-sweep` in Hermes or `$git-sweep` in Codex.

## Usage

- Hermes: `/git-sweep <branch> [--apply] [--discard-ignored] [--push] [--remote <name>] [--lang <language>] [--help]`
- Codex: `$git-sweep <branch> [--apply] [--discard-ignored] [--push] [--remote <name>] [--lang <language>] [--help]`
- `<branch>`: Required local branch that receives everything. Matched exactly (case-sensitive); it must not be `main`.
- `--apply`: Run `/GitConverge <branch> --apply` first (merge every local branch's unique commits into `<branch>`, delete the merged local branches and their clean worktrees), then delete the remote branches that are already merged into a branch the remote keeps. A conflict or failed check stops the command before any deletion. It never moves or deletes `main`, and it pushes commits only with `--push`.
- `--discard-ignored`: Passed through to the converge phase: also allow removing worktrees that hold ignored files (for example `.env`). Without it those worktrees and their branches are kept.
- `--push`: With `--apply`, after the converge phase and before the remote deletions, publish `<branch>` with one fast-forward push, exactly `git push --no-follow-tags <remote> refs/heads/<branch>:refs/heads/<branch>` (never forced, never `--no-verify`), so remote branches merged only into the local `<branch>` are deleted in the same run instead of needing a manual push and a second run. The push is refused when the remote's `<branch>` is not an ancestor of the local one, when `<branch>` is `main` or the remote default, when the converge phase stopped or its validation failed, or when the remote sweep is `UNKNOWN`. When the remote's `<branch>` already equals the local one nothing is pushed (`PUBLISH_NOT_NEEDED`); otherwise the push runs even when no remote branch depends on it. Without `--apply` the preview only predicts the push, and it gives that prediction whether or not `--push` was typed. A published branch cannot be undone by this command.
- `--remote <name>`: The remote whose merged branches are swept (`origin` when absent). It must be listed by `git remote`; otherwise the command stops before anything is changed and names the remedy.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Preview the converge plan and the remote branches that would be deleted, then a readiness verdict (`ONE_SHOT`, `PARTIAL` or `BLOCKED`) with the recommended command and the remedy for everything that remains; nothing is changed and the network is not contacted.

A remote branch is deleted only when its tip is already contained in the remote's own copy of `<branch>` or its default branch. A branch merged only into the local `<branch>` is `PUSH_THEN_DELETE` while the push is predicted to run, in the preview with or without `--push`: with `--push` the run publishes `<branch>` first and then deletes it, and without `--push` the run leaves it on the remote and reports "kept: `--push` not typed" (rerun with `--push`, or push `<branch>` yourself and run `$git-sweep` again). It is `PENDING_PUSH` when the push is not predicted to run (for example `<branch>` is the remote default, or the remote's `<branch>` is not an ancestor of the local one) or when the run skipped the push, or the push failed or was not confirmed: clear the condition the report names, then rerun (with `--push`, except when `<branch>` is the remote default, which the command never pushes). A preview that is not `BLOCKED` ends with the recommended command, which carries exactly the flags that lift something (`--discard-ignored` when ignored files are the only blocker of a worktree, with the files it deletes listed, and `--push` when a branch is `PUSH_THEN_DELETE`, whether or not you typed it) and carries `--remote` and `--lang` as you gave them; the verdict judges that command, not the one you typed. The end state is only `main` and `<branch>` as local branches, the worktrees of the deleted branches removed, and every remote branch deleted or `NOT_TOUCHED`; a worktree the command never touches (a detached one, or one that holds `main` or another kept branch) is listed in the report. An apply report ends with the run state `COMPLETE` or `PARTIAL`, and for `PARTIAL` with a `Next command:` line, built the same way, with the flags in the order `--apply`, `--discard-ignored`, `--push`, `--remote`, `--lang` (`--remote` and `--lang` as you gave them, `--push` when a branch ended `PUSH_THEN_DELETE`, or `PENDING_PUSH` because the push was skipped, failed or was not confirmed, but not when `<branch>` is the remote default); the line is left out when no rerun would change anything.

Examples: `/git-sweep agent/release`, `$git-sweep agent/release --apply`, `$git-sweep agent/release --apply --push`, `$git-sweep agent/release --apply --remote upstream`, `$git-sweep --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-sweep` in the user's message.
- Plugin installs prefix the name with the plugin name: `/magos:git-sweep` in Claude Code and Hermes, `$magos:git-sweep` in Codex. The arguments follow it the same way (Claude Code appends them as `ARGUMENTS: ...`).
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. If the branch is missing, show this help and ask for it; for an unknown option, explain the error and show this help. Do not inspect or change the repository in these error cases. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Claude Code keeps the model from invoking this adapter through `disable-model-invocation: true` in its frontmatter, and Codex disables implicit selection for it through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-sweep` command (Hermes renders it as "The user has invoked the "git-sweep" skill" followed by the arguments) or `$git-sweep` in Codex. With a plugin install, the user's `/magos:git-sweep` (Claude Code, Hermes) or `$magos:git-sweep` (Codex) is the same explicit invocation; in Claude Code, the `/magos:Git*` command of the same name is the preferred form. If this adapter was selected without such an invocation, preview at most and merge, delete, and push nothing.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` sections **7. GitSweep** and **6. GitConverge**: command contract, classifications, gates, and apply procedure (GitSweep reuses the GitConverge procedure unchanged).
3. `../../references/reconnaissance.md` and `../../references/decision-matrix.md`: inspection steps and cleanup criteria.

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line (when the skill was loaded with `skill_view` instead of a slash command, from the `skill_dir` field it returns), go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` (`magos:git-orchestrator` under a Hermes plugin install) and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and do not merge, switch, delete, or push anything; a read-only preview is still allowed.

## Execution

Execute the canonical `/GitSweep` command only when the user explicitly invoked this command skill. Preview by default; merge and delete only when the explicit command includes `--apply` and every gate still passes, and record the full plan first (the converge plan plus every remote candidate with its SHA) and include it in the final report. Stop on a conflict and delete nothing, locally or remotely. The only pushes allowed are the deletion of one named, fully merged remote branch at a time, guarded by `--force-with-lease` on its recorded SHA, and, only with `--push`, the one fast-forward push of `<branch>`, run only after the converge phase finished and its validation did not fail; a skipped or failed push is reported and never retried with another command. Never push other commits or tags, never force-push, never use `--no-verify`, `--mirror` or `--prune`, never run `git remote prune` or `git fetch --prune`, never use `git branch -D` or `git worktree remove --force`, never run a repository-wide `git worktree prune`. Ask for a branch if none is provided. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
