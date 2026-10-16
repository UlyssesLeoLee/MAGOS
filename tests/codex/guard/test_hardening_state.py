"""1.0.2 claim store, git layer, version and upgrade state: canonical release, Windows alias names, control characters, the key whitelist,
the name check under the lock, the claim format gate, doctor's self-test and copy check, arm's recorded settings and guard command,
version, the version-aware installer, the Hermes plugin launcher, the corrected deny messages and the absolute state paths."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from conftest import G, ROOT, SCRIPT, run
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
                 "state=active\nv=0\nbranch=x\nentry=a\n", "state=active\nbranch=x\nworktree=a\nworktree=b\nentry=a\n", "state=active\nbranch=x\n"):
        with pytest.raises(ValueError):
            G.parse_claim(text)
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
    hook_path(repo).write_text(hook_path(repo).read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8", newline="\n")
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


def test_install_is_version_aware_and_atomic(repo, guard, tmp_path):
    home = tmp_path / "h"
    script, launcher, record = home / "guard" / "scripts" / "magos_guard.py", home / "guard" / "hooks" / "run-guard.cmd", home / "guard" / "VERSION.json"
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0 and "guard copy none -> %s" % G.GUARD_VERSION in r.out and "did copy" in r.out
    assert script.read_bytes() == SCRIPT.read_bytes() and launcher.read_bytes() == LAUNCHER.read_bytes()
    rec = json.loads(record.read_text(encoding="utf-8"))
    assert set(rec) == {"version", "sha256", "source", "installed_at"} and rec["version"] == G.GUARD_VERSION
    assert rec["sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest() and os.path.samefile(rec["source"], str(SCRIPT))
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec["installed_at"]) and no_tmp(home)
    stamps = {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in (script, launcher, record)}
    for host in ("codex", "hermes"):
        r = guard(repo, "install", "--host", host, "--home", str(home))
        assert r.rc == 0 and "guard copy unchanged (%s)" % G.GUARD_VERSION in r.out and "did copy" not in r.out
        assert {p: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for p in stamps} == stamps
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
    script.parent.mkdir(parents=True)
    older = with_version(SCRIPT.read_bytes(), "1.0.0")
    script.write_bytes(older)
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
    assert script.read_bytes() == older and record.read_bytes() == before and no_tmp(home / "guard")
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
