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
OK_KEYS = COMMON_KEYS | {"set", "target", "base", "revision", "dry_run", "unchanged", "integration_branch", "order", "requirements", "lanes", "written", "warnings"}
BASE_FILES = ("src/api/a.py", "src/ui/u.py", "tests/api/t.py", "docs/d.md", "docs/readme.md", "README.md", "package-lock.json")
LANE_ROW_KEYS = ["id", "title", "branch", "worktree", "entries", "depends_on", "serves", "outcome", "acceptance", "state", "create"]


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


def wt_path(tmp_path, lid, set_name="demo", prefix="wt"):
    """The worktree of the lane `lid` of `set_name` as a spec names it: a directory whose name ends with -<set>-<id> after a prefix."""
    return P(tmp_path / "wt" / ("%s-%s-%s" % (prefix, set_name, lid)))


def wt_dir(tmp_path, lid, set_name="demo", prefix="wt"):
    return Path(wt_path(tmp_path, lid, set_name, prefix))


REQUIREMENTS = [{"id": "R1", "text": "the API serves the endpoint"}, {"id": "R2", "text": "the UI shows it"}, {"id": "R3", "text": "the docs describe it"}]


def lane(tmp_path, lid, paths, deps=(), serves=("R1",), set_name="demo", **over):
    """A lane of the spec: its branch is agent/<set>/<id>, its worktree ends with -<set>-<id>; it serves the requirement R1 unless it says otherwise."""
    d = {"id": lid, "title": "lane " + lid, "branch": "agent/%s/%s" % (set_name, lid), "worktree": wt_path(tmp_path, lid, set_name), "serves": list(serves),
         "outcome": "the outcome of " + lid, "paths": list(paths), "depends_on": list(deps), "acceptance": "it works"}
    d.update(over)
    return d


def demo_spec(repo, tmp_path, base=None, **over):
    """The demo spec of TC-253: api owns the api (and the shared lock file) and serves R1, ui the ui (after api) and serves R2, docs the docs and serves R3;
    api omits its acceptance."""
    api = lane(tmp_path, "api", ["src/api/", "tests/api/", "package-lock.json"], serves=["R1"])
    del api["acceptance"]
    spec = {"v": 1, "title": "Demo", "requirements": [dict(r) for r in REQUIREMENTS], "base": base or repo.git("rev-parse", "main"),
            "sheet": "# Plan demo -> main  rev 1\n- [ ] api\n- [ ] ui\n", "notes": ["note one"], "shared": [{"path": "package-lock.json", "owner": "api"}],
            "lanes": [api, lane(tmp_path, "ui", ["src/ui/"], ["api"], serves=["R2"]), lane(tmp_path, "docs", ["docs/"], serves=["R3"])]}
    spec.update(over)
    return spec


def custom_spec(repo, tmp_path, lanes, **over):
    """A spec of `lanes` (they serve the one requirement R1, which the spec states) without shared files, unless `over` says otherwise."""
    over.setdefault("shared", [])
    over.setdefault("requirements", [{"id": "R1", "text": "the task is done"}])
    spec = demo_spec(repo, tmp_path, **over)
    spec["lanes"] = lanes
    return spec


def drop_lane(spec, lid, with_requirements=False):
    """The spec without the lane `lid`: no other lane depends on it, no shared file belongs to it, and the requirements it served go to the first lane
    that is left (or, with `with_requirements`, go with it when no other lane serves them)."""
    gone = next(x for x in spec["lanes"] if x["id"] == lid)
    spec["lanes"] = [x for x in spec["lanes"] if x["id"] != lid]
    for x in spec["lanes"]:
        x["depends_on"] = [d for d in x["depends_on"] if d != lid]
    spec["shared"] = [s for s in spec["shared"] if s["owner"] != lid]
    served = {r for x in spec["lanes"] for r in x["serves"]}
    for r in gone["serves"]:
        if r not in served and not with_requirements and spec["lanes"]:
            spec["lanes"][0]["serves"].append(r)
    if with_requirements:
        spec["requirements"] = [r for r in spec["requirements"] if r["id"] in served]
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
    assert v["order"] == ["api", "ui", "docs"]
    assert v["requirements"] == [{"id": "R1", "text": REQUIREMENTS[0]["text"], "lanes": ["api"]}, {"id": "R2", "text": REQUIREMENTS[1]["text"], "lanes": ["ui"]},
                                 {"id": "R3", "text": REQUIREMENTS[2]["text"], "lanes": ["docs"]}]
    for ln, want in zip(v["lanes"], spec["lanes"]):
        assert list(ln) == LANE_ROW_KEYS and ln["id"] == want["id"] and ln["title"] == want["title"] and ln["branch"] == want["branch"] and ln["worktree"] == want["worktree"]
        assert ln["entries"] == want["paths"] and ln["depends_on"] == want["depends_on"] and ln["serves"] == want["serves"] and ln["outcome"] == want["outcome"]
        assert ln["acceptance"] == want.get("acceptance", "") and ln["state"] == "planned"
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
    assert rec["requirements"] == spec["requirements"] and list(G.RECORD_KEYS).index("requirements") == list(G.RECORD_KEYS).index("title") + 1
    assert rec["shared"] == [{"path": "package-lock.json", "owner": "api"}] and [x["id"] for x in rec["lanes"]] == ["api", "ui", "docs"]
    for x, want in zip(rec["lanes"], spec["lanes"]):
        assert x["state"] == "planned" and x["head"] is None and x["changes"] is None and x["note"] == "" and list(x) == list(G.RECORD_LANE_KEYS)
        assert (x["serves"], x["outcome"], x["acceptance"]) == (want["serves"], want["outcome"], want.get("acceptance", ""))
    assert list(G.RECORD_LANE_KEYS) == ["id", "title", "branch", "worktree", "paths", "depends_on", "serves", "outcome", "acceptance", "state", "head", "changes", "note", "updated"]
    assert lane_of(rec, "api")["acceptance"] == "" and lane_of(rec, "ui")["acceptance"] == "it works"  # api omitted it: the empty string is stored
    assert lane_of(rec, "ui")["depends_on"] == ["api"]
    audit = audit_lines(demo)
    assert len(audit) == 1 and audit[0]["op"] == "set-plan" and audit[0]["set"] == "demo" and audit[0]["revision"] == 1 and audit[0]["integration"] == "agent/demo/integration"
    assert audit[0]["requirements"] == ["R1", "R2", "R3"] and [x["serves"] for x in audit[0]["lanes"]] == [["R1"], ["R2"], ["R3"]]
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
    # an amend that rewrites the claims of api and ui and deletes that of docs
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][0]["paths"] = ["src/api/", "tests/api/", "package-lock.json", "api-docs/"]
    amend["lanes"][1]["paths"] = ["src/ui/", "ui-docs/"]
    drop_lane(amend, "docs", with_requirements=True)  # the lane goes with the requirement only it served
    amend_file = write_spec(tmp_path, amend, "amend.json")
    before = store_files(demo)
    l3 = str(store_dir(demo) / "claims" / "agent" / "demo" / "docs.claim")
    for k in range(1, 4):  # the claims of api and ui, then the record
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
            raise PermissionError("injected: the claim of docs is busy")
        return real_remove(path, *a, **kw)
    monkeypatch.setattr(G.os, "remove", no_remove)
    r = guard(demo, *sp_args(amend_file, "demo", "main", "--amend", "--expect-revision", "1"))
    assert r.rc == 11 and "docs is busy" in r.err and store_files(demo) == before  # the writes were undone as well
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
    assert r.rc == 0 and r.out.startswith("MAGOS: the preview of set 'demo' passed, no overlap found; this was a --dry-run and nothing was written.")
    assert not store_dir(demo).exists()
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
        spec = custom_spec(r, tmp_path, [lane(tmp_path, "alpha", a), lane(tmp_path, "beta", b)])
        return r, write_spec(tmp_path, spec, name + ".json")
    nfd, nfc = unicodedata.normalize("NFD", "café/x"), unicodedata.normalize("NFC", "café/x")
    cases = [(["src/a.py"], ["src/a.py"]), (["src/*.py"], ["src/a.py"]), (["src/"], ["src/a.py"]), (["src/**"], ["src/x/y.py"]), (["**/*.md"], ["docs/readme.md"]),
             (["Src/A.py"], ["src/a.py"]), ([nfd], [nfc]), (["pages/[id].tsx"], ["pages/i.tsx"]), (["src/*.py"], ["src/?.py"])]
    for n, (a, b) in enumerate(cases):
        r, f = two(a, b, "ov%d" % n)
        rc, v = jplan(guard, r, f)
        assert rc == 10 and v["code"] == "CONFLICT" and set(v) == COMMON_KEYS | {"overlaps"}, (a, b, v)
        assert v["overlaps"][0]["a"] == "alpha" and v["overlaps"][0]["b"] == "beta" and v["overlaps"][0]["entries"] == [[a[0], b[0]]]
        assert not store_dir(r).exists()  # nothing is written
        text = guard(r, *sp_args(f)).out
        assert "lane alpha and lane beta overlap" in text and a[0] in text and b[0] in text
        zh = run(["--repo", str(r.path), "--lang", "zh", *sp_args(f)])
        assert zh.rc == 10 and "lane alpha 与 lane beta 的 manifest 重叠" in zh.out
    for n, (a, b) in enumerate([(["src/a.py"], ["src/ab.py"]), (["src/a/"], ["src/b/"])]):  # the disjoint neighbours register
        r, f = two(a, b, "dj%d" % n)
        assert plan_ok(guard, r, f)["revision"] == 1
    r, f = two(["src/a.py"], ["docs/d.md"], "three")
    spec = json.loads(f.read_text(encoding="utf-8"))
    spec["lanes"] = [lane(tmp_path, "api", ["src/a.py"]), lane(tmp_path, "ui", ["docs/"]), lane(tmp_path, "docs", ["src/*.py"])]
    rc, v = jplan(guard, r, write_spec(tmp_path, spec, "three.json"))
    assert rc == 10 and [(x["a"], x["b"]) for x in v["overlaps"]] == [("api", "docs")]
    spec["lanes"] = [lane(tmp_path, "alpha", ["src/f1*.py", "src/f2*.py", "src/f3*.py", "src/f4*.py", "src/f5*.py"]),
                     lane(tmp_path, "beta", ["src/*1z*.py", "src/*2z*.py", "src/*3z*.py", "src/*4z*.py", "src/*5z*.py"])]
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
    def spec_with(deps, ids=("api", "ui", "docs")):
        return write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, lid, ["d%d/" % i], d) for i, (lid, d) in enumerate(zip(ids, deps))]))
    cases = [([["api"], [], []], "CYCLE", "lanes[0].depends_on[0]"), ([[], ["api", "api"], []], "DUPLICATE", "lanes[1].depends_on[1]"),
             ([[], ["tools"], []], "UNKNOWN_LANE", "lanes[1].depends_on[0]"), ([[], ["API"], []], "UNKNOWN_LANE", "lanes[1].depends_on[0]"),
             ([["ui"], ["api"], []], "CYCLE", "lanes[0].depends_on"), ([["docs"], ["api"], ["ui"]], "CYCLE", "lanes[0].depends_on")]
    for deps, code, field in cases:
        rc, v = jplan(guard, demo, spec_with(deps), "--dry-run")
        assert rc == 24 and (field, code) in errors_of(v), (deps, v)
    cyc = next(e for e in jplan(guard, demo, spec_with([["docs"], ["api"], ["ui"]]), "--dry-run")[1]["errors"] if e["code"] == "CYCLE")
    assert all(x in cyc["text"] for x in ("api", "ui", "docs"))  # the message lists the lanes on the cycle
    topics = ["topic-%02d" % i for i in range(12)]  # twelve lanes of twelve topics
    twelve = custom_spec(demo, tmp_path, [lane(tmp_path, t, ["d%d/" % i]) for i, t in enumerate(topics)])
    twelve["lanes"][11]["depends_on"] = topics[:11] + [topics[0]]  # 12 ids: one over the limit
    rc, v = jplan(guard, demo, write_spec(tmp_path, twelve), "--dry-run")
    assert rc == 24 and ("lanes[11].depends_on", "RANGE") in errors_of(v)
    twelve["lanes"][11]["depends_on"] = topics[:11]  # 11 ids are fine
    assert jplan(guard, demo, write_spec(tmp_path, twelve), "--dry-run")[0] == 0
    diamond = custom_spec(demo, tmp_path, [lane(tmp_path, "core", ["a/"]), lane(tmp_path, "api", ["b/"], ["core"]), lane(tmp_path, "cli", ["c/"], ["core"]),
                                           lane(tmp_path, "docs", ["d/"], ["api", "cli"])])
    assert jplan(guard, demo, write_spec(tmp_path, diamond), "--dry-run")[1]["order"] == ["core", "api", "cli", "docs"]
    independent = custom_spec(demo, tmp_path, [lane(tmp_path, t, ["d%d/" % i]) for i, t in enumerate(("api", "ui", "docs"))])
    assert jplan(guard, demo, write_spec(tmp_path, independent), "--dry-run")[1]["order"] == ["api", "ui", "docs"]
    chain = custom_spec(demo, tmp_path, [lane(tmp_path, "docs", ["c/"], ["ui"]), lane(tmp_path, "ui", ["b/"], ["api"]), lane(tmp_path, "api", ["a/"])])
    assert jplan(guard, demo, write_spec(tmp_path, chain), "--dry-run")[1]["order"] == ["api", "ui", "docs"]
    mixed = custom_spec(demo, tmp_path, [lane(tmp_path, "alpha", ["a/"], ["gamma"]), lane(tmp_path, "beta", ["b/"]), lane(tmp_path, "gamma", ["c/"])])
    assert jplan(guard, demo, write_spec(tmp_path, mixed), "--dry-run")[1]["order"] == ["beta", "gamma", "alpha"]  # the first lane of the array whose dependencies are placed comes next


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
    a = custom_spec(r, tmp_path, [lane(tmp_path, "alpha", ["src/"], set_name="seta")], title="A")
    b = custom_spec(r, tmp_path, [lane(tmp_path, "beta", ["src/api/"], set_name="setb")], title="B")
    fa, fb = write_spec(tmp_path, a, "a.json"), write_spec(tmp_path, b, "b.json")
    release, procs = racers(r, [sp_args(fa, "seta"), sp_args(fb, "setb")])
    release()
    results = [finished(p) for p in procs]
    assert sorted(rc for rc, _, _ in results) == [0, 10], results
    loser = next(json.loads(o) for rc, o, _ in results if rc == 10)
    winner_lane = "alpha" if results[0][0] == 0 else "beta"
    assert loser["lanes"][0]["conflicts"][0]["branch"] == ("agent/seta/alpha" if winner_lane == "alpha" else "agent/setb/beta")
    assert loser["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "declared"
    sets = sorted(p.stem for p in (store_dir(r) / "sets").glob("*.json"))
    assert len(sets) == 1 and not list(store_dir(r).rglob("*.tmp"))
    claims = sorted(P(p.relative_to(store_dir(r) / "claims")) for p in (store_dir(r) / "claims").rglob("*.claim"))
    assert claims == (["agent/seta/alpha.claim", "agent/seta/integration.claim"] if sets == ["seta"] else ["agent/setb/beta.claim", "agent/setb/integration.claim"])  # the winner's, nothing of the loser's
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
    assert sorted(k for k in after if after[k] != before.get(k) and k != "audit.log") == ["claims/agent/demo/docs.claim", "sets/demo.json"]  # only the claim of docs is rewritten
    for rev in ("1", "5"):
        rc, v = jplan(guard, demo, af, "--amend", "--expect-revision", rev)
        assert rc == 19 and v["kind"] == "revision" and v["current"] == 2 and v["expected"] == int(rev) and set(v) == COMMON_KEYS | {"kind", "expected", "current"}
    out = guard(demo, *sp_args(af, "demo", "main", "--amend", "--expect-revision", "1")).out.rstrip("\n")
    assert out == "MAGOS: the plan is stale, nothing was written: set 'demo' is at revision 2, not 1. Read it again with set-show."
    zh = run(["--repo", str(demo.path), "--lang", "zh", *sp_args(af, "demo", "main", "--amend", "--expect-revision", "1")])
    assert zh.rc == 19 and "现在是修订 2，而你基于修订 1" in zh.out
    assert guard(demo, *sp_args(af, "demo", "main", "--amend")).rc == 2  # no --expect-revision
    ghost = write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"], set_name="ghost")]), "ghost.json")  # a spec that is valid for the set it names
    rc, v = jplan(guard, demo, ghost, "--amend", "--expect-revision", "1", name="ghost")
    assert rc == 21 and v["code"] == "SET_UNKNOWN" and set(v) == COMMON_KEYS
    assert guard(demo, *sp_args(ghost, "ghost", "main", "--amend", "--expect-revision", "1")).out.rstrip("\n") == "MAGOS: there is no set named 'ghost'."
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
    upd_ok(guard, demo, "api", "active")
    upd_ok(guard, demo, "api", "ready", "--head", head, "--note", "done")
    upd_ok(guard, demo, "ui", "blocked", "--note", "waiting for the api")
    seeded = record(demo)
    assert seeded["revision"] == 4
    api_before = (store_dir(demo) / "claims" / "agent" / "demo" / "api.claim").read_bytes()
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][1].update(title="new title", paths=["src/ui/", "ui-extra/"], outcome="the UI shows it, and better", serves=["R2", "R1"])
    amend["lanes"][2:] = [lane(tmp_path, "tools", ["extra/"], serves=["R4"], outcome="the tools exist", acceptance="")]  # docs is removed, tools is new
    amend["requirements"] = [REQUIREMENTS[0], REQUIREMENTS[1], {"id": "R4", "text": "the tools exist"}]  # R3 goes with docs
    af = write_spec(tmp_path, amend, "amend.json")
    kept = json.loads(af.read_text(encoding="utf-8"))
    kept["requirements"] = [REQUIREMENTS[0], REQUIREMENTS[1], REQUIREMENTS[2], {"id": "R4", "text": "the tools exist"}]  # the same amend with R3 kept: nobody serves it
    before = store_files(demo)
    rc, v = jplan(guard, demo, write_spec(tmp_path, kept, "kept.json"), "--amend", "--expect-revision", "4")
    assert rc == 24 and v["code"] == "INVALID_SPEC" and errors_of(v) == {("requirements[2]", "UNSERVED")} and "R3" in v["errors"][0]["text"] and store_files(demo) == before
    v = plan_ok(guard, demo, af, "--amend", "--expect-revision", "4")
    rec = record(demo)
    assert v["revision"] == 5 and rec["revision"] == 5 and rec["created"] == seeded["created"] and [x["id"] for x in rec["lanes"]] == ["api", "ui", "tools"]
    assert rec["requirements"] == amend["requirements"] and v["requirements"] == [{"id": "R1", "text": REQUIREMENTS[0]["text"], "lanes": ["api", "ui"]},
                                                                                  {"id": "R2", "text": REQUIREMENTS[1]["text"], "lanes": ["ui"]},
                                                                                  {"id": "R4", "text": "the tools exist", "lanes": ["tools"]}]  # a requirement served by two lanes
    for x, want in zip(rec["lanes"], amend["lanes"]):  # the serves, the outcome and the acceptance are those of the amend spec
        assert (x["serves"], x["outcome"], x["acceptance"]) == (want["serves"], want["outcome"], want.get("acceptance", ""))
    api = lane_of(rec, "api")
    assert (api["state"], api["head"], api["note"], api["changes"]) == ("ready", head, "done", None)
    assert api["updated"] == lane_of(seeded, "api")["updated"]  # an untouched lane keeps its time
    ui = lane_of(rec, "ui")
    assert (ui["state"], ui["note"], ui["title"], ui["paths"]) == ("blocked", "waiting for the api", "new title", ["src/ui/", "ui-extra/"]) and ui["updated"] != lane_of(seeded, "ui")["updated"]
    tools = lane_of(rec, "tools")
    assert (tools["state"], tools["head"], tools["changes"], tools["note"]) == ("planned", None, None, "")
    claims = store_dir(demo) / "claims" / "agent" / "demo"
    assert not (claims / "docs.claim").exists() and (claims / "api.claim").read_bytes() == api_before and (claims / "tools.claim").is_file()  # the claim of api is not rewritten
    assert "entry=ui-extra/" in (claims / "ui.claim").read_text(encoding="utf-8").split("\n")
    # a lane that has a branch or a worktree keeps its worktree (its branch is fixed by its id); one that has neither can move it to another name ending with -demo-<id>
    again = json.loads(af.read_text(encoding="utf-8"))
    again["lanes"][0]["worktree"] = wt_path(tmp_path, "api", prefix="moved")
    rc, v = jplan(guard, demo, write_spec(tmp_path, again, "again.json"), "--amend", "--expect-revision", "5")
    assert rc == 24 and ("lanes[0].worktree", "STATE") in errors_of(v), v
    again = json.loads(af.read_text(encoding="utf-8"))
    again["lanes"][0]["branch"] = "agent/demo/api2"
    rc, v = jplan(guard, demo, write_spec(tmp_path, again, "again.json"), "--amend", "--expect-revision", "5")
    assert rc == 24 and ("lanes[0].branch", "BRANCH_FORM") in errors_of(v), v
    again = json.loads(af.read_text(encoding="utf-8"))
    again["lanes"][1]["worktree"] = wt_path(tmp_path, "ui", prefix="moved")
    v = plan_ok(guard, demo, write_spec(tmp_path, again, "again.json"), "--amend", "--expect-revision", "5")
    rec = record(demo)
    assert v["revision"] == 6 and lane_of(rec, "ui")["worktree"] == wt_path(tmp_path, "ui", prefix="moved") and lane_of(rec, "ui")["state"] == "blocked"
    assert "worktree=" + wt_path(tmp_path, "ui", prefix="moved") in (claims / "ui.claim").read_text(encoding="utf-8").split("\n")


def test_amend_refuses_removal_and_shrink_of_started_lanes(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    w1, w2 = wt_dir(tmp_path, "api"), wt_dir(tmp_path, "ui")
    demo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(w1), "main")
    demo.commit("src/api/x.py", "x\n", cwd=w1, msg="api")
    demo.write("tests/api/new.py", "uncommitted\n", base=w1)
    demo.git("worktree", "add", "-q", "-b", "agent/demo/ui", str(w2), "main")
    demo.commit("src/ui/y.py", "y\n", cwd=w2, msg="ui")
    demo.git("branch", "agent/demo/docs", "main")  # docs: merged into main
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

    def without(lid):  # every requirement stays served: the lanes that are left take over those of the lane that goes
        return lambda s: drop_lane(s, lid)
    v = refused(without("ui"))
    assert {"lane": "ui", "reason": "UNMERGED_WORK", "files": []} in v["blocked"] and "the branch agent/demo/ui of lane ui has unmerged work" in v["message"]
    v = refused(without("api"))
    assert {(b["lane"], b["reason"]) for b in v["blocked"]} == {("api", "UNMERGED_WORK"), ("api", "DIRTY_WORKTREE")}
    assert next(b for b in v["blocked"] if b["reason"] == "DIRTY_WORKTREE")["files"] == ["tests/api/new.py"]
    v = refused(lambda s: s.update(shared=[]) or s["lanes"][0].update(paths=["src/api/y.py"]))
    assert v["blocked"] == [{"lane": "api", "reason": "SHRINK", "files": ["src/api/x.py", "tests/api/new.py"]}]  # committed and uncommitted
    assert "lane api already changed files outside its new manifest: src/api/x.py, tests/api/new.py" in v["message"]
    v = refused(lambda s: s["lanes"][0].update(paths=["src/api/", "package-lock.json"]))
    assert v["blocked"] == [{"lane": "api", "reason": "SHRINK", "files": ["tests/api/new.py"]}]  # below an uncommitted file
    demo.git("mv", "src/api/a.py", "src/api/renamed.py", cwd=w1)
    v = refused(lambda s: s["lanes"][0].update(paths=["src/api/renamed.py", "src/api/x.py", "tests/api/new.py", "package-lock.json"]))
    assert v["blocked"] == [{"lane": "api", "reason": "SHRINK", "files": ["src/api/a.py"]}]  # a rename counts both names
    both = refused(lambda s: (s.update(shared=[]), s["lanes"][0].update(paths=["web/"]), drop_lane(s, "ui")))
    assert {b["lane"] for b in both["blocked"]} == {"api", "ui"}  # every offending lane is named
    # the lane that holds nothing can be removed: the claim goes, the branch and the worktrees stay
    v = plan_ok(guard, demo, amended(without("docs")), "--amend", "--expect-revision", "1")
    assert v["revision"] == 2 and not (store_dir(demo) / "claims" / "agent" / "demo" / "docs.claim").exists()
    assert [x["id"] for x in record(demo)["lanes"]] == ["api", "ui"]
    assert branches(demo) == ["agent/demo/api", "agent/demo/docs", "agent/demo/ui", "main"] and demo.git("worktree", "list", "--porcelain").count("worktree ") == 3
    assert [x for x in audit_lines(demo) if x["op"] == "set-amend"][0]["removed"] == ["docs"]

    def add_extra(s):
        drop_lane(s, "docs")
        s["lanes"].append(lane(tmp_path, "extra", ["extra/"]))
    plan_ok(guard, demo, amended(add_extra, "add.json"), "--amend", "--expect-revision", "2")
    v = plan_ok(guard, demo, amended(without("docs"), "drop.json"), "--amend", "--expect-revision", "3")  # a lane that has no branch (extra) goes
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
    assert rc == 10 and v["code"] == "CONFLICT" and set(v) == COMMON_KEYS | {"lanes"} and [x["id"] for x in v["lanes"]] == ["ui"]
    lane2 = v["lanes"][0]
    assert lane2["branch"] == "agent/demo/ui" and lane2["code"] == "CONFLICT" and lane2["conflicts"][0]["branch"] == "agent/other" and lane2["conflicts"][0]["evidence"][0]["kind"] == "declared"
    text = guard(r, *sp_args(f)).out
    assert "lane ui (branch agent/demo/ui):" in text and "agent/other" in text and "declared in the ledger" in text
    assert "set-plan neither reads nor consumes an override" in text and "override --fingerprint" not in text
    assert not (store_dir(r) / "sets").exists() and not (store_dir(r) / "claims" / "agent" / "demo").exists()  # only the plain claim exists
    r, f = case("c2", committed)
    rc, v = jplan(guard, r, f)
    assert rc == 10 and [x["id"] for x in v["lanes"]] == ["docs"] and v["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "committed" and v["lanes"][0]["conflicts"][0]["branch"] == "feature/x"
    r, f = case("c3", uncommitted)
    rc, v = jplan(guard, r, f)
    assert rc == 10 and [x["id"] for x in v["lanes"]] == ["api"] and v["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "uncommitted"
    r, f = case("c4", lambda r: (plain_claim(r), committed(r), uncommitted(r)))
    rc, v = jplan(guard, r, f)
    assert rc == 10 and [x["id"] for x in v["lanes"]] == ["api", "ui", "docs"]  # every offending lane at once
    # an unreadable claim and a claim of a newer format deny the whole set
    def garbage(r):
        p = store_dir(r) / "claims" / "zz.claim"
        p.parent.mkdir(parents=True)
        p.write_text("garbage", encoding="utf-8")
    r, f = case("c5", garbage)
    rc, v = jplan(guard, r, f)
    assert rc == 11 and v["code"] == "UNKNOWN" and [x["id"] for x in v["lanes"]] == ["api", "ui", "docs"] and v["lanes"][0]["unknowns"][0]["code"] == "CLAIM_UNPARSEABLE"

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
    def spec_of(*topics):
        return write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, t, ["d%d/" % i]) for i, t in enumerate(topics)]))
    # the clashes with the refs of the repository are exit 12: a ref that would be both a file and a directory, a collision ignoring case, a directory of the integration branch
    for existing, field, other in (("agent/demo", "lanes[0].branch", "lane api"), ("Agent/Demo/Api", "lanes[0].branch", "lane api"),
                                   ("agent/demo/integration/x", "integration", "lane integration")):
        demo.git("branch", existing, "main")
        rc, v = jplan(guard, demo, spec_of("api", "ui"), "--dry-run")
        assert rc == 12 and v["code"] == "INVALID_MANIFEST" and set(v) == COMMON_KEYS | {"errors"}, (existing, v)
        assert v["errors"][0]["field"] == field and v["errors"][0]["code"] == "BRANCH_NAME" and existing in v["errors"][0]["text"] and other in v["errors"][0]["text"], v
        assert "[BRANCH_NAME]" in guard(demo, *sp_args(spec_of("api", "ui"), "demo", "main", "--dry-run")).out
        assert not store_dir(demo).exists()  # nothing is written
        demo.git("branch", "-D", existing)
    # a lane branch equal to the target (the target is a local branch) is a spec rule: exit 24
    demo.git("branch", "agent/demo/api", "main")
    rc, v = jplan(guard, demo, spec_of("api", "ui"), "--dry-run", target="agent/demo/api")
    assert rc == 24 and v["code"] == "INVALID_SPEC" and ("lanes[0].branch", "BRANCH_NAME") in errors_of(v), v
    demo.git("branch", "-D", "agent/demo/api")
    # the lane branches of one spec cannot clash with each other or with the integration branch: they are agent/<set>/<id> of unique lower-case slugs, and integration is no id
    assert plan_ok(guard, demo, spec_of("alpha", "alpha-two", "alpha-two-more"))["revision"] == 1  # prefixes of one another as names, never as refs
    assert not branches(demo).count("agent/demo/alpha")  # nothing was created
    for t, rec_lane in zip(("alpha", "alpha-two", "alpha-two-more"), record(demo)["lanes"]):
        assert rec_lane["branch"] == "agent/demo/" + t


def test_worktree_path_rules(demo, guard, tmp_path):
    win = os.name == "nt"

    def one(value, name="w", extra=None):
        s = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/"], worktree=value)] + (extra or []))
        return jplan(guard, demo, write_spec(tmp_path, s, name + ".json"), "--dry-run")
    base = P(tmp_path / "lanes")
    named = base + "/repo-demo-api"  # every spelling meant to be valid ends with -demo-api after a prefix (the name rule is TC-316)
    invalid = ["wt/a", "./wt", "~/wt", "C:rel", base + "/a/../b", base + "/a\x01b", "/" + "x" * 4097 if not win else "C:/" + "x" * 4094, "\\wt"]
    invalid += ["/wt"] if win else ["/tmp/a\\b"]
    for value in invalid:
        rc, v = one(value)
        assert rc == 24 and v["errors"][0]["field"] == "lanes[0].worktree" and v["errors"][0]["code"] == "WORKTREE", (value[:40], v)
        assert [e["field"] for e in v["errors"]] == ["lanes[0].worktree"], (value[:40], v)  # a spelling that is invalid gets no name error: one error
    assert one(named)[0] == 0
    if win:
        rc, v = one("/c/lanes/repo-demo-api")  # the Git Bash spelling is stored as the drive path
        assert rc == 0 and v["lanes"][0]["worktree"] == "C:/lanes/repo-demo-api" and v["lanes"][0]["create"].startswith('git worktree add "C:/lanes/repo-demo-api" -b')
        rc, v = one("//server/share/repo-demo-api")
        assert rc == 0 and v["lanes"][0]["worktree"] == "//server/share/repo-demo-api"
        rc, v = one("C:\\lanes\\a\\.\\repo-demo-api")
        assert rc == 0 and v["lanes"][0]["worktree"] == "C:/lanes/a/repo-demo-api"
    # two lane worktrees are never equal and never one inside the other (the names of two lanes differ, so a shared path is a name error of the second lane)
    two = [lane(tmp_path, "ui", ["web/"], worktree=named)]
    rc, v = one(named, "same", two)
    assert rc == 24 and v["errors"][0]["field"] == "lanes[1].worktree"
    inner = base + "/outer-demo-api/inner-demo-ui"
    rc, v = one(base + "/outer-demo-api", "inside", [lane(tmp_path, "ui", ["web/"], worktree=inner)])
    assert rc == 24 and v["errors"][0]["field"] == "lanes[1].worktree" and v["errors"][0]["code"] == "WORKTREE"
    rc, v = one(base + "/inner-demo-ui/deep-demo-api", "inside2", [lane(tmp_path, "ui", ["web/"], worktree=base + "/inner-demo-ui")])
    assert rc == 24 and v["errors"][0]["field"] == "lanes[1].worktree"
    rc, v = one(base + "/OUT-demo-api", "case", [lane(tmp_path, "ui", ["web/"], worktree=base + "/out-demo-api/x-demo-ui")])
    assert (rc == 24) == win  # case differences compare equal where the platform folds them
    linked = tmp_path / "area-demo-api" / "linked"
    demo.git("worktree", "add", "-q", "-b", "agent/linked", str(linked), "main")
    for value in (P(demo.path / "sub" / "wt-demo-api"), P(common_dir(demo) / "x-demo-api"), P(linked / "inner-demo-api"), P(tmp_path / "area-demo-api")):
        rc, v = one(value)  # inside a worktree, inside the git directory, inside a linked worktree, and one that contains worktrees
        assert rc == 12 and v["code"] == "INVALID_MANIFEST" and v["errors"][0]["code"] == "WORKTREE" and v["errors"][0]["field"] == "lanes[0].worktree", (value, v)
    # an amend whose lane already has its worktree at that path on its own branch
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    plan_ok(guard, demo, f)
    demo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(wt_dir(tmp_path, "api")), "main")
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][0]["title"] = "renamed"
    assert plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "1")["revision"] == 2
    # the stored spelling is what the hook compares: another separator style is the same path, another path is refused
    cwd = str(demo.path)
    stored = record(demo)["lanes"][1]["worktree"]
    assert stored == wt_path(tmp_path, "ui")
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
            for value in ("wt/wt-demo-api", "/tmp/wt-demo-api"):  # and the command, which reads the same spellings (named as the name rule asks)
                s = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/"], worktree=value)])
                r = guard(demo, "--json", *sp_args(write_spec(tmp_path, s), "demo", "main", "--dry-run"))
                assert (r.rc == 24) == (G.lane_worktree(value)[0] is None), (value, r.out)
    assert all(isinstance(x, tuple) and (x[0] is None) != (x[1] is None) for x in expected)


# ---- TC-268 .. TC-271: set-update ----------------------------------------------------------------------------------------------------
UPDATE_KEYS = COMMON_KEYS | {"set", "lane", "state", "head", "changes", "note", "integration", "revision", "warnings"}
SHOW_KEYS = COMMON_KEYS | {"record", "view", "warnings"}
RELEASE_KEYS = COMMON_KEYS | {"set", "abandoned", "released", "warnings"}
LANE_VIEW_KEYS = ["id", "branch_exists", "tip", "ahead", "descends_from_base", "worktree_present", "worktree_clean", "operation", "state", "head", "claim", "changes"]
DRIFT_LANE_KEYS = LANE_VIEW_KEYS + ["changed", "out_of_lane", "moved_since_ready"]
LANES = {"api": "agent/demo/api", "ui": "agent/demo/ui", "docs": "agent/demo/docs"}
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


def start_lane(repo, tmp_path, lid, files=None, msg=None, prefix="wt"):
    """The lane `lid` of the demo set created as the plan prints it (a worktree at its registered path on its branch, cut from main), with one
    commit that adds `files` {path: text} when given: -> (worktree path, tip)."""
    wt = wt_dir(tmp_path, lid, prefix=prefix)
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
    wt, tip = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n", "tests/api/t.py": "t\n"})
    assert upd(guard, demo, "api", "active")[0] == 0
    rev = record(demo)["revision"]
    rc, v = upd(guard, demo, "api", "ready", "--head", tip)  # inside the manifest
    assert rc == 0 and set(v) == UPDATE_KEYS and v["code"] == "OK" and v["decision"] == "allow" and v["exit_code"] == 0 and v["warnings"] == []
    assert (v["set"], v["lane"], v["state"], v["head"], v["revision"], v["integration"], v["note"]) == ("demo", "api", "ready", tip, rev + 1, None, "")
    rec = record(demo)
    assert lane_of(rec, "api")["state"] == "ready" and lane_of(rec, "api")["head"] == tip and rec["revision"] == rev + 1
    # a file of another lane's manifest: refused with exit 22, in both languages, and nothing is written
    demo.commit("src/ui/x.py", "x\n", cwd=wt, msg="outside")
    bad = demo.git("rev-parse", "agent/demo/api")
    before = record_file(demo).read_bytes()
    args = update_args("api", "ready", rev + 1, "--head", bad)
    rc, v = jcall(guard, demo, *args)
    assert rc == 22 and v["code"] == "OUT_OF_LANE" and set(v) == COMMON_KEYS | {"lane", "files", "truncated"} and v["lane"] == "api" and v["files"] == ["src/ui/x.py"] and v["truncated"] is False
    assert guard(demo, *args).out.rstrip("\n") == ("MAGOS: refused to mark lane api ready: these files lie outside its manifest: src/ui/x.py. "
                                                   "Revert them in the lane, or amend the plan with /GitPlan demo --amend.")
    zh = run(["--repo", str(demo.path), "--lang", "zh", *args])
    assert zh.rc == 22 and "拒绝把 lane api 标记为 ready" in zh.out and "src/ui/x.py" in zh.out and record_file(demo).read_bytes() == before
    # a rename counts both names: the old one is inside the manifest, the new one is not
    demo.git("reset", "-q", "--hard", tip, cwd=wt)
    (wt / "lib").mkdir()
    demo.git("mv", "src/api/a.py", "lib/a.py", cwd=wt)
    demo.git("commit", "-q", "-m", "rename", cwd=wt)
    renamed = demo.git("rev-parse", "agent/demo/api")
    v = upd_refused(guard, demo, "api", "ready", "--head", renamed, rc_want=22)
    assert v["files"] == ["lib/a.py"]
    # merging the target into the lane charges the lane with none of the target's files
    demo.git("reset", "-q", "--hard", tip, cwd=wt)
    demo.commit("README.md", "moved by an unrelated commit\n")
    demo.git("merge", "-q", "-m", "merge main", "main", cwd=wt)
    merged = demo.git("rev-parse", "agent/demo/api")
    assert upd_ok(guard, demo, "api", "ready", "--head", merged)["head"] == merged
    # a deleted file inside the manifest is a change inside it
    demo.git("rm", "-q", "src/api/a.py", cwd=wt)
    demo.git("commit", "-q", "-m", "delete", cwd=wt)
    deleted = demo.git("rev-parse", "agent/demo/api")
    assert upd_ok(guard, demo, "api", "ready", "--head", deleted)["state"] == "ready"
    # a lane without commits may be ready
    _, tip3 = start_lane(demo, tmp_path, "docs")
    assert tip3 == demo.git("rev-parse", "main") and ready_lane(guard, demo, "docs", tip3)["state"] == "ready"
    # a lane that shares no history with the target
    orphan = demo.git("commit-tree", demo.git("mktree", inp=b""), "-m", "orphan")
    demo.git("update-ref", "refs/heads/" + LANES["ui"], orphan)
    upd_ok(guard, demo, "ui", "active")
    v = upd_refused(guard, demo, "ui", "ready", "--head", orphan, rc_want=16)
    assert v["blocked"] == [{"lane": "ui", "reason": "NO_MERGE_BASE"}] and set(v) == COMMON_KEYS | {"blocked"} and "shares no history with the plan's base" in v["message"]
    # more files outside than the listing carries
    demo.git("update-ref", "-d", "refs/heads/" + LANES["ui"])
    fast_commit(demo, LANES["ui"], {"zz/f%03d.txt" % i: "x\n" for i in range(201)})
    big = demo.git("rev-parse", LANES["ui"])
    v = upd_refused(guard, demo, "ui", "ready", "--head", big, rc_want=22)
    assert len(v["files"]) == 200 and v["truncated"] is True and v["files"] == sorted(v["files"])
    # the target branch deleted: the plan's base is the reference
    demo.git("worktree", "remove", "--force", str(wt))  # the registered path is free again for the second repository
    r = make_repo(tmp_path, "gone")
    plan_ok(guard, r, write_spec(tmp_path, demo_spec(r, tmp_path)))
    wt, tip = start_lane(r, tmp_path, "api", {"src/api/a.py": "a\n"})
    upd_ok(guard, r, "api", "active")
    r.git("switch", "-q", "-c", "scratch")
    r.git("branch", "-q", "-D", "main")  # the target branch no longer exists: the plan's base stands in for it
    assert upd_ok(guard, r, "api", "ready", "--head", tip)["state"] == "ready"
    r.commit("docs/new.md", "n\n", cwd=wt, msg="outside")
    v = upd_refused(guard, r, "api", "ready", "--head", r.git("rev-parse", LANES["api"]), rc_want=22)
    assert v["files"] == ["docs/new.md"]


def test_ready_needs_the_branch_tip_a_clean_worktree_and_no_operation(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, tip = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n"})
    upd_ok(guard, demo, "api", "active")
    v = upd_ok(guard, demo, "api", "ready", "--head", tip.upper())  # the tip in any case; stored in lower case
    assert v["head"] == tip and lane_of(record(demo), "api")["head"] == tip
    assert upd_ok(guard, demo, "api", "ready", "--head", tip)["state"] == "ready"
    main_tip = demo.git("rev-parse", "main")
    v = upd_refused(guard, demo, "api", "ready", "--head", main_tip, rc_want=16)
    assert v["blocked"] == [{"lane": "api", "reason": "HEAD_MISMATCH"}] and ("--head %s is not the tip %s of branch agent/demo/api" % (main_tip, tip)) in v["message"]
    for head in (tip[:7], tip + "0", "z" * 40):  # an abbreviation, 41 digits, not hexadecimal
        v = upd_refused(guard, demo, "api", "ready", "--head", head, rc_want=24)
        assert errors_of(v) == {("--head", "FORMAT")}
    rc, v = jcall(guard, demo, *update_args("api", "ready", record(demo)["revision"]))  # no --head
    assert rc == 24 and errors_of(v) == {("--head", "MISSING")}
    v = upd_refused(guard, demo, "api", "active", "--head", tip, rc_want=24)  # options that do not belong to the state
    assert errors_of(v) == {("--head", "STATE")}
    v = upd_refused(guard, demo, "api", "ready", "--head", tip, "--integration", INTEGRATION, rc_want=24)
    assert errors_of(v) == {("--integration", "STATE")}
    # no branch
    upd_ok(guard, demo, "ui", "active")
    v = upd_refused(guard, demo, "ui", "ready", "--head", main_tip, rc_want=16)
    assert v["blocked"] == [{"lane": "ui", "reason": "BRANCH_MISSING"}] and "the branch agent/demo/ui of lane ui does not exist" in v["message"]
    # an uncommitted file
    stray = demo.write("src/api/stray.txt", "u\n", base=wt)
    v = upd_refused(guard, demo, "api", "ready", "--head", tip, rc_want=16)
    assert v["blocked"] == [{"lane": "api", "reason": "DIRTY_WORKTREE"}] and "the worktree of lane api has uncommitted changes" in v["message"]
    stray.unlink()
    # a merge in progress and a rebase in progress
    demo.commit("src/api/c.py", "lane\n", cwd=wt, msg="c")
    tip = demo.git("rev-parse", "agent/demo/api")
    other = tmp_path / "other"
    demo.git("worktree", "add", "-q", "-b", "other", str(other), "main")
    demo.commit("src/api/c.py", "other\n", cwd=other, msg="other")
    demo.git("merge", "other", cwd=wt, check=False)
    v = upd_refused(guard, demo, "api", "ready", "--head", tip, rc_want=16)
    assert {"lane": "api", "reason": "OPERATION_IN_PROGRESS"} in v["blocked"] and "has a merge in progress" in v["message"]
    demo.git("merge", "--abort", cwd=wt)
    demo.git("rebase", "other", cwd=wt, check=False)
    v = upd_refused(guard, demo, "api", "ready", "--head", demo.git("rev-parse", "agent/demo/api"), rc_want=16)
    assert {"lane": "api", "reason": "OPERATION_IN_PROGRESS"} in v["blocked"] and "rebase" in v["message"]
    demo.git("rebase", "--abort", cwd=wt)
    assert demo.git("rev-parse", "agent/demo/api") == tip
    # no worktree at all is fine: a lane may be recorded from the branch alone
    demo.git("worktree", "remove", "--force", str(wt))
    assert upd_ok(guard, demo, "api", "ready", "--head", tip)["head"] == tip


def test_integrated_needs_the_head_in_the_target_or_the_integration_branch(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    tips = {lid: start_lane(demo, tmp_path, lid, {path: lid + "\n"})[1] for lid, path in (("api", "src/api/a1.py"), ("ui", "src/ui/u2.py"), ("docs", "docs/d3.md"))}
    for lid, tip in tips.items():
        ready_lane(guard, demo, lid, tip)
    integrate(demo, LANES["api"], LANES["ui"])
    v = upd_refused(guard, demo, "api", "integrated", "--head", tips["api"], rc_want=24)  # the record names no integration branch yet
    assert errors_of(v) == {("--integration", "MISSING")}
    v = upd_refused(guard, demo, "api", "integrated", "--head", tips["api"], "--integration", "agent/demo/other", rc_want=24)
    assert errors_of(v) == {("--integration", "FORMAT")} and INTEGRATION in v["errors"][0]["text"]
    v = upd_ok(guard, demo, "api", "integrated", "--head", tips["api"], "--integration", INTEGRATION, "--note", "merged")
    assert (v["state"], v["head"], v["integration"], v["note"]) == ("integrated", tips["api"], INTEGRATION, "merged") and record(demo)["integration"] == INTEGRATION
    summary = {"commits": 1, "subjects": ["api"], "more": 0, "files": 1, "insertions": 1, "deletions": 0, "paths": ["src/api"], "paths_more": 0}  # the lane's commits (TC-319)
    assert v["changes"] == summary and lane_of(record(demo), "api")["changes"] == summary
    assert upd_ok(guard, demo, "ui", "integrated", "--head", tips["ui"])["integration"] == INTEGRATION  # the record's branch is used
    ui_changes = lane_of(record(demo), "ui")["changes"]
    assert ui_changes["subjects"] == ["ui"] and ui_changes["paths"] == ["src/ui"]
    assert upd_ok(guard, demo, "ui", "integrated", "--head", tips["ui"], "--integration", INTEGRATION, "--note", "again")["note"] == "again"  # integrated to integrated: a note
    assert lane_of(record(demo), "ui")["changes"] == ui_changes  # and the summary stays
    v = upd_refused(guard, demo, "ui", "integrated", "--head", tips["api"], rc_want=16)  # not the head recorded for the lane
    assert v["blocked"] == [{"lane": "ui", "reason": "HEAD_MISMATCH"}] and ("is not the head %s recorded for lane ui at ready" % tips["ui"]) in v["message"]
    v = upd_refused(guard, demo, "docs", "integrated", "--head", tips["docs"], rc_want=16)  # in neither the target nor the integration branch
    assert v["blocked"] == [{"lane": "docs", "reason": "NOT_MERGED"}] and ("commit %s is in neither main nor the integration branch" % tips["docs"]) in v["message"]
    zh = run(["--repo", str(demo.path), "--lang", "zh", *update_args("docs", "integrated", record(demo)["revision"], "--head", tips["docs"])])
    assert zh.rc == 16 and "拒绝 set-update" in zh.out and "既不在 main 中，也不在集成分支中" in zh.out
    v = upd_refused(guard, demo, "docs", "integrated", "--head", tips["api"], rc_want=16)
    assert v["blocked"] == [{"lane": "docs", "reason": "HEAD_MISMATCH"}]
    edit_record(demo, lambda rec: rec.update(integration="agent/demo/old-name"))  # a record that names another branch: --integration must be that one
    v = upd_refused(guard, demo, "ui", "integrated", "--head", tips["ui"], "--integration", INTEGRATION, rc_want=24)
    assert errors_of(v) == {("--integration", "STATE")} and "agent/demo/old-name" in v["errors"][0]["text"]
    edit_record(demo, lambda rec: rec.update(integration=INTEGRATION))
    upd_ok(guard, demo, "docs", "active")  # a lane that is not ready cannot be integrated
    v = upd_refused(guard, demo, "docs", "integrated", "--head", tips["docs"], rc_want=24)
    assert errors_of(v) == {("--state", "STATE")} and "lane docs is active" in v["errors"][0]["text"]
    assert lane_of(record(demo), "docs")["changes"] is None  # every refusal left the lane without a summary
    upd_ok(guard, demo, "docs", "ready", "--head", tips["docs"])
    demo.git("branch", "-m", INTEGRATION, "agent/demo/old")  # the integration branch is gone
    v = upd_refused(guard, demo, "docs", "integrated", "--head", tips["docs"], rc_want=16)
    assert v["blocked"] == [{"lane": "docs", "reason": "BRANCH_MISSING"}] and "the integration branch agent/demo/integration does not exist" in v["message"]
    demo.git("branch", "-m", "agent/demo/old", INTEGRATION)
    demo.git("merge", "-q", "--no-ff", "-m", "land docs", LANES["docs"])  # merged into main itself, not into the integration branch
    assert lane_of(record(demo), "docs")["changes"] is None
    landed = upd_ok(guard, demo, "docs", "integrated", "--head", tips["docs"])  # a head already in the target is accepted
    assert landed["state"] == "integrated"
    assert landed["changes"] == {"commits": 1, "subjects": ["docs"], "more": 0, "files": 1, "insertions": 1, "deletions": 0, "paths": ["docs/d3.md"], "paths_more": 0}  # measured against the plan's base
    assert [lane_of(record(demo), x)["state"] for x in ("api", "ui", "docs")] == ["integrated"] * 3


def test_the_transition_table_and_the_option_rules(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    allowed = {"planned": {"active", "blocked"}, "active": {"active", "ready", "blocked"}, "ready": {"active", "ready", "integrated", "blocked"},
               "integrated": {"integrated", "blocked"}, "blocked": {"active", "blocked"}}
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    _, tip = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n"})
    integrate(demo, LANES["api"])  # the conditions of ready and of integrated hold for the lane
    path = record_file(demo)
    stored = {"commits": 4, "subjects": ["s1", "s2"], "more": 2, "files": 7, "insertions": 8, "deletions": 9, "paths": ["x"], "paths_more": 3}  # a summary the lane already holds
    for frm in G.LANE_STATES:
        for to in ("active", "ready", "integrated", "blocked"):
            def seed(rec, frm=frm):
                lane_of(rec, "api").update(state=frm, head=tip if frm in ("ready", "integrated") else None, note="n", changes=stored if frm == "integrated" else None)
                rec.update(revision=7, integration=None)
            seeded = edit_record(demo, seed)
            before = path.read_text(encoding="utf-8")
            extra = (["--head", tip] if to in ("ready", "integrated") else []) + (["--integration", INTEGRATION] if to == "integrated" else [])
            rc, v = upd(guard, demo, "api", to, *extra, rev=7)
            if to in allowed[frm]:
                assert rc == 0 and v["revision"] == 8 and v["state"] == to, (frm, to, v)
                after = record(demo)
                assert after["revision"] == 8 and lane_of(after, "api")["state"] == to and lane_of(after, "api")["note"] == "n"  # no --note: the note stays
                assert lane_of(after, "api")["updated"] != lane_of(seeded, "api")["updated"] and after["updated"] != seeded["updated"]
                keys = {k for k in changed_keys(before, path.read_text(encoding="utf-8")) if not k.startswith(("+", "-"))}  # a list item is a line of its own
                assert keys <= {"revision", "updated", "by", "state", "head", "note", "integration", "changes", "commits", "subjects", "more", "files", "insertions", "deletions",
                                "paths", "paths_more"}, (frm, to, keys)
                lane_changes = lane_of(after, "api")["changes"]  # the summary: kept by a repeated integrated, computed by ready to integrated, null for every other state
                if to != "integrated":
                    assert lane_changes is None, (frm, to)
                elif frm == "integrated":
                    assert lane_changes == stored, (frm, to)
                else:
                    assert lane_changes["commits"] == 1 and lane_changes["subjects"] == ["api"] and lane_changes["paths"] == ["src/api"], (frm, to, lane_changes)
                assert lane_of(after, "api")["head"] == (tip if to in ("ready", "integrated") or frm == "ready" or frm == "integrated" else None), (frm, to)
                assert after["integration"] == (INTEGRATION if to == "integrated" else None)
            else:
                assert rc == 24 and v["errors"][0]["field"] == "--state" and v["errors"][0]["code"] == "STATE" and ("lane api is %s" % frm) in v["errors"][0]["text"], (frm, to, v)
                assert path.read_text(encoding="utf-8") == before, (frm, to)
    r = guard(demo, *update_args("api", "planned", 7))  # planned is the initial state, never a value of --state
    assert r.rc == 2 and r.out == "" and "invalid choice" in r.err
    edit_record(demo, lambda rec: (lane_of(rec, "api").update(state="active", head=None), rec.update(revision=7, integration=None)))
    for note in ("x" * 200, "日本" * 100):
        assert upd_ok(guard, demo, "api", "active", "--note", note)["note"] == note
    rev = record(demo)["revision"]
    for note, field_code in (("x" * 201, "RANGE"), ("a\nb", "FORMAT"), ("a\x00b", "FORMAT"), ("a\tb", "FORMAT"), ("\ud800", "ENCODING")):
        v = upd_refused(guard, demo, "api", "active", "--note", note, rc_want=24)
        assert errors_of(v) == {("--note", field_code)}, (note, v)
    assert upd_ok(guard, demo, "api", "active", "--note", "")["note"] == "" and lane_of(record(demo), "api")["note"] == ""  # an empty value clears the note
    upd_ok(guard, demo, "api", "active", "--note", "again")
    assert upd_ok(guard, demo, "api", "blocked")["note"] == "again"
    v = upd_refused(guard, demo, "L9", "active", rc_want=24)  # an unknown lane names the ids
    assert v["errors"] == [{"field": "--lane", "code": "UNKNOWN_LANE", "text": "set demo has the lanes api, ui, docs"}]
    current = record(demo)["revision"]
    for bad in ("0", "01", "+1", "1000000000", "-1", "x", ""):  # a revision is 1 to 999999999 written plainly
        r = guard(demo, "set-update", "--set", "demo", "--expect-revision", bad, "--lane", "api", "--state", "active")
        assert r.rc == 2 and r.out == "" and "--expect-revision" in r.err, bad
    r = guard(demo, "set-update", "--set", "demo", "--lane", "api", "--state", "active")  # required options
    assert r.rc == 2 and "--expect-revision" in r.err
    assert guard(demo, "set-update", "--set", "demo", "--expect-revision", "1", "--state", "active").rc == 2
    v = upd_refused(guard, demo, "api", "active", rev=current - 1, rc_want=19)  # stale: names the current revision
    assert (v["kind"], v["expected"], v["current"]) == ("revision", current - 1, current) and set(v) == COMMON_KEYS | {"kind", "expected", "current"}
    assert ("set 'demo' is at revision %d, not %d" % (current, current - 1)) in v["message"]
    assert upd_ok(guard, demo, "api", "active", rev=current)["revision"] == current + 1


# ---- TC-272 .. TC-276: set-show ----------------------------------------------------------------------------------------------------------
def test_set_show_fields_without_drift(demo, guard, tmp_path, monkeypatch):
    spec = demo_spec(demo, tmp_path)
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    base = spec["base"]
    wt1, _ = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n"})
    demo.commit("src/api/b.py", "b\n", cwd=wt1, msg="second")
    tip1 = demo.git("rev-parse", LANES["api"])
    wt3, tip3 = start_lane(demo, tmp_path, "docs", {"docs/x.md": "lane\n"})
    other = tmp_path / "other"  # a merge in progress and an uncommitted file in the worktree of docs
    demo.git("worktree", "add", "-q", "-b", "other", str(other), "main")
    demo.commit("docs/x.md", "other\n", cwd=other, msg="other")
    demo.git("merge", "other", cwd=wt3, check=False)
    demo.write("docs/untracked.md", "u\n", base=wt3)
    store_before = store_files(demo)
    v = jshow(guard, demo)
    assert set(v) == SHOW_KEYS and v["code"] == "OK" and v["decision"] == "allow" and v["exit_code"] == 0 and v["warnings"] == []
    assert v["record"] == record(demo)  # the record as stored
    view = v["view"]
    assert list(view) == ["target_tip", "target_moved", "lanes", "requirements"] and "drift" not in view and view["target_tip"] == base and view["target_moved"] is False
    assert view["requirements"] == [{"id": "R1", "text": REQUIREMENTS[0]["text"], "lanes": ["api"]}, {"id": "R2", "text": REQUIREMENTS[1]["text"], "lanes": ["ui"]},
                                    {"id": "R3", "text": REQUIREMENTS[2]["text"], "lanes": ["docs"]}]  # in the record's order, with the lanes that serve each
    assert [x["id"] for x in view["lanes"]] == ["api", "ui", "docs"] and all(list(x) == LANE_VIEW_KEYS for x in view["lanes"])
    l1, l2, l3 = view["lanes"]
    assert l1 == {"id": "api", "branch_exists": True, "tip": tip1, "ahead": 2, "descends_from_base": True, "worktree_present": True, "worktree_clean": True,
                  "operation": [], "state": "planned", "head": None, "claim": "ok", "changes": None}
    assert l2 == {"id": "ui", "branch_exists": False, "tip": None, "ahead": None, "descends_from_base": None, "worktree_present": False, "worktree_clean": None,
                  "operation": [], "state": "planned", "head": None, "claim": "ok", "changes": None}
    assert (l3["branch_exists"], l3["tip"], l3["ahead"], l3["worktree_present"], l3["worktree_clean"], l3["operation"]) == (True, tip3, 1, True, False, ["merge"])
    assert store_files(demo) == store_before and not any(p.suffix == ".tmp" for p in store_dir(demo).rglob("*"))  # set-show writes nothing
    # the claim of a lane: missing, or a mismatch when it lacks set= or lane=, or its entries differ, or it cannot be read
    claim = store_dir(demo) / "claims" / "agent" / "demo" / "api.claim"
    good = claim.read_bytes()
    for edited, want in ((good.replace(b"lane=api\n", b""), "mismatch"), (good.replace(b"set=demo\n", b""), "mismatch"), (good.replace(b"entry=src/api/", b"entry=src/other/"), "mismatch"),
                         (good.replace(b"v=1\n", b"v=2\n"), "mismatch"), (good.replace(b"state=active", b"junk"), "mismatch"), (None, "missing")):
        if edited is None:
            claim.unlink()
        else:
            claim.write_bytes(edited)
        assert jshow(guard, demo)["view"]["lanes"][0]["claim"] == want, (edited, want)
    claim.write_bytes(good)
    assert jshow(guard, demo)["view"]["lanes"][0]["claim"] == "ok"
    # the text view, in both languages: [x] only for ready and integrated lanes
    edit_record(demo, lambda rec: (lane_of(rec, "api").update(state="ready", head=tip1), lane_of(rec, "ui").update(state="integrated", head=base), lane_of(rec, "docs").update(state="blocked")))
    en = guard(demo, "set-show", "--set", "demo")
    assert en.rc == 0 and en.err == ""
    lines = en.out.rstrip("\n").split("\n")
    assert lines[0] == "set 'demo' -> main  base %s  revision 1  integration -" % base[:7] and lines[1:4] == spec["sheet"].rstrip("\n").split("\n")
    assert lines[4:] == ["[x] api  ready  head %s  tip %s  ahead 2  worktree clean  branch agent/demo/api" % (tip1[:7], tip1[:7]),
                         "[x] ui  integrated  head %s  tip -  ahead -  worktree absent  branch agent/demo/ui" % base[:7],
                         "[ ] docs  blocked  head -  tip %s  ahead 1  worktree merge in progress  branch agent/demo/docs" % tip3[:7]]
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
    _, tip1 = start_lane(demo, tmp_path, "api", {"tests/api/t.py": "t\n", "src/api/a.py": "a\n"})
    ready_lane(guard, demo, "api", tip1)
    _, tip3 = start_lane(demo, tmp_path, "docs", {"docs/d3.md": "3\n"})
    upd_ok(guard, demo, "docs", "active")
    v = jshow(guard, demo, "--drift")
    rows = v["view"]["lanes"]
    assert all(list(x) == DRIFT_LANE_KEYS for x in rows) and list(v["view"]["drift"]) == ["shared_changes", "target_overlap", "stale", "merge_order"]
    l1, l2, l3 = rows
    assert (l1["changed"], l1["out_of_lane"], l1["moved_since_ready"]) == (["src/api/a.py", "tests/api/t.py"], [], False)  # the committed files, sorted
    assert (l2["changed"], l2["out_of_lane"], l2["moved_since_ready"]) == (None, [], None)  # no branch
    assert (l3["changed"], l3["out_of_lane"], l3["moved_since_ready"]) == (["docs/d3.md"], [], False)  # not ready: false
    assert v["view"]["drift"] == {"shared_changes": [], "target_overlap": [], "stale": False, "merge_order": ["api", "ui", "docs"]} and v["warnings"] == []
    text = guard(demo, "set-show", "--set", "demo", "--drift").out.rstrip("\n").split("\n")
    assert text[-1] == "merge order: api -> ui -> docs" and not any(x.startswith(("outside the manifest", "changed by more", "the target moved", "moved since")) for x in text)
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo", "--drift"])
    assert zh.out.rstrip("\n").endswith("合并顺序：api -> ui -> docs")


def test_drift_target_moved_without_and_with_overlap(demo, guard, tmp_path):
    demo.commit("README.md", "v2\n")  # the base has a parent
    spec = demo_spec(demo, tmp_path)
    base, root = spec["base"], demo.git("rev-parse", "main~1")
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    _, tip1 = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n"})
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
    assert v["view"]["drift"]["target_overlap"] == [{"path": "docs/a.md", "lanes": ["docs"]}, {"path": "src/ui/layout.py", "lanes": ["ui"]}] and v["view"]["drift"]["stale"] is True
    en = guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines()
    assert "the target moved from %s to %s; files that overlap lanes: docs/a.md [docs], src/ui/layout.py [ui]" % (base[:7], tip[:7]) in en
    assert "目标已从 %s 移到 %s；与 lane 重叠的文件：docs/a.md [docs], src/ui/layout.py [ui]" % (base[:7], tip[:7]) in run(
        ["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo", "--drift"]).out
    # main replaced by another history: the base is no longer an ancestor of the target
    demo.git("reset", "-q", "--hard", root)
    demo.commit("src/ui/layout.py", "other history\n")
    v = jshow(guard, demo, "--drift")
    assert v["view"]["target_moved"] is True and v["view"]["drift"]["target_overlap"] == [{"path": "src/ui/layout.py", "lanes": ["ui"]}] and v["view"]["drift"]["stale"] is True
    # the target deleted: null, and the lane files are measured against the base
    demo.git("switch", "-q", "-c", "scratch")
    demo.git("branch", "-q", "-D", "main")
    v = jshow(guard, demo, "--drift")
    assert (v["view"]["target_tip"], v["view"]["target_moved"], v["view"]["drift"]["stale"], v["view"]["drift"]["target_overlap"]) == (None, None, None, [])
    assert v["view"]["lanes"][0]["changed"] == ["src/api/a.py"] and v["view"]["lanes"][0]["ahead"] == 1 and v["warnings"] == []
    assert not any(x.startswith("the target moved") for x in guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines())


def test_drift_lane_tip_moved_after_ready(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt1, h = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n"})
    ready_lane(guard, demo, "api", h)
    wt2, _ = start_lane(demo, tmp_path, "ui", {"src/ui/u.py": "u\n"})
    upd_ok(guard, demo, "ui", "active")

    def moved():
        v = jshow(guard, demo, "--drift")
        return [x["moved_since_ready"] for x in v["view"]["lanes"]], guard(demo, "set-show", "--set", "demo", "--drift").out
    assert moved()[0] == [False, False, None]
    demo.commit("src/api/b.py", "b\n", cwd=wt1, msg="more")
    flags, text = moved()
    assert flags == [True, False, None] and "moved since ready: api" in text.splitlines()
    assert "ready 之后分支又移动：api" in run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo", "--drift"]).out
    demo.git("reset", "-q", "--hard", h, cwd=wt1)  # back at the recorded head
    assert moved()[0] == [False, False, None]
    demo.commit("src/api/b.py", "b\n", cwd=wt1, msg="more")
    h2 = demo.git("rev-parse", LANES["api"])
    upd_ok(guard, demo, "api", "ready", "--head", h2)  # ready again with the new head
    assert moved()[0] == [False, False, None]
    demo.commit("src/ui/more.py", "m\n", cwd=wt2, msg="a lane that is not ready moves")
    assert moved()[0] == [False, False, None]
    demo.git("worktree", "remove", "--force", str(wt1))
    demo.git("branch", "-q", "-D", LANES["api"])  # no branch: null
    assert moved()[0] == [None, False, None]


def test_drift_files_changed_by_two_lanes(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt1, _ = start_lane(demo, tmp_path, "api", {"package-lock.json": "l1\n", "README.md": "same\n", "src/api/a.py": "a\n"})
    demo.git("rm", "-q", "docs/d.md", cwd=wt1)  # api deletes the file that docs renames
    demo.git("commit", "-q", "-m", "delete", cwd=wt1)
    start_lane(demo, tmp_path, "ui", {"package-lock.json": "l2\n", "README.md": "same\n", "src/api/x.py": "x\n", "src/ui/u.py": "u\n"})
    wt3, _ = start_lane(demo, tmp_path, "docs")
    demo.git("mv", "docs/d.md", "docs/e.md", cwd=wt3)
    demo.git("commit", "-q", "-m", "rename", cwd=wt3)
    v = jshow(guard, demo, "--drift")
    d = v["view"]["drift"]
    assert d["shared_changes"] == [{"path": "README.md", "lanes": ["api", "ui"]}, {"path": "docs/d.md", "lanes": ["api", "docs"]}, {"path": "package-lock.json", "lanes": ["api", "ui"]}]
    l1, l2, l3 = v["view"]["lanes"]
    assert l1["out_of_lane"] == ["README.md", "docs/d.md"] and l2["out_of_lane"] == ["README.md", "package-lock.json", "src/api/x.py"] and l3["out_of_lane"] == []
    assert l3["changed"] == ["docs/d.md", "docs/e.md"]  # a rename changes both names
    text = guard(demo, "set-show", "--set", "demo", "--drift").out.splitlines()
    assert "changed by more than one lane: README.md [api,ui], docs/d.md [api,docs], package-lock.json [api,ui]" in text
    assert "outside the manifest (ui): README.md, package-lock.json, src/api/x.py" in text and "outside the manifest (api): README.md, docs/d.md" in text
    # a lane that shares no history with the target
    r2 = make_repo(tmp_path, "unrelated")
    plan_ok(guard, r2, write_spec(tmp_path, demo_spec(r2, tmp_path), "unrelated.json"))
    orphan = r2.git("commit-tree", r2.git("mktree", inp=b""), "-m", "orphan")
    r2.git("update-ref", "refs/heads/" + LANES["ui"], orphan)
    v = jshow(guard, r2, "--drift")
    assert v["view"]["lanes"][1]["changed"] is None and v["view"]["lanes"][1]["out_of_lane"] == []
    assert [w["code"] for w in v["warnings"]] == ["UNRELATED_HISTORY"] and "ui" in v["warnings"][0]["text"] and v["view"]["lanes"][1]["ahead"] == 1


# ---- TC-277, TC-278: set-release -------------------------------------------------------------------------------------------------------
def test_set_release_gating(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wts, tips = {}, {}
    for lid, path in (("api", "src/api/a.py"), ("ui", "src/ui/u.py"), ("docs", "docs/d3.md")):
        wts[lid], tips[lid] = start_lane(demo, tmp_path, lid, {path: lid + "\n"})
        ready_lane(guard, demo, lid, tips[lid])
    integrate(demo, LANES["api"], LANES["ui"], LANES["docs"])
    demo.git("merge", "-q", "--ff-only", INTEGRATION)  # main holds every lane
    upd_ok(guard, demo, "api", "integrated", "--head", tips["api"], "--integration", INTEGRATION)
    upd_ok(guard, demo, "docs", "integrated", "--head", tips["docs"])

    def refused(*extra, want):
        snapshot, audits = store_files(demo), len(audit_lines(demo))
        rc, v = jrelease(guard, demo, *extra)
        assert rc == 16 and v["decision"] == "deny" and v["code"] == "BLOCKED" and set(v) == COMMON_KEYS | {"blocked"} and v["blocked"] == want, (rc, v)
        assert store_files(demo) == snapshot and len(audit_lines(demo)) == audits  # nothing is written
        return v
    v = refused(want=[{"lane": "ui", "reason": "NOT_INTEGRATED"}])  # ui is still ready
    assert v["message"] == "MAGOS: set-release refused: lane ui is ready, not integrated"
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-release", "--set", "demo"])
    assert zh.rc == 16 and zh.out.rstrip("\n") == "MAGOS：拒绝 set-release：lane ui 的状态是 ready，不是 integrated"
    upd_ok(guard, demo, "ui", "integrated", "--head", tips["ui"])
    demo.commit("docs/more.md", "m\n", cwd=wts["docs"], msg="more")  # a commit that main does not have
    v = refused(want=[{"lane": "docs", "reason": "UNMERGED_WORK"}])
    assert "the branch agent/demo/docs of lane docs has unmerged work" in v["message"]
    demo.git("reset", "-q", "--hard", tips["docs"], cwd=wts["docs"])
    stray = demo.write("src/api/stray.txt", "u\n", base=wts["api"])
    v = refused(want=[{"lane": "api", "reason": "DIRTY_WORKTREE"}])
    assert "the worktree of lane api has uncommitted changes" in v["message"]
    stray.unlink()
    claims = store_dir(demo) / "claims" / "agent" / "demo"
    for name, lane_id in (("api", "api"), ("integration", "integration")):
        good = (claims / (name + ".claim")).read_bytes()
        for bad in (good.replace(b"v=1\n", b"v=2\n"), b"state=active\nnot a claim\n"):  # a newer format, and one nobody can read
            (claims / (name + ".claim")).write_bytes(bad)
            v = refused(want=[{"lane": lane_id, "reason": "CLAIM_UNUSABLE"}])
            assert "cannot be read or comes from a newer MAGOS" in v["message"]
        (claims / (name + ".claim")).write_bytes(good)
    demo.commit("docs/more.md", "m\n", cwd=wts["docs"], msg="more")  # every blocking lane is named, with every reason
    stray = demo.write("src/api/stray.txt", "u\n", base=wts["api"])
    upd_ok(guard, demo, "ui", "blocked")
    refused(want=[{"lane": "api", "reason": "DIRTY_WORKTREE"}, {"lane": "ui", "reason": "NOT_INTEGRATED"}, {"lane": "docs", "reason": "UNMERGED_WORK"}])
    stray.unlink()
    demo.git("reset", "-q", "--hard", tips["docs"], cwd=wts["docs"])
    edit_record(demo, lambda rec: lane_of(rec, "ui").update(state="integrated"))
    # released: one branch deleted, one worktree removed, the others as they are
    demo.git("worktree", "remove", "--force", str(wts["ui"]))
    demo.git("branch", "-q", "-D", LANES["ui"])
    demo.git("worktree", "remove", str(wts["docs"]))
    audit_before = len(audit_lines(demo))
    rc, v = jrelease(guard, demo, "--reason", "done")
    assert rc == 0 and set(v) == RELEASE_KEYS and v["code"] == "OK" and v["abandoned"] is False and v["warnings"] == []
    assert v["released"] == [LANES["api"], LANES["ui"], LANES["docs"], INTEGRATION] and v["message"] == "MAGOS: released set 'demo' and its 4 claims."
    assert not list((store_dir(demo) / "claims").rglob("*.claim")) and not record_file(demo).exists() and not list(store_dir(demo).rglob("*.tmp"))
    lines = audit_lines(demo)
    assert len(lines) == audit_before + 1 and lines[-1]["op"] == "set-release" and lines[-1]["reason"] == "done" and lines[-1]["abandon"] is False and lines[-1]["set"] == "demo"
    assert lines[-1]["lanes"] == ["api", "ui", "docs"] and lines[-1]["claims"] == v["released"] and lines[-1]["host"] == "cli"
    assert LANES["api"] in branches(demo) and INTEGRATION in branches(demo) and wts["api"].is_dir()  # no branch and no worktree is removed
    assert guard(demo, "list").out.strip() == "(no claims)" and guard(demo, "doctor").rc == 0
    rc, v = jrelease(guard, demo)
    assert rc == 21 and v["code"] == "SET_UNKNOWN"
    # a claim of the lane's branch that belongs to no set is left in place with a warning, and the rest is released
    r2 = make_repo(tmp_path, "release2")
    plan_ok(guard, r2, write_spec(tmp_path, demo_spec(r2, tmp_path), "release2.json"))
    ui = store_dir(r2) / "claims" / "agent" / "demo" / "ui.claim"
    ui.write_bytes(b"".join(x for x in ui.read_bytes().splitlines(True) if not x.startswith((b"set=", b"lane="))))
    rc, v = jrelease(guard, r2, "--abandon")
    assert rc == 0 and v["released"] == [LANES["api"], LANES["docs"], INTEGRATION] and [w["code"] for w in v["warnings"]] == ["CLAIM_NOT_REMOVED"]
    assert "agent/demo/ui" in v["warnings"][0]["text"] and v["message"].splitlines()[-1].startswith("(CLAIM_NOT_REMOVED) ") and ui.is_file() and not record_file(r2).exists()
    assert [x["branch"] for x in json.loads(guard(r2, "--json", "list").out)] == [LANES["ui"]]


def test_set_release_abandon(tmp_path, guard):
    def fresh(name):
        r = make_repo(tmp_path, name)
        spec = demo_spec(r, tmp_path)
        for lane_ in spec["lanes"]:
            lane_["worktree"] = wt_path(tmp_path, lane_["id"], prefix=name)  # a worktree of its own for every repository
        plan_ok(guard, r, write_spec(tmp_path, spec, name + ".json"))
        return r
    r = fresh("ab1")  # planned, active and blocked lanes whose branches hold nothing the target lacks
    r.git("branch", LANES["ui"], "main")
    upd_ok(guard, r, "ui", "active")
    upd_ok(guard, r, "docs", "blocked", "--note", "waiting")
    rc, v = jrelease(guard, r)
    assert rc == 16 and v["blocked"] == [{"lane": x, "reason": "NOT_INTEGRATED"} for x in ("api", "ui", "docs")]  # without --abandon
    before = store_files(r)
    rc, v = jrelease(guard, r, "--abandon", "--reason", "plan dropped")
    assert rc == 0 and v["abandoned"] is True and len(v["released"]) == 4 and not record_file(r).exists() and not list((store_dir(r) / "claims").rglob("*.claim"))
    assert audit_lines(r)[-1]["abandon"] is True and audit_lines(r)[-1]["reason"] == "plan dropped" and before != store_files(r)
    r = fresh("ab2")  # a lane branch with a commit that the target lacks
    branch_at(r, LANES["api"], {"src/api/n.py": "n\n"})
    before = store_files(r)
    rc, v = jrelease(guard, r, "--abandon")
    assert rc == 16 and v["blocked"] == [{"lane": "api", "reason": "UNMERGED_WORK"}] and store_files(r) == before
    r = fresh("ab3")  # a dirty worktree at the registered path
    wt = wt_dir(tmp_path, "api", prefix="ab3")
    r.git("worktree", "add", "-q", "-b", LANES["api"], str(wt), "main")
    r.write("src/api/stray.txt", "u\n", base=wt)
    before = store_files(r)
    rc, v = jrelease(guard, r, "--abandon")
    assert rc == 16 and v["blocked"] == [{"lane": "api", "reason": "DIRTY_WORKTREE"}] and store_files(r) == before
    (wt / "src" / "api" / "stray.txt").unlink()
    assert jrelease(guard, r, "--abandon")[0] == 0  # clean: the plan is dropped, the worktree and the branch stay
    assert wt.is_dir() and LANES["api"] in branches(r)
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
    results, seen = race([update_args("api", "active", 1), update_args("ui", "active", 1)])  # different lanes, the same revision
    assert sorted(rc for rc, _, _ in results) == [0, 19], results
    loser = json.loads(next(o for rc, o, _ in results if rc == 19))
    assert (loser["kind"], loser["expected"], loser["current"]) == ("revision", 1, 2) and "is at revision 2, not 1" in loser["message"]
    rec = record(demo)
    assert rec["revision"] == 2 and sorted(x["state"] for x in rec["lanes"]) == ["active", "planned", "planned"] and set(seen) <= {1, 2}
    results, _ = race([update_args("docs", "active", 2), update_args("docs", "blocked", 2)])  # the same lane
    assert sorted(rc for rc, _, _ in results) == [0, 19], results
    rec = record(demo)
    winner = next(json.loads(o) for rc, o, _ in results if rc == 0)
    assert rec["revision"] == 3 and lane_of(rec, "docs")["state"] == winner["state"] and not list(store_dir(demo).rglob("*.tmp"))
    assert len([x for x in audit_lines(demo) if x["op"] == "set-update"]) == 2
    # a failure of the replace of the record: the record is as it was, and no temporary file stays
    before, audits = record_file(demo).read_bytes(), len(audit_lines(demo))
    real = G._replace

    def failing(tmp, path, tries=40):
        if str(path).endswith("demo.json"):
            raise OSError("disk full")
        return real(tmp, path, tries)
    monkeypatch.setattr(G, "_replace", failing)
    r = guard(demo, "--json", *update_args("api", "blocked", 3))
    v = json.loads(r.out)
    assert r.rc == 11 and v["unknowns"][0]["code"] == "INTERNAL_ERROR" and "disk full" in v["message"] and "MAGOS guard internal error: OSError: disk full" in r.err
    assert record_file(demo).read_bytes() == before and not list(store_dir(demo).rglob("*.tmp")) and len(audit_lines(demo)) == audits


# ---- TC-279 .. TC-285: set names, the record format, the spec ----------------------------------------------------------------
def set_commands(name, spec_file):
    """The set subcommands as argument lists that name the set `name` (each is refused with exit 21 when the set does not exist)."""
    return {"set-plan": ["set-plan", "--set=" + name, "--target", "main", "--spec", str(spec_file), "--amend", "--expect-revision", "1"],
            "set-show": ["set-show", "--set=" + name], "set-show-drift": ["set-show", "--set=" + name, "--drift"],
            "set-update": ["set-update", "--set=" + name, "--expect-revision", "1", "--lane", "api", "--state", "active"],
            "set-release": ["set-release", "--set=" + name], "set-release-abandon": ["set-release", "--set=" + name, "--abandon"]}


def test_unknown_set_and_invalid_set_names(demo, guard, tmp_path, monkeypatch):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    nowhere = tmp_path / "nowhere"  # a directory that is no git repository is exit 2, whatever the subcommand
    nowhere.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for sub_name, args in set_commands("demo", f).items():
        r = run(["--repo", str(nowhere), *args])
        assert r.rc == 2 and r.out == "" and "not a git repository" in r.err, (sub_name, r)
    ghost = write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"], set_name="ghost")]), "ghost.json")  # valid for the set it names
    for sub_name, args in set_commands("ghost", ghost).items():
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
        device = bad in ("con", "nul", "lpt1", "com9")
        for sub_name, args in set_commands(bad, f).items():
            r = guard(demo, "--json", *args)
            v = json.loads(r.out)
            assert r.rc == 24 and v["code"] == "INVALID_SPEC" and [(e["field"], e["code"]) for e in v["errors"]] == [("--set", "FORMAT")], (bad, sub_name, v)
            want = G.T("en", "set_err_set_device", s=bad) if device else G.T("en", "set_err_set_name", s=bad, rule=G.SLUG_RULE)
            frame = "set_invalid" if sub_name == "set-plan" else "set_invalid_args"  # set-plan refuses a plan, the others refuse their arguments
            assert v["errors"][0]["text"] == want and v["message"] == G.T("en", frame, errors="  [FORMAT] --set: " + want), (bad, sub_name, v)
            zh = run(["--repo", str(demo.path), *args])  # the default language is zh
            assert zh.rc == 24 and zh.out.rstrip("\n") == G.T("zh", frame, errors="  [FORMAT] --set: " + (
                G.T("zh", "set_err_set_device", s=bad) if device else G.T("zh", "set_err_set_name", s=bad, rule=G.SLUG_RULE))), (bad, sub_name, zh)
    rc, v = jplan(guard, demo, f, "--dry-run", name="con")
    assert rc == 24 and "Windows device name" in v["errors"][0]["text"]
    long_set = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"], set_name="a" * 24)])  # the branches and worktrees of a spec name its set
    rc, v = jplan(guard, demo, write_spec(tmp_path, long_set, "long.json"), "--dry-run", name="a" * 24)
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
             "update": update_args("api", "active", 1), "release": ["set-release", "--set", "demo"], "release-abandon": ["set-release", "--set", "demo", "--abandon"]}
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
              lambda r: r.update(target=1), lambda r: r.update(revision=True), lambda r: r.update(notes=[1]),
              lambda r: r.update(requirements="x"), lambda r: r.update(requirements=[{"id": 1, "text": "t"}]), lambda r: r.pop("requirements"),
              lambda r: r["lanes"][0].update(serves="x"), lambda r: r["lanes"][0].update(serves=[1]), lambda r: r["lanes"][0].update(outcome=5),
              lambda r: r["lanes"][0].pop("serves"), lambda r: r["lanes"][0].update(changes=5), lambda r: r["lanes"][0].update(changes={"commits": "x"}),
              lambda r: r["lanes"][0].update(changes={"commits": 1, "subjects": [1], "more": 0, "files": 0, "insertions": 0, "deletions": 0, "paths": [], "paths_more": 0})]
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
    def three():
        return [lane(tmp_path, "api", ["src/api/"]), lane(tmp_path, "ui", ["src/ui/"]), lane(tmp_path, "docs", ["docs/"])]

    def spec(lanes=None, **top):
        s = custom_spec(demo, tmp_path, three() if lanes is None else lanes)
        s.update(top)
        return s

    def lanes_n(n, **over):
        return [lane(tmp_path, "topic-%02d" % i, ["d%d/" % i], **over) for i in range(n)]

    def ok(s, name="ok.json"):
        rc, v = dry(guard, demo, tmp_path, s, name)
        assert rc == 0, v

    def bad(s, field, code=None, name="bad.json"):
        rc, v = dry(guard, demo, tmp_path, s, name)
        assert rc == 24 and v["code"] == "INVALID_SPEC" and field in {e["field"] for e in v["errors"]}, (field, v)
        assert code is None or (field, code) in errors_of(v), (field, code, v)
        assert not store_dir(demo).exists()  # nothing is written
    ok(spec(lanes_n(12)))
    bad(spec(lanes_n(13)), "lanes", "RANGE")
    twelve_ids = ["R%d" % i for i in range(12)]
    twelve = [{"id": i, "text": "requirement " + i} for i in twelve_ids]
    ok(spec([lane(tmp_path, "api", ["src/api/"], serves=twelve_ids)], requirements=twelve))  # 12 requirements and 12 ids in serves
    bad(spec([lane(tmp_path, "api", ["src/api/"], serves=twelve_ids)], requirements=twelve + [{"id": "R12", "text": "one too many"}]), "requirements[12]", "RANGE")
    bad(spec([lane(tmp_path, "api", ["src/api/"]), lane(tmp_path, "ui", ["src/ui/"], serves=twelve_ids + ["R0"])], requirements=twelve), "lanes[1].serves", "RANGE")
    ok(spec(requirements=[{"id": "RRRRRRRR", "text": "an id of 8 characters"}], lanes=[lane(tmp_path, "api", ["src/api/"], serves=["RRRRRRRR"])]))
    bad(spec(requirements=[{"id": "RRRRRRRRR", "text": "an id of 9 characters"}], lanes=[lane(tmp_path, "api", ["src/api/"], serves=["RRRRRRRRR"])]), "requirements[0].id", "FORMAT")
    ok(spec(requirements=[{"id": "R1", "text": "t" * 200}]))
    bad(spec(requirements=[{"id": "R1", "text": "t" * 201}]), "requirements[0].text", "RANGE")
    ok(spec([lane(tmp_path, "topic", ["p/f%d.py" % j for j in range(200)])]))
    bad(spec([lane(tmp_path, "topic", ["p/f%d.py" % j for j in range(201)])]), "lanes[0].paths", "TOO_MANY")

    def entry(n):  # n characters in segments that every file system accepts
        return "d0/" + "/".join(["x" * 200] * 5) + "/" + "y" * (n - 1008)
    ok(spec([lane(tmp_path, "topic", [entry(1024)])]))
    bad(spec([lane(tmp_path, "topic", [entry(1025)])]), "lanes[0].paths[0]", "TOO_LONG")
    ok(spec(sheet="a" * 8186 + "\n\t\n\tx\n"))  # 8,192 characters, with a newline and a tab
    bad(spec(sheet="a" * 8193), "sheet", "RANGE")
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
    s["lanes"][1]["outcome"] = "o" * 300
    s["lanes"][2]["acceptance"] = ""  # an empty acceptance, like an omitted one, is no error
    ok(s)
    for key, big, code in (("title", "t" * 81, "RANGE"), ("acceptance", "a" * 301, "RANGE"), ("outcome", "o" * 301, "RANGE"), ("outcome", "", "RANGE"), ("outcome", 5, "TYPE"),
                           ("acceptance", 5, "TYPE")):
        s = spec()
        s["lanes"][1][key] = big
        bad(s, "lanes[1].%s" % key, code)
    s = spec()
    s["lanes"][0]["paths"] = []
    bad(s, "lanes[0].paths", "EMPTY")
    for lid, good in (("i" * 24, True), ("i" * 25, False), ("a b", False), ("a.b", False), ("a-b", True), ("a_b", False), ("integration", False), ("INTEGRATION", False),
                      ("Integration", False), ("L1", False)):
        s = spec()
        s["lanes"][0] = lane(tmp_path, lid, ["src/api/"])
        if good:
            ok(s)
        else:
            bad(s, "lanes[0].id")
    s = spec()
    s["lanes"][1] = lane(tmp_path, "api", ["src/ui/"])  # the same id twice
    bad(s, "lanes[1].id", "DUPLICATE")
    owner = [lane(tmp_path, "api", ["src/"])]
    ok(spec(owner, shared=[{"path": "src/f%d.py" % j, "owner": "api"} for j in range(64)]))
    bad(spec(owner, shared=[{"path": "src/f%d.py" % j, "owner": "api"} for j in range(65)]), "shared", "RANGE")
    many = lanes_n(12)
    many[11]["depends_on"] = [x["id"] for x in many[:11]]
    ok(spec(many))
    many[11]["depends_on"] = [x["id"] for x in many[:11]] + [many[0]["id"]]
    bad(spec(many), "lanes[11].depends_on", "RANGE")
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
    # a sheet of 8,192 characters is stored, and set-show returns it byte for byte
    sheet = ("# the sheet\n" + "\t| a | b |\n" * 800)[:8191] + "x"
    assert len(sheet) == 8192
    other = make_repo(tmp_path, "sheetrepo")
    plan_ok(guard, other, write_spec(tmp_path, custom_spec(other, tmp_path, three(), sheet=sheet), "sheet.json"))
    assert jshow(guard, other)["record"]["sheet"] == sheet and record(other)["sheet"] == sheet


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
    s = derived()
    s["requirements"][0]["nope"] = 1
    check(s, "requirements[0].nope", "UNKNOWN_KEY")
    check(derived(requirements=KeyError), "requirements", "MISSING")
    check(derived(requirements="x"), "requirements", "TYPE")
    check(derived(requirements=["R1"]), "requirements[0]", "TYPE")
    s = derived()
    del s["lanes"][0]["serves"]
    check(s, "lanes[0].serves", "MISSING")
    s = derived()
    del s["lanes"][1]["outcome"]
    check(s, "lanes[1].outcome", "MISSING")
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
                                      ("branch", "a\x01b", "lanes[0].branch", "BRANCH_FORM"), ("branch", 5, "lanes[0].branch", "TYPE"), ("depends_on", "api", "lanes[0].depends_on", "TYPE"),
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
    check(text.replace('{"id": "api",', '{"id": "api", "id": "api",', 1), "lanes[0].id", "DUPLICATE")
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
    # the texts of the naming and coverage codes are in the language of the call, every other text is English in both
    mixed = derived(extra=1)
    mixed["lanes"][0]["branch"] = "feature/api"
    mixed["lanes"][1]["serves"] = ["R9"]
    for lang, want_branch, want_serves in (("zh", "分支必须是 agent/demo/api", "不是本规划 requirements 中的编号"), ("en", "the branch of lane api must be agent/demo/api", "is no requirement id of this spec")):
        r = run(["--repo", str(demo.path), "--lang", lang, "--json", *sp_args(write_spec(tmp_path, mixed, "mixed.json"), "demo", "main", "--dry-run")])
        texts = {(e["field"], e["code"]): e["text"] for e in json.loads(r.out)["errors"]}
        assert want_branch in texts[("lanes[0].branch", "BRANCH_FORM")] and want_serves in texts[("lanes[1].serves[0]", "UNKNOWN_REQUIREMENT")], (lang, texts)
        assert texts[("extra", "UNKNOWN_KEY")] == "not a key of the spec"  # English in both languages
        assert all(want in json.loads(r.out)["message"] for want in (texts[("lanes[0].branch", "BRANCH_FORM")],))  # the text of the message is the text of the entry


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
        return custom_spec(demo, tmp_path, [lane(tmp_path, "api", list(l1)), lane(tmp_path, "ui", ["other/"])], shared=shared)
    inside = [{"path": "src/dir/a.py", "owner": "api"}, {"path": "gl/a.py", "owner": "api"}, {"path": "lit/file.txt", "owner": "api"}]
    v = plan_ok(guard, demo, write_spec(tmp_path, spec(inside)))
    assert record(demo)["shared"] == inside  # inside by a directory entry, by a glob entry and by the literal file
    cases = [([{"path": "other/x.py", "owner": "api"}], "shared[0].path", "NOT_IN_OWNER"), ([{"path": "elsewhere/x.py", "owner": "api"}], "shared[0].path", "NOT_IN_OWNER"),
             ([{"path": "src/dir/a.py", "owner": "L9"}], "shared[0].owner", "UNKNOWN_LANE"), ([{"path": "src/dir/a.py", "owner": "API"}], "shared[0].owner", "UNKNOWN_LANE"),
             ([{"path": "src/dir/*.py", "owner": "api"}], "shared[0].path", "BAD_GLOB"), ([{"path": "src/dir/?.py", "owner": "api"}], "shared[0].path", "BAD_GLOB"),
             ([{"path": "src/dir/", "owner": "api"}], "shared[0].path", "BAD_GLOB"),
             ([{"path": "src/dir/a.py", "owner": "api"}, {"path": "SRC/DIR/A.PY", "owner": "api"}], "shared[1].path", "DUPLICATE"),
             ([{"path": "/etc/x", "owner": "api"}], "shared[0].path", "ABSOLUTE"), ([{"path": "src/../x", "owner": "api"}], "shared[0].path", "DOTDOT"),
             ([{"path": "", "owner": "api"}], "shared[0].path", None)]
    other = make_repo(tmp_path, "other")
    for shared, field, code in cases:
        s = spec(shared)
        s["base"] = other.git("rev-parse", "main")
        rc, v = dry(guard, other, tmp_path, s, "sh.json")
        assert rc == 24 and field in {e["field"] for e in v["errors"]} and (code is None or (field, code) in errors_of(v)), (shared, v)
        assert not store_dir(other).exists()
    s = spec([{"path": "src/c", "owner": "api"}], l1=("src/c/x.py",))  # the file src/c is not inside the manifest src/c/x.py
    s["base"] = other.git("rev-parse", "main")
    rc, v = dry(guard, other, tmp_path, s, "sh.json")
    assert rc == 24 and ("shared[0].path", "NOT_IN_OWNER") in errors_of(v)
    s = spec([{"path": "src/c/x.py", "owner": "api"}], l1=("src/c/x.py",))
    s["base"] = other.git("rev-parse", "main")
    assert dry(guard, other, tmp_path, s, "sh.json")[0] == 0


def test_lane_manifest_entries(demo, guard, tmp_path):
    def one(paths, name="m.json"):
        return dry(guard, demo, tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "api", paths)]), name)
    cases = [(["/abs/x"], "ABSOLUTE"), (["../x"], "DOTDOT"), (["a/../b"], "DOTDOT"), ([".git"], "GITDIR"), ([".git/config"], "GITDIR"), ([":(glob)x"], "MAGIC"), (["!x"], "MAGIC"),
             (["**"], "UNIVERSAL"), (["*/*"], "UNIVERSAL"), ([""], "EMPTY"), (["d/" + "/".join(["x" * 200] * 6)], "TOO_LONG")]
    for paths, code in cases:
        rc, v = one(paths)
        assert rc == 24 and ("lanes[0].paths[0]", code) in errors_of(v), (paths, v)
    rc, v = one(["ok/", "../bad", "", "/abs"])
    assert rc == 24 and {("lanes[0].paths[1]", "DOTDOT"), ("lanes[0].paths[2]", "EMPTY"), ("lanes[0].paths[3]", "ABSOLUTE")} <= errors_of(v)  # every bad entry is named by its index
    nfd = unicodedata.normalize("NFD", "café/x")
    # entries equal after normalisation (separators, case, a trailing / and the blanks at the ends folded): every later one is DUPLICATE on its own field
    rc, v = one(["a\\b", "a/b", "Src/A", "src/a", "# not a comment", nfd, "  padded/dir/  ", "padded/dir"])
    assert rc == 24 and errors_of(v) == {("lanes[0].paths[1]", "DUPLICATE"), ("lanes[0].paths[3]", "DUPLICATE"), ("lanes[0].paths[7]", "DUPLICATE")}, v
    assert [e["text"] for e in v["errors"]] == ["the entry equals lanes[0].paths[%d] after normalisation" % k for k in (0, 2, 6)]
    paths = ["a\\b", "Src/A", "# not a comment", nfd, "  padded/dir/  "]
    v = plan_ok(guard, demo, write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "api", paths)])))
    stored = record(demo)["lanes"][0]["paths"]
    assert stored == v["lanes"][0]["entries"]
    # one stored entry per entry of the spec, in its order: blanks are stripped; a `#` starts a path, no comment
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
    scenarios["previewed"] = (r, sp_args(f, "demo", "main", "--dry-run"), 0, None, ("的预览通过", "the preview of set 'demo' passed"))
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
    r.git("branch", "agent/demo", "main")  # a ref that would be both a file and a directory with the branch of the lane api
    scenarios["name-clash"] = (r, sp_args(f), 12, None, ("set 规划无效", "the set plan is invalid"))
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
    r.git("worktree", "add", "-q", "-b", "agent/demo/ui", str(wt_dir(tmp_path, "ui")), "main")
    r.commit("src/ui/y.py", "y\n", cwd=wt_dir(tmp_path, "ui"), msg="ui")
    s = drop_lane(demo_spec(r, tmp_path), "ui")
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
    scenarios["show-drift"] = (r, ["set-show", "--set", "demo", "--drift"], 0, None, ("合并顺序：api -> ui -> docs", "merge order: api -> ui -> docs"))
    ok_keys["show-drift"] = SHOW_KEYS
    scenarios["show-invalid"] = (r, ["set-show", "--set", "Demo"], 24, None, ("参数无效，未做任何修改", "invalid arguments, nothing was changed"))
    r, _ = fresh("s_show_none")
    scenarios["show-unknown"] = (r, ["set-show", "--set", "demo"], 21, None, ("没有名为", "there is no set named"))
    scenarios["show-newer"] = (newer(registered("s_show_newer")[0]), ["set-show", "--set", "demo"], 23, None, ("更新版本", "newer MAGOS"))
    scenarios["show-unreadable"] = (unreadable(registered("s_show_bad")[0]), ["set-show", "--set", "demo"], 11, None, ("无法读取", "cannot be read"))
    made = [registered("s_upd%d" % i)[0] for i in range(6)]
    ok_keys["update"] = UPDATE_KEYS
    scenarios["update"] = (made, [update_args("api", "active", 1)] * 6, 0, None, ("的 lane api 现在是 active，修订 2", "lane api of set 'demo' is now active, revision 2"))
    r, _ = registered("s_upd_blocked")
    assert guard(r, *update_args("api", "active", 1)).rc == 0
    scenarios["update-blocked"] = (r, update_args("api", "ready", 2, "--head", r.git("rev-parse", "main")), 16, None, ("拒绝 set-update", "set-update refused"))
    r, _ = registered("s_upd_outside")
    tip = fast_commit(r, LANES["api"], {"src/ui/x.py": "x\n"})
    assert guard(r, *update_args("api", "active", 1)).rc == 0
    scenarios["update-outside"] = (r, update_args("api", "ready", 2, "--head", tip), 22, None, ("拒绝把 lane api 标记为 ready", "refused to mark lane api ready"))
    r, _ = registered("s_upd_stale")
    scenarios["update-stale"] = (r, update_args("api", "active", 5), 19, None, ("计划已过期", "the plan is stale"))
    r, _ = fresh("s_upd_none")
    scenarios["update-unknown"] = (r, update_args("api", "active", 1), 21, None, ("没有名为", "there is no set named"))
    r, _ = registered("s_upd_invalid")
    scenarios["update-invalid"] = (r, update_args("api", "active", 1, "--note", "x" * 201), 24, None, ("参数无效，未做任何修改", "invalid arguments, nothing was changed"))
    scenarios["update-newer"] = (newer(registered("s_upd_newer")[0]), update_args("api", "active", 1), 23, None, ("更新版本", "newer MAGOS"))
    scenarios["update-unreadable"] = (unreadable(registered("s_upd_bad")[0]), update_args("api", "active", 1), 11, None, ("无法读取", "cannot be read"))
    r, _ = registered("s_upd_lock")
    scenarios["update-lock"] = (r, update_args("api", "active", 1), 13, lock_on(r), ("清单锁", "claim lock"))
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
    scenarios["release-invalid"] = (r, ["set-release", "--set", "demo", "--reason", "r" * 201], 24, None, ("参数无效，未做任何修改", "invalid arguments, nothing was changed"))
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
    # a registration reports the requirements with their lanes and every lane with its serves, outcome and acceptance
    r, f = fresh("s_rows")
    v = plan_ok(guard, r, f)
    assert [(x["id"], x["lanes"]) for x in v["requirements"]] == [("R1", ["api"]), ("R2", ["ui"]), ("R3", ["docs"])] and all(list(x) == LANE_ROW_KEYS for x in v["lanes"])
    assert [(x["serves"], x["outcome"], x["acceptance"]) for x in v["lanes"]] == [(["R1"], "the outcome of api", ""), (["R2"], "the outcome of ui", "it works"), (["R3"], "the outcome of docs", "it works")]
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
        return write_spec(tmp_path, custom_spec(repo, tmp_path, [lane(tmp_path, "mod-%02d" % i, ["d%d/" % i]) for i in range(1, 13)]), name + ".json")
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
    assert [x["id"] for x in v["lanes"]] == ["mod-03", "mod-09"]  # only the offending lanes are named
    assert {x["conflicts"][0]["branch"] for x in v["lanes"]} == {"agent/x3", "agent/x9"} and v["lanes"][0]["conflicts"][0]["evidence"][0]["kind"] == "declared"
    assert not (store_dir(r) / "sets").exists()
    # only unknowns: lanes 2 and 5 (a verdict the judge gives for them alone) are named, with exit 11
    r2 = make_repo(tmp_path, "snap2")
    f2 = twelve(r2, "snap2")
    real_judge = G.judge

    def judge(snap, claims, bad, name, entries, override):
        v = real_judge(snap, claims, bad, name, entries, override)
        if name in ("agent/demo/mod-02", "agent/demo/mod-05"):
            v = dict(v, decision="deny", code="UNKNOWN", unknowns=[{"code": "STATUS_FAILED", "text": "%s: status failed" % name}])
        return v
    monkeypatch.setattr(G, "judge", judge)
    rc, v = jplan(guard, r2, f2)
    assert rc == 11 and v["code"] == "UNKNOWN" and [x["id"] for x in v["lanes"]] == ["mod-02", "mod-05"] and v["lanes"][0]["unknowns"][0]["code"] == "STATUS_FAILED"
    assert store_files(r2) in (None, {})
    monkeypatch.setattr(G, "judge", real_judge)
    # an amend: the lanes of the set that already hold work are members of the set, never compared with the lanes
    plan_ok(guard, r2, f2)
    for i in (1, 2):
        wt = wt_dir(tmp_path, "mod-%02d" % i)
        r2.git("worktree", "add", "-q", "-b", "agent/demo/mod-%02d" % i, str(wt), "main")
        r2.commit("d%d/x.py" % i, "x\n", cwd=wt, msg="mod-%02d" % i)
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
    assert "lane ui" in v["message"] and "agent/demo/ui" in v["message"] and "agent/demo/integration" in v["message"]
    r, f = case("e2")  # the target's name as a lane branch is no branch of the set: the form rule refuses it
    s = demo_spec(r, tmp_path)
    s["lanes"][0]["branch"] = "main"
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e2b.json"))
    assert rc == 24 and ("lanes[0].branch", "BRANCH_FORM") in errors_of(v)
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
    r.git("branch", "agent/demo/api", "main")  # api survives with its branch
    s = json.loads(f.read_text(encoding="utf-8"))
    s["lanes"].append(lane(tmp_path, "extra", ["extra/"]))
    assert guard(r, "plan", "--branch", "agent/demo/extra", "--paths", "elsewhere2/").rc == 0
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "1")
    assert rc == 14 and [e["field"] for e in v["errors"]] == ["lanes[3].branch"]
    assert guard(r, "release", "--branch", "agent/demo/extra").rc == 0
    r.git("branch", "agent/demo/extra", "main")
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "1")
    assert rc == 15 and [e["field"] for e in v["errors"]] == ["lanes[3].branch"]
    r.git("branch", "-D", "agent/demo/extra")
    assert plan_ok(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "1")["revision"] == 2  # api's branch exists with the set's claim: fine
    claim = store_dir(r) / "claims" / "agent" / "demo" / "api.claim"  # a claim of a newer format on a lane of the record is the claim gate's, not a foreign claim
    text = claim.read_text(encoding="utf-8")
    claim.write_text(text.replace("v=1", "v=2", 1), encoding="utf-8")
    rc, v = jplan(guard, r, write_spec(tmp_path, s, "e4b.json"), "--amend", "--expect-revision", "2")
    assert rc == 11 and v["code"] == "UNKNOWN" and v["lanes"][0]["unknowns"][0]["code"] == "CLAIM_NEWER_FORMAT" and "v=2" in claim.read_text(encoding="utf-8")
    claim.write_text(text, encoding="utf-8")
    # the first failing kind decides the exit code and every offending lane of that kind is named
    r, f = case("e5")
    r.git("branch", "agent/demo/api/x", "main")  # a ref that would be a directory of the branch of api
    r.git("branch", "agent/demo/ui", "main")
    assert guard(r, "plan", "--branch", "agent/demo/docs", "--paths", "elsewhere/").rc == 0
    rc, v = jplan(guard, r, f)
    assert rc == 12 and [e["field"] for e in v["errors"]] == ["lanes[0].branch"]  # a clash with a ref: 12 before 14 and 15
    r.git("branch", "-D", "agent/demo/api/x")
    rc, v = jplan(guard, r, f)
    assert rc == 14 and {e["field"] for e in v["errors"]} == {"lanes[2].branch"}  # a foreign claim: 14 before 15 (ui's branch exists too)
    r.git("branch", "agent/demo/api", "main")
    assert guard(r, "release", "--branch", "agent/demo/docs").rc == 0
    rc, v = jplan(guard, r, f)
    assert rc == 15 and {e["field"] for e in v["errors"]} == {"lanes[0].branch", "lanes[1].branch"}  # every offending lane is named


def test_amend_moves_the_base(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    old = demo.git("rev-parse", "main")
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    w1, w2 = wt_dir(tmp_path, "api"), wt_dir(tmp_path, "ui")
    demo.git("worktree", "add", "-q", "-b", "agent/demo/api", str(w1), "main")
    demo.commit("src/api/x.py", "x\n", cwd=w1, msg="api")
    demo.git("worktree", "add", "-q", "-b", "agent/demo/ui", str(w2), "main")
    head = demo.git("rev-parse", "agent/demo/api")
    upd_ok(guard, demo, "api", "active")
    upd_ok(guard, demo, "api", "ready", "--head", head, "--note", "done")
    upd_ok(guard, demo, "ui", "active")
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
    assert (lane_of(rec, "api")["state"], lane_of(rec, "api")["head"], lane_of(rec, "api")["note"]) == ("ready", head, "done") and lane_of(rec, "ui")["state"] == "active"
    for branch in ("agent/demo/api", "agent/demo/ui", "agent/demo/docs", "agent/demo/integration"):
        assert "base=" + new in claim_lines(demo, branch), branch  # the claim of every lane follows the plan
    assert demo.git("rev-parse", "agent/demo/api~1") == old  # the lane stays cut from the old base: nothing refuses it
    shrink = demo_spec(demo, tmp_path, base=new)
    shrink["lanes"][0]["paths"] = ["tests/api/", "package-lock.json"]
    shrink["shared"] = [{"path": "package-lock.json", "owner": "api"}]
    rc, v = jplan(guard, demo, write_spec(tmp_path, shrink, "shrink.json"), "--amend", "--expect-revision", str(rev + 1))
    assert rc == 16 and v["blocked"] == [{"lane": "api", "reason": "SHRINK", "files": ["src/api/x.py"]}] and record(demo)["revision"] == rev + 1


def test_the_record_is_written_whole_and_unknown_keys_survive(demo, guard, tmp_path, monkeypatch):
    freeze_clock(monkeypatch)
    sheet = "line one\n\tline two -> x ∣ café 日本\n- [ ] git switch -c y\n"
    spec = demo_spec(demo, tmp_path, sheet=sheet)
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    path = store_dir(demo) / "sets" / "demo.json"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"}\n") and json.loads(raw.decode("utf-8"))["sheet"] == sheet  # UTF-8, no BOM, LF, verbatim
    rec = edit_record(demo, lambda rec: (rec.update(x_note={"a": [1, 2]}), lane_of(rec, "ui").update(x_lane="keep me")))
    amend = demo_spec(demo, tmp_path, sheet=sheet)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "1")
    after = record(demo)
    assert after["x_note"] == {"a": [1, 2]} and lane_of(after, "ui")["x_lane"] == "keep me" and after["revision"] == 2 and after["sheet"] == sheet
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
    upd_ok(guard, demo, "api", "active", "--note", "n", rev=2)
    after, raw = record(demo), path.read_bytes()
    assert after["x_note"] == {"a": [1, 2]} and lane_of(after, "ui")["x_lane"] == "keep me" and after["revision"] == 3 and after["sheet"] == sheet
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
    drop_lane(amend, "ui")
    af = write_spec(tmp_path, amend, "amend.json")
    first = audit_lines(demo)
    assert len(first) == 1
    line = first[0]
    assert set(line) == {"ts", "by", "host", "op", "set", "target", "base", "revision", "requirements", "lanes", "integration"}
    assert line["op"] == "set-plan" and line["host"] == "cli" and line["set"] == "demo" and line["target"] == "main" and line["base"] == demo.git("rev-parse", "main")
    assert line["revision"] == 1 and line["integration"] == "agent/demo/integration" and line["by"] and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", line["ts"])
    assert line["requirements"] == ["R1", "R2", "R3"]  # the ids; the texts are in the record
    assert line["lanes"] == [{"id": x["id"], "branch": x["branch"], "worktree": x["worktree"], "entries": x["paths"], "serves": x["serves"]} for x in demo_spec(demo, tmp_path)["lanes"]]
    store_before = store_files(demo)
    guard(demo, *sp_args(af, "demo", "main", "--amend", "--expect-revision", "1", "--dry-run"))
    assert store_files(demo) == store_before  # still one line
    plan_ok(guard, demo, af, "--amend", "--expect-revision", "1")
    lines = audit_lines(demo)
    assert len(lines) == 2 and lines[0] == line  # the first line is never touched
    amended = lines[1]
    assert set(amended) == {"ts", "by", "host", "op", "set", "target", "base", "revision", "requirements", "lanes", "integration", "previous_revision", "removed"}
    assert amended["requirements"] == ["R1", "R2", "R3"] and [x["serves"] for x in amended["lanes"]] == [["R1", "R2"], ["R3"]]
    assert amended["op"] == "set-amend" and amended["revision"] == 2 and amended["previous_revision"] == 1 and amended["removed"] == ["ui"] and amended["host"] == "cli"
    assert [x["id"] for x in amended["lanes"]] == ["api", "docs"] and amended["lanes"][1]["entries"] == ["docs/", "notes/"]
    plan_ok(guard, demo, af, "--amend", "--expect-revision", "2")  # an amendment that changes nothing writes nothing
    assert len(audit_lines(demo)) == 2
    # set-update and set-release append their lines after the write; a refusal, set-show and the other reads append none
    r = make_repo(tmp_path, "audit2")
    one = custom_spec(r, tmp_path, [lane(tmp_path, "api", ["src/api/"], worktree=wt_path(tmp_path, "api", prefix="audit2"))])
    plan_ok(guard, r, write_spec(tmp_path, one, "audit2.json"))
    wt = wt_dir(tmp_path, "api", prefix="audit2")
    r.git("worktree", "add", "-q", "-b", "agent/demo/api", str(wt), "main")
    r.commit("src/api/a.py", "a\n", cwd=wt, msg="a")
    tip = r.git("rev-parse", "agent/demo/api")
    assert upd(guard, r, "api", "active", rev=9)[0] == 19 and upd(guard, r, "api", "ready", "--head", "abc")[0] == 24 and jrelease(guard, r)[0] == 16  # refusals
    jshow(guard, r, "--drift")
    jshow(guard, r)
    assert len(audit_lines(r)) == 1
    upd_ok(guard, r, "api", "active", "--note", "go")
    upd_ok(guard, r, "api", "ready", "--head", tip)
    integrate(r, "agent/demo/api")
    r.git("merge", "-q", "--ff-only", INTEGRATION)
    upd_ok(guard, r, "api", "integrated", "--head", tip, "--integration", INTEGRATION)
    assert jrelease(guard, r, "--reason", "done")[0] == 0
    lines = audit_lines(r)
    assert [x["op"] for x in lines] == ["set-plan", "set-update", "set-update", "set-update", "set-release"]
    keys = {"ts", "by", "host", "op", "set", "lane", "state", "head", "note", "integration", "revision", "changes"}
    assert all(set(x) == keys and x["host"] == "cli" and x["set"] == "demo" and x["lane"] == "api" and x["by"] for x in lines[1:4])
    assert [(x["state"], x["head"], x["note"], x["integration"], x["revision"], x["changes"]) for x in lines[1:4]] == [
        ("active", None, "go", None, 2, None), ("ready", tip, "go", None, 3, None),
        ("integrated", tip, "go", INTEGRATION, 4, {"commits": 1, "files": 1, "insertions": 1, "deletions": 1})]  # the four counts of an integrated lane (src/api/a.py changes one line), null otherwise
    released = lines[4]
    assert set(released) == {"ts", "by", "host", "op", "set", "revision", "reason", "abandon", "lanes", "claims"} and released["host"] == "cli"
    assert (released["set"], released["revision"], released["reason"], released["abandon"], released["lanes"], released["claims"]) == (
        "demo", 4, "done", False, ["api"], ["agent/demo/api", INTEGRATION])
    r2 = make_repo(tmp_path, "audit3")
    plan_ok(guard, r2, write_spec(tmp_path, demo_spec(r2, tmp_path), "audit3.json"))
    assert jrelease(guard, r2, "--abandon")[0] == 0
    last = audit_lines(r2)[-1]
    assert last["op"] == "set-release" and last["abandon"] is True and last["reason"] == "" and last["lanes"] == ["api", "ui", "docs"] and len(last["claims"]) == 4


def test_writers_time_out_on_the_lock_and_readers_do_not_wait(demo, guard, tmp_path, monkeypatch):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    plan_ok(guard, demo, f)
    of = write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "xray", ["xdir/"], set_name="other")]), "other.json")
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    af = write_spec(tmp_path, amend, "amend.json")
    before = store_files(demo)
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "1")
    release = holding_lock(demo)
    try:
        for args in (sp_args(of, "other"), sp_args(af, "demo", "main", "--amend", "--expect-revision", "1"), update_args("api", "active", 1),
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
    for args in (update_args("api", "active", 1), ["set-release", "--set", "demo", "--abandon"]):  # the same for set-update and set-release
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
    wt, tip = start_lane(demo, tmp_path, "api", {"src/api/a.py": "a\n"})
    upd_ok(guard, demo, "api", "active")
    state = lambda: (record_file(demo).read_bytes(), store_files(demo), len(audit_lines(demo)))
    before = state()
    commands = {"set-show": (["set-show", "--set", "demo", "--drift"], (0, 2, 3, 5, 7, 8)), "set-update": (update_args("api", "ready", 2, "--head", tip), (2, 3, 5, 7)),
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
    assert g.run("rev-list", "--count", "main..main")[1].strip() == b"0" and {"rev-list", "log", "diff", "merge-base"} <= G.LOCAL_GIT  # rev-list, log and diff are local subcommands
    assert g.run("log", "--format=%s", "main..main")[1] == b"" and g.run("diff", "--numstat", "-z", "main...main")[1] == b""
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
    f = write_spec(tmp_path, custom_spec(r, tmp_path, [lane(tmp_path, "mod-%02d" % i, entries(i)) for i in range(1, 13)]))
    calls = []
    real = G.entries_overlap
    monkeypatch.setattr(G, "entries_overlap", lambda a, b: calls.append(1) or real(a, b))
    for extra in (("--dry-run",), ()):
        calls.clear()
        started = time.monotonic()
        rc, v = jplan(guard, r, f, *extra)
        assert rc == 0 and v["revision"] == 1, v
        assert time.monotonic() - started < time_budget(10), time.monotonic() - started
        assert len(calls) <= 4 * 2400, len(calls)  # the literal-prefix index: a small multiple of the entry count
    assert len(record(r)["lanes"]) == 12 and len(record(r)["lanes"][0]["paths"]) == 200
    # the drift view of the same set, its lanes having changed about 5,000 files: 400 files of each lane inside its manifest (literal directories,
    # one-level and recursive globs) and 16 outside it, every entry of a lane starting with the same literal directory
    for i in range(1, 13):
        files = {"d%d/dir0/f%d.py" % (i, k): "x\n" for k in range(100)}
        files.update({"d%d/mod1/m%d.py" % (i, k): "x\n" for k in range(100)})
        files.update({"d%d/s%d/test_2.py" % (i, k): "x\n" for k in range(100)})
        files.update({"d%d/pkg4/q%d/x1.py" % (i, k): "x\n" for k in range(100)})
        files.update({"zz%d/o%d.txt" % (i, k): "x\n" for k in range(16)})
        fast_commit(r, "agent/demo/mod-%02d" % i, files)
    started = time.monotonic()
    rc, v = jcall(guard, r, "set-show", "--set", "demo", "--drift")
    assert rc == 0 and time.monotonic() - started < time_budget(10), time.monotonic() - started
    assert sum(len(x["changed"]) for x in v["view"]["lanes"]) == 12 * 416 and v["view"]["drift"]["shared_changes"] == []
    assert all(x["out_of_lane"] == sorted("zz%d/o%d.txt" % (i, k) for k in range(16)) for i, x in enumerate(v["view"]["lanes"], 1))
    # every entry in the wildcard group: the full comparison either completes or ends with BUDGET_EXCEEDED and no write, never a partial proof
    r2 = make_repo(tmp_path, "perf2")
    wild = custom_spec(r2, tmp_path, [lane(tmp_path, "mod-%02d" % i, ["**/f_%d_%d.py" % (i, j) for j in range(200)]) for i in range(1, 13)])
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


# ---- TC-311 .. TC-318: requirements, coverage, outcome, topic ids, branch and worktree names, messages -------------------------------------
def spec_error(guard, repo, tmp_path, spec, field, code, name="refused.json"):
    """A refused spec (`--dry-run`): exit 24 naming `field` with `code`, nothing written -> the result."""
    rc, v = dry(guard, repo, tmp_path, spec, name)
    assert rc == 24 and v["code"] == "INVALID_SPEC" and (field, code) in errors_of(v), (field, code, v)
    assert not store_dir(repo).exists()
    return v


def spec_ok(guard, repo, tmp_path, spec, name="accepted.json"):
    rc, v = dry(guard, repo, tmp_path, spec, name)
    assert rc == 0 and v["code"] == "OK", v
    return v


def test_requirements_of_the_spec(demo, guard, tmp_path):
    def spec(reqs, lanes=None):
        return custom_spec(demo, tmp_path, lanes or [lane(tmp_path, "api", ["src/api/"])], requirements=reqs)

    def item(rid, text="a requirement"):
        return {"id": rid, "text": text}
    s = spec([item("R1")])
    del s["requirements"]
    spec_error(guard, demo, tmp_path, s, "requirements", "MISSING")
    spec_error(guard, demo, tmp_path, spec("R1"), "requirements", "TYPE")
    spec_error(guard, demo, tmp_path, spec([]), "requirements", "RANGE")
    twelve = [item("R%d" % i) for i in range(12)]
    spec_ok(guard, demo, tmp_path, spec(twelve, [lane(tmp_path, "api", ["src/api/"], serves=[x["id"] for x in twelve])]))  # 12 items register
    spec_error(guard, demo, tmp_path, spec(twelve + [item("R12")], [lane(tmp_path, "api", ["src/api/"], serves=[x["id"] for x in twelve])]), "requirements[12]", "RANGE")  # 13 do not
    spec_error(guard, demo, tmp_path, spec(["R1"]), "requirements[0]", "TYPE")  # an item that is a string
    spec_error(guard, demo, tmp_path, spec([{"text": "no id"}, item("R1")]), "requirements[0].id", "MISSING")
    spec_error(guard, demo, tmp_path, spec([{"id": "R2"}, item("R1")]), "requirements[0].text", "MISSING")
    spec_error(guard, demo, tmp_path, spec([dict(item("R1"), more=1)]), "requirements[0].more", "UNKNOWN_KEY")
    for rid in ("R", "RRRRRRRR", "R_-9", "a" * 8):  # ids of 1 and 8 characters and the characters the rule allows register
        spec_ok(guard, demo, tmp_path, spec([item(rid)], [lane(tmp_path, "api", ["src/api/"], serves=[rid])]))
    for rid in ("R" * 9, "", "R 1", "R.1", "R\u00e9", "R/1"):  # an id that breaks the rule is FORMAT on its own item
        spec_error(guard, demo, tmp_path, spec([item("R1"), item(rid)]), "requirements[1].id", "FORMAT")
    for other in ("R1", "r1"):  # a repeated id, also ignoring case, is DUPLICATE on the later item
        spec_error(guard, demo, tmp_path, spec([item("R1"), item(other)]), "requirements[1].id", "DUPLICATE")
    for text in ("t", "t" * 200):
        spec_ok(guard, demo, tmp_path, spec([item("R1", text)]))
    spec_error(guard, demo, tmp_path, spec([item("R1", "t" * 201)]), "requirements[0].text", "RANGE")
    spec_error(guard, demo, tmp_path, spec([item("R1", "")]), "requirements[0].text", "RANGE")
    spec_error(guard, demo, tmp_path, spec([item("R1", 5)]), "requirements[0].text", "TYPE")
    spec_error(guard, demo, tmp_path, spec([item("R1", "a\x01b")]), "requirements[0].text", "FORMAT")
    # the record stores the requirements as the spec gives them, in its order; an amend replaces them whole
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    assert record(demo)["requirements"] == REQUIREMENTS
    amend = demo_spec(demo, tmp_path, requirements=[REQUIREMENTS[2], REQUIREMENTS[0], dict(REQUIREMENTS[1], text="the UI shows it at last")])
    v = plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", "1")
    assert v["revision"] == 2 and record(demo)["requirements"] == amend["requirements"] and [x["id"] for x in v["requirements"]] == ["R3", "R1", "R2"]
    assert [x["lanes"] for x in v["requirements"]] == [["docs"], ["api"], ["ui"]]


def test_every_requirement_is_served_and_every_lane_serves_one(demo, guard, tmp_path):
    def three(**serves):
        s = demo_spec(demo, tmp_path)
        for lid, ids in serves.items():
            next(x for x in s["lanes"] if x["id"] == lid)["serves"] = ids
        return s
    # a requirement nobody serves is refused, every one of them is named, with its id and text
    v = spec_error(guard, demo, tmp_path, three(ui=["R3"]), "requirements[1]", "UNSERVED")
    assert errors_of(v) == {("requirements[1]", "UNSERVED")}
    assert v["errors"][0]["text"] == ("requirement R2 (the UI shows it) is served by no lane. Serve it with a lane: add R2 to the serves of a lane, or add a lane "
                                      "for it. Never drop a requirement the user stated.")
    zh = run(["--repo", str(demo.path), "--lang", "zh", "--json", *sp_args(write_spec(tmp_path, three(ui=["R3"]), "zh.json"), "demo", "main", "--dry-run")])
    assert json.loads(zh.out)["errors"][0]["text"] == "需求 R2（the UI shows it）没有任何 lane 负责。请用一个 lane 负责它：把 R2 加入某个 lane 的 serves，或为它新增一个 lane。不要删除用户提出的需求。"
    long_text = three(ui=["R3"])
    long_text["requirements"][1]["text"] = "t" * 100  # the text of the requirement is cut to 60 characters in the message
    v = spec_error(guard, demo, tmp_path, long_text, "requirements[1]", "UNSERVED")
    assert v["errors"][0]["text"] == G.T("en", "set_err_unserved", r="R2", t="t" * 60) and "t" * 61 not in v["errors"][0]["text"]
    v = spec_error(guard, demo, tmp_path, three(ui=["R1"], docs=["R1"]), "requirements[2]", "UNSERVED")
    assert errors_of(v) == {("requirements[1]", "UNSERVED"), ("requirements[2]", "UNSERVED")}
    # what a lane serves: 1 to 12 existing ids, each once
    v = spec_error(guard, demo, tmp_path, three(api=[]), "lanes[0].serves", "RANGE")
    assert next(e for e in v["errors"] if e["code"] == "RANGE")["text"] == "the serves of lane api needs 1 to 12 requirement ids (0 given)."
    s = three()
    del s["lanes"][0]["serves"]
    spec_error(guard, demo, tmp_path, s, "lanes[0].serves", "MISSING")
    spec_error(guard, demo, tmp_path, three(api=["R1"] * 13), "lanes[0].serves", "RANGE")
    spec_error(guard, demo, tmp_path, three(api=["R1", "R1"]), "lanes[0].serves[1]", "DUPLICATE")
    v = spec_error(guard, demo, tmp_path, three(api=["R9", "R1"]), "lanes[0].serves[0]", "UNKNOWN_REQUIREMENT")
    assert next(e for e in v["errors"] if e["code"] == "UNKNOWN_REQUIREMENT")["text"] == "'R9' in serves is no requirement id of this spec (known: R1, R2, R3; ids are matched exactly, case included)."
    spec_error(guard, demo, tmp_path, three(api=["r1"]), "lanes[0].serves[0]", "UNKNOWN_REQUIREMENT")  # another case is another id
    spec_error(guard, demo, tmp_path, three(api=[5]), "lanes[0].serves[0]", "UNKNOWN_REQUIREMENT")
    # one requirement served by two lanes, one lane serving three requirements: both register, and the lanes of a requirement are listed in lane order
    both = three(api=["R1", "R2", "R3"], ui=["R2"], docs=["R3", "R1"])
    v = plan_ok(guard, demo, write_spec(tmp_path, both, "both.json"))
    assert [(x["id"], x["lanes"]) for x in v["requirements"]] == [("R1", ["api", "docs"]), ("R2", ["api", "ui"]), ("R3", ["api", "docs"])]
    shown = jshow(guard, demo)
    assert shown["view"]["requirements"] == v["requirements"] and [x["serves"] for x in shown["record"]["lanes"]] == [["R1", "R2", "R3"], ["R2"], ["R3", "R1"]]
    # the only lane that serves R3 has an invalid id: its one id error, and no UNSERVED besides (its serves count)
    other = make_repo(tmp_path, "other")
    s = demo_spec(other, tmp_path)
    s["lanes"][2] = lane(tmp_path, "L1", ["docs/"], serves=["R3"])
    s["shared"] = []
    v = spec_error(guard, other, tmp_path, s, "lanes[2].id", "GENERIC_ID")
    assert errors_of(v) == {("lanes[2].id", "GENERIC_ID")}
    # an amend is validated as a whole: it is refused while a requirement is left without a lane, and registers when the requirement goes with its lane
    amend = drop_lane(demo_spec(demo, tmp_path), "docs", with_requirements=False)
    amend["lanes"][0]["serves"] = ["R1"]
    amend["lanes"][1]["serves"] = ["R2"]  # R3 is served by nobody now
    before = store_files(demo)
    rc, v = jplan(guard, demo, write_spec(tmp_path, amend, "amend1.json"), "--amend", "--expect-revision", "1")
    assert rc == 24 and errors_of(v) == {("requirements[2]", "UNSERVED")} and store_files(demo) == before
    both_gone = drop_lane(demo_spec(demo, tmp_path), "docs", with_requirements=True)
    assert plan_ok(guard, demo, write_spec(tmp_path, both_gone, "amend2.json"), "--amend", "--expect-revision", "1")["revision"] == 2
    assert [x["id"] for x in record(demo)["requirements"]] == ["R1", "R2"]


def test_outcome_is_required_and_acceptance_is_optional(demo, guard, tmp_path):
    def spec_with(**over):
        s = demo_spec(demo, tmp_path)
        s["lanes"][1].update(over)
        return s

    def without(key):
        s = demo_spec(demo, tmp_path)
        del s["lanes"][1][key]
        return s
    spec_error(guard, demo, tmp_path, without("outcome"), "lanes[1].outcome", "MISSING")
    spec_error(guard, demo, tmp_path, spec_with(outcome=""), "lanes[1].outcome", "RANGE")
    spec_error(guard, demo, tmp_path, spec_with(outcome="o" * 301), "lanes[1].outcome", "RANGE")
    spec_error(guard, demo, tmp_path, spec_with(outcome=5), "lanes[1].outcome", "TYPE")
    spec_error(guard, demo, tmp_path, spec_with(outcome="a\x01b"), "lanes[1].outcome", "FORMAT")
    for outcome in ("o", "o" * 300):
        spec_ok(guard, demo, tmp_path, spec_with(outcome=outcome))
    spec_error(guard, demo, tmp_path, spec_with(acceptance="a" * 301), "lanes[1].acceptance", "RANGE")
    spec_error(guard, demo, tmp_path, spec_with(acceptance=5), "lanes[1].acceptance", "TYPE")
    spec_ok(guard, demo, tmp_path, spec_with(acceptance="a" * 300))
    # an omitted acceptance and an empty one are the same: both are stored as the empty string, in the same record bytes
    records = []
    for n, accept in enumerate((KeyError, "")):
        r = make_repo(tmp_path, "accept%d" % n)
        s = demo_spec(r, tmp_path)
        if accept is KeyError:
            s["lanes"][1].pop("acceptance")
        else:
            s["lanes"][1]["acceptance"] = accept
        v = plan_ok(guard, r, write_spec(tmp_path, s, "accept%d.json" % n))
        assert v["lanes"][1]["acceptance"] == "" and v["lanes"][1]["outcome"] == "the outcome of ui"  # the lane rows of the result carry both
        raw = record_file(r).read_bytes().replace(r.git("rev-parse", "main").encode(), b"BASE")
        records.append(re.sub(rb'"\d{4}-\d\d-\d\dT[\d:]+Z"', b'"TIME"', raw))  # the times of the two registrations differ, nothing else may
    assert records[0] == records[1] and record(r)["lanes"][1]["acceptance"] == ""


def test_lane_ids_are_topic_slugs(demo, guard, tmp_path):
    def one(lid, extra=None):
        lanes = [lane(tmp_path, lid if isinstance(lid, str) else "api", ["src/api/"], id=lid)] + (extra or [])
        return custom_spec(demo, tmp_path, lanes)

    def only_error(lid, field_code):
        rc, v = dry(guard, demo, tmp_path, one(lid), "ids.json")
        assert rc == 24 and errors_of(v) == {("lanes[0].id", field_code)}, (lid, v)  # each bad id yields exactly one error
        assert not store_dir(demo).exists()
        return v["errors"][0]["text"]
    for lid in ("api", "ui", "a1", "claim-store", "x-1", "lane-a", "part-a", "i" * 24):
        spec_ok(guard, demo, tmp_path, one(lid))
    generic = ["L1", "l1", "lane-2", "lane2", "Task3", "task-12", "agent-7", "worker1", "wt-1", "t4", "n5", "w6", "work-8", "part-9", "step-10", "item-11", "1", "2024", "a", "Z"]
    for lid in generic:
        text = only_error(lid, "GENERIC_ID")
        assert text == G.T("en", "set_err_generic_id", id=lid) and "claim-store, sweep-readiness, readme-gitplan" in text and "1 to 3 words" in text
    for lid in ("integration", "Integration", "INTEGRATION", "con", "Aux", "nul", "com1", "lpt9"):
        assert only_error(lid, "RESERVED") == G.T("en", "set_err_reserved_id", id=lid)
    for lid, hint in (("Claim-Store", "claim-store"), ("claim_store", "claim-store"), ("i" * 25, None), ("-api", None), ("api.v2", None), ("a b", None), ("", None), ("caf\u00e9", None)):
        text = only_error(lid, "FORMAT")
        assert text == G.T("en", "set_err_id_form", id=lid, rule="[a-z0-9][a-z0-9-]{0,23}", hint=(" Suggestion: %s." % hint) if hint else "") and ("Suggestion:" in text) == bool(hint), (lid, text)
    for bad in (5, None):
        rc, v = dry(guard, demo, tmp_path, one(bad), "ids.json")
        assert rc == 24 and ("lanes[0].id", "TYPE") in errors_of(v)
    rc, v = dry(guard, demo, tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"]), lane(tmp_path, "api", ["src/ui/"])]), "ids.json")
    assert rc == 24 and errors_of(v) == {("lanes[1].id", "DUPLICATE")}
    # a depends_on entry and a shared owner that name a refused id are not reported a second time, and the lane has no branch or worktree error
    s = custom_spec(demo, tmp_path, [lane(tmp_path, "L1", ["src/api/"]), lane(tmp_path, "ui", ["src/ui/"], ["L1"])], shared=[{"path": "src/api/a.py", "owner": "L1"}])
    rc, v = dry(guard, demo, tmp_path, s, "ids.json")
    assert rc == 24 and errors_of(v) == {("lanes[0].id", "GENERIC_ID")}, v
    # the text is in the language of the call and equals errors[].text of --json
    for lang, want in (("zh", "是序号或泛称，看不出改动的主题"), ("en", "is an ordinal or generic name and does not show the topic of the change")):
        r = run(["--repo", str(demo.path), "--lang", lang, "--json", *sp_args(write_spec(tmp_path, one("L1"), "ids.json"), "demo", "main", "--dry-run")])
        v = json.loads(r.out)
        assert v["errors"][0]["text"] == G.T(lang, "set_err_generic_id", id="L1") and want in v["errors"][0]["text"] and v["errors"][0]["text"] in v["message"]
        text = run(["--repo", str(demo.path), "--lang", lang, *sp_args(write_spec(tmp_path, one("L1"), "ids.json"), "demo", "main", "--dry-run")]).out
        assert "  [GENERIC_ID] lanes[0].id: %s" % G.T(lang, "set_err_generic_id", id="L1") in text


def test_the_lane_branch_is_agent_set_id(demo, guard, tmp_path):
    def with_branch(branch):
        return custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"], branch=branch)])
    spec_ok(guard, demo, tmp_path, with_branch("agent/demo/api"))
    for branch in ("feature/api", "agent/demo/API", "Agent/demo/api", "agent/other/api", "agent/demo/ui", "agent/demo/api/x", "agent/demo", "agent/demo/integration",
                   "agent/demo/api ", ""):
        v = spec_error(guard, demo, tmp_path, with_branch(branch), "lanes[0].branch", "BRANCH_FORM")
        text = v["errors"][0]["text"]
        assert text == G.T("en", "set_err_branch_form", l="api", want="agent/demo/api", got=branch) and "agent/demo/api" in text, (branch, text)
    spec_error(guard, demo, tmp_path, with_branch(5), "lanes[0].branch", "TYPE")
    for lang, want in (("zh", "lane api 的分支必须是 agent/demo/api"), ("en", "the branch of lane api must be agent/demo/api")):
        r = run(["--repo", str(demo.path), "--lang", lang, "--json", *sp_args(write_spec(tmp_path, with_branch("feature/api"), "b.json"), "demo", "main", "--dry-run")])
        v = json.loads(r.out)
        assert want in v["errors"][0]["text"] and v["errors"][0]["text"] in v["message"]
    swapped = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"], branch="agent/demo/ui"), lane(tmp_path, "ui", ["src/ui/"], branch="agent/demo/api")])
    rc, v = dry(guard, demo, tmp_path, swapped, "swapped.json")
    assert rc == 24 and errors_of(v) == {("lanes[0].branch", "BRANCH_FORM"), ("lanes[1].branch", "BRANCH_FORM")}  # one error for each lane
    # what is registered carries the branch agent/<set>/<id> in the claims, the record and the create command
    v = plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path), "ok.json"))
    for x, rec_lane in zip(v["lanes"], record(demo)["lanes"]):
        assert x["branch"] == rec_lane["branch"] == "agent/demo/" + x["id"] and ("-b agent/demo/%s main" % x["id"]) in x["create"]
        assert "branch=agent/demo/" + x["id"] in claim_lines(demo, "agent/demo/" + x["id"])


def test_the_worktree_directory_ends_with_set_and_id(demo, guard, tmp_path):
    parent = P(tmp_path)  # the main worktree of the fixture is <parent>/repo
    default = parent + "/repo-demo-api"

    def with_worktree(value, lid="api", **over):
        return custom_spec(demo, tmp_path, [lane(tmp_path, lid, ["src/api/"], worktree=value, **over)])
    for value, stored in ((parent + "/repo-demo-api", default), (parent + "/x-demo-api", parent + "/x-demo-api"), (parent + "/Repo-demo-api", parent + "/Repo-demo-api"),
                          (parent + "/con-demo-api", parent + "/con-demo-api"), (parent + "/repo-demo-api/", default)):
        v = spec_ok(guard, demo, tmp_path, with_worktree(value))  # a name that ends with -demo-api after a non-empty prefix; the trailing separator is gone once normalised
        assert v["lanes"][0]["worktree"] == stored
    for value in ("repo-demo-ui", "repo-api", "repo-other-api", "-demo-api", "demo-api", "Repo-Demo-Api", "repo-demo-api.x"):  # compared exactly, case included
        v = spec_error(guard, demo, tmp_path, with_worktree(parent + "/" + value), "lanes[0].worktree", "WORKTREE_FORM")
        assert v["errors"][0]["text"] == G.T("en", "set_err_worktree_form", l="api", s="demo", got=value, want=default) and default in v["errors"][0]["text"], v
        assert len(v["errors"]) == 1
    root = "C:/" if os.name == "nt" else "/"
    v = spec_error(guard, demo, tmp_path, with_worktree(root), "lanes[0].worktree", "WORKTREE_FORM")  # the root of a drive has no name
    assert v["errors"][0]["text"] == G.T("en", "set_err_worktree_form", l="api", s="demo", got="", want=default)
    v = spec_error(guard, demo, tmp_path, with_worktree(parent + "/aux.x-demo-api"), "lanes[0].worktree", "WORKTREE")  # a device name before the first dot, on every platform
    assert v["errors"][0]["text"] == G.T("en", "set_err_worktree_device", l="api", got="aux.x-demo-api", dev="aux", want=default) and len(v["errors"]) == 1
    v = spec_error(guard, demo, tmp_path, with_worktree("wt/repo-demo-api"), "lanes[0].worktree", "WORKTREE")  # a spelling error is the only error of a worktree
    assert [e["field"] for e in v["errors"]] == ["lanes[0].worktree"] and "absolute" in v["errors"][0]["text"]
    s = custom_spec(demo, tmp_path, [lane(tmp_path, "L1", ["src/api/"], worktree=parent + "/anything")])  # a lane with an invalid id has no name error
    rc, v = dry(guard, demo, tmp_path, s, "invalid-id.json")
    assert rc == 24 and errors_of(v) == {("lanes[0].id", "GENERIC_ID")}
    for lang, want in (("zh", "lane api 的工作树目录名必须以 -demo-api 结尾"), ("en", "the worktree directory of lane api must have a name ending with -demo-api")):
        r = run(["--repo", str(demo.path), "--lang", lang, "--json", *sp_args(write_spec(tmp_path, with_worktree(parent + "/repo-api"), "w.json"), "demo", "main", "--dry-run")])
        v = json.loads(r.out)
        assert want in v["errors"][0]["text"] and default in v["errors"][0]["text"] and v["errors"][0]["text"] in v["message"]
    assert not store_dir(demo).exists()
    # two worktrees that differ only in case still compare equal where the platform folds case
    two = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"], worktree=parent + "/OUT-demo-api"), lane(tmp_path, "ui", ["src/ui/"], worktree=parent + "/out-demo-api/x-demo-ui")])
    assert dry(guard, demo, tmp_path, two, "case.json")[0] == (24 if os.name == "nt" else 0)


def test_naming_and_coverage_messages_exist_in_both_languages(demo, guard, tmp_path, monkeypatch):
    import string
    wanted = {"set_err_generic_id": {"id"}, "set_err_reserved_id": {"id"}, "set_err_id_form": {"id", "rule", "hint"}, "set_hint_slug": {"slug"},
              "set_err_set_name": {"s", "rule"}, "set_err_set_device": {"s"},
              "set_err_branch_form": {"l", "want", "got"}, "set_err_worktree_form": {"l", "s", "got", "want"}, "set_err_worktree_device": {"l", "got", "dev", "want"},
              "set_err_unserved": {"r", "t"}, "set_err_serves_unknown": {"r", "ids"}, "set_err_serves_count": {"l", "n"}, "set_why_changes_target": {"t", "l"},
              "set_why_changes_history": {"l", "ref"}, "show_changes": {"l", "commits", "files", "ins", "del", "paths", "subjects"}, "show_more": {"n"},
              "set_invalid": {"errors"}, "set_invalid_args": {"errors"}}
    for key, fields in wanted.items():
        for column, lang in enumerate(("zh", "en")):
            template = G.M[key][column]
            assert {f for _lit, f, _spec, _conv in string.Formatter().parse(template) if f} == fields, (key, lang)  # exactly the placeholders the code passes
            rendered = G.T(lang, key, **{f: "<%s>" % f for f in fields})
            assert "{" not in rendered and "}" not in rendered and all("<%s>" % f in rendered for f in fields), (key, lang, rendered)  # no literal brace is left
        assert G.M[key][0] != G.M[key][1]
    assert "[a-z0-9][a-z0-9-]{0,23}" in G.T("en", "set_err_id_form", id="X", rule=G.SLUG_RULE, hint="")  # the slug rule enters through {rule}
    assert "[a-z0-9][a-z0-9-]{0,23}" in G.T("en", "set_err_set_name", s="X", rule=G.SLUG_RULE) and "[a-z0-9][a-z0-9-]{0,23}" in G.T("zh", "set_err_set_name", s="X", rule=G.SLUG_RULE)
    # the reserved id asks for another topic slug and names no example; the device set name asks for another name; the others state the compliant form
    for lang in ("zh", "en"):
        assert not any(x in G.T(lang, "set_err_reserved_id", id="integration") for x in ("integration-docs", "claim-store", "例如", "for example"))
        assert ("另选一个" if lang == "zh" else "Choose another name") in G.T(lang, "set_err_set_device", s="con")
        assert "<id>" in G.T(lang, "set_err_reserved_id", id="<id>") and "<s>" in G.T(lang, "set_err_set_name", s="<s>", rule=G.SLUG_RULE)
    # a spec that triggers each error, through the command in both languages and with MAGOS_LANG
    s = demo_spec(demo, tmp_path)
    s["lanes"] = [lane(tmp_path, "L1", ["a/"], serves=["R1"]), lane(tmp_path, "integration", ["b/"], serves=["R1"]), lane(tmp_path, "Claim-Store", ["c/"], serves=["R1"]),
                  lane(tmp_path, "alpha", ["d/"], serves=["R1"], branch="feature/alpha", worktree=P(tmp_path / "x-demo-beta")),
                  lane(tmp_path, "beta", ["e/"], serves=["R9"], worktree=P(tmp_path / "aux.x-demo-beta")), lane(tmp_path, "gamma", ["f/"], serves=[])]
    s["shared"] = []
    f = write_spec(tmp_path, s, "all.json")
    for lang in ("zh", "en"):
        expected = {("lanes[0].id", "GENERIC_ID"): G.T(lang, "set_err_generic_id", id="L1"), ("lanes[1].id", "RESERVED"): G.T(lang, "set_err_reserved_id", id="integration"),
                    ("lanes[2].id", "FORMAT"): G.T(lang, "set_err_id_form", id="Claim-Store", rule=G.SLUG_RULE, hint=" " + G.T(lang, "set_hint_slug", slug="claim-store")),
                    ("lanes[3].branch", "BRANCH_FORM"): G.T(lang, "set_err_branch_form", l="alpha", want="agent/demo/alpha", got="feature/alpha"),
                    ("lanes[3].worktree", "WORKTREE_FORM"): G.T(lang, "set_err_worktree_form", l="alpha", s="demo", got="x-demo-beta", want=P(tmp_path) + "/repo-demo-alpha"),
                    ("lanes[4].worktree", "WORKTREE"): G.T(lang, "set_err_worktree_device", l="beta", got="aux.x-demo-beta", dev="aux", want=P(tmp_path) + "/repo-demo-beta"),
                    ("lanes[4].serves[0]", "UNKNOWN_REQUIREMENT"): G.T(lang, "set_err_serves_unknown", r="R9", ids="R1, R2, R3"),
                    ("lanes[5].serves", "RANGE"): G.T(lang, "set_err_serves_count", l="gamma", n=0),
                    ("requirements[1]", "UNSERVED"): G.T(lang, "set_err_unserved", r="R2", t=REQUIREMENTS[1]["text"])}
        for how in ("flag", "env"):
            if how == "env":
                monkeypatch.setenv("MAGOS_LANG", lang)
            argv = (["--lang", lang] if how == "flag" else []) + sp_args(f, "demo", "main", "--dry-run")
            as_json = run(["--repo", str(demo.path), "--json", *argv])
            as_text = run(["--repo", str(demo.path), *argv])
            if how == "env":
                monkeypatch.delenv("MAGOS_LANG")
            v = json.loads(as_json.out)
            got = {(e["field"], e["code"]): e["text"] for e in v["errors"]}
            for key, text in expected.items():
                assert got[key] == text, (lang, how, key, got[key])  # the entries of M, with the placeholders the design names
                assert "  [%s] %s: %s" % (key[1], key[0], text) in as_text.out  # the same line in the text of the command
            # an option value: the set name, refused in the language of the call by set-plan and by set-show alike
            for sub_args in (sp_args(f, "Bad_Name", "main", "--dry-run"), ["set-show", "--set", "Bad_Name"]):
                if how == "env":
                    monkeypatch.setenv("MAGOS_LANG", lang)
                flag = ["--lang", lang] if how == "flag" else []
                named = json.loads(run(["--repo", str(demo.path), "--json", *flag, *sub_args]).out)
                named_text = run(["--repo", str(demo.path), *flag, *sub_args]).out
                if how == "env":
                    monkeypatch.delenv("MAGOS_LANG")
                want = G.T(lang, "set_err_set_name", s="Bad_Name", rule=G.SLUG_RULE)
                assert [(e["field"], e["code"], e["text"]) for e in named["errors"]] == [("--set", "FORMAT", want)] and "  [FORMAT] --set: " + want in named_text
    # the text of every other code stays English in both languages
    other = demo_spec(demo, tmp_path)
    other["lanes"][0]["nope"] = 1
    for lang in ("zh", "en"):
        v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", *sp_args(write_spec(tmp_path, other, "other.json"), "demo", "main", "--dry-run")]).out)
        assert [e["text"] for e in v["errors"]] == ["not a key of the spec"]


def test_valid_names_always_pass_check_name(demo, guard, tmp_path):
    import random
    from concurrent.futures import ThreadPoolExecutor
    rng = random.Random(20261022)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"

    def slug(minimum=1, tail_hyphen=False):
        n = rng.randint(minimum, 24)
        chars = [rng.choice(alphabet)]
        for _ in range(n - 1):
            chars.append("-" if rng.random() < 0.25 else rng.choice(alphabet))
        text = "".join(chars)
        if tail_hyphen and n > 1:
            text = text[:-1] + "-"
        return text
    pairs = []
    while len(pairs) < 2000:
        set_name, lid = slug(), slug(tail_hyphen=rng.random() < 0.2)
        if G.set_name_problem(set_name) is None and G.lane_id_problem("en", lid) is None:
            pairs.append((set_name, lid))
    g = G.Git(str(demo.path), budget=600)
    one_hyphen_runs = [("a--b", "c---d"), ("a-b-", "e-"), ("z" * 24, "y" * 24)]
    pairs += one_hyphen_runs

    def check(pair):
        set_name, lid = pair
        branch = "agent/%s/%s" % (set_name, lid)
        return branch, G.name_problem(g, branch), len(branch)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, pairs))
    assert all(problem is None and size <= 55 for _b, problem, size in results), [r for r in results if r[1] is not None or r[2] > 55][:3]  # check-ref-format, 100 characters, characters, devices, aliases
    by_set = {}
    for set_name, lid in pairs:
        by_set.setdefault(set_name, set()).add(lid)
    for set_name, ids in by_set.items():  # no lane branch equals, nests in or case-collides with another lane branch or the integration branch
        branches_ = ["agent/%s/%s" % (set_name, i) for i in sorted(ids)] + ["agent/%s/integration" % set_name]
        assert G.name_problem(g, "agent/%s/integration" % set_name) is None
        for b in branches_:
            assert G.name_clash(b, [x for x in branches_ if x != b]) is None, (b, branches_)
    # the Windows device names: as a set name they are refused on --set, as a lane id they are RESERVED once (no BRANCH_NAME besides), and integration is RESERVED in every case
    for dev in ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9"):
        assert G.set_name_problem(dev) is not None
        assert G.lane_id_problem("en", dev)[0] == "RESERVED" and G.lane_id_problem("en", dev.upper())[0] == "RESERVED"
        s = custom_spec(demo, tmp_path, [lane(tmp_path, dev, ["src/api/"])])
        rc, v = dry(guard, demo, tmp_path, s, "dev.json")
        assert rc == 24 and errors_of(v) == {("lanes[0].id", "RESERVED")}
        assert jplan(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path), "ok.json"), "--dry-run", name=dev)[1]["errors"][0]["field"] == "--set"
    for case in ("integration", "Integration", "INTEGRATION", "iNtEgRaTiOn"):
        assert G.lane_id_problem("en", case)[0] == "RESERVED"
    # a lane branch equal to the target is exit 24 BRANCH_NAME
    demo.git("branch", "agent/demo/api", "main")
    rc, v = jplan(guard, demo, write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/api/"])]), "target.json"), "--dry-run", target="agent/demo/api")
    assert rc == 24 and ("lanes[0].branch", "BRANCH_NAME") in errors_of(v)


# ---- TC-319 .. TC-324: the summary of the changes of an integrated lane --------------------------------------------------------------
SUMMARY_COMMANDS = ("merge-base", "rev-list", "log", "diff")
EMPTY_SUMMARY = {"commits": 0, "subjects": [], "more": 0, "files": 0, "insertions": 0, "deletions": 0, "paths": [], "paths_more": 0}


def fast_chain(repo, branch, commits, parent="main"):
    """A chain of commits on `branch` cut from `parent`, in one git process (fast-import): `commits` is [(message, {path: text, bytes or None to delete})]
    and the messages are written as given (an empty one, a tab, an escape character).  -> the tip."""
    buf, first = bytearray(), True
    for n, (message, files) in enumerate(commits):
        msg = message if isinstance(message, bytes) else message.encode("utf-8")
        buf += b"commit refs/heads/%s\ncommitter t <t@example.invalid> %d +0000\ndata %d\n" % (branch.encode(), 1700000000 + n, len(msg)) + msg + b"\n"
        if first:
            buf += b"from %s\n" % repo.git("rev-parse", parent).encode()
            first = False
        for path, content in files.items():
            if content is None:
                buf += b"D " + path.encode("utf-8") + b"\n"
                continue
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            buf += b"M 100644 inline " + path.encode("utf-8") + b"\ndata %d\n" % len(data) + data + b"\n"
        buf += b"\n"
    sub(["git", "fast-import", "--quiet"], cwd=str(repo.path), input=bytes(buf), capture_output=True)
    return repo.git("rev-parse", "refs/heads/" + branch)


def summary_of(repo, branch, parent="main"):
    """The changes summary of `branch` against `parent`: the function of the guard, with a budget of its own."""
    return G.changes_summary(G.Git(str(repo.path), budget=120), repo.git("rev-parse", parent), repo.git("rev-parse", branch))


class RecordedCalls(list):
    """The arguments of the Git.run calls made since recorded_git; stop() puts the real Git.run back."""

    def stop(self):
        self.monkeypatch.setattr(G.Git, "run", self.real)


def recorded_git(monkeypatch):
    """Record the arguments of every Git.run call -> the list."""
    calls = RecordedCalls()
    calls.monkeypatch, calls.real = monkeypatch, G.Git.run
    real = G.Git.run

    def run_(self, *args, **kw):
        calls.append(args)
        return real(self, *args, **kw)
    monkeypatch.setattr(G.Git, "run", run_)
    return calls


def summary_calls(calls):
    """The Git commands of a call that belong to the summary: merge-base (not the ancestry test), rev-list, log and diff."""
    return [c for c in calls if c[0] in SUMMARY_COMMANDS and "--is-ancestor" not in c]


def test_integrated_stores_the_changes_summary(guard, tmp_path, monkeypatch):
    repo = make_repo(tmp_path, "r319", files=("src/ui/u.py", "docs/d.md", "README.md", "package-lock.json"))
    repo.git("config", "diff.renames", "false")  # the configuration of the user changes nothing of the result
    repo.git("config", "log.showSignature", "true")
    repo.git("config", "i18n.logOutputEncoding", "latin1")
    repo.git("config", "core.quotepath", "true")
    plan_ok(guard, repo, write_spec(tmp_path, demo_spec(repo, tmp_path)))
    wt, _ = start_lane(repo, tmp_path, "api", {"src/api/a.py": "".join("line %d\n" % i for i in range(1, 11))}, msg="add the api")
    repo.write("src/api/a.py", "".join("line %d\n" % i for i in range(1, 11)).replace("line 5\n", "line 5a\nline 5b\n"), base=wt)
    repo.git("commit", "-q", "-am", "change the api", cwd=wt)
    repo.commit("tests/api/t.py", "t1\nt2\nt3\nt4\n", cwd=wt, msg="add the api tests")
    head = repo.git("rev-parse", LANES["api"])
    ready_lane(guard, repo, "api", head)
    integrate(repo, LANES["api"])
    before = record_file(repo).read_text(encoding="utf-8")
    rev = record(repo)["revision"]
    main_tip = repo.git("rev-parse", "main")
    calls = recorded_git(monkeypatch)
    rc, v = upd(guard, repo, "api", "integrated", "--head", head, "--integration", INTEGRATION)
    assert rc == 0 and set(v) == UPDATE_KEYS and v["state"] == "integrated" and v["revision"] == rev + 1, v
    summary = {"commits": 3, "subjects": ["add the api", "change the api", "add the api tests"], "more": 0, "files": 2, "insertions": 15, "deletions": 0,
               "paths": ["src/api", "tests/api"], "paths_more": 0}  # the net change from the merge base: a.py is one new file of 11 lines, not the sum of its two commits
    assert v["changes"] == summary and list(v["changes"]) == list(G.CHANGES_KEYS)
    stored = lane_of(record(repo), "api")["changes"]
    assert stored == summary and list(stored) == list(G.CHANGES_KEYS) and [lane_of(record(repo), x)["changes"] for x in ("ui", "docs")] == [None, None]
    after = record_file(repo).read_text(encoding="utf-8")
    keys = {k for k in changed_keys(before, after) if not k.startswith(("+", "-"))}
    assert keys <= {"revision", "updated", "by", "integration", "state", "changes", "commits", "subjects", "more", "files", "insertions", "deletions", "paths", "paths_more"}, keys
    assert record(repo)["revision"] == rev + 1 and record(repo)["integration"] == INTEGRATION
    # the Git commands of the summary: after the conditions of integrated, with full object names and the current tip of main as the compare tip, nothing outside LOCAL_GIT
    ancestry = [i for i, c in enumerate(calls) if c[0] == "merge-base" and "--is-ancestor" in c]
    assert len(ancestry) == 2 and calls[ancestry[0]][-1] == main_tip and calls[ancestry[1]][-1] == repo.git("rev-parse", INTEGRATION)  # main first, the integration branch second
    assert [c for c in summary_calls(calls)] == [
        ("merge-base", main_tip, head), ("rev-list", "--count", "--no-merges", "%s..%s" % (main_tip, head)),
        ("log", "--no-show-signature", "--encoding=UTF-8", "--format=%s", "--reverse", "--no-merges", "--skip=0", "--max-count=8", "%s..%s" % (main_tip, head)),
        ("diff", "--numstat", "-z", "--find-renames", "--no-ext-diff", "--no-textconv", "%s...%s" % (main_tip, head), "--")]
    assert all(c[0] in G.LOCAL_GIT for c in calls) and calls.index(summary_calls(calls)[0]) > ancestry[1]
    audits = [x for x in audit_lines(repo) if x["op"] == "set-update"]
    assert audits[-1]["state"] == "integrated" and audits[-1]["changes"] == {"commits": 3, "files": 2, "insertions": 15, "deletions": 0}
    assert all(x["changes"] is None for x in audits[:-1])
    # the same call as text, in both languages, for the other lanes: the summary is the JSON's, the message is the usual one
    _, ui_tip = start_lane(repo, tmp_path, "ui", {"src/ui/new.py": "n\n"}, msg="add the ui")
    ready_lane(guard, repo, "ui", ui_tip)
    integrate(repo, LANES["ui"], create=False)
    text = guard(repo, *update_args("ui", "integrated", record(repo)["revision"], "--head", ui_tip))
    assert text.rc == 0 and text.out.rstrip("\n") == "MAGOS: lane ui of set 'demo' is now integrated, revision %d." % record(repo)["revision"]
    assert lane_of(record(repo), "ui")["changes"]["subjects"] == ["add the ui"]
    _, docs_tip = start_lane(repo, tmp_path, "docs", {"docs/new.md": "n\n"}, msg="add the docs")
    ready_lane(guard, repo, "docs", docs_tip)
    integrate(repo, LANES["docs"], create=False)
    zh = run(["--repo", str(repo.path), "--lang", "zh", *update_args("docs", "integrated", record(repo)["revision"], "--head", docs_tip)])
    assert zh.rc == 0 and "的 lane docs 现在是 integrated" in zh.out and lane_of(record(repo), "docs")["changes"]["subjects"] == ["add the docs"]


def test_changes_summary_bounds(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, "r320", files=("README.md", "src/keep.py"))
    repo.git("config", "core.quotepath", "true")
    # twenty commits: the eight oldest, oldest first, and the number of the others
    fast_chain(repo, "lane20", [("c%02d" % i, {"d/f%02d.txt" % i: "x\n"}) for i in range(1, 21)])
    s = summary_of(repo, "lane20")
    assert s["commits"] == 20 and s["subjects"] == ["c%02d" % i for i in range(1, 9)] and s["more"] == 12 and s["files"] == 20 and s["paths"] == ["d/f%02d.txt" % i for i in range(1, 13)]
    assert s["paths_more"] == 8 and s["insertions"] == 20 and s["deletions"] == 0
    for n, want_more in ((8, 0), (9, 1)):  # eight commits are read whole, nine give the eight oldest and one more
        fast_chain(repo, "lane%d" % n, [("m%d" % i, {"f%d.txt" % i: "x\n"}) for i in range(1, n + 1)])
        s = summary_of(repo, "lane%d" % n)
        assert s["commits"] == n and s["subjects"] == ["m%d" % i for i in range(1, 9)] and s["more"] == want_more
    # the subjects: cut at 100 characters, control characters, an empty message, wrapped and several paragraphs
    fast_chain(repo, "subjects", [("x" * 150, {"a1": "1"}), ("y" * 100, {"a2": "1"}), ("z" * 101, {"a3": "1"}), ("tab\there\x1besc", {"a4": "1"}), ("", {"a5": "1"}),
                                  ("first line\nsecond line\n\nthe body", {"a6": "1"}), ("para one\n\npara two", {"a7": "1"}), ("  padded  \n", {"a8": "1"})])
    s = summary_of(repo, "subjects")
    assert s["subjects"] == ["x" * 99 + "…", "y" * 100, "z" * 99 + "…", "tab here esc", "(no subject)", "first line second line", "para one", "padded"]
    assert len(s["subjects"][0]) == 100 and s["commits"] == 8 and s["more"] == 0 and all(len(x) <= 100 for x in s["subjects"])
    # the path keys: the first two segments (a file in the root is itself), distinct, in the order of the first changed file, at most twelve
    files = {"README.md": "r\n", "src/x.py": "x\n", "src/y.py": "y\n", "src/api/deep/z.py": "z\n", "lib/a/b/c.py": "c\n"}
    files.update({"d%02d/x/%s.py" % (i, n): "x\n" for i in range(1, 16) for n in ("f", "g")})
    fast_chain(repo, "paths", [("many paths", files)])
    s = summary_of(repo, "paths")
    keys = []
    for p in sorted(files, key=lambda x: x.encode("utf-8")):
        key = "/".join(p.split("/")[:2])
        if key not in keys:
            keys.append(key)
    assert s["files"] == len(files) == 35 and s["paths"] == keys[:12] and s["paths_more"] == len(keys) - 12 and "src/api" in keys and "src/x.py" in keys and "README.md" in keys
    for n, (listed, more) in ((12, (12, 0)), (13, (12, 1))):  # exactly 12 and 13 distinct keys
        fast_chain(repo, "keys%d" % n, [("keys", {"k%02d/a.py" % i: "x\n" for i in range(n)})])
        s = summary_of(repo, "keys%d" % n)
        assert len(s["paths"]) == listed and s["paths_more"] == more and s["files"] == n
    # a name with spaces, quotes and non-ASCII characters is read exactly (core.quotepath is true in the configuration of the repository)
    odd = {"my dir/it's a " + chr(0xe9) + ".txt": "1\n", chr(0x65e5) + chr(0x672c) + "/" + chr(0x30d5) + chr(0x30a1) + ".txt": "2\n"}  # a double quote is no character of a path on Windows
    if os.name != "nt":
        odd['my dir/a "q" b.txt'] = "3\n"
    fast_chain(repo, "odd", [("odd names", odd)])
    s = summary_of(repo, "odd")
    assert sorted(s["paths"]) == sorted(odd) and s["files"] == len(odd) and s["insertions"] == len(odd)

def test_changes_summary_binary_rename_empty_and_merged_target(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, "r321", files=("README.md",))
    repo.git("config", "diff.renames", "copies")  # overridden by --find-renames
    for rel, text in (("src/api/a.py", "".join("a%d\n" % i for i in range(10))), ("src/api/c.py", "".join("c%d\n" % i for i in range(20))), ("tool.sh", "echo\n"),
                      ("five.txt", "1\n2\n3\n4\n5\n")):
        repo.write(rel, text)
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "base files")
    repo.git("branch", "empty-lane", "main")  # a lane with no commit: its branch is at the plan's base
    wt = tmp_path / "wt321"
    repo.git("worktree", "add", "-q", "-b", "work", str(wt), "main")
    (wt / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01")  # a NUL byte: binary
    repo.git("add", "img.png", cwd=wt)
    repo.git("mv", "src/api/a.py", "src/api/b.py", cwd=wt)  # unchanged rename
    repo.git("mv", "src/api/c.py", "src/api/d.py", cwd=wt)
    repo.write("src/api/d.py", "".join("c%d\n" % i for i in range(20)) + "n1\nn2\nn3\n", base=wt)  # renamed and three lines added
    repo.git("update-index", "--chmod=+x", "tool.sh", cwd=wt)  # only the mode changes
    repo.git("rm", "-q", "five.txt", cwd=wt)
    repo.write("empty.txt", "", base=wt)
    repo.write("-dash.txt", "d1\nd2\n", base=wt)
    repo.git("add", "-A", cwd=wt)
    repo.git("add", "--", "-dash.txt", cwd=wt)
    repo.git("commit", "-q", "-m", "everything at once", cwd=wt)
    s = summary_of(repo, "work")
    assert s["commits"] == 1 and s["subjects"] == ["everything at once"] and s["files"] == 7  # the binary file, two renames, the mode change, the deletion, the empty file, the dash file
    assert s["insertions"] == 3 + 2 and s["deletions"] == 5  # the renamed file adds 3, the dash file 2; the deletion removes 5; the binary and the mode change add no line
    assert set(s["paths"]) == {"img.png", "src/api", "tool.sh", "five.txt", "empty.txt", "-dash.txt"} and s["paths_more"] == 0
    numstat = {x.split("\t")[2]: x.split("\t")[:2] for x in repo.git("diff", "--numstat", "--no-renames", "main...work").splitlines()}
    assert numstat["img.png"] == ["-", "-"] and numstat["five.txt"] == ["0", "5"]  # what git itself says of the records
    # a lane with no commit stores zeros and runs no log
    calls = recorded_git(monkeypatch)
    assert summary_of(repo, "empty-lane") == EMPTY_SUMMARY
    assert [c[0] for c in summary_calls(calls)] == ["merge-base", "rev-list", "diff"]  # no log for an empty range
    calls.stop()
    # a lane that merged the target into itself is not charged with the target's files, and its merge commit is no lane commit (TC-330)
    repo.git("branch", "merged", "main")
    mwt = tmp_path / "wt321m"
    repo.git("worktree", "add", "-q", str(mwt), "merged")
    repo.commit("lane-only.txt", "l\n", cwd=mwt, msg="the lane's own file")
    repo.commit("README.md", "moved by the target\n", msg="the target moves on")
    repo.git("merge", "-q", "-m", "merge the target", "main", cwd=mwt)
    s = summary_of(repo, "merged")
    assert s["commits"] == 1 and s["subjects"] == ["the lane's own file"] and s["more"] == 0
    assert s["files"] == 1 and s["paths"] == ["lane-only.txt"] and s["insertions"] == 1


def test_integrated_changes_fail_closed(demo, guard, tmp_path, monkeypatch):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    _, head = start_lane(demo, tmp_path, "api", {"src/api/new.py": "n\n"}, msg="add the api")
    ready_lane(guard, demo, "api", head)
    integrate(demo, LANES["api"])
    args = update_args("api", "integrated", record(demo)["revision"], "--head", head, "--integration", INTEGRATION)
    rev = record(demo)["revision"]
    saved = record_file(demo).read_bytes()
    main_tip = demo.git("rev-parse", "main")

    def state():
        return (record_file(demo).read_bytes(), store_files(demo), len(audit_lines(demo)))

    def refused(rc_want, code=None, reason=None):
        """The call that cannot measure the summary: nothing is written and the lane stays ready."""
        before = state()
        rc, v = jcall(guard, demo, *args)
        assert rc == rc_want and v["decision"] == "deny" and v["exit_code"] == rc_want, v
        assert state() == before and lane_of(record(demo), "api")["state"] == "ready" and lane_of(record(demo), "api")["changes"] is None and record(demo)["revision"] == rev
        assert not list(store_dir(demo).rglob("*.tmp"))
        if code:
            assert v["unknowns"][0]["code"] == code, v
        if reason:
            assert v["blocked"] == [{"lane": "api", "reason": reason}], v
        return v

    def succeeds():
        """The same call once the cause is removed: it records the lane with its changes; the record is then put back for the next scenario."""
        rc, v = jcall(guard, demo, *args)
        assert rc == 0 and v["state"] == "integrated" and v["changes"]["commits"] == 1 and v["changes"]["subjects"] == ["add the api"], v
        record_file(demo).write_bytes(saved)
    # the target branch is gone (the head is an ancestor of the integration branch): exit 11, nothing to measure against
    demo.git("switch", "-q", "-c", "scratch")
    demo.git("branch", "-q", "-D", "main")
    v = refused(11, "TARGET_UNCERTAIN")
    assert v["unknowns"][0]["text"] == "the target branch main does not exist, so the summary of the changes of lane api cannot be computed" and set(v) == COMMON_KEYS | {"unknowns"}
    assert v["message"] == v["unknowns"][0]["text"]  # the message of this exit 11 is the text
    zh = run(["--repo", str(demo.path), "--lang", "zh", *args])
    assert zh.rc == 11 and zh.out.rstrip("\n") == "目标分支 main 不存在，无法计算 lane api 的改动摘要"
    demo.git("branch", "main", main_tip)
    succeeds()
    # a command that fails: exit 128 of merge-base is a failure (only exit 1 means no common history), also rev-list, log and diff, with and without stderr
    import contextlib
    real_run = subprocess.run

    @contextlib.contextmanager
    def git_gives(wanted, rc, stderr=b"", timeout=False):
        def fake(cmd, *a, **k):
            if isinstance(cmd, list) and cmd and cmd[0] == "git" and wanted(cmd):
                if timeout:
                    raise subprocess.TimeoutExpired(cmd, 1)
                return subprocess.CompletedProcess(cmd, rc, b"", stderr)
            return real_run(cmd, *a, **k)
        monkeypatch.setattr(subprocess, "run", fake)
        try:
            yield
        finally:
            monkeypatch.setattr(subprocess, "run", real_run)
    commands = {"merge-base": lambda c: "merge-base" in c and "--is-ancestor" not in c, "rev-list": lambda c: "rev-list" in c, "log": lambda c: "log" in c and "--format=%s" in c,
                "diff": lambda c: "diff" in c and "--numstat" in c}
    for name, wanted in commands.items():
        for stderr in (b"fatal: Not a valid object name", b""):
            with git_gives(wanted, 128, stderr):
                r = guard(demo, "--json", *args)
            v = json.loads(r.out)
            assert r.rc == 11 and v["unknowns"][0]["code"] == "GIT_FAILED" and r.err.replace("\r", "").startswith("MAGOS guard: GIT_FAILED: "), (name, r)
            assert name in v["unknowns"][0]["text"] and lane_of(record(demo), "api")["state"] == "ready" and record_file(demo).read_bytes() == saved
        with git_gives(wanted, 0, timeout=True):  # a timeout is the budget
            r = guard(demo, "--json", *args)
        assert r.rc == 11 and json.loads(r.out)["unknowns"][0]["code"] == "BUDGET_EXCEEDED" and record_file(demo).read_bytes() == saved, (name, r)
        succeeds()
    real = G.Git.run

    def exhausted(self, *a, **k):  # the budget runs out before the diff
        if a and a[0] == "diff" and "--numstat" in a:
            self.deadline = time.monotonic() - 1
        return real(self, *a, **k)
    monkeypatch.setattr(G.Git, "run", exhausted)
    r = guard(demo, "--json", *args)
    monkeypatch.setattr(G.Git, "run", real)
    assert r.rc == 11 and json.loads(r.out)["unknowns"][0]["code"] == "BUDGET_EXCEEDED" and record_file(demo).read_bytes() == saved
    assert len([x for x in audit_lines(demo) if x.get("state") == "integrated"]) == 5  # the five successes above are the only integrated lines: no refusal appended one
    succeeds()
    # no common history with the compare tip: exit 16 NO_MERGE_BASE (a branch of unrelated history merged into the integration branch, recorded ready by hand)
    orphan = demo.git("commit-tree", demo.git("mktree", inp=b""), "-m", "orphan")
    demo.git("branch", LANES["ui"], orphan)
    demo.git("switch", "-q", INTEGRATION)
    demo.git("merge", "-q", "--allow-unrelated-histories", "-m", "unrelated", LANES["ui"])
    demo.git("switch", "-q", "main")
    edit_record(demo, lambda rec: lane_of(rec, "ui").update(state="ready", head=orphan))
    ui_args = update_args("ui", "integrated", record(demo)["revision"], "--head", orphan, "--integration", INTEGRATION)
    before = state()
    rc, v = jcall(guard, demo, *ui_args)
    assert rc == 16 and v["blocked"] == [{"lane": "ui", "reason": "NO_MERGE_BASE"}] and set(v) == COMMON_KEYS | {"blocked"} and state() == before
    assert v["message"] == "MAGOS: set-update refused: lane ui shares no history with main, so the summary of its changes cannot be computed"
    zh = run(["--repo", str(demo.path), "--lang", "zh", *ui_args])
    assert zh.rc == 16 and "lane ui 与 main 没有共同历史，无法计算改动摘要" in zh.out
    edit_record(demo, lambda rec: lane_of(rec, "ui").update(state="planned", head=None))
    # a head that is already in main (the target fast-forwarded to the integration branch): measured against the plan's base, the real work and not zeros
    other = make_repo(tmp_path, "landed")
    own = demo_spec(other, tmp_path)
    for x in own["lanes"]:
        x["worktree"] = wt_path(tmp_path, x["id"], prefix="landed")  # the worktrees of this repository are not those of the first one
    plan_ok(guard, other, write_spec(tmp_path, own, "landed.json"))
    base = other.git("rev-parse", "main")
    other.git("branch", LANES["ui"], "main")  # a lane at the plan's base
    ready_lane(guard, other, "ui", base)
    _, api_head = start_lane(other, tmp_path, "api", {"src/api/new.py": "n\n", "src/api/n2.py": "n\n"}, msg="add the api", prefix="landed")
    ready_lane(guard, other, "api", api_head)
    integrate(other, LANES["api"])
    other.git("merge", "-q", "--ff-only", INTEGRATION)
    calls = recorded_git(monkeypatch)
    v = upd_ok(guard, other, "api", "integrated", "--head", api_head, "--integration", INTEGRATION)
    assert v["changes"] == {"commits": 1, "subjects": ["add the api"], "more": 0, "files": 2, "insertions": 2, "deletions": 0, "paths": ["src/api"], "paths_more": 0}
    assert ("rev-list", "--count", "--no-merges", "%s..%s" % (base, api_head)) in calls  # the plan's base is the compare tip
    calls.clear()
    v = upd_ok(guard, other, "ui", "integrated", "--head", base)
    assert v["changes"] == EMPTY_SUMMARY and "log" not in [c[0] for c in calls]  # a lane at the plan's base gives zeros


def test_changes_summary_lifecycle(demo, guard, tmp_path, monkeypatch):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, head = start_lane(demo, tmp_path, "api", {"src/api/new.py": "n\n"}, msg="add the api")
    ready_lane(guard, demo, "api", head)
    integrate(demo, LANES["api"])
    first = upd_ok(guard, demo, "api", "integrated", "--head", head, "--integration", INTEGRATION, "--note", "first")
    summary = first["changes"]
    assert summary["commits"] == 1 and summary["subjects"] == ["add the api"]
    stored = json.dumps(lane_of(record(demo), "api")["changes"], sort_keys=False)
    # a repeated integrated update replaces the note, keeps the summary byte for byte and runs none of the commands of the summary, also with the target gone
    calls = recorded_git(monkeypatch)
    v = upd_ok(guard, demo, "api", "integrated", "--head", head, "--note", "second")
    assert v["note"] == "second" and v["changes"] == summary and json.dumps(lane_of(record(demo), "api")["changes"]) == stored and summary_calls(calls) == []
    assert any(c[0] == "merge-base" and "--is-ancestor" in c for c in calls)  # the conditions of integrated are still tested
    main_tip = demo.git("rev-parse", "main")
    demo.git("switch", "-q", "-c", "scratch")
    demo.git("branch", "-q", "-D", "main")
    calls.clear()
    v = upd_ok(guard, demo, "api", "integrated", "--head", head, "--note", "third")
    assert v["note"] == "third" and json.dumps(lane_of(record(demo), "api")["changes"]) == stored and summary_calls(calls) == []
    demo.git("branch", "main", main_tip)
    calls.stop()
    real = G.Git.run

    def refuse_summary(self, *a, **k):
        if a and a[0] in SUMMARY_COMMANDS and "--is-ancestor" not in a:
            raise G.GitFail("GIT_FAILED", "the summary must not run: %s" % " ".join(a[:3]))
        return real(self, *a, **k)
    monkeypatch.setattr(G.Git, "run", refuse_summary)
    assert upd_ok(guard, demo, "api", "integrated", "--head", head, "--note", "fourth")["changes"] == summary  # Git.run raises on every command of the summary: none runs
    monkeypatch.setattr(G.Git, "run", real)
    # integrated to blocked: the summary is null in the record, in the result and in set-show
    v = upd_ok(guard, demo, "api", "blocked", "--note", "reopened")
    assert v["changes"] is None and lane_of(record(demo), "api")["changes"] is None
    shown = jshow(guard, demo)
    assert shown["record"]["lanes"][0]["changes"] is None and shown["view"]["lanes"][0]["changes"] is None
    # resumed, one more commit, ready at a new head and integrated again: a new summary that counts the new commit
    upd_ok(guard, demo, "api", "active")
    demo.commit("src/api/more.py", "m\n", cwd=wt, msg="one more commit")
    head2 = demo.git("rev-parse", LANES["api"])
    upd_ok(guard, demo, "api", "ready", "--head", head2)
    integrate(demo, LANES["api"], create=False)
    again = upd_ok(guard, demo, "api", "integrated", "--head", head2)
    assert again["changes"]["commits"] == 2 and again["changes"]["subjects"] == ["add the api", "one more commit"] and again["changes"]["files"] == 2
    kept = lane_of(record(demo), "api")["changes"]
    # an amend keeps the summary of a surviving lane while it replaces the outcome; a new lane has a null summary
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][0]["outcome"] = "a new outcome of the api"
    amend["lanes"].append(lane(tmp_path, "tools", ["tools/"], serves=["R1"]))
    v = plan_ok(guard, demo, write_spec(tmp_path, amend, "amend.json"), "--amend", "--expect-revision", str(record(demo)["revision"]))
    rec = record(demo)
    assert lane_of(rec, "api")["changes"] == kept and lane_of(rec, "api")["outcome"] == "a new outcome of the api" and lane_of(rec, "api")["state"] == "integrated"
    assert lane_of(rec, "tools")["changes"] is None and lane_of(rec, "ui")["changes"] is None and lane_of(rec, "docs")["state"] == "planned"
    # set-release removes the record together with its summary
    demo.git("switch", "-q", "main")
    demo.git("merge", "-q", "--ff-only", INTEGRATION)
    rc, v = jrelease(guard, demo, "--abandon", "--reason", "done")
    assert rc == 0 and not record_file(demo).exists()


def test_set_show_carries_the_requirements_and_the_changes(demo, guard, tmp_path, monkeypatch):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    _, api_head = start_lane(demo, tmp_path, "api", {"src/api/a2.py": "a\n", "tests/api/t2.py": "t\n"}, msg="add the api")
    _, ui_head = start_lane(demo, tmp_path, "ui", {"src/ui/u2.py": "u\n"}, msg="add the ui")
    ready_lane(guard, demo, "api", api_head)
    ready_lane(guard, demo, "ui", ui_head)
    integrate(demo, LANES["api"])
    upd_ok(guard, demo, "api", "integrated", "--head", api_head, "--integration", INTEGRATION)
    stored = lane_of(record(demo), "api")["changes"]
    calls = recorded_git(monkeypatch)
    v = jshow(guard, demo)
    calls.stop()
    assert [x["changes"] for x in v["record"]["lanes"]] == [stored, None, None]  # the stored object for api, null for the others
    assert [x["changes"] for x in v["view"]["lanes"]] == [stored, None, None]  # read from the record: no Git command computes it
    assert not [c for c in calls if c[0] == "log" or "--numstat" in c]
    assert v["view"]["requirements"] == [{"id": "R1", "text": REQUIREMENTS[0]["text"], "lanes": ["api"]}, {"id": "R2", "text": REQUIREMENTS[1]["text"], "lanes": ["ui"]},
                                         {"id": "R3", "text": REQUIREMENTS[2]["text"], "lanes": ["docs"]}]
    drift = jshow(guard, demo, "--drift")
    assert [x["changes"] for x in drift["view"]["lanes"]] == [stored, None, None] and "drift" in drift["view"] and list(drift["view"]["lanes"][0])[-3:] == ["changed", "out_of_lane", "moved_since_ready"]
    en = guard(demo, "set-show", "--set", "demo").out.splitlines()
    index = next(i for i, x in enumerate(en) if x.startswith("[x] api"))
    assert en[index + 1] == "    changes api: 1 commits, 2 files, +2/-0; paths src/api; tests/api; add the api" and not any(x.startswith("    changes") for x in en[index + 2:])
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo"]).out.splitlines()
    index = next(i for i, x in enumerate(zh) if x.startswith("[x] api"))
    assert zh[index + 1] == "    改动 api：1 个提交，2 个文件，+2/-0；路径 src/api; tests/api；add the api"
    # a summary with 12 commits not listed and 3 paths not listed, an empty summary, and an integrated lane whose summary is null
    big = {"commits": 20, "subjects": ["s%d" % i for i in range(1, 9)], "more": 12, "files": 40, "insertions": 100, "deletions": 7, "paths": ["p%d" % i for i in range(1, 13)], "paths_more": 3}
    edit_record(demo, lambda rec: (lane_of(rec, "api").update(changes=big), lane_of(rec, "ui").update(state="integrated", head=ui_head, changes=EMPTY_SUMMARY),
                                   lane_of(rec, "docs").update(state="integrated", head=demo.git("rev-parse", "main"), changes=None)))
    en = guard(demo, "set-show", "--set", "demo").out.splitlines()
    api_line = en[next(i for i, x in enumerate(en) if x.startswith("[x] api")) + 1]
    assert api_line == "    changes api: 20 commits, 40 files, +100/-7; paths " + "; ".join("p%d" % i for i in range(1, 13)) + "; +3 more; " + "; ".join("s%d" % i for i in range(1, 9)) + "; +12 more"
    ui_line = en[next(i for i, x in enumerate(en) if x.startswith("[x] ui")) + 1]
    assert ui_line == "    changes ui: 0 commits, 0 files, +0/-0; paths -; -"  # an empty list reads -
    docs_at = next(i for i, x in enumerate(en) if x.startswith("[x] docs"))
    assert docs_at == len(en) - 1 or not en[docs_at + 1].startswith("    changes")  # no line for an integrated lane whose summary is null
    zh = run(["--repo", str(demo.path), "--lang", "zh", "set-show", "--set", "demo"]).out
    assert "另有 3 项" in zh and "另有 12 项" in zh
    snapshot, audits = store_files(demo), len(audit_lines(demo))
    jshow(guard, demo, "--drift")
    guard(demo, "set-show", "--set", "demo")
    assert store_files(demo) == snapshot and len(audit_lines(demo)) == audits and not [x for x in audit_lines(demo) if x["op"] == "set-show"]  # set-show writes nothing


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


# ---- TC-325 .. TC-333: the drift of the set's own work, equal entries, the creation example, the texts and the non-merge commits ----------------
def drift_log(tip, *negatives):
    """The one Git command of the drift of the target (set-show, The target's own changes), as Git.run receives it."""
    return ("log", "--no-show-signature", "-z", "--format=", "--name-only", "--no-renames", "--diff-merges=dense-combined", "--ignore-missing", tip, "--not",
            *negatives)


def drift_calls(guard, repo, monkeypatch):
    """`set-show --drift --json` with the Git calls recorded -> (the result, the `log` commands it ran); set-show writes nothing."""
    before, audits = store_files(repo), len(audit_lines(repo))
    calls = recorded_git(monkeypatch)
    try:
        v = jshow(guard, repo, "--drift")
    finally:
        calls.stop()
    assert store_files(repo) == before and len(audit_lines(repo)) == audits
    return v, [c for c in calls if c[0] == "log"]


def merge_into(repo, branch, other, msg):
    """The merge of `other` into the local branch `branch` that a lane owner makes with `merge --no-ff`, in plumbing (no worktree): the tree that
    `merge-tree --write-tree` gives, committed with both parents -> the merge commit, now the tip of `branch`."""
    ours = repo.git("rev-parse", "refs/heads/" + branch)
    tree = repo.git("merge-tree", "--write-tree", ours, other).splitlines()[0]
    commit = repo.git("commit-tree", tree, "-p", ours, "-p", other, "-m", msg)
    repo.git("update-ref", "refs/heads/" + branch, commit)
    return commit


def test_drift_leaves_out_the_sets_own_land(demo, guard, tmp_path, monkeypatch):
    spec = demo_spec(demo, tmp_path)
    base = spec["base"]
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    v, logs = drift_calls(guard, demo, monkeypatch)  # the target at the base: no log runs
    assert (v["view"]["target_moved"], v["view"]["drift"]["target_overlap"], v["view"]["drift"]["stale"], logs) == (False, [], False, [])
    heads = {lid: fast_commit(demo, LANES[lid], {path: lid + "\n"}) for lid, path in (("api", "src/api/n.py"), ("ui", "src/ui/n.py"), ("docs", "docs/n.md"))}
    demo.commit("src/ui/layout.py", "t1\n", msg="T1")  # the target moves past the base on a file of ui
    for lid in ("api", "ui", "docs"):
        ready_lane(guard, demo, lid, heads[lid])
    integrate(demo, LANES["api"], LANES["ui"], LANES["docs"])  # the integration branch is cut from T1 and holds it
    upd_ok(guard, demo, "api", "integrated", "--head", heads["api"], "--integration", INTEGRATION)
    for lid in ("ui", "docs"):
        upd_ok(guard, demo, lid, "integrated", "--head", heads[lid])
    itip = demo.git("rev-parse", INTEGRATION)

    def own_work_only(repo):
        """The drift after a land: the target moved, nothing of the set's own work counts, one log with the base, the integration tip and the heads."""
        v, logs = drift_calls(guard, repo, monkeypatch)
        assert v["view"]["target_moved"] is True and v["view"]["drift"]["target_overlap"] == [] and v["view"]["drift"]["stale"] is False, v["view"]["drift"]
        assert logs == [drift_log(repo.git("rev-parse", "main"), base, itip, heads["api"], heads["ui"], heads["docs"])], logs
    own_work_only(demo)  # before the land, T1 is held by the integration branch
    ff = SetsRepo(tmp_path / "landed-ff")  # one copy of the repository lands by a fast-forward
    shutil.copytree(str(demo.path), str(ff.path))
    ff.git("merge", "-q", "--ff-only", INTEGRATION)
    assert ff.git("rev-parse", "main") == itip
    own_work_only(ff)
    demo.git("merge", "-q", "--no-ff", "-m", "land the set", INTEGRATION)  # the other lands by a merge, which is listed by its own changes alone
    own_work_only(demo)
    tip_args = [base, itip, heads["api"], heads["ui"], heads["docs"]]

    def overlap():
        v, logs = drift_calls(guard, demo, monkeypatch)
        assert logs == [drift_log(demo.git("rev-parse", "main"), *tip_args)] and v["view"]["drift"]["stale"] is True
        return v["view"]["drift"]["target_overlap"]
    demo.commit("docs/a.md", "a\n", msg="docs on the target")
    assert overlap() == [{"path": "docs/a.md", "lanes": ["docs"]}]
    demo.git("switch", "-q", "-c", "feature/x")
    demo.commit("src/api/z.py", "z\n", msg="feature x")
    demo.git("switch", "-q", "main")
    demo.git("merge", "-q", "--no-ff", "-m", "merge feature/x", "feature/x")  # the commit of the merged branch counts, its merge adds nothing
    assert overlap() == [{"path": "docs/a.md", "lanes": ["docs"]}, {"path": "src/api/z.py", "lanes": ["api"]}]
    demo.git("switch", "-q", "-c", "feature/y")
    demo.commit("README.md", "y\n", msg="feature y")
    demo.git("switch", "-q", "main")
    demo.git("merge", "-q", "--no-ff", "--no-commit", "feature/y")
    demo.write("src/ui/evil.py", "e\n")  # the merge's own change
    demo.git("add", "-A")
    demo.git("commit", "-q", "-m", "merge feature/y with a change of its own")
    assert overlap() == [{"path": "docs/a.md", "lanes": ["docs"]}, {"path": "src/api/z.py", "lanes": ["api"]}, {"path": "src/ui/evil.py", "lanes": ["ui"]}]


def test_drift_excludes_by_reachability_from_ready_and_integrated_heads(demo, guard, tmp_path, monkeypatch):
    spec = demo_spec(demo, tmp_path)
    base = spec["base"]
    plan_ok(guard, demo, write_spec(tmp_path, spec))
    fast_commit(demo, LANES["ui"], {"src/ui/own.py": "u\n"})
    fast_commit(demo, LANES["api"], {"src/api/own.py": "a\n"})
    demo.write("src/ui/a.py", "t\n")
    demo.write("docs/b.md", "t\n")
    demo.git("add", "-A")
    demo.git("commit", "-q", "-m", "T")
    ui_head = merge_into(demo, LANES["ui"], demo.git("rev-parse", "main"), "the owner of ui merges the target")
    ready_lane(guard, demo, "ui", ui_head)
    demo.commit("src/api/c.py", "u\n", msg="U")
    api_head = merge_into(demo, LANES["api"], demo.git("rev-parse", "main"), "the owner of api merges the target")
    ready_lane(guard, demo, "api", api_head)
    upd_ok(guard, demo, "api", "active")  # back to active: the head of ready is kept, and it is no negative revision
    assert lane_of(record(demo), "api")["head"] == api_head
    upd_ok(guard, demo, "docs", "blocked")
    demo.commit("docs/v.md", "v\n", msg="V")  # no lane holds it
    tip = demo.git("rev-parse", "main")
    v, logs = drift_calls(guard, demo, monkeypatch)
    # T is left out for every lane, docs/b.md of docs included; U (held by an active lane only) and V count
    assert v["view"]["drift"]["target_overlap"] == [{"path": "docs/v.md", "lanes": ["docs"]}, {"path": "src/api/c.py", "lanes": ["api"]}], v["view"]["drift"]
    assert v["view"]["drift"]["stale"] is True and v["view"]["target_moved"] is True
    assert logs == [drift_log(tip, base, ui_head)]  # the base and the head of the ready lane only: no integration tip, no head of api or docs
    saved = record_file(demo).read_bytes()
    edit_record(demo, lambda rec: lane_of(rec, "ui").update(head="e" * 40))  # a head that names no object excludes nothing
    v, logs = drift_calls(guard, demo, monkeypatch)
    assert logs == [drift_log(tip, base, "e" * 40)] and v["exit_code"] == 0
    assert v["view"]["drift"]["target_overlap"] == [{"path": "docs/b.md", "lanes": ["docs"]}, {"path": "docs/v.md", "lanes": ["docs"]},
                                                    {"path": "src/api/c.py", "lanes": ["api"]}, {"path": "src/ui/a.py", "lanes": ["ui"]}]
    record_file(demo).write_bytes(saved)
    edit_record(demo, lambda rec: rec.update(base="d" * 40))  # a base that names no object excludes nothing either: never an empty listing
    v, logs = drift_calls(guard, demo, monkeypatch)
    assert logs == [drift_log(tip, "d" * 40, ui_head)] and v["exit_code"] == 0 and v["view"]["drift"]["stale"] is True
    assert v["view"]["drift"]["target_overlap"] == [{"path": "docs/v.md", "lanes": ["docs"]}, {"path": "src/api/c.py", "lanes": ["api"]}]  # the head of ui holds T and the history before the base
    record_file(demo).write_bytes(saved)
    odd = ["src/ui/a b.py", "src/ui/café.py"] + (["src/ui/new\nline.py"] if os.name != "nt" else [])  # a newline is no character of a Windows name
    for rel in odd:
        demo.write(rel, "w\n")
    demo.git("add", "-A")
    demo.git("commit", "-q", "-m", "odd names")
    v, _ = drift_calls(guard, demo, monkeypatch)
    listed = {x["path"]: x["lanes"] for x in v["view"]["drift"]["target_overlap"]}
    assert all(listed.get(rel) == ["ui"] for rel in odd), listed  # read exactly (-z)


def test_equal_entries_of_one_manifest_are_refused(demo, guard, tmp_path):
    def with_paths(paths, docs=None):
        s = demo_spec(demo, tmp_path)
        s["lanes"][0]["paths"] = list(paths) + ["package-lock.json"]  # the shared file stays inside its owner
        if docs:
            s["lanes"][2]["paths"] = docs
        return s

    def refused(paths, want):
        f = write_spec(tmp_path, with_paths(paths), "dup.json")
        lines = [("lanes[0].paths[%d]" % j, "DUPLICATE", "the entry equals lanes[0].paths[%d] after normalisation" % k) for j, k in want]
        for extra in (("--dry-run",), ()):
            rc, v = jplan(guard, demo, f, *extra)
            assert rc == 24 and v["code"] == "INVALID_SPEC" and [(e["field"], e["code"], e["text"]) for e in v["errors"]] == lines, (paths, extra, v)
            assert store_files(demo) is None  # nothing is written, and the first entry raises nothing
            for lang in ("zh", "en"):  # the text is English in both languages
                text = run(["--repo", str(demo.path), "--lang", lang, *sp_args(f, "demo", "main", *extra)]).out
                assert all("  [%s] %s: %s" % (code, field, why) in text for field, code, why in lines), (lang, text)
    nfd, nfc = unicodedata.normalize("NFD", "src/api/café.py"), unicodedata.normalize("NFC", "src/api/café.py")
    for a, b in (("src/api/", "src\\api\\"), ("Src/Api/x.py", "src/api/x.py"), (nfd, nfc), ("src/api/x.py", " src/api/x.py ")):
        refused([a, b], [(1, 0)])
    refused(["src/a/", "src/b/", "src/a/", "./src//a/"], [(2, 0), (3, 0)])  # three equal entries: each later one names the first
    # the same entry in two lanes is the pairwise overlap, not DUPLICATE
    rc, v = dry(guard, demo, tmp_path, with_paths(["src/api/", "docs/x.md"], docs=["docs/x.md"]), "two.json")
    assert rc == 10 and v["code"] == "CONFLICT" and "errors" not in v and {v["overlaps"][0]["a"], v["overlaps"][0]["b"]} == {"api", "docs"}, v
    assert ["docs/x.md", "docs/x.md"] in v["overlaps"][0]["entries"]
    # distinct entries: one record entry, one claim line and one result entry per entry of the spec, in its order
    want = ["src/api/", "tests/api/", "src/apix.py", "package-lock.json"]
    v = plan_ok(guard, demo, write_spec(tmp_path, with_paths(want[:3]), "distinct.json"))
    assert v["lanes"][0]["entries"] == want and lane_of(record(demo), "api")["paths"] == want
    assert [x[6:] for x in claim_lines(demo, LANES["api"]) if x.startswith("entry=")] == want


def test_set_plan_success_creates_the_example_lane_from_the_base(tmp_path, guard):
    import shlex
    odd = P(tmp_path / "it's here" / "repo-demo-api")

    def spec_file(r, name, docs=None):
        s = demo_spec(r, tmp_path)
        s["lanes"][0]["worktree"] = odd  # under a directory whose name holds a space and an apostrophe
        if docs:
            s["lanes"][2]["paths"] = docs
        return write_spec(tmp_path, s, name + ".json")

    def fresh(name):
        r = make_repo(tmp_path, name)
        return r, spec_file(r, name)
    words = {"zh": "现在可以从基线逐个创建 lane，例如：", "en": "You may now create the lanes from the base, e.g.: "}
    for how in ("zh", "en", "json"):
        r, f = fresh("r328" + how)
        base = r.git("rev-parse", "main")
        if how == "json":
            v = plan_ok(guard, r, f)
            message, lang = v["message"], "en"
            assert [x["create"] for x in v["lanes"]] == ['git worktree add "%s" -b %s main' % (x["worktree"], x["branch"]) for x in v["lanes"]]  # the create key as before
        else:
            out = run(["--repo", str(r.path), "--lang", how, *sp_args(f)])
            assert out.rc == 0, out
            message, lang = out.out.rstrip("\n"), how
        stored = lane_of(record(r), "api")["worktree"]
        example = "git worktree add '%s' -b 'agent/demo/api' '%s'" % (stored.replace("'", "'\\''"), base)
        head = message.split("\n")[0]
        assert head == G.T(lang, "set_ok_plan", s="demo", n=3, t="main", base=base, rev=1, example=example) and head.endswith(words[lang] + example), head
        assert "'\\''" in example and shlex.split(example) == ["git", "worktree", "add", stored, "-b", "agent/demo/api", base]
        assert "main" not in example and base in head  # the example cuts the lane from the base, never from the target
    r, f = fresh("r328amend")
    plan_ok(guard, r, f)
    v = plan_ok(guard, r, spec_file(r, "r328amend2", docs=["docs/", "notes/"]), "--amend", "--expect-revision", "1")
    assert v["message"].split("\n")[0] == G.T("en", "set_ok_amend", s="demo", old=1, rev=2, n=3) and "git worktree add" not in v["message"]
    r, f = fresh("r328dry")
    v = plan_ok(guard, r, f, "--dry-run")
    assert v["message"].split("\n")[0] == G.T("en", "set_ok_check", s="demo") and "git worktree add" not in v["message"]


def test_reserved_id_text_asks_for_a_topic_without_an_example(demo, guard, tmp_path):
    asks = {"zh": "请另选一个说明这个 lane 改动内容的主题 slug。", "en": "Choose another topic slug that names what the lane changes."}
    devices = {"zh": "Windows 设备名", "en": "Windows device names"}
    examples = ("integration-docs", "claim-store", "sweep-readiness", "readme-gitplan", "例如", "for example", "e.g.")
    for lid in ("integration", "Integration", "con", "Aux", "lpt9"):
        f = write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, lid, ["src/api/"])]), "reserved.json")
        for lang in ("zh", "en"):
            args = ["--repo", str(demo.path), "--lang", lang, *sp_args(f, "demo", "main", "--dry-run")]
            v = json.loads(run(args[:4] + ["--json"] + args[4:]).out)
            text = run(args).out
            assert v["exit_code"] == 24 and [(e["field"], e["code"]) for e in v["errors"]] == [("lanes[0].id", "RESERVED")], (lid, v)
            t = v["errors"][0]["text"]
            assert t == G.T(lang, "set_err_reserved_id", id=lid) and "  [RESERVED] lanes[0].id: " + t in text
            assert lid in t and "agent/<set>/integration" in t and devices[lang] in t and t.endswith(asks[lang]), t
            assert not any(x in t for x in examples), t  # no fixed name fits the topic of every lane
    assert not store_dir(demo).exists()


def test_changes_summary_counts_non_merge_commits(demo, guard, tmp_path, monkeypatch):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, _ = start_lane(demo, tmp_path, "ui", {"src/ui/a.py": "a\n"}, msg="ui one")
    demo.commit("src/ui/b.py", "b\n", cwd=wt, msg="ui two")
    demo.commit("src/api/m.py", "m\n", msg="the target moves")
    demo.git("merge", "-q", "--no-ff", "-m", "merge the target into ui", "main", cwd=wt)  # the owner takes the moved target tip
    demo.commit("src/ui/c.py", "c\n", cwd=wt, msg="ui three")
    head = demo.git("rev-parse", LANES["ui"])
    ready_lane(guard, demo, "ui", head)
    integrate(demo, LANES["ui"])
    main_tip = demo.git("rev-parse", "main")
    calls = recorded_git(monkeypatch)
    v = upd_ok(guard, demo, "ui", "integrated", "--head", head, "--integration", INTEGRATION)
    calls.stop()
    assert v["changes"] == {"commits": 3, "subjects": ["ui one", "ui two", "ui three"], "more": 0, "files": 3, "insertions": 3, "deletions": 0, "paths": ["src/ui"],
                            "paths_more": 0}, v["changes"]  # the net diff does not charge the lane with src/api/m.py
    rng = "%s..%s" % (main_tip, head)
    assert summary_calls(calls) == [("merge-base", main_tip, head), ("rev-list", "--count", "--no-merges", rng),
                                    ("log", "--no-show-signature", "--encoding=UTF-8", "--format=%s", "--reverse", "--no-merges", "--skip=0", "--max-count=8", rng),
                                    ("diff", "--numstat", "-z", "--find-renames", "--no-ext-diff", "--no-textconv", "%s...%s" % (main_tip, head), "--")]
    assert audit_lines(demo)[-1]["changes"] == {"commits": 3, "files": 3, "insertions": 3, "deletions": 0}
    # further lanes of another repository, each cut from its base
    r = make_repo(tmp_path, "r330", files=("README.md", "src/ui/u.py"))
    base = r.git("rev-parse", "main")

    def lane_wt(name):
        wt = tmp_path / ("wt330-" + name)
        r.git("worktree", "add", "-q", "-b", name, str(wt), base)
        return wt
    nine = lane_wt("nine")
    for i in range(1, 5):
        r.commit("src/ui/o%d.py" % i, "%d\n" % i, cwd=nine, msg="o%d" % i)
    r.commit("src/api/x1.py", "x1\n", msg="X1")
    first = lane_wt("first")  # its first commit is the merge of the target tip
    r.git("merge", "-q", "--no-ff", "-m", "merge X1 first", "main", cwd=first)
    r.commit("src/ui/own.py", "own\n", cwd=first, msg="own")
    plain = lane_wt("plain")  # its only commit is a plain merge of the target tip
    r.git("merge", "-q", "--no-ff", "-m", "plain merge", "main", cwd=plain)
    evil = lane_wt("evil")  # its only commit is a merge with a change of its own
    r.git("merge", "-q", "--no-ff", "--no-commit", "main", cwd=evil)
    r.write("src/ui/evil.py", "e\n", base=evil)
    r.git("add", "-A", cwd=evil)
    r.git("commit", "-q", "-m", "merge with a change of its own", cwd=evil)
    r.git("merge", "-q", "--no-ff", "-m", "merge X1", "main", cwd=nine)
    for i in range(5, 8):
        r.commit("src/ui/o%d.py" % i, "%d\n" % i, cwd=nine, msg="o%d" % i)
    r.commit("src/api/x2.py", "x2\n", msg="X2")
    r.git("merge", "-q", "--no-ff", "-m", "merge X2", "main", cwd=nine)
    for i in (8, 9):
        r.commit("src/ui/o%d.py" % i, "%d\n" % i, cwd=nine, msg="o%d" % i)
    s = summary_of(r, "first")
    assert (s["commits"], s["subjects"], s["more"], s["files"], s["paths"]) == (1, ["own"], 0, 1, ["src/ui"]), s
    calls = recorded_git(monkeypatch)
    assert summary_of(r, "plain") == EMPTY_SUMMARY
    assert [c[0] for c in summary_calls(calls)] == ["merge-base", "rev-list", "diff"]  # no log when every commit of the range is a merge
    calls.stop()
    s = summary_of(r, "evil")
    assert (s["commits"], s["subjects"], s["more"], s["files"], s["insertions"], s["paths"]) == (0, [], 0, 1, 1, ["src/ui"]), s
    calls = recorded_git(monkeypatch)
    s = summary_of(r, "nine")
    calls.stop()
    assert (s["commits"], s["subjects"], s["more"]) == (9, ["o%d" % i for i in range(1, 9)], 1), s
    logs = [c for c in summary_calls(calls) if c[0] == "log"]
    assert len(logs) == 1 and logs[0][5:8] == ("--no-merges", "--skip=1", "--max-count=8"), logs


def test_set_name_refusal_is_localized_and_framed_by_its_subcommand(demo, guard, tmp_path):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    frames = {"zh": ("MAGOS：参数无效，未做任何修改：", "MAGOS：set 规划无效，未登记也未创建任何东西："),
              "en": ("MAGOS: invalid arguments, nothing was changed:", "MAGOS: the set plan is invalid, nothing registered or created:")}
    def named(lang, name):
        """The refusal of the set name `name` in `lang` (set_err_set_name, or set_err_set_device for a device name), written out."""
        if name in ("con", "nul"):
            return {"zh": "set 名称「%s」是 Windows 设备名，不能用作记录文件 sets/%s.json 的名称。请另选一个说明任务主题的名称。",
                    "en": "the set name '%s' is a Windows device name and cannot name the record file sets/%s.json. Choose another name that names the topic of the task."}[lang] % (name, name)
        return {"zh": "set 名称「%s」无效：必须匹配 [a-z0-9][a-z0-9-]{0,23}（小写字母、数字、连字符，1 到 24 个字符，不以连字符开头），并说明任务的主题。",
                "en": "the set name '%s' is invalid: it must match [a-z0-9][a-z0-9-]{0,23} (lowercase letters, digits and hyphens, 1 to 24 characters, not starting with "
                      "a hyphen) and name the topic of the task."}[lang] % name
    calls = [(["set-plan", "--set", "Order_Totals", "--target", "main", "--spec", str(f), "--dry-run"], "Order_Totals", True),
             (["set-show", "--set", "Order_Totals"], "Order_Totals", False),
             (["set-update", "--set", "Order_Totals", "--expect-revision", "1", "--lane", "api", "--state", "active"], "Order_Totals", False),
             (["set-release", "--set", "con"], "con", False), (["set-show", "--set", "nul", "--drift"], "nul", False)]
    for args, name, plan in calls:
        for lang in ("zh", "en", None):
            flag, shown = (["--lang", lang] if lang else []), lang or "zh"  # the default language is zh
            want = named(shown, name)
            r = run(["--repo", str(demo.path), "--json", *flag, *args])
            v = json.loads(r.out)
            assert r.rc == 24 and v["code"] == "INVALID_SPEC" and v["errors"] == [{"field": "--set", "code": "FORMAT", "text": want}], (args, lang, v)
            text = run(["--repo", str(demo.path), *flag, *args]).out.rstrip("\n")
            assert text.split("\n") == [frames[shown][1 if plan else 0], "  [FORMAT] --set: " + want] and v["message"] == text, (args, lang, text)
            if not plan:  # the neutral frame names no plan, in either language
                assert frames["zh"][1] not in text + r.out and frames["en"][1] not in text + r.out
            assert want == (G.T(shown, "set_err_set_device", s=name) if name in ("con", "nul") else G.T(shown, "set_err_set_name", s=name, rule=G.SLUG_RULE))
    for lang in ("zh", "en"):  # two errors of one call are two lines of one denial
        v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", "set-update", "--set", "Bad", "--head", "abc", "--expect-revision", "1", "--lane", "api",
                            "--state", "ready"]).out)
        lines = v["message"].split("\n")
        assert [(e["field"], e["code"]) for e in v["errors"]] == [("--set", "FORMAT"), ("--head", "FORMAT")] and v["exit_code"] == 24
        assert lines[0] == frames[lang][0] and len(lines) == 3 and lines[1] == "  [FORMAT] --set: " + named(lang, "Bad")
        v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", "set-release", "--set", "Bad", "--reason", "r" * 201]).out)
        assert [(e["field"], e["code"]) for e in v["errors"]] == [("--set", "FORMAT"), ("--reason", "RANGE")] and v["message"].split("\n")[0] == frames[lang][0]
    assert store_files(demo) in (None, {})
    plan_ok(guard, demo, f)  # the refusals of set-update under the lock: an unknown lane and a refused transition
    before = store_files(demo)
    for lang in ("zh", "en"):
        for args, field, code in ((update_args("nope", "active", 1), "--lane", "UNKNOWN_LANE"), (update_args("api", "ready", 1, "--head", demo.git("rev-parse", "main")), "--state", "STATE")):
            v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", *args]).out)
            assert v["exit_code"] == 24 and [(e["field"], e["code"]) for e in v["errors"]] == [(field, code)] and v["message"].split("\n")[0] == frames[lang][0], v
    assert store_files(demo) == before


def test_unserved_text_serves_the_requirement_and_never_drops_it(demo, guard, tmp_path):
    s = demo_spec(demo, tmp_path)
    s["requirements"].append({"id": "R4", "text": "Document the total of the cart UI."})
    f = write_spec(tmp_path, s, "unserved.json")
    texts = {"en": "requirement R4 (Document the total of the cart UI.) is served by no lane. Serve it with a lane: add R4 to the serves of a lane, or add a lane for it. "
                   "Never drop a requirement the user stated.",
             "zh": "需求 R4（Document the total of the cart UI.）没有任何 lane 负责。请用一个 lane 负责它：把 R4 加入某个 lane 的 serves，或为它新增一个 lane。不要删除用户提出的需求。"}
    for lang, want in texts.items():
        assert want == G.T(lang, "set_err_unserved", r="R4", t="Document the total of the cart UI.")
        assert not any(x in want for x in ("remove the requirement", "或删除这条需求"))  # no deletion is offered
        for extra in (("--dry-run",), ()):
            v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", *sp_args(f, "demo", "main", *extra)]).out)
            assert v["exit_code"] == 24 and [(e["field"], e["code"], e["text"]) for e in v["errors"]] == [("requirements[3]", "UNSERVED", want)], v
            assert "  [UNSERVED] requirements[3]: " + want in run(["--repo", str(demo.path), "--lang", lang, *sp_args(f, "demo", "main", *extra)]).out
    assert store_files(demo) in (None, {})


def test_dry_run_and_out_of_lane_texts(demo, guard, tmp_path):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    check = {"zh": "MAGOS：set「demo」的预览通过，没有发现重叠；这是 --dry-run，未写入任何东西。",
             "en": "MAGOS: the preview of set 'demo' passed, no overlap found; this was a --dry-run and nothing was written."}

    def heads_of(args):
        out = {}
        for lang in ("zh", "en"):
            r = run(["--repo", str(demo.path), "--lang", lang, *args])
            v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", *args]).out)
            assert r.rc == 0 and v["dry_run"] is True and v["message"] == r.out.rstrip("\n"), (args, r, v)
            out[lang] = r.out.split("\n")[0]
        return out
    first = heads_of(sp_args(f, "demo", "main", "--dry-run"))
    assert first == check and not any(x in first["zh"] + first["en"] for x in ("not registered", "未登记"))
    plan_ok(guard, demo, f)
    amend = demo_spec(demo, tmp_path)
    amend["lanes"][2]["paths"] = ["docs/", "notes/"]
    assert heads_of(sp_args(write_spec(tmp_path, amend, "amend.json"), "demo", "main", "--amend", "--expect-revision", "1", "--dry-run")) == check  # the same text for the registered set
    tip = fast_commit(demo, LANES["api"], {"src/ui/x.py": "x\n"})
    upd_ok(guard, demo, "api", "active")
    args = update_args("api", "ready", record(demo)["revision"], "--head", tip)
    texts = {"en": "MAGOS: refused to mark lane api ready: these files lie outside its manifest: src/ui/x.py. Revert them in the lane, or amend the plan with /GitPlan demo --amend.",
             "zh": "MAGOS：拒绝把 lane api 标记为 ready：下列文件在它的 manifest 之外：src/ui/x.py。请在该 lane 中撤销这些改动，或用 /GitPlan demo --amend 修改计划。"}
    before = record_file(demo).read_bytes()
    for lang, want in texts.items():
        r = run(["--repo", str(demo.path), "--lang", lang, *args])
        v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", *args]).out)
        assert r.rc == 22 and r.out.rstrip("\n") == want and v["message"] == want and v["code"] == "OUT_OF_LANE" and v["files"] == ["src/ui/x.py"], (lang, r, v)
        assert "set-plan" not in want  # the way forward is the command that changes a set, not a guard subcommand
    assert record_file(demo).read_bytes() == before


# ---- TC-334 .. TC-345: the reason and the audit line, detached and missing lane worktrees, the record's revisions, worktree spellings, the
# pairwise index ------------------------------------------------------------------------------------------------------------------------------
def test_set_release_refuses_a_reason_it_cannot_record(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    before = store_files(demo)
    for reason, code in (("caf\udcff", "ENCODING"), ("two\nlines", "FORMAT"), ("a\ttab", "FORMAT"), ("r" * 201, "RANGE")):
        for lang in ("zh", "en"):
            args = ["set-release", "--set", "demo", "--abandon", "--reason", reason]
            v = json.loads(run(["--repo", str(demo.path), "--lang", lang, "--json", *args]).out)
            assert v["exit_code"] == 24 and [(e["field"], e["code"]) for e in v["errors"]] == [("--reason", code)], (reason, v)
            assert v["message"].startswith(G.T(lang, "set_invalid_args", errors="").rstrip("\n")), v["message"]
            assert run(["--repo", str(demo.path), "--lang", lang, *args]).rc == 24
            assert store_files(demo) == before  # the record, every claim and audit.log as they were
    v = json.loads(run(["--repo", str(demo.path), "--lang", "en", "--json", "set-release", "--set", "Bad", "--reason", "caf\udcff"]).out)
    assert v["exit_code"] == 24 and errors_of(v) == {("--set", "FORMAT"), ("--reason", "ENCODING")}, v  # one denial for both
    rc, v = jrelease(guard, demo, "--abandon", "--reason", "r" * 200)
    assert rc == 0 and audit_lines(demo)[-1]["op"] == "set-release" and audit_lines(demo)[-1]["reason"] == "r" * 200, v


def test_the_audit_line_is_built_before_the_write(demo, guard, tmp_path, monkeypatch):
    f = write_spec(tmp_path, demo_spec(demo, tmp_path))
    real_who, real_line = G.who, G.audit_line

    def no_user(g):
        raise G.GitFail("BUDGET_EXCEEDED", "time budget exhausted")

    def no_line(g, by=None, **rec):
        raise UnicodeEncodeError("utf-8", "caf\udcff", 3, 4, "surrogates not allowed")

    def calls():
        yield lambda: jplan(guard, demo, f)
        yield lambda: upd(guard, demo, "api", "active")
        yield lambda: jrelease(guard, demo, "--abandon")
    for step, call in enumerate(calls()):
        for name, fake in (("who", no_user), ("audit_line", no_line)):
            before = store_files(demo) or {}
            with monkeypatch.context() as m:
                m.setattr(G, name, fake)
                rc, v = call()
            assert rc == 11 and v["code"] == "UNKNOWN" and (store_files(demo) or {}) == before, (step, name, v)  # nothing was written
        lines = len(audit_lines(demo))
        with monkeypatch.context() as m:
            def full_disk(g, line):
                raise OSError(28, "No space left on device")
            m.setattr(G, "append_audit", full_disk)
            rc, v = call()
        assert rc == 0 and v["code"] == "OK", (step, v)  # the change is made and is reported as made
        warn = [w for w in v["warnings"] if w["code"] == "AUDIT_NOT_WRITTEN"]
        assert len(warn) == 1 and "No space left on device" in warn[0]["text"] and "(AUDIT_NOT_WRITTEN)" in v["message"], (step, v)
        assert len(audit_lines(demo)) == lines
        if step == 0:
            assert record(demo)["revision"] == 1 and claim_lines(demo, LANES["api"])[0] == "state=active"
        elif step == 1:
            assert lane_of(record(demo), "api")["state"] == "active" and record(demo)["revision"] == 2
        else:
            assert not record_file(demo).exists() and not (store_dir(demo) / "claims" / "agent" / "demo" / "api.claim").exists()
    assert G.who is real_who and G.audit_line is real_line


def test_amend_judges_the_detached_worktree_of_a_lane(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, _ = start_lane(demo, tmp_path, "api")  # the branch stays at main: it holds no commit of its own
    demo.git("checkout", "-q", "--detach", cwd=wt)
    demo.write("src/api/a.py", "uncommitted\n", base=wt)
    removed = write_spec(tmp_path, drop_lane(demo_spec(demo, tmp_path), "api"), "removed.json")
    amend = ("--amend", "--expect-revision", "1")

    def refused(spec_file, want):
        before = store_files(demo)
        rc, v = jplan(guard, demo, spec_file, *amend)
        assert rc == 16 and v["code"] == "BLOCKED" and v["blocked"] == want and store_files(demo) == before, v
        return v
    refused(removed, [{"lane": "api", "reason": "DIRTY_WORKTREE", "files": ["src/api/a.py"]}])
    demo.git("add", "-A", cwd=wt)
    demo.git("commit", "-q", "-m", "work on the detached HEAD", cwd=wt)
    refused(removed, [{"lane": "api", "reason": "UNMERGED_WORK", "files": ["src/api/a.py"]}])
    shrunk = demo_spec(demo, tmp_path)
    shrunk["lanes"][0]["paths"] = ["src/api/b.py", "tests/api/", "package-lock.json"]
    refused(write_spec(tmp_path, shrunk, "shrunk.json"), [{"lane": "api", "reason": "SHRINK", "files": ["src/api/a.py"]}])
    demo.git("checkout", "-q", LANES["api"], cwd=wt)  # back on the branch: the detached commit is no longer the lane's
    rc, v = jplan(guard, demo, removed, *amend)
    assert rc == 0 and v["revision"] == 2 and [x["id"] for x in record(demo)["lanes"]] == ["ui", "docs"], v
    assert not (store_dir(demo) / "claims" / "agent" / "demo" / "api.claim").exists()


def test_amend_keeps_a_detached_lane_worktree_its_own(demo, guard, tmp_path):
    spec = demo_spec(demo, tmp_path)
    f = write_spec(tmp_path, spec)
    plan_ok(guard, demo, f)
    wt, _ = start_lane(demo, tmp_path, "api")
    demo.git("checkout", "-q", "--detach", cwd=wt)
    amend = ("--amend", "--expect-revision", "1")
    for extra in (("--dry-run",), ()):
        rc, v = jplan(guard, demo, f, *amend, *extra)
        assert rc == 0 and v["unchanged"] is True and v["revision"] == 1, v  # the lane's own worktree, detached by its owner, is no clash
    spec["lanes"][1]["paths"] = ["src/ui/", "tests/ui/"]
    rc, v = jplan(guard, demo, write_spec(tmp_path, spec, "changed.json"), *amend)
    assert rc == 0 and v["revision"] == 2 and v["unchanged"] is False, v
    other = wt_dir(tmp_path, "web", "other")
    demo.git("worktree", "add", "-q", "--detach", str(other), "main")  # a fresh plan still clashes with a detached worktree at a planned path
    s = custom_spec(demo, tmp_path, [lane(tmp_path, "web", ["web/"], set_name="other")])
    rc, v = jplan(guard, demo, write_spec(tmp_path, s, "other.json"), name="other")
    assert rc == 12 and ("lanes[0].worktree", "WORKTREE") in errors_of(v), v


def test_a_missing_lane_worktree_counts_as_dirty(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    docs, tip = start_lane(demo, tmp_path, "docs")
    ui, ui_tip = start_lane(demo, tmp_path, "ui")
    for lid in ("docs", "ui"):
        upd_ok(guard, demo, lid, "active")
    demo.write("docs/d.md", "uncommitted\n", base=docs)
    demo.git("worktree", "lock", "--reason", "usb", str(docs))
    away = docs.with_name(docs.name + "-away")
    os.rename(str(docs), str(away))  # the drive is unmounted: the worktree is locked and missing
    shutil.rmtree(str(ui))  # removed without git worktree remove: prunable
    missing = {lid: G.T("en", "set_why_wt_missing", l=lid, w=P(path)) for lid, path in (("docs", docs), ("ui", ui))}
    before = store_files(demo)
    rc, v = jrelease(guard, demo, "--abandon")
    assert rc == 16 and v["blocked"] == [{"lane": "ui", "reason": "DIRTY_WORKTREE"}, {"lane": "docs", "reason": "DIRTY_WORKTREE"}], v
    assert missing["docs"] in v["message"] and missing["ui"] in v["message"] and store_files(demo) == before, v
    for lid, head in (("docs", tip), ("ui", ui_tip)):
        w = upd_refused(guard, demo, lid, "ready", "--head", head, rc_want=16)
        assert w["blocked"] == [{"lane": lid, "reason": "DIRTY_WORKTREE"}] and missing[lid] in w["message"], w
    rows = {x["id"]: x for x in jshow(guard, demo)["view"]["lanes"]}
    assert [(rows[x]["worktree_present"], rows[x]["worktree_clean"]) for x in ("docs", "ui")] == [(False, None), (False, None)]
    os.rename(str(away), str(docs))
    demo.git("checkout", "--", "docs/d.md", cwd=docs)
    assert upd_ok(guard, demo, "docs", "ready", "--head", tip)["state"] == "ready"


def test_set_show_judges_every_worktree_of_a_lane(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    wt, tip = start_lane(demo, tmp_path, "api", {"src/api/a.py": "lane\n"})
    ready_lane(guard, demo, "api", tip)
    demo.git("checkout", "-q", "--detach", cwd=wt)  # the registered worktree: detached and clean
    second = tmp_path / "second"
    demo.git("worktree", "add", "-q", str(second), LANES["api"])
    demo.write("src/api/a.py", "uncommitted\n", base=second)

    def view():
        v = jshow(guard, demo, "--drift")
        text = run(["--repo", str(demo.path), "--lang", "en", "set-show", "--set", "demo", "--drift"]).out
        row = v["view"]["lanes"][0]
        line = next(x for x in text.split("\n") if x.startswith("[x] api"))
        return row["worktree_present"], row["worktree_clean"], row["operation"], line
    present, clean, ops, line = view()
    assert (present, clean, ops) == (True, False, []) and "worktree dirty" in line, line
    demo.git("checkout", "--", "src/api/a.py", cwd=second)
    gitdir = Path(demo.git("rev-parse", "--absolute-git-dir", cwd=second))
    (gitdir / "MERGE_HEAD").write_text(tip + "\n", encoding="utf-8")  # a merge in progress in the second worktree, with no change
    present, clean, ops, line = view()
    assert (present, clean, ops) == (True, True, ["merge"]) and "worktree merge in progress" in line, line
    (gitdir / "MERGE_HEAD").unlink()
    present, clean, ops, line = view()
    assert (present, clean, ops) == (True, True, []) and "worktree clean" in line, line


def test_record_revisions_must_be_object_names(demo, guard, tmp_path):
    plan_ok(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path)))
    good = record(demo)
    out = tmp_path / "out"
    out.mkdir()
    calls = [("set-show", "--set", "demo", "--drift"), tuple(update_args("api", "active", 1)), ("set-release", "--set", "demo", "--abandon")]

    def unreadable(why):
        for args in calls:
            rc, v = jcall(guard, demo, *args)
            assert rc == 11 and v["code"] == "UNKNOWN" and v["unknowns"][0]["code"] == "SET_UNREADABLE" and why in v["unknowns"][0]["text"], (args, v)
        rc, v = jplan(guard, demo, write_spec(tmp_path, demo_spec(demo, tmp_path), "amend.json"), "--amend", "--expect-revision", "1")
        assert rc == 11 and v["unknowns"][0]["code"] == "SET_UNREADABLE", v
        assert record_file(demo).exists() and not any(out.iterdir())  # nothing written, and git never read a value as an option
    for base in ("--output=%s/PWNED" % P(out), "main", good["base"][:39]):
        write_record(demo, dict(good, base=base))
        unreadable("base is not a full object name")
    write_record(demo, dict(good, base=good["base"].upper()))
    assert jshow(guard, demo)["record"]["base"] == good["base"].upper()
    for head in ("-x", "HEAD"):
        write_record(demo, dict(good, lanes=[dict(good["lanes"][0], state="ready", head=head)] + good["lanes"][1:]))
        unreadable("lanes[0].state or head is not valid")
    write_record(demo, dict(good, lanes=[dict(good["lanes"][0], state="ready", head=good["base"])] + good["lanes"][1:]))
    assert jshow(guard, demo)["record"]["lanes"][0]["head"] == good["base"]


@pytest.mark.skipif(os.name == "nt", reason="the POSIX spelling of a worktree path")
def test_worktree_spelling_folds_leading_slashes_on_posix(demo, guard, tmp_path):
    for p in ("//home/u/x-demo-api", "///home/u/x-demo-api", "/home//u/x-demo-api"):
        assert G.lane_worktree(p) == ("/home/u/x-demo-api", None), p
    for spelled in (P(demo.path / "x-demo-api"), "/" + P(demo.path / "x-demo-api")):  # inside the main worktree, however many slashes lead
        s = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/"], worktree=spelled)])
        rc, v = dry(guard, demo, tmp_path, s)
        assert rc == 12 and ("lanes[0].worktree", "WORKTREE") in errors_of(v), (spelled, v)


@pytest.mark.skipif(os.name != "nt", reason="the Win32 spelling of a worktree path")
def test_worktree_spelling_refuses_win32_namespace_paths(demo, guard, tmp_path):
    for p in ("\\\\?\\C:\\x\\wt-demo-api", "\\\\.\\C:\\x\\wt-demo-api", "//?/C:/x/wt-demo-api", "//./C:/x/wt-demo-api"):
        stored, why = G.lane_worktree(p)
        assert stored is None and "Win32 namespace path" in why, p
    assert G.lane_worktree("\\\\server\\share\\wt-demo-api") == ("//server/share/wt-demo-api", None)
    s = custom_spec(demo, tmp_path, [lane(tmp_path, "api", ["src/"], worktree="\\\\?\\" + str(wt_dir(tmp_path, "api")))])
    rc, v = dry(guard, demo, tmp_path, s)
    assert rc == 24 and [e["field"] for e in v["errors"]] == ["lanes[0].worktree"] and "Win32 namespace path" in v["errors"][0]["text"], v


def test_lane_overlaps_finds_every_pair_a_brute_force_finds(monkeypatch):
    import random
    rnd = random.Random(104)
    monkeypatch.setattr(G, "SPEC_PAIRS", 10 ** 6)
    words = ["src", "SRC", "a", "A", "b", "x", "x.md", "*.py", "a?", "*", "**", "[ab]", "a*b", "?"]

    def entry():
        text = "/".join(rnd.choice(words) for _ in range(rnd.randint(1, 4)))
        return text + "/" if rnd.random() < 0.3 else text
    pairs_seen = 0
    for _ in range(300):
        lanes = []
        for li in range(rnd.randint(2, 5)):
            entries, want = [], rnd.randint(1, 6)
            while len(entries) < want:
                try:
                    entries.append(G.parse_entry(entry()))
                except G.ManifestError:
                    continue
            lanes.append({"id": "l%d" % li, "entries": entries})
        brute, total = [], 0
        for li, a in enumerate(lanes):
            for ea in a["entries"]:
                for b in lanes[li + 1:]:
                    for eb in b["entries"]:
                        if G.entries_overlap(ea, eb):
                            total += 1
                            brute.append((a["id"], ea.raw, b["id"], eb.raw))
        assert G.lane_overlaps(lanes, time.monotonic() + 60) == (brute, total), lanes
        pairs_seen += total
    assert pairs_seen > 100  # the generator makes overlapping and disjoint sets alike


def test_lane_overlaps_stays_linear_below_a_shared_top_directory(demo, guard, tmp_path, monkeypatch):
    def paths(i):
        return ["src/mod-%02d/dir%03d/" % (i, j) for j in range(199)] + ["src/mod-%02d/*.py" % i]
    lanes = [{"id": "mod-%02d" % i, "entries": [G.parse_entry(p) for p in paths(i)]} for i in range(1, 13)]
    calls = []
    real = G.entries_overlap
    monkeypatch.setattr(G, "entries_overlap", lambda a, b: calls.append(1) or real(a, b))
    assert G.lane_overlaps(lanes, time.monotonic() + 60) == ([], 0) and calls == []  # no literal prefix is a prefix of another lane's
    lanes[0]["entries"].append(G.parse_entry("src/*.cfg"))
    assert G.lane_overlaps(lanes, time.monotonic() + 60) == ([], 0)
    assert 0 < len(calls) <= sum(len(x["entries"]) for x in lanes[1:]), len(calls)
    f = write_spec(tmp_path, custom_spec(demo, tmp_path, [lane(tmp_path, "mod-%02d" % i, paths(i)) for i in range(1, 13)]))
    started = time.monotonic()
    rc, v = jplan(guard, demo, f, "--dry-run")
    assert rc == 0 and v["dry_run"] is True and time.monotonic() - started < time_budget(10), (time.monotonic() - started, v.get("code"))
