"""Behaviours added after the adversarial self-review: lane states, bare repositories, detached lanes, encodings, budgets, hook details."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from conftest import G, Repo, payload, run
from test_gitlayer import common, hook_path, repo_git_raw, vetoed
from test_hook import denied, hook, plan
from test_plan_store import claims_dir, verdict


def test_fresh_branch_without_a_worktree_is_still_a_lane(repo, guard):
    assert guard(repo, "plan", "--branch", "agent/fresh", "--paths", "src/a.py").rc == 0
    repo.git("branch", "agent/fresh")  # created at the target tip, no worktree yet, no commits: not an integrated lane
    assert guard(repo, "check", "--branch", "n", "--paths", "src/a.py").rc == 10
    assert json.loads(guard(repo, "list", "--json").out)[0]["state"] == "active"
    repo.commit("docs/d.md", "main moves on\n")  # the target moves beyond the branch tip: still a fresh lane (the tip equals the plan's base)
    assert guard(repo, "check", "--branch", "n2", "--paths", "src/a.py").rc == 10


def test_case_variant_branch_names_find_their_claim(repo, guard):
    assert guard(repo, "plan", "--branch", "agent/Case", "--paths", "docs/").rc == 0
    repo.git("branch", "agent/case-two")
    rows = json.loads(guard(repo, "list", "--json").out)
    assert rows[0]["state"] == "planned"  # a different name is not that lane
    assert G.real_branch({"branch": "Agent/CASE-two"}, {"agent/case-two": "sha"}) == "agent/case-two"


def test_bare_repository_layout_is_guarded(tmp_path, guard):
    seed = Repo(tmp_path / "seed")
    seed.path.mkdir()
    seed.git("init", "-q")
    seed.write("src/a.py", "x\n")
    seed.git("add", "-A")
    seed.git("commit", "-q", "-m", "init")
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed.path), str(bare)], check=True, env=os.environ.copy())
    assert guard(bare, "plan", "--branch", "agent/b", "--paths", "docs/").rc == 0
    wt = tmp_path / "wt-b"
    subprocess.run(["git", "-C", str(bare), "worktree", "add", "-q", "-b", "agent/other", str(wt), "main"], check=True, env=os.environ.copy())
    Repo(tmp_path).write("src/a.py", "edit\n", base=wt)
    r = guard(bare, "check", "--branch", "agent/c", "--paths", "src/a.py")
    assert r.rc == 10 and "agent/other" in r.out  # a bare repository with linked worktrees: the lanes are the worktrees
    g = G.open_repo(str(bare))
    assert g.top is None and g.common


def test_locked_worktree_that_is_missing_is_unknown(repo, guard):
    wt = repo.worktree("wt-offline", "agent/offline")
    repo.git("worktree", "lock", str(wt))
    shutil.rmtree(wt)
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/")
    assert rc == 11 and v["unknowns"][0]["code"] == "WORKTREE_UNREADABLE"


def test_manifest_encodings(repo, guard, tmp_path):
    f = tmp_path / "utf16.txt"
    f.write_bytes("docs/\r\nsrc/a.py\r\n".encode("utf-16"))  # what PowerShell 5.1 `>` writes
    assert guard(repo, "check", "--branch", "n", "--manifest", str(f)).rc == 0
    g = tmp_path / "ansi.txt"
    g.write_bytes("docs/\xe9.md\n".encode("latin-1"))
    r = guard(repo, "check", "--branch", "n", "--manifest", str(g))
    assert r.rc == 12 and "not UTF-8" in r.out


def test_plan_prints_a_quoted_creation_command(repo, guard):
    r = guard(repo, "plan", "--branch", "agent/q", "--paths", "docs/", "--worktree", str(repo.path.parent / "with space"))
    assert r.rc == 0 and 'git worktree add "' in r.out and "with space" in r.out


def test_unresolvable_target_is_an_error(repo, guard):
    rc, v = verdict(guard, repo, "check", "--branch", "n", "--paths", "docs/", "--target", "no-such")
    assert rc == 11 and "does not resolve" in v["unknowns"][0]["text"]


def test_no_username_does_not_break_plan(repo, guard, monkeypatch):
    monkeypatch.setattr(G.getpass, "getuser", lambda: (_ for _ in ()).throw(OSError("no user")))
    assert guard(repo, "plan", "--branch", "agent/nouser", "--paths", "docs/").rc == 0
    assert "(unknown)" in (claims_dir(repo) / "agent" / "nouser.claim").read_text(encoding="utf-8")


def test_comparison_has_a_time_budget(repo):
    repo.branch_with("agent/x", "src/a.py")
    snap = G.gather(G.open_repo(str(repo.path)))
    snap["deadline"] = time.monotonic() - 1
    with pytest.raises(G.GitFail) as err:
        G.judge(snap, {}, [], "n", [G.parse_entry("src/")], None)
    assert err.value.code == "BUDGET_EXCEEDED"


def test_start_process_without_arguments_is_harmless():
    assert G.interpret("Start-Process git -ArgumentList", "C:/repo") == []


def test_arm_can_be_rerun_over_its_own_chained_hook(repo, guard):
    hook_path(repo).parent.mkdir(exist_ok=True)
    hook_path(repo).write_text("#!/bin/sh\ncat >/dev/null\n", encoding="utf-8", newline="\n")
    assert guard(repo, "arm").rc == 0 and (hook_path(repo).parent / "reference-transaction.magos-prev").is_file()
    assert guard(repo, "arm").rc == 0  # an upgrade does not trip over the chained hook it created itself


def test_a_big_transaction_is_read_in_linear_time(repo, guard):
    assert guard(repo, "arm").rc == 0
    sha = repo.git("rev-parse", "HEAD")
    lines = "".join("%s %s refs/tags/t%d\n" % ("0" * 40, sha, i) for i in range(5000))
    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no sh")
    start = time.monotonic()
    r = subprocess.run([sh, str(hook_path(repo)), "prepared"], input=lines.encode(), capture_output=True, cwd=str(repo.path),
                       env=dict(os.environ, GIT_DIR=str(common(repo))))
    assert r.returncode == 0 and time.monotonic() - start < 20


def test_the_veto_message_warns_about_a_half_done_checkout(repo, guard):
    assert guard(repo, "arm").rc == 0
    assert "git status" in vetoed(repo, "branch", "x1")


def test_detached_worktrees_need_a_manifest_keyed_by_their_directory(repo, guard):
    reason = denied(hook(repo, command="git worktree add --detach ../wt-det"))
    assert "detached/wt-det" in reason and "plan --branch detached/wt-det" in reason
    plan(guard, repo, "detached/wt-det", "docs/", worktree=repo.path.parent / "wt-det")
    assert denied(hook(repo, command="git worktree add --detach ../wt-det")) is None
    assert denied(hook(repo, command="git worktree add ../wt-det HEAD")) is None
    repo.git("branch", "existing")
    assert denied(hook(repo, command="git worktree add ../elsewhere existing")) is None  # an existing branch is not a new lane
    wt = repo.path.parent / "wt-det"
    repo.git("worktree", "add", "-q", "--detach", str(wt), "main")
    assert json.loads(guard(repo, "list", "--json").out)[0]["state"] == "active"  # the registered directory exists now


def test_missing_git_denies_a_lane_creation_instead_of_waving_it_through(repo, monkeypatch):
    def nogit(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(G.subprocess, "run", nogit)
    reason = denied(hook(repo, command="git worktree add ../w -b agent/x"))
    assert "guard error" in reason and "not installed or not on PATH" in reason
    assert hook(repo, command="echo hi").out.strip() == "{}"
