# ignored-nonascii-no-overlap

- Title: An ignored non-ASCII directory does not stop an unrelated non-ASCII change
- Mode: apply
- Result: **PASS**

## Checks

- PASS the source content was merged
- PASS the source branch was deleted
- PASS the ignored local file is intact
- PASS invariant: main did not move
- PASS invariant: tags unchanged
- PASS invariant: remote unchanged
- PASS invariant: remote-tracking refs unchanged
- PASS invariant: no merge left in progress
- PASS the run did not stop
- PASS command policy: no forbidden git command
