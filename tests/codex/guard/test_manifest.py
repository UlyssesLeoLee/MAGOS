"""Pure unit tests: manifest parsing, normalisation, the glob-intersection programme, evaluation, rendering."""
from __future__ import annotations

import itertools
import re
import unicodedata

import pytest

from conftest import G


def entry(raw):
    return G.parse_entry(raw)


# ---- normalisation -------------------------------------------------------------------------------------------------
def test_normalisation():
    canon = entry("src/app").alts[0]
    for raw in ("src/app", "src\\app", "./src//app", "SRC/App", "src/app/", "src/app. "):
        assert entry(raw).alts[0][:2] == canon[:2], raw
    # a literal path (or a trailing slash) also claims everything below it
    assert entry("src/app").alts[0][-1] == "**"
    assert entry("src/app/").alts[0][-1] == "**"
    assert entry("src/*.py").alts[0][-1] == "*.py"
    nfd = unicodedata.normalize("NFD", "café/x.txt")
    assert entry(nfd).alts == entry("café/x.txt").alts
    assert entry("Düsseldorf/a").alts[0][0] == "düsseldorf"


@pytest.mark.parametrize("raw,code", [
    ("", "EMPTY"), ("a\x01b", "EMPTY"), (":(glob)a", "MAGIC"), ("!a", "MAGIC"), ("/etc/x", "ABSOLUTE"), ("C:x", "ABSOLUTE"), ("\\\\srv\\x", "ABSOLUTE"),
    ("a/../b", "DOTDOT"), (".git/config", "GITDIR"), ("GIT~1/x", "GITDIR"), ("a/b**c", "BAD_GLOB"), ("**", "UNIVERSAL"), ("*/*", "UNIVERSAL"), ("?", "UNIVERSAL"),
    ("a/... /b", "BAD_SEGMENT"), ("x" * 1025, "TOO_LONG"),
])
def test_invalid_entries(raw, code):
    with pytest.raises(G.ManifestError) as err:
        entry(raw)
    assert err.value.code == code


def test_manifest_limits_and_comments():
    entries, errors = G.parse_manifest(["# comment", "", "src/a.py", "SRC/A.PY", " docs/ "])
    assert [e.raw for e in entries] == ["src/a.py", "docs/"] and not errors  # duplicates fold away
    assert G.parse_manifest([])[1] == [("EMPTY", "the manifest has no entries")]
    entries, errors = G.parse_manifest(["f%d" % i for i in range(201)])
    assert len(entries) == 200 and errors[0][0] == "TOO_MANY"
    entries, errors = G.parse_manifest(["ok.py", "/abs", "..", "a/b**"])
    assert [e.raw for e in entries] == ["ok.py"] and [c for c, _ in errors] == ["ABSOLUTE", "DOTDOT", "BAD_GLOB"]


def test_brackets_are_ordinary_characters():
    e = entry("pages/[id].tsx")
    assert G.path_hit(e, G.fpath("pages/[id].tsx"))
    assert G.path_hit(e, G.fpath("pages/i.tsx"))  # the class reading over-approximates: it can only add conflicts
    assert not G.path_hit(e, G.fpath("pages/ab.tsx"))
    assert len(e.alts) == 2 and len(entry("src/a").alts) == 1


# ---- overlap programme ---------------------------------------------------------------------------------------------
TOKENS = ("a", "ab", "*", "?", "a*", "*b", "**")
ALPHABET = "ab"


def _universe():
    names = ["".join(p) for n in (1, 2) for p in itertools.product(ALPHABET, repeat=n)]
    return [p for depth in (1, 2, 3) for p in itertools.product(names, repeat=depth)]


def _seg_match(pattern, name):
    return re.fullmatch("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern), name) is not None


def _path_match(pattern, path):
    if not pattern:
        return not path
    if pattern[0] == "**":
        return _path_match(pattern[1:], path) or (bool(path) and _path_match(pattern, path[1:]))
    return bool(path) and _seg_match(pattern[0], path[0]) and _path_match(pattern[1:], path[1:])


def test_overlap_matches_oracle():
    paths = _universe()
    patterns = [(t,) for t in TOKENS] + [(x, y) for x in TOKENS for y in TOKENS]
    checked = 0
    for a, b in itertools.product(patterns, repeat=2):
        expected = any(_path_match(a, p) and _path_match(b, p) for p in paths)
        assert G.segs_overlap(a, b) == expected, (a, b)
        checked += 1
    assert checked >= 500


@pytest.mark.parametrize("a,b,expected", [
    ("docs/**", "**/*.md", True), ("src/*.py", "src/a?.py", True), ("a/**/b", "a/x/y/b", True), ("*.lock", "web/package-lock.json", False),
    ("tests/codex/guard/**", "tests/codex/contracts/x.py", False), ("src/a", "src/ab.py", False), ("src/a", "src/a/x.py", True),
    ("src/**", "src", True), ("**/*.rst", "README.md", True),  # a literal entry may be a directory: conservative between entries
])
def test_entry_overlap_examples(a, b, expected):
    assert G.entries_overlap(entry(a), entry(b)) is expected


def test_wildcard_entry_against_concrete_paths():
    assert not G.path_hit(entry("**/*.rst"), G.fpath("README.md"))  # a changed file that is not an .rst file never collides
    assert G.path_hit(entry("**/*.rst"), G.fpath("docs/x.rst"))


def test_file_dir_rule():
    # a changed FILE equal to a proper prefix of the entry's literal part collides (git cannot hold both a file and a directory)
    assert G.path_hit(entry("src/c/x.py"), G.fpath("src/c"))
    assert not G.path_hit(entry("src/*/x.py"), G.fpath("src/c"))  # deliberate false negative, documented in the contract
    assert not G.path_hit(entry("src/a"), G.fpath("src/ab.py"))


def test_case_and_unicode_collisions():
    assert G.path_hit(entry("Docs/Readme.MD"), G.fpath("docs/readme.md"))
    assert G.path_hit(entry("café/a"), G.fpath(unicodedata.normalize("NFD", "café/a")))


# ---- evaluation, fingerprint, rendering ----------------------------------------------------------------------------
def claimant(key, branch, committed=(), uncommitted=(), declared=(), worktrees=(), planned=False):
    return {"key": key, "branch": branch, "worktrees": list(worktrees), "declared": [entry(d) for d in declared],
            "paths": {"committed": set(committed), "uncommitted": set(uncommitted)}, "planned": planned}


def test_evaluate_all_evidence_kinds():
    mine = [entry("src/"), entry("docs/guide.md")]
    cl = [claimant("1", "x", committed=["src/a.py", "other.txt"], uncommitted=["src/b.py"], worktrees=["/wt"]),
          claimant("2", "planned", declared=["docs/"], planned=True), claimant("3", "far", committed=["web/x.js"])]
    out = G.evaluate(mine, cl)
    assert [c["branch"] for c in out] == ["planned", "x"]
    x = next(c for c in out if c["branch"] == "x")
    assert [(e["kind"], e["files"]) for e in x["evidence"]] == [("committed", ["src/a.py"]), ("uncommitted", ["src/b.py"])]
    assert next(c for c in out if c["branch"] == "planned")["evidence"][0] == {"kind": "declared", "files": [], "matched": ["docs/guide.md"], "theirs": ["docs/"]}


def test_fingerprint_is_stable_and_sensitive():
    base = [{"key": "k", "evidence": [{"kind": "committed", "files": ["a", "b"], "theirs": []}]}]
    fp = G.fingerprint("lane", base, ["X"], "sha1")
    assert re.fullmatch("[0-9a-f]{12}", fp)
    assert fp == G.fingerprint("lane", [{"key": "k", "evidence": [{"kind": "committed", "files": ["b", "a"], "theirs": []}]}], ["X"], "sha1")
    assert fp != G.fingerprint("lane", base, ["X"], "sha2") and fp != G.fingerprint("lane", base, [], "sha1") and fp != G.fingerprint("other", base, ["X"], "sha1")


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_render_names_every_conflict(lang):
    conflicts = [{"key": "1", "branch": "agent/x", "worktrees": ["/w/x"], "planned": False,
                  "evidence": [{"kind": "committed", "files": ["f%d" % i for i in range(12)], "matched": ["src/"], "theirs": []},
                               {"kind": "uncommitted", "files": ["u.py"], "matched": ["u.py"], "theirs": []}]},
                 {"key": "2", "branch": "agent/y", "worktrees": [], "planned": True,
                  "evidence": [{"kind": "declared", "files": [], "matched": ["docs/"], "theirs": ["docs/a/"]}]},
                 {"key": "3", "branch": None, "worktrees": ["/w/d"], "planned": False, "evidence": [{"kind": "uncommitted", "files": ["z"], "matched": ["z"], "theirs": []}]}]
    v = {"decision": "deny", "code": "CONFLICT", "conflicts": conflicts, "unknowns": [{"code": "STATUS_FAILED", "text": "boom"}],
         "warnings": [{"code": "TARGET_INFERRED", "text": "guess"}], "target": {"name": "main"}, "fingerprint": "abc123def456"}
    text = G.render(lang, v, "agent/new")
    for needle in ("agent/new", "agent/x", "agent/y", "(detached)", "/w/x", "f0", "...", "docs/a/", "STATUS_FAILED", "TARGET_INFERRED", "abc123def456", "main"):
        assert needle in text, needle
    assert ("已提交" if lang == "zh" else "committed") in text
    assert G.render(lang, {"decision": "deny", "code": "UNKNOWN", "unknowns": [{"code": "U", "text": "t"}], "warnings": []}, "b").startswith("MAGOS")
    assert "plan --branch b" in G.render(lang, {"decision": "deny", "code": "NO_MANIFEST"}, "b")
    for key in G.M:  # both languages carry the same placeholders
        zh, en = G.M[key]
        assert sorted(re.findall(r"{(\w+)}", zh)) == sorted(re.findall(r"{(\w+)}", en)), key
