"""1.0.4 sets: `set-plan` (the spec, the record, the lane claims and the integration claim, the registration under the claim lock), `set-update`
(the transitions of a lane and the conditions of ready and integrated), `set-show` (the record and the view derived from the repository, with the
drift), `set-release` (the gates and the removal of the claims), the plain `plan` and `release` refusing the claims of a set, the exit codes and
messages of all four, and the cost of a twelve-lane registration and of the drift view."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

import pytest

from conftest import G, ROOT, SCRIPT, Repo, run as _run, time_budget

COMMON_KEYS = {"decision", "code", "message", "exit_code"}
OK_KEYS = COMMON_KEYS | {"set", "target", "base", "revision", "dry_run", "unchanged", "integration_branch", "order", "lanes", "written", "warnings"}
BASE_FILES = ("src/api/a.py", "src/ui/u.py", "tests/api/t.py", "docs/d.md", "docs/readme.md", "README.md", "package-lock.json")


def P(path):
    return str(path).replace("\\", "/")


def crashed(text):
    """A git child killed by a Windows NTSTATUS (0xC0000000 and up, e.g. STATUS_DLL_INIT_FAILED when the machine runs low on virtual memory) or
    that ran out of memory: the environment failed, not the guard.  Seen as `exit code N` or `Out of memory` in a Git failure of the guard."""
    return "Out of memory" in text or any(int(n) >= 0xC0000000 for n in re.findall(r"exit code (\d+)", text))


def run(args, stdin=b"", cwd=None):
    """conftest.run again when a git child of the guard was killed by the machine (a call that fails that way has written nothing)."""
    for _ in range(4):
        r = _run(args, stdin=stdin, cwd=cwd)
        if not crashed(r.out + r.err):
            break
    return r


@pytest.fixture
def guard(guard):
    def call(repo, *args, stdin=b""):
        for _ in range(4):
            r = guard(repo, *args, stdin=stdin)
            if not crashed(r.out + r.err):
                break
        return r
    return call


class SetsRepo(Repo):
    """A repository whose git calls are repeated when the machine killed the child before it did anything (no message on stderr)."""

    def git(self, *args, **kw):
        for attempt in range(4):
            try:
                return super().git(*args, **kw)
            except AssertionError as err:
                if attempt == 3 or not (str(err).rstrip().endswith("failed:") or "Out of memory" in str(err)):
                    raise
                time.sleep(1)


def sub(cmd, check=True, **kw):
    """subprocess.run of a git command, repeated when the machine killed the child (an exit code of 0xC0000000 and up)."""
    for attempt in range(4):
        p = subprocess.run(cmd, **kw)
        if p.returncode < 0xC0000000 or attempt == 3:
            break
        time.sleep(0.5)
    if check and p.returncode:
        raise AssertionError("%s failed: %s" % (" ".join(cmd[:3]), p.stderr.decode("utf-8", "replace") if p.stderr else ""))
    return p


def make_repo(tmp_path, name="repo", files=BASE_FILES):
    r = SetsRepo(tmp_path / name)
    r.path.mkdir()
    r.git("init", "-q")
    for rel in files:
        r.write(rel, "base\n")
    r.git("add", "-A")
    r.git("commit", "-q", "-m", "init")
    return r


@pytest.fixture
def demo(tmp_path):
    """The repository of the demo set: main holds the files the demo lanes own."""
    return make_repo(tmp_path)


def wt_path(tmp_path, name):
    return P(tmp_path / "wt" / name)


def lane(tmp_path, lid, branch, paths, deps=(), **over):
    d = {"id": lid, "title": "lane " + lid, "branch": branch, "worktree": wt_path(tmp_path, lid.lower()), "paths": list(paths), "depends_on": list(deps),
         "acceptance": "it works"}
    d.update(over)
    return d


def demo_spec(repo, tmp_path, base=None, **over):
    """The demo spec of TC-253: L1 owns the api (and the shared lock file), L2 the ui (after L1), L3 the docs."""
    spec = {"v": 1, "title": "Demo", "base": base or repo.git("rev-parse", "main"), "sheet": "# Plan demo -> main  rev 1\n- [ ] L1 api\n- [ ] L2 ui\n",
            "notes": ["note one"], "shared": [{"path": "package-lock.json", "owner": "L1"}],
            "lanes": [lane(tmp_path, "L1", "agent/demo/api", ["src/api/", "tests/api/", "package-lock.json"]),
                      lane(tmp_path, "L2", "agent/demo/ui", ["src/ui/"], ["L1"]),
                      lane(tmp_path, "L3", "agent/demo/docs", ["docs/"])]}
    spec.update(over)
    return spec


def write_spec(tmp_path, spec, name="spec.json"):
    """The spec file outside every worktree (a dict is written as JSON, bytes and str as they are)."""
    p = tmp_path / "specs" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(spec if isinstance(spec, bytes) else spec.encode("utf-8") if isinstance(spec, str) else json.dumps(spec).encode("utf-8"))
    return p


def sp_args(spec_file, name="demo", target="main", *extra):
    return ["set-plan", "--set", name, "--target", target, "--spec", str(spec_file), *extra]


def jplan(guard, repo, spec_file, *extra, name="demo", target="main", stdin=b""):
    """-> (exit code, the JSON result) of `--json set-plan`."""
    r = guard(repo, "--json", *sp_args(spec_file, name, target, *extra), stdin=stdin)
    try:
        return r.rc, json.loads(r.out)
    except ValueError:
        raise AssertionError("no JSON result (exit %s); stdout %r; stderr %r" % (r.rc, r.out, r.err)) from None


def plan_ok(guard, repo, spec_file, *extra, **kw):
    rc, v = jplan(guard, repo, spec_file, *extra, **kw)
    assert rc == 0, v
    return v


def dry(guard, repo, tmp_path, spec, name="dry.json", *extra):
    """-> (exit code, JSON result) of `--json set-plan --dry-run` of a spec (a dict, text or bytes)."""
    return jplan(guard, repo, write_spec(tmp_path, spec, name), "--dry-run", *extra)


def common_dir(repo):
    return Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir"))


def store_dir(repo):
    return common_dir(repo) / "magos"


def store_files(repo, skip=("lock",)):
    """{relative path: bytes} of every file of the store (the lock file aside), and the set of its directories."""
    root = store_dir(repo)
    if not root.exists():
        return None
    return {P(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and p.name not in skip}


def store_tree(repo):
    root = store_dir(repo)
    return None if not root.exists() else sorted(P(p.relative_to(root)) for p in root.rglob("*") if p.name != "lock")


def claim_lines(repo, branch):
    return (store_dir(repo) / "claims" / (branch.replace("/", os.sep) + ".claim")).read_text(encoding="utf-8").split("\n")


def record(repo, name="demo"):
    return json.loads((store_dir(repo) / "sets" / (name + ".json")).read_text(encoding="utf-8"))


def write_record(repo, rec, name="demo"):
    p = store_dir(repo) / "sets" / (name + ".json")
    p.write_bytes((json.dumps(rec, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def edit_record(repo, fn, name="demo"):
    rec = record(repo, name)
    fn(rec)
    write_record(repo, rec, name)
    return rec


def lane_of(rec, lid):
    return next(x for x in rec["lanes"] if x["id"] == lid)


def audit_lines(repo):
    p = store_dir(repo) / "audit.log"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def branches(repo):
    return sorted(repo.git("branch", "--list", "--format=%(refname:short)").split())


def errors_of(v):
    return {(e["field"], e["code"]) for e in v["errors"]}


def freeze_clock(monkeypatch, start=1):
    """Every call of now_iso gives a later second, so `updated` differs from `created` whatever the speed of the machine."""
    ticks = [start]

    def tick():
        ticks[0] += 1
        return "2026-01-01T00:00:%02dZ" % (ticks[0] % 60)
    monkeypatch.setattr(G, "now_iso", tick)


def holding_lock(repo):
    """A started thread that holds the claim lock until `release()` is called: -> release function."""
    g = G.open_repo(str(repo.path))
    started, done = threading.Event(), threading.Event()

    def hold():
        with G.Lock(g):
            started.set()
            done.wait(60)
    t = threading.Thread(target=hold)
    t.start()
    assert started.wait(10)

    def release():
        done.set()
        t.join()
    return release


def spawn(repo, *args):
    """The guard in a process of its own (`--json`): -> Popen."""
    return subprocess.Popen([sys.executable, str(SCRIPT), "--repo", str(repo.path), "--lang", "en", "--json", *args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy())


def finished(proc):
    out, err = proc.communicate(timeout=180)
    return proc.returncode, out.decode("utf-8"), err.decode("utf-8", "replace")


def branch_at(repo, name, files=None):
    """A local branch `name` ahead of main by one commit that adds `files` (plumbing only: no worktree, no checkout)."""
    files = files or {name.replace("/", "_") + ".txt": "x\n"}
    idx = repo.path.parent / ("idx-" + name.replace("/", "-"))
    env = dict(os.environ, GIT_INDEX_FILE=str(idx))
    sub(["git", "read-tree", "main"], cwd=str(repo.path), env=env, capture_output=True)
    for rel, text in files.items():
        blob = sub(["git", "hash-object", "-w", "--stdin"], cwd=str(repo.path), input=text.encode("utf-8"), capture_output=True).stdout.decode().strip()
        sub(["git", "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, rel)], cwd=str(repo.path), env=env, capture_output=True)
    tree = sub(["git", "write-tree"], cwd=str(repo.path), env=env, capture_output=True).stdout.decode().strip()
    commit = repo.git("commit-tree", tree, "-p", "main", "-m", name)
    repo.git("update-ref", "refs/heads/" + name, commit)
    idx.unlink()
    return commit


# ---- TC-253 .. TC-260: registration -------------------------------------------------------------------------------------
def test_set_plan_registers_every_claim_and_the_record(demo, guard, tmp_path):
    spec = demo_spec(demo, tmp_path)
    base = spec["base"]
    rc, v = jplan(guard, demo, write_spec(tmp_path, spec))
    assert rc == 0 and v["code"] == "OK" and v["decision"] == "allow" and v["exit_code"] == 0
    assert set(v) == OK_KEYS and v["set"] == "demo" and v["revision"] == 1 and v["dry_run"] is False and v["unchanged"] is False
    assert v["target"] == {"name": "main", "sha": base} and v["base"] == base and v["integration_branch"] == "agent/demo/integration"
    assert v["order"] == ["L1", "L2", "L3"]
    for ln, want in zip(v["lanes"], spec["lanes"]):
        assert ln["id"] == want["id"] and ln["branch"] == want["branch"] and ln["worktree"] == want["worktree"] and ln["entries"] == want["paths"] and ln["state"] == "planned"
        assert ln["create"] == 'git worktree add "%s" -b %s main' % (want["worktree"], want["branch"])
    assert sorted(P(p) for p in v["written"]) == sorted(P(store_dir(demo) / x) for x in (
        "claims/agent/demo/api.claim", "claims/agent/demo/ui.claim", "claims/agent/demo/docs.claim", "claims/agent/demo/integration.claim", "sets/demo.json"))
    for want in spec["lanes"]:
        lines = claim_lines(demo, want["branch"])
        head = lines[:9]
        assert head[:2] == ["state=active", "v=1"] and head[2:5] == ["branch=" + want["branch"], "worktree=" + want["worktree"], "target=main"]
        assert lines[5] == "base=" + base and lines[8] == "override=" and lines[9:11] == ["set=demo", "lane=" + want["id"]]
        assert lines[11:] == ["entry=" + e for e in want["paths"]] + [""]
    il = claim_lines(demo, "agent/demo/integration")
    assert il[:5] == ["state=active", "v=1", "branch=agent/demo/integration", "worktree=", "target=main"] and il[5] == "base=" + base
    assert il[8:] == ["override=", "set=demo", "role=integration", "entry=.magos/integration/demo/", ""] and not any(x.startswith("lane=") for x in il)
    rec = record(demo)
    assert list(rec) == list(G.RECORD_KEYS) and rec["v"] == 1 and rec["revision"] == 1 and rec["set"] == "demo" and rec["target"] == "main" and rec["base"] == base
    assert rec["created"] == rec["updated"] and rec["integration"] is None and rec["title"] == "Demo" and rec["sheet"] == spec["sheet"] and rec["notes"] == ["note one"]
    assert rec["shared"] == [{"path": "package-lock.json", "owner": "L1"}] and [x["id"] for x in rec["lanes"]] == ["L1", "L2", "L3"]
    for x in rec["lanes"]:
        assert x["state"] == "planned" and x["head"] is None and x["note"] == "" and list(x) == list(G.RECORD_LANE_KEYS)
    assert lane_of(rec, "L2")["depends_on"] == ["L1"]
    audit = audit_lines(demo)
    assert len(audit) == 1 and audit[0]["op"] == "set-plan" and audit[0]["set"] == "demo" and audit[0]["revision"] == 1 and audit[0]["integration"] == "agent/demo/integration"
    assert branches(demo) == ["main"] and demo.git("worktree", "list", "--porcelain").count("worktree ") == 1  # nothing was created
    assert not [p for p in store_dir(demo).rglob("*.tmp")]
    listed = guard(demo, "list")
    assert listed.rc == 0 and "agent/demo/api" in listed.out and "agent/demo/integration" in listed.out
    assert guard(demo, "doctor").rc == 0


def test_a_failed_write_leaves_no_partial_state(demo, guard, tmp_path, monkeypatch):
    spec_file = write_spec(tmp_path, demo_spec(demo, tmp_path))
    real = G._replace
    for k in range(1, 6):  # three lane claims, the integration claim, the record
        calls, moved = [], []

        def fake(tmp, path, tries=40, k=k, calls=calls, moved=moved):
            calls.append(path)
            if len(calls) == k:
                raise OSError("injected failure %d" % k)
            moved.append(path)
            return real(tmp, path, tries)
        monkeypatch.setattr(G, "_replace", fake)
        r = guard(demo, "--json", *sp_args(spec_file))
        out = json.loads(r.out)
        assert r.rc == 11 and out["unknowns"][0]["code"] == "INTERNAL_ERROR" and "injected failure %d" % k in r.err, (k, r)
        assert store_tree(demo) in (None, []) and audit_lines(demo) == [], (k, store_tree(demo))  # no claim, no record, no temporary file, no directory
        monkeypatch.setattr(G, "_replace", real)
    calls_all = []

    def counting(tmp, path, tries=40):
        calls_all.append(path)
        return real(tmp, path, tries)
    monkeypatch.setattr(G, "_replace", counting)
    plan_ok(guard, demo, spec_file)
    assert calls_all[-1].endswith("demo.json") and len(calls_all) == 5  # the record is the last file moved
    monkeypatch.setattr(G, "_replace", real)
    # an amend that rewrites the claims of L1 and L2 and deletes that of L3
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][0]["paths"] = ["src/api/", "tests/api/", "package-lock.json", "api-docs/"]
    amend["lanes"][1]["paths"] = ["src/ui/", "ui-docs/"]
    del amend["lanes"][2]
    amend_file = write_spec(tmp_path, amend, "amend.json")
    before = store_files(demo)
    l3 = str(store_dir(demo) / "claims" / "agent" / "demo" / "docs.claim")
    for k in range(1, 4):  # the claims of L1 and L2, then the record
        calls = []

        def fake(tmp, path, tries=40, k=k, calls=calls):
            calls.append(path)
            if len(calls) == k:
                raise OSError("injected failure %d" % k)
            return real(tmp, path, tries)
        monkeypatch.setattr(G, "_replace", fake)
        r = guard(demo, *sp_args(amend_file, "demo", "main", "--amend", "--expect-revision", "1"))
        assert r.rc == 11 and "injected failure %d" % k in r.err and store_files(demo) == before, (k, r)
        monkeypatch.setattr(G, "_replace", real)
    real_remove = os.remove

    def no_remove(path, *a, **kw):
        if P(path).lower() == P(l3).lower():
            raise PermissionError("injected: the claim of L3 is busy")
        return real_remove(path, *a, **kw)
    monkeypatch.setattr(G.os, "remove", no_remove)
    r = guard(demo, *sp_args(amend_file, "demo", "main", "--amend", "--expect-revision", "1"))
    assert r.rc == 11 and "L3 is busy" in r.err and store_files(demo) == before  # the writes were undone as well
    monkeypatch.setattr(G.os, "remove", real_remove)
    # the undo itself fails: the message names the files that could not be put back
    calls = []

    def fake(tmp, path, tries=40):
        calls.append(path)
        if len(calls) in (3, 4):  # the record, then the restore of the claim moved before it
            raise OSError("injected failure")
        return real(tmp, path, tries)
    monkeypatch.setattr(G, "_replace", fake)
    r = guard(demo, *sp_args(amend_file, "demo", "main", "--amend", "--expect-revision", "1"))
    assert r.rc == 11 and "could not be put back" in r.err and "ui.claim" in r.err.replace("\\", "/"), r
    assert not [x for x in audit_lines(demo) if x["op"] == "set-amend"]
    monkeypatch.setattr(G, "_replace", real)


def test_dry_run_writes_nothing_and_takes_no_lock(demo, guard, tmp_path, monkeypatch):
    good = write_spec(tmp_path, demo_spec(demo, tmp_path), "good.json")
    bad = write_spec(tmp_path, {"v": 2}, "bad.json")
    overlap_spec = demo_spec(demo, tmp_path)
    overlap_spec["lanes"][2]["paths"] = ["src/ui/"]
    overlap = write_spec(tmp_path, overlap_spec, "overlap.json")
    stale = write_spec(tmp_path, demo_spec(demo, tmp_path, base="0" * 40), "stale.json")
    assert not store_dir(demo).exists()
    for f, rc, code in ((good, 0, "OK"), (bad, 24, "INVALID_SPEC"), (overlap, 10, "CONFLICT"), (stale, 19, "STALE")):
        rc_, v = jplan(guard, demo, f, "--dry-run")
        assert (rc_, v["code"]) == (rc, code), v
        assert not store_dir(demo).exists()  # not even the store directory
        if rc == 0:
            assert v["dry_run"] is True and v["written"] == []
    r = guard(demo, *sp_args(good, "demo", "main", "--dry-run"))
    assert r.rc == 0 and r.out.startswith("MAGOS: preview passed, no overlap found (set 'demo' not registered).") and not store_dir(demo).exists()
    plan_ok(guard, demo, good)
    before = store_files(demo)
    tree = store_tree(demo)
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    amend_file = write_spec(tmp_path, amend, "amend.json")
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "1")
    release = holding_lock(demo)
    try:
        started = time.monotonic()
        rc, v = jplan(guard, demo, amend_file, "--dry-run", "--amend", "--expect-revision", "1")
        assert rc == 0 and v["code"] == "OK" and v["dry_run"] is True and v["revision"] == 2 and v["written"] == []
        assert time.monotonic() - started < 20  # the held lock neither delays nor blocks the call
    finally:
        release()
    assert store_files(demo) == before and store_tree(demo) == tree and len(audit_lines(demo)) == 1


def test_every_kind_of_overlap_names_both_lanes(tmp_path, guard):
    def two(a, b, name):
        r = make_repo(tmp_path, name, BASE_FILES + ("src/x/y.py", "src/ab.py", "cafe/x", "pages/i.tsx", "src/b/z.py"))
        spec = demo_spec(r, tmp_path, shared=[])
        spec["lanes"] = [lane(tmp_path, "A1", "agent/demo/a", a), lane(tmp_path, "B2", "agent/demo/b", b)]
        return r, write_spec(tmp_path, spec, name + ".json")
    nfd, nfc = unicodedata.normalize("NFD", "café/x"), unicodedata.normalize("NFC", "café/x")
    cases = [(["src/a.py"], ["src/a.py"]), (["src/*.py"], ["src/a.py"]), (["src/"], ["src/a.py"]), (["src/**"], ["src/x/y.py"]), (["**/*.md"], ["docs/readme.md"]),
             (["Src/A.py"], ["src/a.py"]), ([nfd], [nfc]), (["pages/[id].tsx"], ["pages/i.tsx"]), (["src/*.py"], ["src/?.py"])]
    for n, (a, b) in enumerate(cases):
        r, f = two(a, b, "ov%d" % n)
        rc, v = jplan(guard, r, f)
        assert rc == 10 and v["code"] == "CONFLICT" and set(v) == COMMON_KEYS | {"overlaps"}, (a, b, v)
        assert v["overlaps"][0]["a"] == "A1" and v["overlaps"][0]["b"] == "B2" and v["overlaps"][0]["entries"] == [[a[0], b[0]]]
        assert not store_dir(r).exists()  # nothing is written
        text = guard(r, *sp_args(f)).out
        assert "lane A1 and lane B2 overlap" in text and a[0] in text and b[0] in text
        zh = run(["--repo", str(r.path), "--lang", "zh", *sp_args(f)])
        assert zh.rc == 10 and "lane A1 与 lane B2 的 manifest 重叠" in zh.out
    for n, (a, b) in enumerate([(["src/a.py"], ["src/ab.py"]), (["src/a/"], ["src/b/"])]):  # the disjoint neighbours register
        r, f = two(a, b, "dj%d" % n)
        assert plan_ok(guard, r, f)["revision"] == 1
    r, f = two(["src/a.py"], ["docs/d.md"], "three")
    spec = json.loads(f.read_text(encoding="utf-8"))
    spec["lanes"] = [lane(tmp_path, "L1", "agent/demo/a", ["src/a.py"]), lane(tmp_path, "L2", "agent/demo/b", ["docs/"]), lane(tmp_path, "L3", "agent/demo/c", ["src/*.py"])]
    rc, v = jplan(guard, r, write_spec(tmp_path, spec, "three.json"))
    assert rc == 10 and [(x["a"], x["b"]) for x in v["overlaps"]] == [("L1", "L3")]
    spec["lanes"] = [lane(tmp_path, "A1", "agent/demo/a", ["src/f1*.py", "src/f2*.py", "src/f3*.py", "src/f4*.py", "src/f5*.py"]),
                     lane(tmp_path, "B2", "agent/demo/b", ["src/*1z*.py", "src/*2z*.py", "src/*3z*.py", "src/*4z*.py", "src/*5z*.py"])]
    rc, v = jplan(guard, r, write_spec(tmp_path, spec, "many.json"))
    assert rc == 10 and sum(len(x["entries"]) for x in v["overlaps"]) == 20  # 25 pairs: 20 are reported
    assert v["message"].splitlines()[-1] == "... and 5 more"
    # the marker entry of the integration claim and the entries that can match a path under it take no part in the proof
    for n, (a, b) in enumerate([(["docs/**/*.md"], ["*.md"]), (["**/*.md"], ["src/**/*.py"]), (["src/"], [".magos/"]), (["src/"], [".magos/integration/demo/x.py"]),
                                (["src/"], [".magos/**"]), (["src/"], [".magos/integration/other/"])]):
        r, f = two(a, b, "mk%d" % n)
        assert jplan(guard, r, f, "--dry-run")[0] == 0, (a, b)
        v = plan_ok(guard, r, f)
        assert "integration" not in json.dumps(v.get("overlaps", [])) and v["revision"] == 1
        assert claim_lines(r, "agent/demo/integration")[11:] == ["entry=.magos/integration/demo/", ""]
        assert [x["paths"] for x in record(r)["lanes"]] == [a, b]


def test_dependency_graph_cycles_and_unknown_ids(demo, guard, tmp_path):
    def spec_with(deps, ids=("L1", "L2", "L3")):
        s = demo_spec(demo, tmp_path, shared=[])
        s["lanes"] = [lane(tmp_path, lid, "agent/demo/" + lid.lower(), ["d%d/" % i], d) for i, (lid, d) in enumerate(zip(ids, deps))]
        return write_spec(tmp_path, s)
    cases = [([["L1"], [], []], "CYCLE", "lanes[0].depends_on[0]"), ([[], ["L1", "L1"], []], "DUPLICATE", "lanes[1].depends_on[1]"),
             ([[], ["L9"], []], "UNKNOWN_LANE", "lanes[1].depends_on[0]"), ([[], ["l1"], []], "UNKNOWN_LANE", "lanes[1].depends_on[0]"),
             ([["L2"], ["L1"], []], "CYCLE", "lanes[0].depends_on"), ([["L3"], ["L1"], ["L2"]], "CYCLE", "lanes[0].depends_on")]
    for deps, code, field in cases:
        rc, v = jplan(guard, demo, spec_with(deps), "--dry-run")
        assert rc == 24 and (field, code) in errors_of(v), (deps, v)
    cyc = next(e for e in jplan(guard, demo, spec_with([["L3"], ["L1"], ["L2"]]), "--dry-run")[1]["errors"] if e["code"] == "CYCLE")
    assert all(x in cyc["text"] for x in ("L1", "L2", "L3"))  # the message lists the lanes on the cycle
    twelve = demo_spec(demo, tmp_path, shared=[])
    twelve["lanes"] = [lane(tmp_path, "L%d" % i, "agent/demo/l%d" % i, ["d%d/" % i]) for i in range(1, 13)]
    twelve["lanes"][11]["depends_on"] = ["L%d" % i for i in range(1, 12)] + ["L1"]  # 12 ids: one over the limit
    rc, v = jplan(guard, demo, write_spec(tmp_path, twelve), "--dry-run")
    assert rc == 24 and ("lanes[11].depends_on", "RANGE") in errors_of(v)
    twelve["lanes"][11]["depends_on"] = ["L%d" % i for i in range(1, 12)]  # 11 ids are fine
    assert jplan(guard, demo, write_spec(tmp_path, twelve), "--dry-run")[0] == 0
    diamond = demo_spec(demo, tmp_path, shared=[])
    diamond["lanes"] = [lane(tmp_path, "L1", "agent/demo/l1", ["a/"]), lane(tmp_path, "L2", "agent/demo/l2", ["b/"], ["L1"]), lane(tmp_path, "L3", "agent/demo/l3", ["c/"], ["L1"]),
                        lane(tmp_path, "L4", "agent/demo/l4", ["d/"], ["L2", "L3"])]
    assert jplan(guard, demo, write_spec(tmp_path, diamond), "--dry-run")[1]["order"] == ["L1", "L2", "L3", "L4"]
    diamond["lanes"] = [lane(tmp_path, "L%d" % i, "agent/demo/l%d" % i, ["d%d/" % i]) for i in (1, 2, 3)]
    assert jplan(guard, demo, write_spec(tmp_path, diamond), "--dry-run")[1]["order"] == ["L1", "L2", "L3"]
    chain = demo_spec(demo, tmp_path, shared=[])
    chain["lanes"] = [lane(tmp_path, "L3", "agent/demo/l3", ["c/"], ["L2"]), lane(tmp_path, "L2", "agent/demo/l2", ["b/"], ["L1"]), lane(tmp_path, "L1", "agent/demo/l1", ["a/"])]
    assert jplan(guard, demo, write_spec(tmp_path, chain), "--dry-run")[1]["order"] == ["L1", "L2", "L3"]
    mixed = demo_spec(demo, tmp_path, shared=[])  # the first lane of the array whose dependencies are placed comes next
    mixed["lanes"] = [lane(tmp_path, "A", "agent/demo/a", ["a/"], ["C"]), lane(tmp_path, "B", "agent/demo/b", ["b/"]), lane(tmp_path, "C", "agent/demo/c", ["c/"])]
    assert jplan(guard, demo, write_spec(tmp_path, mixed), "--dry-run")[1]["order"] == ["B", "C", "A"]


def test_a_plan_against_another_target_tip_is_stale(demo, guard, tmp_path, monkeypatch):
    old = demo.git("rev-parse", "main")
    demo.commit("README.md", "moved\n")
    new = demo.git("rev-parse", "main")
    f = write_spec(tmp_path, demo_spec(demo, tmp_path, base=old))
    rc, v = jplan(guard, demo, f)
    assert rc == 19 and v["code"] == "STALE" and v["kind"] == "base" and v["expected"] == old and v["current"] == new
    assert set(v) == COMMON_KEYS | {"kind", "expected", "current"} and store_files(demo) in (None, {})
    en = guard(demo, *sp_args(f)).out.rstrip("\n")
    assert en == "MAGOS: the plan is stale, nothing was written: target main is now at %s, but the plan was made against %s. Investigate the repository again and re-plan." % (new, old)
    zh = run(["--repo", str(demo.path), "--lang", "zh", *sp_args(f)])
    assert zh.rc == 19 and "计划已过期" in zh.out and new in zh.out and old in zh.out
    for bad in (new[:7], new + "0", "z" * 40, "g" + new[1:]):  # an abbreviation, 41 digits, not hex
        rc, v = jplan(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path, base=bad)), "--dry-run")
        assert rc == 24 and ("base", "FORMAT") in errors_of(v), bad
    rc, v = jplan(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path, base=new.upper())))  # an upper-case base registers and is stored in lower case
    assert rc == 0 and v["base"] == new and record(demo)["base"] == new
    # the tip is read inside the lock: a commit made while the call waits for the lock makes the plan stale
    other = make_repo(tmp_path, "other")
    tip = other.git("rev-parse", "main")
    f2 = write_spec(tmp_path, demo_spec(other, tmp_path, base=tip), "other.json")
    release = holding_lock(other)
    proc = spawn(other, *sp_args(f2))
    time.sleep(3)
    other.commit("README.md", "moved while waiting\n")
    release()
    rc, out, err = finished(proc)
    v = json.loads(out)
    assert rc == 19 and v["kind"] == "base" and v["expected"] == tip and v["current"] == other.git("rev-parse", "main")
    assert store_files(other) in (None, {})


def test_two_planners_racing_under_the_lock(tmp_path, guard):
    def racers(repo, jobs):
        release = holding_lock(repo)
        procs = [spawn(repo, *j) for j in jobs]
        time.sleep(3)  # both have parsed their arguments and wait for the lock
        return release, procs
    # two different sets whose lanes overlap in one entry
    r = make_repo(tmp_path, "race1")
    a = demo_spec(r, tmp_path, shared=[], title="A")
    a["lanes"] = [lane(tmp_path, "A1", "agent/a/one", ["src/"])]
    b = demo_spec(r, tmp_path, shared=[], title="B")
    b["lanes"] = [lane(tmp_path, "B1", "agent/b/one", ["src/api/"])]
    fa, fb = write_spec(tmp_path, a, "a.json"), write_spec(tmp_path, b, "b.json")
    release, procs = racers(r, [sp_args(fa, "seta"), sp_args(fb, "setb")])
    release()
    results = [finished(p) for p in procs]
    assert sorted(rc for rc, _, _ in results) == [0, 10], results
    loser = next(json.loads(o) for rc, o, _ in results if rc == 10)
    winner_lane = "A1" if results[0][0] == 0 else "B1"
    assert loser["lanes"][0]["conflicts"][0]["branch"] == ("agent/a/one" if winner_lane == "A1" else "agent/b/one")
    assert loser["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "declared"
    sets = sorted(p.stem for p in (store_dir(r) / "sets").glob("*.json"))
    assert len(sets) == 1 and not list(store_dir(r).rglob("*.tmp"))
    claims = sorted(P(p.relative_to(store_dir(r) / "claims")) for p in (store_dir(r) / "claims").rglob("*.claim"))
    assert claims == (["agent/a/one.claim", "agent/seta/integration.claim"] if sets == ["seta"] else ["agent/b/one.claim", "agent/setb/integration.claim"])  # the winner's, nothing of the loser's
    # the same set name twice
    r = make_repo(tmp_path, "race2")
    f = write_spec(tmp_path, demo_spec(r, tmp_path), "same.json")
    release, procs = racers(r, [sp_args(f), sp_args(f)])
    release()
    results = [finished(p) for p in procs]
    assert sorted(rc for rc, _, _ in results) == [0, 20], results
    assert record(r)["revision"] == 1 and len(list((store_dir(r) / "claims").rglob("*.claim"))) == 4
    # a set while another process commits to main
    r = make_repo(tmp_path, "race3")
    tip = r.git("rev-parse", "main")
    f = write_spec(tmp_path, demo_spec(r, tmp_path, base=tip), "moving.json")
    release = holding_lock(r)
    proc = spawn(r, *sp_args(f))
    time.sleep(3)
    r.commit("README.md", "moved\n")
    release()
    rc, out, err = finished(proc)
    assert rc == 19 and json.loads(out)["kind"] == "base" and store_files(r) in (None, {})
    # a plain plan of a lane branch of the set against the set
    r = make_repo(tmp_path, "race4")
    f = write_spec(tmp_path, demo_spec(r, tmp_path), "lane.json")
    release, procs = racers(r, [sp_args(f), ["plan", "--branch", "agent/demo/api", "--paths", "src/other/"]])
    release()
    (rc_set, out_set, _), (rc_plan, out_plan, _) = [finished(p) for p in procs]
    assert (rc_set, rc_plan) in ((0, 14), (14, 0)), (rc_set, out_set, rc_plan, out_plan)
    if rc_set == 0:
        assert "lane of set 'demo'" in json.loads(out_plan)["message"] and len(list((store_dir(r) / "claims").rglob("*.claim"))) == 4
    else:
        assert json.loads(out_set)["errors"][0]["field"] == "lanes[0].branch" and not (store_dir(r) / "sets").exists() or not list((store_dir(r) / "sets").glob("*.json"))
        assert len(list((store_dir(r) / "claims").rglob("*.claim"))) == 1


def test_an_existing_set_is_refused_without_amend(demo, guard, tmp_path):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    plan_ok(guard, demo, f)
    before = store_files(demo)
    other = demo_spec(demo, tmp_path)
    other["lanes"][2]["paths"] = ["docs/", "notes/"]
    of = write_spec(tmp_path, other, "other.json")
    for extra in ((), ("--dry-run",)):
        rc, v = jplan(guard, demo, of, *extra)
        assert rc == 20 and v["code"] == "SET_EXISTS" and v["current"] == 1 and set(v) == COMMON_KEYS | {"current"}
    en = guard(demo, *sp_args(of)).out.rstrip("\n")
    assert en == "MAGOS: set 'demo' already exists (revision 1). Change it with --amend --expect-revision 1, or release it first with set-release."
    zh = run(["--repo", str(demo.path), "--lang", "zh", *sp_args(of)])
    assert zh.rc == 20 and "已存在（修订 1）" in zh.out and "--amend --expect-revision 1" in zh.out
    assert store_files(demo) == before
    for extra in (("--amend",), ("--expect-revision", "1")):
        r = guard(demo, *sp_args(of, "demo", "main", *extra))
        assert r.rc == 2 and r.out == "" and "--amend and --expect-revision go together" in r.err, extra
    assert store_files(demo) == before


# ---- TC-261 .. TC-267: amend, judgement, names ---------------------------------------------------------------------------
def test_amend_compares_the_revision(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    before, rec1 = store_files(demo), record(demo)
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    af = write_spec(tmp_path, amend, "amend.json")
    v = plan_ok(guard, demo, af, "--amend", "--expect-revision", "1")
    assert v["revision"] == 2 and v["unchanged"] is False and v["lanes"][2]["entries"] == ["docs/", "notes/"]
    rec2 = record(demo)
    assert rec2["revision"] == 2 and rec2["updated"] != rec1["updated"] and rec2["created"] == rec1["created"] and rec2["lanes"][2]["paths"] == ["docs/", "notes/"]
    after = store_files(demo)
    assert sorted(k for k in after if after[k] != before.get(k) and k != "audit.log") == ["claims/agent/demo/docs.claim", "sets/demo.json"]  # only the claim of L3 is rewritten
    for rev in ("1", "5"):
        rc, v = jplan(guard, demo, af, "--amend", "--expect-revision", rev)
        assert rc == 19 and v["kind"] == "revision" and v["current"] == 2 and v["expected"] == int(rev) and set(v) == COMMON_KEYS | {"kind", "expected", "current"}
    out = guard(demo, *sp_args(af, "demo", "main", "--amend", "--expect-revision", "1")).out.rstrip("\n")
    assert out == "MAGOS: the plan is stale, nothing was written: set 'demo' is at revision 2, not 1. Read it again with set-show."
    zh = run(["--repo", str(demo.path), "--lang", "zh", *sp_args(af, "demo", "main", "--amend", "--expect-revision", "1")])
    assert zh.rc == 19 and "现在是修订 2，而你基于修订 1" in zh.out
    assert guard(demo, *sp_args(af, "demo", "main", "--amend")).rc == 2  # no --expect-revision
    rc, v = jplan(guard, demo, af, "--amend", "--expect-revision", "1", name="ghost")
    assert rc == 21 and v["code"] == "SET_UNKNOWN" and set(v) == COMMON_KEYS
    assert guard(demo, *sp_args(af, "ghost", "main", "--amend", "--expect-revision", "1")).out.rstrip("\n") == "MAGOS: there is no set named 'ghost'."
    rc, v = jplan(guard, demo, af, "--amend", "--expect-revision", "2", target="develop")
    assert rc == 24 and ("--target", "STATE") in errors_of(v)
    snapshot = store_files(demo)
    v = plan_ok(guard, demo, af, "--amend", "--expect-revision", "2")  # the spec is unchanged
    assert v["unchanged"] is True and v["revision"] == 2 and v["written"] == [] and store_files(demo) == snapshot
    assert guard(demo, *sp_args(af, "demo", "main", "--amend", "--expect-revision", "2")).out.startswith("MAGOS: set 'demo' is unchanged (revision 2); nothing was written.")


def test_amend_keeps_the_state_of_surviving_lanes(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    head = demo.git("rev-parse", "main")
    demo.git("branch", "agent/demo/api", "main")  # a lane with a branch and no commit may be ready
    upd_ok(guard, demo, "L1", "active")
    upd_ok(guard, demo, "L1", "ready", "--head", head, "--note", "done")
    upd_ok(guard, demo, "L2", "blocked", "--note", "waiting for the api")
    seeded = record(demo)
    assert seeded["revision"] == 4
    l1_before = (store_dir(demo) / "claims" / "agent" / "demo" / "api.claim").read_bytes()
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][1].update(title="new title", paths=["src/ui/", "ui-extra/"])
    amend["lanes"][2:] = [lane(tmp_path, "L4", "agent/demo/extra", ["extra/"])]  # L3 is removed, L4 is new
    af = write_spec(tmp_path, amend, "amend.json")
    v = plan_ok(guard, demo, af, "--amend", "--expect-revision", "4")
    rec = record(demo)
    assert v["revision"] == 5 and rec["revision"] == 5 and rec["created"] == seeded["created"] and [x["id"] for x in rec["lanes"]] == ["L1", "L2", "L4"]
    assert (lane_of(rec, "L1")["state"], lane_of(rec, "L1")["head"], lane_of(rec, "L1")["note"]) == ("ready", head, "done")
    assert lane_of(rec, "L1")["updated"] == lane_of(seeded, "L1")["updated"]  # an untouched lane keeps its time
    l2 = lane_of(rec, "L2")
    assert (l2["state"], l2["note"], l2["title"], l2["paths"]) == ("blocked", "waiting for the api", "new title", ["src/ui/", "ui-extra/"]) and l2["updated"] != lane_of(seeded, "L2")["updated"]
    l4 = lane_of(rec, "L4")
    assert (l4["state"], l4["head"], l4["note"]) == ("planned", None, "")
    claims = store_dir(demo) / "claims" / "agent" / "demo"
    assert not (claims / "docs.claim").exists() and (claims / "api.claim").read_bytes() == l1_before and (claims / "extra.claim").is_file()
    assert "entry=ui-extra/" in (claims / "ui.claim").read_text(encoding="utf-8").split("\n")
    # a lane that has a branch or a worktree keeps both; one that has neither can change them
    for field, value in (("branch", "agent/demo/api2"), ("worktree", wt_path(tmp_path, "moved"))):
        again = json.loads(af.read_text(encoding="utf-8"))
        again["lanes"][0][field] = value
        rc, v = jplan(guard, demo, write_spec(tmp_path, again, "again.json"), "--amend", "--expect-revision", "5")
        assert rc == 24 and ("lanes[0].%s" % field, "STATE") in errors_of(v), v
    again = json.loads(af.read_text(encoding="utf-8"))
    again["lanes"][1].update(branch="agent/demo/ui2", worktree=wt_path(tmp_path, "ui2"))
    v = plan_ok(guard, demo, write_spec(tmp_path, again, "again.json"), "--amend", "--expect-revision", "5")
    rec = record(demo)
    assert v["revision"] == 6 and lane_of(rec, "L2")["branch"] == "agent/demo/ui2" and lane_of(rec, "L2")["state"] == "blocked"
    assert not (claims / "ui.claim").exists() and "branch=agent/demo/ui2" in (claims / "ui2.claim").read_text(encoding="utf-8").split("\n")


def test_amend_refuses_removal_and_shrink_of_started_lanes(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    w1, w2 = tmp_path / "wt" / "l1", tmp_path / "wt" / "l2"
    demo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(w1), "main")
    demo.commit("src/api/x.py", "x\n", cwd=w1, msg="l1")
    demo.write("tests/api/new.py", "uncommitted\n", base=w1)
    demo.git("worktree", "add", "-q", "-b", "agent/demo/ui", str(w2), "main")
    demo.commit("src/ui/y.py", "y\n", cwd=w2, msg="l2")
    demo.git("branch", "agent/demo/docs", "main")  # L3: merged into main
    before = store_files(demo)

    def amended(mutate, name="amend.json"):
        s = demo_spec(demo, tmp_path)
        mutate(s)
        return write_spec(tmp_path, s, name)

    def refused(mutate):
        rc, v = jplan(guard, demo, amended(mutate), "--amend", "--expect-revision", "1")
        assert rc == 16 and v["code"] == "BLOCKED" and set(v) == COMMON_KEYS | {"blocked"}, v
        assert store_files(demo) == before  # nothing is written
        return v

    def without(lid, **fix):
        def mutate(s):
            s["lanes"] = [x for x in s["lanes"] if x["id"] != lid]
            for k, val in fix.items():
                s[k] = val
            for x in s["lanes"]:
                x["depends_on"] = [d for d in x["depends_on"] if d != lid]
        return mutate
    v = refused(without("L2"))
    assert {"lane": "L2", "reason": "UNMERGED_WORK", "files": []} in v["blocked"] and "the branch agent/demo/ui of lane L2 has unmerged work" in v["message"]
    v = refused(without("L1", shared=[]))
    assert {(b["lane"], b["reason"]) for b in v["blocked"]} == {("L1", "UNMERGED_WORK"), ("L1", "DIRTY_WORKTREE")}
    assert next(b for b in v["blocked"] if b["reason"] == "DIRTY_WORKTREE")["files"] == ["tests/api/new.py"]
    v = refused(lambda s: s.update(shared=[]) or s["lanes"][0].update(paths=["src/api/y.py"]))
    assert v["blocked"] == [{"lane": "L1", "reason": "SHRINK", "files": ["src/api/x.py", "tests/api/new.py"]}]  # committed and uncommitted
    assert "lane L1 already changed files outside its new manifest: src/api/x.py, tests/api/new.py" in v["message"]
    v = refused(lambda s: s["lanes"][0].update(paths=["src/api/", "package-lock.json"]))
    assert v["blocked"] == [{"lane": "L1", "reason": "SHRINK", "files": ["tests/api/new.py"]}]  # below an uncommitted file
    demo.git("mv", "src/api/a.py", "src/api/renamed.py", cwd=w1)
    v = refused(lambda s: s["lanes"][0].update(paths=["src/api/renamed.py", "src/api/x.py", "tests/api/new.py", "package-lock.json"]))
    assert v["blocked"] == [{"lane": "L1", "reason": "SHRINK", "files": ["src/api/a.py"]}]  # a rename counts both names
    both = refused(lambda s: (s.update(shared=[]), s["lanes"][0].update(paths=["web/"]), s["lanes"].pop(1)))
    assert {b["lane"] for b in both["blocked"]} == {"L1", "L2"}  # every offending lane is named
    # the lane that holds nothing can be removed: the claim goes, the branch and the worktrees stay
    v = plan_ok(guard, demo, amended(without("L3")), "--amend", "--expect-revision", "1")
    assert v["revision"] == 2 and not (store_dir(demo) / "claims" / "agent" / "demo" / "docs.claim").exists()
    assert [x["id"] for x in record(demo)["lanes"]] == ["L1", "L2"]
    assert branches(demo) == ["agent/demo/api", "agent/demo/docs", "agent/demo/ui", "main"] and demo.git("worktree", "list", "--porcelain").count("worktree ") == 3
    assert [x for x in audit_lines(demo) if x["op"] == "set-amend"][0]["removed"] == ["L3"]

    def add_l4(s):
        s["lanes"] = [x for x in s["lanes"] if x["id"] != "L3"] + [lane(tmp_path, "L4", "agent/demo/extra", ["extra/"])]
    plan_ok(guard, demo, amended(add_l4, "add.json"), "--amend", "--expect-revision", "2")

    def drop_l4(s):
        s["lanes"] = [x for x in s["lanes"] if x["id"] not in ("L3", "L4")]
    v = plan_ok(guard, demo, amended(drop_l4, "drop.json"), "--amend", "--expect-revision", "3")  # a lane that has no branch
    assert v["revision"] == 4 and not (store_dir(demo) / "claims" / "agent" / "demo" / "extra.claim").exists()


def test_lanes_are_judged_against_every_other_claimant(tmp_path, guard):
    def case(name, prep):
        r = make_repo(tmp_path, name)
        prep(r)
        return r, write_spec(tmp_path, demo_spec(r, tmp_path), name + ".json")

    def plain_claim(r):
        assert guard(r, "plan", "--branch", "agent/other", "--paths", "src/ui/").rc == 0

    def committed(r):
        branch_at(r, "feature/x", {"docs/readme.md": "changed\n"})

    def uncommitted(r):
        w = r.worktree("wt-extra-" + r.path.name, "agent/extra")
        r.write("src/api/new.py", "n\n", base=w)
    r, f = case("c1", plain_claim)
    rc, v = jplan(guard, r, f)
    assert rc == 10 and v["code"] == "CONFLICT" and set(v) == COMMON_KEYS | {"lanes"} and [x["id"] for x in v["lanes"]] == ["L2"]
    lane2 = v["lanes"][0]
    assert lane2["branch"] == "agent/demo/ui" and lane2["code"] == "CONFLICT" and lane2["conflicts"][0]["branch"] == "agent/other" and lane2["conflicts"][0]["evidence"][0]["kind"] == "declared"
    text = guard(r, *sp_args(f)).out
    assert "lane L2 (branch agent/demo/ui):" in text and "agent/other" in text and "declared in the ledger" in text
    assert "set-plan neither reads nor consumes an override" in text and "override --fingerprint" not in text
    assert not (store_dir(r) / "sets").exists() and not (store_dir(r) / "claims" / "agent" / "demo").exists()  # only the plain claim exists
    r, f = case("c2", committed)
    rc, v = jplan(guard, r, f)
    assert rc == 10 and [x["id"] for x in v["lanes"]] == ["L3"] and v["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "committed" and v["lanes"][0]["conflicts"][0]["branch"] == "feature/x"
    r, f = case("c3", uncommitted)
    rc, v = jplan(guard, r, f)
    assert rc == 10 and [x["id"] for x in v["lanes"]] == ["L1"] and v["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "uncommitted"
    r, f = case("c4", lambda r: (plain_claim(r), committed(r), uncommitted(r)))
    rc, v = jplan(guard, r, f)
    assert rc == 10 and [x["id"] for x in v["lanes"]] == ["L1", "L2", "L3"]  # every offending lane at once
    # an unreadable claim and a claim of a newer format deny the whole set
    def garbage(r):
        p = store_dir(r) / "claims" / "zz.claim"
        p.parent.mkdir(parents=True)
        p.write_text("garbage", encoding="utf-8")
    r, f = case("c5", garbage)
    rc, v = jplan(guard, r, f)
    assert rc == 11 and v["code"] == "UNKNOWN" and [x["id"] for x in v["lanes"]] == ["L1", "L2", "L3"] and v["lanes"][0]["unknowns"][0]["code"] == "CLAIM_UNPARSEABLE"

    def newer(r):
        p = store_dir(r) / "claims" / "other.claim"
        p.parent.mkdir(parents=True)
        p.write_text("state=active\nv=2\nbranch=other\nentry=x/\n", encoding="utf-8")
    r, f = case("c6", newer)
    rc, v = jplan(guard, r, f)
    assert rc == 11 and v["lanes"][0]["unknowns"][0]["code"] == "CLAIM_NEWER_FORMAT"
    assert "Only a MAGOS that reads that format can act on this claim" in guard(r, *sp_args(f)).out and not (store_dir(r) / "sets").exists()
    # an override record is neither read nor consumed
    r, f = case("c7", plain_claim)
    fp = json.loads(guard(r, "--json", "check", "--branch", "agent/demo/ui", "--paths", "src/ui/").out)["fingerprint"]
    ov = store_dir(r) / "override" / (fp + ".json")
    ov.parent.mkdir()
    ov.write_text(json.dumps({"fp": fp, "reason": "test", "expires": "2099-01-01T00:00:00Z"}), encoding="utf-8")
    assert jplan(guard, r, f)[0] == 10 and ov.is_file() and not (store_dir(r) / "sets").exists()
    # the claim of an idle lane (merged, no worktree) does not block
    def idle(r):
        assert guard(r, "plan", "--branch", "agent/idle", "--paths", "src/ui/").rc == 0
        branch_at(r, "agent/idle", {"idle.txt": "i\n"})
        r.git("merge", "-q", "--no-ff", "-m", "merge idle", "agent/idle")
    r, f = case("c8", idle)
    assert plan_ok(guard, r, f)["revision"] == 1
    # the claims of the set never conflict with each other on an amend
    again = json.loads(f.read_text(encoding="utf-8"))
    again["lanes"][1]["paths"] = ["src/ui/", "ui-extra/"]
    assert plan_ok(guard, r, write_spec(tmp_path, again, "again.json"), "--amend", "--expect-revision", "1")["revision"] == 2


def test_branch_name_rules_and_aliasing(demo, guard, tmp_path):
    def with_branches(*names):
        s = demo_spec(demo, tmp_path, shared=[])
        s["lanes"] = [lane(tmp_path, "L%d" % (i + 1), n, ["d%d/" % i]) for i, n in enumerate(names)]
        return write_spec(tmp_path, s)
    nfc, nfd = "agent/caf\u00e9", unicodedata.normalize("NFD", "agent/caf\u00e9")
    for names, field in ((("agent/x", "agent/x/y"), "lanes[1].branch"), (("Agent/X", "agent/x"), "lanes[1].branch"), ((nfc, nfd), "lanes[1].branch"),
                         (("foo.",), "lanes[0].branch"), (("x.claim",), "lanes[0].branch"), (("a./b",), "lanes[0].branch"), (("con",), "lanes[0].branch"),
                         (("agent/aux/x",), "lanes[0].branch"), (("-x",), "lanes[0].branch"), (("a b",), "lanes[0].branch"), (("x" * 101,), "lanes[0].branch"),
                         (("a<b",), "lanes[0].branch"), (("main",), "lanes[0].branch"), (("agent/demo/integration",), "lanes[0].branch"),
                         (("agent/demo/integration/x",), "lanes[0].branch"), (("agent/demo",), "lanes[0].branch")):
        rc, v = jplan(guard, demo, with_branches(*names), "--dry-run")
        assert rc == 24 and v["code"] == "INVALID_SPEC" and field in {e["field"] for e in v["errors"]}, (names, v)
    rc, v = jplan(guard, demo, with_branches("agent/x/y", "agent/x/y"), "--dry-run")
    assert rc == 24 and ("lanes[1].branch", "DUPLICATE") in errors_of(v)
    assert not store_dir(demo).exists()
    for existing, lane_branch in (("topic", "topic/sub"), ("Lane/One", "lane/one")):  # clashes with the refs of the repository: exit 12
        demo.git("branch", existing, "main")
        rc, v = jplan(guard, demo, with_branches(lane_branch), "--dry-run")
        assert rc == 12 and v["code"] == "INVALID_MANIFEST" and set(v) == COMMON_KEYS | {"errors"}, v
        assert v["errors"][0]["field"] == "lanes[0].branch" and v["errors"][0]["code"] == "BRANCH_NAME" and existing in v["errors"][0]["text"] and "lane L1" in v["errors"][0]["text"]
        assert "[BRANCH_NAME]" in guard(demo, *sp_args(with_branches(lane_branch), "demo", "main", "--dry-run")).out
    assert plan_ok(guard, demo, with_branches("agent/one", "agent/two"))["revision"] == 1  # two valid distinct branches register
    assert not branches(demo).count("agent/one")


def test_worktree_path_rules(demo, guard, tmp_path):
    win = os.name == "nt"

    def one(value, name="w", extra=None):
        s = demo_spec(demo, tmp_path, shared=[])
        s["lanes"] = [lane(tmp_path, "L1", "agent/demo/api", ["src/"], worktree=value)] + (extra or [])
        return jplan(guard, demo, write_spec(tmp_path, s, name + ".json"), "--dry-run")
    base = P(tmp_path / "lanes")
    invalid = ["wt/a", "./wt", "~/wt", "C:rel", base + "/a/../b", base + "/a\x01b", "/" + "x" * 4097 if not win else "C:/" + "x" * 4094, "\\wt"]
    invalid += ["/wt"] if win else ["/tmp/a\\b"]
    for value in invalid:
        rc, v = one(value)
        assert rc == 24 and v["errors"][0]["field"] == "lanes[0].worktree" and v["errors"][0]["code"] == "WORKTREE", (value[:40], v)
    if win:
        rc, v = one("/c/lanes/a")  # the Git Bash spelling is stored as the drive path
        assert rc == 0 and v["lanes"][0]["worktree"] == "C:/lanes/a" and v["lanes"][0]["create"].startswith('git worktree add "C:/lanes/a" -b')
        rc, v = one("//server/share/wt")
        assert rc == 0 and v["lanes"][0]["worktree"] == "//server/share/wt"
        rc, v = one("C:\\lanes\\a\\.\\b")
        assert rc == 0 and v["lanes"][0]["worktree"] == "C:/lanes/a/b"
    two = [lane(tmp_path, "L2", "agent/demo/ui", ["web/"], worktree=base + "/same")]
    assert one(base + "/same", "same", two)[1]["errors"][0]["field"] == "lanes[1].worktree"
    rc, v = one(base + "/OUT", "case", [lane(tmp_path, "L2", "agent/demo/ui", ["web/"], worktree=base + "/out")])
    assert (rc == 24) == win  # case differences compare equal where the platform folds them
    rc, v = one(base + "/outer", "inside", [lane(tmp_path, "L2", "agent/demo/ui", ["web/"], worktree=base + "/outer/inner")])
    assert rc == 24 and v["errors"][0]["field"] == "lanes[1].worktree"
    rc, v = one(base + "/inner/deep", "inside2", [lane(tmp_path, "L2", "agent/demo/ui", ["web/"], worktree=base + "/inner")])
    assert rc == 24 and v["errors"][0]["field"] == "lanes[1].worktree"
    linked = tmp_path / "area" / "linked"
    demo.git("worktree", "add", "-q", "-b", "agent/linked", str(linked), "main")
    for value in (P(demo.path / "sub" / "wt"), P(common_dir(demo) / "x"), P(linked / "inner"), P(tmp_path / "area")):
        rc, v = one(value)  # inside a worktree, inside the git directory, inside a linked worktree, and one that contains worktrees
        assert rc == 12 and v["code"] == "INVALID_MANIFEST" and v["errors"][0]["code"] == "WORKTREE" and v["errors"][0]["field"] == "lanes[0].worktree", (value, v)
    # an amend whose lane already has its worktree at that path on its own branch
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    plan_ok(guard, demo, f)
    demo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(tmp_path / "wt" / "l1"), "main")
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][0]["title"] = "renamed"
    assert plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "1")["revision"] == 2
    # the stored spelling is what the hook compares: another separator style is the same path, another path is refused
    cwd = str(demo.path)
    stored = record(demo)["lanes"][1]["worktree"]
    assert stored == wt_path(tmp_path, "l2")
    mine = lambda wt: {"tool_name": "Bash", "tool_input": {"command": 'git worktree add "%s" -b agent/demo/ui main' % wt}, "cwd": cwd}
    assert G.decide(mine(stored), "en") is None
    if win:
        assert G.decide(mine(stored.replace("/", "\\")), "en") is None
    res = G.decide(mine(P(tmp_path / "elsewhere")), "en")
    assert res and res[0] == "UNPLANNABLE" and stored.lower() in res[1].replace("\\", "/").lower()


def test_worktree_classification_ignores_os_path_isabs(demo, guard, tmp_path, monkeypatch):
    # TC-267
    spellings = ["wt/a", "./wt", "~/wt", "C:rel", "C:/x/y", "C:\\x\\y", "/c/x/y", "//server/share/wt", "\\\\server\\share\\wt", "/wt", "\\wt", "/tmp/a", "/tmp/a/../b"]
    expected = [G.lane_worktree(s) for s in spellings]

    def never(p):
        raise AssertionError("os.path.isabs was called")

    def py312(p):  # a rooted path without a drive is absolute on Windows
        return p.startswith(("/", "\\")) or bool(len(p) > 2 and p[1] == ":" and p[2] in "/\\")

    def py313(p):  # it is not
        return bool(len(p) > 2 and p[1] == ":" and p[2] in "/\\") or p.startswith(("//", "\\\\")) or (os.name != "nt" and p.startswith("/"))
    with monkeypatch.context() as m:
        m.setattr(G.os.path, "isabs", never)
        assert [G.lane_worktree(s) for s in spellings] == expected  # the classification never asks os.path.isabs
    for fake in (py312, py313):
        with monkeypatch.context() as m:
            m.setattr(G.os.path, "isabs", fake)
            assert [G.lane_worktree(s) for s in spellings] == expected
            for value in ("wt/a", "/wt"):  # and the command, which reads the same spellings
                s = demo_spec(demo, tmp_path, shared=[])
                s["lanes"] = [lane(tmp_path, "L1", "agent/demo/api", ["src/"], worktree=value)]
                r = guard(demo, "--json", *sp_args(write_spec(tmp_path, s), "demo", "main", "--dry-run"))
                assert (r.rc == 24) == (G.lane_worktree(value)[0] is None), (value, r.out)
    assert all(isinstance(x, tuple) and (x[0] is None) != (x[1] is None) for x in expected)


# ---- TC-268 .. TC-271: set-update ----------------------------------------------------------------------------------------------------
UPDATE_KEYS = COMMON_KEYS | {"set", "lane", "state", "head", "note", "integration", "revision", "warnings"}
SHOW_KEYS = COMMON_KEYS | {"record", "view", "warnings"}
RELEASE_KEYS = COMMON_KEYS | {"set", "abandoned", "released", "warnings"}
LANE_VIEW_KEYS = ["id", "branch_exists", "tip", "ahead", "descends_from_base", "worktree_present", "worktree_clean", "operation", "state", "head", "claim"]
DRIFT_LANE_KEYS = LANE_VIEW_KEYS + ["changed", "out_of_lane", "moved_since_ready"]
LANES = {"L1": "agent/demo/api", "L2": "agent/demo/ui", "L3": "agent/demo/docs"}
INTEGRATION = "agent/demo/integration"


def jcall(guard, repo, *args):
    """-> (exit code, the JSON result) of `--json <args>`."""
    r = guard(repo, "--json", *args)
    try:
        return r.rc, json.loads(r.out)
    except ValueError:
        raise AssertionError("no JSON result (exit %s); stdout %r; stderr %r" % (r.rc, r.out, r.err)) from None


def update_args(lid, state, rev, *extra, name="demo"):
    return ["set-update", "--set", name, "--expect-revision", str(rev), "--lane", lid, "--state", state, *extra]


def upd(guard, repo, lid, state, *extra, rev=None, name="demo"):
    """-> (exit code, JSON result) of `set-update` at the record's current revision (or `rev`)."""
    return jcall(guard, repo, *update_args(lid, state, record(repo, name)["revision"] if rev is None else rev, *extra, name=name))


def upd_ok(guard, repo, lid, state, *extra, **kw):
    rc, v = upd(guard, repo, lid, state, *extra, **kw)
    assert rc == 0, v
    return v


def record_file(repo, name="demo"):
    return store_dir(repo) / "sets" / (name + ".json")


def upd_refused(guard, repo, lid, state, *extra, rc_want, **kw):
    """A refused set-update: the deny object, with the record byte for byte as it was."""
    before = record_file(repo).read_bytes()
    rc, v = upd(guard, repo, lid, state, *extra, **kw)
    assert rc == rc_want and v["decision"] == "deny" and v["exit_code"] == rc_want and record_file(repo).read_bytes() == before, (rc, v)
    return v


def jshow(guard, repo, *extra, name="demo"):
    rc, v = jcall(guard, repo, "set-show", "--set", name, *extra)
    assert rc == 0, v
    return v


def jrelease(guard, repo, *extra, name="demo"):
    return jcall(guard, repo, "set-release", "--set", name, *extra)


def start_lane(repo, tmp_path, lid, files=None, msg=None):
    """The lane `lid` of the demo set created as the plan prints it (a worktree at its registered path on its branch, cut from main), with one
    commit that adds `files` {path: text} when given: -> (worktree path, tip)."""
    wt = tmp_path / "wt" / lid.lower()
    repo.git("worktree", "add", "-q", "-b", LANES[lid], str(wt), "main")
    for rel, text in (files or {}).items():
        repo.write(rel, text, base=wt)
    if files:
        repo.git("add", "-A", cwd=wt)
        repo.git("commit", "-q", "-m", msg or lid, cwd=wt)
    return wt, repo.git("rev-parse", LANES[lid])


def fast_commit(repo, branch, files, parent="main"):
    """One commit on `branch` (created, or moved to it) that adds `files` {path: text} on top of `parent`, in one git process (fast-import): -> its sha."""
    buf = bytearray(("commit refs/heads/%s\ncommitter t <t@example.invalid> 1700000000 +0000\ndata 3\nmsg\nfrom %s\n" % (branch, repo.git("rev-parse", parent))).encode("utf-8"))
    for rel, text in files.items():
        data = text.encode("utf-8")
        buf += ("M 100644 inline %s\ndata %d\n" % (rel, len(data))).encode("utf-8") + data + b"\n"
    sub(["git", "fast-import", "--quiet"], cwd=str(repo.path), input=bytes(buf), capture_output=True)
    return repo.git("rev-parse", "refs/heads/" + branch)


def integrate(repo, *branches, create=True):
    """What the converge command does in the main worktree: the integration branch (cut from main when `create`), each branch merged into it with
    --no-ff, then back on main."""
    repo.git("switch", "-q", *(("-c", INTEGRATION, "main") if create else (INTEGRATION,)))
    for b in branches:
        repo.git("merge", "-q", "--no-ff", "-m", "merge " + b, b)
    repo.git("switch", "-q", "main")


def ready_lane(guard, repo, lid, tip):
    upd_ok(guard, repo, lid, "active")
    return upd_ok(guard, repo, lid, "ready", "--head", tip)


def changed_keys(before, after):
    """The keys of the lines in which two texts of a record differ."""
    import difflib
    keys = set()
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            m = re.match(r'[+-]\s*"([a-z_]+)":', line)
            keys.add(m.group(1) if m else line)
    return keys


def test_ready_checks_every_changed_file_against_the_manifest(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, tip = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n", "tests/api/t.py": "t\n"})
    assert upd(guard, demo, "L1", "active")[0] == 0
    rev = record(demo)["revision"]
    rc, v = upd(guard, demo, "L1", "ready", "--head", tip)  # inside the manifest
    assert rc == 0 and set(v) == UPDATE_KEYS and v["code"] == "OK" and v["decision"] == "allow" and v["exit_code"] == 0 and v["warnings"] == []
    assert (v["set"], v["lane"], v["state"], v["head"], v["revision"], v["integration"], v["note"]) == ("demo", "L1", "ready", tip, rev + 1, None, "")
    rec = record(demo)
    assert lane_of(rec, "L1")["state"] == "ready" and lane_of(rec, "L1")["head"] == tip and rec["revision"] == rev + 1
    # a file of another lane's manifest: refused with exit 22, in both languages, and nothing is written
    demo.commit("src/ui/x.py", "x\n", cwd=wt, msg="outside")
    bad = demo.git("rev-parse", "agent/demo/api")
    before = record_file(demo).read_bytes()
    args = update_args("L1", "ready", rev + 1, "--head", bad)
    rc, v = jcall(guard, demo, *args)
    assert rc == 22 and v["code"] == "OUT_OF_LANE" and set(v) == COMMON_KEYS | {"lane", "files", "truncated"} and v["lane"] == "L1" and v["files"] == ["src/ui/x.py"] and v["truncated"] is False
    assert guard(demo, *args).out.rstrip("\n") == "MAGOS: refused to mark lane L1 ready: these files lie outside its manifest: src/ui/x.py. Revert them, or move the ownership with set-plan --amend."
    zh = run(["--repo", str(demo.path), "--lang", "zh", *args])
    assert zh.rc == 22 and "拒绝把 lane L1 标记为 ready" in zh.out and "src/ui/x.py" in zh.out and record_file(demo).read_bytes() == before
    # a rename counts both names: the old one is inside the manifest, the new one is not
    demo.git("reset", "-q", "--hard", tip, cwd=wt)
    (wt / "lib").mkdir()
    demo.git("mv", "src/api/a.py", "lib/a.py", cwd=wt)
    demo.git("commit", "-q", "-m", "rename", cwd=wt)
    renamed = demo.git("rev-parse", "agent/demo/api")
    v = upd_refused(guard, demo, "L1", "ready", "--head", renamed, rc_want=22)
    assert v["files"] == ["lib/a.py"]
    # merging the target into the lane charges the lane with none of the target's files
    demo.git("reset", "-q", "--hard", tip, cwd=wt)
    demo.commit("README.md", "moved by an unrelated commit\n")
    demo.git("merge", "-q", "-m", "merge main", "main", cwd=wt)
    merged = demo.git("rev-parse", "agent/demo/api")
    assert upd_ok(guard, demo, "L1", "ready", "--head", merged)["head"] == merged
    # a deleted file inside the manifest is a change inside it
    demo.git("rm", "-q", "src/api/a.py", cwd=wt)
    demo.git("commit", "-q", "-m", "delete", cwd=wt)
    deleted = demo.git("rev-parse", "agent/demo/api")
    assert upd_ok(guard, demo, "L1", "ready", "--head", deleted)["state"] == "ready"
    # a lane without commits may be ready
    _, tip3 = start_lane(demo, tmp_path, "L3")
    assert tip3 == demo.git("rev-parse", "main") and ready_lane(guard, demo, "L3", tip3)["state"] == "ready"
    # a lane that shares no history with the target
    orphan = demo.git("commit-tree", demo.git("mktree", inp=b""), "-m", "orphan")
    demo.git("update-ref", "refs/heads/" + LANES["L2"], orphan)
    upd_ok(guard, demo, "L2", "active")
    v = upd_refused(guard, demo, "L2", "ready", "--head", orphan, rc_want=16)
    assert v["blocked"] == [{"lane": "L2", "reason": "NO_MERGE_BASE"}] and set(v) == COMMON_KEYS | {"blocked"} and "shares no history with the plan's base" in v["message"]
    # more files outside than the listing carries
    demo.git("update-ref", "-d", "refs/heads/" + LANES["L2"])
    fast_commit(demo, LANES["L2"], {"zz/f%03d.txt" % i: "x\n" for i in range(201)})
    big = demo.git("rev-parse", LANES["L2"])
    v = upd_refused(guard, demo, "L2", "ready", "--head", big, rc_want=22)
    assert len(v["files"]) == 200 and v["truncated"] is True and v["files"] == sorted(v["files"])
    # the target branch deleted: the plan's base is the reference
    demo.git("worktree", "remove", "--force", str(wt))  # the registered path is free again for the second repository
    r = make_repo(tmp_path, "gone")
    plan_ok(guard, r, write_spec(tmp_path, demo_spec(r, tmp_path)))
    wt, tip = start_lane(r, tmp_path, "L1", {"src/api/a.py": "a\n"})
    upd_ok(guard, r, "L1", "active")
    r.git("switch", "-q", "-c", "scratch")
    r.git("branch", "-q", "-D", "main")  # the target branch no longer exists: the plan's base stands in for it
    assert upd_ok(guard, r, "L1", "ready", "--head", tip)["state"] == "ready"
    r.commit("docs/new.md", "n\n", cwd=wt, msg="outside")
    v = upd_refused(guard, r, "L1", "ready", "--head", r.git("rev-parse", LANES["L1"]), rc_want=22)
    assert v["files"] == ["docs/new.md"]


def test_ready_needs_the_branch_tip_a_clean_worktree_and_no_operation(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, tip = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n"})
    upd_ok(guard, demo, "L1", "active")
    v = upd_ok(guard, demo, "L1", "ready", "--head", tip.upper())  # the tip in any case; stored in lower case
    assert v["head"] == tip and lane_of(record(demo), "L1")["head"] == tip
    assert upd_ok(guard, demo, "L1", "ready", "--head", tip)["state"] == "ready"
    main_tip = demo.git("rev-parse", "main")
    v = upd_refused(guard, demo, "L1", "ready", "--head", main_tip, rc_want=16)
    assert v["blocked"] == [{"lane": "L1", "reason": "HEAD_MISMATCH"}] and ("--head %s is not the tip %s of branch agent/demo/api" % (main_tip, tip)) in v["message"]
    for head in (tip[:7], tip + "0", "z" * 40):  # an abbreviation, 41 digits, not hexadecimal
        v = upd_refused(guard, demo, "L1", "ready", "--head", head, rc_want=24)
        assert errors_of(v) == {("--head", "FORMAT")}
    rc, v = jcall(guard, demo, *update_args("L1", "ready", record(demo)["revision"]))  # no --head
    assert rc == 24 and errors_of(v) == {("--head", "MISSING")}
    v = upd_refused(guard, demo, "L1", "active", "--head", tip, rc_want=24)  # options that do not belong to the state
    assert errors_of(v) == {("--head", "STATE")}
    v = upd_refused(guard, demo, "L1", "ready", "--head", tip, "--integration", INTEGRATION, rc_want=24)
    assert errors_of(v) == {("--integration", "STATE")}
    # no branch
    upd_ok(guard, demo, "L2", "active")
    v = upd_refused(guard, demo, "L2", "ready", "--head", main_tip, rc_want=16)
    assert v["blocked"] == [{"lane": "L2", "reason": "BRANCH_MISSING"}] and "the branch agent/demo/ui of lane L2 does not exist" in v["message"]
    # an uncommitted file
    stray = demo.write("src/api/stray.txt", "u\n", base=wt)
    v = upd_refused(guard, demo, "L1", "ready", "--head", tip, rc_want=16)
    assert v["blocked"] == [{"lane": "L1", "reason": "DIRTY_WORKTREE"}] and "the worktree of lane L1 has uncommitted changes" in v["message"]
    stray.unlink()
    # a merge in progress and a rebase in progress
    demo.commit("src/api/c.py", "lane\n", cwd=wt, msg="c")
    tip = demo.git("rev-parse", "agent/demo/api")
    other = tmp_path / "other"
    demo.git("worktree", "add", "-q", "-b", "other", str(other), "main")
    demo.commit("src/api/c.py", "other\n", cwd=other, msg="other")
    demo.git("merge", "other", cwd=wt, check=False)
    v = upd_refused(guard, demo, "L1", "ready", "--head", tip, rc_want=16)
    assert {"lane": "L1", "reason": "OPERATION_IN_PROGRESS"} in v["blocked"] and "has a merge in progress" in v["message"]
    demo.git("merge", "--abort", cwd=wt)
    demo.git("rebase", "other", cwd=wt, check=False)
    v = upd_refused(guard, demo, "L1", "ready", "--head", demo.git("rev-parse", "agent/demo/api"), rc_want=16)
    assert {"lane": "L1", "reason": "OPERATION_IN_PROGRESS"} in v["blocked"] and "rebase" in v["message"]
    demo.git("rebase", "--abort", cwd=wt)
    assert demo.git("rev-parse", "agent/demo/api") == tip
    # no worktree at all is fine: a lane may be recorded from the branch alone
    demo.git("worktree", "remove", "--force", str(wt))
    assert upd_ok(guard, demo, "L1", "ready", "--head", tip)["head"] == tip


def test_integrated_needs_the_head_in_the_target_or_the_integration_branch(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    tips = {lid: start_lane(demo, tmp_path, lid, {path: lid + "\n"})[1] for lid, path in (("L1", "src/api/a1.py"), ("L2", "src/ui/u2.py"), ("L3", "docs/d3.md"))}
    for lid, tip in tips.items():
        ready_lane(guard, demo, lid, tip)
    integrate(demo, LANES["L1"], LANES["L2"])
    v = upd_refused(guard, demo, "L1", "integrated", "--head", tips["L1"], rc_want=24)  # the record names no integration branch yet
    assert errors_of(v) == {("--integration", "MISSING")}
    v = upd_refused(guard, demo, "L1", "integrated", "--head", tips["L1"], "--integration", "agent/demo/other", rc_want=24)
    assert errors_of(v) == {("--integration", "FORMAT")} and INTEGRATION in v["errors"][0]["text"]
    v = upd_ok(guard, demo, "L1", "integrated", "--head", tips["L1"], "--integration", INTEGRATION, "--note", "merged")
    assert (v["state"], v["head"], v["integration"], v["note"]) == ("integrated", tips["L1"], INTEGRATION, "merged") and record(demo)["integration"] == INTEGRATION
    assert upd_ok(guard, demo, "L2", "integrated", "--head", tips["L2"])["integration"] == INTEGRATION  # the record's branch is used
    assert upd_ok(guard, demo, "L2", "integrated", "--head", tips["L2"], "--integration", INTEGRATION, "--note", "again")["note"] == "again"  # integrated to integrated: a note
    v = upd_refused(guard, demo, "L2", "integrated", "--head", tips["L1"], rc_want=16)  # not the head recorded for the lane
    assert v["blocked"] == [{"lane": "L2", "reason": "HEAD_MISMATCH"}] and ("is not the head %s recorded for lane L2 at ready" % tips["L2"]) in v["message"]
    v = upd_refused(guard, demo, "L3", "integrated", "--head", tips["L3"], rc_want=16)  # in neither the target nor the integration branch
    assert v["blocked"] == [{"lane": "L3", "reason": "NOT_MERGED"}] and ("commit %s is in neither main nor the integration branch" % tips["L3"]) in v["message"]
    zh = run(["--repo", str(demo.path), "--lang", "zh", *update_args("L3", "integrated", record(demo)["revision"], "--head", tips["L3"])])
    assert zh.rc == 16 and "拒绝 set-update" in zh.out and "既不在 main 中，也不在集成分支中" in zh.out
    v = upd_refused(guard, demo, "L3", "integrated", "--head", tips["L1"], rc_want=16)
    assert v["blocked"] == [{"lane": "L3", "reason": "HEAD_MISMATCH"}]
    edit_record(demo, lambda rec: rec.update(integration="agent/demo/old-name"))  # a record that names another branch: --integration must be that one
    v = upd_refused(guard, demo, "L2", "integrated", "--head", tips["L2"], "--integration", INTEGRATION, rc_want=24)
    assert errors_of(v) == {("--integration", "STATE")} and "agent/demo/old-name" in v["errors"][0]["text"]
    edit_record(demo, lambda rec: rec.update(integration=INTEGRATION))
    upd_ok(guard, demo, "L3", "active")  # a lane that is not ready cannot be integrated
    v = upd_refused(guard, demo, "L3", "integrated", "--head", tips["L3"], rc_want=24)
    assert errors_of(v) == {("--state", "STATE")} and "lane L3 is active" in v["errors"][0]["text"]
    upd_ok(guard, demo, "L3", "ready", "--head", tips["L3"])
    demo.git("branch", "-m", INTEGRATION, "agent/demo/old")  # the integration branch is gone
    v = upd_refused(guard, demo, "L3", "integrated", "--head", tips["L3"], rc_want=16)
    assert v["blocked"] == [{"lane": "L3", "reason": "BRANCH_MISSING"}] and "the integration branch agent/demo/integration does not exist" in v["message"]
    demo.git("branch", "-m", "agent/demo/old", INTEGRATION)
    demo.git("merge", "-q", "--no-ff", "-m", "land L3", LANES["L3"])  # merged into main itself, not into the integration branch
    assert upd_ok(guard, demo, "L3", "integrated", "--head", tips["L3"])["state"] == "integrated"  # a head already in the target is accepted
    assert [lane_of(record(demo), x)["state"] for x in ("L1", "L2", "L3")] == ["integrated"] * 3


def test_the_transition_table_and_the_option_rules(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    allowed = {"planned": {"active", "blocked"}, "active": {"active", "ready", "blocked"}, "ready": {"active", "ready", "integrated", "blocked"},
               "integrated": {"integrated", "blocked"}, "blocked": {"active", "blocked"}}
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    _, tip = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n"})
    integrate(demo, LANES["L1"])  # the conditions of ready and of integrated hold for the lane
    path = record_file(demo)
    for frm in G.LANE_STATES:
        for to in ("active", "ready", "integrated", "blocked"):
            def seed(rec, frm=frm):
                lane_of(rec, "L1").update(state=frm, head=tip if frm in ("ready", "integrated") else None, note="n")
                rec.update(revision=7, integration=None)
            seeded = edit_record(demo, seed)
            before = path.read_text(encoding="utf-8")
            extra = (["--head", tip] if to in ("ready", "integrated") else []) + (["--integration", INTEGRATION] if to == "integrated" else [])
            rc, v = upd(guard, demo, "L1", to, *extra, rev=7)
            if to in allowed[frm]:
                assert rc == 0 and v["revision"] == 8 and v["state"] == to, (frm, to, v)
                after = record(demo)
                assert after["revision"] == 8 and lane_of(after, "L1")["state"] == to and lane_of(after, "L1")["note"] == "n"  # no --note: the note stays
                assert lane_of(after, "L1")["updated"] != lane_of(seeded, "L1")["updated"] and after["updated"] != seeded["updated"]
                assert changed_keys(before, path.read_text(encoding="utf-8")) <= {"revision", "updated", "by", "state", "head", "note", "integration"}, (frm, to)
                assert lane_of(after, "L1")["head"] == (tip if to in ("ready", "integrated") or frm == "ready" or frm == "integrated" else None), (frm, to)
                assert after["integration"] == (INTEGRATION if to == "integrated" else None)
            else:
                assert rc == 24 and v["errors"][0]["field"] == "--state" and v["errors"][0]["code"] == "STATE" and ("lane L1 is %s" % frm) in v["errors"][0]["text"], (frm, to, v)
                assert path.read_text(encoding="utf-8") == before, (frm, to)
    r = guard(demo, *update_args("L1", "planned", 7))  # planned is the initial state, never a value of --state
    assert r.rc == 2 and r.out == "" and "invalid choice" in r.err
    edit_record(demo, lambda rec: (lane_of(rec, "L1").update(state="active", head=None), rec.update(revision=7, integration=None)))
    for note in ("x" * 200, "日本" * 100):
        assert upd_ok(guard, demo, "L1", "active", "--note", note)["note"] == note
    rev = record(demo)["revision"]
    for note, field_code in (("x" * 201, "RANGE"), ("a\nb", "FORMAT"), ("a\x00b", "FORMAT"), ("a\tb", "FORMAT"), ("\ud800", "ENCODING")):
        v = upd_refused(guard, demo, "L1", "active", "--note", note, rc_want=24)
        assert errors_of(v) == {("--note", field_code)}, (note, v)
    assert upd_ok(guard, demo, "L1", "active", "--note", "")["note"] == "" and lane_of(record(demo), "L1")["note"] == ""  # an empty value clears the note
    upd_ok(guard, demo, "L1", "active", "--note", "again")
    assert upd_ok(guard, demo, "L1", "blocked")["note"] == "again"
    v = upd_refused(guard, demo, "L9", "active", rc_want=24)  # an unknown lane names the ids
    assert v["errors"] == [{"field": "--lane", "code": "UNKNOWN_LANE", "text": "set demo has the lanes L1, L2, L3"}]
    current = record(demo)["revision"]
    for bad in ("0", "01", "+1", "1000000000", "-1", "x", ""):  # a revision is 1 to 999999999 written plainly
        r = guard(demo, "set-update", "--set", "demo", "--expect-revision", bad, "--lane", "L1", "--state", "active")
        assert r.rc == 2 and r.out == "" and "--expect-revision" in r.err, bad
    r = guard(demo, "set-update", "--set", "demo", "--lane", "L1", "--state", "active")  # required options
    assert r.rc == 2 and "--expect-revision" in r.err
    assert guard(demo, "set-update", "--set", "demo", "--expect-revision", "1", "--state", "active").rc == 2
    v = upd_refused(guard, demo, "L1", "active", rev=current - 1, rc_want=19)  # stale: names the current revision
    assert (v["kind"], v["expected"], v["current"]) == ("revision", current - 1, current) and set(v) == COMMON_KEYS | {"kind", "expected", "current"}
    assert ("set 'demo' is at revision %d, not %d" % (current, current - 1)) in v["message"]
    assert upd_ok(guard, demo, "L1", "active", rev=current)["revision"] == current + 1


# ---- TC-272 .. TC-276: set-show ----------------------------------------------------------------------------------------------------------
def test_set_show_fields_without_drift(demo, guard, tmp_path, monkeypatch):
    spec = demo_spec(demo, tmp_path)
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    base = spec["base"]
    wt1, _ = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n"})
    demo.commit("src/api/b.py", "b\n", cwd=wt1, msg="second")
    tip1 = demo.git("rev-parse", LANES["L1"])
    wt3, tip3 = start_lane(demo, tmp_path, "L3", {"docs/x.md": "lane\n"})
    other = tmp_path / "other"  # a merge in progress and an uncommitted file in the worktree of L3
    demo.git("worktree", "add", "-q", "-b", "other", str(other), "main")
    demo.commit("docs/x.md", "other\n", cwd=other, msg="other")
    demo.git("merge", "other", cwd=wt3, check=False)
    demo.write("docs/untracked.md", "u\n", base=wt3)
    store_before = store_files(demo)
    v = jshow(guard, demo)
    assert set(v) == SHOW_KEYS and v["code"] == "OK" and v["decision"] == "allow" and v["exit_code"] == 0 and v["warnings"] == []
    assert v["record"] == record(demo)  # the record as stored
    view = v["view"]
    assert list(view) == ["target_tip", "target_moved", "lanes"] and "drift" not in view and view["target_tip"] == base and view["target_moved"] is False
    assert [x["id"] for x in view["lanes"]] == ["L1", "L2", "L3"] and all(list(x) == LANE_VIEW_KEYS for x in view["lanes"])
    l1, l2, l3 = view["lanes"]
    assert l1 == {"id": "L1", "branch_exists": True, "tip": tip1, "ahead": 2, "descends_from_base": True, "worktree_present": True, "worktree_clean": True,
                  "operation": [], "state": "planned", "head": None, "claim": "ok"}
    assert l2 == {"id": "L2", "branch_exists": False, "tip": None, "ahead": None, "descends_from_base": None, "worktree_present": False, "worktree_clean": None,
                  "operation": [], "state": "planned", "head": None, "claim": "ok"}
    assert (l3["branch_exists"], l3["tip"], l3["ahead"], l3["worktree_present"], l3["worktree_clean"], l3["operation"]) == (True, tip3, 1, True, False, ["merge"])
    assert store_files(demo) == store_before and not any(p.suffix == ".tmp" for p in store_dir(demo).rglob("*"))  # set-show writes nothing
    # the claim of a lane: missing, or a mismatch when it lacks set= or lane=, or its entries differ, or it cannot be read
    claim = store_dir(demo) / "claims" / "agent" / "demo" / "api.claim"
    good = claim.read_bytes()
    for edited, want in ((good.replace(b"lane=L1\n", b""), "mismatch"), (good.replace(b"set=demo\n", b""), "mismatch"), (good.replace(b"entry=src/api/", b"entry=src/other/"), "mismatch"),
                         (good.replace(b"v=1\n", b"v=2\n"), "mismatch"), (good.replace(b"state=active", b"junk"), "mismatch"), (None, "missing")):
        if edited is None:
            claim.unlink()
        else:
            claim.write_bytes(edited)
        assert jshow(guard, demo)["view"]["lanes"][0]["claim"] == want, (edited, want)
    claim.write_bytes(good)
    assert jshow(guard, demo)["view"]["lanes"][0]["claim"] == "ok"
    # the text view, in both languages: [x] only for ready and integrated lanes
    edit_record(demo, lambda rec: (lane_of(rec, "L1").update(state="ready", head=tip1), lane_of(rec, "L2").update(state="integrated", head=base), lane_of(rec, "L3").update(state="blocked")))
    en = guard(demo, "set-show", "--set", "demo")
    assert en.rc == 0 and en.err == ""
    lines = en.out.rstrip("\n").split("\n")
    assert lines[0] == "set 'demo' -> main  base %s  revision 1  integration -" % base[:7] and lines[1:4] == spec["sheet"].rstrip("\n").split("\n")
    assert lines[4:] == ["[x] L1  ready  head %s  tip %s  ahead 2  worktree clean  branch agent/demo/api" % (tip1[:7], tip1[:7]),
                         "[x] L2  integrated  head %s  tip -  ahead -  worktree absent  branch agent/demo/ui" % base[:7],
                         "[ ] L3  blocked  head -  tip %s  ahead 1  worktree merge in progress  branch agent/demo/docs" % tip3[:7]]
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo"])
    assert zh.rc == 0 and zh.out.startswith("set「demo」→ main") and "集成分支 -" in zh.out and "领先 2" in zh.out and "工作树 干净" in zh.out
    assert "工作树 缺失" in zh.out and "工作树 merge 进行中" in zh.out and zh.out.count("[x]") == 2 and "记录 %s" % tip1[:7] in zh.out
    assert json.loads(guard(demo, "--json", "set-show", "--set", "demo").out)["message"] == en.out.rstrip("\n")  # the message is the text view
    gitdir = Path(demo.git("rev-parse", "--path-format=absolute", "--git-dir", cwd=wt1))  # a git am in progress: its metadata cannot be read
    (gitdir / "rebase-apply").mkdir()
    (gitdir / "rebase-apply" / "applying").write_bytes(b"")
    assert jshow(guard, demo)["view"]["lanes"][0]["operation"] == ["rebase/am", "unreadable"]
    assert "worktree unreadable  branch agent/demo/api" in guard(demo, "set-show", "--set", "demo").out
    assert "工作树 无法读取" in run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo"]).out
    shutil.rmtree(gitdir / "rebase-apply")
    assert not any(p.suffix == ".tmp" for p in store_dir(demo).rglob("*"))
    # set-show takes no lock and creates nothing
    before = store_files(demo)
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "1")
    release = holding_lock(demo)
    try:
        started = time.monotonic()
        assert jshow(guard, demo, "--drift")["view"]["drift"]["stale"] is False  # no wait for the lock
        assert time.monotonic() - started < 15
    finally:
        release()
    assert store_files(demo) == before and len(audit_lines(demo)) == 1
    fresh = make_repo(tmp_path, "nostore")
    assert not store_dir(fresh).exists()
    r = guard(fresh, "--json", "set-show", "--set", "demo")
    assert r.rc == 21 and not store_dir(fresh).exists()  # not even the store directory


def test_drift_of_a_set_that_follows_its_plan(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    _, tip1 = start_lane(demo, tmp_path, "L1", {"tests/api/t.py": "t\n", "src/api/a.py": "a\n"})
    ready_lane(guard, demo, "L1", tip1)
    _, tip3 = start_lane(demo, tmp_path, "L3", {"docs/d3.md": "3\n"})
    upd_ok(guard, demo, "L3", "active")
    v = jshow(guard, demo, "--drift")
    rows = v["view"]["lanes"]
    assert all(list(x) == DRIFT_LANE_KEYS for x in rows) and list(v["view"]["drift"]) == ["shared_changes", "target_overlap", "stale", "merge_order"]
    l1, l2, l3 = rows
    assert (l1["changed"], l1["out_of_lane"], l1["moved_since_ready"]) == (["src/api/a.py", "tests/api/t.py"], [], False)  # the committed files, sorted
    assert (l2["changed"], l2["out_of_lane"], l2["moved_since_ready"]) == (None, [], None)  # no branch
    assert (l3["changed"], l3["out_of_lane"], l3["moved_since_ready"]) == (["docs/d3.md"], [], False)  # not ready: false
    assert v["view"]["drift"] == {"shared_changes": [], "target_overlap": [], "stale": False, "merge_order": ["L1", "L2", "L3"]} and v["warnings"] == []
    text = guard(demo, "set-show", "--set", "demo", "--drift").out.rstrip("\n").split("\n")
    assert text[-1] == "merge order: L1 -> L2 -> L3" and not any(x.startswith(("outside the manifest", "changed by more", "the target moved", "moved since")) for x in text)
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo", "--drift"])
    assert zh.out.rstrip("\n").endswith("合并顺序：L1 -> L2 -> L3")


def test_drift_target_moved_without_and_with_overlap(demo, guard, tmp_path):
    demo.commit("README.md", "v2\n")  # the base has a parent
    spec = demo_spec(demo, tmp_path)
    base, root = spec["base"], demo.git("rev-parse", "main~1")
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    _, tip1 = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n"})
    demo.commit("README.md", "moved\n")  # outside every manifest
    drift = jshow(guard, demo, "--drift")["view"]
    assert drift["target_moved"] is True and drift["drift"]["target_overlap"] == [] and drift["drift"]["stale"] is False
    assert not any(x.startswith("the target moved") for x in guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines())
    demo.write("src/ui/layout.py", "l\n")
    demo.write("docs/a.md", "a\n")
    demo.git("add", "-A")
    demo.git("commit", "-q", "-m", "two lanes' files")
    tip = demo.git("rev-parse", "main")
    v = jshow(guard, demo, "--drift")
    assert v["view"]["target_tip"] == tip and v["view"]["target_moved"] is True
    assert v["view"]["drift"]["target_overlap"] == [{"path": "docs/a.md", "lanes": ["L3"]}, {"path": "src/ui/layout.py", "lanes": ["L2"]}] and v["view"]["drift"]["stale"] is True
    en = guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines()
    assert "the target moved from %s to %s; files that overlap lanes: docs/a.md [L3], src/ui/layout.py [L2]" % (base[:7], tip[:7]) in en
    assert "目标已从 %s 移到 %s；与 lane 重叠的文件：docs/a.md [L3], src/ui/layout.py [L2]" % (base[:7], tip[:7]) in run(
        ["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo", "--drift"]).out
    # main replaced by another history: the base is no longer an ancestor of the target
    demo.git("reset", "-q", "--hard", root)
    demo.commit("src/ui/layout.py", "other history\n")
    v = jshow(guard, demo, "--drift")
    assert v["view"]["target_moved"] is True and v["view"]["drift"]["target_overlap"] == [{"path": "src/ui/layout.py", "lanes": ["L2"]}] and v["view"]["drift"]["stale"] is True
    # the target deleted: null, and the lane files are measured against the base
    demo.git("switch", "-q", "-c", "scratch")
    demo.git("branch", "-q", "-D", "main")
    v = jshow(guard, demo, "--drift")
    assert (v["view"]["target_tip"], v["view"]["target_moved"], v["view"]["drift"]["stale"], v["view"]["drift"]["target_overlap"]) == (None, None, None, [])
    assert v["view"]["lanes"][0]["changed"] == ["src/api/a.py"] and v["view"]["lanes"][0]["ahead"] == 1 and v["warnings"] == []
    assert not any(x.startswith("the target moved") for x in guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines())


def test_drift_lane_tip_moved_after_ready(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt1, h = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n"})
    ready_lane(guard, demo, "L1", h)
    wt2, _ = start_lane(demo, tmp_path, "L2", {"src/ui/u.py": "u\n"})
    upd_ok(guard, demo, "L2", "active")

    def moved():
        v = jshow(guard, demo, "--drift")
        return [x["moved_since_ready"] for x in v["view"]["lanes"]], guard(demo, "set-show", "--set", "demo", "--drift").out
    assert moved()[0] == [False, False, None]
    demo.commit("src/api/b.py", "b\n", cwd=wt1, msg="more")
    flags, text = moved()
    assert flags == [True, False, None] and "moved since ready: L1" in text.splitlines()
    assert "ready 之后分支又移动：L1" in run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo", "--drift"]).out
    demo.git("reset", "-q", "--hard", h, cwd=wt1)  # back at the recorded head
    assert moved()[0] == [False, False, None]
    demo.commit("src/api/b.py", "b\n", cwd=wt1, msg="more")
    h2 = demo.git("rev-parse", LANES["L1"])
    upd_ok(guard, demo, "L1", "ready", "--head", h2)  # ready again with the new head
    assert moved()[0] == [False, False, None]
    demo.commit("src/ui/more.py", "m\n", cwd=wt2, msg="a lane that is not ready moves")
    assert moved()[0] == [False, False, None]
    demo.git("worktree", "remove", "--force", str(wt1))
    demo.git("branch", "-q", "-D", LANES["L1"])  # no branch: null
    assert moved()[0] == [None, False, None]


def test_drift_files_changed_by_two_lanes(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt1, _ = start_lane(demo, tmp_path, "L1", {"package-lock.json": "l1\n", "README.md": "same\n", "src/api/a.py": "a\n"})
    demo.git("rm", "-q", "docs/d.md", cwd=wt1)  # L1 deletes the file that L3 renames
    demo.git("commit", "-q", "-m", "delete", cwd=wt1)
    start_lane(demo, tmp_path, "L2", {"package-lock.json": "l2\n", "README.md": "same\n", "src/api/x.py": "x\n", "src/ui/u.py": "u\n"})
    wt3, _ = start_lane(demo, tmp_path, "L3")
    demo.git("mv", "docs/d.md", "docs/e.md", cwd=wt3)
    demo.git("commit", "-q", "-m", "rename", cwd=wt3)
    v = jshow(guard, demo, "--drift")
    d = v["view"]["drift"]
    assert d["shared_changes"] == [{"path": "README.md", "lanes": ["L1", "L2"]}, {"path": "docs/d.md", "lanes": ["L1", "L3"]}, {"path": "package-lock.json", "lanes": ["L1", "L2"]}]
    l1, l2, l3 = v["view"]["lanes"]
    assert l1["out_of_lane"] == ["README.md", "docs/d.md"] and l2["out_of_lane"] == ["README.md", "package-lock.json", "src/api/x.py"] and l3["out_of_lane"] == []
    assert l3["changed"] == ["docs/d.md", "docs/e.md"]  # a rename changes both names
    text = guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines()
    assert "changed by more than one lane: README.md [L1,L2], docs/d.md [L1,L3], package-lock.json [L1,L2]" in text
    assert "outside the manifest (L2): README.md, package-lock.json, src/api/x.py" in text and "outside the manifest (L1): README.md, docs/d.md" in text
    # a lane that shares no history with the target
    r2 = make_repo(tmp_path, "unrelated")
    plan_ok(guard, r2, write_spec(tmp_path, demo_spec(r2, tmp_path), "unrelated.json"))
    orphan = r2.git("commit-tree", r2.git("mktree", inp=b""), "-m", "orphan")
    r2.git("update-ref", "refs/heads/" + LANES["L2"], orphan)
    v = jshow(guard, r2, "--drift")
    assert v["view"]["lanes"][1]["changed"] is None and v["view"]["lanes"][1]["out_of_lane"] == []
    assert [w["code"] for w in v["warnings"]] == ["UNRELATED_HISTORY"] and "L2" in v["warnings"][0]["text"] and v["view"]["lanes"][1]["ahead"] == 1


# ---- TC-277, TC-278: set-release -------------------------------------------------------------------------------------------------------
def test_set_release_gating(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wts, tips = {}, {}
    for lid, path in (("L1", "src/api/a.py"), ("L2", "src/ui/u.py"), ("L3", "docs/d3.md")):
        wts[lid], tips[lid] = start_lane(demo, tmp_path, lid, {path: lid + "\n"})
        ready_lane(guard, demo, lid, tips[lid])
    integrate(demo, LANES["L1"], LANES["L2"], LANES["L3"])
    demo.git("merge", "-q", "--ff-only", INTEGRATION)  # main holds every lane
    upd_ok(guard, demo, "L1", "integrated", "--head", tips["L1"], "--integration", INTEGRATION)
    upd_ok(guard, demo, "L3", "integrated", "--head", tips["L3"])

    def refused(*extra, want):
        snapshot, audits = store_files(demo), len(audit_lines(demo))
        rc, v = jrelease(guard, demo, *extra)
        assert rc == 16 and v["decision"] == "deny" and v["code"] == "BLOCKED" and set(v) == COMMON_KEYS | {"blocked"} and v["blocked"] == want, (rc, v)
        assert store_files(demo) == snapshot and len(audit_lines(demo)) == audits  # nothing is written
        return v
    v = refused(want=[{"lane": "L2", "reason": "NOT_INTEGRATED"}])  # L2 is still ready
    assert v["message"] == "MAGOS: set-release refused: lane L2 is ready, not integrated"
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-release", "--set", "demo"])
    assert zh.rc == 16 and zh.out.rstrip("\n") == "MAGOS：拒绝 set-release：lane L2 的状态是 ready，不是 integrated"
    upd_ok(guard, demo, "L2", "integrated", "--head", tips["L2"])
    demo.commit("docs/more.md", "m\n", cwd=wts["L3"], msg="more")  # a commit that main does not have
    v = refused(want=[{"lane": "L3", "reason": "UNMERGED_WORK"}])
    assert "the branch agent/demo/docs of lane L3 has unmerged work" in v["message"]
    demo.git("reset", "-q", "--hard", tips["L3"], cwd=wts["L3"])
    stray = demo.write("src/api/stray.txt", "u\n", base=wts["L1"])
    v = refused(want=[{"lane": "L1", "reason": "DIRTY_WORKTREE"}])
    assert "the worktree of lane L1 has uncommitted changes" in v["message"]
    stray.unlink()
    claims = store_dir(demo) / "claims" / "agent" / "demo"
    for name, lane_id in (("api", "L1"), ("integration", "integration")):
        good = (claims / (name + ".claim")).read_bytes()
        for bad in (good.replace(b"v=1\n", b"v=2\n"), b"state=active\nnot a claim\n"):  # a newer format, and one nobody can read
            (claims / (name + ".claim")).write_bytes(bad)
            v = refused(want=[{"lane": lane_id, "reason": "CLAIM_UNUSABLE"}])
            assert "cannot be read or comes from a newer MAGOS" in v["message"]
        (claims / (name + ".claim")).write_bytes(good)
    demo.commit("docs/more.md", "m\n", cwd=wts["L3"], msg="more")  # every blocking lane is named, with every reason
    stray = demo.write("src/api/stray.txt", "u\n", base=wts["L1"])
    upd_ok(guard, demo, "L2", "blocked")
    refused(want=[{"lane": "L1", "reason": "DIRTY_WORKTREE"}, {"lane": "L2", "reason": "NOT_INTEGRATED"}, {"lane": "L3", "reason": "UNMERGED_WORK"}])
    stray.unlink()
    demo.git("reset", "-q", "--hard", tips["L3"], cwd=wts["L3"])
    edit_record(demo, lambda rec: lane_of(rec, "L2").update(state="integrated"))
    # released: one branch deleted, one worktree removed, the others as they are
    demo.git("worktree", "remove", "--force", str(wts["L2"]))
    demo.git("branch", "-q", "-D", LANES["L2"])
    demo.git("worktree", "remove", str(wts["L3"]))
    audit_before = len(audit_lines(demo))
    rc, v = jrelease(guard, demo, "--reason", "done")
    assert rc == 0 and set(v) == RELEASE_KEYS and v["code"] == "OK" and v["abandoned"] is False and v["warnings"] == []
    assert v["released"] == [LANES["L1"], LANES["L2"], LANES["L3"], INTEGRATION] and v["message"] == "MAGOS: released set 'demo' and its 4 claims."
    assert not list((store_dir(demo) / "claims").rglob("*.claim")) and not record_file(demo).exists() and not list(store_dir(demo).rglob("*.tmp"))
    lines = audit_lines(demo)
    assert len(lines) == audit_before + 1 and lines[-1]["op"] == "set-release" and lines[-1]["reason"] == "done" and lines[-1]["abandon"] is False and lines[-1]["set"] == "demo"
    assert lines[-1]["lanes"] == ["L1", "L2", "L3"] and lines[-1]["claims"] == v["released"] and lines[-1]["host"] == "cli"
    assert LANES["L1"] in branches(demo) and INTEGRATION in branches(demo) and wts["L1"].is_dir()  # no branch and no worktree is removed
    assert guard(demo, "list").out.strip() == "(no claims)" and guard(demo, "doctor").rc == 0
    rc, v = jrelease(guard, demo)
    assert rc == 21 and v["code"] == "SET_UNKNOWN"
    # a claim of the lane's branch that belongs to no set is left in place with a warning, and the rest is released
    r2 = make_repo(tmp_path, "release2")
    plan_ok(guard, r2, write_spec(tmp_path, demo_spec(r2, tmp_path), "release2.json"))
    ui = store_dir(r2) / "claims" / "agent" / "demo" / "ui.claim"
    ui.write_bytes(b"".join(x for x in ui.read_bytes().splitlines(True) if not x.startswith((b"set=", b"lane="))))
    rc, v = jrelease(guard, r2, "--abandon")
    assert rc == 0 and v["released"] == [LANES["L1"], LANES["L3"], INTEGRATION] and [w["code"] for w in v["warnings"]] == ["CLAIM_NOT_REMOVED"]
    assert "agent/demo/ui" in v["warnings"][0]["text"] and v["message"].splitlines()[-1].startswith("(CLAIM_NOT_REMOVED) ") and ui.is_file() and not record_file(r2).exists()
    assert [x["branch"] for x in json.loads(guard(r2, "--json", "list").out)] == [LANES["L2"]]


def test_set_release_abandon(tmp_path, guard):
    def fresh(name):
        r = make_repo(tmp_path, name)
        spec = demo_spec(r, tmp_path)
        for lid, lane_ in zip(("l1", "l2", "l3"), spec["lanes"]):
            lane_["worktree"] = wt_path(tmp_path, name + "-" + lid)
        plan_ok(guard, r, write_spec(tmp_path, spec, name + ".json"))
        return r
    r = fresh("ab1")  # planned, active and blocked lanes whose branches hold nothing the target lacks
    r.git("branch", LANES["L2"], "main")
    upd_ok(guard, r, "L2", "active")
    upd_ok(guard, r, "L3", "blocked", "--note", "waiting")
    rc, v = jrelease(guard, r)
    assert rc == 16 and v["blocked"] == [{"lane": x, "reason": "NOT_INTEGRATED"} for x in ("L1", "L2", "L3")]  # without --abandon
    before = store_files(r)
    rc, v = jrelease(guard, r, "--abandon", "--reason", "plan dropped")
    assert rc == 0 and v["abandoned"] is True and len(v["released"]) == 4 and not record_file(r).exists() and not list((store_dir(r) / "claims").rglob("*.claim"))
    assert audit_lines(r)[-1]["abandon"] is True and audit_lines(r)[-1]["reason"] == "plan dropped" and before != store_files(r)
    r = fresh("ab2")  # a lane branch with a commit that the target lacks
    branch_at(r, LANES["L1"], {"src/api/n.py": "n\n"})
    before = store_files(r)
    rc, v = jrelease(guard, r, "--abandon")
    assert rc == 16 and v["blocked"] == [{"lane": "L1", "reason": "UNMERGED_WORK"}] and store_files(r) == before
    r = fresh("ab3")  # a dirty worktree at the registered path
    wt = tmp_path / "wt" / "ab3-l1"
    r.git("worktree", "add", "-q", "-b", LANES["L1"], str(wt), "main")
    r.write("src/api/stray.txt", "u\n", base=wt)
    before = store_files(r)
    rc, v = jrelease(guard, r, "--abandon")
    assert rc == 16 and v["blocked"] == [{"lane": "L1", "reason": "DIRTY_WORKTREE"}] and store_files(r) == before
    (wt / "src" / "api" / "stray.txt").unlink()
    assert jrelease(guard, r, "--abandon")[0] == 0  # clean: the plan is dropped, the worktree and the branch stay
    assert wt.is_dir() and LANES["L1"] in branches(r)
    r = fresh("ab4")  # the claims were removed by hand: the record is retired
    shutil.rmtree(store_dir(r) / "claims")
    rc, v = jrelease(guard, r, "--abandon")
    assert rc == 0 and v["released"] == [] and v["message"] == "MAGOS: released set 'demo' and its 0 claims." and not record_file(r).exists()
    r = fresh("ab5")  # the reason is at most 200 characters
    rc, v = jrelease(guard, r, "--abandon", "--reason", "x" * 201)
    assert rc == 24 and errors_of(v) == {("--reason", "RANGE")} and record_file(r).exists()
    assert jrelease(guard, r, "--abandon", "--reason", "x" * 200)[0] == 0


def test_set_update_compare_and_swap_across_processes(demo, guard, tmp_path, monkeypatch):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))

    def race(jobs):
        release = holding_lock(demo)
        procs = [spawn(demo, *j) for j in jobs]
        time.sleep(3)  # both have parsed their arguments and wait for the lock
        release()
        seen = []
        while any(p.poll() is None for p in procs):  # a reader meanwhile always gets a whole record: the old one or the new one
            seen.append(jshow(guard, demo)["record"]["revision"])
        return [finished(p) for p in procs], seen
    results, seen = race([update_args("L1", "active", 1), update_args("L2", "active", 1)])  # different lanes, the same revision
    assert sorted(rc for rc, _, _ in results) == [0, 19], results
    loser = json.loads(next(o for rc, o, _ in results if rc == 19))
    assert (loser["kind"], loser["expected"], loser["current"]) == ("revision", 1, 2) and "is at revision 2, not 1" in loser["message"]
    rec = record(demo)
    assert rec["revision"] == 2 and sorted(x["state"] for x in rec["lanes"]) == ["active", "planned", "planned"] and set(seen) <= {1, 2}
    results, _ = race([update_args("L3", "active", 2), update_args("L3", "blocked", 2)])  # the same lane
    assert sorted(rc for rc, _, _ in results) == [0, 19], results
    rec = record(demo)
    winner = next(json.loads(o) for rc, o, _ in results if rc == 0)
    assert rec["revision"] == 3 and lane_of(rec, "L3")["state"] == winner["state"] and not list(store_dir(demo).rglob("*.tmp"))
    assert len([x for x in audit_lines(demo) if x["op"] == "set-update"]) == 2
    # a failure of the replace of the record: the record is as it was, and no temporary file stays
    before, audits = record_file(demo).read_bytes(), len(audit_lines(demo))
    real = G._replace

    def failing(tmp, path, tries=40):
        if str(path).endswith("demo.json"):
            raise OSError("disk full")
        return real(tmp, path, tries)
    monkeypatch.setattr(G, "_replace", failing)
    r = guard(demo, "--json", *update_args("L1", "blocked", 3))
    v = json.loads(r.out)
    assert r.rc == 11 and v["unknowns"][0]["code"] == "INTERNAL_ERROR" and "disk full" in v["message"] and "MAGOS guard internal error: OSError: disk full" in r.err
    assert record_file(demo).read_bytes() == before and not list(store_dir(demo).rglob("*.tmp")) and len(audit_lines(demo)) == audits


# ---- TC-279 .. TC-285: set names, the record format, the spec ----------------------------------------------------------------
def set_commands(name, spec_file):
    """The set subcommands as argument lists that name the set `name` (each is refused with exit 21 when the set does not exist)."""
    return {"set-plan": ["set-plan", "--set=" + name, "--target", "main", "--spec", str(spec_file), "--amend", "--expect-revision", "1"],
            "set-show": ["set-show", "--set=" + name], "set-show-drift": ["set-show", "--set=" + name, "--drift"],
            "set-update": ["set-update", "--set=" + name, "--expect-revision", "1", "--lane", "L1", "--state", "active"],
            "set-release": ["set-release", "--set=" + name], "set-release-abandon": ["set-release", "--set=" + name, "--abandon"]}


def test_unknown_set_and_invalid_set_names(demo, guard, tmp_path, monkeypatch):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    nowhere = tmp_path / "nowhere"  # a directory that is no git repository is exit 2, whatever the subcommand
    nowhere.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for sub_name, args in set_commands("demo", f).items():
        r = run(["--repo", str(nowhere), *args])
        assert r.rc == 2 and r.out == "" and "not a git repository" in r.err, (sub_name, r)
    for sub_name, args in set_commands("ghost", f).items():
        for flags in ((), ("--json",)):
            r = guard(demo, *flags, *args)
            assert r.rc == 21 and r.err == "", (sub_name, r)
            if flags:
                v = json.loads(r.out)
                assert v["code"] == "SET_UNKNOWN" and v["decision"] == "deny" and v["exit_code"] == 21 and set(v) == COMMON_KEYS, v
            else:
                assert r.out.rstrip("\n") == "MAGOS: there is no set named 'ghost'."
        zh = run(["--repo", str(demo.path), "--lang", "zh", *args])
        assert zh.rc == 21 and zh.out.rstrip("\n") == "MAGOS：没有名为「ghost」的 set。"
    assert store_files(demo) in (None, {})  # nothing is written (the first locked call creates the lock file)
    for bad in ("Demo", "-x", "a.b", "../x", "con", "nul", "lpt1", "com9", "x" * 25, "", "a_b", "a b"):
        for sub_name, args in set_commands(bad, f).items():
            r = guard(demo, "--json", *args)
            v = json.loads(r.out)
            assert r.rc == 24 and v["code"] == "INVALID_SPEC" and v["errors"][0]["field"] == "--set", (bad, sub_name, v)
    rc, v = jplan(guard, demo, f, "--dry-run", name="con")
    assert rc == 24 and "Windows device name" in v["errors"][0]["text"]
    rc, v = jplan(guard, demo, f, "--dry-run", name="a" * 24)
    assert rc == 0 and v["set"] == "a" * 24 and v["integration_branch"] == "agent/%s/integration" % ("a" * 24)  # 24 characters are accepted
    assert store_files(demo) in (None, {})


NEWER_RECORDS = [b'{"v": 2, "set": "demo"}', b'{"v": 99999999999999999999}', ('{"v": %s}' % ("9" * 5000)).encode(),  # more digits than int() reads from Python 3.11 on
                 b'{"v": 2, "set": 7, "lanes": "x", "revision": [1]}', b'\xef\xbb\xbf{"v": 3}\r\n']
UNREADABLE_RECORDS = [b'{"v": 0}', b'{"v": "1"}', b'{"v": true}', b'{"v": 1.0}', b'{"v": -1}', b'{"set": "demo"}', b'[1, 2]', b'{', b'', b'null', b'\xff\xfe\x00',
                      b'{"v": ' + b"-" + b"9" * 5000 + b"}"]


def test_set_record_format_gate(demo, guard, tmp_path):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    plan_ok(guard, demo, f)
    path = store_dir(demo) / "sets" / "demo.json"
    good = path.read_bytes()
    claims_before = {k: v for k, v in store_files(demo).items() if k.startswith("claims/")}
    wrong_name = json.dumps(dict(json.loads(good), set="other")).encode("utf-8")
    calls = {"plan": sp_args(f), "dry-run": sp_args(f, "demo", "main", "--dry-run"), "amend": sp_args(f, "demo", "main", "--amend", "--expect-revision", "1"),
             "amend-dry-run": sp_args(f, "demo", "main", "--amend", "--expect-revision", "1", "--dry-run"),
             "show": ["set-show", "--set", "demo"], "show-drift": ["set-show", "--set", "demo", "--drift"],
             "update": update_args("L1", "active", 1), "release": ["set-release", "--set", "demo"], "release-abandon": ["set-release", "--set", "demo", "--abandon"]}
    for body in NEWER_RECORDS:
        path.write_bytes(body)
        for label, args in calls.items():
            r = guard(demo, "--json", *args)
            v = json.loads(r.out)
            assert r.rc == 23 and v["code"] == "SET_NEWER_FORMAT" and set(v) == COMMON_KEYS and r.err == "", (body[:30], label, r)
            assert path.read_bytes() == body  # never overwritten, none of its fields read
        text = guard(demo, *calls["plan"]).out.rstrip("\n")
        assert text.startswith("MAGOS: set 'demo' was written by a newer MAGOS (v=") and "upgrade this guard (doctor shows its version, install refreshes the copy)" in text
        assert "run this command with the MAGOS that wrote it." in text and len(text) < 400
        zh = run(["--repo", str(demo.path), "--lang", "zh", *calls["plan"]])
        assert zh.rc == 23 and "由更新版本的 MAGOS 写入" in zh.out and "请升级本守卫" in zh.out
        recs, bad = G.read_sets(G.open_repo(str(demo.path)))  # the readers of every set list it apart, with its format
        assert recs == {} and [(b.code, b.name) for b in bad] == [("SET_NEWER_FORMAT", "demo")] and str(bad[0].v).isdigit()
        d = guard(demo, "doctor")  # doctor counts it as newer-format and says how to go on; list still lists the claims
        assert d.rc == 1 and "sets: 0, unreadable: 0, newer-format: 1" in d.out and "sets/demo.json was written by a newer MAGOS (v=" in d.out and "upgrade this guard" in d.out
        assert guard(demo, "list").rc == 0 and path.read_bytes() == body
    for body in UNREADABLE_RECORDS + [wrong_name, b'{"v": 1, "set": "demo", "revision": 0}']:
        path.write_bytes(body)
        for label, args in calls.items():
            r = guard(demo, "--json", *args)
            v = json.loads(r.out)
            assert r.rc == 11 and v["code"] == "UNKNOWN" and set(v) == COMMON_KEYS | {"unknowns"} and v["unknowns"][0]["code"] == "SET_UNREADABLE", (body[:30], label, r)
            assert "demo.json" in v["message"] and "The user must inspect the file." in v["message"] and path.read_bytes() == body
        zh = run(["--repo", str(demo.path), "--lang", "zh", *calls["plan"]])
        assert zh.rc == 11 and "无法读取" in zh.out and "demo.json" in zh.out
        recs, bad = G.read_sets(G.open_repo(str(demo.path)))
        assert recs == {} and [(b.code, b.name) for b in bad] == [("SET_UNREADABLE", "demo")]
        d = guard(demo, "doctor")
        assert d.rc == 1 and "sets: 0, unreadable: 1, newer-format: 0" in d.out and "unreadable set record sets/demo.json" in d.out and path.read_bytes() == body
        assert guard(demo, "list").rc == 0

    def mutated(fn):
        rec = json.loads(good)
        fn(rec)
        return json.dumps(rec).encode("utf-8")
    shapes = [lambda r: r.update(notes="x"), lambda r: r.update(shared=[1]), lambda r: r.update(integration=5), lambda r: r.update(lanes="x"), lambda r: r["lanes"].__setitem__(0, 1),
              lambda r: r["lanes"][0].update(title=5), lambda r: r["lanes"][0].update(paths="x"), lambda r: r["lanes"][0].update(state="weird"), lambda r: r["lanes"][0].update(head=5),
              lambda r: r.update(target=1), lambda r: r.update(revision=True), lambda r: r.update(notes=[1])]
    for fn in shapes:  # a record of format 1 whose fields have another shape is unreadable, never repaired
        body = mutated(fn)
        path.write_bytes(body)
        with pytest.raises(G.SetUnreadable):
            G.parse_set("demo", "demo.json", body.decode("utf-8"))
        r = guard(demo, "--json", *calls["plan"])
        assert r.rc == 11 and json.loads(r.out)["unknowns"][0]["code"] == "SET_UNREADABLE" and path.read_bytes() == body
    path.unlink()
    path.mkdir()  # a directory in place of the record cannot be read either
    r = guard(demo, "--json", *calls["plan"])
    assert r.rc == 11 and json.loads(r.out)["unknowns"][0]["code"] == "SET_UNREADABLE" and path.is_dir()
    path.rmdir()
    path.write_bytes(good)
    assert {k: v for k, v in store_files(demo).items() if k.startswith("claims/")} == claims_before
    assert plan_ok(guard, demo, f, "--amend", "--expect-revision", "1")["unchanged"] is True  # a good record reads again
    for body in NEWER_RECORDS + UNREADABLE_RECORDS:  # the parser itself: the format gate precedes every other field
        try:
            G.parse_set("demo", "demo.json", body.decode("utf-8-sig", "replace"))
        except G.SetNewer as err:
            assert body in NEWER_RECORDS, body
            assert str(err.v).isdigit()
        except G.SetUnreadable:
            assert body in UNREADABLE_RECORDS, body


def test_spec_limits(demo, guard, tmp_path, monkeypatch):
    def spec(**top):
        s = demo_spec(demo, tmp_path, shared=[])
        s.update(top)
        return s

    def lanes_n(n, **over):
        return [lane(tmp_path, "L%d" % i, "agent/demo/l%d" % i, ["d%d/" % i], **over) for i in range(n)]

    def ok(s, name="ok.json"):
        rc, v = dry(guard, demo, tmp_path, s, name)
        assert rc == 0, v

    def bad(s, field, code=None, name="bad.json"):
        rc, v = dry(guard, demo, tmp_path, s, name)
        assert rc == 24 and v["code"] == "INVALID_SPEC" and field in {e["field"] for e in v["errors"]}, (field, v)
        assert code is None or (field, code) in errors_of(v), (field, code, v)
        assert not store_dir(demo).exists()  # nothing is written
    ok(spec(lanes=lanes_n(12)))
    bad(spec(lanes=lanes_n(13)), "lanes", "RANGE")
    ok(spec(lanes=[lane(tmp_path, "L0", "agent/demo/l0", ["p/f%d.py" % j for j in range(200)])]))
    bad(spec(lanes=[lane(tmp_path, "L0", "agent/demo/l0", ["p/f%d.py" % j for j in range(201)])]), "lanes[0].paths", "TOO_MANY")
    def entry(n):  # n characters in segments that every file system accepts
        return "d0/" + "/".join(["x" * 200] * 5) + "/" + "y" * (n - 1008)
    ok(spec(lanes=[lane(tmp_path, "L0", "agent/demo/l0", [entry(1024)])]))
    bad(spec(lanes=[lane(tmp_path, "L0", "agent/demo/l0", [entry(1025)])]), "lanes[0].paths[0]", "TOO_LONG")
    ok(spec(sheet="a" * 4090 + "\n\t\n\tx\n"))  # 4,096 characters, with a newline and a tab
    bad(spec(sheet="a" * 4097), "sheet", "RANGE")
    bad(spec(sheet="a\x01b"), "sheet", "FORMAT")
    ok(spec(notes=["n" * 200] * 5))
    bad(spec(notes=["n"] * 6), "notes[5]", "RANGE")
    bad(spec(notes=["n" * 201]), "notes[0]", "RANGE")
    ok(spec(title="t" * 120))
    bad(spec(title="t" * 121), "title", "RANGE")
    bad(spec(title=""), "title", "RANGE")
    s = spec()
    s["lanes"][0]["title"] = "t" * 80
    s["lanes"][0]["acceptance"] = "a" * 300
    ok(s)
    for key, big in (("title", "t" * 81), ("acceptance", "a" * 301), ("acceptance", "")):
        s = spec()
        s["lanes"][1][key] = big
        bad(s, "lanes[1].%s" % key, "RANGE")
    s = spec()
    s["lanes"][0]["paths"] = []
    bad(s, "lanes[0].paths", "EMPTY")
    for lid, good in (("i" * 16, True), ("i" * 17, False), ("a b", False), ("a.b", False), ("a-b_c", True), ("integration", False), ("INTEGRATION", False), ("Integration", False)):
        s = spec()
        s["lanes"][0]["id"] = lid
        s["lanes"][1]["depends_on"] = []  # the other lanes no longer name L1
        s["shared"] = []
        if good:
            ok(s)
        else:
            bad(s, "lanes[0].id")
    s = spec()
    s["lanes"][1]["id"] = "l1"  # equal ignoring case
    s["lanes"][1]["depends_on"] = []
    s["shared"] = []
    bad(s, "lanes[1].id", "DUPLICATE")
    owner = [lane(tmp_path, "L0", "agent/demo/l0", ["src/"])]
    ok(spec(lanes=owner, shared=[{"path": "src/f%d.py" % j, "owner": "L0"} for j in range(64)]))
    bad(spec(lanes=owner, shared=[{"path": "src/f%d.py" % j, "owner": "L0"} for j in range(65)]), "shared", "RANGE")
    twelve = lanes_n(12)
    twelve[11]["depends_on"] = ["L%d" % i for i in range(11)]
    ok(spec(lanes=twelve))
    twelve[11]["depends_on"] = ["L%d" % i for i in range(11)] + ["L0"]
    bad(spec(lanes=twelve), "lanes[11].depends_on", "RANGE")
    # the size of the spec: 4,194,304 bytes read, one more is refused without parsing
    body = json.dumps(spec()).encode("utf-8")
    ok(body + b" " * (4194304 - len(body)), "max.json")
    parsed = []
    real = G._loads
    monkeypatch.setattr(G, "_loads", lambda text: parsed.append(1) or real(text))
    rc, v = dry(guard, demo, tmp_path, body + b" " * (4194305 - len(body)), "over.json")
    assert rc == 24 and ("spec", "TOO_LARGE") in errors_of(v) and parsed == [] and not store_dir(demo).exists()
    rc, v = dry(guard, demo, tmp_path, body + b" " * (6000000 - len(body)), "huge.json")  # reading stops at 4,194,305 bytes
    assert rc == 24 and ("spec", "TOO_LARGE") in errors_of(v) and parsed == []
    r = guard(demo, "--json", *sp_args("-", "demo", "main", "--dry-run"), stdin=body + b" " * (4194305 - len(body)))
    assert r.rc == 24 and ("spec", "TOO_LARGE") in errors_of(json.loads(r.out)) and parsed == []


def test_invalid_spec_messages_name_the_field(demo, guard, tmp_path):
    base = demo_spec(demo, tmp_path)
    text = json.dumps(base)

    def derived(**changes):
        s = json.loads(text)
        for k, v in changes.items():
            if v is KeyError:
                del s[k]
            else:
                s[k] = v
        return s

    def check(payload, field, code, name="inv.json"):
        rc, v = dry(guard, demo, tmp_path, payload, name)
        assert rc == 24 and v["code"] == "INVALID_SPEC" and set(v) == COMMON_KEYS | {"errors"} and (field, code) in errors_of(v), (field, code, v)
        assert not store_dir(demo).exists()
        return v
    check(derived(v=KeyError), "v", "MISSING")
    check(derived(v=2), "v", "UNSUPPORTED_VERSION")
    check(text.replace('"v": 1', '"v": ' + "9" * 5000, 1), "v", "UNSUPPORTED_VERSION")
    for bad in (True, "1", 1.0, None, [1]):
        check(derived(v=bad), "v", "TYPE")
    check(derived(extra=1), "extra", "UNKNOWN_KEY")
    s = derived()
    s["lanes"][0]["nope"] = 1
    check(s, "lanes[0].nope", "UNKNOWN_KEY")
    s = derived()
    s["shared"][0]["nope"] = 1
    check(s, "shared[0].nope", "UNKNOWN_KEY")
    check(derived(notes="x"), "notes", "TYPE")
    check(derived(title=["x"]), "title", "TYPE")
    check(derived(lanes="x"), "lanes", "TYPE")
    check(derived(lanes=[]), "lanes", "RANGE")
    check(derived(base=5), "base", "TYPE")
    check(derived(notes=[5]), "notes[0]", "TYPE")
    check(derived(shared="x"), "shared", "TYPE")
    check(derived(shared=[5]), "shared[0]", "TYPE")
    s = derived()
    s["shared"][0].update(path=5, owner=5)
    check(s, "shared[0].path", "TYPE")
    check(s, "shared[0].owner", "UNKNOWN_LANE")
    for field, value, where, code in (("paths", [5, "ok/", "src/\ud800"], "lanes[0].paths[0]", "TYPE"), ("paths", [5, "ok/", "src/\ud800"], "lanes[0].paths[2]", "ENCODING"),
                                      ("worktree", 5, "lanes[0].worktree", "TYPE"), ("worktree", "C:/x\ud800", "lanes[0].worktree", "ENCODING"),
                                      ("branch", "a\x01b", "lanes[0].branch", "FORMAT"), ("branch", 5, "lanes[0].branch", "TYPE"), ("depends_on", "L1", "lanes[0].depends_on", "TYPE"),
                                      ("depends_on", [5], "lanes[0].depends_on[0]", "UNKNOWN_LANE"), ("id", 5, "lanes[0].id", "TYPE"), ("id", "a\ud800", "lanes[0].id", "ENCODING")):
        s = derived()
        s["lanes"][0][field] = value
        s["lanes"][1]["depends_on"] = []
        s["shared"] = []
        check(s, where, code)
    s = derived()
    s["lanes"][0]["paths"] = "src/"
    check(s, "lanes[0].paths", "TYPE")
    s = derived()
    s["lanes"][0] = [1]
    check(s, "lanes[0]", "TYPE")
    check('{"v": 1, ' + text[1:], "v", "DUPLICATE")
    check(text.replace('{"id": "L1",', '{"id": "L1", "id": "L1",', 1), "lanes[0].id", "DUPLICATE")
    check(text.replace('"notes": ["note one"]', '"notes": [NaN]'), "spec", "JSON")
    check(text.replace('"notes": ["note one"]', '"notes": [Infinity]'), "spec", "JSON")
    check("[1, 2]", "spec", "TYPE")
    check("", "spec", "JSON")
    check("{", "spec", "JSON")
    check(b'{"v": 1, "title": "caf\xe9"}', "spec", "ENCODING")
    check("[" * 100000, "spec", "JSON")  # nesting no parser reads
    check(text.replace('"title": "Demo"', '"title": "\\ud800"'), "title", "ENCODING")
    check(text.replace('"title": "Demo"', '"title": "a\\u0001b"'), "title", "FORMAT")
    check(text.replace('"title": "Demo"', '"title": "a\\nb"'), "title", "FORMAT")  # only the sheet may hold a newline
    for encoded in (text.encode("utf-16"), b"\xef\xbb\xbf" + text.encode("utf-8")):  # PowerShell 5.1 writes UTF-16 with a BOM
        rc, v = dry(guard, demo, tmp_path, encoded, "enc.json")
        assert rc == 0 and v["code"] == "OK", v
    many = derived()
    many.update({"k%02d" % i: i for i in range(25)})
    rc, v = dry(guard, demo, tmp_path, many, "many.json")
    assert rc == 24 and len(v["errors"]) == 20 and all(e["code"] == "UNKNOWN_KEY" for e in v["errors"])
    lines = v["message"].splitlines()
    assert lines[0] == "MAGOS: the set plan is invalid, nothing registered or created:" and len(lines) == 22
    assert lines[1].strip() == "[UNKNOWN_KEY] k00: not a key of the spec" and lines[-1].strip() == "... and 5 more"
    zh = run(["--repo", str(demo.path), "--lang", "zh", *sp_args(write_spec(tmp_path, many, "many.json"), "demo", "main", "--dry-run")])
    assert zh.rc == 24 and zh.out.startswith("MAGOS：set 规划无效，未登记也未创建任何东西：") and "[UNKNOWN_KEY] k00" in zh.out and zh.err == ""
    both = derived(v=2, title="")
    both["lanes"][0]["nope"] = 1
    v = check(both, "v", "UNSUPPORTED_VERSION")
    assert {("title", "RANGE"), ("lanes[0].nope", "UNKNOWN_KEY")} <= errors_of(v)  # the errors of every field are collected


def test_spec_from_file_stdin_and_inside_a_worktree(demo, guard, tmp_path):
    spec = demo_spec(demo, tmp_path)
    text = json.dumps(spec)
    via_file = dry(guard, demo, tmp_path, spec, "file.json")
    assert via_file[0] == 0
    for payload in (text.encode("utf-8"), b"\xef\xbb\xbf" + text.encode("utf-8"), text.encode("utf-16")):  # a PowerShell-style pipe writes UTF-16
        r = guard(demo, "--json", *sp_args("-", "demo", "main", "--dry-run"), stdin=payload)
        assert r.rc == 0 and json.loads(r.out) == via_file[1], r
    real = guard(demo, "--json", *sp_args("-"), stdin=text.encode("utf-8"))
    assert real.rc == 0 and record(demo)["base"] == spec["base"]  # stdin registers as well
    other = make_repo(tmp_path, "other")
    linked = tmp_path / "linkedwt"
    other.git("worktree", "add", "-q", "-b", "agent/linked", str(linked), "main")
    lane_wt = Path(spec["lanes"][0]["worktree"])
    lane_wt.mkdir(parents=True)
    ospec = demo_spec(other, tmp_path)
    for where in (other.path, linked, lane_wt):
        f = where / "inside.json"
        f.write_text(json.dumps(ospec), encoding="utf-8")
        rc, v = jplan(guard, other, f, "--dry-run")
        assert rc == 24 and v["errors"][0]["field"] == "--spec" and v["errors"][0]["code"] == "SPEC_IN_WORKTREE" and not store_dir(other).exists(), (where, v)
        assert "write it elsewhere, or pass -" in v["errors"][0]["text"]
    assert plan_ok(guard, other, write_spec(tmp_path, ospec, "okfile.json"), "--dry-run")["code"] == "OK"  # the same spec outside every worktree
    for target in (tmp_path / "does-not-exist.json", tmp_path / "specs"):  # a missing file, a directory
        rc, v = jplan(guard, other, target, "--dry-run")
        assert rc == 24 and v["errors"][0]["field"] == "--spec" and not store_dir(other).exists(), (target, v)
    if os.name != "nt":
        locked = write_spec(tmp_path, ospec, "locked.json")
        locked.chmod(0)
        if not os.access(str(locked), os.R_OK):  # not root
            rc, v = jplan(guard, other, locked, "--dry-run")
            assert rc == 24 and v["errors"][0]["field"] == "--spec"
        locked.chmod(0o600)


def test_shared_paths(demo, guard, tmp_path):
    def spec(shared, l1=("src/dir/", "gl/*.py", "lit/file.txt")):
        s = demo_spec(demo, tmp_path, shared=shared)
        s["lanes"] = [lane(tmp_path, "L1", "agent/demo/api", list(l1)), lane(tmp_path, "L2", "agent/demo/ui", ["other/"])]
        return s
    inside = [{"path": "src/dir/a.py", "owner": "L1"}, {"path": "gl/a.py", "owner": "L1"}, {"path": "lit/file.txt", "owner": "L1"}]
    v = plan_ok(guard, demo, write_spec(tmp_path, spec(inside)))
    assert record(demo)["shared"] == inside  # inside by a directory entry, by a glob entry and by the literal file
    cases = [([{"path": "other/x.py", "owner": "L1"}], "shared[0].path", "NOT_IN_OWNER"), ([{"path": "elsewhere/x.py", "owner": "L1"}], "shared[0].path", "NOT_IN_OWNER"),
             ([{"path": "src/dir/a.py", "owner": "L9"}], "shared[0].owner", "UNKNOWN_LANE"), ([{"path": "src/dir/a.py", "owner": "l1"}], "shared[0].owner", "UNKNOWN_LANE"),
             ([{"path": "src/dir/*.py", "owner": "L1"}], "shared[0].path", "BAD_GLOB"), ([{"path": "src/dir/?.py", "owner": "L1"}], "shared[0].path", "BAD_GLOB"),
             ([{"path": "src/dir/", "owner": "L1"}], "shared[0].path", "BAD_GLOB"),
             ([{"path": "src/dir/a.py", "owner": "L1"}, {"path": "SRC/DIR/A.PY", "owner": "L1"}], "shared[1].path", "DUPLICATE"),
             ([{"path": "/etc/x", "owner": "L1"}], "shared[0].path", "ABSOLUTE"), ([{"path": "src/../x", "owner": "L1"}], "shared[0].path", "DOTDOT"),
             ([{"path": "", "owner": "L1"}], "shared[0].path", None)]
    other = make_repo(tmp_path, "other")
    for shared, field, code in cases:
        s = spec(shared)
        s["base"] = other.git("rev-parse", "main")
        rc, v = dry(guard, other, tmp_path, s, "sh.json")
        assert rc == 24 and field in {e["field"] for e in v["errors"]} and (code is None or (field, code) in errors_of(v)), (shared, v)
        assert not store_dir(other).exists()
    s = spec([{"path": "src/c", "owner": "L1"}], l1=("src/c/x.py",))  # the file src/c is not inside the manifest src/c/x.py
    s["base"] = other.git("rev-parse", "main")
    rc, v = dry(guard, other, tmp_path, s, "sh.json")
    assert rc == 24 and ("shared[0].path", "NOT_IN_OWNER") in errors_of(v)
    s = spec([{"path": "src/c/x.py", "owner": "L1"}], l1=("src/c/x.py",))
    s["base"] = other.git("rev-parse", "main")
    assert dry(guard, other, tmp_path, s, "sh.json")[0] == 0


def test_lane_manifest_entries(demo, guard, tmp_path):
    def one(paths, name="m.json"):
        s = demo_spec(demo, tmp_path, shared=[])
        s["lanes"] = [lane(tmp_path, "L1", "agent/demo/api", paths)]
        return dry(guard, demo, tmp_path, s, name)
    cases = [(["/abs/x"], "ABSOLUTE"), (["../x"], "DOTDOT"), (["a/../b"], "DOTDOT"), ([".git"], "GITDIR"), ([".git/config"], "GITDIR"), ([":(glob)x"], "MAGIC"), (["!x"], "MAGIC"),
             (["**"], "UNIVERSAL"), (["*/*"], "UNIVERSAL"), ([""], "EMPTY"), (["d/" + "/".join(["x" * 200] * 6)], "TOO_LONG")]
    for paths, code in cases:
        rc, v = one(paths)
        assert rc == 24 and ("lanes[0].paths[0]", code) in errors_of(v), (paths, v)
    rc, v = one(["ok/", "../bad", "", "/abs"])
    assert rc == 24 and {("lanes[0].paths[1]", "DOTDOT"), ("lanes[0].paths[2]", "EMPTY"), ("lanes[0].paths[3]", "ABSOLUTE")} <= errors_of(v)  # every bad entry is named by its index
    nfd = unicodedata.normalize("NFD", "café/x")
    paths = ["a\\b", "a/b", "Src/A", "src/a", "# not a comment", nfd, "  padded/dir/  ", "padded/dir"]
    v = plan_ok(guard, demo, write_spec(tmp_path, dict(demo_spec(demo, tmp_path, shared=[]), lanes=[lane(tmp_path, "L1", "agent/demo/api", paths)])))
    stored = record(demo)["lanes"][0]["paths"]
    assert stored == v["lanes"][0]["entries"]
    # entries equal after normalisation (separators, case and Unicode folded) collapse into the first; blanks are stripped; a `#` starts a path, no comment
    assert stored == ["a\\b", "Src/A", "# not a comment", nfd, "padded/dir/"]
    lines = claim_lines(demo, "agent/demo/api")
    assert [x[6:] for x in lines if x.startswith("entry=")] == stored  # the claim's entry lines equal the record's paths


# ---- TC-286 .. TC-292: outputs, targets, plain commands, one snapshot, existing branches, the base, the record ---------------------------
EXIT_NAMES = {0: "OK", 10: "CONFLICT", 11: "UNKNOWN", 12: "INVALID_MANIFEST", 13: "LOCK_TIMEOUT", 14: "LANE_EXISTS", 15: "BRANCH_EXISTS", 16: "BLOCKED", 19: "STALE",
              20: "SET_EXISTS", 21: "SET_UNKNOWN", 22: "OUT_OF_LANE", 23: "SET_NEWER_FORMAT", 24: "INVALID_SPEC"}
EXIT_KEYS = {0: OK_KEYS, 10: COMMON_KEYS | {"overlaps"}, 12: COMMON_KEYS | {"errors"}, 13: COMMON_KEYS, 14: COMMON_KEYS | {"errors"}, 15: COMMON_KEYS | {"errors"},
             16: COMMON_KEYS | {"blocked"}, 19: COMMON_KEYS | {"kind", "expected", "current"}, 20: COMMON_KEYS | {"current"}, 21: COMMON_KEYS, 23: COMMON_KEYS,
             22: COMMON_KEYS | {"lane", "files", "truncated"}, 24: COMMON_KEYS | {"errors"}}


def fast_branches(repo, count, prefix="feature/b", under="zz"):
    """`count` local branches, each one commit ahead of main that adds the file <under>/<name>.txt (one git process: fast-import)."""
    lines = []
    for i in range(count):
        body = "branch %d\n" % i
        lines += ["commit refs/heads/%s%02d" % (prefix, i), "committer t <t@example.invalid> %d +0000" % (1700000000 + i), "data 3", "msg", "from refs/heads/main^0",
                  "M 100644 inline %s/%s%02d.txt" % (under, prefix.replace("/", "_"), i), "data %d" % len(body), body.rstrip("\n"), ""]
    sub(["git", "fast-import", "--quiet"], cwd=str(repo.path), input=("\n".join(lines) + "\n").encode("utf-8"), capture_output=True)


def test_json_text_and_language_outputs(tmp_path, guard, monkeypatch):
    import contextlib

    def fresh(name):
        r = make_repo(tmp_path, name)
        return r, write_spec(tmp_path, demo_spec(r, tmp_path), name + ".json")

    def registered(name):
        r, f = fresh(name)
        plan_ok(guard, r, f)
        return r, f

    def amend_args(f, rev="1"):
        return sp_args(f, "demo", "main", "--amend", "--expect-revision", rev)
    def norm(text):
        return re.sub(r"[0-9a-f]{40}", "<sha>", text)
    scenarios = {}  # name -> (repo, args, exit code, context manager or None, the zh and the en text that must appear)
    ok_keys = {}  # the keys of the success of a scenario that is not a set-plan

    made = [fresh("s_ok%d" % i) for i in range(6)]  # a registration and an amendment write: each of the six calls gets a repository of its own
    scenarios["registered"] = ([m[0] for m in made], [sp_args(m[1]) for m in made], 0, None, ("已登记 set「demo」", "registered set 'demo'"))
    r, f = fresh("s_preview")
    scenarios["previewed"] = (r, sp_args(f, "demo", "main", "--dry-run"), 0, None, ("预览通过", "preview passed"))
    r, f = registered("s_unchanged")
    scenarios["unchanged"] = (r, amend_args(f), 0, None, ("没有变化", "is unchanged"))
    made = [registered("s_amended%d" % i) for i in range(6)]
    amended = []
    for i, (r, f) in enumerate(made):
        s = demo_spec(r, tmp_path)
        s["lanes"][2]["paths"] = ["docs/", "notes/"]
        amended.append(amend_args(write_spec(tmp_path, s, "s_amended2_%d.json" % i)))
    scenarios["amended"] = ([m[0] for m in made], amended, 0, None, ("已修改 set「demo」", "amended set 'demo'"))
    r, f = fresh("s_overlap")
    s = demo_spec(r, tmp_path)
    s["lanes"][2]["paths"] = ["src/ui/"]
    scenarios["overlap"] = (r, sp_args(write_spec(tmp_path, s, "s_overlap2.json")), 10, None, ("manifest 重叠", "overlap"))
    r, f = fresh("s_unknown_target")
    scenarios["target-uncertain"] = (r, sp_args(f, "demo", "nope"), 11, None, ("TARGET_UNCERTAIN", "TARGET_UNCERTAIN"))
    r, f = registered("s_unreadable")
    (store_dir(r) / "sets" / "demo.json").write_bytes(b"{")
    scenarios["record-unreadable"] = (r, sp_args(f), 11, None, ("无法读取", "cannot be read"))
    r, f = fresh("s_branch")
    r.git("branch", "topic", "main")
    s = demo_spec(r, tmp_path)
    s["lanes"][0]["branch"] = "topic/sub"
    scenarios["name-clash"] = (r, sp_args(write_spec(tmp_path, s, "s_branch2.json")), 12, None, ("set 规划无效", "the set plan is invalid"))
    r, f = registered("s_lock")

    @contextlib.contextmanager
    def locked(repo=r):
        monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "1")
        release = holding_lock(repo)
        try:
            yield
        finally:
            release()
            monkeypatch.delenv("MAGOS_LOCK_TIMEOUT")
    scenarios["lock-timeout"] = (r, amend_args(f), 13, locked, ("清单锁", "claim lock"))
    r, f = fresh("s_foreign")
    assert guard(r, "plan", "--branch", "agent/demo/ui", "--paths", "web/").rc == 0
    scenarios["foreign-claim"] = (r, sp_args(f), 14, None, ("不属于这个 set 的登记", "not this set's"))
    r, f = fresh("s_exists")
    r.git("branch", "agent/demo/docs", "main")
    scenarios["branch-exists"] = (r, sp_args(f), 15, None, ("没有有效登记", "without a claim"))
    r, f = registered("s_blocked")
    r.git("worktree", "add", "-q", "-b", "agent/demo/ui", str(tmp_path / "wt" / "l2"), "main")
    r.commit("src/ui/y.py", "y\n", cwd=tmp_path / "wt" / "l2", msg="l2")
    s = demo_spec(r, tmp_path)
    del s["lanes"][1]
    for x in s["lanes"]:
        x["depends_on"] = []
    scenarios["blocked"] = (r, amend_args(write_spec(tmp_path, s, "s_blocked2.json")), 16, None, ("拒绝", "refused"))
    r, f = fresh("s_stale")
    old = r.git("rev-parse", "main")
    r.commit("README.md", "moved\n")
    scenarios["stale"] = (r, sp_args(write_spec(tmp_path, demo_spec(r, tmp_path, base=old), "s_stale2.json")), 19, None, ("计划已过期", "the plan is stale"))
    r, f = registered("s_exists2")
    scenarios["set-exists"] = (r, sp_args(f), 20, None, ("已存在", "already exists"))
    r, f = fresh("s_unknown")
    scenarios["set-unknown"] = (r, amend_args(f), 21, None, ("没有名为", "there is no set named"))
    r, f = registered("s_newer")
    (store_dir(r) / "sets" / "demo.json").write_bytes(b'{"v": 2}')
    scenarios["record-newer"] = (r, sp_args(f), 23, None, ("更新版本", "newer MAGOS"))
    r, f = fresh("s_invalid")
    scenarios["invalid-spec"] = (r, sp_args(write_spec(tmp_path, {"v": 2}, "s_invalid2.json")), 24, None, ("set 规划无效", "the set plan is invalid"))
    # set-show, set-update and set-release
    def newer(r):
        (store_dir(r) / "sets" / "demo.json").write_bytes(b'{"v": 2}')
        return r

    def unreadable(r):
        (store_dir(r) / "sets" / "demo.json").write_bytes(b"{")
        return r

    def lock_on(repo):
        return lambda: locked(repo)
    r, _ = registered("s_show")
    ok_keys["show"] = SHOW_KEYS
    scenarios["show"] = (r, ["set-show", "--set", "demo"], 0, None, ("set「demo」→ main", "set 'demo' -> main"))
    scenarios["show-drift"] = (r, ["set-show", "--set", "demo", "--drift"], 0, None, ("合并顺序：L1 -> L2 -> L3", "merge order: L1 -> L2 -> L3"))
    ok_keys["show-drift"] = SHOW_KEYS
    r, _ = fresh("s_show_none")
    scenarios["show-unknown"] = (r, ["set-show", "--set", "demo"], 21, None, ("没有名为", "there is no set named"))
    scenarios["show-newer"] = (newer(registered("s_show_newer")[0]), ["set-show", "--set", "demo"], 23, None, ("更新版本", "newer MAGOS"))
    scenarios["show-unreadable"] = (unreadable(registered("s_show_bad")[0]), ["set-show", "--set", "demo"], 11, None, ("无法读取", "cannot be read"))
    made = [registered("s_upd%d" % i)[0] for i in range(6)]
    ok_keys["update"] = UPDATE_KEYS
    scenarios["update"] = (made, [update_args("L1", "active", 1)] * 6, 0, None, ("的 lane L1 现在是 active，修订 2", "lane L1 of set 'demo' is now active, revision 2"))
    r, _ = registered("s_upd_blocked")
    assert guard(r, *update_args("L1", "active", 1)).rc == 0
    scenarios["update-blocked"] = (r, update_args("L1", "ready", 2, "--head", r.git("rev-parse", "main")), 16, None, ("拒绝 set-update", "set-update refused"))
    r, _ = registered("s_upd_outside")
    tip = fast_commit(r, LANES["L1"], {"src/ui/x.py": "x\n"})
    assert guard(r, *update_args("L1", "active", 1)).rc == 0
    scenarios["update-outside"] = (r, update_args("L1", "ready", 2, "--head", tip), 22, None, ("拒绝把 lane L1 标记为 ready", "refused to mark lane L1 ready"))
    r, _ = registered("s_upd_stale")
    scenarios["update-stale"] = (r, update_args("L1", "active", 5), 19, None, ("计划已过期", "the plan is stale"))
    r, _ = fresh("s_upd_none")
    scenarios["update-unknown"] = (r, update_args("L1", "active", 1), 21, None, ("没有名为", "there is no set named"))
    r, _ = registered("s_upd_invalid")
    scenarios["update-invalid"] = (r, update_args("L1", "active", 1, "--note", "x" * 201), 24, None, ("set 规划无效", "the set plan is invalid"))
    scenarios["update-newer"] = (newer(registered("s_upd_newer")[0]), update_args("L1", "active", 1), 23, None, ("更新版本", "newer MAGOS"))
    scenarios["update-unreadable"] = (unreadable(registered("s_upd_bad")[0]), update_args("L1", "active", 1), 11, None, ("无法读取", "cannot be read"))
    r, _ = registered("s_upd_lock")
    scenarios["update-lock"] = (r, update_args("L1", "active", 1), 13, lock_on(r), ("清单锁", "claim lock"))
    made = [registered("s_rel%d" % i)[0] for i in range(6)]
    ok_keys["release"] = RELEASE_KEYS
    scenarios["release"] = (made, [["set-release", "--set", "demo", "--abandon"]] * 6, 0, None, ("已释放 set「demo」及其 4 份登记", "released set 'demo' and its 4 claims"))
    r, _ = registered("s_rel_blocked")
    scenarios["release-blocked"] = (r, ["set-release", "--set", "demo"], 16, None, ("拒绝 set-release", "set-release refused"))
    r, _ = fresh("s_rel_none")
    scenarios["release-unknown"] = (r, ["set-release", "--set", "demo"], 21, None, ("没有名为", "there is no set named"))
    scenarios["release-newer"] = (newer(registered("s_rel_newer")[0]), ["set-release", "--set", "demo"], 23, None, ("更新版本", "newer MAGOS"))
    scenarios["release-unreadable"] = (unreadable(registered("s_rel_bad")[0]), ["set-release", "--set", "demo"], 11, None, ("无法读取", "cannot be read"))
    r, _ = registered("s_rel_lock")
    scenarios["release-lock"] = (r, ["set-release", "--set", "demo"], 13, lock_on(r), ("清单锁", "claim lock"))
    for name, (repos, argses, rc, ctx, (zh_text, en_text)) in scenarios.items():
        def at(i, repos=repos, argses=argses):
            return (repos[i] if isinstance(repos, list) else repos), (argses[i] if isinstance(argses[0], list) else argses)
        manager = ctx() if ctx else contextlib.nullcontext()
        with manager:
            first = guard(at(0)[0], "--json", *at(0)[1])  # the global options before the subcommand
            second = guard(at(1)[0], *at(1)[1], "--json")  # and after it
            text = guard(at(2)[0], *at(2)[1])
            zh = run(["--repo", str(at(3)[0].path), *at(3)[1]])  # the default language is zh
            monkeypatch.setenv("MAGOS_LANG", "en")
            env_en = run(["--repo", str(at(4)[0].path), *at(4)[1]])
            monkeypatch.delenv("MAGOS_LANG")
            zh_flag = run(["--repo", str(at(5)[0].path), "--lang", "zh", *at(5)[1]])
        v = json.loads(first.out)
        assert first.rc == rc and v["exit_code"] == rc and v["code"] == EXIT_NAMES[rc] and G.EXIT[v["code"]] == rc, (name, first)
        assert v["decision"] == ("allow" if rc == 0 else "deny") and first.err == "", (name, first)
        same = not isinstance(repos, list)  # the six calls of a registration or an amendment ran in six repositories: only their shas differ
        assert second.rc == rc and (json.loads(second.out) == v if same else set(json.loads(second.out)) == set(v)), name
        if rc == 11:
            assert set(v) in (COMMON_KEYS | {"unknowns"}, COMMON_KEYS | {"lanes"}) and v["unknowns"][0]["code"] in (
                "TARGET_UNCERTAIN", "SET_UNREADABLE", "BUDGET_EXCEEDED", "GIT_FAILED", "INTERNAL_ERROR"), (name, v)
        else:
            assert set(v) == ok_keys.get(name, EXIT_KEYS[rc]), (name, sorted(v))
        for other in (text, zh, env_en, zh_flag):
            assert other.rc == rc and other.err == "", (name, other)
        assert norm(text.out.rstrip("\n")) == norm(v["message"]) and norm(env_en.out) == norm(text.out)  # the text is the message
        assert en_text in text.out and zh_text in zh.out and norm(zh.out) == norm(zh_flag.out) and (zh_text == en_text or zh_text not in text.out), (name, text.out, zh.out)
        if rc == 0:
            assert v["warnings"] == [] or {w["code"] for w in v["warnings"]} <= {"NOT_ARMED", "REMOTE_AS_OF_LAST_FETCH", "TARGET_INFERRED"}
    # a repository that is not armed: the warning follows a success, as a line of the text and as a JSON entry
    r, f = fresh("s_warn")
    rc, v = jplan(guard, r, f, "--dry-run")
    assert [w["code"] for w in v["warnings"]] == ["NOT_ARMED"] and v["message"].splitlines()[-1].startswith("(NOT_ARMED) ")
    assert guard(r, *sp_args(f, "demo", "main", "--dry-run")).out.splitlines()[-1].startswith("(NOT_ARMED) parallel lanes exist")
    assert guard(r, "arm").rc == 0
    assert jplan(guard, r, f, "--dry-run")[1]["warnings"] == []
    r.git("config", "core.hooksPath", str(tmp_path / "hooks-elsewhere"))
    assert [w["code"] for w in jplan(guard, r, f, "--dry-run")[1]["warnings"]] == ["HOOK_BYPASSED"]
    # a Git failure is the deny object of exit 11 under --json, and a line on stderr
    r, f = fresh("s_gitfail")
    monkeypatch.setattr(G, "gather", lambda *a, **k: (_ for _ in ()).throw(G.GitFail("GIT_FAILED", "git status: boom")))
    out = guard(r, "--json", *sp_args(f))
    v = json.loads(out.out)
    assert out.rc == 11 and v["decision"] == "deny" and v["unknowns"][0]["code"] == "GIT_FAILED" and set(v) == COMMON_KEYS | {"unknowns"} and v["exit_code"] == 11
    assert out.err.replace("\r", "") == "MAGOS guard: GIT_FAILED: git status: boom\n"
    plain = guard(r, *sp_args(f))
    assert plain.rc == 11 and plain.out == "" and plain.err.replace("\r", "") == "MAGOS guard: GIT_FAILED: git status: boom\n"
    assert store_files(r) in (None, {})
    usage = guard(r, "set-plan", "--set", "demo", "--target", "main")
    assert usage.rc == 2 and usage.out == "" and "--spec" in usage.err


def test_the_target_must_be_a_local_branch_at_the_resolved_tip(tmp_path, guard):
    r = make_repo(tmp_path, "t1")
    bare = tmp_path / "origin.git"
    sub(["git", "clone", "-q", "--bare", str(r.path), str(bare)], capture_output=True)
    r.git("remote", "add", "origin", str(bare))
    r.git("fetch", "-q", "origin")
    tip = r.git("rev-parse", "main")

    def attempt(base, target="main", name="t.json", repo=r, *extra):
        return jplan(guard, repo, write_spec(tmp_path, demo_spec(repo, tmp_path, base=base), name), "--dry-run", *extra, target=target)

    def uncertain(rc_v, why=None):
        rc, v = rc_v
        assert rc == 11 and v["code"] == "UNKNOWN" and v["unknowns"][0]["code"] == "TARGET_UNCERTAIN" and set(v) == COMMON_KEYS | {"unknowns"}, v
        assert why is None or why in v["unknowns"][0]["text"], v
    rc, v = attempt(tip)  # the same tip locally and on the remote: registers
    assert rc == 0 and v["target"] == {"name": "main", "sha": tip}
    r.git("push", "-q", "origin", "main:refs/heads/feature")
    r.git("fetch", "-q", "origin")
    uncertain(attempt(tip, "feature"), "not a local branch")  # a target that exists only as a remote-tracking ref
    uncertain(attempt(tip, "nope"), "not a local branch")
    clone = tmp_path / "c2"
    sub(["git", "clone", "-q", str(bare), str(clone)], capture_output=True)
    c2 = SetsRepo(clone)
    c2.commit("remote.txt", "r\n", msg="remote")
    c2.git("push", "-q", "origin", "main")
    r.git("fetch", "-q", "origin")
    ahead = r.git("rev-parse", "origin/main")
    assert ahead != tip
    uncertain(attempt(tip), "behind or diverged")  # the base equals the local tip while origin/main is ahead
    uncertain(attempt(ahead), "behind or diverged")
    r.commit("local.txt", "l\n", msg="local")  # local and remote diverged
    uncertain(attempt(r.git("rev-parse", "main")))
    assert store_files(r) in (None, {})
    # develop is the target while main is checked out; the claims record the target's name
    r2 = make_repo(tmp_path, "t2")
    r2.git("branch", "develop", "main")
    dev = r2.git("rev-parse", "develop")
    f = write_spec(tmp_path, demo_spec(r2, tmp_path, base=dev), "dev.json")
    v = plan_ok(guard, r2, f, target="develop")
    assert v["target"] == {"name": "develop", "sha": dev} and v["lanes"][0]["create"].endswith(" develop")
    assert "target=develop" in claim_lines(r2, "agent/demo/api") and record(r2)["target"] == "develop"
    # a linked worktree as --repo resolves the same store
    r3 = make_repo(tmp_path, "t3")
    linked = tmp_path / "area3"
    r3.git("worktree", "add", "-q", "-b", "agent/other", str(linked), "main")
    f3 = write_spec(tmp_path, demo_spec(r3, tmp_path), "t3.json")
    out = guard(SetsRepo(linked), "--json", *sp_args(f3))
    assert out.rc == 0, out
    assert (store_dir(r3) / "sets" / "demo.json").is_file() and (store_dir(r3) / "claims" / "agent" / "demo" / "api.claim").is_file()


def test_plain_plan_and_release_refuse_set_claims(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    before = store_files(demo)
    same = guard(demo, "plan", "--branch", "agent/demo/api", "--paths", "src/api/", "tests/api/", "package-lock.json")
    assert same.rc == 0 and store_files(demo) == before  # identical entries: a no-op
    for extra in ((), ("--amend",)):
        for paths in (["src/other/"], ["src/api/", "tests/api/"]):
            r = guard(demo, "plan", "--branch", "agent/demo/api", "--paths", *paths, *extra)
            assert r.rc == 14 and r.out.rstrip("\n") == ("MAGOS: branch 'agent/demo/api' is a lane of set 'demo'; its claim cannot be changed on its own. "
                                                           "Use set-plan --amend, or set-release first."), (extra, paths, r)
            assert store_files(demo) == before
    zh = run(["--repo", str(demo.path), "--lang", "zh", "plan", "--branch", "agent/demo/api", "--paths", "x/"])
    assert zh.rc == 14 and "是 set「demo」的 lane" in zh.out
    for branch in ("agent/demo/docs", "agent/demo/integration", "AGENT/demo/docs", "agent\\demo\\docs"):
        r = guard(demo, "release", "--branch", branch)
        assert r.rc == 16 and r.out == "" and "belongs to set 'demo'. Retire the whole set with set-release." in r.err, (branch, r)
        assert "release refused: '%s' belongs" % ("agent/demo/integration" if branch.endswith("integration") else "agent/demo/docs") in r.err
        assert store_files(demo) == before
    zr = run(["--repo", str(demo.path), "--lang", "zh", "release", "--branch", "agent/demo/docs"])
    assert zr.rc == 16 and "请用 set-release 一并释放" in zr.err
    checked = guard(demo, "--json", "check", "--branch", "feature/x", "--paths", "src/api/new.py")
    v = json.loads(checked.out)
    assert checked.rc == 10 and v["conflicts"][0]["branch"] == "agent/demo/api" and v["conflicts"][0]["evidence"][0]["kind"] == "declared"
    assert store_files(demo) == before  # check writes nothing
    (store_dir(demo) / "sets" / "demo.json").unlink()  # the record is gone: the claims are orphans, released like any claim
    for branch in ("agent/demo/integration", "agent/demo/docs"):
        r = guard(demo, "release", "--branch", branch)
        assert r.rc == 0 and "released the claim" in r.out, (branch, r)
    assert not (store_dir(demo) / "claims" / "agent" / "demo" / "docs.claim").exists() and not (store_dir(demo) / "claims" / "agent" / "demo" / "integration.claim").exists()
    again = guard(demo, "plan", "--branch", "agent/demo/api", "--paths", "src/other/", "--amend")
    assert again.rc == 0  # without a record the claim of a lane is an ordinary claim
    assert "set=demo" in claim_lines(demo, "agent/demo/api")  # the amend keeps the keys it does not know


def test_one_snapshot_serves_every_lane(tmp_path, guard, monkeypatch):
    def twelve(repo, name):
        s = demo_spec(repo, tmp_path, shared=[])
        s["lanes"] = [lane(tmp_path, "L%d" % i, "agent/demo/l%d" % i, ["d%d/" % i]) for i in range(1, 13)]
        return write_spec(tmp_path, s, name + ".json")
    r = make_repo(tmp_path, "snap")
    fast_branches(r, 30)
    assert guard(r, "plan", "--branch", "agent/x3", "--paths", "d3/").rc == 0
    assert guard(r, "plan", "--branch", "agent/x9", "--paths", "d9/x.py").rc == 0
    f = twelve(r, "snap")
    counts = {"gather": 0, "evaluate": 0}
    real_gather, real_evaluate = G.gather, G.evaluate

    def gather(*a, **k):
        counts["gather"] += 1
        return real_gather(*a, **k)

    def evaluate(*a, **k):
        counts["evaluate"] += 1
        return real_evaluate(*a, **k)
    monkeypatch.setattr(G, "gather", gather)
    monkeypatch.setattr(G, "evaluate", evaluate)
    rc, v = jplan(guard, r, f)
    assert rc == 10 and counts == {"gather": 1, "evaluate": 12}, counts  # one snapshot for the whole call, one evaluation per lane
    assert [x["id"] for x in v["lanes"]] == ["L3", "L9"]  # only the offending lanes are named
    assert {x["conflicts"][0]["branch"] for x in v["lanes"]} == {"agent/x3", "agent/x9"} and v["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "declared"
    assert not (store_dir(r) / "sets").exists()
    # only unknowns: lanes 2 and 5 (a verdict the judge gives for them alone) are named, with exit 11
    r2 = make_repo(tmp_path, "snap2")
    f2 = twelve(r2, "snap2")
    real_judge = G.judge

    def judge(snap, claims, bad, name, entries, override):
        v = real_judge(snap, claims, bad, name, entries, override)
        if name in ("agent/demo/l2", "agent/demo/l5"):
            v = dict(v, decision="deny", code="UNKNOWN", unknowns=[{"code": "STATUS_FAILED", "text": "%s: status failed" % name}])
        return v
    monkeypatch.setattr(G, "judge", judge)
    rc, v = jplan(guard, r2, f2)
    assert rc == 11 and v["code"] == "UNKNOWN" and [x["id"] for x in v["lanes"]] == ["L2", "L5"] and v["lanes"][0]["unknowns"][0]["code"] == "STATUS_FAILED"
    assert store_files(r2) in (None, {})
    monkeypatch.setattr(G, "judge", real_judge)
    # an amend: the lanes of the set that already hold work are members of the set, never compared with the lanes
    plan_ok(guard, r2, f2)
    for i in (1, 2):
        wt = tmp_path / "wt" / ("l%d" % i)
        r2.git("worktree", "add", "-q", "-b", "agent/demo/l%d" % i, str(wt), "main")
        r2.commit("d%d/x.py" % i, "x\n", cwd=wt, msg="l%d" % i)
    amend = json.loads(f2.read_text(encoding="utf-8"))
    amend["lanes"][5]["title"] = "retitled"
    counts.update(gather=0, evaluate=0)
    monkeypatch.setattr(G, "gather", gather)
    monkeypatch.setattr(G, "evaluate", evaluate)
    assert plan_ok(guard, r2, write_spec(tmp_path, amend, "snap2b.json"), "--amend", "--expect-revision", "1")["revision"] == 2
    assert counts == {"gather": 1, "evaluate": 12}


def test_existing_lane_and_integration_branches(tmp_path, guard):
    def case(name):
        r = make_repo(tmp_path, name)
        return r, write_spec(tmp_path, demo_spec(r, tmp_path), name + ".json")
    r, f = case("e1")  # a lane branch that exists without a claim, and the integration branch
    r.git("branch", "agent/demo/ui", "main")
    r.git("branch", "agent/demo/integration", "main")
    rc, v = jplan(guard, r, f)
    assert rc == 15 and v["code"] == "BRANCH_EXISTS" and set(v) == COMMON_KEYS | {"errors"} and store_files(r) in (None, {})
    assert {(e["field"], e["code"]) for e in v["errors"]} == {("lanes[1].branch", "BRANCH_EXISTS"), ("integration", "BRANCH_EXISTS")}
    assert "lane L2" in v["message"] and "agent/demo/ui" in v["message"] and "agent/demo/integration" in v["message"]
    r, f = case("e2")  # the target's name as a lane branch is a spec rule
    s = demo_spec(r, tmp_path)
    s["lanes"][0]["branch"] = "main"
    assert jplan(guard, r, write_spec(tmp_path, s, "e2b.json"))[0] == 24
    r, f = case("e3")  # a plain claim on a lane branch, and on the integration branch
    assert guard(r, "plan", "--branch", "agent/demo/docs", "--paths", "elsewhere/").rc == 0
    assert guard(r, "plan", "--branch", "agent/demo/integration", "--paths", "other/").rc == 0
    rc, v = jplan(guard, r, f)
    assert rc == 14 and v["code"] == "LANE_EXISTS" and {e["field"] for e in v["errors"]} == {"lanes[2].branch", "integration"}
    assert "already has a claim that is not this set's" in v["message"]
    assert not (store_dir(r) / "sets").exists() and not (store_dir(r) / "claims" / "agent" / "demo" / "api.claim").exists()  # nothing of the set is written
    r, f = case("e4")  # the remnant of an interrupted registration: claims that carry set=demo while no record exists
    plan_ok(guard, r, f)
    (store_dir(r) / "sets" / "demo.json").unlink()
    rc, v = jplan(guard, r, f)
    assert rc == 14 and len(v["errors"]) == 4
    for branch in ("agent/demo/api", "agent/demo/ui", "agent/demo/docs", "agent/demo/integration"):
        assert guard(r, "release", "--branch", branch).rc == 0
    assert plan_ok(guard, r, f)["revision"] == 1  # the registration succeeds once the remnant is freed
    # an amend: a new lane whose branch has a foreign claim or exists; a surviving lane whose branch exists with the set's own claim
    r.git("branch", "agent/demo/api", "main")  # L1 survives with its branch
    s = json.loads(f.read_text(encoding="utf-8"))
    s["lanes"].append(lane(tmp_path, "L4", "agent/demo/extra", ["extra/"]))
    assert guard(r, "plan", "--branch", "agent/demo/extra", "--paths", "elsewhere2/").rc == 0
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "1")
    assert rc == 14 and [e["field"] for e in v["errors"]] == ["lanes[3].branch"]
    assert guard(r, "release", "--branch", "agent/demo/extra").rc == 0
    r.git("branch", "agent/demo/extra", "main")
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "1")
    assert rc == 15 and [e["field"] for e in v["errors"]] == ["lanes[3].branch"]
    r.git("branch", "-D", "agent/demo/extra")
    assert plan_ok(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "1")["revision"] == 2  # L1's branch exists with the set's claim: fine
    claim = store_dir(r) / "claims" / "agent" / "demo" / "api.claim"  # a claim of a newer format on a lane of the record is the claim gate's, not a foreign claim
    text = claim.read_text(encoding="utf-8")
    claim.write_text(text.replace("v=1", "v=2", 1), encoding="utf-8")
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "2")
    assert rc == 11 and v["code"] == "UNKNOWN" and v["lanes"][0]["unknowns"][0]["code"] == "CLAIM_NEWER_FORMAT" and "v=2" in claim.read_text(encoding="utf-8")
    claim.write_text(text, encoding="utf-8")
    # the first failing kind decides the exit code and every offending lane of that kind is named
    r, f = case("e5")
    r.git("branch", "topic", "main")
    r.git("branch", "agent/demo/ui", "main")
    assert guard(r, "plan", "--branch", "agent/demo/docs", "--paths", "elsewhere/").rc == 0
    s = demo_spec(r, tmp_path)
    s["lanes"][0]["branch"] = "topic/sub"
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e5b.json"))
    assert rc == 12 and [e["field"] for e in v["errors"]] == ["lanes[0].branch"]  # a clash with a ref: 12 before 14 and 15
    rc, v = jplan(guard, r, f)
    assert rc == 14 and {e["field"] for e in v["errors"]} == {"lanes[2].branch"}  # a foreign claim: 14 before 15 (L2's branch exists too)
    r.git("branch", "agent/demo/api", "main")
    assert guard(r, "release", "--branch", "agent/demo/docs").rc == 0
    rc, v = jplan(guard, r, f)
    assert rc == 15 and {e["field"] for e in v["errors"]} == {"lanes[0].branch", "lanes[1].branch"}  # every offending lane is named


def test_amend_moves_the_base(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    old = demo.git("rev-parse", "main")
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    w1, w2 = tmp_path / "wt" / "l1", tmp_path / "wt" / "l2"
    demo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(w1), "main")
    demo.commit("src/api/x.py", "x\n", cwd=w1, msg="l1")
    demo.git("worktree", "add", "-q", "-b", "agent/demo/ui", str(w2), "main")
    head = demo.git("rev-parse", "agent/demo/api")
    upd_ok(guard, demo, "L1", "active")
    upd_ok(guard, demo, "L1", "ready", "--head", head, "--note", "done")
    upd_ok(guard, demo, "L2", "active")
    seeded = record(demo)
    rev = seeded["revision"]
    demo.commit("README.md", "moved by an unrelated commit\n")
    new = demo.git("rev-parse", "main")
    rc, v = jplan(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path, base=old), "old.json"), "--amend", "--expect-revision", str(rev))
    assert rc == 19 and v["kind"] == "base" and v["expected"] == old and v["current"] == new  # the old base is stale
    f = write_spec(tmp_path, demo_spec(demo, tmp_path, base=new), "new.json")
    v = plan_ok(guard, demo, f, "--amend", "--expect-revision", str(rev))
    rec = record(demo)
    assert v["revision"] == rev + 1 and v["base"] == new and rec["base"] == new and rec["created"] == seeded["created"]
    assert (lane_of(rec, "L1")["state"], lane_of(rec, "L1")["head"], lane_of(rec, "L1")["note"]) == ("ready", head, "done") and lane_of(rec, "L2")["state"] == "active"
    for branch in ("agent/demo/api", "agent/demo/ui", "agent/demo/docs", "agent/demo/integration"):
        assert "base=" + new in claim_lines(demo, branch), branch  # the claim of every lane follows the plan
    assert demo.git("rev-parse", "agent/demo/api~1") == old  # the lane stays cut from the old base: nothing refuses it
    shrink = demo_spec(demo, tmp_path, base=new)
    shrink["lanes"][0]["paths"] = ["tests/api/", "package-lock.json"]
    shrink["shared"] = [{"path": "package-lock.json", "owner": "L1"}]
    rc, v = jplan(guard, demo, write_spec(tmp_path, shrink, "shrink.json"), "--amend", "--expect-revision", str(rev + 1))
    assert rc == 16 and v["blocked"] == [{"lane": "L1", "reason": "SHRINK", "files": ["src/api/x.py"]}] and record(demo)["revision"] == rev + 1


def test_the_record_is_written_whole_and_unknown_keys_survive(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    sheet = "line one\n\tline two -> x ∣ café 日本\n- [ ] git switch -c y\n"
    spec = demo_spec(demo, tmp_path, sheet=sheet)
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    path = store_dir(demo) / "sets" / "demo.json"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n") and json.loads(raw.decode("utf-8"))["sheet"] == sheet  # UTF-8, no BOM, LF, verbatim
    rec = edit_record(demo, lambda rec: (rec.update(x_note={"a": [1, 2]}), lane_of(rec, "L2").update(x_lane="keep me")))
    amend = demo_spec(demo, tmp_path, sheet=sheet)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "1")
    after = record(demo)
    assert after["x_note"] == {"a": [1, 2]} and lane_of(after, "L2")["x_lane"] == "keep me" and after["revision"] == 2 and after["sheet"] == sheet
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf") and b"\r" not in path.read_bytes()
    # a BOM and CRLF added by hand still read
    text = path.read_text(encoding="utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    v = plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "2")
    assert v["unchanged"] is True and v["revision"] == 2
    # a temporary file is never read as a record and does not stop doctor
    sets = store_dir(demo) / "sets"
    (sets / "demo.json.tmp").write_bytes(b"garbage")
    (sets / "other.json.tmp").write_bytes(b"{")
    assert plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "2")["unchanged"] is True
    assert G.read_sets(G.open_repo(str(demo.path)))[0].keys() == {"demo"} and G.read_sets(G.open_repo(str(demo.path)))[1] == []
    assert guard(demo, "doctor").rc == 0
    # set-update keeps the unknown keys too, and writes the record whole in the format of the guard whatever the hand-made spelling was
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    upd_ok(guard, demo, "L1", "active", "--note", "n", rev=2)
    after, raw = record(demo), path.read_bytes()
    assert after["x_note"] == {"a": [1, 2]} and lane_of(after, "L2")["x_lane"] == "keep me" and after["revision"] == 3 and after["sheet"] == sheet
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n") and G.record_bytes(after) == raw


# ---- TC-293 .. TC-297: audit lines, the lock, Git failures, the cost of a large spec ---------------------------------------------------
def test_audit_lines_of_every_set_write(demo, guard, tmp_path):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    invalid = write_spec(tmp_path, {"v": 2}, "invalid.json")
    overlap = demo_spec(demo, tmp_path)
    overlap["lanes"][2]["paths"] = ["src/ui/"]
    stale = write_spec(tmp_path, demo_spec(demo, tmp_path, base="0" * 40), "stale.json")
    for spec_file, extra in ((f, ("--dry-run",)), (invalid, ()), (write_spec(tmp_path, overlap, "overlap.json"), ()), (stale, ()), (f, ("--amend", "--expect-revision", "1"))):
        guard(demo, *sp_args(spec_file, "demo", "main", *extra))  # a preview and every refusal append nothing
    assert audit_lines(demo) == []
    plan_ok(guard, demo, f)
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    amend["lanes"].pop(1)
    af = write_spec(tmp_path, amend, "amend.json")
    first = audit_lines(demo)
    assert len(first) == 1
    line = first[0]
    assert set(line) == {"ts", "by", "host", "op", "set", "target", "base", "revision", "lanes", "integration"}
    assert line["op"] == "set-plan" and line["host"] == "cli" and line["set"] == "demo" and line["target"] == "main" and line["base"] == demo.git("rev-parse", "main")
    assert line["revision"] == 1 and line["integration"] == "agent/demo/integration" and line["by"] and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", line["ts"])
    assert line["lanes"] == [{"id": x["id"], "branch": x["branch"], "worktree": x["worktree"], "entries": x["paths"]} for x in demo_spec(demo, tmp_path)["lanes"]]
    store_before = store_files(demo)
    guard(demo, *sp_args(af, "demo", "main", "--amend", "--expect-revision", "1", "--dry-run"))
    assert store_files(demo) == store_before  # still one line
    plan_ok(guard, demo, af, "--amend", "--expect-revision", "1")
    lines = audit_lines(demo)
    assert len(lines) == 2 and lines[0] == line  # the first line is never touched
    amended = lines[1]
    assert set(amended) == {"ts", "by", "host", "op", "set", "target", "base", "revision", "lanes", "integration", "previous_revision", "removed"}
    assert amended["op"] == "set-amend" and amended["revision"] == 2 and amended["previous_revision"] == 1 and amended["removed"] == ["L2"] and amended["host"] == "cli"
    assert [x["id"] for x in amended["lanes"]] == ["L1", "L3"] and amended["lanes"][1]["entries"] == ["docs/", "notes/"]
    plan_ok(guard, demo, af, "--amend", "--expect-revision", "2")  # an amendment that changes nothing writes nothing
    assert len(audit_lines(demo)) == 2
    # set-update and set-release append their lines after the write; a refusal, set-show and the other reads append none
    r = make_repo(tmp_path, "audit2")
    one = demo_spec(r, tmp_path, shared=[])
    one["lanes"] = [lane(tmp_path, "L1", "agent/demo/api", ["src/api/"], worktree=wt_path(tmp_path, "audit2-l1"))]
    plan_ok(guard, r, write_spec(tmp_path, one, "audit2.json"))
    wt = tmp_path / "wt" / "audit2-l1"
    r.git("worktree", "add", "-q", "-b", "agent/demo/api", str(wt), "main")
    r.commit("src/api/a.py", "a\n", cwd=wt, msg="a")
    tip = r.git("rev-parse", "agent/demo/api")
    assert upd(guard, r, "L1", "active", rev=9)[0] == 19 and upd(guard, r, "L1", "ready", "--head", "abc")[0] == 24 and jrelease(guard, r)[0] == 16  # refusals
    jshow(guard, r, "--drift")
    jshow(guard, r)
    assert len(audit_lines(r)) == 1
    upd_ok(guard, r, "L1", "active", "--note", "go")
    upd_ok(guard, r, "L1", "ready", "--head", tip)
    integrate(r, "agent/demo/api")
    r.git("merge", "-q", "--ff-only", INTEGRATION)
    upd_ok(guard, r, "L1", "integrated", "--head", tip, "--integration", INTEGRATION)
    assert jrelease(guard, r, "--reason", "done")[0] == 0
    lines = audit_lines(r)
    assert [x["op"] for x in lines] == ["set-plan", "set-update", "set-update", "set-update", "set-release"]
    keys = {"ts", "by", "host", "op", "set", "lane", "state", "head", "note", "integration", "revision"}
    assert all(set(x) == keys and x["host"] == "cli" and x["set"] == "demo" and x["lane"] == "L1" and x["by"] for x in lines[1:4])
    assert [(x["state"], x["head"], x["note"], x["integration"], x["revision"]) for x in lines[1:4]] == [
        ("active", None, "go", None, 2), ("ready", tip, "go", None, 3), ("integrated", tip, "go", INTEGRATION, 4)]
    released = lines[4]
    assert set(released) == {"ts", "by", "host", "op", "set", "revision", "reason", "abandon", "lanes", "claims"} and released["host"] == "cli"
    assert (released["set"], released["revision"], released["reason"], released["abandon"], released["lanes"], released["claims"]) == (
        "demo", 4, "done", False, ["L1"], ["agent/demo/api", INTEGRATION])
    r2 = make_repo(tmp_path, "audit3")
    plan_ok(guard, r2, write_spec(tmp_path, demo_spec(r2, tmp_path), "audit3.json"))
    assert jrelease(guard, r2, "--abandon")[0] == 0
    last = audit_lines(r2)[-1]
    assert last["op"] == "set-release" and last["abandon"] is True and last["reason"] == "" and last["lanes"] == ["L1", "L2", "L3"] and len(last["claims"]) == 4


def test_writers_time_out_on_the_lock_and_readers_do_not_wait(demo, guard, tmp_path, monkeypatch):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    plan_ok(guard, demo, f)
    other = demo_spec(demo, tmp_path)
    other["lanes"] = [lane(tmp_path, "X1", "agent/other/x", ["xdir/"], worktree=wt_path(tmp_path, "x1"))]
    other["shared"] = []
    of = write_spec(tmp_path, other, "other.json")
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    af = write_spec(tmp_path, amend, "amend.json")
    before = store_files(demo)
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "1")
    release = holding_lock(demo)
    try:
        for args in (sp_args(of, "other"), sp_args(af, "demo", "main", "--amend", "--expect-revision", "1"), update_args("L1", "active", 1),
                     ["set-release", "--set", "demo", "--abandon"]):
            started = time.monotonic()
            r = guard(demo, "--json", *args)
            v = json.loads(r.out)
            assert r.rc == 13 and v["code"] == "LOCK_TIMEOUT" and set(v) == COMMON_KEYS and r.err == "", (args, r)
            assert time.monotonic() - started < 15
            assert "could not take the claim lock within 1 s; nothing registered. Retry." in guard(demo, *args).out
            assert "1 秒内没有拿到清单锁" in run(["--repo", str(demo.path), "--lang", "zh", *args]).out
        started = time.monotonic()
        assert guard(demo, "list").rc == 0 and jplan(guard, demo, af, "--dry-run", "--amend", "--expect-revision", "1")[0] == 0
        assert jplan(guard, demo, of, "--dry-run", name="other")[0] == 0  # the readers and the preview do not wait for the lock
        assert guard(demo, "set-show", "--set", "demo").rc == 0 and guard(demo, "--json", "set-show", "--set", "demo", "--drift").rc == 0
        assert time.monotonic() - started < 15
    finally:
        release()
    assert store_files(demo) == before and len(audit_lines(demo)) == 1
    # the wait for the lock does not shorten the budget of the git calls that follow: it starts when the lock is held
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "60")
    monkeypatch.setattr(G.Git.__init__, "__defaults__", (3.0,))  # the budget that starts when the repository is opened
    monkeypatch.setattr(G, "BUDGET_S", 30.0)
    release = holding_lock(demo)
    result = []
    worker = threading.Thread(target=lambda: result.append(guard(demo, "--json", *sp_args(of, "other"))))
    worker.start()
    time.sleep(5)  # longer than the budget of the open repository
    release()
    worker.join(120)
    assert result and result[0].rc == 0 and json.loads(result[0].out)["revision"] == 1, result
    assert (store_dir(demo) / "sets" / "other.json").is_file()
    for args in (update_args("L1", "active", 1), ["set-release", "--set", "demo", "--abandon"]):  # the same for set-update and set-release
        release = holding_lock(demo)
        result = []
        worker = threading.Thread(target=lambda a=args: result.append(guard(demo, "--json", *a)))
        worker.start()
        time.sleep(5)
        release()
        worker.join(120)
        assert result and result[0].rc == 0, (args, result)
    assert not record_file(demo).exists()


def test_git_failures_fail_closed_and_rev_list_is_local(demo, guard, tmp_path, monkeypatch):
    import ast
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    real_run, real_isdir = subprocess.run, os.path.isdir

    def inject(after, exc, vanish=False):
        state = {"n": 0}

        def run_(*a, **k):
            state["n"] += 1
            if state["n"] > after:
                raise exc
            return real_run(*a, **k)

        def isdir(p):
            return False if vanish and state["n"] > after and G.pkey(p) == G.pkey(str(demo.path)) else real_isdir(p)
        monkeypatch.setattr(subprocess, "run", run_)
        monkeypatch.setattr(os.path, "isdir", isdir)

    def restore():
        monkeypatch.setattr(subprocess, "run", real_run)
        monkeypatch.setattr(os.path, "isdir", real_isdir)
    kinds = [("GIT_MISSING", FileNotFoundError("git"), False), ("GIT_FAILED", FileNotFoundError("gone"), True), ("BUDGET_EXCEEDED", subprocess.TimeoutExpired("git", 1), False)]
    for code, exc, vanish in kinds:
        for after in ((2, 3, 7, 9) if code == "GIT_FAILED" else (0, 3, 7, 9)):  # a failure while the repository is opened reads as no repository, except a missing git or the budget
            for dry_run in (False, True):
                args = sp_args(f, "demo", "main", *(("--dry-run",) if dry_run else ()))
                inject(after, exc, vanish)
                plain = guard(demo, *args)
                inject(after, exc, vanish)
                as_json = guard(demo, "--json", *args)
                restore()
                for r in (plain, as_json):
                    assert r.rc == 11 and r.err.replace("\r", "").startswith("MAGOS guard: %s: " % code), (code, after, dry_run, r)
                assert plain.out == "", (code, after, plain)
                v = json.loads(as_json.out)
                assert v["decision"] == "deny" and v["unknowns"][0]["code"] == code and v["exit_code"] == 11 and set(v) == COMMON_KEYS | {"unknowns"}, v
                assert store_files(demo) in (None, {}), (code, after)  # nothing is written
    plan_ok(guard, demo, f)  # the other three subcommands, on a registered set whose lane has a branch, a worktree and a commit
    wt, tip = start_lane(demo, tmp_path, "L1", {"src/api/a.py": "a\n"})
    upd_ok(guard, demo, "L1", "active")
    state = lambda: (record_file(demo).read_bytes(), store_files(demo), len(audit_lines(demo)))
    before = state()
    commands = {"set-show": (["set-show", "--set", "demo", "--drift"], (0, 2, 3, 5, 7, 8)), "set-update": (update_args("L1", "ready", 2, "--head", tip), (2, 3, 5, 7)),
                "set-release": (["set-release", "--set", "demo", "--abandon"], (2, 3, 5))}  # the points that lie before the write of each
    for code, exc, vanish in kinds:
        for label, (args, points) in commands.items():
            for after in ((x for x in points if x) if code == "GIT_FAILED" else points):
                inject(after, exc, vanish)
                plain = guard(demo, *args)
                inject(after, exc, vanish)
                as_json = guard(demo, "--json", *args)
                restore()
                for r in (plain, as_json):
                    assert r.rc == 11 and r.err.replace("\r", "").startswith("MAGOS guard: %s: " % code), (label, code, after, r)
                assert plain.out == "", (label, code, after, plain)
                v = json.loads(as_json.out)
                assert v["decision"] == "deny" and v["unknowns"][0]["code"] == code and v["exit_code"] == 11 and set(v) == COMMON_KEYS | {"unknowns"}, v
                assert state() == before, (label, code, after)  # nothing is written
    g = G.Git(str(demo.path))
    assert g.run("rev-list", "--count", "main..main")[1].strip() == b"0" and "rev-list" in G.LOCAL_GIT  # rev-list is a local subcommand
    assert not G.LOCAL_GIT & {"fetch", "pull", "push", "clone", "ls-remote", "remote", "merge", "merge-tree", "switch", "checkout"}
    started = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: started.append(a) or pytest.fail("git started"))
    for refused in ("merge", "merge-tree", "switch", "fetch"):
        with pytest.raises(G.GitFail) as err:
            g.run(refused, "x")
        assert err.value.code == "GIT_FAILED" and "git %s is not a subcommand the guard runs" % refused in str(err.value)
    assert started == []
    restore()
    tree = ast.parse(Path(G.__file__).read_text(encoding="utf-8"))
    worktree_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("run", "text") and n.args
                      and isinstance(n.args[0], ast.Constant) and n.args[0].value == "worktree"]
    assert worktree_calls and all(len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and n.args[1].value == "list" for n in worktree_calls)  # `worktree` only as `worktree list`


def test_a_twelve_lane_spec_is_registered_within_the_budget(tmp_path, guard, monkeypatch):
    r = make_repo(tmp_path, "perf")
    fast_branches(r, 20)

    def entries(i):  # 200 mixed entries, all of lane i under its own top-level directory d<i>
        kinds = ("d%d/dir%d/", "d%d/mod%d/*.py", "d%d/**/test_%d.py", "d%d/file%d.txt", "d%d/pkg%d/*/x?.py")
        return [kinds[j % 5] % (i, j) for j in range(200)]
    spec = demo_spec(r, tmp_path, shared=[])
    spec["lanes"] = [lane(tmp_path, "L%d" % i, "agent/demo/l%d" % i, entries(i)) for i in range(1, 13)]
    f = write_spec(tmp_path, spec)
    calls = []
    real = G.entries_overlap
    monkeypatch.setattr(G, "entries_overlap", lambda a, b: calls.append(1) or real(a, b))
    for extra in (("--dry-run",), ()):
        calls.clear()
        started = time.monotonic()
        rc, v = jplan(guard, r, f, *extra)
        assert rc == 0 and v["revision"] == 1, v
        assert time.monotonic() - started < time_budget(10), time.monotonic() - started
        assert len(calls) <= 4 * 2400, len(calls)  # the first-segment index: a small multiple of the entry count
    assert len(record(r)["lanes"]) == 12 and len(record(r)["lanes"][0]["paths"]) == 200
    # the drift view of the same set, its lanes having changed about 5,000 files: 400 files of each lane inside its manifest (literal directories,
    # one-level and recursive globs) and 16 outside it, every entry of a lane starting with the same literal directory
    for i in range(1, 13):
        files = {"d%d/dir0/f%d.py" % (i, k): "x\n" for k in range(100)}
        files.update({"d%d/mod1/m%d.py" % (i, k): "x\n" for k in range(100)})
        files.update({"d%d/s%d/test_2.py" % (i, k): "x\n" for k in range(100)})
        files.update({"d%d/pkg4/q%d/x1.py" % (i, k): "x\n" for k in range(100)})
        files.update({"zz%d/o%d.txt" % (i, k): "x\n" for k in range(16)})
        fast_commit(r, "agent/demo/l%d" % i, files)
    started = time.monotonic()
    rc, v = jcall(guard, r, "set-show", "--set", "demo", "--drift")
    assert rc == 0 and time.monotonic() - started < time_budget(10), time.monotonic() - started
    assert sum(len(x["changed"]) for x in v["view"]["lanes"]) == 12 * 416 and v["view"]["drift"]["shared_changes"] == []
    assert all(x["out_of_lane"] == sorted("zz%d/o%d.txt" % (i, k) for k in range(16)) for i, x in enumerate(v["view"]["lanes"], 1))
    # every entry in the wildcard group: the full comparison either completes or ends with BUDGET_EXCEEDED and no write, never a partial proof
    r2 = make_repo(tmp_path, "perf2")
    wild = demo_spec(r2, tmp_path, shared=[])
    wild["lanes"] = [lane(tmp_path, "L%d" % i, "agent/demo/l%d" % i, ["**/f_%d_%d.py" % (i, j) for j in range(200)]) for i in range(1, 13)]
    monkeypatch.setattr(G, "entries_overlap", real)
    monkeypatch.setattr(G.Git.__init__, "__defaults__", (4.0,))
    started = time.monotonic()
    rc, v = jplan(guard, r2, write_spec(tmp_path, wild, "wild.json"))
    assert time.monotonic() - started < time_budget(30)
    assert rc in (0, 11), v
    if rc == 11:
        assert v["unknowns"][0]["code"] == "BUDGET_EXCEEDED" and store_files(r2) in (None, {})
    # a spec of 4 MiB of nested lists is refused at once
    started = time.monotonic()
    rc, v = dry(guard, r, tmp_path, b"[" * 4194304, "nested.json")
    assert rc == 24 and ("spec", "JSON") in errors_of(v) and time.monotonic() - started < time_budget(10)


# ---- TC-310: the manifest index ---------------------------------------------------------------------------------------------------------
def test_manifest_index_agrees_with_path_hit():
    import random
    rng = random.Random(20261021)
    segs = ["a", "b", "ab", "src", "x.py", "Src", "t_1", "pages[id].tsx", "c*", "*.py", "?", "a?", "*", "**", "*b*", "docs", "caf\u00e9"]
    names = ["a", "b", "ab", "src", "x.py", "t_1", "pages[id].tsx", "abc", "a.py", "docs", "Src", "q", "a*", "b?", "cafe\u0301", "caf\u00e9"]
    checked = 0
    for _ in range(700):
        raws = []
        for _ in range(rng.randint(1, 5)):
            raw = "/".join(rng.choice(segs) for _ in range(rng.randint(1, 4))) + ("/" if rng.random() < 0.3 else "")
            try:
                G.parse_entry(raw)
            except G.ManifestError:
                continue
            raws.append(raw)
        if not raws:
            continue
        index, entries = G.ManifestIndex(raws), [G.parse_entry(r) for r in raws]
        for _ in range(25):
            path = tuple(G.fold(rng.choice(names)) for _ in range(rng.randint(1, 5)))
            assert index.hit(path) == any(G.path_hit(e, path) for e in entries), (raws, path)
            checked += 1
    assert checked > 10000
    # literal directories and files, a file that an entry names as a directory, and the files of a manifest sorted by outside()
    index = G.ManifestIndex(["src/api/", "tests/api/t.py", "docs/**", "lib/*.py", "Pages/[id].tsx"])
    inside = ["src/api/a.py", "src/api", "src", "tests/api/t.py", "tests/api", "docs/x/y.md", "docs", "lib/m.py", "LIB/M.PY", "pages/[id].tsx", "pages/i.tsx"]
    outside = ["src/ui/a.py", "src/apix", "tests/api/u.py", "lib/m/n.py", "lib", "readme.md", "other/src/api/a.py"]
    assert all(index.hit(G.fpath(x)) for x in inside), [x for x in inside if not index.hit(G.fpath(x))]
    assert not any(index.hit(G.fpath(x)) for x in outside), [x for x in outside if index.hit(G.fpath(x))]
    assert index.outside(outside + inside) == sorted(outside) and not index.hit(())
    # an entry that cannot be read matches nothing, and a file name that is itself a glob is compared by the exact intersection
    index = G.ManifestIndex(["/absolute", "src/", "  "])
    assert index.hit(G.fpath("src/x.py")) and not index.hit(G.fpath("absolute/x"))
    glob_name = G.ManifestIndex(["src/api/", "lib/a?.py"])
    assert glob_name.hit(G.fpath("src/*")) and glob_name.hit(G.fpath("lib/*.py")) and not glob_name.hit(G.fpath("docs/*"))
    # the deadline ends a long comparison with BUDGET_EXCEEDED, never with a partial answer
    many = G.ManifestIndex(["a/*%d*.py" % i for i in range(300)], deadline=time.monotonic() - 1)
    with pytest.raises(G.GitFail) as err:
        many.hit(G.fpath("a/zzz.txt"))
    assert err.value.code == "BUDGET_EXCEEDED"
