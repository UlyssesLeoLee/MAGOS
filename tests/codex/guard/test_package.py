"""Shipped files around the guard: hook wiring, endings, contract anchors, and the package rules the guard must not break."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys

import pytest

from conftest import G, ROOT


def test_hooks_json_wiring():
    doc = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    groups = doc["hooks"]["PreToolUse"]
    assert [g["matcher"] for g in groups] == ["^EnterWorktree$", "^(Bash|PowerShell|Agent|Task|Workflow)$|^mcp__.*(start_session|worktree|branch|hand_off_to_session)"]
    strict, soft = (g["hooks"][0] for g in groups)
    assert strict["command"] == '"${CLAUDE_PLUGIN_ROOT}/hooks/run-guard.cmd" --strict hook claude pre-tool'
    assert soft["command"] == '"${CLAUDE_PLUGIN_ROOT}/hooks/run-guard.cmd" hook claude pre-tool'
    assert strict["type"] == soft["type"] == "command" and strict["timeout"] == soft["timeout"] == 25
    assert strict["shell"] == soft["shell"] == "bash"  # the quoted ${CLAUDE_PLUGIN_ROOT} form is bash syntax
    for g in groups:  # anchored regexes: BashOutput, TaskList and similar tools never match
        assert g["matcher"].startswith("^")
        assert not re.search(g["matcher"], "BashOutput") and not re.search(g["matcher"], "TaskList")
    assert re.search(groups[1]["matcher"], "mcp__ccd_session__start_session")


def test_line_endings_are_pinned():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    for needle in ("*.cmd text eol=lf", "hooks/hooks.json text eol=lf", "scripts/magos_guard.py text eol=lf", ".quality/** text eol=lf"):
        assert needle in attrs
    for rel in ("hooks/hooks.json", "scripts/magos_guard.py", "hooks/run-guard.cmd"):
        assert b"\r" not in (ROOT / rel).read_bytes(), rel


def test_guard_is_standard_library_only():
    tree = ast.parse((ROOT / "scripts" / "magos_guard.py").read_text(encoding="utf-8"))
    modules = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert modules <= set(sys.stdlib_module_names) | {"msvcrt", "fcntl"}, modules
    assert ast.get_docstring(tree).startswith("MAGOS lane guard")


def test_hook_body_is_valid_posix_sh():
    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no sh")
    assert G.HOOK_SH.startswith("#!/bin/sh\n") and "\r" not in G.HOOK_SH and G.MARK in G.HOOK_SH
    assert subprocess.run([sh, "-n"], input=G.HOOK_SH.encode("utf-8"), capture_output=True).returncode == 0


def test_contract_and_skill_anchors():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    description = re.search(r'^description: "(.*)"$', skill, re.M).group(1)
    assert 0 < len(description) <= 1024 and description.startswith("Automatically use for") and description.endswith("shared-history safety matters.")
    assert "10. **A lane's files are planned before the lane exists.**" in skill and "`references/lane-split.md`" in skill
    assert "create a branch or worktree without a registered file manifest" in skill
    contract = (ROOT / "references" / "lane-split.md").read_text(encoding="utf-8")
    for needle in ("No manifest, no lane.", "A denial stops only the creation.", "Only the user overrides.", "Unknown is not safe.", "## 12. Honest Limits"):
        assert needle in contract
    codes = {int(c) for c in re.findall(r"(\d+) (?:allowed|denied|unknown|invalid|lock|the lane|the branch|release)", contract)}
    assert codes <= set(G.EXIT.values())
    assert "scripts/magos_guard.py" in contract and (ROOT / "references").glob("lane-split.md")
    commands = (ROOT / "references" / "commands.md").read_text(encoding="utf-8")
    assert "holds an open lane-guard claim" in commands and "magos_guard.py release --branch <lane> --reason integrated" in commands


def test_package_rules_still_hold():
    claude = sorted(p.name for p in (ROOT / ".claude-plugin").iterdir())
    assert claude == ["marketplace.json", "plugin.json"]  # no hook file next to the manifests
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "hooks" not in plugin and set(plugin) <= {"name", "version", "description", "author", "homepage", "repository", "license", "keywords"}
    spec = __import__("importlib.util").util.spec_from_file_location("sync_hosts_real", ROOT / "scripts" / "sync_hosts.py")
    mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = mod.package_files(ROOT)
    assert "references/lane-split.md" in files and "scripts/magos_guard.py" not in files and "hooks/hooks.json" not in files
    assert re.fullmatch(r"[A-Za-z0-9_.-]+\.md", "lane-split.md") and (ROOT / "references" / "lane-split.md").is_file()


def test_launcher_is_staged_executable():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", "hooks/run-guard.cmd"], capture_output=True, text=True).stdout
    if out:  # tracked: a plugin hook that is run directly on POSIX needs the executable bit
        assert out.startswith("100755"), out
