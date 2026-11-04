---
name: git-protect
description: "保护分支；/git-protect [BRANCH] [--release|--status] [--lang <language>] [--help]."
license: Apache-2.0
disable-model-invocation: true
user-invocable: false
metadata:
  short-description: "保护分支；$git-protect [BRANCH] [--release] [--status] [--help]."
---

# GitProtect

Command adapter for the canonical `/GitProtect` command of the MAGOS (Multi-Agent Git Orchestrator) package. It sets or lifts the protection of a branch, which makes the guard's hook refuse every commit, merge and other write to that branch that an agent makes. Use it only when the user explicitly invokes `/git-protect` in Hermes or `$git-protect` in Codex.

## Usage

- Hermes: `/git-protect [<branch>] [--release | --status] [--lang <language>] [--help]`
- Codex: `$git-protect [<branch>] [--release | --status] [--lang <language>] [--help]`

Forms (`--lang <language>` and `--help` go with every form; written for Hermes, Codex uses `$git-protect` in place of `/git-protect`):

- `/git-protect <branch>`: protect `<branch>`: from then on the guard's hook refuses every commit, merge and other write to it that an agent makes. The host asks you to approve it first.
- `/git-protect <branch> --release`: lift the protection of `<branch>`. The host asks you to approve it first.
- `/git-protect` and `/git-protect --release`: the same for the branch checked out in the current worktree (`git branch --show-current`); a detached HEAD stops the command and asks for a branch name.
- `/git-protect --status [<branch>]`: list the protected branches of the repository and, with `<branch>`, say whether it is protected (read-only).

Arguments and options:

- `<branch>`: Optional. The local branch name, as `git branch` shows it (`main`, not `refs/heads/main`). Without it, the branch checked out in the current worktree. A branch that does not exist yet can be protected: the name is what is stored. Names are compared ignoring case.
- `--release`: Lift the protection instead of setting it.
- `--status`: Read-only: print the protections of the repository (`magos_guard.py protect-show`); nothing is written and nothing is approved.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this inline usage and argument description, then stop without inspecting or changing the repository.
- Default: Set the protection of the branch through the guard's user-only subcommand `protect`, which runs only after you approve it in the host's own prompt (or in your own terminal); then print the protections of the repository.

A protection belongs to the repository and holds in every worktree of it. While a branch is protected, the guard's hook refuses an agent's commit (also `--amend`), merge (also the merge a pull makes), cherry-pick, revert, rebase, reset, am, `update-ref`, `branch -f/-m/-M/-d/-D`, `checkout -B` / `switch -C`, `worktree add` of it, a fetch or push into it from this repository's own local path (a push to a remote host, `gh pr merge` and a branch of another clone are not covered) and a write whose target the hook cannot read; reading the branch, checking it out in an existing worktree and creating other branches from it stay allowed. Only you set or lift a protection: `protect` is a user-only guard subcommand like `arm` and `disarm`, approved by your click in the host's prompt or run in your own terminal, at every approval level, `--release` included. Your own terminal, programs the agent's tools do not start and Git itself are not affected: the protection is enforced by the host hook only, and `git config --local magos.guard off` switches it off for the repository.

Examples: `/git-protect main`, `$git-protect develop --release`, `$git-protect`, `$git-protect --status`, `$git-protect --status main --lang English`, `$git-protect --help`.

## Arguments

- Codex: the arguments are the text that follows `$git-protect` in the user's message.
- Plugin installs prefix the name with the plugin name: `/magos:git-protect` in Hermes, `$magos:git-protect` in Codex; Claude Code hides this adapter and offers the command `/magos:GitProtect` instead. The arguments follow the name the same way.
- Hermes: the arguments are the instruction Hermes appends after the skill content, introduced by "The user has provided the following instruction alongside the skill invocation:" (single command) or `User instruction:` (stacked commands). An empty instruction means no arguments.

If `--help` is present, even with other arguments, answer from the inline Usage section above and stop before any tool call, file read, or repository inspection. For an unknown option, more than one branch, or `--release` together with `--status`, explain the error and show this help. Do not inspect or change the repository in these error cases. Read the shared files below only for a normal invocation.

## Explicit invocation only

A semantic match or automatic skill selection is not authorization to write. Claude Code keeps the model from invoking this adapter through `disable-model-invocation: true` in its frontmatter, and Codex disables implicit selection for it through `agents/openai.yaml`; Hermes has no per-skill switch, so this rule applies there by instruction. An explicit invocation is the user's `/git-protect` command (Hermes renders it as "The user has invoked the "git-protect" skill" followed by the arguments) or `$git-protect` in Codex. With a plugin install, the user's `/magos:git-protect` (Hermes) or `$magos:git-protect` (Codex) is the same explicit invocation; Claude Code hides this adapter, and there the user's `/magos:GitProtect` command is the explicit invocation. If this adapter was selected without such an invocation, run at most `protect-show` and set or lift no protection.

## Shared files

This adapter belongs to the MAGOS package. The shared files are in the package root, two directories above this skill's directory:

1. `../../SKILL.md`: shared orchestration rules and safety invariants.
2. `../../references/commands.md` section **9. GitProtect**: command contract, the guard calls, the approval routes, exit codes and output.
3. `../../references/lane-split.md`: the lane guard `magos_guard.py`, its user-only subcommands and approval routes (section 3, rule 4, and section 6), and what a protection refuses (section 15).

Locate them as follows:

- Codex: resolve the paths relative to the directory that contains this `SKILL.md`.
- Hermes: take the absolute path from the `[Skill directory: ...]` line (when the skill was loaded with `skill_view` instead of a slash command, from the `skill_dir` field it returns), go up two directories, and read the files with the file or terminal tool. The skill viewer rejects paths that contain `..`. Alternatively, load the skill `multi-agent-git-orchestrator` (`magos:git-orchestrator` under a Hermes plugin install) and view its files under `references/`.
- Other hosts: resolve the paths relative to this file.

Do not use `commands/*.md` for this adapter. Those files are Claude Code slash-command wrappers with Claude-specific loading steps.

If `../../SKILL.md` or `../../references/commands.md` cannot be read, name the missing path, report that the MAGOS installation is incomplete, and set or lift no protection; `--status` is still allowed.

## Execution

Execute the canonical `/GitProtect` command only when the user explicitly invoked this command skill. `--status` only reads: run `magos_guard.py protect-show` and print its result. To set or lift a protection, resolve the branch first (the argument, else `git branch --show-current`; empty output is a detached HEAD: stop and ask for a branch name), show the current protections with `protect-show`, then run the user-only subcommand `magos_guard.py --repo '<top>' protect --branch <branch>` (`<top>` is the absolute top level of the worktree; add `--release` to lift) by the approval route of the host: in Codex call the MCP tool `magos_approve` of the server `magos` with `subcommand` `protect`, `repo`, `branch` and `release` (true for `--release`), and Codex shows the user its own dialog; in Hermes run it with the `terminal` tool as one direct invocation of the guard script, in the foreground, without a pseudo-terminal and with nothing else on the line, and the MAGOS plugin hands Hermes the question for the user. Never pass `--approval`. When there is no prompt (`magos.approval` is `terminal`, Codex's approval policy is `never`, the tool `magos_approve` is not available, Hermes approves without a human, or the guard denies the call), print the command for the user's own terminal and run nothing. Report the guard's result (the branch, the stored spelling, whether the record changed, and the protected branches after the call) and quote a refusal with its exit code as `references/commands.md` section 9 states. Never write `.git/magos` or `protected.json` yourself, never run `override`, `arm`, `disarm` or `install`, never write `magos.*` config, and never retry a refused or declined `protect` in another form. This command never commits, merges, creates, switches, deletes or pushes a branch. When the guard later refuses a write to a protected branch, report the refusal and work on another branch; never lift the protection to make a write pass. Reply in the language selected by `--lang` (Chinese when absent); never translate commands, options, branch names, paths, SHAs, or status codes. Remove `--lang` and its value from the arguments before parsing the rest.
