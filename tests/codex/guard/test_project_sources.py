"""In-process tests of the other tracked sources (`__init__.py`, `scripts/sync_hosts.py`) so the project coverage gate measures them."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import ROOT


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- __init__.py -----------------------------------------------------------------------------------------------------
class RecordingContext:
    """The part of the Hermes context that register() uses; fail_on makes the nth register_skill call raise instead of record."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.hooks = []
        self.fail_on = fail_on

    def register_skill(self, name, path, description=""):
        if self.fail_on is not None and len(self.calls) + 1 == self.fail_on:
            raise RuntimeError("register_skill failed on %s" % name)
        self.calls.append((name, Path(path).name, description))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


COMMAND_SKILLS = ["git-recon", "git-analyze", "git-recommend", "git-integrate", "git-cleanup", "git-converge", "git-sweep", "git-plan"]
WRITE_COMMANDS = ["git-integrate", "git-cleanup", "git-converge", "git-sweep", "git-plan"]


def init_module():
    return load(ROOT / "__init__.py", "magos_plugin_init")


def test_init_registers_every_skill_with_a_description():
    mod = init_module()
    ctx = RecordingContext()
    mod.register(ctx)
    names = [c[0] for c in ctx.calls]
    assert names == sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
    assert all(c[1] == "SKILL.md" and c[2] for c in ctx.calls)
    assert set(mod.INDEX_DESCRIPTIONS) == set(names)


def test_init_registers_the_entry_skill_and_the_eight_command_adapters():
    ctx = RecordingContext()
    init_module().register(ctx)
    expected = ["git-analyze", "git-cleanup", "git-converge", "git-integrate", "git-orchestrator", "git-plan", "git-recommend", "git-recon", "git-sweep"]
    assert [c[0] for c in ctx.calls] == expected
    assert sorted(p.name for p in (ROOT / "skills").iterdir()) == expected  # the directory holds no other skill


def test_init_registers_the_two_guard_callbacks():
    class Ordered(RecordingContext):
        def register_hook(self, name, callback):
            self.hooks.append((name, callback, len(self.calls)))  # how many skills were registered before this hook

    mod = init_module()
    ctx = Ordered()
    mod.register(ctx)
    assert [c[0] for c in ctx.calls] == sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
    assert ctx.hooks == [("pre_tool_call", mod.verdict, 9), ("pre_tool_call", mod.approval, 9)]  # after the nine skills


def test_the_index_table_is_a_literal_in_the_contract_order():
    mod = init_module()
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    value = next(node.value for node in tree.body
                 if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "INDEX_DESCRIPTIONS" for target in node.targets))
    table = ast.literal_eval(value)  # a literal: a check can read it without running the module
    assert table == mod.INDEX_DESCRIPTIONS
    assert list(table) == ["git-orchestrator", *COMMAND_SKILLS]
    assert all(isinstance(line, str) and line.strip() and "\n" not in line and "\r" not in line for line in table.values())


def test_every_write_command_index_line_says_never_load_it_yourself():
    table = init_module().INDEX_DESCRIPTIONS
    derived = sorted(p.name for p in (ROOT / "skills").iterdir()
                     if "\n## Explicit invocation only" in (p / "SKILL.md").read_text(encoding="utf-8"))
    assert derived == sorted(WRITE_COMMANDS)  # an adapter that loses the section turns this red
    for name in derived:
        line = table[name]
        assert "run only when the user types /magos:%s." % name in line and line.endswith("Never load it yourself."), name
    for name in ("git-recon", "git-analyze", "git-recommend"):
        line = table[name]
        assert line.startswith("Read-only") and "when the user asks" in line and "Never load it yourself" not in line, name


def test_the_git_plan_index_line_names_its_writes():
    line = init_module().INDEX_DESCRIPTIONS["git-plan"]
    assert line == ("Registers lane claims and, with --converge --apply, merges the lanes: run only when the user types /magos:git-plan. "
                    "Never load it yourself.")
    assert len(line) <= 160


def test_index_lines_name_only_their_own_command_and_keep_their_length():
    for name, line in init_module().INDEX_DESCRIPTIONS.items():
        named = re.findall(r"/([\w-]+):([\w-]+)", line)
        if name == "git-orchestrator":
            assert 100 <= len(line) <= 400
            assert all(pair == ("magos", name) for pair in named)
        else:
            assert named and all(pair == ("magos", name) for pair in named), name
            assert len(line) <= 160, name


def test_register_skips_non_skills_and_defaults_the_description(tmp_path, monkeypatch):
    mod = init_module()
    skills = tmp_path / "skills"
    for name in ("a", "z"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text("skill %s\n" % name, encoding="utf-8")
    (skills / "b").mkdir()  # a directory without SKILL.md
    (skills / "c" / "SKILL.md").mkdir(parents=True)  # a SKILL.md that is a directory
    (skills / "notes.txt").write_text("notes\n", encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "__init__.py"))  # register() resolves skills/ from __file__ at call time
    ctx = RecordingContext()
    mod.register(ctx)
    assert ctx.calls == [("a", "SKILL.md", ""), ("z", "SKILL.md", "")]
    assert "a" not in mod.INDEX_DESCRIPTIONS and "z" not in mod.INDEX_DESCRIPTIONS


def test_register_without_a_skills_directory_raises(tmp_path, monkeypatch):
    mod = init_module()
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "__init__.py"))
    ctx = RecordingContext()
    with pytest.raises(FileNotFoundError):
        mod.register(ctx)
    assert ctx.calls == []


def test_register_propagates_a_failing_context(tmp_path, monkeypatch):
    mod = init_module()
    for name in ("a", "z"):
        (tmp_path / "skills" / name).mkdir(parents=True)
        (tmp_path / "skills" / name / "SKILL.md").write_text("skill %s\n" % name, encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "__init__.py"))
    ctx = RecordingContext(fail_on=2)
    with pytest.raises(RuntimeError, match="register_skill failed on z"):
        mod.register(ctx)
    assert ctx.calls == [("a", "SKILL.md", "")]  # nothing after the failing skill, and nothing rolled back


# ---- scripts/sync_hosts.py -------------------------------------------------------------------------------------------
@pytest.fixture
def pkg(tmp_path):
    """A miniature package; main() is pointed at it through __file__ while the real module code runs."""
    repo = tmp_path / "pkg"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "sync_hosts.py", repo / "scripts" / "sync_hosts.py")
    (repo / "SKILL.md").write_text("root\n", encoding="utf-8")
    (repo / "references").mkdir()
    (repo / "references" / "a.md").write_text("a\n", encoding="utf-8")
    (repo / "references" / "b.md").write_text("b\n", encoding="utf-8")
    for name in ("git-recon", "git-orchestrator"):
        d = repo / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("skill %s\n" % name, encoding="utf-8")
    (repo / "skills" / "git-recon" / "agents").mkdir()
    (repo / "skills" / "git-recon" / "agents" / "openai.yaml").write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
    (repo / "commands").mkdir()
    mod = load(ROOT / "scripts" / "sync_hosts.py", "sync_hosts_pkg")  # the real file, so the coverage gate measures it
    mod.FAKE_FILE = str(repo / "scripts" / "sync_hosts.py")
    for rel in mod.COMMAND_PATHS:
        (repo / rel).write_text("command\n", encoding="utf-8")
    return repo, mod


def main_of(mod, monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["sync_hosts.py", *argv])
    monkeypatch.setattr(mod, "__file__", mod.FAKE_FILE)  # main() resolves the repository from __file__
    code = mod.main()
    return code, capsys.readouterr().out


def test_package_files_excludes_the_plugin_only_entry(pkg):
    repo, mod = pkg
    assert mod.package_files(repo) == ("SKILL.md", "references/a.md", "references/b.md", "skills/git-recon/SKILL.md", "skills/git-recon/agents/openai.yaml")
    assert mod.file_sha256(repo / "SKILL.md") == __import__("hashlib").sha256((repo / "SKILL.md").read_bytes()).hexdigest()


def test_eight_commands_and_their_adapters_are_listed():
    mod = load(ROOT / "scripts" / "sync_hosts.py", "sync_hosts_real")
    names = ("GitRecon", "GitAnalyze", "GitRecommend", "GitIntegrate", "GitCleanup", "GitConverge", "GitSweep", "GitPlan")
    assert mod.COMMAND_NAMES == names
    declaration = next(line for line in (ROOT / "scripts" / "sync_hosts.py").read_text(encoding="utf-8").splitlines()
                       if line.startswith("COMMAND_NAMES = "))
    assert declaration.endswith('"GitConverge", "GitSweep", "GitPlan")')  # the tail the Claude source-contract case pins
    assert len(mod.COMMAND_PATHS) == 8 and mod.COMMAND_PATHS[-1] == "commands/GitPlan.md"
    assert all((ROOT / path).is_file() for path in mod.COMMAND_PATHS)
    listed = mod.package_files(ROOT)
    for name in names:
        word = name[len("Git"):].lower()
        for path in ("skills/git-%s/SKILL.md" % word, "skills/git-%s/agents/openai.yaml" % word):
            assert (ROOT / path).is_file() and path in listed, path
    assert not [path for path in listed if path.startswith("skills/git-orchestrator/")]


def test_install_roots(tmp_path, monkeypatch, pkg):
    _, mod = pkg
    home = tmp_path / "h"
    root, notes = mod.codex_install_root(home, True)
    assert root == home / ".agents" / "skills" / "MAGOS" and not notes
    legacy = home / ".codex" / "skills" / "MAGOS"
    legacy.mkdir(parents=True)
    root, notes = mod.codex_install_root(home, True)
    assert root == legacy and "legacy" in notes[0]
    (home / ".agents" / "skills" / "MAGOS").mkdir(parents=True)
    root, notes = mod.codex_install_root(home, True)
    assert root == home / ".agents" / "skills" / "MAGOS" and "duplicate" in notes[0]
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "ch"))
    assert mod.codex_install_root(home, False)[0] == home / ".agents" / "skills" / "MAGOS"
    assert mod.codex_install_root(home, True)[0] == home / ".agents" / "skills" / "MAGOS"

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hh"))
    assert mod.hermes_home(home, False) == tmp_path / "hh"
    monkeypatch.delenv("HERMES_HOME")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    # LOCALAPPDATA names the Hermes home only on Windows; elsewhere it is ~/.hermes.  An explicit home ignores the variable.
    for platform, expected, explicit in (("win32", tmp_path / "lad" / "hermes", home / "AppData" / "Local" / "hermes"),
                                         ("linux", home / ".hermes", home / ".hermes")):
        monkeypatch.setattr(mod, "sys", SimpleNamespace(platform=platform))
        assert mod.hermes_home(home, False) == expected and mod.hermes_home(home, True) == explicit, platform
    monkeypatch.setattr(mod, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", "  ")  # empty on Windows: the home's own AppData\Local
    assert mod.hermes_home(home, False) == home / "AppData" / "Local" / "hermes"
    monkeypatch.setattr(mod, "sys", sys)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    base = mod.hermes_home(home, False)
    assert base == (tmp_path / "lad" / "hermes" if sys.platform == "win32" else home / ".hermes")
    (base / "profiles" / "work").mkdir(parents=True)
    (base / "active_profile").write_text("work\n", encoding="utf-8")
    assert mod.hermes_home(home, False) == base / "profiles" / "work"
    (base / "active_profile").write_text("default\n", encoding="utf-8")
    assert mod.hermes_home(home, False) == base
    assert mod.hermes_home(home, True) == (home / "AppData" / "Local" / "hermes" if sys.platform == "win32" else home / ".hermes")

    skills = base / "skills"
    (skills / "multi-agent-git-orchestrator").mkdir(parents=True)
    assert mod.hermes_install_root(home, False)[0] == skills / "multi-agent-git-orchestrator"
    (skills / "MAGOS").mkdir()
    root, notes = mod.hermes_install_root(home, False)
    assert "Keep one install" in notes[0]
    (skills / "multi-agent-git-orchestrator").rmdir()
    root, notes = mod.hermes_install_root(home, False)
    assert root == skills / "MAGOS" and "existing Hermes install" in notes[0]


def test_claude_plugin_notes(tmp_path, pkg):
    _, mod = pkg
    claude = tmp_path / ".claude"
    (claude / "skills" / "magos" / ".claude-plugin").mkdir(parents=True)
    (claude / "skills" / "magos" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "magos"}), encoding="utf-8")
    (claude / "skills" / "other" / ".claude-plugin").mkdir(parents=True)
    (claude / "skills" / "other" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "other"}), encoding="utf-8")
    (claude / "skills" / "bad" / ".claude-plugin").mkdir(parents=True)
    (claude / "skills" / "bad" / ".claude-plugin" / "plugin.json").write_text("{not json", encoding="utf-8")
    notes = mod.claude_plugin_notes(claude)
    assert len(notes) == 1 and "/magos:GitXxx" in notes[0]


def test_plan_verify_apply_cycle(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    home.mkdir()
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--host", "hermes")
    assert code == 2 and "Preflight failed" in out and "missing-root" in out
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--host", "hermes", "--apply", "--create-roots")
    assert code == 0 and "Created roots" in out and "Written: 10" in out
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--host", "hermes", "--verify")
    assert code == 0 and "matched" in out
    target = home / ".agents" / "skills" / "MAGOS" / "SKILL.md"
    target.write_text("drifted\n", encoding="utf-8")
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--verify", "--json")
    report = json.loads(out)
    assert code == 1 and report["summary"]["different"] == 1 and report["mode"] == "verify"
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--apply")
    assert code == 0 and target.read_text(encoding="utf-8") == "root\n"
    (repo / "references" / "a.md").unlink()
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex")
    assert code == 0  # a file that disappeared from the source is simply no longer in the package list


def test_claude_host_and_plugin_skip(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    (home / ".claude" / "commands").mkdir(parents=True)
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "claude", "--apply")
    assert code == 0 and "Written: 8" in out and (home / ".claude" / "commands" / "GitRecon.md").is_file()
    (home / ".claude" / "skills" / "magos" / ".claude-plugin").mkdir(parents=True)
    (home / ".claude" / "skills" / "magos" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "magos"}), encoding="utf-8")
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--hermes-root", str(tmp_path / "hr"), "--codex-root", str(tmp_path / "cr"))
    assert "Skipping the claude host" in out and code == 2


def test_a_home_without_the_eighth_command_reports_it_missing_and_apply_adds_it(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    commands = home / ".claude" / "commands"
    commands.mkdir(parents=True)
    claude = ("--home", str(home), "--host", "claude")
    code, out = main_of(mod, monkeypatch, capsys, *claude, "--apply")
    assert code == 0 and "Written: 8" in out
    (commands / "GitPlan.md").unlink()  # the home of an install that predates the eighth command
    code, out = main_of(mod, monkeypatch, capsys, *claude, "--verify", "--json")
    report = json.loads(out)
    assert code == 1 and report["summary"]["missing"] == 1 and report["summary"]["matched"] == 7
    assert [item["relative_path"] for item in report["files"] if item["status"] == "missing"] == ["commands/GitPlan.md"]
    code, out = main_of(mod, monkeypatch, capsys, *claude, "--apply")
    assert code == 0 and "Written: 1" in out and (commands / "GitPlan.md").is_file()  # only the missing file is copied
    code, out = main_of(mod, monkeypatch, capsys, *claude, "--verify", "--json")
    assert code == 0 and {item["status"] for item in json.loads(out)["files"]} == {"matched"}


def test_git_checkout_roots_and_blocked_destinations(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    root = home / ".agents" / "skills" / "MAGOS"
    (root / ".git").mkdir(parents=True)
    (root / ".claude-plugin").mkdir()
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex")
    assert code == 2 and "git-checkout" in out and "$magos:git-*" in out
    shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "SKILL.md").mkdir()  # a directory where a file belongs
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex")
    assert code == 2 and "blocked" in out
    shutil.rmtree(root / "SKILL.md")
    (repo / "references" / "b.md").unlink()
    (repo / "references" / "b.md").mkdir()  # the package list now names a source that is not a file
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex")
    assert code == 2 and "SOURCE ERROR" in out and "references/b.md" in out


def test_copy_file_guards(pkg, tmp_path):
    repo, mod = pkg
    root = tmp_path / "root"
    root.mkdir()
    src = repo / "SKILL.md"
    digest = mod.file_sha256(src)
    mod.copy_file(src, root / "sub" / "SKILL.md", root, digest)
    assert (root / "sub" / "SKILL.md").read_text(encoding="utf-8") == "root\n"
    with pytest.raises(RuntimeError, match="changed during sync"):
        mod.copy_file(src, root / "x.md", root, "0" * 64)
    with pytest.raises(RuntimeError, match="unsafe"):
        mod.copy_file(src, tmp_path / "outside.md", root, digest)


def test_apply_stops_on_a_write_error_and_reports_mismatches(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    (home / ".agents" / "skills" / "MAGOS").mkdir(parents=True)
    real = mod.copy_file
    calls = []

    def flaky(source, destination, root, expected):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(source, destination, root, expected)
    monkeypatch.setattr(mod, "copy_file", flaky)
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--apply")
    assert code == 2 and "Sync stopped after a write error" in out
    monkeypatch.setattr(mod, "copy_file", lambda *a: None)  # a copy that silently does nothing leaves files different
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--apply")
    assert code == 2 and "did not match after writing" in out
    monkeypatch.setattr(mod, "copy_file", real)
    shutil.rmtree(repo / "references")
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex", "--verify")
    assert code in (0, 1, 2)


def test_missing_source_is_a_preflight_error(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    (home / ".agents" / "skills" / "MAGOS").mkdir(parents=True)
    monkeypatch.setattr(mod, "package_files", lambda r: ("SKILL.md", "nope.md"))
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "codex")
    assert code == 2 and "SOURCE ERROR" in out and "nope.md" in out


# ---- Claude Code marketplace installs (supply-05) ---------------------------------------------------------------------
def plugin_index(home, plugins):
    """~/.claude/plugins/installed_plugins.json in the version 2 shape, holding the given plugins map."""
    path = home / ".claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8")
    return path


def install_entry(scope):
    return {"scope": scope, "installPath": "/x/.claude/plugins/cache/magos/magos/1.0.2", "version": "1.0.2"}


def cache_manifest(home, name, marketplace="magos", plugin="magos", version="1.0.1"):
    """A plugins-cache manifest, cache/<marketplace>/<plugin>/<version>/.claude-plugin/plugin.json, named name."""
    path = home / ".claude" / "plugins" / "cache" / marketplace / plugin / version / ".claude-plugin" / "plugin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")
    return path


def roots(tmp_path):
    """Existing Codex and Hermes roots, passed explicitly so a default run selects hosts without root notes."""
    codex, hermes = tmp_path / "cr", tmp_path / "hr"
    codex.mkdir(exist_ok=True)
    hermes.mkdir(exist_ok=True)
    return "--codex-root", str(codex), "--hermes-root", str(hermes)


def test_marketplace_user_scope_install_skips_claude(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    plugin_index(home, {"magos@magos": [install_entry("user")]})
    notes = mod.claude_plugin_notes(home / ".claude")
    assert len(notes) == 1 and "magos@magos" in notes[0] and "/magos:GitXxx" in notes[0] and "plugin manager" in notes[0]
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), *roots(tmp_path), "--json")
    report = json.loads(out)
    assert code == 0 and report["selected_hosts"] == ["codex", "hermes"] and {f["host"] for f in report["files"]} == {"codex", "hermes"}
    assert report["notes"][0] == notes[0] and report["notes"][1].startswith("Skipping the claude host")
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), *roots(tmp_path))
    assert code == 0 and "Skipping the claude host" in out and "magos@magos" in out
    # a list that mixes scopes counts, a key without @ is all plugin part, and every detected install gets its own note
    plugin_index(home, {"magos@a": [install_entry("project"), install_entry("user")], "magos": [install_entry("user")]})
    notes = mod.claude_plugin_notes(home / ".claude")
    assert len(notes) == 2 and notes[0].startswith("Marketplace plugin magos (") and notes[1].startswith("Marketplace plugin magos@a (")


def test_marketplace_project_scope_only_keeps_the_claude_commands(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    plugin_index(home, {"magos@magos": [install_entry("project"), install_entry("local")]})
    assert mod.claude_plugin_notes(home / ".claude") == []
    (home / ".claude" / "commands").mkdir(parents=True)
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), *roots(tmp_path), "--json")
    report = json.loads(out)
    assert code == 0 and report["selected_hosts"] == ["claude", "codex", "hermes"] and report["notes"] == []
    assert sorted(f["relative_path"] for f in report["files"] if f["host"] == "claude") == sorted(mod.COMMAND_PATHS)


def test_a_magos_plugin_from_any_marketplace_counts(pkg, tmp_path):
    _, mod = pkg
    home = tmp_path / "home"
    plugin_index(home, {"magos@my-fork": [install_entry("user")], "magosx@magos": [install_entry("user")],
                        "other@magos": [install_entry("user")]})
    notes = mod.claude_plugin_notes(home / ".claude")
    assert len(notes) == 1 and "magos@my-fork" in notes[0] and "magosx" not in notes[0] and "other@magos" not in notes[0]


def test_a_malformed_plugin_index_is_ignored(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    index = plugin_index(home, {})
    for body in (b"{not json", b"\xff\xfe{}", b"[]", json.dumps([{"magos@magos": [install_entry("user")]}]).encode(),
                 json.dumps({"plugins": [["magos@magos", install_entry("user")]]}).encode(),
                 json.dumps({"plugins": {"magos@magos": install_entry("user")}}).encode(),
                 json.dumps({"plugins": {"magos@magos": ["user", 1, None, [install_entry("user")]]}}).encode(),
                 json.dumps({"plugins": {"magos@magos": [{"scope": ["user"]}, {"scope": "User"}]}}).encode()):
        index.write_bytes(body)
        assert mod.claude_plugin_notes(home / ".claude") == [], body
    assert not (home / ".claude" / "plugins" / "cache").exists()
    (home / ".claude" / "commands").mkdir()
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), *roots(tmp_path), "--json")
    assert code == 0 and json.loads(out)["selected_hosts"] == ["claude", "codex", "hermes"]


def test_the_plugins_cache_counts_only_without_a_plugin_index(pkg, tmp_path):
    _, mod = pkg
    home = tmp_path / "home"
    claude = home / ".claude"
    manifest = cache_manifest(home, "magos")
    notes = mod.claude_plugin_notes(claude)
    assert len(notes) == 1 and str(manifest) in notes[0] and "/magos:GitXxx" in notes[0]
    manifest.write_text(json.dumps({"name": "other"}), encoding="utf-8")
    assert mod.claude_plugin_notes(claude) == []
    manifest.write_text("{unreadable", encoding="utf-8")
    assert mod.claude_plugin_notes(claude) == []
    manifest.write_text(json.dumps({"name": "magos"}), encoding="utf-8")
    index = plugin_index(home, {"other@magos": [install_entry("user")]})
    assert mod.claude_plugin_notes(claude) == []  # the index parses, so it decides
    index.write_text(json.dumps({"version": 2}), encoding="utf-8")  # no plugins key: the cache decides again
    assert len(mod.claude_plugin_notes(claude)) == 1


def test_explicit_claude_host_copies_despite_a_marketplace_install(pkg, tmp_path, monkeypatch, capsys):
    repo, mod = pkg
    home = tmp_path / "home"
    plugin_index(home, {"magos@magos": [install_entry("user")]})
    (home / ".claude" / "commands").mkdir(parents=True)
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--host", "claude", "--apply")
    assert code == 0 and "magos@magos" in out and "/magos:GitXxx" in out and "Written: 8" in out
    assert "Skipping the claude host" not in out
    assert sorted(p.name for p in (home / ".claude" / "commands").iterdir()) == sorted(Path(rel).name for rel in mod.COMMAND_PATHS)
