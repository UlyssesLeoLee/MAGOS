# Handoff and State

## Lane State Machine

```text
PLANNED
  |
ACTIVE
  |
READY -----\
  |         -> BLOCKED
APPROVED --/ 
  |
INTEGRATING
  |
INTEGRATED

READY/APPROVED may also -> REJECTED
```

### State ownership

- Worker may move `PLANNED -> ACTIVE -> READY` by producing evidence.
- Reviewer/verifier may return `READY -> ACTIVE/BLOCKED`.
- Orchestrator owns `APPROVED`, `INTEGRATING`, `INTEGRATED`, and integration selection.
- Any material code change after approval invalidates `APPROVED`.
- Any material target-branch change requires freshness evaluation before integration.

## Minimal Lane Record

```yaml
lane_id: TASK-123-auth
owner: agent-a
state: ACTIVE
branch: agent/TASK-123-auth
worktree: <path-or-harness-id>
base_branch: main
base_sha: <sha>
head_sha: <sha>
dependencies: []
acceptance_criteria:
  - <criterion>
validation:
  - command: <command>
    result: pass|fail
known_risks: []
```

## Integration Receipt

After successful integration, record enough data to audit and revert:

```yaml
lane_id: TASK-123-auth
source_head: <sha>
target_before: <sha>
target_after: <sha>
operation: merge|squash-merge|cherry-pick
integrated_commits:
  - <sha>
validation_after_integration:
  - command: <command>
    result: pass
```
