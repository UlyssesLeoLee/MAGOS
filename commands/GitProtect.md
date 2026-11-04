---
description: 保护分支，拒绝代理对它的提交与合并；设置与解除只经用户批准，--status 只读
argument-hint: "[<branch>] [--release | --status] [--lang <language>] [--help]"
disable-model-invocation: true
---

Handle `--help` first, even if other arguments are present. `--lang <language>` never changes what you do; it only sets the language of everything you write back, this help included (Chinese when absent; translate the explanations but never flags, commands, or examples). Answer solely from the inline help below, then stop before any tool call, file read, skill load, or repository inspection. For an unknown option, more than one branch, or `--release` together with `--status`, explain the error, show this help, and stop.

## Inline help

Usage: `/GitProtect [<branch>] [--release | --status] [--lang <language>] [--help]`

Forms (`--lang <language>` and `--help` go with every form):

- `/GitProtect <branch>`: protect `<branch>`: from then on the guard's hook refuses every commit, merge and other write to it that an agent makes. The host asks you to approve it first.
- `/GitProtect <branch> --release`: lift the protection of `<branch>`. The host asks you to approve it first.
- `/GitProtect` and `/GitProtect --release`: the same for the branch checked out in the current worktree (`git branch --show-current`); a detached HEAD stops the command and asks for a branch name.
- `/GitProtect --status [<branch>]`: list the protected branches of the repository and, with `<branch>`, say whether it is protected (read-only).

Arguments and options:

- `<branch>`: Optional. The local branch name, as `git branch` shows it (`main`, not `refs/heads/main`). Without it, the branch checked out in the current worktree. A branch that does not exist yet can be protected: the name is what is stored. Names are compared ignoring case.
- `--release`: Lift the protection instead of setting it.
- `--status`: Read-only: print the protections of the repository (`magos_guard.py protect-show`); nothing is written and nothing is approved.
- `--lang <language>`: Language of the reply, as a name or code (for example `English`, `ja`); Chinese when absent. Command names, options, branch names, paths, SHAs, and status codes stay untranslated.
- `--help`: Show this help and stop without inspecting or changing the repository.
- Default: Set the protection of the branch through the guard's user-only subcommand `protect`, which runs only after you approve it in the host's own prompt (or in your own terminal); then print the protections of the repository.

A protection belongs to the repository and holds in every worktree of it. While a branch is protected, the guard's hook refuses an agent's commit (also `--amend`), merge (also the merge a pull makes), cherry-pick, revert, rebase, reset, am, `update-ref`, `branch -f/-m/-M/-d/-D`, `checkout -B` / `switch -C`, `worktree add` of it, a fetch into it (a refspec on the line or one configured in `remote.<name>.fetch`), a push into it through a local repository (a push to a remote host, `gh pr merge` and a branch of another clone are not covered) and a write whose target the hook cannot read; reading the branch, checking it out in an existing worktree and creating other branches from it stay allowed. Only you set or lift a protection: `protect` is a user-only guard subcommand like `arm` and `disarm`, approved by your click in the host's prompt or run in your own terminal, at every approval level, `--release` included. Your own terminal, programs the agent's tools do not start and Git itself are not affected: the protection is enforced by the host hook only. It is an accident guard for the ordinary spellings of git and the shell, not a boundary against deliberate evasion (settings that run a program, URL rewriting and the other limits of `references/lane-split.md` section 15). `git config --local magos.guard off` does not switch it off; only `MAGOS_GUARD=off` in the host process and `--release` do.

Examples: `/GitProtect main`, `/GitProtect develop --release`, `/GitProtect`, `/GitProtect --status`, `/GitProtect --status main --lang English`, `/GitProtect --help`.

For a normal invocation, run the Multi-Agent Git Orchestrator command `/GitProtect $ARGUMENTS`.

1. Load the orchestrator skill with the Skill tool. It may be listed as `magos` (plugin clone directory), `MAGOS` (install directory), `multi-agent-git-orchestrator` (frontmatter name), or `MAGO-Skill` (older clone directory); any listed skill described as the Multi-Agent Git Orchestrator is the same skill. Under the `magos` plugin (marketplace install or a clone in `~/.claude/skills/magos`) it is listed as `magos:git-orchestrator`, an entry skill that points to the package-root `SKILL.md`; load it and follow that file. The other `magos:git-*` skills and the `magos:Git*` commands are command entry points, not this skill: never load them here. If none is listed but `~/.claude/skills/magos/SKILL.md` or `~/.claude/skills/MAGOS/SKILL.md` exists, read that file instead. Only if the skill cannot be loaded at all, tell the user, then continue read-only only: run at most `protect-show`, and set or lift no protection.
2. Execute `/GitProtect` exactly as defined in the skill's **Explicit Command Interface** and `references/commands.md` section **9. GitProtect**. Write every reply in the language selected by `--lang` (Chinese when absent).
   Arguments (may be empty): $ARGUMENTS
3. Inspect the current repository before giving any state-dependent advice.
4. Before you write the final report, check the reply language again: it is the language selected by `--lang` (Chinese when absent), including headings, tables, and the closing summary.

Safety default: `--status` only reads. To set or lift a protection, resolve the branch first (the argument, else `git branch --show-current`; empty output is a detached HEAD: stop and ask for a branch name), show the current protections with `magos_guard.py protect-show`, then run `magos_guard.py --repo '<top>' protect --branch <branch>` (`<top>` is the absolute top level of the worktree; add `--release` to lift) as one direct invocation of the guard script with the `Bash` or `PowerShell` tool, with nothing else on the line, so that the host asks the user; never pass `--approval`, and if the hook denies the call (approval level `terminal`, or no prompt), print the command for the user's own terminal and run nothing. If the skill could not be loaded, set or lift nothing. Never write `.git/magos` or `protected.json` yourself, never run `override`, `arm`, `disarm` or `install`, never write `magos.*` config, and never retry a refused or declined `protect` in another form. This command never commits, merges, creates, switches, deletes or pushes a branch. When the guard later refuses a write to a protected branch, report the refusal and work on another branch; never lift the protection to make a write pass. Reply language: Chinese unless `--lang` selects another one; this includes the final report.
