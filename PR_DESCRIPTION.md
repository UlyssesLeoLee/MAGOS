# Add MAGOS (Multi-Agent Git Orchestrator) to the Hermes plugin catalog

## Summary

Add `magos` as a community plugin. MAGOS helps developers coordinate multiple AI coding agents sharing Git repositories. It provides an orchestration skill and eight named command skills for branch/worktree reconnaissance, analysis, recommendations, integration, cleanup, convergence, remote cleanup, and lane planning.

- Upstream repository: https://github.com/UlyssesLeoLee/MAGOS
- Catalog entry: `plugin-catalog/magos.yaml`
- Version: `1.0.5`
- Pinned commit: `071e9c6a75a10a59d4ca1252067c293ea0684257`

## Hermes integration surface

The native `plugin.yaml` and `__init__.py` register skills with `ctx.register_skill`. The Hermes plugin entrypoint does not register custom tools, hooks, middleware, providers, or environment-variable requirements. The repository additionally contains Claude Code-specific hooks; these are not registered as Hermes hooks by its native entrypoint.

## Security and behavior disclosures

- **Local repository reads:** MAGOS relies on Git commands for local branch, commit, worktree, merge-base, diff and status inspection. The optional guard examines tool-call text and local repository metadata.
- **Local writes:** Repository-changing commands operate only on explicit user instruction (and require confirmation/apply where documented). The guard can write local lane claims, plans, overrides, approval records (`<git-common-dir>/magos/approvals/`), denial records (`<git-common-dir>/magos/denials/`), and audit logs under the repository's Git common directory (`<git-common-dir>/magos/`), including Git user metadata and reason strings; the approval records of `install` live in `<guard home>/approvals/` (`MAGOS_HOME`, else `~/.magos`). The guard installer copies files to `~/.magos/guard` and runs only with the user's approval: a click in Claude Code's permission dialog, or the user's own terminal (at `magos.approval` `auto-safe`, an install into the default guard home without `--allow-downgrade` runs without a click). Optional `arm` adds a Git reference-transaction hook.
- **Shell and subprocess:** The optional guard uses Python and local Git subprocesses. MAGOS instructions can lead to user-authorized Git actions; these are not automatically executed by the plugin's Hermes `register` function.
- **Network:** The optional guard itself does not send telemetry or make network requests. Users can expressly request Git remote operations (e.g. `git fetch --prune` via `--remote`, or remote branch modifications via relevant `--apply`/`--push` commands), which communicate with their configured Git remotes.
- **Credentials:** No credentials are collected or stored by the MAGOS guard, and the Hermes native plugin does not request API credentials.
- **Background services:** No always-on background service is registered by the Hermes native entrypoint.
- **Updates:** The pinned package does not automatically fetch and replace its own files. Catalog updates should happen only by separately reviewed SHA-bump PRs.

MAGOS documentation explains explicit operations, the local audit trail, opt-out controls, and the need for user approval before repository changes. The admission security scan may flag scripts for reviewer inspection; please review the scanned code at the pinned SHA.

## Validation

- [ ] `hermes plugins validate <local-checkout-at-pinned-sha> --install-deps` passes
- [ ] Security-scan warnings have been reviewed and disclosed
- [ ] The pinned SHA matches the public `plugin.yaml` version
- [ ] Catalog CI passes

**Note:** Local Hermes CLI validation has not been executed as part of preparing this submission.

## Screenshots

Not applicable: MAGOS has no custom Hermes user interface.
