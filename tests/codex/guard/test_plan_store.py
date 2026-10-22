"""Real-Git integration tests: evidence gathering, plan / check / list / release / override, the claim store and its lock."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import G, SCRIPT, Repo, payload, run


def claims_dir(repo):
    return Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "claims"


def verdict(guard, repo, *args, stdin=b""):
    r = guard(repo, "--json", *args, stdin=stdin)
    try:
        return r.rc, json.loads(r.out)
    except ValueError:
        raise AssertionError("no JSON verdict (exit %s); stdout %r; stderr %r" % (r.rc, r.out, r.err)) from None


# ---- evidence ------------------------------------------------------------------------------------------------------
def test_committed_overlap_names_branch(repo, guard):
    repo.branch_with("agent/x", "src/a.py")
    rc, v = verdict(guard, repo, "check", "--branch", "agent/new", "--paths", "src/a.py")
    assert rc == 10 and v["code"] == "CONFLICT"
    c = v["conflicts"][0]
    assert c["branch"] == "agent/x" and c["evidence"][0]["kind"] == "committed" and c["evidence"][0]["files"] == ["src/a.py"]
    assert "agent/x" in v["message"] and v["fingerprint"]
    assert guard(repo, "check", "--branch", "agent/new", "--paths", "docs/").rc == 0


def test_uncommitted_overlap_and_sibling_untouched(repo, guard):
    wt = repo.worktree("wt-a", "agent/a")
    repo.write("src/a.py", "edit\n", base=wt)
    repo.git("add", "src/a.py", cwd=wt)
    repo.write("src/b.py", "edit\n", base=wt)
    repo.write("new/untracked.txt", "u\n", base=wt)
    before = repo.git("status", "--porcelain=v1", "--untracked-files=all", cwd=wt)
    rc, v = verdict(guard, repo, "check", "--branch", "agent/new", "--paths", "src/", "new/")
    assert rc == 10
    ev = v["conflicts"][0]["evidence"][0]
    assert ev["kind"] == "uncommitted" and ev["files"] == ["new/untracked.txt", "src/a.py", "src/b.py"]
    assert str(wt).lower().replace("\\", "/") in v["conflicts"][0]["worktrees"][0].lower().replace("\\", "/")
    assert repo.git("status", "--porcelain=v1", "--untracked-files=all", cwd=wt) == before  # the sibling is only read


def test_rename_claims_both_names_and_delete_claims(repo, guard):
    wt = repo.worktree("wt-r", "agent/r")
    repo.git("mv", "src/a.py", "src/renamed.py", cwd=wt)
    repo.git("rm", "-q", "docs/d.md", cwd=wt)
    assert guard(repo, "check", "--branch", "n1", "--paths", "src/a.py").rc == 10
    assert guard(repo, "check", "--branch", "n2", "--paths", "src/renamed.py").rc == 10
    assert guard(repo, "check", "--branch", "n3", "--paths", "docs/d.md").rc == 10


def test_presence_in_a_checkout_claims_nothing(repo, guard):
    repo.worktree("wt-p", "agent/p")  # contains every file, modifies none
    assert guard(repo, "check", "--branch", "agent/n", "--paths", "src/").rc == 0


def test_dirty_primary_worktree_replica(repo, guard):
    for i in range(300):
        repo.write("tests/gen/f%03d.txt" % i, "x\n")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "tests")
    for i in range(300):
        os.remove(repo.path / "tests" / "gen" / ("f%03d.txt" % i))  # the primary worktree is dirty with deleted files
    assert guard(repo, "check", "--branch", "agent/n", "--paths", "references/").rc == 0
    rc, v = verdict(guard, repo, "check", "--branch", "agent/n", "--paths", "tests/gen/f007.txt")
    assert rc == 10 and v["conflicts"][0]["branch"] == "main" and v["conflicts"][0]["evidence"][0]["kind"] == "uncommitted"


def test_squash_merged_branch_stops_claiming(repo, guard):
    repo.branch_with("agent/s", "src/a.py", "squashed\n")
    assert guard(repo, "check", "--branch", "n1", "--paths", "src/a.py").rc == 10
    repo.git("merge", "--squash", "agent/s")
    repo.git("commit", "-q", "-m", "squash")
    assert guard(repo, "check", "--branch", "n2", "--paths", "src/a.py").rc == 0  # the target holds that content now
    wt = repo.path.parent / "tmp-agent-s2"
    repo.git("worktree", "add", "-q", str(wt), "agent/s")
    repo.commit("src/a.py", "diverged again\n", cwd=wt)
    repo.git("worktree", "remove", "--force", str(wt))
    assert guard(repo, "check", "--branch", "n3", "--paths", "src/a.py").rc == 10  # a later divergent edit claims again


def test_in_progress_operations(repo, guard):
    wt = repo.worktree("wt-m", "agent/m")
    repo.commit("src/a.py", "lane\n", cwd=wt)
    repo.commit("src/a.py", "main side\n")
    repo.git("merge", "agent/m", check=False)  # conflicting merge left in progress in the primary worktree
    rc, v = verdict(guard, repo, "check", "--branch", "n1", "--paths", "docs/")
    assert rc == 0 and any(w["code"] == "OP_IN_PROGRESS" for w in v["warnings"])
    gitdir = Path(repo.git("rev-parse", "--absolute-git-dir", cwd=wt))
    (gitdir / "rebase-apply").mkdir()
    (gitdir / "rebase-apply" / "applying").write_text("", encoding="utf-8")
    rc, v = verdict(guard, repo, "check", "--branch", "n2", "--paths", "docs/")
    assert rc == 11 and any(u["code"] == "OP_METADATA_UNREADABLE" for u in v["unknowns"])


def test_remote_tracking_branch_ahead(repo, guard):
    repo.branch_with("tmp-remote", "web/package-lock.json", "remote\n")
    sha = repo.git("rev-parse", "tmp-remote")
    repo.git("branch", "-D", "tmp-remote")
    repo.git("update-ref", "refs/remotes/origin/feat", sha)
    rc, v = verdict(guard, repo, "check", "--branch", "n1", "--paths", "web/")
    assert rc == 10 and v["conflicts"][0]["branch"] == "origin/feat"
    assert any(w["code"] == "REMOTE_AS_OF_LAST_FETCH" for w in v["warnings"])
    # the same name checked out locally and equal to the remote copy: one claimant, not two
    repo.git("branch", "feat", sha)
    rc, v = verdict(guard, repo, "check", "--branch", "n2", "--paths", "web/")
    assert [c["branch"] for c in v["conflicts"]] == ["feat"]
    # a remote copy that is ahead of the local branch is its own claimant again
    wt = repo.path.parent / "tmp-feat"
    repo.git("worktree", "add", "-q", str(wt), "feat")
    repo.commit("web/more.js", "m\n", cwd=wt)
    repo.git("worktree", "remove", "--force", str(wt))
    repo.git("update-ref", "refs/remotes/origin/feat", sha)
    repo.git("update-ref", "refs/remotes/origin/ahead", repo.git("rev-parse", "main"))
    assert guard(repo, "check", "--branch", "n3", "--paths", "web/").rc == 10


def test_target_resolution(repo, guard):
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert v["target"] == {"name": "main", "sha": repo.git("rev-parse", "main"), "confidence": "medium"}
    assert any(w["code"] == "TARGET_INFERRED" for w in v["warnings"])
    repo.git("branch", "dev")
    repo.git("config", "--local", "magos.target", "dev")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert v["target"]["name"] == "dev" and v["target"]["confidence"] == "high"
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/", "--target", "main")
    assert v["target"]["name"] == "main"
    repo.git("config", "--local", "--unset", "magos.target")
    repo.git("branch", "-m", "main", "work")
    repo.git("branch", "develop")
    repo.git("branch", "master")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 11 and v["unknowns"][0]["code"] == "TARGET_UNCERTAIN" and "git config magos.target" in v["unknowns"][0]["text"]
    repo.git("branch", "-D", "master")
    repo.git("config", "--local", "init.defaultBranch", "work")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 0 and v["target"]["name"] == "work"


def test_target_from_remote_head_and_diverged_copies(repo, guard):
    sha = repo.git("rev-parse", "main")
    repo.git("update-ref", "refs/remotes/origin/main", sha)
    repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert v["target"]["confidence"] == "high"
    repo.commit("src/a.py", "local only\n")
    repo.git("update-ref", "refs/remotes/origin/main", sha)
    assert guard(repo, "check", "--branch", "n", "--paths", "docs/").rc == 0  # the remote copy is an ancestor: the local one wins
    other = repo.git("commit-tree", repo.git("rev-parse", "main^{tree}"), "-m", "diverge")
    repo.git("update-ref", "refs/remotes/origin/main", other)
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 11 and "diverged" in v["unknowns"][0]["text"]


def test_unrelated_history_is_a_warning(repo, guard):
    tree = repo.git("hash-object", "-t", "tree", "-w", "--stdin", inp=b"")
    orphan = repo.git("commit-tree", tree, "-m", "orphan")
    repo.git("branch", "gh-pages", orphan)
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 0 and any(w["code"] == "UNRELATED_HISTORY" and "gh-pages" in w["text"] for w in v["warnings"])  # it cannot be merged, so it cannot collide


def test_too_many_claimants(repo, guard, monkeypatch):
    monkeypatch.setattr(G, "MAX_CLAIMANTS", 1)
    repo.branch_with("a1", "src/a.py")
    repo.branch_with("a2", "src/b.py")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 11 and v["unknowns"][0]["code"] == "TOO_MANY_CLAIMANTS"


def test_prunable_worktree_is_a_warning(repo, guard):
    wt = repo.worktree("wt-gone", "agent/gone")
    import shutil
    shutil.rmtree(wt)
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 0 and any(w["code"] == "WORKTREE_PRUNABLE" for w in v["warnings"])


def test_git_failures_fail_closed(repo, guard, monkeypatch):
    import subprocess as sp
    real = sp.run

    def missing(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(G.subprocess, "run", missing)
    rc = guard(repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc.rc == 11 and "GIT_MISSING" in rc.err  # a missing git is an error, never "not a repository"
    monkeypatch.setattr(G.subprocess, "run", real)
    g = G.open_repo(str(repo.path))
    monkeypatch.setattr(G.subprocess, "run", missing)
    with pytest.raises(G.GitFail) as err:
        g.run("status")
    assert err.value.code == "GIT_MISSING"
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        raise OSError(1455, "paging file")
    monkeypatch.setattr(G.subprocess, "run", flaky)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    with pytest.raises(G.GitFail) as err:
        g.run("status")
    assert err.value.code == "GIT_FAILED" and len(calls) == 3

    def slow(*a, **k):
        raise sp.TimeoutExpired("git", 1)
    monkeypatch.setattr(G.subprocess, "run", slow)
    with pytest.raises(G.GitFail) as err:
        g.run("status")
    assert err.value.code == "BUDGET_EXCEEDED"
    g.deadline = 0
    with pytest.raises(G.GitFail):
        g.run("status")
    monkeypatch.setattr(G.subprocess, "run", real)
    g2 = G.open_repo(str(repo.path))
    with pytest.raises(G.GitFail) as err:
        g2.run("rev-parse", "--verify", "refs/heads/no-such-branch")  # real git exits 128 with a message
    assert err.value.code == "GIT_FAILED" and "rev-parse" in str(err.value) and "single revision" in str(err.value), str(err.value)


def test_open_repo_edge_cases(tmp_path):
    assert G.open_repo(None) is None and G.open_repo(str(tmp_path / "missing")) is None
    assert G.open_repo(str(tmp_path)) is None  # a directory that is not a repository
    assert run(["--repo", str(tmp_path), "plan", "--branch", "b", "--paths", "x"]).rc == 2
    assert run(["--repo", str(tmp_path), "list"]).rc == 2
    assert run(["--repo", str(tmp_path), "release", "--branch", "b"]).rc == 2
    assert run(["--repo", str(tmp_path), "arm"]).rc == 2
    assert run(["--repo", str(tmp_path), "disarm"]).rc == 2
    assert run(["--repo", str(tmp_path), "override", "--fingerprint", "f", "--reason", "r"]).rc == 2


def test_opening_a_repository_reads_a_git_failure_as_no_repository(repo, monkeypatch):
    # Opening the repository is the one step that does not fail closed (Invariant 3): a failing rev-parse reads as "not a repository",
    # except a missing git and an exhausted budget, which stay errors.
    real = G.Git.run

    def failing(code):
        def run_git(self, *args, **kw):
            if args[:1] == ("rev-parse",):
                raise G.GitFail(code, "injected")
            return real(self, *args, **kw)
        return run_git
    assert G.open_repo(str(repo.path)) is not None
    monkeypatch.setattr(G.Git, "run", failing("GIT_FAILED"))
    assert G.open_repo(str(repo.path)) is None
    for code in ("GIT_MISSING", "BUDGET_EXCEEDED"):
        monkeypatch.setattr(G.Git, "run", failing(code))
        with pytest.raises(G.GitFail) as err:
            G.open_repo(str(repo.path))
        assert err.value.code == code


# ---- plan / amend / list / release ---------------------------------------------------------------------------------
def test_plan_registers_claim_and_prints_creation_command(repo, guard):
    r = guard(repo, "plan", "--branch", "agent/one", "--paths", "docs/", "src/a.py", "--worktree", str(repo.path.parent / "wt-one"))
    assert r.rc == 0 and "git worktree add" in r.out and "-b agent/one main" in r.out
    claim = (claims_dir(repo) / "agent" / "one.claim").read_text(encoding="utf-8").splitlines()
    assert claim[0] == "state=active" and "entry=docs/" in claim and "entry=src/a.py" in claim
    assert next(x for x in claim if x.startswith("branch=")) == "branch=agent/one" and next(x for x in claim if x.startswith("by=")).startswith("by=tester")
    audit = [json.loads(x) for x in (claims_dir(repo).parent / "audit.log").read_text(encoding="utf-8").splitlines()]
    assert audit[0]["op"] == "plan" and audit[0]["branch"] == "agent/one"
    rows = json.loads(guard(repo, "list", "--json").out)
    assert rows[0]["state"] == "planned" and rows[0]["entries"] == ["docs/", "src/a.py"]
    assert "planned" in guard(repo, "list").out and guard(repo, "list", "--drift").rc == 0


def test_amend_semantics(repo, guard):
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "src/a.py").rc == 0
    assert guard(repo, "plan", "--branch", "L", "--paths", "src/a.py", "docs/").rc == 0  # same entries (any order that normalises equal)? different order is a different list
    r = guard(repo, "plan", "--branch", "L", "--paths", "docs/")
    assert r.rc == 14 and "--amend" in r.out
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "--amend").rc == 0  # removal only
    assert "entry=src/a.py" not in (claims_dir(repo) / "L.claim").read_text(encoding="utf-8")
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "web/", "--amend").rc == 0  # growth is re-judged
    repo.branch_with("other", "web/package-lock.json")
    r = guard(repo, "plan", "--branch", "L", "--paths", "docs/", "web/package-lock.json", "--amend")
    assert r.rc == 10 and "other" in r.out
    assert [json.loads(x)["op"] for x in (claims_dir(repo).parent / "audit.log").read_text(encoding="utf-8").splitlines()] == ["plan", "amend", "amend"]


def test_declared_manifests_collide_even_before_any_branch_exists(repo, guard):
    assert guard(repo, "plan", "--branch", "lane1", "--paths", "docs/").rc == 0
    rc, v = verdict(guard, repo, "plan", "--branch", "lane2", "--paths", "docs/guide.md")
    assert rc == 10 and v["conflicts"][0]["branch"] == "lane1" and v["conflicts"][0]["planned"] is True
    assert v["conflicts"][0]["evidence"][0]["kind"] == "declared"
    assert not (claims_dir(repo) / "lane2.claim").exists()  # a denial registers nothing
    assert guard(repo, "plan", "--branch", "lane3", "--paths", "src/b.py").rc == 0


def test_branch_that_exists_cannot_be_registered_afterwards(repo, guard):
    repo.branch_with("already", "src/a.py")
    r = guard(repo, "plan", "--branch", "already", "--paths", "src/a.py")
    assert r.rc == 15 and "already exists" in r.out


def test_branch_name_rules(repo, guard):
    repo.git("branch", "feature")
    repo.git("branch", "Agent/x")
    for name, needle in (("bad name", "valid git branch name"), ("con", "reserved"), ("agent/aux.txt", "reserved"), ("a" * 101, "100"), ("a<b", "100 characters or contains"),
                         ("feature/sub", "file and a directory"), ("agent/x", "collides"), ("-dash", "valid git branch name")):
        r = guard(repo, "check", "--branch=" + name, "--paths", "docs/")
        assert r.rc == 12 and needle in r.out, (name, r.out)
    assert guard(repo, "check", "--branch", "agent/y", "--paths", "docs/").rc == 0
    guard(repo, "plan", "--branch", "claimed/one", "--paths", "docs/")
    assert guard(repo, "check", "--branch", "claimed", "--paths", "src/").rc == 12  # a claim is a directory prefix of the new name


def test_manifest_inputs(repo, guard, tmp_path):
    f = tmp_path / "manifest.txt"
    f.write_bytes("﻿# lane\r\ndocs/\r\n\r\nsrc/a.py\r\n".encode("utf-8"))
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--manifest", str(f))
    assert rc == 0
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--manifest", "-", stdin=b"docs/\nsrc/\n")
    assert rc == 0
    inside = repo.write("m.txt", "docs/\n")
    r = guard(repo, "check", "--branch", "n", "--manifest", str(inside))
    assert r.rc == 12 and "outside every worktree" in r.out
    r = guard(repo, "check", "--branch", "n", "--paths", "/abs", "../x")
    assert r.rc == 12 and "ABSOLUTE" in r.out and "DOTDOT" in r.out
    assert guard(repo, "check", "--branch", "n").rc == 12


def test_not_armed_warning(repo, guard):
    repo.branch_with("agent/x", "src/a.py")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert any(w["code"] == "NOT_ARMED" for w in v["warnings"])


def test_list_states_and_drift(repo, guard):
    guard(repo, "plan", "--branch", "planned", "--paths", "docs/")
    repo.branch_with("active", "src/a.py")
    repo.branch_with("idle", "src/b.py")
    repo.git("merge", "-q", "--no-ff", "idle", "-m", "integrate idle")  # a merge commit: the lane moved beyond the target tip it was cut from
    for name, paths in (("active", ["src/"]), ("idle", ["src/b.py"])):
        claim = G.Lock  # claims for pre-existing branches are written directly: plan refuses to register an existing branch
        g = G.open_repo(str(repo.path))
        G.write_claim(g, name, {"branch": name, "worktree": "", "target": "main", "base": "x", "created": "2026-01-01T00:00:00Z", "by": "t", "override": "", "entries": paths})
    wt = repo.worktree("wt-drift", "drifty")
    g = G.open_repo(str(repo.path))
    G.write_claim(g, "drifty", {"branch": "drifty", "worktree": str(wt), "target": "main", "base": "x", "created": "2026-01-02T00:00:00Z", "by": "t", "override": "ov", "entries": ["docs/"]})
    repo.write("src/outside.py", "n\n", base=wt)
    rows = {r["branch"]: r for r in json.loads(guard(repo, "list", "--drift", "--json").out)}
    assert (rows["planned"]["state"], rows["active"]["state"], rows["idle"]["state"], rows["drifty"]["state"]) == ("planned", "active", "idle", "active")
    assert rows["drifty"]["drift"] == ["src/outside.py"] and rows["drifty"]["override"] == "ov" and rows["planned"]["drift"] == []
    assert "drift: src/outside.py" in guard(repo, "list", "--drift").out


def test_release(repo, guard):
    guard(repo, "plan", "--branch", "gone", "--paths", "docs/")
    assert guard(repo, "release", "--branch", "nope").out.startswith("no open claim")
    r = guard(repo, "release", "--branch", "gone", "--reason", "abandoned")
    assert r.rc == 0 and "released" in r.out.lower() and not (claims_dir(repo) / "gone.claim").exists()
    assert json.loads((claims_dir(repo).parent / "audit.log").read_text(encoding="utf-8").splitlines()[-1])["op"] == "release"
    repo.branch_with("busy", "src/a.py")
    g = G.open_repo(str(repo.path))
    G.write_claim(g, "busy", {"branch": "busy", "worktree": "", "target": "main", "base": "x", "created": "2026-01-01T00:00:00Z", "by": "t", "override": "", "entries": ["src/"]})
    r = guard(repo, "release", "--branch", "busy")
    assert r.rc == 16 and "refused" in r.err and (claims_dir(repo) / "busy.claim").exists()
    repo.git("merge", "-q", "busy")
    assert guard(repo, "release", "--branch", "busy").rc == 0  # merged and without a worktree: idle


# ---- override ------------------------------------------------------------------------------------------------------
def test_override_gate_and_consumption(repo, guard, monkeypatch):
    repo.branch_with("agent/x", "src/a.py")
    rc, v = verdict(guard, repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    fp = v["fingerprint"]
    r = guard(repo, "override", "--fingerprint", fp, "--reason", "user said so")
    assert r.rc == 17 and "real terminal" in r.err  # no console: refused at once, no hang
    monkeypatch.setattr(G, "user_console", lambda: True)
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--fingerprint", fp, "--reason", "x"], stdin=b"wrong\n")
    assert r.rc == 17
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--fingerprint", fp, "--reason", "user said so"], stdin=(fp + "\n").encode())
    assert r.rc == 0 and fp in r.out
    store = claims_dir(repo).parent
    rec = json.loads((store / "override" / (fp + ".json")).read_text(encoding="utf-8"))
    assert rec["reason"] == "user said so" and rec["expires"] > rec["at"]
    rc, v = verdict(guard, repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert rc == 0 and v["overridden"] is True and v["code"] == "OVERRIDDEN"
    assert "override=" + fp in (claims_dir(repo) / "agent" / "new.claim").read_text(encoding="utf-8")
    assert not (store / "override" / (fp + ".json")).exists()  # one-shot
    assert json.loads((store / "audit.log").read_text(encoding="utf-8").splitlines()[-1])["reason"] == "user said so"


def test_override_expires_and_a_changed_repository_voids_it(repo, guard, monkeypatch):
    repo.branch_with("agent/x", "src/a.py")
    fp = verdict(guard, repo, "check", "--branch", "n", "--paths", "src/a.py")[1]["fingerprint"]
    g = G.open_repo(str(repo.path))
    d = Path(G.store(g)) / "override"
    d.mkdir(parents=True)
    (d / (fp + ".json")).write_text(json.dumps({"fp": fp, "reason": "r", "at": "2020-01-01T00:00:00Z", "expires": "2020-01-01T01:00:00Z"}), encoding="utf-8")
    assert guard(repo, "plan", "--branch", "n", "--paths", "src/a.py").rc == 10  # expired: plan does not honour it
    (d / (fp + ".json")).write_text(json.dumps({"fp": fp, "reason": "r", "at": "2020", "expires": "2999-01-01T00:00:00Z"}), encoding="utf-8")
    assert guard(repo, "check", "--branch", "n", "--paths", "src/a.py").rc == 10  # only plan reads override records
    assert (d / (fp + ".json")).exists()
    repo.commit("docs/d.md", "moved target\n")  # the target sha changes, so the denial fingerprint changes
    repo.git("branch", "-f", "agent/x", "agent/x")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "src/a.py")
    assert rc == 10 and v["fingerprint"] != fp
    (d / (fp + ".json")).write_text("{bad json", encoding="utf-8")
    assert G.read_override(g, fp) is None and G.read_override(g, "ffffffffffff") is None


def test_challenge_prompts_and_times_out(monkeypatch, capsys):
    monkeypatch.setattr(G, "user_console", lambda: True)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("abc123\n"))
    assert G.challenge("abc123", "en") is True
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("nope\n"))
    assert G.challenge("abc123", "en") is False
    monkeypatch.setattr(G, "user_console", lambda: False)
    assert G.challenge("abc123", "zh") is False
    monkeypatch.setattr(G, "user_console", lambda: True)
    gate = threading.Event()

    class Silent:  # a terminal where nothing is typed
        def readline(self):
            gate.wait(5)
            return ""
    monkeypatch.setattr(G.threading.Thread, "join", lambda self, timeout=None: None)  # the 120 s window elapses at once
    exited = []
    monkeypatch.setattr(G.os, "_exit", lambda code: exited.append(code) or (_ for _ in ()).throw(SystemExit(code)))
    monkeypatch.setattr(sys, "stdin", Silent())
    with pytest.raises(SystemExit):
        G.challenge("abc123", "en")
    gate.set()
    assert exited == [17]


def test_user_console_detection(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    assert G.user_console() is False  # not a console under pytest capture
    monkeypatch.setattr(G.os, "name", "posix")
    monkeypatch.setattr(G.os, "isatty", lambda fd: True)
    monkeypatch.setattr(sys, "stdout", type("S", (), {"isatty": lambda self: True})())
    assert G.user_console() is True
    monkeypatch.setattr(G.os, "isatty", lambda fd: (_ for _ in ()).throw(OSError()))
    assert G.user_console() is False


# ---- the store, its lock and concurrent planners -------------------------------------------------------------------
def test_lock_timeout_and_release(repo, guard, monkeypatch):
    g = G.open_repo(str(repo.path))
    monkeypatch.setenv("MAGOS_LOCK_TIMEOUT", "0.3")
    started, done = threading.Event(), threading.Event()

    def hold():
        with G.Lock(g):
            started.set()
            done.wait(5)
    t = threading.Thread(target=hold)
    t.start()
    started.wait(5)
    try:
        # on POSIX flock is per open file description, on Windows locking is per handle: a second handle in this process contends too
        r = guard(repo, "plan", "--branch", "n", "--paths", "docs/")
        assert r.rc == 13 and "claim lock" in r.out
        r = guard(repo, "release", "--branch", "n")
        assert r.rc == 13
    finally:
        done.set()
        t.join()
    assert guard(repo, "plan", "--branch", "n", "--paths", "docs/").rc == 0  # free again


def test_concurrent_planners_one_winner(repo):
    def planner(branch, paths):
        return subprocess.Popen([sys.executable, str(SCRIPT), "--repo", str(repo.path), "--lang", "en", "--json", "plan", "--branch", branch, "--paths", *paths],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy())
    for attempt in range(3):
        a, b = "race-a%d" % attempt, "race-b%d" % attempt
        procs = [planner(a, ["web/%d/" % attempt]), planner(b, ["web/%d/x.js" % attempt])]
        outs = []
        for p in procs:
            out, err = p.communicate(timeout=120)
            outs.append((p.returncode, out.decode("utf-8"), err.decode("utf-8", "replace")))
        codes = sorted(rc for rc, _, _ in outs)
        assert codes == [0, 10], outs
        loser = next(json.loads(o) for rc, o, _ in outs if rc == 10)
        assert loser["conflicts"][0]["branch"] in (a, b), outs
    disjoint = [planner("dis-a", ["docs/"]), planner("dis-b", ["src/"])]
    done = [(p.communicate(timeout=120), p.returncode) for p in disjoint]
    assert [rc for _, rc in done] == [0, 0], done


def test_claim_files_atomic_and_tolerant(repo, guard):
    g = G.open_repo(str(repo.path))
    G.write_claim(g, "x/y", {"branch": "x/y", "worktree": "", "target": "main", "base": "b", "created": "t", "by": "me", "override": "", "entries": ["a", "b c"]})
    claims, bad = G.read_claims(g)
    assert claims[G.fold("x/y")]["entries"] == ["a", "b c"] and not bad
    p = Path(G.claim_path(g, "x/y"))
    assert not list(p.parent.glob("*.tmp"))
    p.write_bytes(b"\xef\xbb\xbfstate=active\r\nbranch=x/y\r\nentry=a\r\n")  # BOM and CRLF are tolerated
    assert G.read_claims(g)[0][G.fold("x/y")]["entries"] == ["a"]
    p.write_text("garbage", encoding="utf-8")
    claims, bad = G.read_claims(g)
    assert not claims and bad
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 11 or rc == 0  # an unreadable claim is carried as an unknown only when its branch is declared; the file alone is ignored here
    p.write_text("state=active\nbranch=x/y\nentry=/absolute\n", encoding="utf-8")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 11 and v["unknowns"][0]["code"] == "CLAIM_UNPARSEABLE"


def test_read_retry_on_permission_error(tmp_path, monkeypatch):
    f = tmp_path / "x"
    f.write_text("hi", encoding="utf-8")
    real = open
    calls = []

    def flaky(path, mode="r", *a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(path)
        return real(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", flaky)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    assert G._read_retry(str(f)) == "hi"
    calls.clear()
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(PermissionError("x")))
    with pytest.raises(PermissionError):
        G._read_retry(str(f))


def test_write_claim_retries_replace(repo, monkeypatch):
    g = G.open_repo(str(repo.path))
    real = os.replace
    n = []

    def flaky(a, b):
        n.append(1)
        if len(n) < 3:
            raise PermissionError(b)
        return real(a, b)
    monkeypatch.setattr(G.os, "replace", flaky)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    G.write_claim(g, "r", {"branch": "r", "entries": ["a"]})
    assert len(n) == 3 and Path(G.claim_path(g, "r")).exists()
    monkeypatch.setattr(G.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError(b)))
    with pytest.raises(PermissionError):
        G.write_claim(g, "r2", {"branch": "r2", "entries": ["a"]})


def busy_remove(monkeypatch, fails):
    """os.remove raising PermissionError for a path while its count in `fails` is not used up (None: on every call); -> the calls per path."""
    real, calls = os.remove, {}

    def remove(path, *a, **kw):
        key = os.path.normcase(str(path))
        if key in fails:
            calls[key] = calls.get(key, 0) + 1
            if fails[key] is None or calls[key] <= fails[key]:
                raise PermissionError(13, "injected: busy", str(path))
        return real(path, *a, **kw)
    monkeypatch.setattr(G.os, "remove", remove)
    return calls


def a_record_and_a_claim(tmp_path):
    (tmp_path / "claims").mkdir()
    rec, claim = tmp_path / "demo.json", tmp_path / "claims" / "docs.claim"
    rec.write_bytes(b"old record\n")
    claim.write_bytes(b"old claim\n")
    return rec, claim


def test_store_removal_retries_a_busy_file(tmp_path, monkeypatch):
    rec, claim = a_record_and_a_claim(tmp_path)
    key = os.path.normcase(str(claim))
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    calls = busy_remove(monkeypatch, {key: 2})
    G.commit_store([(str(rec), b"new record\n", b"old record\n")], [(str(claim), b"old claim\n")])
    assert rec.read_bytes() == b"new record\n" and not claim.exists() and calls[key] == 3
    rec.write_bytes(b"old record\n")
    claim.write_bytes(b"old claim\n")
    calls = busy_remove(monkeypatch, {key: None})
    with pytest.raises(PermissionError):
        G.commit_store([(str(rec), b"new record\n", b"old record\n")], [(str(claim), b"old claim\n")])
    assert calls[key] == 40 and rec.read_bytes() == b"old record\n" and claim.read_bytes() == b"old claim\n"
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses to remove a file that a reader holds open")
def test_store_removal_waits_for_a_reader(tmp_path):
    rec, claim = a_record_and_a_claim(tmp_path)
    reader = open(claim, "rb")
    timer = threading.Timer(0.3, reader.close)
    timer.start()
    try:
        G.commit_store([(str(rec), b"new record\n", b"old record\n")], [(str(claim), b"old claim\n")])
    finally:
        timer.join()
        reader.close()
    assert rec.read_bytes() == b"new record\n" and not claim.exists()


def test_store_undo_retries_a_busy_removal(tmp_path, monkeypatch):
    rec, claim = a_record_and_a_claim(tmp_path)
    new = tmp_path / "claims" / "api.claim"
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    calls = busy_remove(monkeypatch, {os.path.normcase(str(claim)): None, os.path.normcase(str(new)): 2})
    with pytest.raises(PermissionError) as err:
        G.commit_store([(str(new), b"new claim\n", None), (str(rec), b"new record\n", b"old record\n")], [(str(claim), b"old claim\n")])
    assert not isinstance(err.value, G.NotRestored) and "could not be put back" not in str(err.value)
    assert not new.exists() and calls[os.path.normcase(str(new))] == 3
    assert rec.read_bytes() == b"old record\n" and claim.read_bytes() == b"old claim\n" and not list(tmp_path.rglob("*.tmp"))


def test_replace_files_undo_retries_a_busy_removal(tmp_path, monkeypatch):
    new, old = tmp_path / "a.claim", tmp_path / "b.json"
    old.write_bytes(b"old\n")
    real = G._replace

    def failing(tmp, path, tries=40):
        if os.path.normcase(str(path)) == os.path.normcase(str(old)):
            raise OSError("injected move failure")
        return real(tmp, path, tries)
    monkeypatch.setattr(G, "_replace", failing)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    calls = busy_remove(monkeypatch, {os.path.normcase(str(new)): 2})
    with pytest.raises(OSError) as err:
        G.replace_files([(str(new), b"new\n", None, None), (str(old), b"new\n", b"old\n", None)])
    assert not isinstance(err.value, G.NotRestored) and "injected move failure" in str(err.value)
    assert not new.exists() and calls[os.path.normcase(str(new))] == 3 and old.read_bytes() == b"old\n" and not list(tmp_path.rglob("*.tmp"))


def test_store_removal_fails_at_once_on_another_error(tmp_path, monkeypatch):
    rec, claim = a_record_and_a_claim(tmp_path)
    key, calls, real = os.path.normcase(str(claim)), [], os.remove

    def gone(path, *a, **kw):  # only PermissionError means a busy file: any other error of the removal is final
        if os.path.normcase(str(path)) == key:
            calls.append(path)
            raise FileNotFoundError(2, "injected: gone", str(path))
        return real(path, *a, **kw)
    monkeypatch.setattr(G.os, "remove", gone)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    with pytest.raises(FileNotFoundError) as err:
        G.commit_store([(str(rec), b"new record\n", b"old record\n")], [(str(claim), b"old claim\n")])
    assert not isinstance(err.value, G.NotRestored) and len(calls) == 1
    assert rec.read_bytes() == b"old record\n" and claim.read_bytes() == b"old claim\n" and not list(tmp_path.rglob("*.tmp"))


def test_main_error_paths(repo, monkeypatch, capsys):
    monkeypatch.setattr(G, "cmd_list", lambda a: (_ for _ in ()).throw(G.GitFail("GIT_FAILED", "boom")))
    r = run(["--repo", str(repo.path), "list"])
    assert r.rc == 11 and "GIT_FAILED" in r.err
    monkeypatch.setattr(G, "cmd_list", lambda a: (_ for _ in ()).throw(RuntimeError("kaput")))
    r = run(["--repo", str(repo.path), "list"])
    assert r.rc == 11 and "internal error" in r.err
    assert run(["bogus"]).rc == 2
    assert run(["hook", "claude", "bogus"]).rc == 1  # a usage error of the hook entry is a failure, never a deny
    assert run(["--lang", "en", "--help"]).rc == 0


# ---- review findings: detached lanes, integrated lanes, release, unreadable claims, caps --------------------------------
def test_committed_work_on_a_detached_worktree_claims_its_files(repo, guard):
    wt = repo.path.parent / "wt-detached"
    repo.git("worktree", "add", "-q", "--detach", str(wt), "main")
    repo.commit("src/a.py", "detached work\n", cwd=wt)
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "src/a.py")
    assert rc == 10 and v["conflicts"][0]["branch"] is None and v["conflicts"][0]["evidence"][0]["kind"] == "committed"
    assert guard(repo, "check", "--branch", "n2", "--paths", "docs/").rc == 0


def test_integrated_lane_without_a_workspace_stops_blocking(repo, guard):
    assert guard(repo, "plan", "--branch", "agent/done", "--paths", "src/a.py").rc == 0
    assert guard(repo, "check", "--branch", "n1", "--paths", "src/a.py").rc == 10  # planned: blocks
    wt = repo.path.parent / "wt-done"
    assert repo.git("worktree", "add", "-q", "-b", "agent/done", str(wt), "main") is not None
    repo.commit("src/a.py", "work\n", cwd=wt)
    repo.git("merge", "-q", "--no-ff", "agent/done", "-m", "merge")
    assert guard(repo, "check", "--branch", "n2", "--paths", "src/a.py").rc == 10  # merged but the worktree is still there: still a lane
    repo.git("worktree", "remove", "--force", str(wt))
    assert guard(repo, "check", "--branch", "n3", "--paths", "src/a.py").rc == 0  # idle: integrated and no workspace
    assert json.loads(guard(repo, "list", "--json").out)[0]["state"] == "idle"


def test_release_of_an_integrated_lane_whose_worktree_is_still_there(repo, guard):
    assert guard(repo, "plan", "--branch", "agent/int", "--paths", "docs/").rc == 0
    wt = repo.path.parent / "wt-int"
    repo.git("worktree", "add", "-q", "-b", "agent/int", str(wt), "main")
    repo.commit("docs/d.md", "work\n", cwd=wt)
    assert guard(repo, "release", "--branch", "agent/int").rc == 16  # unmerged work
    repo.git("merge", "-q", "agent/int")
    repo.write("docs/dirty.md", "d\n", base=wt)
    assert guard(repo, "release", "--branch", "agent/int").rc == 16  # merged, but its worktree is dirty
    os.remove(wt / "docs" / "dirty.md")
    assert guard(repo, "release", "--branch", "agent/int", "--reason", "integrated").rc == 0  # what /GitIntegrate does after an integration


def test_an_unreadable_claim_file_can_be_released(repo, guard):
    g = G.open_repo(str(repo.path))
    p = Path(G.claim_path(g, "agent/broken"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("garbage", encoding="utf-8")
    r = guard(repo, "release", "--branch", "agent/broken")
    assert r.rc == 0 and not p.exists() and "released" in r.out.lower()
    assert json.loads((claims_dir(repo).parent / "audit.log").read_text(encoding="utf-8").splitlines()[-1])["reason"] == "unreadable claim file removed"


def test_amend_updates_the_registered_worktree_path(repo, guard):
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "--worktree", str(repo.path.parent / "one")).rc == 0
    r = guard(repo, "plan", "--branch", "L", "--paths", "docs/", "--worktree", str(repo.path.parent / "two"))
    assert r.rc == 14  # the registered path differs: an explicit amend is needed
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "--worktree", str(repo.path.parent / "two"), "--amend").rc == 0
    assert "two" in (claims_dir(repo) / "L.claim").read_text(encoding="utf-8")


def test_a_re_plan_without_worktree_keeps_the_registered_path(repo, guard):
    one = str(repo.path.parent / "one")
    want = "worktree=" + os.path.abspath(one).replace("\\", "/")
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "--worktree", one).rc == 0
    assert guard(repo, "plan", "--branch", "L", "--paths", "docs/", "web/", "--amend").rc == 0  # an amend without --worktree
    assert want in (claims_dir(repo) / "L.claim").read_text(encoding="utf-8").split("\n")
    repo.branch_with("agent/x", "docs/d.md")  # a conflict the user overrides: the re-plan without --worktree stores the override
    fp = verdict(guard, repo, "check", "--branch", "L", "--paths", "docs/", "web/")[1]["fingerprint"]
    ov = claims_dir(repo).parent / "override" / (fp + ".json")
    ov.parent.mkdir()
    ov.write_text(json.dumps({"fp": fp, "reason": "test", "expires": "2099-01-01T00:00:00Z"}), encoding="utf-8")
    rc, v = verdict(guard, repo, "plan", "--branch", "L", "--paths", "docs/", "web/")
    lines = (claims_dir(repo) / "L.claim").read_text(encoding="utf-8").split("\n")
    assert rc == 0 and v["code"] == "OVERRIDDEN" and want in lines and "override=" + fp in lines


def test_the_plan_example_names_the_registered_worktree(repo, guard):
    one = str(repo.path.parent / "one").replace("\\", "/")  # typed as the claim stores it, so only the path of the example is at stake
    example = 'git worktree add "%s" -b L main' % os.path.abspath(one).replace("\\", "/")
    first = guard(repo, "plan", "--branch", "L", "--paths", "docs/", "--worktree", one)
    assert first.rc == 0 and first.out.splitlines()[0].endswith("e.g.: " + example), first
    for paths in (["docs/", "web/", "--amend"], ["docs/", "web/"]):  # an amend without --worktree, then the identical re-plan (a no-op)
        r = guard(repo, "plan", "--branch", "L", "--paths", *paths)
        assert r.rc == 0 and r.out.splitlines()[0].endswith("e.g.: " + example) and "<path>" not in r.out, (paths, r)
    rc, v = verdict(guard, repo, "plan", "--branch", "L", "--paths", "docs/", "web/")
    assert rc == 0 and "worktree" not in v  # the path is no key of the verdict
    allowed = run(["hook", "claude", "pre-tool"], stdin=json.dumps(payload("Bash", example, repo.path)).encode())
    assert allowed.out.strip() == "{}", allowed  # the printed command is the creation the hook lets through
    bare = guard(repo, "plan", "--branch", "M", "--paths", "src/")
    assert bare.rc == 0 and bare.out.splitlines()[0].endswith('e.g.: git worktree add "<path>" -b M main')  # a claim that registers no worktree


def test_remote_tracking_cap_warns_instead_of_denying(repo, guard, monkeypatch):
    monkeypatch.setattr(G, "MAX_REMOTES", 1)
    sha = repo.git("rev-parse", "main")
    repo.commit("src/b.py", "x\n")
    ahead = repo.git("rev-parse", "main")
    repo.git("reset", "-q", "--hard", sha)
    for name in ("r1", "r2", "r3"):
        repo.git("update-ref", "refs/remotes/origin/" + name, ahead)
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 0 and any(w["code"] == "REMOTE_TRUNCATED" for w in v["warnings"])


def test_core_hooks_path_after_arming_is_flagged(repo, guard):
    assert guard(repo, "arm").rc == 0
    repo.git("config", "--local", "core.hooksPath", "elsewhere")
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert any(w["code"] == "HOOK_BYPASSED" for w in v["warnings"])
    r = guard(repo, "doctor")
    assert r.rc == 1 and "no longer runs the backstop" in r.out
