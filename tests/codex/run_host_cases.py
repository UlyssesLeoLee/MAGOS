"""cypher
CREATE
  (f:File {name:'run_host_cases.py', type:'file', language:'python'}),
  (g:Function {name:'git', type:'function'}),
  (w:Function {name:'write_json', type:'function'}),
  (s:Function {name:'snapshot', type:'function'}),
  (p:Function {name:'prepare_fixture', type:'function'}),
  (project_skill:Function {name:'provision_codex_skill', type:'function'}),
  (root:Variable {name:'ROOT', type:'variable'}),
  (tool_types:Variable {name:'tool_item_types', type:'variable'}),
  (v:Function {name:'verify_fixture', type:'function'}),
  (c:Function {name:'host_command', type:'function'}),
  (x:Function {name:'extract_response', type:'function'}),
  (i:Function {name:'invoke_host', type:'function'}),
  (e:Function {name:'evaluate', type:'function'}),
  (hg:Function {name:'has_git_command', type:'function'}),
  (r:Function {name:'run_case', type:'function'}),
  (m:Function {name:'main', type:'function'}),
  (run:Function {name:'subprocess.run', type:'function'}),
  (dump:Function {name:'json.dumps', type:'function'}),
  (json_loads:Function {name:'json.loads', type:'function'}),
  (regex_search:Function {name:'re.search', type:'function'}),
  (write:Function {name:'Path.write_text', type:'function'}),
  (read:Function {name:'Path.read_text', type:'function'}),
  (mkdir:Function {name:'Path.mkdir', type:'function'}),
  (copytree:Function {name:'shutil.copytree', type:'function'}),
  (rglob:Function {name:'Path.rglob', type:'function'}),
  (read_bytes:Function {name:'Path.read_bytes', type:'function'}),
  (as_posix:Function {name:'Path.as_posix', type:'function'}),
  (sha256:Function {name:'hashlib.sha256', type:'function'}),
  (which:Function {name:'shutil.which', type:'function'}),
  (temp:Function {name:'tempfile.TemporaryDirectory', type:'function'}),
  (f)-[:CONTAINS]->(g), (f)-[:CONTAINS]->(w), (f)-[:CONTAINS]->(s),
  (f)-[:CONTAINS]->(p), (f)-[:CONTAINS]->(project_skill), (f)-[:CONTAINS]->(v), (f)-[:CONTAINS]->(c),
  (f)-[:CONTAINS]->(x), (f)-[:CONTAINS]->(i), (f)-[:CONTAINS]->(e),
  (f)-[:CONTAINS]->(hg), (f)-[:CONTAINS]->(json_loads), (f)-[:CONTAINS]->(regex_search),
  (f)-[:CONTAINS]->(r), (f)-[:CONTAINS]->(m),
  (g)-[:CALLS]->(run), (w)-[:CALLS]->(dump), (w)-[:CALLS]->(write),
  (s)-[:CALLS]->(g), (s)-[:CALLS]->(as_posix), (p)-[:CALLS]->(g), (p)-[:CALLS]->(mkdir),
  (v)-[:CALLS]->(s), (v)-[:CALLS]->(g), (c)-[:CALLS]->(which),
  (x)-[:CALLS]->(read), (x)-[:CALLS]->(json_loads), (i)-[:CALLS]->(run), (e)-[:CALLS]->(g),
  (e)-[:CALLS]->(hg), (hg)-[:CALLS]->(json_loads), (hg)-[:CALLS]->(regex_search),
  (x)-[:USES]->(tool_types),
  (r)-[:CALLS]->(p), (r)-[:CALLS]->(project_skill), (r)-[:CALLS]->(v), (r)-[:CALLS]->(s),
  (r)-[:CALLS]->(c), (r)-[:CALLS]->(i), (r)-[:CALLS]->(x),
  (r)-[:CALLS]->(e), (r)-[:CALLS]->(w), (r)-[:CALLS]->(temp),
  (m)-[:CALLS]->(read), (m)-[:CALLS]->(r),
  (project_skill)-[:CALLS]->(copytree),
  (project_skill)-[:CALLS]->(rglob), (project_skill)-[:CALLS]->(read_bytes),
  (project_skill)-[:CALLS]->(sha256), (project_skill)-[:CALLS]->(read),
  (project_skill)-[:CALLS]->(write),
  (project_skill)-[:CALLS]->(mkdir),
  (project_skill)-[:USES]->(root), (f)-[:CONTAINS]->(root);
"""

"""Run real Git-skill invocations in disposable fixtures and retain evidence."""

import argparse
import contextlib
import copy
import fnmatch
import functools
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path


TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
CASES = TESTS / "host_cases"
MANIFEST = TESTS / "host_cases.json"
PACKAGE_DIR = "MAGOS"
HOST_NAME = {
    "git-recon": "$git-recon",
    "git-analyze": "$git-analyze",
    "git-recommend": "$git-recommend",
    "git-integrate": "$git-integrate",
    "git-cleanup": "$git-cleanup",
    "git-converge": "$git-converge",
}
RUNTIME_ERROR = re.compile(
    r"(?i)(insufficient.?(?:credit|balance)|usage limit|rate limit|quota|"
    r"authentication|not logged in|login required|api.?key|billing|"
    r"CreateProcessAsUserW|sandbox.*(?:denied|failed)|permission denied|"
    r"helper_unknown_error|setup refresh had errors|"
    r"orchestrator_helper_exit_nonzero|setup helper exited with status|"
    r"access is denied|interrupted.update|auto.recover.*install|"
    r"could not.*(?:connect|resolve)|model.*unavailable|provider.*error|"
    r"API call failed|request timed out)"
)


def git(directory: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(directory), *args],
        text=True, encoding="utf-8", errors="replace", capture_output=True,
        timeout=120, check=False,
    )
    if check and completed.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {completed.stderr.strip()}")
    return completed.stdout.strip()


def is_ancestor(directory: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(directory), "merge-base", "--is-ancestor", ancestor, descendant],
        text=True, encoding="utf-8", errors="replace", capture_output=True,
        timeout=120, check=False,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"git merge-base failed: {completed.stderr.strip()}")
    return completed.returncode == 0


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot(fixture: dict) -> dict:
    root = fixture["cwd"]
    if fixture["kind"] == "empty":
        files = {}
        for path in root.rglob("*"):
            relative_parts = path.relative_to(root).parts
            if path.is_file() and ".git" not in relative_parts and ".serena" not in relative_parts:
                files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"files": files, "git_repository": (root / ".git").exists()}
    refs = {}
    for line in git(root, "for-each-ref", "--format=%(refname) %(objectname)").splitlines():
        ref, sha = line.split(" ", 1)
        refs[ref] = sha
    worktree_text = git(root, "worktree", "list", "--porcelain")
    worktrees = {}
    for line in worktree_text.splitlines():
        if line.startswith("worktree "):
            worktree_path = Path(line[9:])
            worktrees[str(worktree_path)] = {
                "head": git(worktree_path, "rev-parse", "HEAD"),
                "branch": git(worktree_path, "branch", "--show-current"),
                "status": git(worktree_path, "status", "--porcelain=v1", "--untracked-files=all"),
            }
    files = {}
    for worktree_path in worktrees:
        base = Path(worktree_path)
        for path in base.rglob("*"):
            relative_parts = path.relative_to(base).parts
            if path.is_file() and ".git" not in relative_parts and ".serena" not in relative_parts:
                files[f"{base.name}/{path.relative_to(base).as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    bare_refs = {}
    if fixture.get("remote"):
        for line in git(fixture["remote"], "for-each-ref", "--format=%(refname) %(objectname)").splitlines():
            ref, sha = line.split(" ", 1)
            bare_refs[ref] = sha
    return {"git_repository": True, "refs": refs, "worktrees": worktrees,
            "files": files, "bare_refs": bare_refs}


def prepare_fixture(base: Path, kind: str) -> dict:
    if kind == "empty":
        cwd = base / "empty"
        cwd.mkdir()
        git(cwd, "init", "-b", "main")
        return {"kind": kind, "cwd": cwd, "base": base}
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    remote = repo / ".git" / "acceptance-origin.git"
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    git(repo, "config", "user.name", "MAGOS Acceptance")
    git(repo, "config", "user.email", "acceptance@example.invalid")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    fixture = {"kind": kind, "cwd": repo, "base": base, "remote": remote}
    if kind in {"branch", "remote", "integrate"}:
        git(repo, "switch", "-c", "agent/auth")
        (repo / "feature.txt").write_text("accepted feature\n", encoding="utf-8")
        git(repo, "add", "feature.txt")
        git(repo, "commit", "-m", "agent auth feature")
        fixture["lane_head"] = git(repo, "rev-parse", "HEAD")
        git(repo, "switch", "main")
        if kind in {"branch", "remote"}:
            worktree = base / "auth-worktree"
            git(repo, "worktree", "add", str(worktree), "agent/auth")
            (worktree / "feature.txt").write_text("accepted feature\ndirty edit\n", encoding="utf-8")
            fixture["worktree"] = worktree
        if kind == "remote":
            publisher = base / "publisher"
            git(base, "clone", str(remote), str(publisher))
            git(publisher, "config", "user.name", "MAGOS Publisher")
            git(publisher, "config", "user.email", "publisher@example.invalid")
            (publisher / "remote.txt").write_text("remote advance\n", encoding="utf-8")
            git(publisher, "add", "remote.txt")
            git(publisher, "commit", "-m", "advance origin main")
            git(publisher, "push", "origin", "main")
            fixture["remote_head"] = git(publisher, "rev-parse", "HEAD")
    elif kind == "cleanup":
        git(repo, "switch", "-c", "agent/done")
        (repo / "done.txt").write_text("merged work\n", encoding="utf-8")
        git(repo, "add", "done.txt")
        git(repo, "commit", "-m", "completed work")
        git(repo, "switch", "main")
        git(repo, "merge", "--no-ff", "--no-edit", "agent/done")
        git(repo, "switch", "-c", "agent/unique")
        (repo / "unique.txt").write_text("unmerged work\n", encoding="utf-8")
        git(repo, "add", "unique.txt")
        git(repo, "commit", "-m", "unique work")
        git(repo, "switch", "-c", "agent/dependent")
        (repo / "dependent.txt").write_text("depends on unique\n", encoding="utf-8")
        git(repo, "add", "dependent.txt")
        git(repo, "commit", "-m", "dependent work")
        git(repo, "switch", "main")
        git(repo, "branch", "agent/dirty")
        worktree = base / "dirty-worktree"
        git(repo, "worktree", "add", str(worktree), "agent/dirty")
        (worktree / "README.md").write_text("fixture\ndirty edit\n", encoding="utf-8")
        fixture["worktree"] = worktree
    return fixture


def verify_fixture(fixture: dict, state: dict) -> list[dict]:
    kind = fixture["kind"]
    checks = []
    if kind == "empty":
        checks.append({"name": "empty Git repository", "passed": state["git_repository"]})
        if fixture.get("skill"):
            skill_file = f".agents/skills/{PACKAGE_DIR}/skills/{fixture['skill']}/SKILL.md"
            checks.append({"name": "project-local Codex skill is present",
                           "passed": skill_file in state["files"]})
            checks.append({"name": "workspace contains only the skill scaffold",
                           "passed": all(path.startswith(".agents/") for path in state["files"])})
        else:
            checks.append({"name": "workspace is empty", "passed": not state["files"]})
    else:
        refs = state["refs"]
        checks.append({"name": "main and local origin exist",
                       "passed": "refs/heads/main" in refs and "refs/remotes/origin/main" in refs})
        checks.append({"name": "bare origin exists", "passed": bool(state["bare_refs"])})
        if kind in {"branch", "remote", "integrate"}:
            checks.append({"name": "unmerged lane exists", "passed":
            "refs/heads/agent/auth" in refs and not is_ancestor(fixture["cwd"], "agent/auth", "main")})
        if kind in {"branch", "remote"}:
            checks.append({"name": "dirty lane worktree exists", "passed":
                           str(fixture["worktree"]) in state["worktrees"] and
                           bool(state["worktrees"][str(fixture["worktree"])]["status"])})
        if kind == "remote":
            checks.append({"name": "remote tracking ref is stale", "passed":
                           refs["refs/remotes/origin/main"] != fixture["remote_head"] and
                           state["bare_refs"]["refs/heads/main"] == fixture["remote_head"]})
        if kind == "cleanup":
            checks.append({"name": "safe, dirty, unique, dependent candidates exist",
                           "passed": all(f"refs/heads/agent/{name}" in refs for name in
                                         ("done", "dirty", "unique", "dependent"))})
            checks.append({"name": "done is merged and unique is not", "passed":
                           is_ancestor(fixture["cwd"], "agent/done", "main") and
                           not is_ancestor(fixture["cwd"], "agent/unique", "main") and
                           bool(state["worktrees"][str(fixture["worktree"])]["status"])})
    if fixture.get("skill_path"):
        adapter = Path(fixture["skill_path"]).parent
        checks.append({"name": "adapter shared files resolve", "passed": all(
            (adapter / relative).resolve().is_file()
            for relative in ("../../SKILL.md", "../../references/commands.md", "../../references/reconnaissance.md"))})
    return checks


@functools.lru_cache(maxsize=None)
def load_sync_hosts():
    spec = importlib.util.spec_from_file_location("sync_hosts", ROOT / "scripts" / "sync_hosts.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # keep scripts/ free of __pycache__
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def load_package_files() -> tuple[str, ...]:
    """Use the installer's package list so tests and real installs share one layout."""
    return load_sync_hosts().package_files(ROOT)


def provision_codex_skill(fixture: dict, skill: str) -> None:
    """Install the checkout package through Codex's project-local discovery path, as sync_hosts.py does."""
    if skill not in HOST_NAME:
        raise ValueError(f"Unknown Codex skill fixture: {skill}")
    workspace = fixture["cwd"]
    agents = workspace / ".agents"
    package = agents / "skills" / PACKAGE_DIR
    for relative in load_package_files():
        destination = package / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    skill_target = package / "skills" / skill
    fixture["skill"] = skill
    fixture["skill_path"] = str(skill_target / "SKILL.md")
    copied_files = sorted(path for path in agents.rglob("*") if path.is_file())
    fixture["skill_source_sha256"] = hashlib.sha256("\n".join(
        f"{path.relative_to(agents).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in copied_files
    ).encode("utf-8")).hexdigest()
    git_directory = workspace / ".git"
    if git_directory.is_dir():
        exclude = git_directory / "info" / "exclude"
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if "/.agents/" not in existing.splitlines():
            exclude.write_text(existing.rstrip() + "\n/.agents/\n", encoding="utf-8")


def user_level_installs() -> list[str]:
    """Codex dedups skills by path, not name, so a user-level MAGOS install stays in the catalog."""
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    candidates = (Path.home() / ".agents" / "skills" / PACKAGE_DIR, codex_home / "skills" / PACKAGE_DIR)
    return [str(path) for path in candidates if path.exists()]


# Hermes's own resolver for its committed dependency environment: it reads the install's
# selection record (or falls back to the in-tree venv) and never creates state.
PROJECT_PYTHON = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pm.environments import project_python
print(project_python(Path(sys.argv[1])))
"""


def hermes_runtime_python(executable: str, agent_dir: Path) -> Path | None:
    """Ask Hermes which Python runs its dependency environment, or None if it cannot say.

    `hermes --print-runtime-command` names the launcher's interpreter without running the
    bootstrap (which may sync or relaunch). That interpreter then evaluates
    pm.environments.project_python with -I -B, so nothing is written to the Hermes install.
    """
    try:
        completed = subprocess.run([executable, "--print-runtime-command"], text=True, encoding="utf-8",
                                   errors="replace", capture_output=True, stdin=subprocess.DEVNULL,
                                   timeout=120, check=False)
        launcher = Path(json.loads(completed.stdout.strip().splitlines()[-1])[0])
        if completed.returncode or not launcher.is_file():
            return None
        resolved = subprocess.run([str(launcher), "-I", "-B", "-c", PROJECT_PYTHON, str(agent_dir)], text=True,
                                  encoding="utf-8", errors="replace", capture_output=True,
                                  stdin=subprocess.DEVNULL, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError, KeyError, TypeError):
        return None  # e.g. a Hermes release without the launcher contract
    python = Path(resolved.stdout.strip()) if resolved.returncode == 0 and resolved.stdout.strip() else None
    return python if python and python.is_file() else None


@functools.lru_cache(maxsize=None)
def hermes_install() -> dict | None:
    """Locate the Hermes CLI, its source checkout, and its dependency-environment Python (once per run)."""
    executable = shutil.which("hermes")
    if not executable:
        return None
    completed = subprocess.run([executable, "--version"], text=True, encoding="utf-8", errors="replace",
                               capture_output=True, timeout=120, check=False)
    match = re.search(r"^Install directory:\s*(.+?)\s*$", completed.stdout, re.M)
    if not match:
        return None
    agent_dir = Path(match.group(1))
    python = hermes_runtime_python(executable, agent_dir) or next(
        (path for path in (agent_dir / "venv" / "Scripts" / "python.exe", agent_dir / "venv" / "bin" / "python")
         if path.is_file()), None)
    version = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
    return {"executable": executable, "agent_dir": agent_dir, "python": python, "version": version}


HERMES_CONFIG_BACKUP = TESTS / ".hermes-config-backup.yaml"
# Equal when two Hermes configs differ only in fixture (.magos-accept-*) trust entries.
CONFIG_EQUIVALENCE = """
import sys
try:
    from yaml import safe_load
except ImportError:  # newer Hermes environments ship ruamel.yaml only
    from ruamel.yaml import YAML
    safe_load = YAML(typ="safe", pure=True).load
first, second = (safe_load(open(path, encoding="utf-8")) or {} for path in sys.argv[1:3])
for config in (first, second):
    skills = config.get("skills") or {}
    skills["trusted_project_dirs"] = [entry for entry in (skills.get("trusted_project_dirs") or [])
                                      if ".magos-accept-" not in str(entry)]
    config["skills"] = skills
print("equal" if first == second else "different")
"""


def recover_hermes_config(install: dict, config: Path) -> str | None:
    """Restore config.yaml from a backup left by an interrupted run (fixture trust entries only)."""
    if not HERMES_CONFIG_BACKUP.is_file():
        return None
    verdict = subprocess.run([str(install["python"]), "-c", CONFIG_EQUIVALENCE, str(HERMES_CONFIG_BACKUP),
                              str(config)], text=True, capture_output=True, timeout=120, check=False).stdout.strip()
    if verdict != "equal":
        raise RuntimeError(f"{HERMES_CONFIG_BACKUP} is left from an interrupted run, but {config} has other "
                           f"changes; compare them manually before running Hermes cases again")
    config.write_bytes(HERMES_CONFIG_BACKUP.read_bytes())
    HERMES_CONFIG_BACKUP.unlink()
    return "restored config.yaml left trusted by an interrupted run"


@contextlib.contextmanager
def hermes_trusted(install: dict, root: Path, evidence: Path):
    """Trust the fixture for project skills, then untrust it and restore the user's config bytes.

    `hermes skills trust/untrust` rewrites config.yaml through save_config. The original bytes are
    restored only when the parsed config is otherwise unchanged; any other difference is reported.
    The original is also kept in HERMES_CONFIG_BACKUP until then, so an interrupted run can be
    recovered by the next one.
    """
    config = load_sync_hosts().hermes_home(Path.home(), False) / "config.yaml"
    recovered = recover_hermes_config(install, config)
    original = config.read_bytes() if config.is_file() else None
    if original is not None:
        HERMES_CONFIG_BACKUP.write_bytes(original)
    record = {"config_sha256_before": hashlib.sha256(original).hexdigest() if original else None,
              "recovered_interrupted_run": recovered}
    run = lambda *args: subprocess.run([install["executable"], "skills", *args, str(root)], text=True,  # noqa: E731
                                       encoding="utf-8", errors="replace", capture_output=True,
                                       timeout=120, check=False)
    record["trust"] = run("trust").stdout.strip()[-300:]
    try:
        yield
    finally:
        record["untrust"] = run("untrust").stdout.strip()[-300:]
        current = config.read_bytes() if config.is_file() else None
        record["restored"] = False
        if original is not None and current != original:
            with tempfile.TemporaryDirectory(prefix="magos-config-") as temporary:
                saved = Path(temporary) / "original.yaml"
                saved.write_bytes(original)
                verdict = subprocess.run([str(install["python"]), "-c", CONFIG_EQUIVALENCE, str(saved), str(config)],
                                         text=True, capture_output=True, timeout=120, check=False).stdout.strip()
            record["semantic_comparison"] = verdict
            if verdict == "equal":
                config.write_bytes(original)
                record["restored"] = True
        elif original is None and current is not None:
            config.unlink()  # Hermes had no config.yaml before `skills trust` created one
            record["restored"] = True
        if record["restored"] or current == original:
            HERMES_CONFIG_BACKUP.unlink(missing_ok=True)
        final = config.read_bytes() if config.is_file() else None
        record["config_sha256_after"] = hashlib.sha256(final).hexdigest() if final else None
        write_json(evidence / "hermes_trust.json", record)


def hermes_probe(install: dict, fixture: dict, skill: str, instruction: str) -> dict:
    completed = subprocess.run(
        [str(install["python"]), "-X", "utf8", str(TESTS / "hermes_probe.py"), str(install["agent_dir"]),
         skill, instruction],
        cwd=fixture["cwd"], text=True, encoding="utf-8", errors="replace", capture_output=True,
        timeout=300, check=False)
    line = next((line for line in completed.stdout.splitlines() if line.startswith("MAGOS_PROBE_RESULT ")), None)
    if not line:
        return {"error": (completed.stdout[-600:] + completed.stderr[-600:]).strip()}
    return json.loads(line[len("MAGOS_PROBE_RESULT "):])


def probe_checks(probe: dict) -> list[dict]:
    registered = probe.get("registered") or {}
    invocation = probe.get("invocation") or {}
    return [
        {"name": "Hermes loads the fixture's project skills", "passed": bool(probe.get("project_skill_tier_trusted"))},
        {"name": "all seven slash commands resolve to the fixture copy",
         "passed": bool(registered) and all(item and item["from_fixture"] for item in registered.values())},
        {"name": "skills_guard verdict is not dangerous for any skill",
         "passed": bool(probe.get("guard")) and all(item["verdict"] != "dangerous" for item in probe["guard"].values())},
        {"name": "slash message carries skill directory and user instruction",
         "passed": bool(invocation.get("found") and invocation.get("has_skill_directory")
                        and invocation.get("has_user_instruction"))},
        {"name": "root skill references/commands.md is viewable",
         "passed": bool((probe.get("root_skill_reference_view") or {}).get("success"))},
    ]  # probe.json also records dotdot_view: a host detail the adapters work around, not a gate


def run_hermes_case(spec: dict, options: argparse.Namespace, fixture: dict, before: dict, evidence: Path) -> dict:
    """Run one case through Hermes: project-skill trust, deterministic probe, then `hermes -z`."""
    def finish(result: dict) -> dict:
        write_json(evidence / "result.json", result)
        (evidence / "summary.md").write_text(
            f"# {spec['id']} — hermes\n\nStatus: **{result['status']}**\nScope: {result['scope']}\n\n"
            f"Reason: {result.get('reason', 'See assertions/checks in result.json')}\n\n"
            "Evidence: probe.json, hermes_trust.json, invocation.json, first_stdout.txt, first_stderr.txt, "
            "before.json, after.json, observed.json.\n", encoding="utf-8")
        return result

    install = hermes_install()
    if not install or not install["python"]:
        return finish({"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime",
                       "reason": "Hermes CLI or its Python environment is unavailable"})
    if spec["assertion"] == "cleanup-stale":
        return finish({"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime",
                       "reason": "two-turn case is not supported for Hermes one-shot runs"})
    skill = spec["id"].split("/")[0]
    args = spec["args"].format(worktree=fixture.get("worktree", ""))
    context = spec.get("context", "").format(lane_head=fixture.get("lane_head", ""))
    instruction = "\n".join(part for part in (
        args,
        "The current working directory is a disposable acceptance-test fixture. "
        "Operate only in this fixture and its local origin; do not touch other repositories.",
        context) if part)
    with hermes_trusted(install, fixture["cwd"], evidence):
        probe = hermes_probe(install, fixture, skill, instruction)
        message = probe.pop("message", "")
        write_json(evidence / "probe.json", {"hermes": install["version"], **probe})
        checks = probe_checks(probe)
        if not all(item["passed"] for item in checks):
            return finish({"case": spec["id"], "status": "FAIL", "scope": "Hermes discovery probe (no model call)",
                           "checks": checks, "reason": probe.get("error", "probe check failed")})
        if options.fixture_check:
            return finish({"case": spec["id"], "status": "PASS", "checks": checks,
                           "scope": "fixture setup + Hermes discovery probe; no model call"})
        # `hermes -z` does not expand slash commands; send the exact message the interactive CLI
        # builds for `/<skill> <args>` (cli.py -> build_skill_invocation_message).
        command = [install["executable"], "-z", message]
        write_json(evidence / "invocation.json", {"host": "hermes", "hermes": install["version"],
                                                  "cwd": str(fixture["cwd"]), "skill_path": fixture["skill_path"],
                                                  "skill_source_sha256": fixture["skill_source_sha256"],
                                                  "slash_command": f"/{skill} {args}".strip(),
                                                  "user_instruction": instruction, "command": command[:2],
                                                  "message": message, "timeout_seconds": options.timeout})
        first = invoke_host(command, fixture["cwd"], fixture["base"], options.timeout)
    write_json(evidence / "first_call.json", {k: v for k, v in first.items() if k not in {"stdout", "stderr"}})
    (evidence / "first_stdout.txt").write_text(first["stdout"], encoding="utf-8")
    (evidence / "first_stderr.txt").write_text(first["stderr"], encoding="utf-8")
    after = snapshot(fixture)
    answer = first["stdout"].strip()
    write_json(evidence / "before.json", before)
    write_json(evidence / "after.json", after)
    write_json(evidence / "observed.json", {"answer": answer, "tool_calls": [], "structured_trace": False})
    runtime_error = RUNTIME_ERROR.search(first["stdout"] + "\n" + first["stderr"])
    if first["timed_out"] or first["returncode"] != 0 or not answer or runtime_error:
        return finish({"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime",
                       "returncode": first["returncode"],
                       "reason": "host timed out" if first["timed_out"] else
                       f"host runtime error: {runtime_error.group(0)}" if runtime_error else
                       "host did not return a usable agent response"})
    assertions = evaluate(spec, fixture, before, after, answer, [], False)
    if spec["assertion"] == "help":
        return finish({"case": spec["id"], "status": "UNVERIFIED", "scope": "actual Hermes one-shot run",
                       "assertions": assertions,
                       "reason": "Hermes one-shot output has no tool trace; 'no repository inspection' cannot be checked"})
    return finish({"case": spec["id"], "status": "PASS" if all(item["passed"] for item in assertions) else "FAIL",
                   "scope": "actual Hermes one-shot run and disposable Git state", "assertions": assertions})


def host_command(cwd: Path, options: argparse.Namespace) -> list[str] | None:
    """Build `codex exec`; the prompt goes through stdin (`-`) because the npm shim codex.cmd runs
    under cmd.exe, which cuts a multi-line argument at its first newline."""
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    if not executable:
        return None
    command = [executable, "exec", "--json", "--ephemeral",
               "-C", str(cwd), "-s", options.codex_sandbox,
               "-c", 'model_reasoning_effort="low"',
               "-c", "mcp_servers.serena.enabled=false"]
    if options.model:
        command += ["-m", options.model]
    return command + ["-"]


def extract_response(stdout: str) -> tuple[str, list[str], bool]:
    messages = []
    tool_calls = []
    tool_item_types = {
        "command_execution", "file_change", "mcp_tool_call", "collab_tool_call",
        "web_search", "function_call", "tool_call",
    }
    parsed_any = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        parsed_any = True
        item = event.get("item", {})
        if isinstance(item, dict):
            if item.get("type") == "agent_message" and item.get("text"):
                messages.append(str(item["text"]))
            if item.get("type") in tool_item_types:
                tool_calls.append(json.dumps(item, ensure_ascii=False))
        message = event.get("message", {})
        if isinstance(message, dict):
            for block in message.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    messages.append(str(block.get("text", "")))
                elif isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(json.dumps(block.get("input", {}), ensure_ascii=False))
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            messages.append(event["result"])
    return "\n".join(messages).strip(), tool_calls, parsed_any


def has_git_command(tool_calls: list[str]) -> bool:
    for tool_call in tool_calls:
        try:
            item = json.loads(tool_call)
        except json.JSONDecodeError:
            continue
        command = item.get("command") if isinstance(item, dict) else None
        if isinstance(command, str) and re.search(r"(?i)\bgit(?:\.exe)?\s", command):
            return True
    return False


def invoke_host(command: list[str], cwd: Path, base: Path, timeout: int, stdin_text: str | None = None) -> dict:
    """Run a host CLI; stdin carries `stdin_text` or is closed, never the runner's own stdin."""
    started = datetime.now(timezone.utc).isoformat()
    environment = os.environ.copy()
    environment["GIT_CEILING_DIRECTORIES"] = str(base)
    stdin = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    try:
        completed = subprocess.run(command, cwd=cwd, env=environment, text=True,
                                   encoding="utf-8", errors="replace", capture_output=True,
                                   timeout=timeout, check=False, **stdin)
        return {"started_utc": started, "returncode": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr, "timed_out": False}
    except subprocess.TimeoutExpired as error:
        return {"started_utc": started, "returncode": None,
                "stdout": str(error.stdout or ""), "stderr": str(error.stderr or ""),
                "timed_out": True}
    except OSError as error:
        return {"started_utc": started, "returncode": None,
                "stdout": "", "stderr": repr(error), "timed_out": False}


def evaluate(spec: dict, fixture: dict, before: dict, after: dict,
             answer: str, tool_calls: list[str], trace: bool,
             preview: str = "", mutated: dict | None = None) -> list[dict]:
    assertion = spec["assertion"]
    text = answer.casefold()
    def add(name: str, passed: bool) -> None:
        checks.append({"name": name, "passed": bool(passed)})
    def unchanged(allow_remote: bool = False) -> bool:
        first, second = copy.deepcopy(before), copy.deepcopy(after)
        if allow_remote:
            for item in (first, second):
                item["refs"] = {k: v for k, v in item["refs"].items()
                                if not k.startswith("refs/remotes/")}
        return first == second
    def has_any(*words: str) -> bool:
        return any(word.casefold() in text for word in words)
    checks = []
    if assertion == "help":
        add("usage includes --help", "--help" in text)
        option = {"git-recon": "--remote", "git-analyze": "--remote",
                  "git-recommend": "--remote", "git-integrate": "--strategy",
                  "git-cleanup": "--apply", "git-converge": "--apply"}[spec["id"].split("/")[0]]
        add("usage describes command option", option in text)
        add("repository state remains unchanged", before == after)
        add("structured trace permits inspection check", trace)
        add("no Git command", not has_git_command(tool_calls))
    elif assertion == "recon":
        add("reports main and agent/auth", "main" in text and "agent/auth" in text)
        add("reports dirty state", has_any("dirty", "未提交", "脏", "修改"))
        add("read-only Git state", unchanged())
    elif assertion in {"remote", "remote-recommend"}:
        add("origin/main refreshed", after["refs"].get("refs/remotes/origin/main") == fixture["remote_head"])
        add("branches, worktrees and files unchanged", unchanged(allow_remote=True))
        add("reports remote refresh", has_any("remote", "远端", "远程", "fetch"))
        if assertion == "remote-recommend":
            add("mentions requested lane", "agent/auth" in text)
    elif assertion in {"analyze", "analyze-worktree", "operation-matrix"}:
        add("identifies requested lane", "agent/auth" in text or
            (assertion == "analyze-worktree" and "auth-worktree" in text))
        add("compares with main", "main" in text)
        add("read-only Git state", unchanged())
        if assertion == "analyze-worktree":
            add("identifies dirty worktree", has_any("dirty", "未提交", "脏", "修改"))
        if assertion == "operation-matrix":
            for operation in ("merge", "rebase", "cherry-pick", "squash", "cleanup"):
                add(f"assesses {operation}", operation in text or
                    (operation == "cleanup" and has_any("delete", "清理", "删除")))
    elif assertion == "missing-target":
        add("requests target", has_any("target", "branch", "worktree", "目标", "分支"))
        add("read-only Git state", unchanged())
    elif assertion == "recommend":
        add("mentions candidate", "agent/auth" in text)
        add("read-only Git state", unchanged())
    elif assertion == "integration-gate":
        add("review gate reported", has_any("review", "acceptance", "评审", "审核", "验收"))
        # A permitted ref refresh (e.g. fetch creating refs/remotes/origin/HEAD) is not an integration.
        add("no integration performed", unchanged(allow_remote=True))
    elif assertion == "invalid-strategy":
        add("invalid strategy reported", has_any("invalid", "unsupported", "strategy", "无效", "不支持", "策略"))
        add("no integration performed", unchanged(allow_remote=True))
    elif assertion.startswith("integration-"):
        main_before = before["refs"]["refs/heads/main"]
        main_after = after["refs"]["refs/heads/main"]
        add("main advanced", main_before != main_after)
        add("source branch retained", after["refs"].get("refs/heads/agent/auth") == fixture["lane_head"])
        add("feature content in main", git(fixture["cwd"], "show", "main:feature.txt", check=False) == "accepted feature")
        add("worktrees clean", all(not tree["status"] for tree in after["worktrees"].values()))
        add("remote unchanged", before["bare_refs"] == after["bare_refs"])
        ancestry = is_ancestor(fixture["cwd"], fixture["lane_head"], "main")
        if assertion == "integration-merge":
            add("source is ancestor of main", ancestry)
        elif assertion in {"integration-squash", "integration-cherry-pick"}:
            add("source SHA not imported", not ancestry)
        add("reports post-validation", has_any("validat", "verif", "验证", "检查", "确认"))
    elif assertion == "cleanup-preview":
        add("classifies merged candidate", "agent/done" in text)
        add("identifies dirty or unique work", "agent/dirty" in text or "agent/unique" in text)
        add("preview leaves Git state unchanged", unchanged())
    elif assertion == "cleanup-apply":
        refs = after["refs"]
        add("merged safe branch removed", "refs/heads/agent/done" not in refs)
        add("dirty, unique and dependent branches retained", all(
            f"refs/heads/agent/{name}" in refs for name in ("dirty", "unique", "dependent")))
        add("main and remote unchanged", before["refs"]["refs/heads/main"] == refs["refs/heads/main"] and
            before["bare_refs"] == after["bare_refs"])
        add("dirty worktree preserved", str(fixture["worktree"]) in after["worktrees"] and
            bool(after["worktrees"][str(fixture["worktree"])]["status"]))
    elif assertion == "cleanup-stale":
        add("preview names safe candidate", "agent/done" in preview.casefold() and
            any(word in preview.casefold() for word in ("safe", "安全", "可清理")))
        add("candidate changed between calls", bool(mutated) and
            before["refs"]["refs/heads/agent/done"] != mutated["refs"]["refs/heads/agent/done"])
        add("stale candidate retained", after["refs"].get("refs/heads/agent/done") ==
            (mutated or {}).get("refs", {}).get("refs/heads/agent/done"))
        add("apply leaves mutated state unchanged", after == mutated)
        add("recheck reason reported", has_any("changed", "unique", "not integrated", "unmerged", "变更", "未合并", "重新检查"))
    return checks


def evidence_name(options: argparse.Namespace) -> str:
    if options.fixture_check:
        return "fixture-check" if options.host == "codex" else f"fixture-check-{options.host}"
    return f"host-{options.host}"


def run_case(spec: dict, options: argparse.Namespace) -> dict:
    case_dir = CASES / spec["id"]
    evidence = case_dir / "evidence" / evidence_name(options)
    evidence.mkdir(parents=True, exist_ok=True)
    write_json(case_dir / "host_case.json", spec)
    with tempfile.TemporaryDirectory(prefix=".magos-accept-", dir=options.fixture_root) as temporary:
        try:
            fixture = prepare_fixture(Path(temporary), spec["fixture"])
        except Exception as error:
            result = {"case": spec["id"], "status": "UNVERIFIED", "scope": "fixture setup",
                      "reason": f"{type(error).__name__}: {error}"}
            write_json(evidence / "result.json", result)
            (evidence / "harness_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            (evidence / "summary.md").write_text(
                f"# {spec['id']} — {options.host}\n\nStatus: **UNVERIFIED**\n"
                f"Scope: fixture setup\n\nReason: {result['reason']}\n\n"
                "Evidence: harness_error.txt records the fixture initialization exception.\n",
                encoding="utf-8",
            )
            return result
        provision_codex_skill(fixture, spec["id"].split("/")[0])
        before = snapshot(fixture)
        checks = verify_fixture(fixture, before)
        write_json(evidence / "fixture.json", {
            "kind": fixture["kind"], "checks": checks, "initial_state": before,
            "skill": fixture.get("skill"), "skill_path": fixture.get("skill_path"),
            "skill_source_sha256": fixture.get("skill_source_sha256"),
        })
        if not all(item["passed"] for item in checks):
            result = {"case": spec["id"], "status": "FAIL", "scope": "fixture setup",
                      "checks": checks}
            write_json(evidence / "result.json", result)
            return result
        if options.host == "hermes":
            return run_hermes_case(spec, options, fixture, before, evidence)
        if options.fixture_check:
            result = {"case": spec["id"], "status": "PASS", "scope": "fixture setup only; no AI host invoked",
                      "checks": checks}
            write_json(evidence / "result.json", result)
            return result
        skill = spec["id"].split("/")[0]
        args = spec["args"].format(worktree=fixture.get("worktree", ""))
        invocation = (HOST_NAME[skill] + " " + args).strip()
        context = spec.get("context", "").format(lane_head=fixture.get("lane_head", ""))
        prompt = (f"Invoke the project-local MAGOS skill from this acceptance-test checkout exactly as requested: {invocation}\n"
                  f"The current working directory is a disposable acceptance-test fixture. "
                  f"Operate only in this fixture and its local origin; do not touch other repositories.\n{context}")
        command = host_command(fixture["cwd"], options)
        shadows = user_level_installs()
        write_json(evidence / "invocation.json", {"host": options.host, "cwd": str(fixture["cwd"]),
                                                  "skill_path": fixture["skill_path"],
                                                  "skill_source_sha256": fixture["skill_source_sha256"],
                                                  "user_level_installs": shadows,
                                                  "command": command, "prompt": prompt,
                                                  "timeout_seconds": options.timeout})
        if shadows and not options.allow_user_install:
            result = {"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime",
                      "reason": "user-level MAGOS install may shadow the fixture copy: " + ", ".join(shadows)}
            write_json(evidence / "result.json", result)
            return result
        if not command:
            result = {"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime",
                      "reason": "host executable unavailable"}
            write_json(evidence / "result.json", result)
            return result
        first = invoke_host(command, fixture["cwd"], fixture["base"], options.timeout, prompt)
        write_json(evidence / "first_call.json", {k: v for k, v in first.items() if k not in {"stdout", "stderr"}})
        (evidence / "first_stdout.txt").write_text(first["stdout"], encoding="utf-8")
        (evidence / "first_stderr.txt").write_text(first["stderr"], encoding="utf-8")
        first_answer, first_calls, first_trace = extract_response(first["stdout"])
        preview = ""
        mutated = None
        last = first
        answer, calls, trace = first_answer, first_calls, first_trace
        if spec["assertion"] == "cleanup-stale" and first["returncode"] == 0 and first_answer:
            preview = first_answer
            after_preview = snapshot(fixture)
            write_json(evidence / "after_preview.json", after_preview)
            if after_preview == before:
                repo = fixture["cwd"]
                git(repo, "switch", "agent/done")
                (repo / "late.txt").write_text("new work after preview\n", encoding="utf-8")
                git(repo, "add", "late.txt")
                git(repo, "commit", "-m", "new work after cleanup preview")
                git(repo, "switch", "main")
                mutated = snapshot(fixture)
                write_json(evidence / "between_calls.json", {"operation": "new unique commit on agent/done",
                                                       "state": mutated})
                second_invocation = HOST_NAME[skill] + " " + spec["followup_args"]
                second_prompt = (f"Invoke the project-local MAGOS skill from this acceptance-test checkout exactly as requested: {second_invocation}. "
                                 "A candidate changed after the previous preview. Recheck it before applying cleanup. "
                                 "Operate only in this disposable fixture and its local origin.")
                second_command = host_command(repo, options)
                write_json(evidence / "second_invocation.json", {"command": second_command,
                                                                   "prompt": second_prompt, "cwd": str(repo)})
                last = invoke_host(second_command, repo, fixture["base"], options.timeout, second_prompt)
                (evidence / "second_stdout.txt").write_text(last["stdout"], encoding="utf-8")
                (evidence / "second_stderr.txt").write_text(last["stderr"], encoding="utf-8")
                answer, calls, trace = extract_response(last["stdout"])
                write_json(evidence / "second_call.json", {k: v for k, v in last.items() if k not in {"stdout", "stderr"}})
        after = snapshot(fixture)
        write_json(evidence / "before.json", before)
        write_json(evidence / "after.json", after)
        write_json(evidence / "observed.json", {"answer": answer, "tool_calls": calls,
                                               "structured_trace": trace, "preview_answer": preview})
        error_text = first["stdout"] + "\n" + first["stderr"] + "\n" + last["stdout"] + "\n" + last["stderr"]
        runtime_error = RUNTIME_ERROR.search(error_text)
        if first["timed_out"] or last["timed_out"] or runtime_error or \
                first["returncode"] != 0 or last["returncode"] != 0 or not answer:
            reason = "host timed out" if first["timed_out"] or last["timed_out"] else (
                "host runtime/auth/model/sandbox error" if runtime_error else
                "host did not return a usable agent response")
            result = {"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime", "reason": reason,
                      "returncode": last["returncode"]}
        elif spec["assertion"] == "help" and not trace:
            result = {"case": spec["id"], "status": "UNVERIFIED", "scope": "host runtime",
                      "reason": "structured tool trace unavailable; cannot check no repository inspection"}
        else:
            assertions = evaluate(spec, fixture, before, after, answer, calls, trace, preview, mutated)
            result = {"case": spec["id"], "status": "PASS" if all(x["passed"] for x in assertions) else "FAIL",
                      "scope": "actual host CLI invocation and disposable Git state", "assertions": assertions}
        write_json(evidence / "result.json", result)
        lines = [f"# {spec['id']} — {options.host}", "", f"Status: **{result['status']}**",
                 f"Scope: {result['scope']}", "", f"Reason: {result.get('reason', 'See assertions in result.json')}",
                 "", "Evidence: invocation.json, first_stdout.txt, first_stderr.txt, before.json, after.json, observed.json."]
        (evidence / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Real host CLI acceptance in disposable Git fixtures")
    parser.add_argument("--host", choices=("codex", "hermes"), default="codex",
                        help="host CLI to run; hermes uses project-local skills in each trusted fixture")
    parser.add_argument("--case", action="append", default=[], help="glob case ID; repeatable")
    parser.add_argument("--fixture-check", action="store_true", help="verify fixture setup only; no model calls")
    parser.add_argument("--model", help="optional host model override")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--allow-user-install", action="store_true",
                        help="run even if ~/.agents/skills/MAGOS or $CODEX_HOME/skills/MAGOS exists; Codex may "
                             "then load that copy instead of the fixture's")
    parser.add_argument("--fixture-root", type=Path, default=TESTS,
                        help="directory for disposable fixtures (default: tests/codex); use a short path "
                             "if Windows reports 'Filename too long'")
    parser.add_argument("--codex-sandbox", choices=("read-only", "workspace-write", "danger-full-access"),
                        default="workspace-write")
    options = parser.parse_args()
    specs = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = [spec for spec in specs if not options.case or
                any(fnmatch.fnmatchcase(spec["id"], pattern) for pattern in options.case)]
    if not selected:
        parser.error("no case matches --case")
    if options.fixture_check:
        fixture_specs = []
        seen_fixtures = set()
        for spec in selected:
            if spec["fixture"] not in seen_fixtures:
                fixture_specs.append(spec)
                seen_fixtures.add(spec["fixture"])
        selected = fixture_specs
    results = []
    for spec in selected:
        try:
            result = run_case(spec, options)
        except Exception as error:
            evidence = CASES / spec["id"] / "evidence" / evidence_name(options)
            evidence.mkdir(parents=True, exist_ok=True)
            result = {"case": spec["id"], "status": "UNVERIFIED", "scope": "test harness",
                      "reason": f"{type(error).__name__}: {error}"}
            write_json(evidence / "result.json", result)
            (evidence / "harness_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            (evidence / "summary.md").write_text(
                f"# {spec['id']} — {options.host}\n\nStatus: **UNVERIFIED**\n"
                f"Scope: test harness\n\nReason: {result['reason']}\n\n"
                "Evidence: harness_error.txt records the test harness exception.\n",
                encoding="utf-8",
            )
        results.append(result)
        print(f"{result['status']:10} {result['case']}", flush=True)
    counts = {status: sum(item["status"] == status for item in results)
              for status in ("PASS", "FAIL", "UNVERIFIED")}
    label = f"{options.host} fixture setups" if options.fixture_check else f"{options.host} host cases"
    print(f"{label}: {counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['UNVERIFIED']} UNVERIFIED")
    return 1 if counts["FAIL"] else (2 if counts["UNVERIFIED"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
