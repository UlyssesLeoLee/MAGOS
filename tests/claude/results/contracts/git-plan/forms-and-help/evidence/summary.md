# git-plan/forms-and-help

- Skill: `git-plan`
- Feature: The nine forms of /GitPlan are chosen by one selecting option; help stops before any inspection and a wrong combination executes nothing
- Result: **PASS**

## Expected behavior

- The usage line and the argument hint list every option, and the nine forms are chosen by exactly one selecting option: --into, --status, --amend, --converge or --release.
- The set name is [a-z0-9][a-z0-9-]{0,23}, matched case-sensitively and never a Windows device name; --into names a local branch that is not main; --amend needs --expect-revision.
- --help (and --lang) is handled first: the command shows its inline help and stops before any tool call, file read, skill load or repository inspection; a missing set name is asked for, and an unknown option, two selecting options or an option the form does not list is a usage error that executes nothing.
- Without --apply (and without --release) the command only previews: nothing is registered, created or merged, nothing is fetched, and the only write is a scratch spec file outside every worktree.
- The hosts spell the same forms (/GitPlan in Claude Code, /git-plan in Hermes, $git-plan in Codex) and the three READMEs show the same examples.
- Every form that shows the plan prints the Requirements table and the Lanes table (with State and Head once the plan has state, and with the changes of every lane once a lane is integrated), rendered from the guard's result or from its record and never from memory; the inline help of the Claude Code command and of the Hermes and Codex adapters says so in every form.

## Contract checks

- PASS `commands/GitPlan.md`
- PASS `skills/git-plan/SKILL.md`
- PASS `references/commands.md`
- PASS `SKILL.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
