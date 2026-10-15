"""In-process tests of the other tracked sources (`__init__.py`, `scripts/sync_hosts.py`) so the project coverage gate measures them."""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

from conftest import ROOT


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- __init__.py -----------------------------------------------------------------------------------------------------
def test_init_registers_every_skill_with_a_description():
    mod = load(ROOT / "__init__.py", "magos_plugin_init")

    class Ctx:
        def __init__(self):
            self.calls = []

        def register_skill(self, name, path, description=""):
            self.calls.append((name, Path(path).name, description))
    ctx = Ctx()
    mod.register(ctx)
    names = [c[0] for c in ctx.calls]
    assert names == sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
    assert all(c[1] == "SKILL.md" and c[2] for c in ctx.calls)
    assert set(mod.INDEX_DESCRIPTIONS) == set(names)


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
    base = mod.hermes_home(home, False)
    assert base.name == "hermes"
    (base / "profiles" / "work").mkdir(parents=True)
    (base / "active_profile").write_text("work\n", encoding="utf-8")
    assert mod.hermes_home(home, False) == base / "profiles" / "work"
    (base / "active_profile").write_text("default\n", encoding="utf-8")
    assert mod.hermes_home(home, False) == base
    assert mod.hermes_home(home, True).parts[-3:] == ("AppData", "Local", "hermes") or mod.hermes_home(home, True).name == ".hermes"

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
    assert code == 0 and "Written: 7" in out and (home / ".claude" / "commands" / "GitRecon.md").is_file()
    (home / ".claude" / "skills" / "magos" / ".claude-plugin").mkdir(parents=True)
    (home / ".claude" / "skills" / "magos" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "magos"}), encoding="utf-8")
    code, out = main_of(mod, monkeypatch, capsys, "--home", str(home), "--hermes-root", str(tmp_path / "hr"), "--codex-root", str(tmp_path / "cr"))
    assert "Skipping the claude host" in out and code == 2


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
