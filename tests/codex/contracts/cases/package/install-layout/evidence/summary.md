# package/install-layout

- Skill: `package`
- Feature: Codex and Hermes installs, and a git clone of the repository into a host skills directory, contain every file the adapters reference, and a replica of each host's discovery rules finds every skill once
- Result: **PASS**

## Expected behavior

- sync_hosts.py installs the full package (SKILL.md, references/, skills/) for Codex and Hermes.
- Every ../../ reference in an adapter and every references/ link in SKILL.md resolves inside the installed tree.
- No adapter routes through commands/; all eight adapters set policy.allow_implicit_invocation: false.
- Each skill name appears exactly once in the Codex and Hermes discovery replicas.
- Every installed SKILL.md frontmatter is inside the strict YAML subset (no flow style, no ': ' in plain values, string-only metadata) and reads the same under PyYAML when it is installed.
- Over the tracked files of a git checkout, the Codex and Hermes replicas also find each skill exactly once.
- No tracked .codex-plugin, .claude-plugin, or .cursor-plugin directory exists; Codex would treat a git-clone install as a plugin root and rename its skills to magos:<name>.

## Contract checks

- PASS `install:sync_hosts.py --apply --create-roots`
- PASS `install:roots stay inside the temporary home`
- PASS `install:codex relative references resolve`
- PASS `install:codex adapters do not route through commands/`
- PASS `install:codex adapters disable implicit invocation`
- PASS `install:codex discovery replica finds each skill once`
- PASS `install:codex every installed SKILL.md is strict YAML with string-only metadata`
- PASS `install:hermes relative references resolve`
- PASS `install:hermes adapters do not route through commands/`
- PASS `install:hermes adapters disable implicit invocation`
- PASS `install:hermes discovery replica finds each skill once`
- PASS `install:hermes every installed SKILL.md is strict YAML with string-only metadata`
- PASS `install:synced Codex and Hermes packages carry no host plugin manifest`
- PASS `install:git-clone checkout, the Codex and Hermes replicas find each skill once`
- PASS `install:git-clone checkout has no host plugin manifest other than .claude-plugin/plugin.json and .claude-plugin/marketplace.json`
- PASS `install:git-clone checkout's .claude-plugin/plugin.json is the Claude Code manifest of plugin.json`
- PASS `install:.claude-plugin/marketplace.json lists this repository root as the one plugin magos`
- PASS `install:plugin.yaml is the Hermes native manifest of plugin.json, and __init__.py registers skills/`

Evidence scope: source-contract check; no AI host CLI is invoked.
