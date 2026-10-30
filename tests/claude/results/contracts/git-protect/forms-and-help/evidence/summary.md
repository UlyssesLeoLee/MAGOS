# git-protect/forms-and-help

- Skill: `git-protect`
- Feature: The forms of /GitProtect set, lift or show the protection of a branch; help stops before any inspection and a wrong combination executes nothing
- Result: **PASS**

## Expected behavior

- The usage line and the argument hint list every option: /GitProtect [<branch>] [--release | --status] [--lang <language>] [--help].
- Without a branch the command takes git branch --show-current, and a detached HEAD stops it and asks for a branch name; a branch that does not exist yet can be protected.
- --help (and --lang) is handled first: the command shows its inline help and stops before any tool call; an unknown option, more than one branch or --release with --status is a usage error that executes nothing.
- --status runs only the read-only guard subcommand protect-show; setting and lifting run the user-only subcommand protect.

## Contract checks

- PASS `commands/GitProtect.md`
- PASS `skills/git-protect/SKILL.md`
- PASS `references/commands.md`
- PASS `SKILL.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
