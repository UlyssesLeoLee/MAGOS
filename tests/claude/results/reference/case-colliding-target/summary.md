# case-colliding-target

- Title: A branch named like the target except for case stops the command
- Mode: apply
- Result: **PASS**

## Checks

- PASS a stopped command changes nothing
- PASS invariant: main did not move
- PASS invariant: tags unchanged
- PASS invariant: remote unchanged
- PASS invariant: remote-tracking refs unchanged
- PASS invariant: no merge left in progress
- PASS the gate is NAME_CASE_COLLISION
- PASS command policy: no forbidden git command
