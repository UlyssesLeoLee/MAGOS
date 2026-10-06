# ```cypher
# CREATE
#   (file:File {name: "agent_plugin.py", type: "file", language: "python"}),
#   (v_SCHEMA_URL:Variable {name: "SCHEMA_URL", type: "variable"}),
#   (v_MCP_SCHEMA_URL:Variable {name: "MCP_SCHEMA_URL", type: "variable"}),
#   (v_PLUGIN_SCHEMA:Variable {name: "PLUGIN_SCHEMA", type: "variable"}),
#   (v_ANNOTATIONS:Variable {name: "ANNOTATIONS", type: "variable"}),
#   (v_TYPES:Variable {name: "TYPES", type: "variable"}),
#   (v_EXPECTED_PLUGIN_SKILLS:Variable {name: "EXPECTED_PLUGIN_SKILLS", type: "variable"}),
#   (v_ROOT_SKILL_NAME:Variable {name: "ROOT_SKILL_NAME", type: "variable"}),
#   (v_ALLOWED_FIELDS:Variable {name: "ALLOWED_FIELDS", type: "variable"}),
#   (v_SKILL_NAME:Variable {name: "SKILL_NAME", type: "variable"}),
#   (v_QUOTED_FIELDS:Variable {name: "QUOTED_FIELDS", type: "variable"}),
#   (v_ADAPTER_REFERENCE:Variable {name: "ADAPTER_REFERENCE", type: "variable"}),
#   (f_validate:Function {name: "validate", type: "function", signature: "validate(instance, schema: dict, where: str='$') -> list[str]"}),
#   (f_reject_constant:Function {name: "reject_constant", type: "function", signature: "reject_constant(token: str)"}),
#   (f_load_json:Function {name: "load_json", type: "function", signature: "load_json(path: Path)"}),
#   (f_load_json_pairs:Function {name: "load_json.pairs", type: "function", signature: "pairs(items)"}),
#   (f_is_link:Function {name: "is_link", type: "function", signature: "is_link(path: Path) -> bool"}),
#   (f_is_link_lambda_108_61:Function {name: "is_link.lambda_108_61", type: "function", signature: "lambda_108_61()"}),
#   (f_git_lines:Function {name: "git_lines", type: "function", signature: "git_lines(root: Path, *arguments: str) -> list[str]"}),
#   (f_is_work_tree_root:Function {name: "is_work_tree_root", type: "function", signature: "is_work_tree_root(root: Path) -> bool"}),
#   (f_walk_package:Function {name: "walk_package", type: "function", signature: "walk_package(root: Path, skip: set[str]) -> tuple[list[str], list[str]]"}),
#   (f_tracked_files:Function {name: "tracked_files", type: "function", signature: "tracked_files(root: Path) -> list[tuple[str, str]]"}),
#   (f_skill_md_of:Function {name: "skill_md_of", type: "function", signature: "skill_md_of(directory: Path) -> Path | None"}),
#   (f_adapter_skill_files:Function {name: "adapter_skill_files", type: "function", signature: "adapter_skill_files(root: Path) -> list[Path]"}),
#   (f_skill_problems:Function {name: "skill_problems", type: "function", signature: "skill_problems(skill_md: Path, directory_name: str) -> list[str]"}),
#   (f_check_manifest:Function {name: "check_manifest", type: "function", signature: "check_manifest(root: Path) -> list[str]"}),
#   (f_check_version:Function {name: "check_version", type: "function", signature: "check_version(root: Path) -> list[str]"}),
#   (f_discovered_skills:Function {name: "discovered_skills", type: "function", signature: "discovered_skills(root: Path) -> tuple[list[Path], list[str]]"}),
#   (f_check_containment:Function {name: "check_containment", type: "function", signature: "check_containment(root: Path) -> list[str]"}),
#   (f_check_mcp:Function {name: "check_mcp", type: "function", signature: "check_mcp(root: Path) -> list[str]"}),
#   (f_guarded:Function {name: "guarded", type: "function", signature: "guarded(compute) -> list[str]"}),
#   (f_check:Function {name: "check", type: "function", signature: "check(root: Path) -> list[dict]"}),
#   (f_check_lambda_345_56:Function {name: "check.lambda_345_56", type: "function", signature: "lambda_345_56()"}),
#   (f_check_lambda_344_91:Function {name: "check.lambda_344_91", type: "function", signature: "lambda_344_91()"}),
#   (f_check_lambda_343_9:Function {name: "check.lambda_343_9", type: "function", signature: "lambda_343_9()"}),
#   (f_check_lambda_341_34:Function {name: "check.lambda_341_34", type: "function", signature: "lambda_341_34()"}),
#   (f_check_lambda_338_9:Function {name: "check.lambda_338_9", type: "function", signature: "lambda_338_9()"}),
#   (f_check_lambda_336_72:Function {name: "check.lambda_336_72", type: "function", signature: "lambda_336_72()"}),
#   (f_check_discovery:Function {name: "check.discovery", type: "function", signature: "discovery() -> list[str]"}),
#   (file)-[:CONTAINS]->(v_SCHEMA_URL),
#   (file)-[:CONTAINS]->(v_MCP_SCHEMA_URL),
#   (file)-[:CONTAINS]->(v_PLUGIN_SCHEMA),
#   (file)-[:CONTAINS]->(v_ANNOTATIONS),
#   (file)-[:CONTAINS]->(v_TYPES),
#   (file)-[:CONTAINS]->(v_EXPECTED_PLUGIN_SKILLS),
#   (file)-[:CONTAINS]->(v_ROOT_SKILL_NAME),
#   (file)-[:CONTAINS]->(v_ALLOWED_FIELDS),
#   (file)-[:CONTAINS]->(v_SKILL_NAME),
#   (file)-[:CONTAINS]->(v_QUOTED_FIELDS),
#   (file)-[:CONTAINS]->(v_ADAPTER_REFERENCE),
#   (file)-[:CONTAINS]->(f_validate),
#   (file)-[:CONTAINS]->(f_reject_constant),
#   (file)-[:CONTAINS]->(f_load_json),
#   (f_load_json)-[:CONTAINS]->(f_load_json_pairs),
#   (file)-[:CONTAINS]->(f_is_link),
#   (f_is_link)-[:CONTAINS]->(f_is_link_lambda_108_61),
#   (file)-[:CONTAINS]->(f_git_lines),
#   (file)-[:CONTAINS]->(f_is_work_tree_root),
#   (file)-[:CONTAINS]->(f_walk_package),
#   (file)-[:CONTAINS]->(f_tracked_files),
#   (file)-[:CONTAINS]->(f_skill_md_of),
#   (file)-[:CONTAINS]->(f_adapter_skill_files),
#   (file)-[:CONTAINS]->(f_skill_problems),
#   (file)-[:CONTAINS]->(f_check_manifest),
#   (file)-[:CONTAINS]->(f_check_version),
#   (file)-[:CONTAINS]->(f_discovered_skills),
#   (file)-[:CONTAINS]->(f_check_containment),
#   (file)-[:CONTAINS]->(f_check_mcp),
#   (file)-[:CONTAINS]->(f_guarded),
#   (file)-[:CONTAINS]->(f_check),
#   (f_check)-[:CONTAINS]->(f_check_lambda_345_56),
#   (f_check)-[:CONTAINS]->(f_check_lambda_344_91),
#   (f_check)-[:CONTAINS]->(f_check_lambda_343_9),
#   (f_check)-[:CONTAINS]->(f_check_lambda_341_34),
#   (f_check)-[:CONTAINS]->(f_check_lambda_338_9),
#   (f_check)-[:CONTAINS]->(f_check_lambda_336_72),
#   (f_check)-[:CONTAINS]->(f_check_discovery),
#   (f_adapter_skill_files)-[:CALLS]->(f_skill_md_of),
#   (f_check)-[:CALLS]->(f_guarded),
#   (f_check_containment)-[:CALLS]->(f_adapter_skill_files),
#   (f_check_containment)-[:CALLS]->(f_is_link),
#   (f_check_containment)-[:CALLS]->(f_tracked_files),
#   (f_check_containment)-[:USES]->(v_ADAPTER_REFERENCE),
#   (f_check_discovery)-[:CALLS]->(f_discovered_skills),
#   (f_check_lambda_336_72)-[:CALLS]->(f_check_manifest),
#   (f_check_lambda_338_9)-[:CALLS]->(f_check_version),
#   (f_check_lambda_341_34)-[:CALLS]->(f_skill_problems),
#   (f_check_lambda_343_9)-[:CALLS]->(f_skill_problems),
#   (f_check_lambda_343_9)-[:USES]->(v_ROOT_SKILL_NAME),
#   (f_check_lambda_344_91)-[:CALLS]->(f_check_containment),
#   (f_check_lambda_345_56)-[:CALLS]->(f_check_mcp),
#   (f_check_manifest)-[:CALLS]->(f_load_json),
#   (f_check_manifest)-[:CALLS]->(f_validate),
#   (f_check_manifest)-[:USES]->(v_PLUGIN_SCHEMA),
#   (f_check_mcp)-[:CALLS]->(f_load_json),
#   (f_check_mcp)-[:USES]->(v_MCP_SCHEMA_URL),
#   (f_check_version)-[:CALLS]->(f_load_json),
#   (f_check_version)-[:USES]->(v_ROOT_SKILL_NAME),
#   (f_discovered_skills)-[:CALLS]->(f_adapter_skill_files),
#   (f_discovered_skills)-[:USES]->(v_EXPECTED_PLUGIN_SKILLS),
#   (f_skill_problems)-[:USES]->(v_ALLOWED_FIELDS),
#   (f_skill_problems)-[:USES]->(v_QUOTED_FIELDS),
#   (f_skill_problems)-[:USES]->(v_SKILL_NAME),
#   (f_tracked_files)-[:CALLS]->(f_git_lines),
#   (f_tracked_files)-[:CALLS]->(f_is_work_tree_root),
#   (f_tracked_files)-[:CALLS]->(f_walk_package),
#   (f_validate)-[:USES]->(v_ANNOTATIONS),
#   (f_validate)-[:USES]->(v_TYPES),
#   (f_walk_package)-[:CALLS]->(f_is_link);
# ```
"""Check that the repository is a conformant Agent Plugins 1.0.0 package (standard library only).

Sources: https://agent-plugins.org/specification (1.0.0), the manifest schema below, and the Agent Skills rules at
https://agentskills.io/specification as the reference validator skills-ref codes them. No official Agent Plugins
validator exists, and clients must not fetch schemas while loading (§5.2), so the schema is mirrored here.

Plugin clients discover only skills/<dir>/SKILL.md (§6.1, §7.1). They see the six command adapters; the
orchestrator SKILL.md at the package root is reached through the adapters' ../../ paths and is not a plugin skill.
"""

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

import skill_frontmatter

SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_URL = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
# Mirror of SCHEMA_URL as published for 1.0.0 (the 1.1.0 draft differs only in the $schema constant).
PLUGIN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": SCHEMA_URL,
    "title": "Agent Plugins Manifest",
    "type": "object",
    "properties": {
        "$schema": {"const": SCHEMA_URL},
        "name": {"type": "string", "minLength": 1, "maxLength": 64,
                 "pattern": r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$"},
        "version": {"type": "string"},
        "description": {"type": "string"},
        "author": {"type": "object", "additionalProperties": False, "properties": {
            "name": {"type": "string"}, "email": {"type": "string"}, "url": {"type": "string"}}},
        "homepage": {"type": "string"},
        "repository": {"type": "string"},
        "license": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "extensions": {"type": "object", "additionalProperties": {"type": "object"}},
    },
    "required": ["$schema", "name"],
    "additionalProperties": False,
}
ANNOTATIONS = {"$schema", "$id", "title", "description"}
TYPES = {"object": dict, "string": str, "array": list}

EXPECTED_PLUGIN_SKILLS = ["git-analyze", "git-cleanup", "git-converge", "git-integrate", "git-recommend", "git-recon"]
ROOT_SKILL_NAME = "multi-agent-git-orchestrator"
ALLOWED_FIELDS = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
QUOTED_FIELDS = ("description", "compatibility")
ADAPTER_REFERENCE = re.compile(r"`((?:\.\./)+[A-Za-z0-9_./-]+\.(?:md|yaml))`")


def validate(instance, schema: dict, where: str = "$") -> list[str]:
    """Validate against the subset of JSON Schema that PLUGIN_SCHEMA uses; any other keyword fails closed."""
    unknown = set(schema) - ANNOTATIONS - {"type", "const", "properties", "required", "additionalProperties",
                                            "items", "minLength", "maxLength", "pattern"}
    if unknown:
        raise ValueError(f"schema keyword(s) not implemented: {sorted(unknown)}")
    if "const" in schema and instance != schema["const"]:
        return [f"{where} must equal {schema['const']!r}"]
    if "type" in schema and not isinstance(instance, TYPES[schema["type"]]):
        return [f"{where} must be of type {schema['type']}"]
    problems = []
    if isinstance(instance, str):
        if not schema.get("minLength", 0) <= len(instance) <= schema.get("maxLength", len(instance)):
            problems.append(f"{where} length {len(instance)} is outside the allowed range")
        if "pattern" in schema:
            match = re.search(schema["pattern"], instance)
            if not match or (schema["pattern"].endswith("$") and match.end() != len(instance)):
                problems.append(f"{where} {instance!r} does not match {schema['pattern']}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            problems += validate(item, schema["items"], f"{where}[{index}]")
    if isinstance(instance, dict):
        problems += [f"{where} is missing required field {key!r}" for key in schema.get("required", [])
                     if key not in instance]
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in properties:
                problems += validate(value, properties[key], f"{where}.{key}")
            elif extra is False:
                problems.append(f"{where} has field {key!r}, which the closed schema does not allow")
            elif isinstance(extra, dict):
                problems += validate(value, extra, f"{where}.{key}")
    return problems


def reject_constant(token: str):
    raise ValueError(f"{token} is not valid JSON (RFC 8259 has no NaN or Infinity)")


def load_json(path: Path):
    """Parse strict UTF-8 JSON (no BOM, no NaN/Infinity) and reject duplicate keys, which parsers resolve differently."""
    def pairs(items):
        keys = [key for key, _ in items]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"duplicate key(s) {duplicates}")
        return dict(items)
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def git_lines(root: Path, *arguments: str) -> list[str]:
    """NUL-separated output of a git command run in root; failures and timeouts propagate."""
    output = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, encoding="utf-8",
                            timeout=300, check=True).stdout
    return [item for item in output.split("\0") if item]


def is_work_tree_root(root: Path) -> bool:
    """True when root is the top of a git work tree; False when git is missing or root is not one."""
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             encoding="utf-8", timeout=300, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    return Path(top).resolve() == root.resolve()


def walk_package(root: Path, skip: set[str]) -> tuple[list[str], list[str]]:
    """(files, directory links) below root.

    The walk never enters .git, a nested repository or worktree (git does not list their files either), a path in
    skip (the ignored paths), or a directory link: a link is reported, not followed, so it cannot lead outside root.
    """
    files, links = [], []
    for directory, names, filenames in os.walk(root):
        base = Path(directory)
        keep = []
        for name in names:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if name == ".git" or relative in skip:
                continue
            if is_link(path):
                links.append(relative)
            elif not os.path.lexists(path / ".git"):
                keep.append(name)
        names[:] = keep
        files += [relative for relative in ((base / name).relative_to(root).as_posix() for name in filenames)
                  if relative not in skip]
    return files, links


def tracked_files(root: Path) -> list[tuple[str, str]]:
    """(git mode, relative path) of every file a commit of root would ship, each path once, plus directory links.

    In a git work tree this is the index plus the untracked files git does not ignore, so a new file is checked before
    `git add`; entries missing from the work tree (deleted, sparse checkout) are dropped, and ignored paths are never
    walked. A git failure inside a work tree propagates instead of silently widening the listing. Outside a work tree
    it is a directory walk.
    """
    entries: dict[str, str] = {}
    if is_work_tree_root(root):
        for entry in git_lines(root, "ls-files", "-s", "-z"):
            entries.setdefault(entry.split("\t", 1)[1], entry.split(" ", 1)[0])
        for relative in git_lines(root, "ls-files", "--others", "--exclude-standard", "-z"):
            entries.setdefault(relative, "100644")
        ignored = {path.rstrip("/") for path in
                   git_lines(root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z")}
        _, links = walk_package(root, ignored)
    else:
        files, links = walk_package(root, set())
        for relative in files:
            entries[relative] = "120000" if (root / relative).is_symlink() else "100644"
    for relative in links:
        entries.setdefault(relative, "120000")
    return [(mode, relative) for relative, mode in entries.items() if os.path.lexists(root / relative)]


def skill_md_of(directory: Path) -> Path | None:
    """directory/SKILL.md when an entry named exactly SKILL.md is a regular file (§7.1).

    A plain `(directory / "SKILL.md").is_file()` also matches skill.md on case-insensitive filesystems.
    """
    try:
        if "SKILL.md" in os.listdir(directory) and (directory / "SKILL.md").is_file():
            return directory / "SKILL.md"
    except OSError:
        pass
    return None


def adapter_skill_files(root: Path) -> list[Path]:
    """The SKILL.md of every immediate child directory of skills/ (§7.1), without recursion."""
    skills = root / "skills"
    if not skills.is_dir():
        return []
    return [path for child in sorted(skills.iterdir()) if child.is_dir() for path in [skill_md_of(child)] if path]


def skill_problems(skill_md: Path, directory_name: str) -> list[str]:
    """Agent Skills rules for one SKILL.md, read as skills-ref does, plus the repository's double-quote rule."""
    label = skill_md.parent.name + "/SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
        fields, styles = skill_frontmatter.parse(text)
    except (OSError, UnicodeDecodeError, skill_frontmatter.FrontmatterError) as error:
        return [f"{label}: {error}"]
    problems = [f"{label}: {problem}" for problem in [skill_frontmatter.cross_check(text, fields)] if problem]
    extra = sorted(set(fields) - ALLOWED_FIELDS)
    if extra:
        problems.append(f"{label}: fields {extra} are outside {sorted(ALLOWED_FIELDS)}")
    for key in ("name", "description", "license", "allowed-tools", "compatibility"):
        if key in fields and not isinstance(fields[key], str):
            problems.append(f"{label}: {key} must be a string")
    name, description = fields.get("name"), fields.get("description")
    if not isinstance(name, str) or not SKILL_NAME.fullmatch(name) or len(name) > 64:
        problems.append(f"{label}: name {name!r} must be 1-64 of a-z, 0-9 and single inner hyphens")
    elif unicodedata.normalize("NFKC", name) != unicodedata.normalize("NFKC", directory_name):
        problems.append(f"{label}: name {name!r} must equal its directory name {directory_name!r}")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        problems.append(f"{label}: description must be 1-1024 characters and not blank")
    if isinstance(fields.get("compatibility"), str) and not 1 <= len(fields["compatibility"]) <= 500:
        problems.append(f"{label}: compatibility must be 1-500 characters")
    metadata = fields.get("metadata", {})
    if not isinstance(metadata, dict):
        problems.append(f"{label}: metadata must be a map of strings")
    elif "hermes" in metadata:
        problems.append(f"{label}: metadata.hermes is not allowed (a nested map breaks Agent Skills; a string "
                        f"breaks Hermes skill_view)")
    quoted = [key for key in styles if (key in QUOTED_FIELDS or key.startswith("metadata.")) and styles[key] != "double"]
    if quoted:
        problems.append(f"{label}: {quoted} must be double-quoted (repository rule)")
    return problems


def check_manifest(root: Path) -> list[str]:
    path = root / "plugin.json"
    if not path.is_file() or path.is_symlink():
        return ["plugin.json must be a regular file at the plugin root (§4.1, §5.1)"]
    try:
        manifest = load_json(path)
    except (UnicodeDecodeError, ValueError) as error:
        return [f"plugin.json is not strict UTF-8 JSON: {error}"]
    return validate(manifest, PLUGIN_SCHEMA)


def check_version(root: Path) -> list[str]:
    try:
        manifest = load_json(root / "plugin.json")
        fields, _ = skill_frontmatter.parse((root / "SKILL.md").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"cannot read the versions: {error}"]
    if not isinstance(manifest, dict):
        return ["plugin.json is not a JSON object"]
    skill_version = fields.get("metadata", {}).get("version", "") if isinstance(fields.get("metadata"), dict) else ""
    expected = skill_version + ".0" if re.fullmatch(r"\d+\.\d+", skill_version) else skill_version
    problems = []
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        problems.append(f"plugin.json version {version!r} should be a SemVer string (§10.2)")
    if version != expected:
        problems.append(f"plugin.json version {version!r} != SKILL.md metadata.version {skill_version!r} "
                        f"(as {expected!r})")
    commands = (root / "references" / "commands.md").read_text(encoding="utf-8") \
        if (root / "references" / "commands.md").is_file() else ""
    if f"`{ROOT_SKILL_NAME}` v{skill_version}." not in commands:
        problems.append(f"references/commands.md does not state `{ROOT_SKILL_NAME}` v{skill_version}.")
    return problems


def discovered_skills(root: Path) -> tuple[list[Path], list[str]]:
    """§7.1: each immediate child of skills/ holding a regular SKILL.md inside the root is one skill; no recursion."""
    skills = root / "skills"
    if not skills.is_dir() or skills.is_symlink():
        return [], ["skills/ must be a real directory"]
    found, problems = [], []
    for skill_md in adapter_skill_files(root):
        if not skill_md.resolve().is_relative_to(root.resolve()):
            problems.append(f"skills/{skill_md.parent.name}/SKILL.md resolves outside the plugin root")
        else:
            found.append(skill_md)
    names = [path.parent.name for path in found]
    if names != EXPECTED_PLUGIN_SKILLS:
        problems.append(f"plugin clients would discover {names}; expected {EXPECTED_PLUGIN_SKILLS}")
    return found, problems


def check_containment(root: Path) -> list[str]:
    problems = []
    base = root.resolve()
    for skill_md in adapter_skill_files(root):
        for reference in ADAPTER_REFERENCE.findall(skill_md.read_text(encoding="utf-8")):
            target = (skill_md.parent / reference).resolve()
            if not target.is_relative_to(base):
                problems.append(f"{skill_md.parent.name}: {reference} resolves outside the plugin root")
            elif not target.is_file():
                problems.append(f"{skill_md.parent.name}: {reference} does not exist")
    # Every directory link is listed itself (walk_package reports links instead of entering them), so checking each
    # listed path is enough; files below a link need no per-parent check.
    problems += [f"{relative} is a symbolic link or junction" for mode, relative in tracked_files(root)
                 if mode == "120000" or is_link(root / relative)]
    return problems


def check_mcp(root: Path) -> list[str]:
    path = root / "mcp.json"
    if not path.exists():
        return []
    try:
        config = load_json(path)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        return [f"mcp.json is not strict UTF-8 JSON: {error}"]
    if not isinstance(config, dict) or set(config) != {"$schema", "mcpServers"} or \
            config["$schema"] != MCP_SCHEMA_URL or not isinstance(config["mcpServers"], dict):
        return ["mcp.json must hold exactly $schema (1.0.0) and an mcpServers object (§7.2)"]
    return []


def guarded(compute) -> list[str]:
    """Run one row's check; an exception (an unreadable file, a git failure) becomes that row's problem, not a crash."""
    try:
        return compute()
    except Exception as error:  # noqa: BLE001 - every failure must surface as a red row
        return [f"the check could not run: {type(error).__name__}: {error}"]


def check(root: Path) -> list[dict]:
    found: list[Path] = []

    def discovery() -> list[str]:
        paths, problems = discovered_skills(root)
        found.extend(paths)
        return problems

    rows = [
        ("plugin: plugin.json is a valid Agent Plugins 1.0.0 manifest", lambda: check_manifest(root)),
        ("plugin: manifest version matches SKILL.md metadata.version and references/commands.md",
         lambda: check_version(root)),
        ("plugin: skills/ discovery (§7.1) finds exactly the six command adapters", discovery),
        ("plugin: every discovered skill meets Agent Skills (strict YAML, allowed fields, name = directory, "
         "string-only metadata)", lambda: [problem for path in found for problem in skill_problems(path, path.parent.name)]),
        ("plugin: root SKILL.md (not a plugin skill) meets the same Agent Skills rules",
         lambda: skill_problems(root / "SKILL.md", ROOT_SKILL_NAME)),
        ("plugin: package paths stay inside the plugin root and include no links (§4.1)", lambda: check_containment(root)),
        ("plugin: mcp.json is absent or valid (§7.2)", lambda: check_mcp(root)),
    ]
    results = []
    for label, compute in rows:
        problems = guarded(compute)
        results.append({"file": label, "passed": not problems, "missing": problems})
    return results
