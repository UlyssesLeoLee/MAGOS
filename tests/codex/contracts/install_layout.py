"""Install the Codex and Hermes packages into a temporary home and verify the installed layout.

The discovery checks are replicas of the host rules, not the hosts themselves:
- Codex: codex-rs/ext/skills/src/loader (recursive scan, MAX_SCAN_DEPTH = 6, hidden directories skipped).
- Hermes: agent/skill_utils.py (rglob; a SKILL.md below a parent skill's support directory is not a skill).
The same replicas also run over the files a commit would ship (tracked, plus untracked files git does not ignore),
because users may git clone the repository straight into a Codex or Hermes skills directory (README.md), where
every committed SKILL.md is discovered.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import agent_plugin
import skill_frontmatter

EXPECTED_SKILLS = {"multi-agent-git-orchestrator", "git-recon", "git-analyze", "git-recommend",
                   "git-integrate", "git-cleanup", "git-converge"}
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

    Codex marks a directory as a plugin root, and renames its skills to <plugin>:<name>, only for the manifests in
    HOST_PLUGIN_MANIFEST_DIRS (codex-rs DISCOVERABLE_PLUGIN_MANIFEST_PATHS); a root plugin.json is not one of them.
    """
    tracked = [relative for _, relative in agent_plugin.tracked_files(repo)]
    skill_files = [repo / relative for relative in tracked if relative.split("/")[-1] == "SKILL.md"]
    problems = []
    for host, discover in (("codex", codex_discovery), ("hermes", hermes_discovery)):
        names = discover(repo.parent, skill_files)
        if sorted(names) != sorted(EXPECTED_SKILLS):
            problems.append(f"{host} replica discovers {sorted(names)}; expected {sorted(EXPECTED_SKILLS)}")
    manifests = sorted(relative for relative in tracked if HOST_PLUGIN_MANIFEST_DIRS & set(relative.split("/")))
    return [{"file": "install:git-clone checkout, the Codex and Hermes replicas find each skill once",
             "passed": not problems, "missing": problems},
            {"file": "install:git-clone checkout has no .codex-plugin/.claude-plugin/.cursor-plugin manifest",
             "passed": not manifests, "missing": manifests}]


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
        return results
