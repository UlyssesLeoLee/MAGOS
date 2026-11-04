# Repository conventions

- Run runtime tests in the project-folder test worktree, separate from the `.codex` `develop_codex` worktree. Keep test cases and evidence under `tests/codex`; merge the tested changes and evidence into `develop_codex` only after test results are available, then integrate to `main`.
