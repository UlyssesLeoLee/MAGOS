# recommend-goal-lang

- Prompt: `/GitRecommend which branches --lang English should merge first`
- Result: **PASS**

## Checks

- PASS preview changes no ref, worktree, or file
- PASS invariant: main did not move
- PASS invariant: tags unchanged
- PASS invariant: remote unchanged
- PASS invariant: remote-tracking refs unchanged
- PASS invariant: no merge left in progress
- PASS the reply is in English
- PASS command policy: no forbidden git command and read-only preview
