# recon-lang-missing

- Prompt: `/GitRecon --lang`
- Result: **PASS**

## Checks

- PASS preview changes no ref, worktree, or file
- PASS invariant: main did not move
- PASS invariant: tags unchanged
- PASS invariant: remote unchanged
- PASS invariant: remote-tracking refs unchanged
- PASS invariant: no merge left in progress
- PASS the reply is in Chinese (the default)
- PASS no git command was run (the command must not execute)
- PASS command policy: no forbidden git command and read-only preview
