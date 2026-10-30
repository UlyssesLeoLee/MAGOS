# git-sweep/one-shot-readiness

- Skill: `git-sweep`
- Feature: A preview ends with a readiness verdict, the recommended command and the remedy of every remaining item; an apply ends with its run state
- Result: **PASS**

## Expected behavior

- The preview ends with ONE_SHOT (one run of the recommended command reaches the end state), PARTIAL (something remains that no flag lifts) or BLOCKED (a gate fails and nothing can run); the verdict judges the recommended command, not the command as typed.
- The end state is only main and <branch> as local branches, the worktrees of the deleted branches removed, and every remote branch deleted or NOT_TOUCHED; it leaves out a worktree the command never touches (a detached one, or one that holds main or another kept branch), and the report lists it.
- The recommended command is the /GitSweep <branch> --apply line, with --remote and --lang as given, and exactly the flags that lift something: --discard-ignored with the ignored paths it deletes listed, --push (whether or not it was typed) when a remote branch is PUSH_THEN_DELETE, and also a typed --push whose publish prediction says the push will run, with the publish prediction; a typed --push that cannot run is dropped from the line and the report says why; otherwise a flag that lifts nothing is never recommended and none is added silently.
- Every failed gate is reported at once with its remedy, in /GitConverge and in /GitSweep (a --remote that git remote does not list included), and every blocker, UNKNOWN, PREDICTED_CONFLICT and PREDICTED_IGNORED_OVERLAP is followed by the action that lifts it.
- A PUSH_THEN_DELETE branch kept for want of --push has the remedy rerun with --push (the Next preview: line, then the Next command: line) or, once local <branch> holds its tip, push <branch> by hand; a PENDING_PUSH branch has the remedy clear the condition the report names (publish the remote default by hand, fetch and merge a newer remote tip, or the rows of an UNKNOWN phase 2); a KEPT_NOT_MERGED branch is merged by the user and then recommended with --apply --push by the next preview.
- The apply report ends with the run state COMPLETE or PARTIAL and, for PARTIAL, two lines in this order: Next preview: (the same line without --apply, so that the preview becomes the earlier plan after the remedies) and Next command: (the line to run after that preview; when the preview recommends another line, run the recommended one). Both carry --remote and --lang as given and their flags in the order --apply, --discard-ignored, --push, --remote, --lang; Next command: carries --push when a remote branch ended PUSH_THEN_DELETE or PENDING_PUSH for a reason that a rerun with --push can clear, or when --push was typed and the publish prediction says the push would still run, never when the only reason is that <branch> is the remote default, and with phase 2 UNKNOWN only when it was typed; both lines are left out when no rerun would change anything.
- A preview computes the remote classification and the will-remain set as if the recommended command had been typed (a worktree whose only blocker is ignored files counts as lifted when --discard-ignored is recommended), and an apply uses the flags it was given.

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
- PASS `references/commands.md`
- PASS `commands/GitSweep.md`
- PASS `skills/git-sweep/SKILL.md`
- PASS `README.md`
- PASS `README.en.md`
- PASS `README.ja.md`
- PASS `references/pressure-tests.md`

Evidence scope: source-contract check; no AI host CLI is invoked.
