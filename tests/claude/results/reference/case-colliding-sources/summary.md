# case-colliding-sources

- Title: Two local branches whose names differ only in case are kept unmerged; others converge
- Mode: apply
- Result: **PASS**

## Checks

- PASS agent/Feat is kept at its tip
- PASS agent/feat is kept at its tip
- PASS agent/Feat's commit was not merged
- PASS the ordinary source was merged and deleted
- PASS invariant: main did not move
- PASS invariant: tags unchanged
- PASS invariant: remote unchanged
- PASS invariant: remote-tracking refs unchanged
- PASS invariant: no merge left in progress
- PASS both colliding names are UNKNOWN
- PASS each colliding name records its own tip
- PASS command policy: no forbidden git command
