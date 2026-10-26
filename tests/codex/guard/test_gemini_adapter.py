"""scripts/validate_gemini_adapter.py (TC-001 to TC-008 of .quality/test-design/scripts/validate_gemini_adapter.py.test.md): the offline check of the Gemini CLI
adapter. Every case but the first works on a temporary copy of the files the validator reads and changes one fact at a time; the content of the TOML files
is read on Python 3.11 and later, and the fallback below that is tested everywhere by setting `tomllib` to None on the loaded module."""
from __future__ import annotations

import importlib.util
import json
import re
import runpy
import shutil
import sys

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "validate_gemini_adapter.py"
NAMES = ("GitRecon", "GitAnalyze", "GitRecommend", "GitIntegrate", "GitCleanup", "GitConverge", "GitSweep", "GitPlan")
FILES = ("gemini-extension.json", "GEMINI.md", "SKILL.md", "plugin.json", "references/commands.md", "skills/git-orchestrator/SKILL.md",
         "policies/magos-git-confirm.toml")
needs_toml = pytest.mark.skipif(sys.version_info < (3, 11), reason="the TOML content is read on Python 3.11 and later")


@pytest.fixture()
def adapter():
    spec = importlib.util.spec_from_file_location("validate_gemini_adapter_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def tree(tmp_path):
    """A copy of the adapter files and of the source files the validator reads."""
    for rel in FILES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    (tmp_path / "commands").mkdir()
    for name in NAMES:
        for suffix in (".toml", ".md"):
            shutil.copyfile(ROOT / "commands" / (name + suffix), tmp_path / "commands" / (name + suffix))
    return tmp_path


def edit_json(path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def edit_text(path, change):
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")


def test_the_repository_passes(adapter, capsys):
    assert adapter.validate(ROOT) is None
    assert adapter.validate(ROOT, overlay_only=True) is None
    assert capsys.readouterr().out.count("PASS:") == 2


def test_manifest_and_context_failures(adapter, tree):
    manifest = tree / "gemini-extension.json"
    original = manifest.read_text(encoding="utf-8")
    edit_json(manifest, lambda data: data.update(name="other"))
    with pytest.raises(AssertionError, match="name must match MAGOS"):
        adapter.validate(tree)
    manifest.write_text(original, encoding="utf-8")
    edit_json(manifest, lambda data: data.update(contextFileName="OTHER.md"))
    with pytest.raises(AssertionError):
        adapter.validate(tree)
    manifest.write_text(original, encoding="utf-8")
    edit_json(manifest, lambda data: data.pop("name"))
    with pytest.raises(KeyError):
        adapter.validate(tree)
    manifest.write_text(original, encoding="utf-8")
    context = (tree / "GEMINI.md").read_bytes()
    (tree / "GEMINI.md").unlink()
    with pytest.raises(AssertionError):
        adapter.validate(tree)
    (tree / "GEMINI.md").write_bytes(context)
    manifest.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        adapter.validate(tree)


@needs_toml
def test_policy_failures(adapter, tree):
    policy = tree / "policies" / "magos-git-confirm.toml"
    original = policy.read_text(encoding="utf-8")
    policy.write_text(original.replace('decision = "ask_user"', 'decision = "allow"'), encoding="utf-8")
    with pytest.raises(AssertionError):
        adapter.validate(tree)
    policy.write_text("rule = []\n", encoding="utf-8")
    with pytest.raises(AssertionError):
        adapter.validate(tree)
    policy.unlink()
    with pytest.raises(OSError):
        adapter.validate(tree)


@needs_toml
@pytest.mark.parametrize("token, message", [("{{args}}", "missing Gemini args placeholder: GitSweep"), ("--help", None), ("activate_skill", None),
                                              ("--lang", None), ("SKILL.md", None), ("references/commands.md", None), ("GitSweep", "GitSweep")])
def test_command_prompt_failures(adapter, tree, token, message):
    edit_text(tree / "commands" / "GitSweep.toml", lambda text: text.replace(token, "x" if token == "GitSweep" else ""))
    with pytest.raises(AssertionError, match=message):
        adapter.validate(tree)


@needs_toml
def test_a_command_without_a_description_or_with_invalid_toml(adapter, tree):
    command = tree / "commands" / "GitSweep.toml"
    original = command.read_text(encoding="utf-8")
    command.write_text(re.sub(r"(?m)^description\s*=.*\n", "", original), encoding="utf-8")
    with pytest.raises(AssertionError):
        adapter.validate(tree)
    command.write_text("not = = toml\n", encoding="utf-8")
    with pytest.raises(ValueError):
        adapter.validate(tree)


def test_missing_command_files_and_overlay_only(adapter, tree):
    (tree / "commands" / "GitSweep.toml").unlink()
    with pytest.raises(AssertionError, match=r"GitSweep\.toml"):
        adapter.validate(tree)
    shutil.copyfile(ROOT / "commands" / "GitSweep.toml", tree / "commands" / "GitSweep.toml")
    (tree / "commands" / "GitSweep.md").unlink()
    with pytest.raises(AssertionError, match="missing original Claude command GitSweep"):
        adapter.validate(tree)
    assert adapter.validate(tree, overlay_only=True) is None


def test_source_dependencies_and_the_version(adapter, tree):
    for rel in ("SKILL.md", "references/commands.md", "skills/git-orchestrator/SKILL.md"):
        saved = (tree / rel).read_bytes()
        (tree / rel).unlink()
        with pytest.raises(AssertionError, match="merged with MAGOS repo"):
            adapter.validate(tree)
        assert adapter.validate(tree, overlay_only=True) is None
        (tree / rel).write_bytes(saved)
    plugin = tree / "plugin.json"
    original = plugin.read_text(encoding="utf-8")
    edit_json(plugin, lambda data: data.update(name="other"))
    with pytest.raises(AssertionError):
        adapter.validate(tree)
    plugin.write_text(original, encoding="utf-8")
    edit_json(plugin, lambda data: data.update(version="0.0.1"))
    with pytest.raises(AssertionError, match="version must match plugin.json"):
        adapter.validate(tree)
    assert adapter.validate(tree, overlay_only=True) is None


def test_without_a_toml_reader(adapter, tree, monkeypatch, capsys):
    monkeypatch.setattr(adapter, "tomllib", None)
    assert adapter.validate(ROOT) is None
    assert "TOML content not checked" in capsys.readouterr().out
    sweep = tree / "commands" / "GitSweep.toml"
    original = sweep.read_bytes()
    sweep.write_text("not toml at all\n", encoding="utf-8")  # read, not parsed
    assert adapter.validate(tree) is None
    sweep.unlink()
    with pytest.raises(AssertionError, match=r"GitSweep\.toml"):
        adapter.validate(tree)
    sweep.write_bytes(original)
    (tree / "policies" / "magos-git-confirm.toml").unlink()
    with pytest.raises(OSError):
        adapter.validate(tree)


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["validate_gemini_adapter.py", *argv])
    try:
        runpy.run_path(str(SCRIPT), run_name="__main__")
        code = 0
    except SystemExit as stop:
        code = stop.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_main_exit_codes(tree, monkeypatch, capsys):
    code, out, err = run_main(monkeypatch, capsys)  # no --repo: the repository the script sits in
    assert code == 0 and "PASS:" in out and not err
    code, out, err = run_main(monkeypatch, capsys, "--repo", str(tree))
    assert code == 0 and "PASS:" in out and not err
    (tree / "commands" / "GitSweep.md").unlink()
    code, out, err = run_main(monkeypatch, capsys, "--repo", str(tree))
    assert code == 1 and not out and err.startswith("FAIL: missing original Claude command GitSweep")
    code, out, err = run_main(monkeypatch, capsys, "--repo", str(tree), "--overlay-only")
    assert code == 0 and "PASS:" in out
    manifest = tree / "gemini-extension.json"
    edit_json(manifest, lambda data: data.update(name="other"))
    code, out, err = run_main(monkeypatch, capsys, "--repo", str(tree))
    assert code == 1 and err.startswith("FAIL: ")
    manifest.write_text("{not json", encoding="utf-8")
    code, out, err = run_main(monkeypatch, capsys, "--repo", str(tree))
    assert code == 1 and err.startswith("FAIL: ")
    manifest.unlink()
    code, out, err = run_main(monkeypatch, capsys, "--repo", str(tree))
    assert code == 1 and err.startswith("FAIL: ")
