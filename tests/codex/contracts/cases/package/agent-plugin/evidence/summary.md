# package/agent-plugin

- Skill: `package`
- Feature: The repository is a conformant Agent Plugins 1.0.0 package whose discovered skills meet Agent Skills
- Result: **PASS**

## Expected behavior

- plugin.json validates against the closed 1.0.0 manifest schema: exact $schema, lowercase name, no other fields.
- plugin.json version equals SKILL.md metadata.version as x.y.z, and references/commands.md states the same version.
- Plugin discovery (skills/<dir>/SKILL.md, one level) finds exactly the eight command adapters and the git-orchestrator entry skill; the root orchestrator SKILL.md is package content they read, not a plugin skill.
- Every discovered skill, and the root SKILL.md, meets Agent Skills: strict YAML, allowed fields only, name equal to its directory (the root as multi-agent-git-orchestrator), description 1-1024, string-only metadata, no metadata.hermes, and double-quoted description, compatibility, and metadata values.
- Every ../ reference in an adapter resolves to a file inside the plugin root, and the package holds no symbolic links or junctions.
- mcp.json is valid when present (the package ships one, which declares the approval server magos that Codex starts): exactly $schema (1.0.0) and an mcpServers object, each server an object with only the keys Codex accepts, and a server that starts a command of type stdio.

## Contract checks

- PASS `plugin: plugin.json is a valid Agent Plugins 1.0.0 manifest`
- PASS `plugin: manifest version matches SKILL.md metadata.version and references/commands.md`
- PASS `plugin: the entry skill's metadata.version and the guard's GUARD_VERSION equal the manifest version`
- PASS `plugin: skills/ discovery (§7.1) finds exactly the eight command adapters and git-orchestrator`
- PASS `plugin: every discovered skill meets Agent Skills (strict YAML, allowed fields, name = directory, string-only metadata)`
- PASS `plugin: root SKILL.md (not a plugin skill) meets the same Agent Skills rules`
- PASS `plugin: the eight command adapters set user-invocable: false and disable-model-invocation: true, the entry skill sets user-invocable: false only (Claude Code lists the eight commands/ entries alone), and the root SKILL.md sets neither`
- PASS `plugin: package paths stay inside the plugin root and include no links (§4.1)`
- PASS `plugin: mcp.json is absent or valid (§7.2)`

Evidence scope: source-contract check; no AI host CLI is invoked.
