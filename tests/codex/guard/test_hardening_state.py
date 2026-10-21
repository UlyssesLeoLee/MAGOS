"""1.0.2 claim store, git layer, version and upgrade state: canonical release, Windows alias names, control characters, the key whitelist,
the name check under the lock, the claim format gate, doctor's self-test and copy check, arm's recorded settings and guard command,
version, the version-aware installer, the Hermes plugin launcher, the corrected deny messages and the absolute state paths."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import SH, G, ROOT, SCRIPT, Repo, payload, run
from test_hook import denied, hook
from test_plan_store import claims_dir, verdict

LAUNCHER = ROOT / "hooks" / "run-guard.cmd"
WIN = sys.platform == "win32"


def P(path):
    return str(path).replace("\\", "/")


def common(repo):
    return Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir"))


def hook_path(repo):
    return common(repo) / "hooks" / "reference-transaction"


def put_claim(repo, name, text):
    """A claim file written by hand at the path of `name`."""
    path = claims_dir(repo).joinpath(*name.split("/")).with_suffix(".claim")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def claim_files(repo):
    d = claims_dir(repo)
    return sorted(P(p.relative_to(d)) for p in d.rglob("*") if p.is_file()) if d.exists() else []


def audit_lines(repo):
    log = claims_dir(repo).parent / "audit.log"
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def with_version(data, version):
    """The guard's bytes with its GUARD_VERSION set to `version` (None: the line removed, like a guard before 1.0.2)."""
    line = ('GUARD_VERSION = "%s"' % G.GUARD_VERSION).encode("ascii")
    assert line in data
    return data.replace(line, b"OLD_VERSION = None" if version is None else ('GUARD_VERSION = "%s"' % version).encode("ascii"))


def no_tmp(root):
    return not [p for p in Path(root).rglob("*.tmp")] if Path(root).exists() else True


# ---- release (state-02) ------------------------------------------------------------------------------------------------
def test_release_resolves_the_canonical_claim_for_every_spelling(repo, guard):
    assert guard(repo, "plan", "--branch", "feat", "--paths", "src/a.py").rc == 0
    wt = repo.path.parent / "wt-feat"
    repo.git("worktree", "add", "-q", "-b", "feat", str(wt), "main")
    repo.commit("src/a.py", "work\n", cwd=wt)
    claim = claims_dir(repo) / "feat.claim"
    before = claim.read_bytes()
    for spelling in ("feat", "./feat", "FEAT", "zz/../feat", "./zz/../FEAT"):
        r = guard(repo, "release", "--branch", spelling)
        assert r.rc == 16 and "unmerged work" in r.err and claim.read_bytes() == before, (spelling, r)
    store = claims_dir(repo).parent
    outside = [store / "outside.claim", store.parent / "outside.claim", repo.path / "outside.claim", repo.path.parent / "outside.claim"]
    for f in outside:
        f.write_text("state=active\nbranch=outside\nentry=docs/\n", encoding="utf-8")
    for spelling in ("../outside", "../../outside", "../../../outside", "../../../../outside"):
        r = guard(repo, "release", "--branch", spelling)
        assert r.rc == 0 and r.out.startswith("no open claim"), (spelling, r)
    assert all(f.read_text(encoding="utf-8").startswith("state=active") for f in outside)
    assert [a["op"] for a in audit_lines(repo)] == ["plan"]  # nothing was released under any spelling
    moved = put_claim(repo, "misplaced", "state=active\nbranch=agent/elsewhere\nentry=web/\n")  # a claim not at its own path
    r = guard(repo, "release", "--branch", "agent/elsewhere")
    assert r.rc == 16 and "not at its own path" in r.err and moved.exists()


def test_release_removes_only_its_own_unreadable_claim_file(repo, guard):
    lane = put_claim(repo, "lane", "garbage")
    other = put_claim(repo, "agent/other", "also garbage")
    r = guard(repo, "release", "--branch", "lane")
    assert r.rc == 0 and "released" in r.out.lower() and not lane.exists()
    last = audit_lines(repo)[-1]
    assert last["op"] == "release" and last["branch"] == "lane" and last["reason"] == "unreadable claim file removed"
    stray = claims_dir(repo).parent / "stray.claim"  # garbage beside the claims directory, inside the store
    stray.write_text("garbage", encoding="utf-8")
    alias = put_claim(repo, "alias", "state=active\nbranch=elsewhere\nentry=docs/\n")  # readable: the claim of another branch, not garbage
    for name in ("other-name", "agent/other-name", "agent", "../claims", "../stray", "alias"):
        r = guard(repo, "release", "--branch", name)
        assert r.rc == 0 and r.out.startswith("no open claim"), (name, r)
    assert other.read_text(encoding="utf-8") == "also garbage" and stray.read_text(encoding="utf-8") == "garbage" and alias.exists()
    assert guard(repo, "release", "--branch", "lane").out.startswith("no open claim")  # nothing left of it
    assert [a["reason"] for a in audit_lines(repo)] == ["unreadable claim file removed"]


# ---- names and values (state-03, state-05) --------------------------------------------------------------------------
def test_names_that_alias_on_windows_are_rejected(repo, guard):
    assert guard(repo, "plan", "--branch", "foo/bar", "--paths", "src/a.py").rc == 0
    before = {p: (claims_dir(repo) / p).read_bytes() for p in claim_files(repo)}
    for name in ("foo./bar", "rel.claim/x", "x.claim", "a./b", "deep/X.CLAIM"):
        r = guard(repo, "plan", "--branch", name, "--paths", "docs/")
        assert r.rc == 12 and "[BRANCH_NAME]" in r.out and "Windows alias rule" in r.out, (name, r.out)
    assert {p: (claims_dir(repo) / p).read_bytes() for p in claim_files(repo)} == before
    assert G.check_name(G.open_repo(str(repo.path)), "foo.bar/baz", {}) is None  # a dot inside a component is fine
    p = put_claim(repo, "rel.claim/x", "state=active\nv=1\nbranch=rel.claim/x\nentry=web/\n")  # stored by an earlier guard
    claims, bad = G.read_claims(G.open_repo(str(repo.path)))
    assert G.fold("rel.claim/x") in claims and G.fold("foo/bar") in claims and not bad and p.exists()
    rows = {r["branch"]: r for r in json.loads(guard(repo, "list", "--json").out)}
    assert rows["rel.claim/x"]["state"] == "planned" and rows["foo/bar"]["entries"] == ["src/a.py"]


def test_a_claim_file_is_never_overwritten_by_another_branch(repo, guard, monkeypatch):
    g = G.open_repo(str(repo.path))
    p = put_claim(repo, "b", "state=active\nv=1\nbranch=c\nentry=docs/\n")
    before = p.read_bytes()
    with pytest.raises(G.ClaimRefused) as err:
        G.write_claim(g, "b", {"branch": "b", "entries": ["src/"]})
    assert "holds the claim of c" in str(err.value) and p.read_bytes() == before
    r = guard(repo, "plan", "--branch", "b", "--paths", "src/")
    assert r.rc == 12 and "holds the claim of c" in r.out and p.read_bytes() == before
    (claims_dir(repo) / "q.claim").mkdir()
    with pytest.raises(G.ClaimRefused):
        G.write_claim(g, "q", {"branch": "q", "entries": ["src/"]})
    put_claim(repo, "u", "garbage")
    with pytest.raises(G.ClaimRefused):
        G.write_claim(g, "u", {"branch": "u", "entries": ["src/"]})

    def failing(a, b):
        raise OSError("simulated: the disk is full")
    monkeypatch.setattr(G.os, "replace", failing)
    with pytest.raises(OSError):
        G.write_claim(g, "d", {"branch": "d", "entries": ["web/"]})
    assert not (claims_dir(repo) / "d.claim").exists() and no_tmp(claims_dir(repo))


def test_control_characters_never_reach_a_claim_file(repo, guard):
    wt = str(repo.path.parent / "w") + "\nentry=src/a.py\nbranch=lane-x"
    r = guard(repo, "plan", "--branch", "lane-a", "--paths", "docs/", "--worktree", wt)
    assert r.rc == 12 and "[WORKTREE]" in r.out and claim_files(repo) == []
    repo.git("config", "user.name", "a\nentry=x")
    g = G.open_repo(str(repo.path))
    assert "\n" in G.cfg(g, "user.name")
    assert guard(repo, "plan", "--branch", "lane-b", "--paths", "docs/").rc == 0
    lines = (claims_dir(repo) / "lane-b.claim").read_text(encoding="utf-8").splitlines()
    by = [x for x in lines if x.startswith("by=")]
    assert len(by) == 1 and by[0].startswith("by=a entry=x <t@example.invalid>")
    assert [x for x in lines if x.startswith("entry=")] == ["entry=docs/"] and lines[0] == "state=active"
    assert G.read_claims(g)[0][G.fold("lane-b")]["entries"] == ["docs/"]
    for doc in ({"branch": "z", "entries": ["a\nentry=b"]}, {"branch": "z", "worktree": "w\x07", "entries": ["a"]},
                {"branch": "z", "entries": ["a"], "extra": [("k", "v\x00")]}):
        with pytest.raises(G.ClaimRefused):
            G.write_claim(g, "z", doc)
    assert not (claims_dir(repo) / "z.claim").exists()


def test_claim_keys_are_whitelisted(repo, guard):
    put_claim(repo, "k1", "state=active\nv=1\nbranch=k1\nentries=docs/\nentry=src/a.py\n")
    put_claim(repo, "k2", "state=active\nbranch=k2\nstate=released\nentry=web/\n")
    put_claim(repo, "k3", "state=active\nbranch=k3\nv=9\nentry=README.md\n")
    g = G.open_repo(str(repo.path))
    claims, bad = G.read_claims(g)
    assert not bad
    assert claims["k1"]["entries"] == ["src/a.py"] and ("entries", "docs/") in claims["k1"]["extra"]
    assert claims["k2"]["entries"] == ["web/"] and "state" not in claims["k2"]  # line 1 alone is the state
    assert claims["k3"]["v"] == 1 and claims["k3"]["entries"] == ["README.md"]  # line 2 alone is the format
    for text in ("state=active\nbranch=x\nentry=a\nbranch=y\n", "branch=x\nstate=active\nentry=a\n", "state=active\nv=x\nbranch=x\nentry=a\n",
                 "state=active\nbranch=x\nworktree=a\nworktree=b\nentry=a\n", "state=active\nbranch=x\n"):
        with pytest.raises(ValueError):
            G.parse_claim(text)
    assert G.parse_claim("state=active\nv=0\nbranch=x\nentry=a\n")["v"] == 1  # format 0 and 1 are this guard's format
    put_claim(repo, "k4", "state=active\nbranch=k4\nbranch=other\nentry=docs/\n")
    claims, bad = G.read_claims(g)
    assert "k4" not in claims and "other" not in claims and [(b.code, P(b)) for b in bad] == [("CLAIM_UNPARSEABLE", "k4.claim")]
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "src/b.py")
    assert rc == 11 and [u["code"] for u in v["unknowns"]] == ["CLAIM_UNPARSEABLE"] and "k4" in v["unknowns"][0]["text"]


def test_the_name_check_runs_again_under_the_lock(repo, monkeypatch):
    g = G.open_repo(str(repo.path))
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "60")
    real = G.Lock
    held, free = threading.Event(), threading.Event()

    def holder():
        with real(g):
            held.set()
            free.wait(60)
    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(10)
    arrived = {"nest0": threading.Event(), "nest0/sub": threading.Event()}

    class Spy(real):
        def __enter__(self):
            arrived[threading.current_thread().name].set()  # this planner passed the early name check and now waits for the lock
            return real.__enter__(self)
    monkeypatch.setattr(G, "Lock", Spy)
    results = {}

    def planner(name, path):
        entries, errors = G.parse_manifest([path])
        results[name] = G.plan_core(G.open_repo(str(repo.path)), name, entries, True, False, "en")
    threads = [threading.Thread(target=planner, args=(n, p), name=n) for n, p in (("nest0", "docs/"), ("nest0/sub", "src/"))]
    try:
        for th in threads:
            th.start()
        assert all(e.wait(60) for e in arrived.values())  # both planners passed the unlocked check with no claim in the store
    finally:
        free.set()
        t.join()
        for th in threads:
            th.join(60)
    codes = sorted(G.EXIT[v["code"]] for v in results.values())
    assert codes == [0, 12], results
    loser = next(v for v in results.values() if v["code"] == "INVALID_MANIFEST")
    assert "clashes with the existing branch or claim" in loser["message"] and "file and a directory" in loser["message"]
    assert len(claim_files(repo)) == 1


# ---- the claim format (update-02) -------------------------------------------------------------------------------------
NEWER = "state=active\nv=2\nbranch=agent/a\nscope=exclusive-repo\nentry=docs/\n"
NEWER_TEXT = "agent/a was written by a newer MAGOS (v=2); upgrade this guard"


def test_a_claim_in_a_newer_format_is_never_misread(repo, guard):
    p = put_claim(repo, "agent/a", NEWER)
    before = p.read_bytes()
    for args in (("check", "--branch", "agent/n", "--paths", "src/a.py"), ("plan", "--branch", "agent/n", "--paths", "src/a.py")):
        rc, v = verdict(guard, repo, *args)
        assert rc == 11 and v["code"] == "UNKNOWN" and v["unknowns"] == [{"code": "CLAIM_NEWER_FORMAT", "text": NEWER_TEXT}], v
        assert "upgrade this guard" in v["message"]
    assert claim_files(repo) == ["agent/a.claim"]
    reason = denied(hook(repo, command="git worktree add ../wa -b agent/a"))
    assert "CLAIM_NEWER_FORMAT" in reason and "upgrade this guard" in reason
    assert denied(hook(repo, command="git switch -c feature/z")) is not None  # a claim the guard cannot read still makes the lanes parallel
    r = guard(repo, "release", "--branch", "agent/a")
    assert r.rc == 16 and NEWER_TEXT in r.err and p.read_bytes() == before
    assert guard(repo, "release", "--branch", "./agent/a").rc == 16 and p.read_bytes() == before
    for extra in ((), ("--amend",)):
        r = guard(repo, "plan", "--branch", "agent/a", "--paths", "docs/", "src/", *extra)
        assert r.rc == 11 and "CLAIM_NEWER_FORMAT" in r.out and p.read_bytes() == before, r
    with pytest.raises(G.ClaimTooNew):  # write_claim refuses by itself, whatever a verdict said
        G.write_claim(G.open_repo(str(repo.path)), "agent/a", {"branch": "agent/a", "entries": ["docs/"]})
    assert p.read_bytes() == before
    put_claim(repo, "anon", "state=active\nv=3\nentry=x\n")
    rc, v = verdict(guard, repo, "check", "--branch", "agent/n", "--paths", "src/a.py")
    assert {"code": "CLAIM_NEWER_FORMAT", "text": "claims/anon.claim was written by a newer MAGOS (v=3); upgrade this guard"} in v["unknowns"]


def test_list_shows_unreadable_and_newer_format_claims(repo, guard):
    assert guard(repo, "plan", "--branch", "good", "--paths", "docs/").rc == 0
    put_claim(repo, "broken", "garbage")
    put_claim(repo, "agent/a", NEWER)
    r = guard(repo, "list")
    lines = r.out.splitlines()
    assert r.rc == 0 and lines[0].split() == ["planned", "good", "[docs/]"]
    assert "unreadable claims/broken.claim" in lines and "newer-format agent/a (v=2): upgrade this guard" in lines
    r = guard(repo, "list", "--json")
    rows = json.loads(r.out)
    assert r.rc == 0 and rows[0]["branch"] == "good" and rows[0]["state"] == "planned"
    assert {"branch": None, "state": "unreadable", "path": "broken.claim"} in rows
    assert {"branch": "agent/a", "state": "newer-format", "v": 2, "path": "agent/a.claim"} in rows
    r = guard(repo, "doctor")
    assert r.rc == 1 and "unreadable: 1, newer-format: 1" in r.out and NEWER_TEXT in r.out


def test_format_one_claims_round_trip_unknown_keys(repo, guard):
    put_claim(repo, "old", "state=active\nbranch=old\nentry=web/\n")
    p = put_claim(repo, "lane", "state=active\nv=1\nbranch=lane\nworktree=\ntarget=main\nbase=x\ncreated=t\nby=me\noverride=\nscope=exclusive\n"
                                "entry=src/a.py\n")
    claims = G.read_claims(G.open_repo(str(repo.path)))[0]
    assert claims["old"]["v"] == 1 and claims["old"]["extra"] == [] and claims["lane"]["extra"] == [("scope", "exclusive")]
    for paths in (("src/a.py", "src/b.py"), ("src/a.py", "src/b.py", "README.md")):
        assert guard(repo, "plan", "--branch", "lane", "--paths", *paths, "--amend").rc == 0
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[:3] == ["state=active", "v=1", "branch=lane"] and lines.count("scope=exclusive") == 1
        assert [x[6:] for x in lines if x.startswith("entry=")] == list(paths)
    assert guard(repo, "plan", "--branch", "fresh", "--paths", "docs/").rc == 0
    assert (claims_dir(repo) / "fresh.claim").read_text(encoding="utf-8").splitlines()[:2] == ["state=active", "v=%d" % G.CLAIM_FORMAT]


# ---- doctor, arm and disarm (state-07, state-09, state-10, docs-07) -------------------------------------------------------
def test_doctor_counts_only_a_magos_veto_as_a_passing_self_test(repo, guard, tmp_path, monkeypatch):
    repo.git("branch", "__magos_selftest")
    assert guard(repo, "arm").rc == 0
    r = guard(repo, "doctor")
    assert r.rc == 1 and "self-test inconclusive: the branch __magos_selftest already exists" in r.out and "self-test ok" not in r.out
    repo.git("branch", "-D", "__magos_selftest")
    r = guard(repo, "doctor")
    assert r.rc == 0 and "self-test ok: an unclaimed branch is vetoed" in r.out and "__magos_selftest" not in repo.git("branch", "--list")
    assert guard(repo, "plan", "--branch", "__magos_selftest", "--paths", "docs/").rc == 0
    r = guard(repo, "doctor")
    assert r.rc == 1 and "self-test inconclusive: a claim for __magos_selftest exists" in r.out
    assert "__magos_selftest" not in repo.git("branch", "--list")
    assert guard(repo, "release", "--branch", "__magos_selftest").rc == 0
    real = G.selftest_probe
    monkeypatch.setattr(G, "selftest_probe", lambda g: (128, "fatal: simulated failure"))
    r = guard(repo, "doctor")
    assert r.rc == 1 and "self-test inconclusive: git exited 128 without a MAGOS veto: fatal: simulated failure" in r.out
    monkeypatch.setattr(G, "selftest_probe", real)
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    subprocess.run(["git", "init", "-q", str(unborn)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    assert guard(unborn, "arm").rc == 0
    r = guard(unborn, "doctor")
    assert r.rc == 1 and "self-test inconclusive: git exited" in r.out and "MAGOS veto" in r.out
    assert subprocess.run(["git", "-C", str(unborn), "branch", "--list"], capture_output=True, stdin=subprocess.DEVNULL).stdout == b""


def test_disarm_restores_the_pack_refs_settings(repo, guard):
    repo.git("config", "--local", "gc.packRefs", "true")
    record = common(repo) / "magos" / "arm-config.json"

    def local(key):
        return repo.git("config", "--local", "--get", key, check=False) or None
    assert guard(repo, "arm").rc == 0
    assert (local("gc.packRefs"), local("maintenance.pack-refs.enabled")) == ("false", "false")
    assert json.loads(record.read_text(encoding="utf-8")) == {"gc.packRefs": "true", "maintenance.pack-refs.enabled": None}
    assert guard(repo, "arm").rc == 0  # a re-run never records its own false
    assert json.loads(record.read_text(encoding="utf-8")) == {"gc.packRefs": "true", "maintenance.pack-refs.enabled": None}
    r = guard(repo, "disarm", "--dry-run")
    assert r.rc == 0 and "would restore gc.packRefs=true" in r.out and "would unset maintenance.pack-refs.enabled" in r.out and record.exists()
    assert local("gc.packRefs") == "false"
    r = guard(repo, "disarm")
    assert r.rc == 0 and "did restore gc.packRefs=true" in r.out
    assert (local("gc.packRefs"), local("maintenance.pack-refs.enabled")) == ("true", None) and not record.exists()
    assert guard(repo, "arm").rc == 0
    record.unlink()  # a repository armed before 1.0.2 has no record
    assert guard(repo, "disarm").rc == 0
    assert (local("gc.packRefs"), local("maintenance.pack-refs.enabled")) == ("false", "false")
    assert guard(repo, "arm").rc == 0
    record.write_text("not json", encoding="utf-8")
    r = guard(repo, "disarm")
    assert r.rc == 0 and "unreadable" in r.out and record.exists()
    assert (local("gc.packRefs"), local("maintenance.pack-refs.enabled")) == ("false", "false")


def test_arm_records_a_stable_guard_command_and_doctor_checks_it(repo, guard):
    home = Path(os.environ["MAGOS_HOME"])
    copy = home / "guard" / "scripts" / "magos_guard.py"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(SCRIPT.read_bytes())
    (home / "guard" / "hooks").mkdir()
    (home / "guard" / "hooks" / "run-guard.cmd").write_bytes(LAUNCHER.read_bytes())
    recorded = common(repo) / "magos" / "guard"
    assert guard(repo, "arm").rc == 0
    assert recorded.read_text(encoding="utf-8").strip() == G.guard_cmd(str(copy)) and P(copy) in recorded.read_text(encoding="utf-8")
    r = guard(repo, "doctor")
    assert r.rc == 0 and "backstop guard command: %s" % G.guard_cmd(str(copy)) in r.out and "the same as this guard" in r.out
    shutil.rmtree(str(home / "guard"))  # the copy the backstop names is gone
    r = guard(repo, "doctor")
    rearm = "re-arm in your own terminal: %s arm" % G.guard_cmd()
    assert r.rc == 1 and "the script is MISSING" in r.out and rearm in r.out
    assert guard(repo, "arm").rc == 0  # without a copy: the running script
    assert recorded.read_text(encoding="utf-8").strip() == G.guard_cmd()
    assert guard(repo, "doctor").rc == 0
    hook_path(repo).write_bytes(hook_path(repo).read_bytes() + b"\n# edited\n")
    r = guard(repo, "doctor")
    assert r.rc == 1 and "installed but different from this version; " + rearm in r.out


def test_doctor_checks_the_git_version(tmp_path, monkeypatch):
    real = G.Git.text
    stub = {}

    def text(self, *args, **kw):
        return stub["v"] if args == ("--version",) else real(self, *args, **kw)
    monkeypatch.setattr(G.Git, "text", text)
    stub["v"] = "git version 2.35.1\n"
    r = run(["--repo", str(tmp_path), "doctor"])
    assert r.rc == 1 and "git 2.35 TOO OLD for the lane guard (need 2.36+)" in r.out
    stub["v"] = "git version 2.36.0.windows.1\n"
    r = run(["--repo", str(tmp_path), "doctor"])
    assert r.rc == 0 and "TOO OLD" not in r.out and "git git version 2.36.0.windows.1" in r.out
    assert G.git_too_old("git version 1.9.5") == "1.9" and G.git_too_old("git version 2.100.0") is None and G.git_too_old("git version 3.0") is None


# ---- version, install and the copy check (update-01) -----------------------------------------------------------------
def test_version_subcommand(repo, guard, tmp_path):
    sha = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert G.version_of(SCRIPT.read_bytes()) == G.GUARD_VERSION and re.fullmatch(r"\d+\.\d+\.\d+", G.GUARD_VERSION)
    for cwd in (repo.path, tmp_path):
        r = run(["version"], cwd=cwd)
        assert r.rc == 0 and r.out.splitlines() == ["magos_guard %s" % G.GUARD_VERSION, "sha256 %s" % sha, "path %s" % P(SCRIPT),
                                                    "python %s" % platform.python_version()]
        for argv in (["--json", "version"], ["version", "--json"]):
            r = run(argv, cwd=cwd)
            assert r.rc == 0 and json.loads(r.out) == {"version": G.GUARD_VERSION, "sha256": sha, "path": P(SCRIPT), "python": platform.python_version()}
    assert guard(repo, "plan", "--branch", "agent/v", "--paths", "docs/").rc == 0
    store = sorted(P(p) for p in (common(repo) / "magos").rglob("*"))
    for cmd in ("py -3 scripts/magos_guard.py version", "python3 magos_guard.py --json version", "python3 %s version --json" % P(SCRIPT)):
        assert denied(hook(repo, command=cmd)) is None, cmd  # agents may run it
    assert sorted(P(p) for p in (common(repo) / "magos").rglob("*")) == store  # version writes nothing


def test_install_is_version_aware_and_atomic(repo, guard, tmp_path, monkeypatch):
    clock = iter("2026-10-17T00:00:%02dZ" % n for n in range(60))
    monkeypatch.setattr(G, "now_iso", lambda: next(clock))
    home = tmp_path / "h"
    script, launcher, record = home / "guard" / "scripts" / "magos_guard.py", home / "guard" / "hooks" / "run-guard.cmd", home / "guard" / "VERSION.json"
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0 and "guard copy none -> %s" % G.GUARD_VERSION in r.out and "did copy" in r.out
    assert script.read_bytes() == SCRIPT.read_bytes() and launcher.read_bytes() == LAUNCHER.read_bytes()
    rec = json.loads(record.read_text(encoding="utf-8"))
    assert set(rec) == {"version", "sha256", "source", "installed_at"} and rec["version"] == G.GUARD_VERSION
    assert rec["sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest() and os.path.samefile(rec["source"], str(SCRIPT))
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec["installed_at"]) and no_tmp(home)
    stamps = {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in (script, launcher)}
    for host in ("codex", "hermes"):
        before = json.loads(record.read_text(encoding="utf-8"))
        r = guard(repo, "install", "--host", host, "--home", str(home))
        assert r.rc == 0 and "guard copy unchanged (%s)" % G.GUARD_VERSION in r.out and "did copy" not in r.out
        assert {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in stamps} == stamps
        after = json.loads(record.read_text(encoding="utf-8"))  # rewritten by every install
        assert after["installed_at"] > before["installed_at"] and dict(after, installed_at=None) == dict(before, installed_at=None)
    assert (home / "guard" / "generated" / "hermes.yaml").is_file()  # the snippet is written although the copy is unchanged
    r = guard(repo, "install", "--host", "codex", "--home", str(home), "--dry-run")
    assert r.rc == 0 and "guard copy unchanged" in r.out
    launcher.write_bytes(b"@echo off\r\n")  # only the launcher differs: it alone is replaced
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0 and "did copy %s" % LAUNCHER in r.out and "did copy %s" % SCRIPT not in r.out
    assert launcher.read_bytes() == LAUNCHER.read_bytes() and script.stat().st_ino == stamps[script][0]
    assert G.vtuple("1.0.10") > G.vtuple("1.0.9") and G.version_of(b"x = 1\n") is None


def test_install_refuses_a_downgrade_with_exit_18(repo, guard, tmp_path):
    home = tmp_path / "h"
    script, launcher = home / "guard" / "scripts" / "magos_guard.py", home / "guard" / "hooks" / "run-guard.cmd"
    script.parent.mkdir(parents=True)
    newer = with_version(SCRIPT.read_bytes(), "9.9.9")
    script.write_bytes(newer)
    for dry in ((), ("--dry-run",)):
        r = guard(repo, "install", "--host", "codex", "--home", str(home), *dry)
        assert r.rc == 18 and "9.9.9" in r.err and "--allow-downgrade" in r.err
        assert script.read_bytes() == newer and not launcher.exists() and not (home / "guard" / "VERSION.json").exists()
        assert not (home / "guard" / "generated").exists()
    r = guard(repo, "install", "--host", "codex", "--home", str(home), "--allow-downgrade")
    assert r.rc == 0 and "guard copy 9.9.9 -> %s" % G.GUARD_VERSION in r.out and script.read_bytes() == SCRIPT.read_bytes()
    script.write_bytes(with_version(SCRIPT.read_bytes(), None))  # a copy from before 1.0.2 declares no version: it is older
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0 and "guard copy unversioned -> %s" % G.GUARD_VERSION in r.out and script.read_bytes() == SCRIPT.read_bytes()
    script.write_bytes(with_version(SCRIPT.read_bytes(), "1.0.1"))
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0 and "guard copy 1.0.1 -> %s" % G.GUARD_VERSION in r.out


def test_an_interrupted_install_leaves_the_previous_copy_whole(repo, guard, monkeypatch):
    home = Path(os.environ["MAGOS_HOME"])  # the default home, so that doctor looks at the same copy
    script, record = home / "guard" / "scripts" / "magos_guard.py", home / "guard" / "VERSION.json"
    launcher = home / "guard" / "hooks" / "run-guard.cmd"
    script.parent.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    older = with_version(SCRIPT.read_bytes(), "1.0.0")
    script.write_bytes(older)
    old_launcher = LAUNCHER.read_bytes().replace(b"setlocal\n", b"setlocal\nREM 1.0.0\n", 1)
    launcher.write_bytes(old_launcher)
    record.write_text(json.dumps({"version": "1.0.0", "sha256": hashlib.sha256(older).hexdigest(), "source": "x", "installed_at": "2026-01-01T00:00:00Z"}),
                      encoding="utf-8")
    before = record.read_bytes()
    real = os.replace

    def failing(a, b):
        if P(b).endswith("guard/scripts/magos_guard.py"):
            raise OSError("simulated: the disk is full")
        return real(a, b)
    monkeypatch.setattr(G.os, "replace", failing)
    r = guard(repo, "install", "--host", "codex")
    monkeypatch.setattr(G.os, "replace", real)
    assert r.rc == 11 and "install failed" in r.err and "simulated" in r.err
    assert script.read_bytes() == older and launcher.read_bytes() == old_launcher and record.read_bytes() == before and no_tmp(home / "guard")
    r = guard(repo, "doctor")
    assert r.rc == 1 and "1.0.0 (%s) DIFFERS from this guard %s" % (hashlib.sha256(older).hexdigest()[:12], G.GUARD_VERSION) in r.out


def stale_guard_bytes():
    """The 1.0.0 guard as shipped (74bf82f), or, where the history is not there, the current bytes without a version line."""
    p = subprocess.run(["git", "-C", str(ROOT), "show", "74bf82f:scripts/magos_guard.py"], capture_output=True, stdin=subprocess.DEVNULL)
    return p.stdout if p.returncode == 0 and p.stdout else with_version(SCRIPT.read_bytes(), None)


def test_doctor_flags_a_stale_copy_before_looking_for_a_repository(repo, tmp_path):
    home = Path(os.environ["MAGOS_HOME"])
    script = home / "guard" / "scripts" / "magos_guard.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(stale_guard_bytes())
    (home / "guard" / "hooks").mkdir()
    (home / "guard" / "hooks" / "run-guard.cmd").write_bytes(LAUNCHER.read_bytes())
    gen = home / "guard" / "generated"
    gen.mkdir()
    (gen / "codex.json").write_text("{}", encoding="utf-8")
    (gen / "hermes.yaml").write_text("hooks: {}\n", encoding="utf-8")
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    for where in (nowhere, repo.path):
        r = run(["--repo", str(where), "--lang", "en", "doctor"])
        assert r.rc == 1 and r.out.startswith("guard %s (" % G.GUARD_VERSION), r.out
        assert "unversioned" in r.out and "DIFFERS from this guard %s" % G.GUARD_VERSION in r.out
        assert "%s install --host codex" % G.guard_cmd() in r.out and "%s install --host hermes" % G.guard_cmd() in r.out
        assert "install --host claude" not in r.out and r.out.index("DIFFERS") < r.out.index("repository:")
    assert "guard is inert here" in run(["--repo", str(nowhere), "doctor"]).out
    shutil.rmtree(str(gen))  # no generated snippet: every host gets its refresh command
    assert all("install --host %s" % h in run(["--repo", str(nowhere), "doctor"]).out for h in ("claude", "codex", "hermes"))
    script.write_bytes(SCRIPT.read_bytes())
    for where in (nowhere, repo.path):
        r = run(["--repo", str(where), "--lang", "en", "doctor"])
        assert r.rc == 0 and "the same as this guard" in r.out and "DIFFERS" not in r.out


def test_hermes_snippet_points_at_the_hermes_plugin_launcher(repo, guard, tmp_path, monkeypatch):
    hermes = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    own = hermes / "plugins" / "magos" / "hooks" / "run-guard.cmd"
    own.parent.mkdir(parents=True)
    own.write_bytes(LAUNCHER.read_bytes())
    (hermes / "plugins" / "magos" / "scripts").mkdir()
    (hermes / "plugins" / "magos" / "scripts" / "magos_guard.py").write_bytes(SCRIPT.read_bytes())
    home = tmp_path / "mh"
    saved = home / "guard" / "generated" / "hermes.yaml"
    r = guard(repo, "install", "--host", "hermes", "--home", str(home))
    assert r.rc == 0 and P(own) in saved.read_text(encoding="utf-8") and P(own) in r.out
    assert "%s/guard/hooks" % P(home) not in saved.read_text(encoding="utf-8") and "hook hermes pre-tool" in saved.read_text(encoding="utf-8")
    assert (home / "guard" / "scripts" / "magos_guard.py").is_file()  # the copy is still made: Codex runs it
    assert P(own) not in G.host_snippet("codex", P(home))  # only the Hermes entry follows the Hermes plugin
    own.unlink()
    assert guard(repo, "install", "--host", "hermes", "--home", str(home)).rc == 0
    assert "%s/guard/hooks/run-guard.cmd" % P(home) in saved.read_text(encoding="utf-8")
    monkeypatch.delenv("HERMES_HOME")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
    assert G.hermes_home() == (os.path.join(str(tmp_path / "lad"), "hermes") if WIN else os.path.expanduser("~/.hermes"))


# ---- deny messages (docs-08) and absolute state paths (state-04) ------------------------------------------------------------
def test_deny_messages_give_instructions_that_work(repo, guard):
    repo.branch_with("agent/other", "src/a.py")  # another lane: AUTO engages auto-named creations
    reason = denied(hook(repo, "Agent", prompt="x", isolation="worktree"))
    assert "names the branch or worktree itself" in reason and "worktree-<name>" in reason and "EnterWorktree name=<name>" in reason
    assert denied(hook(repo, "EnterWorktree", name="feat")) is not None  # not planned yet
    assert guard(repo, "plan", "--branch", "worktree-feat", "--paths", "docs/").rc == 0  # what the text says to do
    assert denied(hook(repo, "EnterWorktree", name="feat")) is None
    assert guard(repo, "plan", "--branch", "lane", "--paths", "web/").rc == 0
    wt = repo.path.parent / "wt-lane"
    repo.git("worktree", "add", "-q", "-b", "lane", str(wt), "main")
    repo.commit("web/package-lock.json", "work\n", cwd=wt)
    repo.git("merge", "-q", "--no-ff", "lane", "-m", "integrate lane")
    repo.write("web/new.txt", "untracked\n", base=wt)
    r = guard(repo, "release", "--branch", "lane")
    assert r.rc == 16 and "release refused: the branch has unmerged work or its worktree has uncommitted changes" in r.err
    r = run(["--repo", str(repo.path), "--lang", "zh", "release", "--branch", "lane"])
    assert r.rc == 16 and "未提交的修改" in r.err
    os.remove(wt / "web" / "new.txt")
    assert guard(repo, "release", "--branch", "lane").rc == 0  # a clean worktree that is still checked out is no reason to refuse


def test_state_paths_are_matched_by_their_absolute_spelling(repo, guard, tmp_path, monkeypatch):
    gh = tmp_path / "guardhome"  # a guard home whose name the .magos pattern cannot match
    monkeypatch.setenv("MAGOS_HOME", str(gh))
    proj = tmp_path / "proj"
    proj.mkdir()
    for args in (["clone", "-q", "--bare", str(repo.path), str(proj / ".bare")], ["-C", str(proj / ".bare"), "worktree", "add", "-q", str(proj / "main"), "main"]):
        subprocess.run(["git", *args], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    main = proj / "main"
    assert guard(main, "arm").rc == 0
    bare = Path(subprocess.run(["git", "-C", str(main), "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True,
                               stdin=subprocess.DEVNULL).stdout.decode().strip())
    s, h = P(bare / "magos"), P(gh)
    writers = ["rm %s/ARMED" % s, "rm -rf %s/claims" % s, "cp evil.py %s/guard/scripts/magos_guard.py" % h, "echo x > %s/claims/l.claim" % s,
               "unlink %s/ARMED" % s, "rm -rf %s/guard" % h]
    if WIN:
        writers += ["rm %s" % str(bare / "magos" / "ARMED"), "Remove-Item %s" % str(bare / "magos" / "claims"), "rm %s/armed" % s.upper(),
                    "cp evil.py %s" % str(gh / "guard" / "scripts" / "magos_guard.py").lower(),
                    "rm /%s/%s/ARMED" % (s[0].lower(), s[3:])]  # the Git Bash spelling /c/...
    readers = ["cat %s/ARMED" % s, "ls %s/claims" % s, "cat %s/guard/scripts/magos_guard.py" % h]
    for cmd in writers:
        reason = denied(hook(main, command=cmd))
        assert reason and "guard's own" in reason, cmd
    for cmd in readers:
        assert denied(hook(main, command=cmd)) is None, cmd
    s2 = P(common(repo) / "magos")  # a repository with no claim and no hook: its state is not guarded yet
    for cmd in ["rm %s/ARMED" % s2, "rm -rf %s/claims" % s2, "cp evil.py %s/guard/scripts/magos_guard.py" % h]:
        assert denied(hook(repo, command=cmd)) is None, cmd
    assert G.protected("rm %s/ARMED" % s) is None  # without the absolute roots only the .git and .magos spellings are known


# ---- launcher homes and host entries (launcher-n3, launcher-n4, h-upgrade-05) ------------------------------------------------
NO_WINDOW = 0x08000000 if WIN else 0
META_HOMES = ("a&b", "p(a)r", "c^d", "p%PATH%q", "s;c,o=m", "x=y")


def stale(version):
    """This guard's bytes declaring `version` (None: no version line, like a guard before 1.0.2)."""
    return with_version(SCRIPT.read_bytes(), version)


def lane_payload(repo):
    """A Bash payload that creates a named worktree in `repo`: every guard denies it (no manifest is registered)."""
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": "git worktree add ../wt-q -b agent/q"}, "cwd": str(repo.path)}).encode("utf-8")


def bash_exe():
    """The bash Claude Code runs hook commands with: Git's bash beside the test sh on Windows (never System32's WSL launcher)."""
    if WIN:
        found = os.path.join(os.path.dirname(SH), "bash.exe") if SH else None
        return found if found and os.path.isfile(found) else None
    return shutil.which("bash")


def run_entry(argv, payload, cwd):
    return subprocess.run(argv, input=payload, capture_output=True, cwd=str(cwd), creationflags=NO_WINDOW, timeout=120)


def deny_object(p):
    """True when a host entry's process printed the guard's deny object and exited 0."""
    if p.returncode != 0 or not p.stdout.strip():
        return False
    obj = json.loads(p.stdout)
    return obj["decision"] == "block" and obj["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.skipif(not WIN, reason="cmd.exe reads these characters only on Windows")
def test_install_refuses_a_home_with_cmd_metacharacters(repo, guard, tmp_path):
    from test_package import _mini_yaml
    for name in META_HOMES:
        home = tmp_path / name / ".magos"
        bad = next(c for c in name if c in "&()^%;,=")
        for host in G.HOSTS:
            for dry in ((), ("--dry-run",)):
                r = guard(repo, "install", "--host", host, "--home", str(home), *dry)
                assert r.rc == 2 and repr(bad) in r.err and P(home) + "/guard/hooks/run-guard.cmd" in r.err, (name, host, r)
                assert "--home DIR or MAGOS_HOME" in r.err and r.out == "", (name, host, r)
        assert not (tmp_path / name).exists(), name  # nothing was written under it
    bash, payload = bash_exe(), lane_payload(repo)
    for name in ("two words", "a!b", "o'brien", "d$x", "目录"):
        home = tmp_path / name / ".magos"
        for host in G.HOSTS:
            assert guard(repo, "install", "--host", host, "--home", str(home)).rc == 0, (name, host)
        gen = home / "guard" / "generated"
        claude = json.loads((gen / "claude.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
        codex = json.loads((gen / "codex.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]["commandWindows"]
        hermes = _mini_yaml((gen / "hermes.yaml").read_text(encoding="utf-8"))["hooks"]["pre_tool_call"][0]["command"]
        runs = ([("claude", [bash, "-c", claude])] if bash else []) + [
            ("codex", ["powershell", "-NoProfile", "-NonInteractive", "-Command", codex]),
            ("hermes", shlex.split(hermes))]  # Hermes splits the command into its words and starts them without a shell
        for host, argv in runs:
            p = run_entry(argv, payload, repo.path)
            assert deny_object(p), (name, host, p)


def test_codex_snippet_quotes_the_launcher_for_sh_and_powershell(repo, guard, tmp_path):
    home = tmp_path / "o'brien x" / ".magos"
    assert guard(repo, "install", "--host", "codex", "--home", str(home)).rc == 0
    entry = json.loads((home / "guard" / "generated" / "codex.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
    launcher = P(home) + "/guard/hooks/run-guard.cmd"
    assert entry["command"] == "sh '%s' hook codex pre-tool" % launcher.replace("'", "'\\''")
    assert entry["commandWindows"] == "& '%s' hook codex pre-tool; exit $LASTEXITCODE" % launcher.replace("'", "''")
    assert G.ps_quote("o’b") == "'o’’b'"  # PowerShell also closes a single-quoted string at a typographic quote
    payload, ran = lane_payload(repo), 0
    if SH:
        p = run_entry([SH, "-c", entry["command"]], payload, repo.path)
        assert deny_object(p), p
        ran += 1
    if WIN:
        p = run_entry(["powershell", "-NoProfile", "-NonInteractive", "-Command", entry["commandWindows"]], payload, repo.path)
        assert deny_object(p), p
        ran += 1
    if not ran:
        pytest.skip("neither sh nor PowerShell is available")


def test_claude_snippet_quotes_the_launcher_for_bash(repo, guard, tmp_path, monkeypatch):
    bash, payload, real = bash_exe(), lane_payload(repo), sys.platform
    for name in ("o'brien", "d$x", "t`ick", "a!b"):
        home = P(tmp_path / name / ".magos")
        launcher = home + "/guard/hooks/run-guard.cmd"
        quoted = "'%s'" % launcher.replace("'", "'\\''")
        for platform in ("linux", "win32"):
            monkeypatch.setattr(G.sys, "platform", platform)
            groups = json.loads(G.host_snippet("claude", home))["hooks"]["PreToolUse"]
            monkeypatch.setattr(G.sys, "platform", real)
            assert [g["hooks"][0]["command"] for g in groups] == [quoted + " --strict hook claude pre-tool", quoted + " hook claude pre-tool"]
            assert all(g["hooks"][0]["shell"] == "bash" for g in groups)
        if not bash:
            continue
        back = subprocess.run([bash, "-c", "printf %s " + quoted], capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=60)
        assert back.stdout.decode("utf-8") == launcher, (name, back)  # bash reads the exact path back
        assert guard(repo, "install", "--host", "claude", "--home", home).rc == 0
        for g in json.loads((Path(home) / "guard" / "generated" / "claude.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]:
            p = run_entry([bash, "-c", g["hooks"][0]["command"]], payload, repo.path)
            assert deny_object(p), (name, g["matcher"], p)
    if not bash:
        pytest.skip("no bash to run the entries")


# ---- the Hermes entry (h-upgrade-01, replay-docs-new-2) ---------------------------------------------------------------------
def plugin_at(hermes, guard_bytes):
    """A Hermes plugin directory holding the launcher and `guard_bytes` as its guard; -> the launcher path as install writes it."""
    root = hermes / "plugins" / "magos"
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "hooks" / "run-guard.cmd").write_bytes(LAUNCHER.read_bytes())
    (root / "scripts" / "magos_guard.py").write_bytes(guard_bytes)
    return P(os.path.abspath(str(root / "hooks" / "run-guard.cmd")))


def test_hermes_entry_follows_the_plugin_only_at_the_same_version(repo, guard, tmp_path, monkeypatch):
    hermes = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    home = tmp_path / "mh"
    saved, copy = home / "guard" / "generated" / "hermes.yaml", P(home) + "/guard/hooks/run-guard.cmd"
    own = plugin_at(hermes, SCRIPT.read_bytes())
    r = guard(repo, "install", "--host", "hermes", "--home", str(home))
    assert r.rc == 0 and own in saved.read_text(encoding="utf-8") and "NOTE" not in r.out
    for guard_bytes, shown in ((stale(None), "unversioned"), (stale("9.9.9"), "9.9.9")):
        plugin_at(hermes, guard_bytes)
        r = guard(repo, "install", "--host", "hermes", "--home", str(home))
        text = saved.read_text(encoding="utf-8")
        assert r.rc == 0 and copy in text and own not in text, (shown, text)
        assert "holds guard %s, not %s" % (shown, G.GUARD_VERSION) in r.out and "hermes plugins update magos" in r.out, (shown, r.out)
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()

    def doctor():
        return run(["--repo", str(nowhere), "--lang", "en", "doctor", "--home", str(home)])
    plugin_at(hermes, SCRIPT.read_bytes())
    assert guard(repo, "install", "--host", "hermes", "--home", str(home)).rc == 0 and own in saved.read_text(encoding="utf-8")
    r = doctor()
    assert r.rc == 0 and "hermes entry: %s (guard %s)" % (own, G.GUARD_VERSION) in r.out, r.out
    plugin_at(hermes, stale("1.0.1"))  # the plugin moved to another version after install
    r = doctor()
    assert r.rc == 1 and "its launcher %s runs guard 1.0.1, not this guard %s" % (own, G.GUARD_VERSION) in r.out, r.out
    shutil.rmtree(str(hermes / "plugins" / "magos"))  # the plugin was removed: fail_closed blocks every Hermes terminal call
    r = doctor()
    assert r.rc == 1 and "its launcher %s does NOT EXIST" % own in r.out and "install --host hermes" in r.out, r.out
    if WIN:  # a plugin path cmd.exe would misread: the entry names the copy, and install says why
        amp = tmp_path / "a&b" / "hermes"
        monkeypatch.setenv("HERMES_HOME", str(amp))
        own2 = plugin_at(amp, SCRIPT.read_bytes())
        r = guard(repo, "install", "--host", "hermes", "--home", str(home))
        text = saved.read_text(encoding="utf-8")
        assert r.rc == 0 and copy in text and own2 not in text and "contains '&'" in r.out and own2 in r.out, r.out


# ---- install: modes, atomicity, VERSION.json (h-upgrade-03, h-upgrade-09, h-upgrade-10) --------------------------------------
@pytest.mark.skipif(WIN, reason="POSIX file modes")
def test_install_keeps_the_launcher_executable_on_posix(repo, guard, tmp_path):
    home = tmp_path / "h"
    script, launcher = home / "guard" / "scripts" / "magos_guard.py", home / "guard" / "hooks" / "run-guard.cmd"
    assert guard(repo, "install", "--host", "codex", "--home", str(home)).rc == 0
    assert stat.S_IMODE(os.stat(str(launcher)).st_mode) == 0o755
    os.chmod(str(launcher), 0o644)
    launcher.write_bytes(LAUNCHER.read_bytes()[:-1] + b"#")
    script.write_bytes(SCRIPT.read_bytes()[:-1] + b"#")
    assert guard(repo, "install", "--host", "codex", "--home", str(home)).rc == 0
    assert stat.S_IMODE(os.stat(str(launcher)).st_mode) == 0o755
    assert script.read_bytes() == SCRIPT.read_bytes() and launcher.read_bytes() == LAUNCHER.read_bytes()


def test_install_replaces_both_files_or_neither(repo, guard, monkeypatch, tmp_path):
    home = tmp_path / "h"
    script, launcher, record = home / "guard" / "scripts" / "magos_guard.py", home / "guard" / "hooks" / "run-guard.cmd", home / "guard" / "VERSION.json"
    script.parent.mkdir(parents=True)
    launcher.parent.mkdir(parents=True)
    script.write_bytes(stale("1.0.0"))
    launcher.write_bytes(b"@echo off\nREM the 1.0.0 launcher\n")
    record.write_text(json.dumps({"version": "1.0.0", "sha256": "0" * 64, "source": "x", "installed_at": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    before = {p: p.read_bytes() for p in (script, launcher, record)}
    real = os.replace

    def failing(a, b):
        if P(b).endswith("guard/hooks/run-guard.cmd"):
            raise OSError("simulated: the launcher is in use")
        return real(a, b)
    monkeypatch.setattr(G.os, "replace", failing)
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 11 and "install failed" in r.err and "simulated" in r.err and "kept whole" in r.err, r
    assert {p: p.read_bytes() for p in before} == before and no_tmp(home)
    r = guard(repo, "install", "--host", "codex", "--home", str(home), "--json")  # the failure as a deny object as well
    assert r.rc == 11 and json.loads(r.out)["unknowns"][0]["code"] == "INTERNAL_ERROR" and {p: p.read_bytes() for p in before} == before
    moves = []

    def restore_fails(a, b):  # the script's move fails, and so does putting the launcher back: install says so instead of "kept whole"
        if P(b).endswith("guard/scripts/magos_guard.py"):
            raise OSError("simulated: the script is in use")
        if P(b).endswith("guard/hooks/run-guard.cmd"):
            moves.append(b)
            if len(moves) > 1:
                raise OSError("simulated: the launcher is in use")
        return real(a, b)
    monkeypatch.setattr(G.os, "replace", restore_fails)
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 11 and "could not be put back" in r.err and "may now mix two versions" in r.err and no_tmp(home), r
    monkeypatch.setattr(G.os, "replace", real)
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0 and script.read_bytes() == SCRIPT.read_bytes() and launcher.read_bytes() == LAUNCHER.read_bytes() and no_tmp(home)
    lone = tmp_path / "lone"  # a copy without a launcher: a launcher moved in before the script's move failed is removed again
    (lone / "guard" / "scripts").mkdir(parents=True)
    (lone / "guard" / "scripts" / "magos_guard.py").write_bytes(stale("1.0.0"))

    def script_fails(a, b):
        if P(b).endswith("guard/scripts/magos_guard.py"):
            raise OSError("simulated: the script is in use")
        return real(a, b)
    monkeypatch.setattr(G.os, "replace", script_fails)
    r = guard(repo, "install", "--host", "codex", "--home", str(lone))
    assert r.rc == 11 and "kept whole" in r.err and not (lone / "guard" / "hooks" / "run-guard.cmd").exists() and no_tmp(lone), r
    assert (lone / "guard" / "scripts" / "magos_guard.py").read_bytes() == stale("1.0.0")


def test_version_json_is_rewritten_by_install_and_read_by_doctor(repo, guard, tmp_path, monkeypatch):
    clock = iter("2026-10-17T01:00:%02dZ" % n for n in range(60))
    monkeypatch.setattr(G, "now_iso", lambda: next(clock))
    home, nowhere = tmp_path / "h", tmp_path / "nowhere"
    nowhere.mkdir()
    record = home / "guard" / "VERSION.json"
    assert guard(repo, "install", "--host", "codex", "--home", str(home)).rc == 0
    first = json.loads(record.read_text(encoding="utf-8"))
    assert guard(repo, "install", "--host", "codex", "--home", str(home)).rc == 0
    second = json.loads(record.read_text(encoding="utf-8"))
    assert second["installed_at"] > first["installed_at"] and dict(second, installed_at=None) == dict(first, installed_at=None)

    def doctor():
        return run(["--repo", str(nowhere), "--lang", "en", "doctor", "--home", str(home)])
    line = "guard copy provenance: %s (%s) from %s, installed %s" % (G.GUARD_VERSION, second["sha256"][:12], second["source"], second["installed_at"])
    r = doctor()
    assert r.rc == 0 and line in r.out.splitlines(), r.out
    record.write_text(json.dumps(dict(second, sha256="0" * 64)), encoding="utf-8")
    r = doctor()  # information only: the exit code stays
    assert r.rc == 0 and line.replace(second["sha256"][:12], "0" * 12) + ", which does not match the copy" in r.out.splitlines(), r.out
    before = record.read_bytes()
    assert guard(repo, "install", "--host", "codex", "--home", str(home), "--dry-run").rc == 0 and record.read_bytes() == before
    record.write_text("{not json", encoding="utf-8")
    r = doctor()
    assert r.rc == 0 and "guard copy provenance: VERSION.json cannot be read" in r.out
    record.unlink()
    assert "guard copy provenance: no VERSION.json" in doctor().out


# ---- doctor (h-upgrade-06, h-upgrade-07, h-upgrade-08, NF-update-1, NF-state-2) ---------------------------------------------------
def test_doctor_self_test_has_its_own_git_budget(repo, guard, monkeypatch):
    assert guard(repo, "arm").rc == 0
    real = G.selftest_probe

    def late(g):
        g.deadline = time.monotonic() - 1  # the time the rest of doctor shares is used up
        return real(g)
    monkeypatch.setattr(G, "selftest_probe", late)
    r = guard(repo, "doctor")
    assert r.rc == 0 and "self-test ok: an unclaimed branch is vetoed" in r.out, r
    assert "__magos_selftest" not in repo.git("branch", "--list")

    def timeout(g):
        raise G.GitFail("BUDGET_EXCEEDED", "git timed out: branch __magos_selftest")
    monkeypatch.setattr(G, "selftest_probe", timeout)
    r = guard(repo, "doctor")
    assert r.rc == 1 and "self-test inconclusive: the probe failed: BUDGET_EXCEEDED: git timed out: branch __magos_selftest" in r.out, r


def test_doctor_counts_only_the_backstop_veto_line(tmp_path, guard, monkeypatch):
    path = tmp_path / "MAGOS-lab" / "repo"  # a repository whose path contains MAGOS
    path.mkdir(parents=True)
    r = Repo(path)
    r.git("init", "-q")
    r.commit("README.md", "base\n")
    assert guard(r, "arm").rc == 0
    lock = common(r) / "refs" / "heads" / "__magos_selftest.lock"
    lock.write_bytes(b"")
    res = guard(r, "doctor")
    assert res.rc == 1 and "self-test inconclusive: " in res.out and "__magos_selftest.lock exists" in res.out and "self-test ok" not in res.out
    assert lock.exists()  # doctor never deletes it
    lock.unlink()
    lock_text = ("fatal: cannot lock ref 'refs/heads/__magos_selftest': Unable to create '%s/.git/refs/heads/__magos_selftest.lock': "
                 "File exists." % P(path))
    cases = ((128, lock_text, False),
             (1, "MAGOS BLOCKED: '__magos_selftest' has no registered file manifest (creation / 新建分支).\nfatal: ref updates aborted by hook", True),
             (1, "hint: x\nMAGOS 拒绝: 分支「__magos_selftest」没有已登记的文件清单", True),
             (1, "error: MAGOS hook failed", False))
    for rc, err, ok in cases:
        monkeypatch.setattr(G, "selftest_probe", lambda g, rc=rc, err=err: (rc, err))
        res = guard(r, "doctor")
        if ok:
            assert res.rc == 0 and "self-test ok: an unclaimed branch is vetoed" in res.out, (err, res.out)
        else:
            assert res.rc == 1 and "self-test inconclusive: git exited %d without a MAGOS veto" % rc in res.out, (err, res.out)


def test_doctor_home_option_and_doctor_run_from_the_copy(repo, guard, tmp_path, monkeypatch):
    nowhere, x = tmp_path / "nowhere", tmp_path / "custom home"
    nowhere.mkdir()
    assert guard(repo, "install", "--host", "codex", "--home", str(x)).rc == 0
    copy, record = x / "guard" / "scripts" / "magos_guard.py", x / "guard" / "VERSION.json"
    copy.write_bytes(stale("1.0.1"))  # the copy the Codex entry runs is stale

    def doctor(*extra):
        return run(["--repo", str(nowhere), "--lang", "en", "doctor", *extra])
    r = doctor()
    assert r.rc == 0 and "guard copy: none under %s/guard" % P(os.environ["MAGOS_HOME"]) in r.out, r.out
    r = doctor("--home", str(x))
    assert r.rc == 1 and "1.0.1 (" in r.out and "DIFFERS from this guard %s" % G.GUARD_VERSION in r.out, r.out
    assert '  %s install --host codex --home "%s"' % (G.guard_cmd(), P(x)) in r.out.splitlines(), r.out
    monkeypatch.setenv("MAGOS_HOME", str(x))
    r = doctor()
    assert r.rc == 1 and "DIFFERS" in r.out and "  %s install --host codex" % G.guard_cmd() in r.out.splitlines(), r.out
    # doctor run from the copy itself compares it with the source VERSION.json names
    copy.write_bytes(SCRIPT.read_bytes())
    src = tmp_path / "newer" / "scripts" / "magos_guard.py"
    src.parent.mkdir(parents=True)
    src.write_bytes(stale("9.9.9"))
    (src.parent.parent / "hooks").mkdir()
    (src.parent.parent / "hooks" / "run-guard.cmd").write_bytes(LAUNCHER.read_bytes())

    def source(path):
        rec = json.loads(record.read_text(encoding="utf-8"))
        record.write_text(json.dumps(dict(rec, source=P(path))), encoding="utf-8")
    source(src)
    p = subprocess.run([sys.executable, "-X", "utf8", "-B", str(copy), "--repo", str(nowhere), "--lang", "en", "doctor", "--home", str(x)],
                       capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=120)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 1 and "this guard is the copy; it is compared with its source %s" % P(src) in out, out
    assert "DIFFERS from its source %s 9.9.9" % P(src) in out and '  %s install --host codex --home "%s"' % (G.guard_cmd(str(src)), P(x)) in out.splitlines(), out
    monkeypatch.setattr(G, "__file__", str(copy))  # the same, in process
    r = doctor("--home", str(x))
    assert r.rc == 1 and "DIFFERS from its source %s 9.9.9" % P(src) in r.out, r.out
    r = guard(repo, "install", "--host", "codex", "--home", str(x))  # install run from the copy keeps the source it came from
    assert r.rc == 0 and "guard copy unchanged" in r.out and json.loads(record.read_text(encoding="utf-8"))["source"] == P(src), r
    source(SCRIPT)  # a source byte-identical to the copy
    r = doctor("--home", str(x))
    assert r.rc == 0 and "the same as its source %s" % P(SCRIPT) in r.out, r.out
    source(tmp_path / "gone" / "magos_guard.py")
    r = doctor("--home", str(x))
    assert r.rc == 0 and "VERSION.json names no source to compare it with" in r.out, r.out
    record.unlink()
    r = doctor("--home", str(x))
    assert r.rc == 0 and "VERSION.json names no source to compare it with" in r.out and "provenance: no VERSION.json" in r.out, r.out


def test_doctor_never_suggests_a_refused_install(tmp_path):
    home = Path(os.environ["MAGOS_HOME"]) / "guard"
    (home / "scripts").mkdir(parents=True)
    (home / "hooks").mkdir()
    (home / "generated").mkdir()
    (home / "generated" / "codex.json").write_text("{}", encoding="utf-8")
    copy = stale("9.9.9")
    (home / "scripts" / "magos_guard.py").write_bytes(copy)
    (home / "hooks" / "run-guard.cmd").write_bytes(LAUNCHER.read_bytes())
    source = tmp_path / "magos-9.9.9" / "scripts" / "magos_guard.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(copy)
    (home / "VERSION.json").write_text(json.dumps({"version": "9.9.9", "sha256": hashlib.sha256(copy).hexdigest(), "source": P(source),
                                                   "installed_at": "2026-10-17T00:00:00Z"}), encoding="utf-8")
    r = run(["--repo", str(tmp_path), "--lang", "en", "doctor"])
    assert r.rc == 1 and "is NEWER than this guard %s" % G.GUARD_VERSION in r.out and "9.9.9 (" in r.out, r.out
    assert "run doctor from that MAGOS (VERSION.json names its source: %s)" % P(source) in r.out and "install --host" not in r.out, r.out


def test_arm_records_the_copy_only_at_the_same_version(repo, guard):
    copy = Path(os.environ["MAGOS_HOME"]) / "guard" / "scripts" / "magos_guard.py"
    copy.parent.mkdir(parents=True)
    recorded = common(repo) / "magos" / "guard"
    for data, expect in ((stale("1.0.1"), G.guard_cmd()), (stale(None), G.guard_cmd()), (SCRIPT.read_bytes(), G.guard_cmd(str(copy)))):
        copy.write_bytes(data)
        assert guard(repo, "arm").rc == 0
        assert recorded.read_text(encoding="utf-8").strip() == expect
        p = subprocess.run(["git", "-C", str(repo.path), "branch", "agent/unclaimed"], capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        err = p.stderr.decode("utf-8", "replace")
        assert p.returncode != 0 and "MAGOS BLOCKED: " in err and expect in err, err  # the backstop's veto names the recorded command


def test_doctor_reports_a_backstop_command_older_than_this_guard(repo, guard, tmp_path):
    assert guard(repo, "arm").rc == 0
    recorded = common(repo) / "magos" / "guard"
    rearm = "re-arm in your own terminal: %s arm" % G.guard_cmd()
    for name, data, shown in (("old", stale("1.0.1"), "1.0.1"), ("none", stale(None), "no version")):
        script = tmp_path / name / "magos_guard.py"
        script.parent.mkdir()
        script.write_bytes(data)
        recorded.write_bytes((G.guard_cmd(str(script)) + "\n").encode("utf-8"))
        r = guard(repo, "doctor")
        assert r.rc == 1 and "its script declares %s, older than this guard %s" % (shown, G.GUARD_VERSION) in r.out and rearm in r.out, r.out
    recorded.write_bytes((G.guard_cmd() + "\n").encode("utf-8"))
    r = guard(repo, "doctor")
    assert r.rc == 0 and "backstop guard command: %s" % G.guard_cmd() in r.out and "older than this guard" not in r.out, r.out


# ---- the claim format line and the newer-format denial (NF-update-2, h-upgrade-11) -----------------------------------------
def test_claim_format_line_reads_any_integer_spelling(repo, guard):
    wt = repo.worktree("wt-d", "agent/d")
    repo.write("src/a.py", "edited\n", base=wt)  # the lane has uncommitted work: release must refuse
    cases = [(v, "active") for v in ("01", "001", "0")] + [(v, "newer") for v in ("2", "02", "1000000", "1" * 5000)] + \
        [(v, "unreadable") for v in ("1.0", "+1", "x", "", "1_0", " 1", "١")]
    for v, kind in cases:
        p = put_claim(repo, "agent/d", "state=active\nv=%s\nbranch=agent/d\nentry=src/a.py\n" % v)
        before = p.read_bytes()
        lines = guard(repo, "list").out.splitlines()
        if kind == "active":
            assert [ln.split() for ln in lines] == [["active", "agent/d", "[src/a.py]"]], (v, lines)
        elif kind == "newer":
            assert lines == ["newer-format agent/d (v=%s): upgrade this guard" % v.lstrip("0")], (v[:20], lines[:1])
        else:
            assert lines == ["unreadable claims/agent/d.claim"], (v, lines)
        r = guard(repo, "release", "--branch", "agent/d")
        assert r.rc == 16 and p.read_bytes() == before, (v[:20], r)
        if kind == "unreadable":
            assert "has a format line this guard cannot read" in r.err, (v, r.err)
    assert [a["op"] for a in audit_lines(repo)] == []  # nothing was released


NEWER_OPTIONS = ("Options:", "shrink", "release --branch", "override --fingerprint", "可选处理", "缩小")


def test_a_newer_format_claim_denial_says_upgrade_only(repo, guard):
    put_claim(repo, "agent/a", NEWER)
    put_claim(repo, "agent/b", "state=active\nv=1\nbranch=agent/b\nentry=src/b.py\n")
    for lang, upgrade in (("en", "upgrade"), ("zh", "升级")):
        texts = []
        for args in (("plan", "--branch", "agent/a", "--paths", "docs/", "--amend"), ("plan", "--branch", "agent/b", "--paths", "src/b.py"),
                     ("check", "--branch", "agent/b", "--paths", "src/b.py")):
            r = run(["--repo", str(repo.path), "--lang", lang, *args])
            assert r.rc == 11, (lang, args, r)
            texts.append(r.out)
        body = payload("Bash", "git switch -c agent/b", repo.path)
        r = run(["--lang", lang, "hook", "claude", "pre-tool"], stdin=json.dumps(body).encode("utf-8"))
        texts.append(json.loads(r.out)["reason"])
        for text in texts:
            assert "agent/a" in text and "v=2" in text and upgrade in text, (lang, text)
            assert not [w for w in NEWER_OPTIONS if w in text], (lang, text)
    rc, v = verdict(guard, repo, "check", "--branch", "agent/n", "--paths", "web/")  # another unknown beside it keeps the options
    assert rc == 11 and v["message"].count("[CLAIM_NEWER_FORMAT]") == 1
    put_claim(repo, "broken", "garbage")
    rc, v = verdict(guard, repo, "check", "--branch", "agent/n", "--paths", "web/")
    assert rc == 11 and "Options:" in v["message"] and "[CLAIM_UNPARSEABLE]" in v["message"]


# ---- a claim stored under a name the Windows alias rule refuses (cr-15) ------------------------------------------------------
def test_a_stored_claim_under_a_refused_name_keeps_its_branch(repo, guard):
    repo.branch_with("agent/other", "src/a.py")  # an unmerged lane: the repository is engaged in AUTO
    assert guard(repo, "plan", "--branch", "agent/ok", "--paths", "web/").rc == 0
    assert "plan refuses" not in guard(repo, "doctor").out  # a name plan accepts is not reported
    g = G.open_repo(str(repo.path))
    stored = {}
    for name, entry in (("rel.claim", "docs/"), ("aux.claim", "README.md")):  # the second is also a Windows device name, which stays refused
        body = ["state=active", "branch=" + name, "worktree=", "target=main", "base=" + repo.git("rev-parse", "main"),  # no v= line: stored by 1.0.1
                "created=2026-01-01T00:00:00Z", "by=old", "override=", "entry=" + entry]
        path = Path(G.claim_path(g, name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("\n".join(body) + "\n").encode("utf-8"))
        stored[name] = path.read_bytes()
    assert denied(hook(repo, command="git switch -c rel.claim")) is None  # the claim of its own branch allows the creation
    assert denied(hook(repo, command="git worktree add ../w-rel -b rel.claim")) is None
    reason = denied(hook(repo, command="git switch -c aux.claim"))
    assert reason and "reserved device name" in reason, reason  # only the alias rule is skipped
    reason = denied(hook(repo, command="git switch -c other.claim"))  # no claim: planned like any other branch
    assert reason and "creating 'other.claim'" in reason and "a planned file manifest must be registered" in reason, reason
    for extra in ((), ("--amend",)):
        r = guard(repo, "plan", "--branch", "rel.claim", "--paths", "docs/", "src/", *extra)
        assert r.rc == 12 and "[BRANCH_NAME]" in r.out and "Windows alias rule" in r.out, (extra, r)
    assert guard(repo, "check", "--branch", "rel.claim", "--paths", "docs/").rc == 12
    assert Path(G.claim_path(g, "rel.claim")).read_bytes() == stored["rel.claim"]  # nothing was rewritten
    rows = {r["branch"]: r for r in json.loads(guard(repo, "list", "--json").out)}
    assert rows["rel.claim"]["state"] == "planned" and "Windows alias rule" in rows["rel.claim"]["refused_name"], rows["rel.claim"]
    assert "refused_name" not in rows["agent/ok"]
    shown = guard(repo, "list").out
    lines = {ln.split()[1]: ln for ln in shown.splitlines()}
    assert "(name refused by plan: " in lines["rel.claim"] and "Windows alias rule" in lines["rel.claim"] and "refused" not in lines["agent/ok"], shown
    doctor = [ln for ln in guard(repo, "doctor").out.splitlines() if "plan refuses" in ln]
    assert len(doctor) == 1 and "rel.claim" in doctor[0] and "aux.claim" in doctor[0] and "agent/ok" not in doctor[0], doctor
    assert guard(repo, "release", "--branch", "rel.claim").rc == 0  # the way out: release it and plan the lane under another name
    assert guard(repo, "plan", "--branch", "rel-claim", "--paths", "docs/").rc == 0
    assert denied(hook(repo, command="git switch -c rel.claim")) is not None


# ---- sets (1.0.4): the integration claim ----------------------------------------------------------------------------------------------
def set_spec_file(repo, tmp_path, name, lanes, base=None, tag=""):
    """The spec file of a set (outside every worktree): lanes are (id, branch, paths, depends_on)."""
    spec = {"v": 1, "title": name, "base": base or repo.git("rev-parse", "main"), "sheet": "sheet", "notes": [], "shared": [],
            "lanes": [{"id": lid, "title": "lane " + lid, "branch": branch, "worktree": P(tmp_path / "wt" / (name + "-" + lid.lower())), "paths": list(paths), "depends_on": list(deps),
                       "acceptance": "it works"} for lid, branch, paths, deps in lanes]}
    f = tmp_path / ("spec-%s%s.json" % (name, tag))
    f.write_text(json.dumps(spec), encoding="utf-8")
    return f


def register_set(guard, repo, tmp_path, name, lanes, tag=""):
    r = guard(repo, "set-plan", "--set", name, "--target", "main", "--spec", str(set_spec_file(repo, tmp_path, name, lanes, tag=tag)))
    assert r.rc == 0, r.out + r.err
    return r


DEMO_LANES = [("L1", "agent/demo/api", ["src/api/"], []), ("L2", "agent/demo/ui", ["src/ui/"], ["L1"]), ("L3", "agent/demo/docs", ["docs/"], [])]


def claim_text(base, branch, entries, extra=(), v=1):
    lines = ["state=active", "v=%d" % v, "branch=" + branch, "worktree=", "target=main", "base=" + base, "created=2026-01-01T00:00:00Z", "by=t", "override="]
    return "\n".join(lines + ["%s=%s" % kv for kv in extra] + ["entry=" + e for e in entries]) + "\n"


MARKER = ".magos/integration/demo/"
SHAPES = [  # label, branch, entries, extra keys, is it the integration claim set-plan writes?
    ("written by set-plan", "agent/demo/integration", [MARKER], [("set", "demo"), ("role", "integration")], True),
    ("upper case", "AGENT/DEMO/INTEGRATION", [MARKER.upper()], [("set", "DEMO"), ("role", "integration")], True),
    ("another entry", "agent/demo/integration", ["lib/"], [("set", "demo"), ("role", "integration")], False),
    ("a second entry", "agent/demo/integration", [MARKER, "lib/"], [("set", "demo"), ("role", "integration")], False),
    ("another branch", "agent/demo/late", [MARKER], [("set", "demo"), ("role", "integration")], False),
    ("another set", "agent/demo/integration", [MARKER], [("set", "other"), ("role", "integration")], False),
    ("no set", "agent/demo/integration", [MARKER], [("role", "integration")], False),
    ("role in another case", "agent/demo/integration", [MARKER], [("set", "demo"), ("role", "Integration")], False),
    ("role with a suffix", "agent/demo/integration", [MARKER], [("set", "demo"), ("role", "integration-x")], False),
    ("role twice", "agent/demo/integration", [MARKER], [("set", "demo"), ("role", "integration"), ("role", "integration")], False),
    ("set twice", "agent/demo/integration", [MARKER], [("set", "demo"), ("set", "demo"), ("role", "integration")], False),
    ("a lane of a set", "agent/demo/api", ["src/api/"], [("set", "demo"), ("lane", "L1")], False),
]


def test_integration_claim_is_recognised_by_its_shape_and_skipped_by_the_judgement(repo, guard, monkeypatch):
    base = repo.git("rev-parse", "main")
    docs = [(label, branch, G.parse_claim(claim_text(base, branch, entries, extra)), integration) for label, branch, entries, extra, integration in SHAPES]
    for label, branch, doc, integration in docs:
        assert G.is_integration_claim(doc) is integration, label
    assert G.integration_branch("demo") == "agent/demo/integration" and G.integration_entry("demo") == MARKER
    assert G.is_integration_claim(G.parse_claim(claim_text(base, "agent/demo/api", ["src/api/"]))) is False  # a claim of 1.0.3 has no extra key
    g = G.open_repo(str(repo.path))
    snap = G.gather(g)
    real_parse = G.parse_entry
    for label, branch, doc, integration in docs:  # with_declared leaves the integration claim out and keeps every other claim with its entries
        table, bad = G.with_declared([], {G.fold(branch): doc}, G.lane_key("agent/unrelated"), snap)
        if integration:
            assert table == [] and bad == [], label
        else:
            assert [(c["branch"], [e.raw for e in c["declared"]]) for c in table] == [(branch, doc["entries"])] and bad == [], label
    # an integration claim is never parsed: no CLAIM_UNPARSEABLE even where parsing would fail
    monkeypatch.setattr(G, "parse_entry", lambda raw: (_ for _ in ()).throw(G.ManifestError("BAD", "never parsed")) if raw == MARKER else real_parse(raw))
    table, bad = G.with_declared([], {G.fold("agent/demo/integration"): docs[0][2]}, G.lane_key("agent/x"), snap)
    assert table == [] and bad == []
    table, bad = G.with_declared([], {G.fold("agent/demo/integration"): docs[5][2]}, G.lane_key("agent/x"), snap)  # another set's claim is parsed
    assert table == [] and bad == ["agent/demo/integration"]
    monkeypatch.setattr(G, "parse_entry", real_parse)
    # check_creation: the integration claim is allowed for its claim and its name; every other shape is judged in full
    assert guard(repo, "plan", "--branch", "agent/other", "--paths", ".magos/", "lib/", "src/api/").rc == 0  # overlaps the marker and the entries of the claims below
    for label, branch, doc, integration in docs:
        path = put_claim(repo, branch, claim_text(base, branch, doc["entries"], doc["extra"]))
        v = G.check_creation(g, branch, {"path": None}, "en", "auto")
        if integration:
            assert v is None, (label, v)
        else:
            assert v and v["code"] == "CONFLICT" and "agent/other" in [c["branch"] for c in v["conflicts"]], (label, v)  # its entries conflict with an overlapping claimant
        path.unlink()
    calls = []
    real_core = G.plan_core
    monkeypatch.setattr(G, "plan_core", lambda *a, **k: calls.append(a[1]) or (_ for _ in ()).throw(AssertionError("judged")))
    for label, branch, doc, integration in docs[:2]:
        path = put_claim(repo, branch, claim_text(base, branch, doc["entries"], doc["extra"]))
        assert G.check_creation(g, branch, {"path": None}, "en", "armed") is None and calls == [], label  # nothing is gathered or evaluated
        path.unlink()
    monkeypatch.setattr(G, "plan_core", real_core)
    assert guard(repo, "release", "--branch", "agent/other").rc == 0
    bad_claim = put_claim(repo, "zz-unreadable", "garbage")  # an unreadable claim elsewhere
    uncertain = lambda *a, **k: (_ for _ in ()).throw(G.Uncertain("integration target is ambiguous"))
    for label, branch, doc, integration in (docs[0], docs[2], docs[4]):
        path = put_claim(repo, branch, claim_text(base, branch, doc["entries"], doc["extra"]))
        v = G.check_creation(g, branch, {"path": None}, "en", "armed")
        if integration:
            assert v is None, label
        else:
            assert v and v["code"] == "UNKNOWN" and v["unknowns"][0]["code"] == "CLAIM_UNPARSEABLE", (label, v)
        with monkeypatch.context() as m:  # an uncertain target
            m.setattr(G, "gather", uncertain)
            v = G.check_creation(g, branch, {"path": None}, "en", "armed")
            assert (v is None) if integration else (v and v["code"] == "UNKNOWN"), (label, v)
        path.unlink()
    bad_claim.unlink()


def test_the_integration_claim_is_never_a_claimant(repo, guard, tmp_path):
    register_set(guard, repo, tmp_path, "demo", DEMO_LANES)
    assert "role=integration" in (claims_dir(repo) / "agent" / "demo" / "integration.claim").read_text(encoding="utf-8")
    r = guard(repo, "--json", "plan", "--branch", "tool/a", "--paths", ".magos/")  # the marker lies under .magos/
    v = json.loads(r.out)
    assert r.rc == 0 and v["conflicts"] == [] and "agent/demo/integration" not in r.out, r
    cwd = str(repo.path)
    assert G.decide({"tool_name": "Bash", "tool_input": {"command": "git switch -c tool/a"}, "cwd": cwd}, "en") is None  # its creation is allowed
    # another set whose lane owns .magos/**
    other = Repo(tmp_path / "other")
    other.path.mkdir()
    other.git("init", "-q")
    other.commit("README.md", "x\n")
    register_set(guard, other, tmp_path, "demo", [("L1", "agent/demo/api", ["src/api/"], [])])
    register_set(guard, other, tmp_path, "second", [("L1", "agent/second/magos", [".magos/**"], [])], tag="x")
    # the integration branch holds a merged lane commit and a commit of its own that touches CHANGELOG.md
    third = Repo(tmp_path / "third")
    third.path.mkdir()
    third.git("init", "-q")
    for rel in ("src/api/a.py", "README.md"):
        third.write(rel, "base\n")
    third.git("add", "-A")
    third.git("commit", "-q", "-m", "init")
    lanes = [("L1", "agent/demo/api", ["src/api/"], []), ("L2", "agent/demo/ui", ["src/ui/"], [])]
    register_set(guard, third, tmp_path, "demo", lanes, tag="t")
    wt = tmp_path / "wt" / "demo-l1"
    third.git("worktree", "add", "-q", "-b", "agent/demo/api", str(wt), "main")
    third.commit("src/api/b.py", "b\n", cwd=wt, msg="lane work")
    third.git("switch", "-q", "-c", "agent/demo/integration")
    third.git("merge", "-q", "--no-ff", "-m", "merge L1", "agent/demo/api")
    third.commit("CHANGELOG.md", "changes\n", msg="the integration branch's own commit")
    third.git("switch", "-q", "main")
    more = lanes + [("L4", "agent/demo/extra", ["CHANGELOG.md"], [])]
    spec = set_spec_file(third, tmp_path, "demo", more, tag="amend")
    amended = guard(third, "set-plan", "--set", "demo", "--target", "main", "--spec", str(spec), "--amend", "--expect-revision", "1")
    assert amended.rc == 0, amended.out + amended.err  # the integration branch is a member of the set in the snapshot of set-plan
    d = json.loads(guard(third, "--json", "plan", "--branch", "tool/d", "--paths", "CHANGELOG.md").out)
    assert d["code"] == "CONFLICT" and {c["branch"] for c in d["conflicts"]} == {"agent/demo/extra", "agent/demo/integration"}
    kinds = {c["branch"]: [e["kind"] for e in c["evidence"]] for c in d["conflicts"]}
    assert kinds["agent/demo/extra"] == ["declared"] and kinds["agent/demo/integration"] == ["committed"]  # the claim of the integration branch adds nothing
    e = json.loads(guard(third, "--json", "plan", "--branch", "tool/e", "--paths", "src/api/").out)
    assert e["code"] == "CONFLICT" and {"agent/demo/api", "agent/demo/integration"} <= {c["branch"] for c in e["conflicts"]}
    assert all(c["evidence"] and not (c["branch"] == "agent/demo/integration" and "declared" in [x["kind"] for x in c["evidence"]]) for c in e["conflicts"])


def test_the_integration_creation_still_needs_its_claim_and_a_valid_name(repo, guard, tmp_path):
    register_set(guard, repo, tmp_path, "demo", DEMO_LANES)
    g = G.open_repo(str(repo.path))
    name = "agent/demo/integration"
    claim = claims_dir(repo) / "agent" / "demo" / "integration.claim"
    text = claim.read_text(encoding="utf-8")

    def judged():
        return G.check_creation(g, name, {"path": None}, "en", "armed")
    assert judged() is None  # the claim exists and the name is valid
    claim.unlink()
    assert judged()["code"] == "NO_MANIFEST"  # without a claim
    claim.write_text(text.replace("v=1", "v=2", 1), encoding="utf-8")
    v = judged()
    assert v["code"] == "UNKNOWN" and v["unknowns"][0]["code"] == "CLAIM_NEWER_FORMAT" and name in v["unknowns"][0]["text"] and "upgrade this guard" in v["unknowns"][0]["text"]
    claim.write_text(text, encoding="utf-8")
    repo.git("update-ref", "refs/heads/agent/demo/integration/x", "HEAD")  # a ref that would be a directory of the branch name
    v = judged()
    assert v["code"] == "INVALID_MANIFEST" and "[BRANCH_NAME]" in v["message"] and "agent/demo/integration/x" in v["message"]
    repo.git("update-ref", "-d", "refs/heads/agent/demo/integration/x")
    assert judged() is None
    other = G.check_creation(g, "agent/demo/late", {"path": None}, "en", "armed")
    assert other["code"] == "NO_MANIFEST"  # a branch that has no claim is still denied


# ---- sets (1.0.4): claims with set keys, list and doctor -----------------------------------------------------------------------------------
def edit_set(repo, fn, name="demo"):
    """The record of a set, changed by `fn` and written back in the format of the guard."""
    path = common(repo) / "magos" / "sets" / (name + ".json")
    rec = json.loads(path.read_text(encoding="utf-8"))
    fn(rec)
    path.write_bytes(G.record_bytes(rec))
    return rec


def test_claims_with_set_keys_round_trip_and_old_claims_stay_readable(repo, guard, tmp_path):
    g = G.open_repo(str(repo.path))
    base = repo.git("rev-parse", "main")
    plain = claim_text(base, "agent/old", ["src/"])  # a claim as 1.0.3 writes it: no key of a set
    doc = G.parse_claim(plain)
    assert doc["extra"] == [] and G.claim_set(doc) is None and not G.is_integration_claim(doc) and G.claim_bytes(g, "agent/old", doc)[1].decode("utf-8") == plain
    shapes = [("agent/demo/api", ["src/api/"], [("set", "demo"), ("lane", "L1")]), ("agent/demo/integration", [MARKER], [("set", "demo"), ("role", "integration")]),
              ("agent/rep/x", ["web/"], [("set", "a"), ("set", "b"), ("lane", "L1")])]  # a repeated line is kept as well
    for branch, entries, extra in shapes:
        text = claim_text(base, branch, entries, extra)
        doc = G.parse_claim(text)
        assert doc["extra"] == extra and doc["v"] == 1 and "set" not in G.CLAIM_KEYS and "lane" not in G.CLAIM_KEYS and "role" not in G.CLAIM_KEYS
        assert G.claim_bytes(g, branch, doc)[1].decode("utf-8") == text  # written back unchanged and in order
        assert text.split("\n")[0] == "state=active"  # line 1 is what the git layer reads
    assert G.claim_set(G.parse_claim(claim_text(base, "agent/rep/x", ["web/"], shapes[2][2]))) == "a"  # the first line names the set
    for key, value in (("set", "de\x01mo"), ("lane", "L\x001")):  # a control character is refused by the writer
        bad = G.parse_claim(claim_text(base, "agent/demo/api", ["src/api/"], [("set", "demo")]))
        bad["extra"] = [(key, value)]
        with pytest.raises(G.ClaimRefused):
            G.claim_bytes(g, "agent/demo/api", bad)
    # plan --amend of such a claim (its set has no record) keeps the keys, in order, with line 1 as it was
    orphan = claims_dir(repo) / "agent" / "orphan.claim"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(claim_text(base, "agent/orphan", ["web/"], [("set", "ghost"), ("lane", "L1")]).encode("utf-8"))
    assert guard(repo, "plan", "--branch", "agent/orphan", "--paths", "web/", "docs/", "--amend").rc == 0
    lines = orphan.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "state=active" and lines[9:11] == ["set=ghost", "lane=L1"] and lines[11:] == ["entry=web/", "entry=docs/", ""]
    # the rows of list: a plain claim has neither field, the claims with set keys have them
    assert guard(repo, "plan", "--branch", "agent/plain", "--paths", "tools/").rc == 0
    rows = {r["branch"]: r for r in json.loads(guard(repo, "list", "--json").out)}
    assert "set" not in rows["agent/plain"] and "lane" not in rows["agent/plain"] and "role" not in rows["agent/plain"]
    assert (rows["agent/orphan"]["set"], rows["agent/orphan"]["lane"]) == ("ghost", "L1") and "role" not in rows["agent/orphan"]
    # the git layer reads line 1 only: a claim with set keys allows its branch, an unclaimed branch is vetoed
    assert guard(repo, "arm").rc == 0
    orphan.write_bytes(claim_text(base, "agent/orphan", ["web/"], [("set", "ghost"), ("lane", "L1"), ("role", "integration")]).encode("utf-8"))
    repo.git("branch", "agent/orphan", "main")
    refused = subprocess.run(["git", "branch", "agent/unclaimed", "main"], cwd=str(repo.path), capture_output=True, env=os.environ.copy())
    assert refused.returncode != 0 and "MAGOS" in refused.stderr.decode("utf-8", "replace")
    assert "agent/orphan" in repo.git("branch", "--list", "agent/orphan") and not repo.git("branch", "--list", "agent/unclaimed")


def test_list_shows_the_set_and_lane_of_a_claim(repo, guard, tmp_path):
    register_set(guard, repo, tmp_path, "demo", DEMO_LANES)
    wt = tmp_path / "wt" / "demo-l1"
    repo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(wt), "main")
    repo.commit("src/api/b.py", "b\n", cwd=wt, msg="lane work")
    repo.commit("web/outside.txt", "o\n", cwd=wt, msg="a file outside the manifest")
    repo.git("switch", "-q", "-c", "agent/demo/integration")  # the integration branch holds the merged lane commits
    repo.git("merge", "-q", "--no-ff", "-m", "merge L1", "agent/demo/api")
    repo.git("switch", "-q", "main")
    assert guard(repo, "plan", "--branch", "tool/plain", "--paths", "tools/").rc == 0
    register_set(guard, repo, tmp_path, "ghost", [("L1", "agent/ghost/a", ["ghost/"], [])], tag="g")
    (common(repo) / "magos" / "sets" / "ghost.json").unlink()  # a set claim whose record is gone
    odd = claims_dir(repo) / "agent" / "odd"
    odd.mkdir(parents=True, exist_ok=True)
    base = repo.git("rev-parse", "main")
    (odd / "twice.claim").write_bytes(claim_text(base, "agent/odd/twice", ["odd1/"], [("set", "first"), ("set", "second"), ("lane", "L9")]).encode("utf-8"))
    (odd / "other.claim").write_bytes(claim_text(base, "agent/odd/other", ["odd2/"], [("set", "other"), ("role", "integration")]).encode("utf-8"))  # not the marker entry
    rows = {r["branch"]: r for r in json.loads(guard(repo, "--json", "list").out)}
    assert not {"set", "lane", "role"} & set(rows["tool/plain"])  # a plain claim has none of the fields
    assert (rows["agent/demo/api"]["set"], rows["agent/demo/api"]["lane"], "role" in rows["agent/demo/api"]) == ("demo", "L1", False)
    assert (rows["agent/demo/ui"]["set"], rows["agent/demo/ui"]["lane"]) == ("demo", "L2") and rows["agent/demo/ui"]["state"] == "planned"
    integration = rows["agent/demo/integration"]
    assert (integration["set"], integration["lane"], integration["role"], integration["state"]) == ("demo", None, "integration", "active")  # unmerged work: active
    assert (rows["agent/ghost/a"]["set"], rows["agent/ghost/a"]["lane"]) == ("ghost", "L1")  # an orphan set claim still shows its set
    assert (rows["agent/odd/twice"]["set"], rows["agent/odd/twice"]["lane"]) == ("first", "L9")  # the first line names the set
    assert rows["agent/odd/other"]["set"] == "other" and "lane" not in rows["agent/odd/other"] and "role" not in rows["agent/odd/other"]  # role=integration in another shape
    zh = run(["--repo", str(repo.path), "--lang", "zh", "list"])
    text = zh.out.splitlines()
    assert zh.rc == 0 and text == guard(repo, "list").out.splitlines()  # the listing is not translated
    assert "active   set demo/L1 agent/demo/api  [src/api/]" in text and "planned  set demo/L2 agent/demo/ui  [src/ui/]" in text
    assert "active   set demo/integration agent/demo/integration  [.magos/integration/demo/]" in text
    assert "planned  set other agent/odd/other  [odd2/]" in text and "planned  set ghost/L1 agent/ghost/a  [ghost/]" in text and "planned  set first/L9 agent/odd/twice  [odd1/]" in text
    assert "planned  tool/plain  [tools/]" in text  # a plain claim is listed as before
    # --drift reports the lanes as before and skips the integration claim, whose branch holds files that its marker entry does not match
    drift = {r["branch"]: r["drift"] for r in json.loads(guard(repo, "--json", "list", "--drift").out)}
    assert drift["agent/demo/api"] == ["web/outside.txt"] and drift["agent/demo/integration"] == [] and drift["agent/demo/ui"] == []
    shown = guard(repo, "list", "--drift").out
    assert "drift: web/outside.txt" in [ln for ln in shown.splitlines() if "agent/demo/api" in ln][0]
    assert "drift:" not in [ln for ln in shown.splitlines() if "agent/demo/integration" in ln][0]


def test_doctor_reports_set_problems(repo, guard, tmp_path):
    out = guard(repo, "doctor")
    assert out.rc == 0 and "sets:" not in out.out and "set demo" not in out.out  # a repository without sets prints no line about sets
    register_set(guard, repo, tmp_path, "demo", DEMO_LANES)
    claims = claims_dir(repo) / "agent" / "demo"
    out = guard(repo, "doctor")
    assert out.rc == 0 and "sets: 1, unreadable: 0, newer-format: 0" in out.out and "claims without a branch or planned worktree: none" in out.out  # the integration claim is no orphan
    assert "without a record" not in out.out
    for name, edit, line in (("docs", None, "  set demo lane L3: claim missing"), ("ui", lambda t: t.replace("entry=src/ui/", "entry=lib/"), "  set demo lane L2: claim differs"),
                             ("api", lambda t: t.replace("set=demo", "set=other"), "  set demo lane L1: claim differs"), ("api", lambda t: t.replace("lane=L1\n", ""), "  set demo lane L1: claim differs")):
        path = claims / (name + ".claim")
        good = path.read_text(encoding="utf-8")
        if edit is None:
            path.unlink()
        else:
            path.write_text(edit(good), encoding="utf-8")
        out = guard(repo, "doctor")
        assert out.rc == 1 and line in out.out.splitlines() and "sets: 1, unreadable: 0, newer-format: 0" in out.out, (name, out.out)
        path.write_text(good, encoding="utf-8")
    assert guard(repo, "doctor").rc == 0
    # a lane in state active or ready whose branch is gone is a problem; planned, integrated and blocked lanes without a branch are not
    def states(rec):
        for lane, state in zip(rec["lanes"], ("active", "ready", "planned")):
            lane["state"] = state
    edit_set(repo, states)
    out = guard(repo, "doctor")
    assert out.rc == 1 and "  set demo lane L1: branch vanished" in out.out.splitlines() and "  set demo lane L2: branch vanished" in out.out.splitlines() and "L3: branch vanished" not in out.out
    edit_set(repo, lambda rec: [lane.update(state=s) for lane, s in zip(rec["lanes"], ("planned", "integrated", "blocked"))])
    assert guard(repo, "doctor").rc == 0
    # claims of a set that has no record, a newer-format record, an unreadable one, and a temporary file
    register_set(guard, repo, tmp_path, "ghost", [("L1", "agent/ghost/a", ["ghost/"], [])], tag="g")
    (common(repo) / "magos" / "sets" / "ghost.json").unlink()
    sets = common(repo) / "magos" / "sets"
    (sets / "newer.json").write_bytes(b'{"v": 3}')
    (sets / "broken.json").write_bytes(b"{")
    (sets / "demo.json.tmp").write_bytes(b"garbage")
    out = guard(repo, "doctor")
    lines = out.out.splitlines()
    assert out.rc == 1 and "sets: 1, unreadable: 1, newer-format: 1" in lines
    assert "  claims of set ghost without a record: agent/ghost/a, agent/ghost/integration" in lines
    assert any(ln.startswith("  set record sets/newer.json was written by a newer MAGOS (v=3)") and "upgrade this guard" in ln for ln in lines)
    assert "  unreadable set record sets/broken.json" in lines
    assert "claims without a branch or planned worktree: agent/ghost/integration" in lines  # no record: the integration claim is an orphan too
    for name in ("newer.json", "broken.json", "demo.json.tmp"):
        (sets / name).unlink()
    assert guard(repo, "release", "--branch", "agent/ghost/a").rc == 0 and guard(repo, "release", "--branch", "agent/ghost/integration").rc == 0  # release --branch frees them
    assert guard(repo, "doctor").rc == 0
    # the target branch is gone
    repo.git("switch", "-q", "-c", "scratch")
    repo.git("branch", "-q", "-D", "main")
    out = guard(repo, "doctor")
    assert out.rc == 1 and "  set demo: the target branch main no longer exists" in out.out.splitlines()
