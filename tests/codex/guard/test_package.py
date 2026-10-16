"""Shipped files around the guard: hook wiring, endings, contract anchors, and the package rules the guard must not break."""
from __future__ import annotations

import ast
import io
import json
import re
import shlex
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
    for name in ("Bash", "PowerShell", "Monitor", "Agent", "mcp__terminal__run_in_terminal", "mcp__ccd_session__start_session"):
        assert re.search(soft, name), name
    for name in ("mcp__scheduled-tasks__run_scheduled_task", "Read", "BashOutput", "TaskList", "EnterWorktree", "XBash"):
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


def test_write_adapters_disable_model_invocation():
    frontmatter, plugin = contract_module("skill_frontmatter"), contract_module("agent_plugin")
    writes = {"git-integrate", "git-cleanup", "git-converge", "git-sweep"}
    assert set(plugin.WRITE_ADAPTERS) == writes
    assert plugin.ALLOWED_FIELDS - {"name", "description", "license", "allowed-tools", "metadata", "compatibility"} == {"disable-model-invocation"}
    seen = set()
    for skill in sorted(p for p in (ROOT / "skills").iterdir() if p.is_dir()):
        fields, _ = frontmatter.parse((skill / "SKILL.md").read_text(encoding="utf-8"))
        seen.add(skill.name)
        if skill.name in writes:
            assert fields.get("disable-model-invocation") is True, skill.name
        else:
            assert "disable-model-invocation" not in fields, skill.name
    assert writes | {"git-recon", "git-analyze", "git-recommend", "git-orchestrator"} == seen
    assert "disable-model-invocation" not in frontmatter.parse((ROOT / "SKILL.md").read_text(encoding="utf-8"))[0]
    assert plugin.check_model_invocation(ROOT) == []
    for command in ("GitIntegrate", "GitCleanup", "GitConverge", "GitSweep"):  # the Claude commands of the same name say the same
        assert "\ndisable-model-invocation: true\n" in (ROOT / "commands" / (command + ".md")).read_text(encoding="utf-8")
