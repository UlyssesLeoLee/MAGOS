#!/usr/bin/env python3
"""Offline syntax/source-consistency check for MAGOS Gemini adapter. Stdlib only."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.9 and 3.10 have no TOML reader: the TOML files are read, but their content is not checked
    tomllib = None

COMMANDS = ("GitRecon", "GitAnalyze", "GitRecommend", "GitIntegrate",
            "GitCleanup", "GitConverge", "GitSweep", "GitPlan")

def read_toml(path: Path):
    """The parsed TOML file, or None when this Python has no TOML reader (a missing file is an error either way)."""
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text) if tomllib else None

def validate(base: Path, overlay_only: bool = False) -> None:
    manifest = json.loads((base / "gemini-extension.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "magos", "Gemini extension name must match MAGOS"
    assert manifest["contextFileName"] == "GEMINI.md"
    assert (base / "GEMINI.md").is_file()
    policy = read_toml(base / "policies/magos-git-confirm.toml")
    if policy is not None:
        assert policy["rule"] and all(r["decision"] == "ask_user" for r in policy["rule"])
    names = set()
    for name in COMMANDS:
        path = base / "commands" / (name + ".toml")
        assert path.is_file(), str(path)
        definition = read_toml(path)
        if definition is not None:
            text = definition["prompt"]
            assert definition.get("description")
            assert "{{args}}" in text, f"missing Gemini args placeholder: {name}"
            assert "--help" in text and "activate_skill" in text
            assert "--lang" in text
            assert "SKILL.md" in text and "references/commands.md" in text
            assert name in text, name
        names.add(name)
        if not overlay_only:
            assert (base / "commands" / (name + ".md")).is_file(), "missing original Claude command " + name
    assert len(names) == 8
    if not overlay_only:
        assert (base / "SKILL.md").is_file(), "must be merged with MAGOS repo"
        assert (base / "references/commands.md").is_file(), "must be merged with MAGOS repo"
        assert (base / "skills/git-orchestrator/SKILL.md").is_file(), "must be merged with MAGOS repo"
        source = json.loads((base / "plugin.json").read_text(encoding="utf-8"))
        assert source.get("name") == "magos"
        assert source.get("version") == manifest["version"], "Gemini version must match plugin.json"
    print("PASS: Gemini manifest, policy, 8 TOML custom commands and source dependencies"
          + ("" if tomllib else " (TOML content not checked: it is read on Python 3.11 and later)"))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--overlay-only", action="store_true")
    args=p.parse_args()
    try:
        validate(args.repo.resolve(), args.overlay_only)
    except (AssertionError, KeyError, ValueError, OSError) as e:
        print("FAIL:",str(e),file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
