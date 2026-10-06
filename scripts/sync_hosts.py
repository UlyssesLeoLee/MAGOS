# ```cypher
# CREATE
#   (file:File {name: 'sync_hosts.py', type: 'file', language: 'python'}),
#   (module:Module {name: 'sync_hosts', type: 'module', language: 'python'}),
#   (command_names:Variable {name: 'COMMAND_NAMES', type: 'variable'}),
#   (command_paths:Variable {name: 'COMMAND_PATHS', type: 'variable'}),
#   (package:Function {name: 'package_files', type: 'function'}),
#   (codex_root:Function {name: 'codex_install_root', type: 'function'}),
#   (build:Function {name: 'build_targets', type: 'function'}),
#   (hash:Function {name: 'file_sha256', type: 'function'}),
#   (inspect:Function {name: 'inspect', type: 'function'}),
#   (copy:Function {name: 'copy_file', type: 'function'}),
#   (render:Function {name: 'render', type: 'function'}),
#   (main:Function {name: 'main', type: 'function'}),
#   (selected_hosts:Variable {name: 'selected_hosts', type: 'variable'}),
#   (file)-[:CONTAINS]->(module),
#   (module)-[:CONTAINS]->(command_names),
#   (module)-[:CONTAINS]->(command_paths),
#   (module)-[:CONTAINS]->(package),
#   (module)-[:CONTAINS]->(codex_root),
#   (module)-[:CONTAINS]->(build),
#   (module)-[:CONTAINS]->(hash),
#   (module)-[:CONTAINS]->(inspect),
#   (module)-[:CONTAINS]->(copy),
#   (module)-[:CONTAINS]->(render),
#   (module)-[:CONTAINS]->(main),
#   (build)-[:USES]->(command_paths),
#   (build)-[:CALLS]->(package),
#   (build)-[:CALLS]->(codex_root),
#   (inspect)-[:CALLS]->(build),
#   (inspect)-[:CALLS]->(hash),
#   (main)-[:CALLS]->(inspect),
#   (main)-[:CALLS]->(build),
#   (main)-[:CALLS]->(copy),
#   (main)-[:CALLS]->(render),
#   (main)-[:USES]->(selected_hosts),
#   (build)-[:USES]->(selected_hosts),
#   (inspect)-[:USES]->(selected_hosts);
# ```
"""Compare or synchronize MAGOS host installs (Claude commands, Codex and Hermes packages)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


COMMAND_NAMES = ("GitRecon", "GitAnalyze", "GitRecommend", "GitIntegrate", "GitCleanup", "GitConverge")
COMMAND_PATHS = tuple(f"commands/{name}.md" for name in COMMAND_NAMES)
PACKAGE_NAME = "MAGOS"
HERMES_PACKAGE_NAME = "multi-agent-git-orchestrator"


def package_files(repo: Path) -> tuple[str, ...]:
    """Relative paths of the host-neutral skill package used by Codex and Hermes.

    The adapters in skills/ resolve ../../SKILL.md and ../../references/*.md, so the
    installed tree must keep this layout. The test harness provisions the same list.
    plugin.json (the Agent Plugins manifest of the whole repository), commands/, tests/
    and the READMEs are not part of it; Codex and Hermes skill discovery never reads
    plugin.json.
    """
    references = sorted(path.relative_to(repo).as_posix()
                        for path in (repo / "references").glob("*.md"))
    adapters = []
    for skill in sorted(path.parent for path in (repo / "skills").glob("*/SKILL.md")):
        adapters.append((skill / "SKILL.md").relative_to(repo).as_posix())
        metadata = skill / "agents" / "openai.yaml"
        if metadata.is_file():
            adapters.append(metadata.relative_to(repo).as_posix())
    return ("SKILL.md", *references, *adapters)


def codex_install_root(home: Path, explicit_home: bool) -> tuple[Path, list[str]]:
    """Choose the Codex user skills root and report duplicate-install risks.

    Codex loads ~/.agents/skills (current) and $CODEX_HOME/skills (deprecated but
    still scanned). An existing legacy install is kept in place; new installs use
    ~/.agents/skills.
    """
    codex_home = Path(os.environ["CODEX_HOME"]) if os.environ.get("CODEX_HOME") and not explicit_home \
        else home / ".codex"
    current = home / ".agents" / "skills" / PACKAGE_NAME
    legacy = codex_home / "skills" / PACKAGE_NAME
    notes: list[str] = []
    if current.is_dir() and legacy.is_dir():
        notes.append(f"Both {current} and {legacy} exist; Codex loads both and sees duplicate skills. "
                     f"Keep one install.")
        return current, notes
    if legacy.is_dir():
        notes.append(f"Using legacy Codex root {legacy}; ~/.agents/skills is the current location.")
        return legacy, notes
    return current, notes


def hermes_home(home: Path, explicit_home: bool) -> Path:
    """Mirror Hermes: HERMES_HOME, then %LOCALAPPDATA%\\hermes on Windows, then ~/.hermes.

    With an explicit --home, environment overrides are ignored so tests stay inside that home.
    """
    if os.environ.get("HERMES_HOME", "").strip() and not explicit_home:
        return Path(os.environ["HERMES_HOME"].strip())
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = (Path(local_appdata) if local_appdata and not explicit_home else home / "AppData" / "Local") / "hermes"
    else:
        base = home / ".hermes"
    if not explicit_home:
        # The `hermes` launcher follows a sticky profile: HERMES_HOME=<root>/profiles/<name>.
        try:
            active = (base / "active_profile").read_text(encoding="utf-8").strip()
        except OSError:
            active = ""
        if active and active != "default" and (base / "profiles" / active).is_dir():
            return base / "profiles" / active
    return base


def hermes_install_root(home: Path, explicit_home: bool) -> tuple[Path, list[str]]:
    """Prefer an existing Hermes install so Hermes does not see duplicate skill names."""
    skills = hermes_home(home, explicit_home) / "skills"
    preferred = skills / HERMES_PACKAGE_NAME
    existing = skills / PACKAGE_NAME
    notes: list[str] = []
    if preferred.is_dir() and existing.is_dir():
        notes.append(f"Both {preferred} and {existing} exist; Hermes keeps the first skill of each name. "
                     f"Keep one install.")
        return preferred, notes
    if existing.is_dir():
        notes.append(f"Using existing Hermes install {existing}.")
        return existing, notes
    return preferred, notes


def build_targets(home: Path, selected_hosts: tuple[str, ...], repo: Path, explicit_home: bool = True,
                  codex_root: Path | None = None, hermes_root: Path | None = None,
                  ) -> tuple[tuple[str, Path, Path, tuple[str, ...]], list[str]]:
    """Return (host, target root, required installed directory, relative files) and notes."""
    notes: list[str] = []
    claude = home / ".claude"
    if codex_root is None:
        codex_root, codex_notes = codex_install_root(home, explicit_home)
        if "codex" in selected_hosts:
            notes += codex_notes
    if hermes_root is None:
        hermes_root, hermes_notes = hermes_install_root(home, explicit_home)
        if "hermes" in selected_hosts:
            notes += hermes_notes
    package = package_files(repo)
    targets = (
        ("claude", claude, claude / "commands", COMMAND_PATHS),
        ("codex", codex_root, codex_root, package),
        ("hermes", hermes_root, hermes_root, package),
    )
    selected = tuple(target for target in targets if target[0] in selected_hosts)
    return selected, notes


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(repo: Path, targets: tuple[tuple[str, Path, Path, tuple[str, ...]], ...],
            home: Path, selected_hosts: tuple[str, ...], notes: list[str]) -> dict[str, object]:
    """Inventory source and installed bytes without changing either tree."""
    source_hashes: dict[str, str] = {}
    source_errors: list[str] = []
    for relative in sorted({path for target in targets for path in target[3]}):
        source = repo / relative
        if not source.is_file() or source.is_symlink():
            source_errors.append(f"Missing or unsafe repository source: {source}")
        else:
            source_hashes[relative] = file_sha256(source)

    hosts: list[dict[str, str]] = []
    files: list[dict[str, str | None]] = []
    for host, root, required, relatives in targets:
        if not required.is_dir():
            hosts.append({
                "host": host,
                "status": "missing-root",
                "required_directory": str(required),
            })
            continue
        if (required / ".git").exists():
            hosts.append({
                "host": host,
                "status": "git-checkout",
                "required_directory": str(required),
                "reason": "installed root is a git checkout; update it with git instead of copying files",
            })
            continue
        hosts.append({"host": host, "status": "ready", "required_directory": str(required)})
        resolved_root = root.resolve()
        for relative in relatives:
            destination = root / relative
            record: dict[str, str | None] = {
                "host": host,
                "relative_path": relative,
                "destination": str(destination),
                "source_sha256": source_hashes.get(relative),
                "installed_sha256": None,
            }
            if relative not in source_hashes:
                record["status"] = "blocked"
                record["reason"] = "repository source is unavailable"
            elif not destination.resolve().is_relative_to(resolved_root):
                record["status"] = "blocked"
                record["reason"] = "destination escapes the installed root"
            elif destination.is_symlink() or (destination.exists() and not destination.is_file()):
                record["status"] = "blocked"
                record["reason"] = "destination is a symlink or is not a regular file"
            elif not destination.exists():
                record["status"] = "missing"
            else:
                record["installed_sha256"] = file_sha256(destination)
                record["status"] = (
                    "matched" if record["installed_sha256"] == record["source_sha256"] else "different"
                )
            files.append(record)

    counts = {status: sum(record["status"] == status for record in files)
              for status in ("matched", "missing", "different", "blocked")}
    counts["missing_roots"] = sum(host["status"] == "missing-root" for host in hosts)
    counts["git_checkouts"] = sum(host["status"] == "git-checkout" for host in hosts)
    counts["source_errors"] = len(source_errors)
    return {"home": str(home), "selected_hosts": list(selected_hosts), "hosts": hosts, "files": files,
            "source_errors": source_errors, "notes": notes, "summary": counts}


def copy_file(source: Path, destination: Path, root: Path, expected_sha256: str) -> None:
    """Atomically replace one adapter after checking its source and destination."""
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise RuntimeError(f"Repository source changed during sync: {source}")
    if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"Destination became unsafe during sync: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_handle, temporary_name = tempfile.mkstemp(prefix=".magos-sync-", dir=destination.parent)
    try:
        with os.fdopen(file_handle, "wb") as stream:
            stream.write(content)
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def render(report: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"MAGOS install {report['mode']}: {report['home']}")
    for note in report["notes"]:
        print(f"NOTE {note}")
    for error in report["source_errors"]:
        print(f"SOURCE ERROR {error}")
    for host in report["hosts"]:
        print(f"{host['host']}: {host['status']} ({host['required_directory']})")
        if host.get("reason"):
            print(f"    {host['reason']}")
    for item in report["files"]:
        source_hash = item["source_sha256"] or "-"
        installed_hash = item["installed_sha256"] or "-"
        print(f"  {item['host']} {item['status']} {item['relative_path']} "
              f"source={source_hash} installed={installed_hash}")
        if item.get("reason"):
            print(f"    {item['reason']}")
    if report.get("created_roots"):
        print(f"Created roots: {', '.join(report['created_roots'])}")
    if report.get("written"):
        print(f"Written: {len(report['written'])}")
    if report.get("error"):
        print(f"ERROR {report['error']}")
    print(f"Summary: {report['summary']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path,
                        help="User home containing .claude, .agents/.codex and .hermes installs (default: ~)")
    parser.add_argument("--host", choices=("claude", "codex", "hermes"), action="append",
                        help="Limit inspection or synchronization to this host; repeat to select multiple hosts")
    parser.add_argument("--codex-root", type=Path,
                        help="Codex package root (default: ~/.agents/skills/MAGOS, or an existing "
                             "$CODEX_HOME/skills/MAGOS)")
    parser.add_argument("--hermes-root", type=Path,
                        help="Hermes package root (default: <Hermes home>/skills/multi-agent-git-orchestrator, or "
                             "an existing <Hermes home>/skills/MAGOS; Hermes home is HERMES_HOME, else "
                             "%%LOCALAPPDATA%%\\hermes on Windows, else ~/.hermes)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="Exit nonzero if any installed file differs")
    mode.add_argument("--apply", action="store_true", help="Copy missing or different files")
    parser.add_argument("--create-roots", action="store_true",
                        help="With --apply, create missing install roots instead of failing preflight")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable report")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    explicit_home = args.home is not None
    home = (args.home or Path.home()).expanduser().resolve()
    selected_hosts = tuple(args.host or ("claude", "codex", "hermes"))
    targets, notes = build_targets(home, selected_hosts, repo, explicit_home,
                                   args.codex_root, args.hermes_root)
    created: list[str] = []
    report = inspect(repo, targets, home, selected_hosts, notes)
    counts = report["summary"]
    # Create missing roots only when nothing else would fail preflight, so a refused run writes nothing.
    if (args.apply and args.create_roots and counts["missing_roots"]
            and not (counts["git_checkouts"] or counts["source_errors"] or counts["blocked"])):
        for _, _, required, _ in targets:
            if not required.is_dir():
                required.mkdir(parents=True, exist_ok=True)
                created.append(str(required))
        report = inspect(repo, targets, home, selected_hosts, notes)
    report["mode"] = "apply" if args.apply else "verify" if args.verify else "plan"
    report["created_roots"] = created
    counts = report["summary"]
    if counts["missing_roots"] or counts["git_checkouts"] or counts["source_errors"] or counts["blocked"]:
        report["error"] = ("Preflight failed; create the listed installed roots (or use --apply --create-roots), "
                           "update git-checkout installs with git (or select other hosts), "
                           "or fix blocked paths. No files were written.")
        render(report, args.json)
        return 2

    if args.apply:
        roots = {host: root for host, root, _, _ in targets}
        written: list[str] = []
        try:
            for item in report["files"]:
                if item["status"] not in ("missing", "different"):
                    continue
                relative = item["relative_path"]
                copy_file(repo / relative, Path(item["destination"]), roots[item["host"]],
                          item["source_sha256"])
                written.append(f"{item['host']}:{relative}")
        except (OSError, RuntimeError) as exc:
            report["written"] = written
            report["error"] = f"Sync stopped after a write error: {exc}. Rerun --verify or --apply."
            render(report, args.json)
            return 2
        report = inspect(repo, targets, home, selected_hosts, notes)
        report["mode"] = "apply"
        report["created_roots"] = created
        report["written"] = written
        if any(report["summary"][status] for status in
               ("missing", "different", "blocked", "missing_roots", "git_checkouts", "source_errors")):
            report["error"] = "Some files did not match after writing."
            render(report, args.json)
            return 2

    render(report, args.json)
    if args.verify and (counts["missing"] or counts["different"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
