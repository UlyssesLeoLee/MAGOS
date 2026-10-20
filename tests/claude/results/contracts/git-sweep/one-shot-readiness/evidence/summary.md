# git-sweep/one-shot-readiness

- Skill: `git-sweep`
- Feature: A preview ends with a readiness verdict, the recommended command and the remedy of every remaining item; an apply ends with its run state
- Result: **PASS**

## Expected behavior

- The preview ends with ONE_SHOT (one run of the recommended command reaches the end state), PARTIAL (something remains that no flag lifts) or BLOCKED (a gate fails and nothing can run); the verdict judges the recommended command, not the command as typed.
- The end state is only main and <branch> as local branches, the worktrees of the deleted branches removed, and every remote branch deleted or NOT_TOUCHED; it leaves out a worktree the command never touches (a detached one, or one that holds main or another kept branch), and the report lists it.
- The recommended command is the /GitSweep <branch> --apply line, with --remote and --lang as given, and exactly the flags that lift something: --discard-ignored with the ignored paths it deletes listed, --push (whether or not it was typed) when a remote branch is PUSH_THEN_DELETE, with the publish prediction; a flag that lifts nothing is never recommended and none is added silently.
- Every failed gate is reported at once with its remedy, in /GitConverge and in /GitSweep (a --remote that git remote does not list included), and every blocker, UNKNOWN and PREDICTED_CONFLICT is followed by the action that lifts it.
- A PUSH_THEN_DELETE branch kept for want of --push has the remedy rerun with --push (or push <branch> by hand); a PENDING_PUSH branch has the remedy clear the condition the report names (publish the remote default by hand, fetch and merge a newer remote tip, or the rows of an UNKNOWN phase 2).
- The apply report ends with the run state COMPLETE or PARTIAL and, for PARTIAL, a Next command: line with the exact line to run after the remedies, carrying --remote and --lang as given and --push when a branch ended PUSH_THEN_DELETE or PENDING_PUSH because the publish was skipped, failed or unconfirmed (not when <branch> is the remote default); the flags of the recommended command and of that line come in the order --apply, --discard-ignored, --push, --remote, --lang, and the line is left out when no rerun would change anything.

## Contract checks

- PASS `references/commands.md`
- PASS `references/commands.md`
- PASS `references/commands.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `SKILL.md`
- PASS `references/pressure-tests.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`
- PASS `CHANGELOG.md`
- PASS `RELEASE_NOTES_1.0.3.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
