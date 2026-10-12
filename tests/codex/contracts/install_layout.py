"""Install the Codex and Hermes packages into a temporary home and verify the installed layout.

The discovery checks are replicas of the host rules, not the hosts themselves:
- Codex: codex-rs/ext/skills/src/loader (recursive scan, MAX_SCAN_DEPTH = 6, hidden directories skipped).
- Hermes: agent/skill_utils.py (rglob; a SKILL.md below a parent skill's support directory is not a skill).
The same replicas also run over the files a commit would ship (tracked, plus untracked files git does not ignore),
because users may git clone the repository straight into a Codex or Hermes skills directory (README.md), where
every committed SKILL.md is discovered.
"""

import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import agent_plugin
import skill_frontmatter

EXPECTED_SKILLS = {"multi-agent-git-orchestrator", "git-recon", "git-analyze", "git-recommend",
                   "git-integrate", "git-cleanup", "git-converge", "git-sweep"}
# A git clone also carries skills/git-orchestrator, the entry skill plugin hosts need because they never load the
# root SKILL.md; scripts/sync_hosts.py leaves it out of the Codex and Hermes packages (PLUGIN_ONLY_SKILLS).
CHECKOUT_SKILLS = EXPECTED_SKILLS | {"git-orchestrator"}
CODEX_MAX_SCAN_DEPTH = 6
HERMES_SUPPORT_DIRS = {"references", "templates", "assets", "scripts"}
# Hermes agent/skill_utils.py EXCLUDED_SKILL_DIRS: a SKILL.md below any of these directories is not a skill.
HERMES_SKIP_PARTS = {".git", ".github", ".hub", ".archive", ".curator_backups", ".locks", ".venv", "venv",
                     "node_modules", "site-packages", "__pycache__", ".tox", ".nox", ".pytest_cache", ".mypy_cache",
                     ".ruff_cache"}
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
ROOT_REFERENCE = re.compile(r"`(references/[A-Za-z0-9_.-]+\.md)`")
HOST_PLUGIN_MANIFEST_DIRS = {".codex-plugin", ".claude-plugin", ".cursor-plugin"}
CLAUDE_PLUGIN_MANIFEST = ".claude-plugin/plugin.json"
MARKETPLACE_MANIFEST = ".claude-plugin/marketplace.json"
MARKETPLACE_ENTRY_KEYS = {"name", "source", "description", "version", "author", "homepage", "repository", "license",
                          "keywords", "category", "tags"}
# Metadata only: any other key (commands, skills, hooks, monitors, themes, ...) declares a component or setting.
CLAUDE_METADATA_KEYS = {"name", "version", "description", "author", "homepage", "repository", "license", "keywords"}


def frontmatter(path: Path) -> dict:
    """Strictly parsed frontmatter, or {} when it is outside the YAML subset (see skill_frontmatter)."""
    try:
        return skill_frontmatter.parse(path.read_text(encoding="utf-8"))[0]
    except (OSError, UnicodeDecodeError, skill_frontmatter.FrontmatterError):
        return {}


def skill_name(path: Path) -> str:
    """The name a host would register; an unreadable frontmatter is reported, never replaced by the directory name."""
    name = frontmatter(path).get("name")
    return name if isinstance(name, str) and name else f"<frontmatter outside the strict subset: {path.parent.name}>"


def codex_discovery(skills_root: Path, paths=None) -> list[str]:
    names = []
    for path in skills_root.rglob("SKILL.md") if paths is None else paths:
        parts = path.relative_to(skills_root).parts
        if any(part.startswith(".") for part in parts[:-1]) or len(parts) - 1 > CODEX_MAX_SCAN_DEPTH:
            continue
        names.append(skill_name(path))
    return names


def hermes_discovery(skills_root: Path, paths=None) -> list[str]:
    names = []
    for path in skills_root.rglob("SKILL.md") if paths is None else paths:
        parts = path.relative_to(skills_root).parts
        if any(part in HERMES_SKIP_PARTS for part in parts):
            continue
        if any(part in HERMES_SUPPORT_DIRS and (skills_root.joinpath(*parts[:index]) / "SKILL.md").exists()
               for index, part in enumerate(parts[:-1])):
            continue
        names.append(skill_name(path))
    return names


def strict_yaml_problems(package_root: Path, skill_files) -> list[str]:
    """Every SKILL.md must be inside the strict YAML subset and read the same under PyYAML when it is installed."""
    problems = []
    for skill_file in skill_files:
        label = skill_file.relative_to(package_root).as_posix()
        try:
            text = skill_file.read_text(encoding="utf-8")
            fields, _ = skill_frontmatter.parse(text)
        except (OSError, UnicodeDecodeError, skill_frontmatter.FrontmatterError) as error:
            problems.append(f"{label}: {error}")
            continue
        problem = skill_frontmatter.cross_check(text, fields)
        if problem:
            problems.append(f"{label}: {problem}")
    return problems


def check_package(host: str, package_root: Path, skills_root: Path, discover) -> list[dict]:
    results = []
    missing = []
    commands_links = []
    for adapter in sorted(package_root.glob("skills/*/SKILL.md")):
        text = adapter.read_text(encoding="utf-8")
        label = adapter.relative_to(package_root).as_posix()
        for reference in agent_plugin.ADAPTER_REFERENCE.findall(text):
            if reference.startswith("../../commands/"):
                commands_links.append(f"{label} -> {reference}")
            elif not (adapter.parent / reference).resolve().is_file():
                missing.append(f"{label} -> {reference}")
    root_skill = package_root / "SKILL.md"
    if not root_skill.is_file():
        missing.append("SKILL.md")
    else:
        for reference in ROOT_REFERENCE.findall(root_skill.read_text(encoding="utf-8")):
            if not (package_root / reference).is_file():
                missing.append(f"SKILL.md -> {reference}")
    results.append({"file": f"install:{host} relative references resolve", "passed": not missing,
                    "missing": missing})
    results.append({"file": f"install:{host} adapters do not route through commands/",
                    "passed": not commands_links, "missing": commands_links})

    policy_missing = [path.relative_to(package_root).as_posix()
                      for path in sorted(package_root.glob("skills/*/agents/openai.yaml"))
                      if not re.search(r"^policy:\n  allow_implicit_invocation: false$",
                                       path.read_text(encoding="utf-8"), re.M)]
    if len(list(package_root.glob("skills/*/agents/openai.yaml"))) != len(EXPECTED_SKILLS) - 1:
        policy_missing.append(f"expected {len(EXPECTED_SKILLS) - 1} agents/openai.yaml files")
    results.append({"file": f"install:{host} adapters disable implicit invocation",
                    "passed": not policy_missing, "missing": policy_missing})

    names = discover(skills_root)
    problems = []
    if sorted(names) != sorted(EXPECTED_SKILLS):
        problems.append(f"discovered {sorted(names)}; expected {sorted(EXPECTED_SKILLS)}")
    for skill_file in [root_skill, *package_root.glob("skills/*/SKILL.md")]:
        fields = frontmatter(skill_file) if skill_file.is_file() else {}
        name, description = fields.get("name"), fields.get("description")
        if not isinstance(name, str) or not 0 < len(name) <= MAX_NAME_LENGTH:
            problems.append(f"{skill_file.relative_to(package_root).as_posix()}: invalid name")
        if not isinstance(description, str) or not description.strip() or len(description) > MAX_DESCRIPTION_LENGTH:
            problems.append(f"{skill_file.relative_to(package_root).as_posix()}: invalid description length")
    results.append({"file": f"install:{host} discovery replica finds each skill once",
                    "passed": not problems, "missing": problems})
    skill_files = ([root_skill] if root_skill.is_file() else []) + sorted(package_root.glob("skills/*/SKILL.md"))
    yaml_problems = strict_yaml_problems(package_root, skill_files)
    results.append({"file": f"install:{host} every installed SKILL.md is strict YAML with string-only metadata",
                    "passed": not yaml_problems, "missing": yaml_problems})
    return results


def check_checkout(repo: Path) -> list[dict]:
    """A git clone into a host skills directory: every committed SKILL.md is discovered, whatever package_files() lists.

    The listing is what a commit would ship (agent_plugin.tracked_files), so a new file is caught before `git add`.

    Codex marks a directory as a plugin root, and renames its skills to <plugin>:<name>, for any directory in
    HOST_PLUGIN_MANIFEST_DIRS (codex-rs DISCOVERABLE_PLUGIN_MANIFEST_PATHS); a root plugin.json is not one of them.
    The checkout carries .claude-plugin/plugin.json on purpose, so that a clone into ~/.claude/skills/ loads as a
    Claude Code plugin; a clone into a Codex skills directory therefore shows $magos:<name>, and Codex installs use
    scripts/sync_hosts.py, whose package never contains a host manifest (check_installed). The replicas here do not
    model that namespace. Every other host manifest stays forbidden, and the Claude one must match plugin.json.
    """
    tracked = [relative for _, relative in agent_plugin.tracked_files(repo)]
    skill_files = [repo / relative for relative in tracked if relative.split("/")[-1] == "SKILL.md"]
    problems = []
    for host, discover in (("codex", codex_discovery), ("hermes", hermes_discovery)):
        names = discover(repo.parent, skill_files)
        if sorted(names) != sorted(CHECKOUT_SKILLS):
            problems.append(f"{host} replica discovers {sorted(names)}; expected {sorted(CHECKOUT_SKILLS)}")
    manifests = sorted(relative for relative in tracked if HOST_PLUGIN_MANIFEST_DIRS & set(relative.split("/")))
    stray = [relative for relative in manifests if relative not in (CLAUDE_PLUGIN_MANIFEST, MARKETPLACE_MANIFEST)]
    return [{"file": "install:git-clone checkout, the Codex and Hermes replicas find each skill once",
             "passed": not problems, "missing": problems},
            {"file": "install:git-clone checkout has no host plugin manifest other than .claude-plugin/plugin.json "
                     "and .claude-plugin/marketplace.json",
             "passed": not stray, "missing": stray},
            {"file": "install:git-clone checkout's .claude-plugin/plugin.json is the Claude Code manifest of plugin.json",
             "passed": not (claude := claude_manifest_problems(repo, manifests)), "missing": claude},
            {"file": "install:.claude-plugin/marketplace.json lists this repository root as the one plugin magos",
             "passed": not (market := marketplace_problems(repo, manifests)), "missing": market},
            {"file": "install:plugin.yaml is the Hermes native manifest of plugin.json, and __init__.py registers skills/",
             "passed": not (hermes := hermes_manifest_problems(repo)), "missing": hermes}]


def hermes_manifest_problems(repo: Path) -> list[str]:
    """`hermes plugins install` prefers a native plugin.yaml over the portable plugin.json; with it the skills are
    /magos:<name> instead of /agent-plugin-magos-<digest>:<name>. Its name and version must match plugin.json, and
    __init__.py must register the skills/ directory (and nothing else: catalog rule 6 compares declared capabilities)."""
    try:
        text = (repo / "plugin.yaml").read_text(encoding="utf-8")
        package = agent_plugin.load_json(repo / "plugin.json")
        entry = (repo / "__init__.py").read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        return [f"cannot read the Hermes plugin files: {error}"]
    fields = dict(re.findall(r'^(name|version): *"?([^"\n]+?)"? *$', text, re.M))
    problems = [f"plugin.yaml {key} {fields.get(key)!r} != plugin.json {key} {package.get(key)!r}"
                for key in ("name", "version") if fields.get(key) != package.get(key)]
    if re.search(r"^(provides_|requires_|capabilities|python_dependencies)", text, re.M):
        problems.append("plugin.yaml declares hooks, tools, capabilities or dependencies; MAGOS ships skills only")
    if "ctx.register_skill(" not in entry or re.search(r"ctx\.register_(?!skill\()", entry):
        problems.append("__init__.py must call ctx.register_skill() and no other ctx.register_*")
    problems += hermes_index_problems(repo, entry)
    return problems


def hermes_index_problems(repo: Path, entry: str) -> list[str]:
    """Hermes lists every registered plugin skill in <available_skills> with the description passed to
    ctx.register_skill (without one the model sees the bare name and never loads the skill on its own), so each skill
    needs an INDEX_DESCRIPTIONS line: the orchestrator a trigger-rich one, a command that writes to a repository (an
    adapter with an "Explicit invocation only" section) one that tells the model to leave it to the user."""
    try:
        tree = ast.parse(entry)
        table = ast.literal_eval(next(
            node.value for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
            and any(getattr(target, "id", "") == "INDEX_DESCRIPTIONS"
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target]))))
    except StopIteration:
        return ["__init__.py has no top-level INDEX_DESCRIPTIONS assignment"]
    except (SyntaxError, ValueError, TypeError) as error:
        return [f"__init__.py has no literal INDEX_DESCRIPTIONS table: {error}"]
    if not isinstance(table, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                              for key, value in table.items()):
        return ["__init__.py INDEX_DESCRIPTIONS must be a literal dict from skill name to description string"]
    names = sorted(path.parent.name for path in (repo / "skills").glob("*/SKILL.md"))
    problems = [f"INDEX_DESCRIPTIONS has no line for skills/{name}" for name in names if not table.get(name)]
    problems += [f"INDEX_DESCRIPTIONS names {name!r}, which is not a skill" for name in sorted(set(table) - set(names))]
    if not passes_index_description(tree):
        problems.append("__init__.py does not pass the INDEX_DESCRIPTIONS line to ctx.register_skill()")
    orchestrator = table.get("git-orchestrator", "")
    if not 100 <= len(orchestrator) <= 400:
        problems.append(f"the git-orchestrator index line has {len(orchestrator)} characters; keep it 100-400, "
                        "since it sits in every Hermes system prompt")
    for name in names:
        if "\n## Explicit invocation only" in read_text_or_empty(repo / "skills" / name / "SKILL.md") \
                and "Never load it yourself" not in table.get(name, ""):
            problems.append(f"the {name} index line must tell the model never to load it itself")
    for name, line in sorted(table.items()):
        others = sorted({command for command in re.findall(r"/[\w-]+:([\w-]+)", line) if command != name})
        if others:
            problems.append(f"the {name} index line names another command: {', '.join(others)}")
    return problems


def passes_index_description(tree: ast.AST) -> bool:
    """Every ctx.register_skill() call passes description=<an expression that reads INDEX_DESCRIPTIONS>."""
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "register_skill"]
    return bool(calls) and all(
        any(keyword.arg == "description" and any(isinstance(name, ast.Name) and name.id == "INDEX_DESCRIPTIONS"
                                                 for name in ast.walk(keyword.value))
            for keyword in call.keywords)
        for call in calls)


def read_text_or_empty(path: Path) -> str:
    """The file's text, or "" when it cannot be read; the frontmatter rows already report an unreadable SKILL.md."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def marketplace_problems(repo: Path, manifests: list[str]) -> list[str]:
    """The Claude Code and Codex marketplace must list exactly one plugin, the repository root itself.

    Claude Code (`/plugin marketplace add`) and Codex (`codex plugin marketplace add`, codex-rs
    MARKETPLACE_MANIFEST_RELATIVE_PATHS) both read this file; "./" is the source form both accept for the
    marketplace root. Codex installs it through the root plugin.json, Claude Code through .claude-plugin/plugin.json.
    """
    if MARKETPLACE_MANIFEST not in manifests:
        return [f"{MARKETPLACE_MANIFEST} is missing, so no marketplace can list the plugin"]
    try:
        market = agent_plugin.load_json(repo / MARKETPLACE_MANIFEST)
        package = agent_plugin.load_json(repo / "plugin.json")
    except (OSError, ValueError) as error:
        return [f"cannot read the manifests: {error}"]
    if not isinstance(market, dict) or not isinstance(package, dict):
        return ["a manifest is not a JSON object"]
    problems = []
    if not isinstance(market.get("name"), str) or not market["name"]:
        problems.append(f"{MARKETPLACE_MANIFEST} has no marketplace name")
    owner = market.get("owner")
    if not isinstance(owner, dict) or not isinstance(owner.get("name"), str) or not owner["name"]:
        problems.append(f"{MARKETPLACE_MANIFEST} has no owner.name (Claude Code requires it)")
    plugins = market.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
        return problems + [f"{MARKETPLACE_MANIFEST} must list exactly one plugin"]
    entry = plugins[0]
    if entry.get("name") != package.get("name"):
        problems.append(f"marketplace plugin name {entry.get('name')!r} != plugin.json name {package.get('name')!r}")
    if entry.get("source") != "./":
        problems.append(f"marketplace plugin source {entry.get('source')!r} is not the repository root './'")
    problems += [f"marketplace plugin entry declares {key!r}, which is not a metadata key"
                 for key in sorted(set(entry) - MARKETPLACE_ENTRY_KEYS)]
    return problems


def claude_manifest_problems(repo: Path, manifests: list[str]) -> list[str]:
    """The Claude Code manifest must exist, use the Agent Plugins name and version, and hold only metadata keys.

    Without component keys Claude Code scans its default commands/ and skills/ directories, the files every other
    host uses too; a component key would make the Claude plugin diverge from them. The check allows the known
    metadata keys instead of denying known component keys, so a component key Claude Code adds later is still caught.
    """
    if CLAUDE_PLUGIN_MANIFEST not in manifests:
        return [f"{CLAUDE_PLUGIN_MANIFEST} is missing, so a clone into ~/.claude/skills/ loads no commands"]
    try:
        claude = agent_plugin.load_json(repo / CLAUDE_PLUGIN_MANIFEST)
        package = agent_plugin.load_json(repo / "plugin.json")
    except (OSError, ValueError) as error:
        return [f"cannot read the manifests: {error}"]
    if not isinstance(claude, dict) or not isinstance(package, dict):
        return ["a manifest is not a JSON object"]
    problems = [f"{CLAUDE_PLUGIN_MANIFEST} {key} {claude.get(key)!r} != plugin.json {key} {package.get(key)!r}"
                for key in ("name", "version") if claude.get(key) != package.get(key)]
    problems += [f"{CLAUDE_PLUGIN_MANIFEST} declares {key!r}, which is not a metadata key"
                 for key in sorted(set(claude) - CLAUDE_METADATA_KEYS)]
    return problems


def check(repo: Path) -> list[dict]:
    return check_installed(repo) + check_checkout(repo)


def check_installed(repo: Path) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="magos-layout-") as temporary:
        home = Path(temporary)
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(repo / "scripts" / "sync_hosts.py"), "--home", str(home),
             "--host", "codex", "--host", "hermes", "--apply", "--create-roots", "--json"],
            text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120, check=False)
        results = [{"file": "install:sync_hosts.py --apply --create-roots", "passed": completed.returncode == 0,
                    "missing": [] if completed.returncode == 0 else [completed.stdout[-400:] + completed.stderr[-400:]]}]
        if completed.returncode:
            return results
        report = json.loads(completed.stdout)
        roots = {host["host"]: Path(host["required_directory"]) for host in report["hosts"]}
        outside = [f"{host}: install root is outside the temporary home" for host, root in roots.items()
                   if not root.resolve().is_relative_to(home.resolve())]
        results.append({"file": "install:roots stay inside the temporary home", "passed": not outside,
                        "missing": outside})
        if outside:
            return results
        results += check_package("codex", roots["codex"], roots["codex"].parent, codex_discovery)
        results += check_package("hermes", roots["hermes"], roots["hermes"].parent, hermes_discovery)
        shipped = sorted(f"{host}: {path.relative_to(root).as_posix()}" for host, root in roots.items()
                         for path in root.rglob("*") if HOST_PLUGIN_MANIFEST_DIRS & set(path.relative_to(root).parts))
        results.append({"file": "install:synced Codex and Hermes packages carry no host plugin manifest",
                        "passed": not shipped, "missing": shipped})
        return results
