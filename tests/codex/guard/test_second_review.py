"""Behaviours added by the second review: own-path exclusion, linear-time parsing, one budget per hook call, script detection, claim defaults."""
from __future__ import annotations

import json
import os
import time

import pytest

from conftest import G, time_budget
from test_detector import ECHO_PIPE_FORMS
from test_hook import denied, hook, plan
from test_plan_store import claims_dir, verdict


def write_claim(repo, name, *lines):
    path = claims_dir(repo).joinpath(*name.split("/")).with_suffix(".claim")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(("state=active", "branch=" + name) + lines) + "\n", encoding="utf-8")


# ---- own worktree ---------------------------------------------------------------------------------------------------
def test_a_worktree_of_another_branch_at_the_planned_path_is_still_compared(repo, guard):
    wt = repo.worktree("wt-b", "agent/b")
    repo.write("src/a.py", "edit\n", base=wt)
    r = guard(repo, "plan", "--branch", "agent/a", "--paths", "src/a.py", "--worktree", str(wt))
    assert r.rc == 10 and "agent/b" in r.out  # naming another lane's worktree as the planned path hides nothing


def test_a_detached_lane_is_not_compared_with_its_own_worktree(repo, guard):
    wt = repo.path.parent / "wt-det"
    plan(guard, repo, "detached/wt-det", "docs/", worktree=wt)
    repo.git("worktree", "add", "-q", "--detach", str(wt), "main")
    repo.write("docs/d.md", "edit\n", base=wt)
    assert guard(repo, "check", "--branch", "detached/wt-det", "--paths", "docs/").rc == 0
    r = guard(repo, "check", "--branch", "agent/n", "--paths", "docs/")
    assert r.rc == 10 and "wt-det" in r.out  # every other lane still sees it


@pytest.mark.skipif(os.name != "nt", reason="drive letters and case-insensitive paths")
def test_replanning_with_another_spelling_of_the_worktree_path_is_a_no_op(repo, guard):
    wt = repo.path.parent / "wt-q"
    plan(guard, repo, "agent/q", "docs/", worktree=wt)
    assert guard(repo, "plan", "--branch", "agent/q", "--paths", "docs/", "--worktree", str(wt).upper()).rc == 0


# ---- linear-time parsing --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cmd", ["echo" + " " * 190000 + "git x", "git " + "update-ref " * 18000, "git " + ")" * 190000, "git " + "-git " * 45000],
                         ids=["echo-spaces", "update-ref", "parens", "git-options"])
def test_worst_case_command_lines_parse_in_linear_time(cmd):
    start = time.monotonic()
    G.interpret(cmd, ".")
    G.protected(cmd)
    G._git_subcommands(cmd)
    assert time.monotonic() - start < time_budget(5)


def test_update_ref_stdin_and_echo_pipes_are_still_read():
    assert [r["names"] for r in G.interpret("git update-ref --stdin <<< 'create refs/heads/agent/u HEAD'", ".")] == [["agent/u"]]
    assert len(ECHO_PIPE_FORMS) >= 3
    for row in ECHO_PIPE_FORMS:  # echoed text piped into a shell, from the data file
        assert [r["names"] for r in G.interpret(row["cmd"], ".")] == [row["names"]], row


def test_every_git_call_is_checked_for_an_alias(repo):
    assert sorted(G._git_subcommands("git status && git mkwt y; echo git")) == ["mkwt", "status"]
    repo.git("config", "alias.mkwt", "worktree add")
    reason = denied(hook(repo, command="git status && git mkwt ../w -b agent/x"))
    assert reason and "agent/x" in reason


def test_an_over_long_command_is_denied_with_its_real_reason(repo, guard):
    repo.branch_with("agent/x", "src/a.py")  # a parallel lane engages branch-only checks
    long = "git status " + "x" * (G.MAX_TEXT + 1)
    assert "longer than %d characters" % G.MAX_TEXT in denied(hook(repo, command=long))
    plan(guard, repo, "agent/y", "docs/")
    assert "too long to inspect" in denied(hook(repo, command=long))  # with a claim it may also edit the guard's state


# ---- budgets --------------------------------------------------------------------------------------------------------
def test_declared_only_claimants_watch_the_clock():
    e = G.parse_entry("src/")
    planned = {"key": "k", "branch": "agent/p", "worktrees": [], "declared": [e], "paths": {"committed": set(), "uncommitted": set()}}
    with pytest.raises(G.GitFail) as err:
        G.evaluate([e], [planned], time.monotonic() - 1)
    assert err.value.code == "BUDGET_EXCEEDED"
    busy = dict(planned, declared=[], paths={"committed": {"src/f%d.py" % i for i in range(300)}, "uncommitted": set()})
    assert len(G.evaluate([e], [busy], time.monotonic() + 60)[0]["evidence"][0]["files"]) == 300


def test_one_hook_call_shares_one_git_budget(repo, monkeypatch):
    monkeypatch.setattr(G, "BUDGET_S", 0.0)
    assert "time budget exhausted" in denied(hook(repo, command="git worktree add ../w -b agent/x"))
    assert G.HOOK_DEADLINE is None
    assert G.Git(str(repo.path)).deadline > time.monotonic() + 10  # outside a hook call every Git has its own budget


def test_a_named_worktree_is_denied_when_its_check_fails_in_auto_mode(repo, guard, monkeypatch):
    plan(guard, repo, "agent/x", "docs/")

    def broken(*a, **k):
        raise G.GitFail("GIT_FAILED", "simulated")
    monkeypatch.setattr(G, "check_name", broken)
    assert "simulated" in denied(hook(repo, command="git worktree add ../w -b agent/x"))
    assert denied(hook(repo, command="git branch agent/x")) is None  # auto mode allows an unanalysable branch-only creation


def test_a_vanished_working_directory_is_not_a_missing_git(tmp_path, monkeypatch):
    def gone(*a, **k):
        raise FileNotFoundError("cwd")
    monkeypatch.setattr(G.subprocess, "run", gone)
    with pytest.raises(G.GitFail) as err:
        G.Git(str(tmp_path / "gone")).run("--version")
    assert err.value.code == "GIT_FAILED" and "no longer exists" in str(err.value)
    with pytest.raises(G.GitFail) as err:
        G.Git(str(tmp_path)).run("--version")
    assert err.value.code == "GIT_MISSING"


# ---- detection, input and claims ------------------------------------------------------------------------------------
def test_the_script_after_option_values_is_read(tmp_path):
    for name in ("x.ps1", "x.sh"):
        (tmp_path / name).write_text("git branch sneaky\n", encoding="utf-8")
    for cmd in ("powershell -ExecutionPolicy Bypass -File x.ps1", "bash -o pipefail x.sh", "bash x.sh", "pwsh -NoProfile -File x.ps1"):
        assert [r["names"] for r in G.interpret(cmd, str(tmp_path))] == [["sneaky"]], cmd


def test_override_wants_the_printed_fingerprint(repo, guard):
    r = guard(repo, "override", "--fingerprint", "../../x", "--reason", "r")
    assert r.rc == 2 and "12 hex digits" in r.err
    assert not (claims_dir(repo).parent / "override").exists()


def test_plan_takes_no_target(repo, guard):
    assert guard(repo, "plan", "--branch", "agent/t", "--paths", "docs/", "--target", "main").rc == 2  # enforcement judges against the resolved target
    assert guard(repo, "check", "--branch", "agent/t", "--paths", "docs/", "--target", "main").rc == 0


def test_malformed_utf16_is_an_encoding_error():
    for raw in (b"\xff\xfe\x00\xd8", b"\xff\xfea"):
        with pytest.raises(G.ManifestError) as err:
            G.decode_manifest(raw)
        assert err.value.code == "ENCODING"


def test_a_claim_without_optional_fields_is_read(repo, guard):
    write_claim(repo, "agent/bare", "entry=docs/")
    rows = json.loads(guard(repo, "list", "--json", "--drift").out)
    assert rows[0]["branch"] == "agent/bare" and rows[0]["state"] == "planned"
    assert denied(hook(repo, command="git worktree add ../w -b agent/bare")) is None


def test_list_drift_survives_an_invalid_entry(repo, guard):
    write_claim(repo, "agent/bad", "worktree=", "created=2026-01-01T00:00:00Z", "entry=../outside")
    rows = json.loads(guard(repo, "list", "--json", "--drift").out)
    assert rows[0]["branch"] == "agent/bad" and rows[0]["drift"] == []
    rc, v = verdict(guard, repo, "check", "--branch", "agent/n", "--paths", "docs/")
    assert rc == 11 and v["unknowns"][0]["code"] == "CLAIM_UNPARSEABLE"
