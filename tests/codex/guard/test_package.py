"""Shipped files around the guard: hook wiring, endings, contract anchors, and the package rules the guard must not break."""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tokenize

import pytest

from conftest import SH, G, ROOT

# Standard-library modules of Python 3.9, for the interpreters without sys.stdlib_module_names (3.10+).
STDLIB_FALLBACK = frozenset("""
__future__ abc argparse array ast asyncio base64 binascii bisect bz2 calendar codecs collections concurrent contextlib copy csv
ctypes dataclasses datetime decimal difflib email enum errno fcntl filecmp fnmatch fractions functools getpass gettext glob
gzip hashlib heapq hmac html http importlib inspect io ipaddress itertools json keyword locale logging lzma math mimetypes
msvcrt multiprocessing ntpath numbers operator os pathlib pickle platform plistlib posixpath pprint queue random re secrets
select selectors shlex shutil signal socket sqlite3 stat statistics string struct subprocess sys sysconfig tempfile textwrap
threading time timeit traceback types typing unicodedata unittest urllib uuid warnings weakref winreg xml zipfile zlib
""".split())


def test_hooks_json_wiring():
    doc = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    groups = doc["hooks"]["PreToolUse"]
    assert [g["matcher"] for g in groups] == ["^EnterWorktree$", G.claude_matcher()]
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
    for stdlib in (getattr(sys, "stdlib_module_names", None) or STDLIB_FALLBACK, STDLIB_FALLBACK):  # the fallback is checked everywhere
        assert modules <= set(stdlib) | {"msvcrt", "fcntl"}, modules - set(stdlib)
    assert ast.get_docstring(tree).startswith("MAGOS lane guard")


def test_hook_body_is_valid_posix_sh():
    if not SH:
        pytest.skip("no sh")
    assert G.HOOK_SH.startswith("#!/bin/sh\n") and "\r" not in G.HOOK_SH and G.MARK in G.HOOK_SH
    assert subprocess.run([SH, "-n"], input=G.HOOK_SH.encode("utf-8"), capture_output=True).returncode == 0
    launcher = (ROOT / "hooks" / "run-guard.cmd").read_bytes()
    assert subprocess.run([SH, "-n"], input=launcher, capture_output=True).returncode == 0  # the launcher's sh half parses too


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
    assert claude == ["icon.png", "marketplace.json", "plugin.json"]  # the two manifests and the listing icon: no hook file next to them
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "hooks" not in plugin and set(plugin) <= {"name", "version", "description", "author", "homepage", "repository", "license", "keywords"}
    spec = __import__("importlib.util").util.spec_from_file_location("sync_hosts_real", ROOT / "scripts" / "sync_hosts.py")
    mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = mod.package_files(ROOT)
    assert "references/lane-split.md" in files and "scripts/magos_guard.py" not in files and "hooks/hooks.json" not in files
    assert re.fullmatch(r"[A-Za-z0-9_.-]+\.md", "lane-split.md") and (ROOT / "references" / "lane-split.md").is_file()


def test_launcher_is_staged_executable():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", "hooks/run-guard.cmd"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL).stdout
    if not out:  # an installed plugin copy has no .git: nothing to read the mode from
        pytest.skip("hooks/run-guard.cmd is not tracked in a git work tree here")
    assert out.startswith("100755"), out  # a plugin hook that is run directly on POSIX needs the executable bit


# The Hermes plugin scanner (tools/skills_guard.py, rule echo_pipe_exec) rates text echoed into a shell or an interpreter as
# critical: one such line anywhere in the plugin turns an unattended `hermes plugins install` or `update` into a refusal.
# It reads the files whose suffix is in its SCANNABLE_EXTENSIONS, and every SKILL.md; the regex is its own, case-insensitive.
ECHO_PIPE_EXEC = re.compile(r"echo\s+[^\n]*\|\s*(?:(?:bash|sh|zsh|ksh|dash)\b|python|perl|ruby|node)", re.IGNORECASE)
SCANNED_SUFFIXES = frozenset({".md", ".txt", ".py", ".sh", ".bash", ".js", ".ts", ".rb", ".yaml", ".yml", ".json", ".toml",
                              ".cfg", ".ini", ".conf", ".html", ".css", ".xml", ".tex", ".r", ".jl", ".pl", ".php"})


def shipped_files():
    """Every file a host receives.  Claude Code, Codex and Hermes take the whole repository, so in a git work tree that is the
    tracked files plus the untracked files git does not ignore; in an installed copy without .git, every file below ROOT."""
    try:
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                                capture_output=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:  # no git: read the tree as installed
        listed = None
    if listed is not None and listed.returncode == 0 and listed.stdout:
        return sorted({ROOT / rel for rel in listed.stdout.decode("utf-8").split("\0") if rel})
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.relative_to(ROOT).parts)


def test_no_shipped_line_looks_like_an_echo_pipe_exec():
    data = ROOT / "tests" / "codex" / "guard" / "data" / "echo_pipe_forms.jsonl"
    forms = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert forms and all(ECHO_PIPE_EXEC.search(row["cmd"]) for row in forms)  # the rule is live: the detector cases match it
    assert data.suffix not in SCANNED_SUFFIXES  # and they sit in a file the scanner does not read
    files = shipped_files()
    assert ROOT / "SKILL.md" in files and ROOT / "tests" / "codex" / "guard" / "test_detector.py" in files
    offenders = []
    for path in files:
        if path.suffix.lower() not in SCANNED_SUFFIXES and path.name != "SKILL.md":
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").split("\n")
        except (OSError, UnicodeDecodeError):  # the scanner skips a file it cannot read as UTF-8 as well
            continue
        offenders += ["%s:%d" % (path.relative_to(ROOT).as_posix(), number) for number, line in enumerate(lines, 1)
                      if ECHO_PIPE_EXEC.search(line)]
    assert offenders == []


# The same scanner rates two more shapes as high, and one high finding also refuses an unattended install or update: the
# privilege-escalation command word outside a string literal (rule sudo_usage) and an environment dump (rule dump_all_env,
# string literals included). Both patterns are assembled from parts, so this file does not carry the shapes it looks for.
PRIV_WORD, DUMP_WORD = "su" + "do", "print" + "env"
SUDO_WORD = re.compile(r"\b%s\b" % PRIV_WORD)
ENV_DUMP = re.compile(r"%s|(?<![A-Za-z0-9_])env\s*\|(?!\|)(?!\s*[{(])" % DUMP_WORD)


def test_no_shipped_line_has_the_scanners_other_high_shapes():
    assert SUDO_WORD.search("# runs under " + PRIV_WORD) and ENV_DUMP.search('r"(?:en' + 'v|command)"')  # the rules are live
    offenders = []
    for path in shipped_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() not in SCANNED_SUFFIXES and path.name != "SKILL.md":
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        offenders += ["%s:%d env-dump" % (rel, n) for n, line in enumerate(text.split("\n"), 1) if ENV_DUMP.search(line)]
        if path.suffix.lower() == ".py":
            try:
                tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            except (tokenize.TokenError, SyntaxError):
                continue
            offenders += ["%s:%d sudo-in-comment" % (rel, tok.start[0]) for tok in tokens
                          if tok.type == tokenize.COMMENT and SUDO_WORD.search(tok.string)]
    assert offenders == []


def test_claude_matcher_is_generated_from_the_hooked_tool_list(tmp_path):
    groups = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    snippet = json.loads(G.host_snippet("claude", tmp_path.as_posix()))["hooks"]["PreToolUse"]
    assert [g["matcher"] for g in groups] == [g["matcher"] for g in snippet] == [G.claude_matcher(strict=True), G.claude_matcher()]
    soft, strict = G.claude_matcher(), G.claude_matcher(strict=True)
    for name in G.HOOKED_TOOLS["shell"] + G.HOOKED_TOOLS["isolation"]:  # the Claude Code tools of the constant
        assert re.search(soft, name), name
    for word in G.HOOKED_TOOLS["mcp_shell"] + G.HOOKED_TOOLS["mcp_session"]:  # the MCP words of the constant, after any server name
        assert re.search(soft, "mcp__server__" + word), word
    for name in ("Bash", "PowerShell", "Monitor", "Agent", "mcp__terminal__run_in_terminal", "mcp__ccd_session__start_session", "mcp__serena__execute_shell_command",
                 "mcp__iterm__write_to_terminal", "mcp__windows-mcp__Powershell-Tool", "mcp__x__run_command", "mcp__x__cmd", "mcp__desktop-commander__start_process"):
        assert re.search(soft, name), name
    for name in ("mcp__scheduled-tasks__run_scheduled_task", "mcp__gbrain__run_doctor", "Read", "BashOutput", "TaskList", "EnterWorktree", "XBash"):
        assert not re.search(soft, name), name
    assert re.search(strict, "EnterWorktree") and not re.search(strict, "EnterWorktreeX") and not re.search(strict, "Bash")
    assert all(G.is_shell_tool(name) for name in G.HOOKED_TOOLS["shell"])  # what the hook routes, the guard reads as a command


def _mini_yaml(text):
    """A strict reader for the Hermes snippet's YAML shape (two nested keys, one sequence item of scalars); scalars are single-quoted
    ('' stands for '), double-quoted, integers or booleans.  Anything else raises ValueError."""
    def scalar(raw):
        if raw.startswith("'"):
            if not re.fullmatch(r"'(?:[^']|'')*'", raw):
                raise ValueError("invalid single-quoted scalar: %s" % raw)
            return raw[1:-1].replace("''", "'")
        if raw.startswith('"'):
            if not re.fullmatch(r'"[^"\\]*"', raw):
                raise ValueError("unexpected double-quoted scalar: %s" % raw)
            return raw[1:-1]
        if raw in ("true", "false"):
            return raw == "true"
        if re.fullmatch(r"[0-9]+", raw):
            return int(raw)
        raise ValueError("unexpected scalar: %s" % raw)
    lines = [line for line in text.split("\n") if line.strip()]
    if lines[:2] != ["hooks:", "  pre_tool_call:"] or len(lines) < 3:
        raise ValueError("unexpected structure")
    item = {}
    for i, line in enumerate(lines[2:]):
        indent, body = line[:6], line[6:]
        key, sep, raw = body.partition(": ")
        if indent != ("    - " if i == 0 else "      ") or not sep or not re.fullmatch(r"[a-z_]+", key) or key in item:
            raise ValueError("unexpected line: %s" % line)
        item[key] = scalar(raw)
    return {"hooks": {"pre_tool_call": [item]}}


def test_hermes_snippet_is_valid_yaml_on_every_platform(monkeypatch):
    with pytest.raises(ValueError):  # the reader rejects the unescaped POSIX command that 1.0.1 generated
        _mini_yaml("hooks:\n  pre_tool_call:\n    - matcher: \"terminal\"\n      command: 'sh '/home/u/.magos/guard/hooks/run-guard.cmd' hook'\n")
    try:
        import yaml
    except ImportError:
        yaml = None
    for platform, home, prefix in (("win32", "C:/Users/o'brien x/.magos", []), ("linux", "/home/o'brien x/.magos", ["sh"]),
                                   ("linux", "/home/u/.magos", ["sh"])):
        monkeypatch.setattr(G.sys, "platform", platform)
        text = G.host_snippet("hermes", home)
        docs = [_mini_yaml(text)] + ([yaml.safe_load(text)] if yaml else [])
        for doc in docs:
            entry = doc["hooks"]["pre_tool_call"]
            assert len(entry) == 1 and set(entry[0]) == {"matcher", "command", "timeout", "fail_closed"}, (platform, doc)
            assert entry[0]["matcher"] == "terminal" and entry[0]["timeout"] == 25 and entry[0]["fail_closed"] is True, (platform, doc)
            command = entry[0]["command"]
            assert shlex.split(command) == prefix + [home + "/guard/hooks/run-guard.cmd", "hook", "hermes", "pre-tool"], (platform, command)
            assert "--strict" not in command  # fail-open on infrastructure errors by default; --strict is the documented opt-in


def test_versions_agree():
    version = G.GUARD_VERSION
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)

    def read(rel):
        return (ROOT / rel).read_text(encoding="utf-8")
    found = {
        "plugin.json": json.loads(read("plugin.json"))["version"],
        ".claude-plugin/plugin.json": json.loads(read(".claude-plugin/plugin.json"))["version"],
        "plugin.yaml": re.search(r"^version: *(\S+) *$", read("plugin.yaml"), re.M).group(1),
        "SKILL.md": re.search(r'^  version: "([^"]+)"$', read("SKILL.md"), re.M).group(1),
        "references/commands.md": re.fullmatch(r"This reference defines the command-layer behavior for `multi-agent-git-orchestrator` v(\S+)\.",
                                               read("references/commands.md").splitlines()[2]).group(1),
    }
    entry = re.search(r'^  version: "([^"]+)"$', read("skills/git-orchestrator/SKILL.md"), re.M)
    if entry:  # the entry skill states a version
        found["skills/git-orchestrator/SKILL.md"] = entry.group(1)
    assert found == {rel: version for rel in found}
    assert re.search(r'^GUARD_VERSION = "%s"' % re.escape(version), read("scripts/magos_guard.py"), re.M)  # the file the copies carry


def test_changelog_has_a_heading_for_the_current_version():
    version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
    headings = re.findall(r"^## (\S+)[ \t]*$", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8-sig"), re.M)
    assert version in headings, (version, headings)
    assert headings[0] == version  # the newest entry comes first


def contract_module(name):
    """A module of the package contract suite (tests/codex/contracts), which owns the frontmatter reader and the allow-list."""
    contracts = str(ROOT / "tests" / "codex" / "contracts")
    if contracts not in sys.path:
        sys.path.insert(0, contracts)
    return __import__(name)


def test_the_listing_icon_meets_the_directory_rules():
    """The plugin directory takes a square PNG or JPEG of 512 to 2048 pixels, under 2 MB (not SVG, not WebP); it sits beside the manifest."""
    path = ROOT / ".claude-plugin" / "icon.png"
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height and 512 <= width <= 2048, (width, height)
    assert len(data) < 2_000_000, len(data)
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "icon" not in plugin  # found by its place, so the manifest keeps only metadata keys


def test_the_command_adapters_are_hidden_from_claude_code():
    """Claude Code gets its eight commands from commands/: each skills/ adapter (for Codex and Hermes) is out of its / menu and not offered to the model."""
    frontmatter, plugin = contract_module("skill_frontmatter"), contract_module("agent_plugin")
    writes = {"git-integrate", "git-cleanup", "git-converge", "git-sweep", "git-plan"}
    adapters = writes | {"git-recon", "git-analyze", "git-recommend"}
    assert plugin.ENTRY_SKILL == "git-orchestrator"
    assert plugin.ALLOWED_FIELDS - {"name", "description", "license", "allowed-tools", "metadata", "compatibility"} == {"disable-model-invocation", "user-invocable"}
    seen = set()
    for skill in sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir()):
        fields, _ = frontmatter.parse((skill / "SKILL.md").read_text(encoding="utf-8"))
        seen.add(skill.name)
        if skill.name in adapters:
            assert fields.get("disable-model-invocation") is True and fields.get("user-invocable") is False, skill.name
        else:  # the entry skill: loaded by the model, out of the / menu
            assert "disable-model-invocation" not in fields and fields.get("user-invocable") is False, skill.name
    assert adapters | {"git-orchestrator"} == seen
    root_fields = frontmatter.parse((ROOT / "SKILL.md").read_text(encoding="utf-8"))[0]
    assert "disable-model-invocation" not in root_fields and "user-invocable" not in root_fields
    assert plugin.check_model_invocation(ROOT) == []
    commands = sorted((ROOT / "commands").glob("*.md"))
    assert len(commands) == 8
    for command in commands:  # the commands are THE set of Claude Code: none is hidden
        assert "\nuser-invocable:" not in command.read_text(encoding="utf-8"), command.name
    for command in ("GitIntegrate", "GitCleanup", "GitConverge", "GitSweep", "GitPlan"):  # the Claude commands of the write adapters say the same
        assert "\ndisable-model-invocation: true\n" in (ROOT / "commands" / (command + ".md")).read_text(encoding="utf-8")


def test_a_visible_adapter_or_a_mis_set_entry_skill_is_reported(tmp_path):
    plugin = contract_module("agent_plugin")
    shutil.copytree(ROOT / "skills", tmp_path / "skills", ignore=shutil.ignore_patterns("agents"))
    shutil.copy(ROOT / "SKILL.md", tmp_path / "SKILL.md")
    assert plugin.check_model_invocation(tmp_path) == []

    def rewrite(rel, old, new):
        p = tmp_path / rel
        text = p.read_text(encoding="utf-8")
        assert old in text.replace("\r\n", "\n")
        p.write_bytes(text.replace("\r\n", "\n").replace(old, new).encode("utf-8"))

    rewrite("skills/git-recon/SKILL.md", "user-invocable: false\n", "")  # an adapter in the / menu
    rewrite("skills/git-analyze/SKILL.md", "disable-model-invocation: true\n", "")  # an adapter offered to the model
    rewrite("skills/git-orchestrator/SKILL.md", "user-invocable: false\n", "")  # the entry skill typed in the / menu next to the commands
    rewrite("skills/git-orchestrator/SKILL.md", "\nlicense:", "\ndisable-model-invocation: true\nlicense:")  # the entry skill kept from the model
    problems = plugin.check_model_invocation(tmp_path)
    assert len(problems) == 4 and any("git-recon" in p and "user-invocable: false" in p for p in problems), problems
    assert any("git-analyze" in p and "disable-model-invocation: true" in p for p in problems), problems
    assert any("git-orchestrator" in p and "must set user-invocable: false" in p for p in problems), problems
    assert any("git-orchestrator" in p and "must not set disable-model-invocation" in p for p in problems), problems


def test_each_host_key_takes_exactly_one_boolean():
    frontmatter = contract_module("skill_frontmatter")

    def parse(extra):
        return frontmatter.parse('---\nname: x\ndescription: "d"\n%s\n---\n' % extra)[0]

    assert parse("user-invocable: false")["user-invocable"] is False
    assert parse("disable-model-invocation: true")["disable-model-invocation"] is True
    for bad in ("user-invocable: true", "user-invocable: no", 'user-invocable: "false"', "disable-model-invocation: false", "disable-model-invocation: yes"):
        with pytest.raises(frontmatter.FrontmatterError):
            parse(bad)


# APIs newer than Python 3.9, the minimum the package supports (TC-179): (callable name, keyword) pairs, attribute names and imports.
NEWER_KEYWORDS = {("write_text", "newline"): "3.10", ("read_text", "newline"): "3.13", ("zip", "strict"): "3.10", ("rmtree", "onexc"): "3.12",
                  ("dataclass", "slots"): "3.10", ("dataclass", "kw_only"): "3.10", ("TemporaryDirectory", "ignore_cleanup_errors"): "3.10"}
NEWER_ATTRIBUTES = {"bit_count": "3.10", "pairwise": "3.10", "batched": "3.12", "hardlink_to": "3.10", "isjunction": "3.12", "is_junction": "3.12"}
NEWER_IMPORTS = {("itertools", "pairwise"): "3.10", ("itertools", "batched"): "3.12", ("contextlib", "chdir"): "3.11",
                 ("contextlib", "aclosing"): "3.10", ("typing", "TypeAlias"): "3.10", ("typing", "ParamSpec"): "3.10", ("typing", "Self"): "3.11",
                 ("tomllib", None): "3.11"}


def _guarded_by_version(tree):
    """The nodes inside the body of `if sys.version_info >= (..)` or `> (..)`: code an older interpreter never runs."""
    inside = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.ops[0], (ast.GtE, ast.Gt))
                and "version_info" in ast.dump(node.test.left)):
            inside.update(id(sub) for stmt in node.body for sub in ast.walk(stmt))
    return inside


def newer_api_uses(tree):
    """['line N: <what> (Python X.Y)'] for every use of an API from NEWER_* outside a version guard."""
    guarded, found = _guarded_by_version(tree), []
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            found += ["line %d: %s(%s=) (Python %s)" % (node.lineno, name, kw.arg, NEWER_KEYWORDS[(name, kw.arg)])
                      for kw in node.keywords if (name, kw.arg) in NEWER_KEYWORDS]
        elif isinstance(node, ast.Attribute) and node.attr in NEWER_ATTRIBUTES:
            found.append("line %d: .%s (Python %s)" % (node.lineno, node.attr, NEWER_ATTRIBUTES[node.attr]))
        elif isinstance(node, ast.ImportFrom):
            found += ["line %d: from %s import %s (Python %s)" % (node.lineno, node.module, a.name, NEWER_IMPORTS[(node.module, a.name)])
                      for a in node.names if (node.module, a.name) in NEWER_IMPORTS]
        elif isinstance(node, ast.Import):
            found += ["line %d: import %s (Python %s)" % (node.lineno, a.name, NEWER_IMPORTS[(a.name, None)])
                      for a in node.names if (a.name, None) in NEWER_IMPORTS]
    return found


def _annotated(tree):
    return any(isinstance(n, ast.AnnAssign) or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
        n.returns or any(a.annotation for a in n.args.posonlyargs + n.args.args + n.args.kwonlyargs))) for n in ast.walk(tree))


def test_sources_parse_as_python_3_9_and_tests_use_no_newer_api():
    probe = ast.parse("from pathlib import Path\nPath('x').write_text('y', encoding='utf-8', newline='\\n')\nzip(a, b, strict=True)\n"
                      "import itertools\nitertools.pairwise(a)\n(5).bit_count()\nif sys.version_info >= (3, 12):\n    shutil.rmtree(p, onexc=f)\n")
    assert [use.split(":")[0] for use in newer_api_uses(probe)] == ["line 2", "line 3", "line 5", "line 6"]  # the checks are live
    with pytest.raises(SyntaxError):  # and so is the grammar of 3.9
        ast.parse("match x:\n    case 1:\n        pass\n", feature_version=(3, 9))
    sources = [p for p in shipped_files() if p.suffix == ".py"]
    assert ROOT / "scripts" / "magos_guard.py" in sources and ROOT / "tests" / "codex" / "contracts" / "test_agent_plugin.py" in sources
    problems = []
    for path in sources:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(text, rel, feature_version=(3, 9))
        except SyntaxError as err:
            problems.append("%s: not Python 3.9: %s" % (rel, err))
            continue
        problems += ["%s %s" % (rel, use) for use in newer_api_uses(tree)]
        future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names) for n in tree.body)
        if _annotated(tree) and not future:  # annotations are evaluated at definition time on 3.9: `X | None` would raise there
            problems.append("%s: annotated without `from __future__ import annotations`" % rel)
    assert problems == []


def _coverage_gate():
    spec = __import__("importlib.util").util.spec_from_file_location("coverage_gate", ROOT / "tests" / "codex" / "coverage_gate.py")
    mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lcov(*records):
    """An LCOV report: (path, covered lines, lines) per record."""
    out = []
    for path, hit, total in records:
        out += ["TN:", "SF:%s" % path] + ["DA:%d,%d" % (n, 1 if n <= hit else 0) for n in range(1, total + 1)] + ["LF:%d" % total, "LH:%d" % hit, "end_of_record"]
    return "\n".join(out) + "\n"


def test_ci_coverage_job_runs_the_qguard_commands(tmp_path):
    yaml = pytest.importorskip("yaml")
    text = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    assert flow["permissions"] == {"contents": "read"} and "pull_request_target" not in text
    for needle in ("secrets.", "github.token", "GITHUB_TOKEN"):
        assert needle not in text, needle
    for name, job in flow["jobs"].items():
        assert set(job.get("permissions", {}).values()) <= {"read", "none"}, name  # every job is read-only
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), (name, step)
                if step["uses"].startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False, name
    jobs = [job for job in flow["jobs"].values() if any("coverage_gate.py" in step.get("run", "") for step in job["steps"])]
    assert len(jobs) == 1 and jobs[0]["runs-on"] == "windows-latest", jobs
    steps = jobs[0]["steps"]
    assert [s["with"]["python-version"] for s in steps if s.get("uses", "").startswith("actions/setup-python@")] == ["3.14"]
    runs = [s.get("run", "").strip() for s in steps]
    assert ("python -m pip install --require-hashes --only-binary :all: -r .github/requirements/tests-py314.txt -r .github/requirements/coverage.txt"
            in runs), runs
    assert [r for r in runs if "coverage_gate.py" in r] == ["python -X utf8 tests/codex/coverage_gate.py"]

    # The gate runs exactly the coverage commands of .quality/qguard.json and gates every tracked source file.
    gate = _coverage_gate()
    qguard = json.loads((ROOT / ".quality" / "qguard.json").read_text(encoding="utf-8"))
    assert gate.coverage_commands(gate.load_config()) == qguard["coverage_commands"]
    assert gate.limit_of(qguard) == qguard["min_coverage_exclusive"] == 90
    sources = gate.tracked_sources(qguard)
    assert {"scripts/magos_guard.py", "scripts/sync_hosts.py", "__init__.py"} <= set(sources)
    assert not [s for s in sources if s.startswith(("tests/", ".quality/", ".github/"))], sources
    assert gate.is_source("scripts/x.py", {}) and not gate.is_source("scripts/test_x.py", {}) and not gate.is_source("README.md", {})
    assert not gate.is_source("scripts/x.py", {"excluded_sources": ["scripts/*"]})

    # Strictly above the limit, per file and for the project; a source missing from the report fails; records of one file merge.
    def failures(report, files=("pkg/a.py", "b.py")):
        return gate.gate(report, list(files), 90, root=tmp_path)[1]
    a = os.path.join("pkg", "a.py")  # coverage writes the separator of the platform
    assert failures(_lcov((a, 901, 1000), ("b.py", 10, 10))) == []
    bad = failures(_lcov((a, 9, 10), ("b.py", 10, 10)))
    assert len(bad) == 1 and bad[0].startswith("pkg/a.py: line coverage 9/10 = 90.00%"), bad  # 90.00 percent is not above 90
    bad = failures(_lcov((a, 10, 10)))
    assert len(bad) == 1 and bad[0].startswith("b.py: not in the coverage report"), bad
    assert failures(_lcov((str(tmp_path / "pkg" / "a.py"), 5, 10), (a, 10, 10), ("b.py", 10, 10))) == []  # both spellings of a file merge
    assert failures(_lcov(("b.py", 0, 0), (a, 10, 10)))[0].startswith("b.py: line coverage 0/0")
    assert failures("", ())[0].startswith("project: line coverage 0/0")
    rows, _ = gate.gate(_lcov((a, 91, 100), ("b.py", 95, 100)), ["pkg/a.py", "b.py"], 90, root=tmp_path)
    assert rows == [("pkg/a.py", 91, 100), ("b.py", 95, 100)]
    with pytest.raises(ValueError):
        gate.limit_of({"min_coverage_exclusive": 80})
    with pytest.raises(ValueError):
        gate.coverage_commands({"coverage_commands": ["python -m coverage run"]})  # a shell string is no argv list

    # The commands run in order in the given root, and the first one that fails stops the run.
    log = tmp_path / "order.txt"
    step = "import sys; open(sys.argv[1], 'a').write(sys.argv[2]); sys.exit(int(sys.argv[3]))"
    cfg = {"coverage_commands": [[sys.executable, "-c", step, str(log), "1", "0"], [sys.executable, "-c", step, str(log), "2", "3"],
                                 [sys.executable, "-c", step, str(log), "3", "0"]], "test_timeout_seconds": 60}
    failed = gate.run_commands(cfg, root=tmp_path)
    assert failed and failed.endswith("exit code 3") and log.read_text(encoding="utf-8") == "12", failed


def test_codeql_analyses_python_and_the_workflows_with_minimal_permissions():
    yaml = pytest.importorskip("yaml")
    text = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")
    flow = yaml.safe_load(text)
    assert flow["permissions"] == {} and "secrets." not in text and "pull_request_target" not in text
    (job,) = flow["jobs"].values()
    assert job["permissions"] == {"contents": "read", "security-events": "write"}
    assert sorted(row["language"] for row in job["strategy"]["matrix"]["include"]) == ["actions", "python"]
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), step
    updates = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))["updates"]
    assert [(u["package-ecosystem"], u["directory"]) for u in updates] == [("github-actions", "/"), ("pip", "/.github/requirements")]  # the pins get update requests


def _section(text, heading):
    """The `## <heading>` section of a Markdown text, up to the next `## ` heading."""
    start = text.index("\n## %s" % heading)
    end = text.find("\n## ", start + 4)
    return text[start:] if end < 0 else text[start:end]


def test_docs_state_that_the_console_gate_is_not_access_control():
    limits = _section((ROOT / "references" / "lane-split.md").read_text(encoding="utf-8"), "12. Honest Limits")
    for needle in ("`start`", "`Start-Process`", "console gate", "neither the console gate nor an override is access control"):
        assert needle in limits, needle
    install = (ROOT / "references" / "installation.md").read_text(encoding="utf-8")
    for needle in ("`start`", "`Start-Process`", "真实控制台", "控制台检查与覆盖都不是访问控制"):
        assert needle in install, needle
