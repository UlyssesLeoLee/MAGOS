"""1.0.2 host-hook hardening: repository redirects, missing cd targets, hooked tools, the executable search order, user-only spellings,
undecided engagement, override through plan only, JSON errors and silent Git failures."""
from __future__ import annotations

import base64
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import G, ROOT, SCRIPT, SH, Repo, crashed, payload, retried, run, time_budget

NOMAN = "a planned file manifest must be registered"
UNPARSE = "cannot tell which branch this creates"
REDIRECT = "the repository is redirected by --git-dir/GIT_DIR and cannot be resolved; use git -C <repo>"
UNPLAN = "names the branch or worktree itself"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
SESSIONS = ("empty", "clean", "lane")


def P(path):
    return str(path).replace("\\", "/")


def same_dir(a, b):
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def make(tmp_path, name):
    r = Repo(tmp_path / name)
    r.path.mkdir()
    r.git("init", "-q")
    for rel in ("src/a.py", "src/b.py", "docs/d.md", "README.md"):
        r.write(rel, "base\n")
    r.git("add", "-A")
    r.git("commit", "-q", "-m", "init")
    return r


def hook_body(body):
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=body)  # conftest.run makes a call again whose git child the machine killed
    assert r.rc == 0, r
    return r


def hook(cwd, command=None, tool="Bash", host="claude", **tool_input):
    r = run(["--lang", "en", "hook", host, "pre-tool"], stdin=json.dumps(payload(tool, command, cwd, **tool_input)).encode("utf-8"))
    assert r.rc == 0, r
    return r


def verdict(r, quiet=True):
    """None for an allow, else the deny reason; quiet: engagement was decided, so stderr is empty."""
    if quiet:
        assert r.err == "", r.err
    if r.out.strip() == "{}":
        return None
    obj = json.loads(r.out)
    assert obj["decision"] == "block" and obj["hookSpecificOutput"]["permissionDecision"] == "deny" and r.out.isascii()
    return obj["reason"]


def plan(guard, repo, branch, *paths, worktree=None):
    args = ["plan", "--branch", branch, "--paths", *(paths or ("docs/",))] + (["--worktree", str(worktree)] if worktree else [])
    r = guard(repo, *args)
    assert r.rc == 0, r.out + r.err
    return r


def branches(repo):
    return repo.git("branch", "--list", "--format=%(refname:short)").split()


@pytest.fixture
def target(repo):
    """Repository A: an unmerged lane (agent/other) and no claim."""
    repo.branch_with("agent/other", "src/a.py")
    return repo


def session(kind, tmp_path):
    """A session directory outside any repository, another clean repository, or another repository that holds a lane."""
    if kind == "empty":
        d = tmp_path / "empty"
        d.mkdir()
        return d, None
    r = make(tmp_path, kind)
    if kind == "lane":
        r.branch_with("agent/l", "src/b.py")
    return r.path, r


# ---- --git-dir / GIT_DIR ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", SESSIONS)
def test_git_dir_redirect_is_judged_in_the_redirected_repository(target, guard, tmp_path, kind):
    cwd, own = session(kind, tmp_path)
    if own is not None and kind == "lane":
        plan(guard, own, "x")  # a claim for the same name in the session repository allows nothing elsewhere
    gd = P(target.path / ".git")
    for cmd in ("git --git-dir=%s branch x" % gd, "git --git-dir %s branch x" % gd):
        reason = verdict(hook(cwd, cmd))
        assert reason and NOMAN in reason and "plan --branch x" in reason, (cmd, reason)
        assert ('--repo "%s"' % P(target.path)).lower() in reason.replace("\\", "/").lower()  # the plan command names repository A
    assert "x" not in branches(target)
    plan(guard, target, "x")
    for cmd in ("git --git-dir=%s branch x" % gd, "git --git-dir %s branch x" % gd):
        assert verdict(hook(cwd, cmd)) is None, cmd
    subprocess.run(["git", "--git-dir=" + gd, "branch", "x"], cwd=str(cwd), capture_output=True, stdin=subprocess.DEVNULL, check=True)
    assert "x" in branches(target)  # git acts on the repository the guard judged


def test_a_claim_in_the_session_repository_does_not_allow_a_redirected_creation(target, guard, tmp_path):
    cwd, c = session("lane", tmp_path)
    plan(guard, c, "x")
    gd = P(target.path / ".git")
    for cmd in ("GIT_DIR=%s git branch x" % gd, "git --git-dir=%s branch x" % gd):
        assert NOMAN in (verdict(hook(cwd, cmd)) or ""), cmd
    assert verdict(hook(cwd, "git branch x")) is None  # the claim does allow the creation in its own repository


def records(tool, cmd, cwd, name=None):
    """The creation records the hook judges for a payload of `tool` (the tool names the shell that runs the command)."""
    return [c for c in G.extract(payload(tool, cmd, cwd))[0] if name is None or c["names"] == [name]]


def test_git_dir_environment_spellings_redirect_the_judged_repository(target, tmp_path):
    cwd, _b = session("clean", tmp_path)
    gd = P(target.path / ".git")
    cases = [
        ("Bash", "GIT_DIR=%s git branch y1" % gd, "y1"),
        ("Bash", "env GIT_DIR=%s git branch y2" % gd, "y2"),
        ("Bash", "GIT_DIR=%s; git branch y3" % gd, "y3"),  # standalone, not exported
        ("Bash", "export GIT_DIR=%s; git branch y4" % gd, "y4"),
        ("Bash", "GIT_DIR=%s; export GIT_DIR; git branch y5" % gd, "y5"),
        ("PowerShell", "$env:GIT_DIR='%s'; git branch y6" % gd, "y6"),
        ("PowerShell", "$env:GIT_DIR = '%s'; git branch y7" % gd, "y7"),
        ("Bash", "set GIT_DIR=%s&& git branch y8" % gd, "y8"),  # cmd's set, typed into bash: bash's set leaves GIT_DIR alone
        ("Bash", 'cmd /c "set GIT_DIR=%s&& git branch y9"' % gd, "y9"),
    ]
    for tool, cmd, name in cases:
        reason = verdict(hook(cwd, cmd, tool=tool))
        assert reason and NOMAN in reason and name in reason, (cmd, reason)
        crs = records(tool, cmd, cwd, name)
        redirected = [c for c in crs if c["redirect"] is True]
        assert redirected and all(same_dir(c["gitdir"], target.path / ".git") for c in redirected), (cmd, crs)
        if name in ("y3", "y8"):  # judged in both repositories: the redirect target and the directory it runs in
            assert len(crs) == 2 and [c for c in crs if c["redirect"] is False and c["gitdir"] is None], crs
        else:
            assert len(crs) == 1, (cmd, crs)


def test_git_dir_spellings_are_judged_by_the_shell_that_runs_them(target, tmp_path):
    """A GIT_DIR change that the running shell may not perform is judged both ways, so the guard never judges only a repository git does
    not use; on Windows every case of GIT_DIR redirects git, and text a line runs ($(..), here-documents, update-ref --stdin, gh) is judged
    in the directory and GIT_DIR state it runs in."""
    lanes = target  # L: another lane exists, so a creation there is denied without a claim
    clean = make(tmp_path, "clean")  # C: a single lane, so a creation there is allowed
    lgd, cgd = P(lanes.path / ".git"), P(clean.path / ".git")
    hops = [tmp_path / ("d%d" % k) for k in range(9)]  # more directories than the hook judges text in
    for d in hops:
        d.mkdir()
    deny_from_lanes = [  # session in L, the line names C: git still runs in L unless the shell really redirects it
        ("PowerShell", "export GIT_DIR=%s; git branch z1" % cgd),
        ("Bash", "$env:GIT_DIR='%s'; git branch z2" % cgd),
        ("Bash", "set GIT_DIR=%s; git branch z3" % cgd),
        ("Bash", "export GIT_DIR=%s; sudo git branch z4" % cgd),
        ("Bash", "export GIT_DIR=%s; wsl git branch z5" % cgd),
        ("PowerShell", "[Environment]::SetEnvironmentVariable('GIT_DIR', '%s', 'User'); git branch z6" % cgd),
    ]
    for tool, cmd in deny_from_lanes:
        reason = verdict(hook(lanes.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    deny_from_clean = [  # session in C, the line redirects to L: judged in L
        ("Bash", "declare -x GIT_DIR=%s; git branch z7" % lgd),
        ("PowerShell", "Set-Item Env:GIT_DIR %s; git branch z8" % lgd),
        ("PowerShell", "New-Item -Path Env: -Name GIT_DIR -Value %s; git branch z9" % lgd),
        ("PowerShell", "[Environment]::SetEnvironmentVariable('GIT_DIR', '%s'); git branch z10" % lgd),
        ("Bash", "export GIT_DIR=%s; rm Env:GIT_DIR; git branch z11" % lgd),  # bash's rm does not touch the environment
        ("terminal", "export GIT_DIR=%s; git branch z12" % lgd),  # a shell the hook cannot name
        ("Bash", "export GIT_DIR=%s; echo $(git branch z13)" % lgd),
        ("Bash", "export GIT_DIR=%s; git update-ref --stdin <<< 'create refs/heads/z14 HEAD'" % lgd),
        ("Bash", "cd %s && bash <<EOF\ngit branch z15\nEOF" % P(lanes.path)),
        ("Bash", "cd %s && echo `git branch z16`" % P(lanes.path)),
        ("Bash", "GIT_DIR=%s bash <<EOF\ngit branch z23\nEOF" % lgd),  # the shell that reads the text has its own GIT_DIR
        ("Bash", 'GIT_DIR=%s sh <<< "git branch z24"' % lgd),
    ]
    for tool, cmd in deny_from_clean:
        reason = verdict(hook(clean.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    reason = verdict(hook(clean.path, "export GIT_DIR=%s; gh pr checkout 5" % lgd))
    assert reason and UNPLAN in reason
    assert verdict(hook(lanes.path, "export GIT_DIR=%s; git branch z17" % cgd)) is None  # bash really exports it: judged in C only
    assert verdict(hook(lanes.path, "$env:GIT_DIR='%s'; git branch z18" % cgd, tool="PowerShell")) is None
    assert verdict(hook(lanes.path, "$env:GIT_DIR='%s'; Remove-Item Env:GIT_DIR; git branch z19" % lgd, tool="PowerShell")) is not None
    cds = "; ".join("cd %s" % P(d) for d in hops)
    reason = verdict(hook(lanes.path, "%s; echo $(git branch z20)" % cds))
    assert reason and UNPARSE in reason and "more directory or GIT_DIR states than the hook judges" in reason
    empty, _ = session("empty", tmp_path)
    reason = verdict(hook(empty, "%s; cd %s; echo $(git branch z20)" % (cds, P(lanes.path))))  # also where the session is no repository
    assert reason and "more directory or GIT_DIR states than the hook judges" in reason
    assert UNPARSE in (verdict(hook(lanes.path, "git update-ref --stdin < refs.txt")) or "")  # the names arrive from a file the hook cannot read
    assert verdict(hook(lanes.path, "git update-ref --stdin <<< 'delete refs/heads/agent/old'")) is None
    lower = "git_dir=%s git branch z21" % lgd
    if sys.platform == "win32":  # git reads the environment without regard to case
        assert NOMAN in (verdict(hook(clean.path, lower)) or "")
        assert NOMAN in (verdict(hook(clean.path, "export GIT_DIR=%s; unset git_dir; git branch z22" % lgd)) or "")
        bash = shutil.which("bash")
        sysname = subprocess.run([bash, "-c", "uname -s"], capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                                 timeout=60).stdout if bash else b""
        if sysname.startswith((b"MINGW", b"MSYS")):  # Git Bash (not the WSL launcher)
            subprocess.run([bash, "-c", "git_dir=%s git branch real-lower" % cgd], cwd=str(lanes.path), capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW, timeout=120)
            assert "real-lower" in branches(clean) and "real-lower" not in branches(lanes)  # the premise: a lower-case git_dir redirects git
    else:
        assert verdict(hook(clean.path, lower)) is None  # another variable: git stays in C


def test_every_git_dir_change_reaches_the_judged_records(tmp_path):
    """Each GIT_DIR assignment, export change and removal the detector knows, as (redirect, gitdir) of the records it leaves."""
    g = P(tmp_path / "g" / ".git")
    definite, both, none, dynamic = [(True, g)], [(False, None), (True, g)], [(False, None)], [(True, None)]
    cases = [
        ("Bash", "export -n GIT_DIR=%s; git branch y" % g, none),
        ("Bash", "export GIT_DIR=%s; declare +x GIT_DIR; git branch y" % g, none),
        ("Bash", "export GIT_DIR=%s; unset -f GIT_DIR; git branch y" % g, definite),  # -f names a function
        ("Bash", "export GIT_DIR=%s; unset -v GIT_DIR; git branch y" % g, none),
        ("Bash", "typeset -x GIT_DIR=%s; git branch y" % g, definite),
        ("Bash", "declare GIT_DIR=%s; git branch y" % g, both),  # not exported here; maybe exported before
        ("Bash", "export GIT_DIR=%s; env -i git branch y" % g, none),
        ("Bash", "export GIT_DIR=%s; env --unset=GIT_DIR git branch y" % g, none),
        ("Bash", "export GIT_DIR=%s; env -uGIT_DIR git branch y" % g, none),
        ("Bash", "export GIT_DIR=%s; exec -c git branch y" % g, none),
        ("Bash", "export GIT_DIR=%s; sudo -E git branch y" % g, definite),
        ("Bash", "export GIT_DIR=%s; sudo git branch y" % g, both),
        ("Bash", "sudo GIT_DIR=%s git branch y" % g, definite),
        ("Bash", 'cmd /c "set /p GIT_DIR=<f.txt& git branch y"', dynamic),
        ("Bash", 'cmd /c "set GIT_DIR=%s& set GIT_DIR=& git branch y"' % g, none),
        ("PowerShell", "$env:GIT_DIR='%s'; Clear-Item Env:GIT_DIR; git branch y" % g, none),
        ("PowerShell", "$env:GIT_DIR='%s'; Set-Item Env:GIT_DIR $null; git branch y" % g, none),
        ("PowerShell", "Set-Item -Path Env:GIT_DIR; git branch y", dynamic),
        ("PowerShell", "$env:GIT_DIR += '%s'; git branch y" % g, dynamic),
        ("PowerShell", "${env:GIT_DIR} = '%s'; git branch y" % g, definite),
        ("PowerShell", "$env:GIT_DIR='%s'; [Environment]::SetEnvironmentVariable('GIT_DIR', $null); git branch y" % g, none),
        ("PowerShell", "$env:GIT_DIR='%s'; Remove-Item -Path Env:\\GIT_DIR; git branch y" % g, none),
        ("Bash", "GIT_DIR=%s bash <<EOF\ngit branch y\nEOF" % g, both),
        ("Bash", "export GIT_DIR=%s; GIT_DIR= git branch y" % g, dynamic),  # an empty GIT_DIR: git cannot find a repository
    ]
    for tool, cmd, want in cases:
        got = sorted((c["redirect"], c["gitdir"] and P(c["gitdir"])) for c in records(tool, cmd, tmp_path, "y"))
        assert got == sorted(want), (tool, cmd, got)
    many = "cd %s; echo %s" % (P(tmp_path / "g"), " ".join("$(git branch y%d)" % k for k in range(2049)))  # 2 states x 2049 texts > 4096
    assert [c for c in G.interpret(many, str(tmp_path), sh="bash") if c.get("anywhere")]
    assert not [c for c in G.interpret("echo $(git branch y)", str(tmp_path), sh="bash") if c.get("anywhere")]


@pytest.mark.parametrize("kind", SESSIONS)
def test_redirected_worktree_add_and_relative_git_dir_after_cd(target, guard, tmp_path, kind):
    cwd, own = session(kind, tmp_path)
    if kind == "lane":
        for name in ("w1", "w2", "w3", "w4"):
            plan(guard, own, name, "docs/%s.md" % name)
    a = P(target.path)
    cases = [
        ("git --git-dir=%s/.git worktree add wt-w1 -b w1" % a, "w1"),  # the relative worktree path is the shell's, never the redirect's
        ("cd %s && git --git-dir=.git branch w2" % a, "w2"),
        ("git --git-dir=.git -C %s branch w3" % a, "w3"),  # the -C after the relative value still applies first
        ("export GIT_DIR=.git; cd %s; git branch w4" % a, "w4"),  # assigned before the cd, resolved where git runs
    ]
    for cmd, name in cases:
        assert NOMAN in (verdict(hook(cwd, cmd)) or ""), cmd
    plan(guard, target, "w1", "docs/w1.md", worktree=cwd / "wt-w1")
    for name in ("w2", "w3", "w4"):
        plan(guard, target, name, "docs/%s.md" % name)
    for cmd, name in cases:
        assert verdict(hook(cwd, cmd)) is None, cmd
    wt = G.interpret(cases[0][0], str(cwd))[0]
    assert same_dir(wt["path"], cwd / "wt-w1") and same_dir(wt["gitdir"], target.path / ".git")
    mismatch = verdict(hook(cwd, "git --git-dir=%s/.git worktree add elsewhere -b w1" % a))
    assert "registered worktree path" in mismatch


def test_an_unresolvable_redirect_is_denied_with_its_own_message(tmp_path, monkeypatch):
    empty, _ = session("empty", tmp_path)
    off = make(tmp_path, "off")
    off.git("config", "--local", "magos.guard", "off")
    plain = tmp_path / "plain"
    plain.mkdir()
    for cwd in (empty, off.path):
        for cmd in ("git --git-dir=$D branch x", "GIT_DIR=$D git branch x", "git --git-dir=%s branch x" % P(plain),
                    "git --git-dir=%s branch x" % P(tmp_path / "missing" / ".git")):
            reason = verdict(hook(cwd, cmd))
            assert reason and REDIRECT in reason, (cwd, cmd, reason)
    assert verdict(hook(off.path, "git branch x")) is None  # the repository's own creations stay silenced
    monkeypatch.setenv("MAGOS_GUARD", "off")  # the host kill switch still silences everything
    assert verdict(hook(empty, "git --git-dir=$D branch x")) is None


def test_work_tree_alone_does_not_change_the_judged_repository(target, tmp_path):
    b = make(tmp_path, "single")
    d = P(target.path)  # a lane-bearing repository: judging it would deny
    for cmd in ("git --work-tree=%s branch x" % d, "GIT_WORK_TREE=%s git branch x" % d, "git --work-tree %s branch x" % d):
        assert verdict(hook(b.path, cmd)) is None, cmd
        assert G.interpret(cmd, str(b.path))[0]["cwd"] == str(b.path)
    b.branch_with("agent/b", "src/a.py")
    for cmd in ("git --work-tree=%s branch x" % d, "GIT_WORK_TREE=%s git branch x" % d):
        reason = verdict(hook(b.path, cmd))
        assert reason and NOMAN in reason and UNPARSE not in reason, cmd


def test_mode_and_engagement_come_from_the_redirected_repository(target, guard, tmp_path):
    d = make(tmp_path, "dest")
    cmd = "git --git-dir=%s/.git branch x" % P(d.path)
    assert verdict(hook(target.path, cmd)) is None  # judged in the clean single-lane repository, not in the lane-bearing session
    d.git("config", "--local", "magos.guard", "off")
    assert verdict(hook(target.path, cmd)) is None
    d.git("config", "--local", "--unset", "magos.guard")
    assert guard(d, "arm").rc == 0
    assert NOMAN in (verdict(hook(target.path, cmd)) or "")
    assert verdict(hook(target.path, "git branch x")) is not None  # the session repository is still judged for its own creations


def test_removing_git_dir_ends_the_redirect(tmp_path):
    d = make(tmp_path, "dest")
    b = make(tmp_path, "lanes")
    b.branch_with("agent/b", "src/a.py")
    single = make(tmp_path, "single")
    off = make(tmp_path, "off")
    off.git("config", "--local", "magos.guard", "off")
    gd = P(d.path / ".git")
    cases = [
        ("Bash", "export GIT_DIR=%s; unset GIT_DIR; git branch u1" % gd),
        ("Bash", "export GIT_DIR=%s; export -n GIT_DIR; git branch u2" % gd),
        ("Bash", "export GIT_DIR=%s; env -u GIT_DIR git branch u3" % gd),
        ("PowerShell", "$env:GIT_DIR='%s'; Remove-Item Env:GIT_DIR; git branch u4" % gd),
        ("PowerShell", "$env:GIT_DIR='%s'; $env:GIT_DIR = $null; git branch u5" % gd),
        ("PowerShell", "$env:GIT_DIR='%s'; $env:GIT_DIR = ''; git branch u6" % gd),
    ]
    for tool, cmd in cases:
        reason = verdict(hook(b.path, cmd, tool=tool))
        assert reason and NOMAN in reason and UNPARSE not in reason and REDIRECT not in reason, (cmd, reason)
        assert all(c["redirect"] is False for c in records(tool, cmd, b.path)), cmd
        for cwd in (single.path, off.path):
            assert verdict(hook(cwd, cmd, tool=tool)) is None, (cwd, cmd)


def test_unexported_git_dir_is_judged_in_both_repositories(guard, tmp_path):
    d = make(tmp_path, "dest")
    b = make(tmp_path, "lanes")
    b.branch_with("agent/b", "src/a.py")
    gd = P(d.path / ".git")
    for cmd in ("GIT_DIR=%s; git branch s1" % gd, "GIT_DIR=%s\ngit worktree add ../w -b s2" % gd):
        if "s2" in cmd:
            plan(guard, d, "s2")  # repository D alone allows both creations
        assert verdict(hook(d.path, cmd.replace(gd, ".git"))) is None, cmd
        reason = verdict(hook(b.path, cmd))
        assert reason and NOMAN in reason, (cmd, reason)
        crs = G.interpret(cmd, str(b.path))
        assert sorted(str(c["redirect"]) for c in crs) == ["False", "True"], crs


# ---- a cd to a missing directory ------------------------------------------------------------------------------------
def test_a_cd_to_a_missing_directory_is_judged_in_the_prior_directory(target):
    cases = [
        ("Bash", "cd C:/definitely/not/here; git switch -c a1"),
        ("Bash", "cd nothere; git switch -c a2"),
        ("Bash", "cd /does/not/exist; git switch -c a3"),
        ("Bash", "cd nothere\ngit worktree add ../w3 -b a4"),
        ("Bash", "cd nothere && git worktree add ../w3 -b a4b"),
        ("PowerShell", "Set-Location C:\\not\\here; git switch -c a5"),
        ("PowerShell", "sl nothere; git switch -c a6"),
        ("Bash", "pushd nothere; git switch -c a7"),
        ("Bash", "cd nothere; cd sub; git switch -c a8"),
        ("PowerShell", "Set-Location \\definitely\\not\\here; git switch -c a9"),  # rooted on the current drive
    ]
    for tool, cmd in cases:
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and UNPARSE in reason and "does not exist" in reason, (cmd, reason)
        cr = G.interpret(cmd, str(target.path))[0]
        assert isinstance(cr["cwd"], G._Missing) and same_dir(cr["cwd"].prior, target.path), (cmd, cr)


def test_a_missing_directory_after_a_non_repository_is_not_judged(target, tmp_path):
    other = tmp_path / "unrelated"
    other.mkdir()
    cmd = "cd %s && git init x && cd x && git switch -c main2" % P(other)
    assert verdict(hook(target.path, cmd)) is None  # the prior directory is not a repository
    single = make(tmp_path, "single")
    assert verdict(hook(single.path, "cd nothere; git switch -c a")) is None  # judged in the prior directory, nothing engaged there


def test_popd_returns_to_the_directory_pushd_left(target, tmp_path):
    clean = make(tmp_path, "clean")
    for tool, cmd in (("Bash", "pushd %s; popd; git branch p1" % P(clean.path)), ("PowerShell", "Push-Location %s; Pop-Location; git branch p2" % P(clean.path))):
        assert NOMAN in (verdict(hook(target.path, cmd, tool=tool)) or ""), cmd  # git runs back in the lane-bearing repository
        assert same_dir(records(tool, cmd, target.path)[0]["cwd"], target.path)
    assert verdict(hook(target.path, "pushd %s; git branch p3" % P(clean.path))) is None  # still in the clean repository
    assert UNPARSE in (verdict(hook(target.path, "popd; git branch p4")) or "")  # a stack the line did not fill: the directory is unknown


# ---- changes the guard cannot place in one state, shells behind wrappers, doas, GIT_COMMON_DIR, the overflow rule -------------------
STATES = "more directory or GIT_DIR states than the hook judges"
MAX_STATES = 8  # the states a line is walked in (MAX_CONTEXTS)


def where(cmd, cwd, tool="Bash", name=None):
    """(redirect, directory or git directory) of each record the hook judges, as comparable lower-case paths."""
    return sorted((c["redirect"], P(c["gitdir"] if c["redirect"] else c["cwd"]).lower()) for c in records(tool, cmd, cwd, name))


def test_a_change_inside_a_subshell_or_a_pipeline_is_judged_before_and_after(target, tmp_path):
    """bash runs a group ( .. ) and every pipeline command but the last in a subshell: a cd / pushd or a GIT_DIR change there never reaches
    the commands after it, which keep the state the line was in.  The last pipeline command (zsh, lastpipe), PowerShell and a shell the
    hook cannot name may change it: the commands after it are judged in both states.  Inside the group its own change holds."""
    clean = make(tmp_path, "clean")
    c, l = P(clean.path), P(target.path)
    subshells = [  # session in the lane-bearing repository: git runs there, never in C
        "(cd %s); git branch s1" % c,
        "(cd %s && cd src); git branch s2" % c,
        "cd %s | cat; git branch s3" % c,
        "pushd %s | cat; git branch s4" % c,
        "(export GIT_DIR=%s/.git); git branch s6" % c,
        "((cd %s); cd %s/src); git branch s7" % (c, c),
        "(echo $(pwd); cd %s); git branch s14" % c,  # the ')' that closes $( does not end the group
        '(cd %s; echo "(") ; git branch s16' % c,  # the ')' after a quoted '(' still ends the group
        "echo $(true; (cd %s); git branch s17)" % c,  # a group inside $( .. ): its ')' is not the one that closes $(
    ]
    for cmd in subshells:
        assert where(cmd, target.path) == [(False, l.lower())], cmd
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason, (cmd, reason)
    possible = [("Bash", "cat x | cd %s; git branch s5" % c), ("PowerShell", "(Set-Location %s); git branch s8" % c),
                ("PowerShell", "Set-Location %s | Out-Null; git branch s9" % c), ("terminal", "(cd %s); git branch s18" % c)]
    for tool, cmd in possible:
        assert where(cmd, target.path, tool) == sorted([(False, l.lower()), (False, c.lower())]), (tool, cmd)
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    for cmd in ("(cd %s; git branch s11)" % c, "(cd %s && git branch s12)" % c, "cd %s && git branch s13 | cat" % c):
        assert verdict(hook(target.path, cmd)) is None, cmd  # inside the group git runs in C, which has a single lane
        assert where(cmd, target.path) == [(False, c.lower())], cmd
    for cmd in ("(cd %s); git branch s10" % l, "(cd %s); cd %s; git branch s15" % (l, c)):  # from C: the group's cd never reaches git
        assert where(cmd, clean.path) == [(False, c.lower())], cmd
        assert verdict(hook(clean.path, cmd)) is None, cmd


def test_eval_and_sourced_changes_are_judged_before_and_after(target, tmp_path):
    """Text the current shell runs itself (eval, iex, source, `.`, a PowerShell script) changes the directory and GIT_DIR of the commands
    after it; the hook judges those commands in the state before and in every state the text leaves."""
    clean = make(tmp_path, "clean")
    c, l = P(clean.path), P(target.path)
    (tmp_path / "to-lanes.sh").write_bytes(("cd %s\n" % l).encode())
    (tmp_path / "to-lanes.ps1").write_bytes(("Set-Location %s\n" % l).encode())
    (tmp_path / "gd-lanes.sh").write_bytes(("export GIT_DIR=%s/.git\n" % l).encode())
    script = P(tmp_path)
    from_clean = [  # session in the clean repository: the text moves git into the lane-bearing one
        ("Bash", 'eval "cd %s"; git branch e1' % l),
        ("Bash", "eval cd %s; git branch e2" % l),
        ("Bash", "source %s/to-lanes.sh; git branch e3" % script),
        ("Bash", ". %s/to-lanes.sh; git branch e4" % script),
        ("Bash", 'eval "export GIT_DIR=%s/.git"; git branch e5' % l),
        ("Bash", "source %s/gd-lanes.sh; git branch e6" % script),
        ("Bash", 'eval "pushd %s"; git branch e7' % l),
        ("PowerShell", "Invoke-Expression 'Set-Location %s'; git branch e8" % l),
        ("PowerShell", "iex 'cd %s'; git branch e9" % l),
        ("PowerShell", "& %s/to-lanes.ps1; git branch e10" % script),
        ("PowerShell", ". %s/to-lanes.ps1; git branch e11" % script),
        ("PowerShell", "%s/to-lanes.ps1; git branch e12" % script),
    ]
    for tool, cmd in from_clean:
        reason = verdict(hook(clean.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    assert where('eval "cd %s"; git branch e1' % l, clean.path, name="e1") == sorted([(False, c.lower()), (False, l.lower())])
    assert where('eval "export GIT_DIR=%s/.git"; git branch e5' % l, clean.path, name="e5") == sorted([(False, c.lower()), (True, l.lower() + "/.git")])
    assert verdict(hook(clean.path, 'eval "cd %s && git branch e13"' % c)) is None  # inside the text its own cd holds: judged in C only
    assert verdict(hook(clean.path, "bash -c 'cd %s'; git branch e14" % l)) is None  # a child shell's cd never reaches the parent
    assert verdict(hook(clean.path, "bash %s/to-lanes.sh; git branch e15" % script)) is None
    assert where('pushd %s; eval "popd"; git branch e16' % c, target.path, name="e16") == sorted([(False, c.lower()), (False, l.lower())])


def maybe_cds(dirs):
    """`[ -d <dir> ] && cd <dir>` lists: each cd may or may not run, so each adds a state for the commands after it."""
    return "; ".join("[ -d %s ] && cd %s" % (P(d), P(d)) for d in dirs)


def test_more_scoped_states_than_the_hook_walks_are_denied(target, tmp_path):
    clean = make(tmp_path, "clean")
    hops = [tmp_path / ("h%d" % k) for k in range(9)]
    for d in hops:
        d.mkdir()
    cmd = maybe_cds(hops) + "; git branch o1"
    reason = verdict(hook(clean.path, cmd))
    assert reason and UNPARSE in reason and "a condition or a background job may change the directory or GIT_DIR, which leaves the command in " + STATES in reason
    assert verdict(hook(clean.path, maybe_cds(hops[:7]) + "; git branch o2")) is None  # eight states: walked
    empty, _ = session("empty", tmp_path)
    assert UNPARSE in (verdict(hook(empty, cmd)) or "")
    steps = "git status; " * 2000 + "git branch o3"  # every command walked in seven further states spends the budget
    many = maybe_cds(hops[:7]) + "; " + steps
    assert [c["why"] for c in G.interpret(many, str(clean.path), sh="bash") if c.get("anywhere")] == [G._OVER_WORK]
    assert "more walking" in (verdict(hook(clean.path, many)) or "")
    assert not [c for c in G.interpret(steps, str(clean.path), sh="bash") if c.get("anywhere")]  # one state: within the budget
    groups = "; ".join("(cd %s)" % P(d) for d in hops) + "; git branch o4"
    assert where(groups, clean.path) == [(False, P(clean.path).lower())]  # bash: every group is a subshell, one state is left
    assert verdict(hook(clean.path, groups)) is None
    assert len({P(c["cwd"]).lower() for c in records("terminal", groups, clean.path, "o4")}) == MAX_STATES  # the shell is not known: ten states, eight walked
    reason = verdict(hook(clean.path, groups, tool="terminal"))
    assert reason and UNPARSE in reason and STATES in reason


def test_a_shell_behind_a_prefix_assignment_or_a_wrapper_reads_piped_text(target, tmp_path):
    """Text piped into `FOO=1 sh`, `env FOO=1 bash`, `sudo -E sh`, `command sh` or `doas -u user sh` runs as a command, exactly as text piped
    into a bare shell; the patterns that find these sinks stay linear in the command length."""
    q = '"'
    cases = [  # (command, name): no line holds the scanner's echo-pipe-exec shape (the shell word never follows the pipe directly)
        ("echo %sgit branch p1%s | FOO=1 sh" % (q, q), "p1"),
        ("echo %sgit branch p2%s | env FOO=1 bash" % (q, q), "p2"),
        ("echo %sgit branch p3%s | sudo -E sh" % (q, q), "p3"),
        ("echo %sgit branch p4%s | command sh" % (q, q), "p4"),
        ("printf 'git branch p5' | FOO=1 sh", "p5"),
        ("echo %sgit branch p6%s | doas -u root sh" % (q, q), "p6"),
        ("echo 'git branch p7' | FOO=1 BAR=2 env -i dash", "p7"),
        ("cd . && echo %sgit branch p8%s | nice -n 5 bash -s" % (q, q), "p8"),
        ("echo %sgit branch p9%s | sudo -u root -E zsh" % (q, q), "p9"),
        ("echo git branch p10 |& FOO=1 sh", "p10"),
        ("echo %sgit branch p11%s | FOO=1 pwsh -Command -" % (q, q), "p11"),
    ]
    for cmd, name in cases:
        assert [n for c in G.interpret(cmd, str(target.path), sh="bash") for n in c["names"]] == [name], cmd
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and name in reason, (cmd, reason)
    for cmd in ("echo %sgit branch n1%s | grep sh" % (q, q), "echo %sgit branch n2%s | FOO=1 cat" % (q, q), "echo 'git branch n3' | tee shell.log"):
        assert G.interpret(cmd, str(target.path), sh="bash") == [], cmd  # no shell reads the text
    for bad in ("|a=| " * 40000, "| -a x " * 28000, "|-a " + "x " * 95000, "echo " + "|a=| " * 40000, "echo " + "| sudo -E " * 19000,
                "printf " + "| env " * 33000, "| " + "-x env " * 28000 + "y", "| " + "-x A=1 " * 28000 + "y", "echo " + "| -x env " * 20000):
        start = time.monotonic()
        G.interpret(bad, ".")
        G._SINK.search(bad)
        G._ECHO_PIPE.match(bad)
        assert time.monotonic() - start < time_budget(5), bad[:40]


def test_doas_is_a_wrapper_like_sudo(target, tmp_path):
    clean = make(tmp_path, "clean")
    for cmd, name in (("doas git branch d1", "d1"), ("doas -u user git branch d2", "d2"), ("doas -u git git branch d3", "d3"), ("doas -n git switch -c d4", "d4"),
                      ("sudo -u git git branch d5", "d5")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and name in reason, (cmd, reason)
    cmd = "export GIT_DIR=%s/.git; doas git branch d6" % P(target.path)  # doas may start git with a clean environment: judged both ways
    assert where(cmd, clean.path, name="d6") == sorted([(False, P(clean.path).lower()), (True, P(target.path).lower() + "/.git")])
    assert NOMAN in (verdict(hook(clean.path, cmd)) or "")
    assert verdict(hook(clean.path, "doas git branch d7")) is None  # the clean repository has a single lane


def test_git_common_dir_is_judged_in_both_repositories(target, tmp_path):
    """Under GIT_COMMON_DIR git writes the branch into the repository it finds from its directory (or GIT_DIR) and reads the config, the
    hooks and the objects of the GIT_COMMON_DIR repository, so a creation is judged in both repositories, by every spelling GIT_DIR has."""
    clean = make(tmp_path, "clean")
    c, l = P(clean.path), P(target.path)
    spellings = [
        ("Bash", "GIT_COMMON_DIR=%s/.git git branch g1" % l),
        ("Bash", "env GIT_COMMON_DIR=%s/.git git branch g2" % l),
        ("Bash", "export GIT_COMMON_DIR=%s/.git; git branch g3" % l),
        ("Bash", "declare -x GIT_COMMON_DIR=%s/.git; git branch g4" % l),
        ("Bash", "GIT_COMMON_DIR=%s/.git; git branch g5" % l),
        ("PowerShell", "$env:GIT_COMMON_DIR='%s/.git'; git branch g6" % l),
        ("PowerShell", "Set-Item Env:GIT_COMMON_DIR %s/.git; git branch g7" % l),
        ("Bash", 'cmd /c "set GIT_COMMON_DIR=%s/.git&& git branch g8"' % l),
        ("Bash", "cd %s && GIT_COMMON_DIR=.git git -C %s branch g9" % (c, l)),  # relative: resolved where git runs, after -C
    ]
    for tool, cmd in spellings:
        reason = verdict(hook(clean.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    assert where(spellings[0][1], clean.path) == sorted([(False, c.lower()), (True, l.lower() + "/.git")])
    assert NOMAN in (verdict(hook(target.path, "GIT_COMMON_DIR=%s/.git git branch g10" % c)) or "")  # from the lane-bearing side as well
    both = "GIT_DIR=%s/.git GIT_COMMON_DIR=%s/.git git branch g11" % (c, l)
    assert where(both, tmp_path) == sorted([(True, c.lower() + "/.git"), (True, l.lower() + "/.git")])  # GIT_DIR and GIT_COMMON_DIR, not the directory
    assert NOMAN in (verdict(hook(clean.path, both)) or "")
    flag = "export GIT_COMMON_DIR=%s/.git; git --git-dir=%s/.git branch g12" % (l, c)  # --git-dir replaces GIT_DIR only
    assert where(flag, tmp_path) == sorted([(True, c.lower() + "/.git"), (True, l.lower() + "/.git")])
    for cmd in ("GIT_COMMON_DIR=$X git branch g13", "GIT_COMMON_DIR=%s/nothing git branch g14" % P(tmp_path)):
        assert REDIRECT in (verdict(hook(clean.path, cmd)) or ""), cmd
    for tool, cmd in (("Bash", "export GIT_COMMON_DIR=%s/.git; unset GIT_COMMON_DIR; git branch g15" % l),
                      ("Bash", "export GIT_COMMON_DIR=%s/.git; env -u GIT_COMMON_DIR git branch g16" % l),
                      ("PowerShell", "$env:GIT_COMMON_DIR='%s/.git'; Remove-Item Env:GIT_COMMON_DIR; git branch g17" % l)):
        assert verdict(hook(clean.path, cmd, tool=tool)) is None, cmd  # a removal ends it: judged in the clean repository only
    # the premise: git splits the repository under GIT_COMMON_DIR (config from the GIT_COMMON_DIR one, the ref in one of the two)
    clean.git("config", "--local", "probe.where", "clean")
    target.git("config", "--local", "probe.where", "lanes")
    env = dict(os.environ, GIT_COMMON_DIR=str(target.path / ".git"))
    sha = target.git("rev-parse", "main")

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(clean.path), env=env, capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                              timeout=120)
    assert git("config", "probe.where").stdout.strip() == b"lanes"
    assert git("branch", "premise", sha).returncode == 0
    assert "premise" in branches(clean) + branches(target)


def test_the_overflow_rule_respects_a_guard_that_is_off(target, tmp_path, monkeypatch):
    """Inner text in more directory or GIT_DIR states than the hook judges, more scoped states than it walks, or more walking than its
    budget is denied UNPARSEABLE, except where the session directory's repository is off or MAGOS_GUARD=off; outside a repository it is
    denied."""
    off = make(tmp_path, "off")
    off.branch_with("agent/o", "src/a.py")  # another lane: without the switch every unclaimed creation there is denied
    off.git("config", "--local", "magos.guard", "off")
    clean = make(tmp_path, "clean")
    empty, _ = session("empty", tmp_path)
    hops = [tmp_path / ("h%d" % k) for k in range(9)]
    for d in hops:
        d.mkdir()
    cds = "; ".join("cd %s" % P(d) for d in hops)
    nest = "git branch q " + "y " * 5000
    for level in range(3):
        nest = "; ".join("cd %s" % P(d) for d in hops[:7]) + "; bash <<E%d\n%s\nE%d" % (level, nest, level)
    lines = ["%s; echo $(git branch o1)" % cds, "%s; git branch o2" % maybe_cds(hops), nest]
    for cmd in lines:
        assert verdict(hook(off.path, cmd)) is None, cmd[:60]  # the session repository is off
        for cwd in (clean.path, empty):
            reason = verdict(hook(cwd, cmd))
            assert reason and UNPARSE in reason and ("states than the hook" in reason), (cwd, cmd[:60], reason)
    reason = verdict(hook(clean.path, nest))
    assert "the command takes more walking through nested text and directory or GIT_DIR states than the hook does" in reason
    assert NOMAN in (verdict(hook(off.path, "git -C %s branch o3" % P(target.path))) or "")  # off silences its own repository, not another
    monkeypatch.setenv("MAGOS_GUARD", "off")
    for cmd in lines:
        assert verdict(hook(empty, cmd)) is None, cmd[:60]


# ---- hooked tools ---------------------------------------------------------------------------------------------------
def test_monitor_and_shell_mcp_tools_are_inspected(target, tmp_path):
    empty, _ = session("empty", tmp_path)
    assert NOMAN in (verdict(hook(empty, "git -C %s branch m1" % P(target.path), tool="Monitor")) or "")
    tools = ("mcp__terminal__run_in_terminal", "mcp__desktop-commander__start_process", "mcp__shell__execute_command", "mcp__x__exec_command",
             "mcp__x__terminal", "mcp__x__shell", "mcp__gbrain__run_doctor", "mcp__terminal__read_terminal", "mcp__scheduled-tasks__run_scheduled_task")
    for tool in tools:  # every MCP tool with a string command is inspected, whatever its name
        assert NOMAN in (verdict(hook(target.path, "git branch m2", tool=tool)) or ""), tool
    assert verdict(hook(target.path, ["git", "branch", "m3"], tool="Monitor")) is None  # Monitor takes a string command only
    assert verdict(hook(target.path, None, tool="Monitor", description="x")) is None
    for tool in tools:
        assert verdict(hook(target.path, None, tool=tool, description="x")) is None, tool
    assert G.is_shell_tool("Monitor") and G.is_shell_tool("mcp__terminal__read_terminal") and not G.is_shell_tool("BashOutput")


def test_tool_input_cwd_is_the_session_directory(target, tmp_path):
    empty, _ = session("empty", tmp_path)
    body = {"tool_name": "mcp__terminal__run_in_terminal", "tool_input": {"command": "git branch c1", "cwd": str(target.path)}, "cwd": str(empty)}
    r = hook_body(json.dumps(body).encode())
    assert NOMAN in (verdict(r) or "")
    body["tool_input"]["workdir"] = str(empty)  # workdir wins over tool_input.cwd
    assert verdict(hook_body(json.dumps(body).encode())) is None
    assert G.extract({"tool_name": "Bash", "tool_input": {"command": "ls", "cwd": 7}, "cwd": str(empty)})[2] == str(empty)


# ---- the executable search order on Windows ---------------------------------------------------------------------------
MARKER_CS = r'''using System; using System.IO;
class Marker { static int Main(string[] a) {
  File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "marker.txt"), "FAKEGIT " + string.Join(" ", a) + Environment.NewLine);
  Console.WriteLine("FAKE-EXE-RAN"); return 0; } }
'''


def _csc():
    root = os.environ.get("WINDIR", r"C:\Windows")
    return next((p for p in (os.path.join(root, "Microsoft.NET", fw, "v4.0.30319", "csc.exe") for fw in ("Framework64", "Framework")) if os.path.isfile(p)), None)


@pytest.mark.skipif(sys.platform != "win32", reason="the working-directory search is a Windows CreateProcess rule")
def test_executables_are_never_resolved_from_the_working_directory(tmp_path):
    csc = _csc()
    if not csc:
        pytest.skip("no C# compiler to build the marker git.exe")
    plant = tmp_path / "plant"
    plant.mkdir()
    (tmp_path / "marker.cs").write_text(MARKER_CS, encoding="utf-8")
    built = subprocess.run([csc, "/nologo", "/out:%s" % (plant / "git.exe"), str(tmp_path / "marker.cs")], capture_output=True, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW)
    assert built.returncode == 0, built.stdout
    for name in ("py.cmd", "py.bat"):
        (plant / name).write_bytes(b'@echo PYCMD %* >> "%~dp0marker.txt"\r\n')
    env = {k: v for k, v in os.environ.items() if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}

    def child(*args, inp=None):
        return subprocess.run([sys.executable, *args], input=inp, stdin=None if inp is not None else subprocess.DEVNULL, capture_output=True, cwd=str(plant),
                              env=env, creationflags=NO_WINDOW, timeout=120)
    control = child("-c", "import subprocess; print(subprocess.run(['git', '--version'], capture_output=True, stdin=subprocess.DEVNULL).stdout)")
    assert b"FAKE-EXE-RAN" in control.stdout and (plant / "marker.txt").exists()  # without the variable the planted git.exe is found first
    (plant / "marker.txt").unlink()
    body = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git switch -c feat"}, "cwd": str(plant)}).encode()
    r = child("-X", "utf8", "-B", str(SCRIPT), "hook", "codex", "pre-tool", inp=body)
    assert r.returncode == 0 and json.loads(r.stdout) == {}, r
    r = child("-X", "utf8", "-B", str(SCRIPT), "doctor")
    assert b"git version" in r.stdout and b"FAKE" not in r.stdout, r
    r = child("-c", "import importlib.util, os, sys; s = importlib.util.spec_from_file_location('g', sys.argv[1]); s.loader.exec_module(importlib.util.module_from_spec(s));"
                    " print(os.environ.get('NoDefaultCurrentDirectoryInExePath'))", str(SCRIPT))
    assert r.stdout.strip() == b"1", r
    assert not (plant / "marker.txt").exists()


# ---- user-only commands ---------------------------------------------------------------------------------------------
def test_user_only_commands_are_recognised_whatever_the_option_spelling(repo, tmp_path):
    empty, _ = session("empty", tmp_path)
    cmds = ["py -3 magos_guard.py --repo=. install --host codex", "python3 scripts/magos_guard.py --lang=en arm", "python magos_guard.py --rep . disarm",
            "magos_guard.py --la en arm", "magos_guard.py --js arm", "magos_guard.py --json --repo=. override --fingerprint 0123456789ab --reason y",
            "magos_guard.py --r . --l en --j install --host hermes", "python C:/x/MAGOS_GUARD.PY --repo=. install --host codex"]
    for cwd in (repo.path, empty):
        for cmd in cmds + ["bash -c '%s'" % c for c in cmds]:
            reason = verdict(hook(cwd, cmd))
            assert reason and "user-only" in reason, (cwd, cmd)
        assert verdict(hook(cwd, "python3 magos_guard.py --repo=. list")) is None
        assert verdict(hook(cwd, "python3 magos_guard.py --repo=. --unknown install")) is None  # argparse refuses it: nothing runs


def test_abbreviated_options_are_usage_errors(repo):
    for argv in (["--rep", ".", "list"], ["check", "--bra", "x", "--paths", "a"], ["--js", "version"], ["--js", "list"], ["list", "--dri"]):
        r = run(argv, cwd=repo.path)
        assert r.rc == 2 and r.out == "", (argv, r)
    assert run(["--json", "list"], cwd=repo.path).rc == 0  # the full spelling works


def test_install_needs_a_console_except_for_a_dry_run(tmp_path, monkeypatch):
    home = tmp_path / "h"
    monkeypatch.setattr(G, "user_console", lambda: False)
    r = run(["--lang", "en", "install", "--host", "codex", "--home", str(home)])
    assert r.rc == 17 and "real terminal" in r.err and not home.exists()
    r = run(["--lang", "en", "install", "--host", "codex", "--home", str(home), "--dry-run"])
    assert r.rc == 0 and "would copy" in r.out and not home.exists()
    monkeypatch.setattr(G, "user_console", lambda: True)
    r = run(["--lang", "en", "install", "--host", "codex", "--home", str(home)])
    assert r.rc == 0 and (home / "guard" / "scripts" / "magos_guard.py").is_file()


# ---- undecided engagement, override, errors ---------------------------------------------------------------------------
def test_auto_named_creations_are_denied_when_engagement_cannot_be_decided(target, guard, monkeypatch):
    real = G.gather

    def exhausted(*a, **k):
        raise G.GitFail("BUDGET_EXCEEDED", "the comparison ran out of time")
    monkeypatch.setattr(G, "gather", exhausted)
    r = hook(target.path, None, tool="Agent", prompt="x", isolation="worktree")
    reason = verdict(r, quiet=False)
    assert reason and UNPLAN in reason and "BUDGET_EXCEEDED" in reason
    assert r.err.count("\n") == 1 and "BUDGET_EXCEEDED" in r.err and "auto-named" in r.err
    r = hook(target.path, "git switch -c feature/z")
    assert verdict(r, quiet=False) is None and "BUDGET_EXCEEDED" in r.err and "allows" in r.err  # the documented branch-only allow, with a warning
    r = hook(target.path, "git worktree add ../w -b agent/q")
    assert NOMAN in (verdict(r) or "")  # a named worktree is always engaged: decided, no warning
    monkeypatch.setattr(G, "gather", real)
    plan(guard, target, "agent/p")
    monkeypatch.setattr(G, "gather", exhausted)
    r = hook(target.path, "git switch -c feature/z")
    assert NOMAN in (verdict(r, quiet=False) or "") and "open claim" in r.err
    monkeypatch.setattr(G, "gather", lambda *a, **k: (_ for _ in ()).throw(G.Uncertain("integration target is ambiguous")))
    r = hook(target.path, None, tool="Agent", prompt="x", isolation="worktree")
    assert "TARGET_UNCERTAIN" in (verdict(r, quiet=False) or "") and "TARGET_UNCERTAIN" in r.err


def test_an_override_takes_effect_only_through_a_re_plan(repo, guard, monkeypatch):
    plan(guard, repo, "agent/ov", "src/a.py")
    repo.branch_with("agent/x", "src/a.py")  # another lane now changes the planned file
    cmd = "git worktree add ../w -b agent/ov"
    reason = verdict(hook(repo.path, cmd))
    assert reason and "agent/x" in reason and "a re-plan is required" in reason
    fp = re.search(r"--fingerprint ([0-9a-f]{12})", reason).group(1)
    monkeypatch.setattr(G, "user_console", lambda: True)
    assert run(["--repo", str(repo.path), "override", "--fingerprint", fp, "--reason", "ok"], stdin=(fp + "\n").encode()).rc == 0
    record = G.os.path.join(G.store(G.open_repo(str(repo.path))), "override", fp + ".json")
    for _ in range(2):
        assert "agent/x" in (verdict(hook(repo.path, cmd)) or "")  # the hook never reads the record
        assert os.path.isfile(record)
    assert guard(repo, "check", "--branch", "agent/ov", "--paths", "src/a.py").rc == 10  # neither does check
    assert guard(repo, "plan", "--branch", "agent/ov", "--paths", "src/a.py").rc == 0  # the re-plan consumes it
    assert not os.path.isfile(record) and "override=" + fp in open(G.claim_path(G.open_repo(str(repo.path)), "agent/ov"), encoding="utf-8").read()
    assert verdict(hook(repo.path, cmd)) is None


def test_json_mode_prints_a_deny_object_on_git_and_internal_errors(repo, tmp_path, monkeypatch):
    nowhere = tmp_path / "nopath"
    nowhere.mkdir()
    with monkeypatch.context() as m:
        m.setenv("PATH", str(nowhere))
        r = run(["--repo", str(repo.path), "--json", "check", "--branch", "n", "--paths", "docs/"])
        assert r.rc == 11 and "MAGOS guard: GIT_MISSING: " in r.err
        obj = json.loads(r.out)
        assert obj["decision"] == "deny" and obj["code"] == "UNKNOWN" and obj["exit_code"] == 11 and obj["unknowns"][0]["code"] == "GIT_MISSING"
        assert obj["message"] == r.err.strip()
        r = run(["--repo", str(repo.path), "check", "--branch", "n", "--paths", "docs/"])
        assert r.rc == 11 and r.out == "" and "GIT_MISSING" in r.err
    monkeypatch.setattr(G, "cmd_list", lambda a: (_ for _ in ()).throw(RuntimeError("kaput")))
    r = run(["--repo", str(repo.path), "--json", "list"])
    obj = json.loads(r.out)
    assert r.rc == 11 and obj["unknowns"] == [{"code": "INTERNAL_ERROR", "text": "RuntimeError: kaput"}] and "MAGOS guard internal error: RuntimeError: kaput" in r.err
    r = run(["--repo", str(repo.path), "list"])
    assert r.rc == 11 and r.out == "" and "internal error" in r.err


def test_a_silent_git_failure_reports_its_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(G.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 5, b"", b""))
    with pytest.raises(G.GitFail) as err:
        G.Git(str(tmp_path)).run("rev-parse", "HEAD")
    assert err.value.code == "GIT_FAILED" and str(err.value) == "git rev-parse HEAD: exit code 5"
    monkeypatch.setattr(G.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 5, b"", b"fatal: broken\n"))
    with pytest.raises(G.GitFail) as err:
        G.Git(str(tmp_path)).run("rev-parse", "HEAD")
    assert str(err.value) == "git rev-parse HEAD: fatal: broken"


# ---- the same verdicts on every interpreter ------------------------------------------------------------------------------
def path_payloads(target, guard, tmp_path):
    """The payloads of TC-056, TC-057, TC-061 and TC-064 (tool, command, session directory)."""
    other = tmp_path / "unrelated"
    other.mkdir()
    plan(guard, target, "agent/planned")
    spelled = "/" + P(target.path).replace(":", "", 1)  # /C/Users/... as Git Bash prints it
    gd = P(target.path / ".git")
    out = [("Bash", "cd %s && git worktree add ../w -b agent/new" % spelled, other),
           ("Bash", "cd /does/not/exist && git worktree add ../w -b agent/other2", target.path),
           ("Bash", "cd %s && git init x && cd x && git switch -c main2" % P(other), target.path),
           ("Bash", "git --git-dir=%s branch x" % gd, other), ("Bash", "git --git-dir %s branch x" % gd, other),
           ("Bash", "git --git-dir=$D branch x", other), ("Bash", "GIT_DIR=$D git branch x", other), ("Bash", "git --git-dir=%s branch x" % P(other), other)]
    out += [("Bash", c, target.path) for c in ("cd C:/definitely/not/here; git switch -c a1", "cd nothere; git switch -c a2", "cd /does/not/exist; git switch -c a3",
                                               "cd nothere\ngit worktree add ../w3 -b a4", "cd nothere && git worktree add ../w3 -b a4b",
                                               "pushd nothere; git switch -c a7", "cd nothere; cd sub; git switch -c a8")]
    out += [("PowerShell", "Set-Location C:\\not\\here; git switch -c a5", target.path), ("PowerShell", "sl nothere; git switch -c a6", target.path)]
    return out


def _launcher_python():
    """The first interpreter the launcher would pick (python3, py -3, python) that runs, with its version."""
    for cand in (["python3"], ["py", "-3"], ["python"]):
        exe = shutil.which(cand[0])
        if not exe:
            continue
        try:
            p = subprocess.run([exe] + cand[1:] + ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True, stdin=subprocess.DEVNULL,
                               timeout=60, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            continue
        version = p.stdout.decode("ascii", "replace").strip()
        if p.returncode == 0 and re.fullmatch(r"\d+\.\d+", version):
            return [exe] + cand[1:], version
    return None, None


def test_hook_verdicts_agree_under_the_launchers_interpreter(target, guard, tmp_path):
    launcher, version = _launcher_python()
    if launcher is None or version == "%d.%d" % sys.version_info[:2]:
        pytest.skip("the launcher's interpreter is this interpreter (%s)" % version)
    cases = path_payloads(target, guard, tmp_path)

    def verdicts(python):
        out = []
        for tool, cmd, cwd in cases:
            body = json.dumps(payload(tool, cmd, cwd)).encode("utf-8")
            p = retried(lambda: subprocess.run(python + ["-X", "utf8", "-B", str(SCRIPT), "--lang", "en", "hook", "claude", "pre-tool"], input=body,
                                               capture_output=True, cwd=str(tmp_path), env=dict(os.environ), creationflags=NO_WINDOW, timeout=120),
                        lambda p: crashed((p.stdout + p.stderr).decode("utf-8", "replace"), p.returncode))  # a transient crash of git is retried
            assert p.returncode == 0, (python, cmd, p.stderr)
            out.append(p.stdout)
        return out
    mine, theirs = verdicts([sys.executable]), verdicts(launcher)
    for (tool, cmd, _), a, b in zip(cases, mine, theirs):
        assert a == b, (version, cmd, a, b)
    assert sum(v.strip() != b"{}" for v in mine) == len(cases) - 1  # every payload but the real non-repository directory is denied


def _isabs_before_313(s):
    rest = ntpath.splitdrive(os.fspath(s))[1]
    return rest[:1] in ("\\", "/")


def _isabs_since_313(s):
    s = os.fspath(s)
    drive, rest = ntpath.splitdrive(s)
    return bool(drive) and rest[:1] in ("\\", "/") or s[:2] in ("\\\\", "//")


@pytest.mark.skipif(sys.platform != "win32", reason="os.path.isabs changed for rooted Windows paths without a drive")
def test_path_rules_do_not_depend_on_the_isabs_behaviour(target, guard, tmp_path, monkeypatch):
    cases = [c for c in path_payloads(target, guard, tmp_path) if "git-dir" not in c[1] and "GIT_DIR" not in c[1]]
    bodies = [json.dumps(payload(tool, cmd, cwd)).encode("utf-8") for tool, cmd, cwd in cases]
    results = []
    for fake in (_isabs_before_313, _isabs_since_313):
        with monkeypatch.context() as m:
            m.setattr(os.path, "isabs", fake)
            results.append([hook_body(b).out for b in bodies])
    assert results[0] == results[1]
    by_cmd = {cmd: out for (_, cmd, _), out in zip(cases, results[0])}
    assert "agent/new" in by_cmd[cases[0][1]] and NOMAN in json.loads(by_cmd[cases[0][1]])["reason"]  # the Git Bash spelling is judged in the repository
    for cmd, out in by_cmd.items():
        if "/does/not/exist" in cmd:
            assert UNPARSE in json.loads(out)["reason"], cmd  # a POSIX-rooted target that maps to no drive is the missing-directory rule


# ---- definite and possible directory changes ---------------------------------------------------------------------------
def lanes_and_clean(target, tmp_path):
    """(L, C, clean, both): L is the lane-bearing repository (an unclaimed creation there is denied), C a single-lane one (allowed)."""
    clean = make(tmp_path, "clean")
    l, c = P(target.path), P(clean.path)
    return l, c, clean, sorted([(False, l.lower()), (False, c.lower())])


def test_a_change_after_and_or_is_definite_only_along_an_and_chain(target, tmp_path):
    """A cd after '&&' or '||' is definite for a later git only when '&&' alone joins them, starting from a command that always runs; a
    git after ';', a newline or '||' is judged in the states before and after the cd, and the stricter verdict applies."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    possible = ["false && cd %s; git branch a1" % c, "false || cd %s; git branch a2" % c, "true || cd %s && git branch a3" % c,
                "false && cd %s\ngit branch a4" % c, "x && cd %s && cd %s; git branch a5" % (c, c), "x || cd %s && false || git branch a6" % c]
    for cmd in possible:
        assert where(cmd, target.path) == both, cmd
    for cmd in possible[:4]:
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason, (cmd, reason)
    definite = ["cd %s && git switch -c ok1" % c, "cd %s; git switch -c ok2" % c, "git status && cd %s && git switch -c ok3" % c, "cd %s\ngit switch -c ok4" % c,
                "cd %s || exit 1; git switch -c ok5" % c, "a || b && cd %s && git switch -c ok6" % c, "cd %s 2>&1 && git switch -c ok7" % c,
                "cd %s >/dev/null 2>&1; git switch -c ok8" % c, "cd %s > /dev/null; git switch -c ok9" % c,
                "cd %s && false || git switch -c ok12" % c]  # the first command of a list always runs
    for cmd in definite:
        assert where(cmd, target.path) == [(False, c.lower())], cmd  # judged in C only, as before
    for cmd in definite[:3]:
        assert verdict(hook(target.path, cmd)) is None, cmd
    assert verdict(hook(target.path, "cd %s && git switch -c ok10" % c, tool="PowerShell")) is None
    assert verdict(hook(target.path, "Set-Location %s; git switch -c ok11" % c, tool="PowerShell")) is None


def test_a_change_inside_a_compound_command_is_possible(target, tmp_path):
    """if / while / until / for / select / case run their parts or not: every change inside is possible, inside the compound command
    and after it, and a PowerShell block in braces keeps the state it was opened in."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    cases = [("Bash", "if false; then cd %s; fi; git branch b1" % c), ("Bash", "if true; then :; else cd %s; fi; git branch b2" % c),
             ("Bash", "if false; then cd %s; else git branch b3; fi" % c), ("Bash", "while false; do cd %s; done; git branch b4" % c),
             ("Bash", "until true; do cd %s; done; git branch b5" % c), ("Bash", "for x in 1; do cd %s; done; git branch b6" % c),
             ("Bash", "(case a in a) cd %s;; esac); git branch b7" % c), ("Bash", "case a in a) cd %s;; esac; git branch b8" % c),
             ("Bash", "case a in (b|a) cd %s;; *) :;; esac; git branch b9" % c), ("Bash", "if x; then y=$(if a; then b; fi); cd %s; fi; git branch b10" % c),
             ("PowerShell", "if ($false) { Set-Location %s }; git branch b11" % c), ("PowerShell", "if($x){Set-Location %s}; git branch b12" % c)]
    for tool, cmd in cases:
        want = [(False, l.lower())] if cmd.startswith("(case") else both  # bash runs the group, and the case inside it, in a subshell
        assert where(cmd, target.path, tool) == want, (tool, cmd)
    for tool, cmd in cases[:1] + cases[6:8] + cases[10:11]:
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    assert where("cd %s; case a in a) git branch b13;; esac" % c, target.path) == [(False, c.lower())]  # a definite cd before it still holds


def test_a_function_body_or_a_brace_block_keeps_the_state_it_was_opened_in(target, tmp_path):
    """A function body runs only when the function is called and a PowerShell script block only when it is invoked: a change inside a
    brace block is possible for the commands after it; inside the block its own definite changes hold."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for tool, cmd in (("Bash", "f() { cd %s; }; git branch f1" % c), ("Bash", "function f { cd %s; }; git branch f2" % c),
                      ("Bash", "function f() { cd %s; }; f; git branch f3" % c), ("PowerShell", "function f { Set-Location %s }; git branch f4" % c),
                      ("PowerShell", "Invoke-Command { Set-Location %s }; git branch f5" % c)):
        assert where(cmd, target.path, tool) == both, (tool, cmd)
    assert where("{ cd %s; } & git branch f6" % c, target.path) == [(False, l.lower())]  # bash runs a background list in a subshell
    reason = verdict(hook(target.path, "f() { cd %s; }; git branch f7" % c))
    assert reason and NOMAN in reason
    assert where("cd %s && { git switch -c ok1; }" % c, target.path) == [(False, c.lower())]
    assert where("{ cd %s; git switch -c ok2; }" % c, target.path) == [(False, c.lower())]
    assert verdict(hook(target.path, "cd %s && { git switch -c ok3; }" % c)) is None


def test_a_list_sent_to_the_background_keeps_the_state_it_started_in(target, tmp_path):
    """A list ended by '&' runs in a background job, which bash runs in a subshell: its cd never reaches the shell, so later commands
    keep the state the list started in.  In cmd '&' runs the next command after the first one, and cmd's `cd /d` switches the drive and
    directory together."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for cmd in ("cd %s & git branch g1" % c, "x && cd %s & git branch g2" % c, "cd %s &\ngit branch g3" % c):
        assert where(cmd, target.path) == [(False, l.lower())], cmd
        assert where(cmd, target.path, "terminal") == both, cmd  # a shell the hook cannot name: the change is possible
    reason = verdict(hook(target.path, "cd %s & git branch g4" % c))
    assert reason and NOMAN in reason
    for cmd in ('cmd /c "cd /d %s & git switch -c ok1"' % c, 'cmd /c "cd /d %s && git switch -c ok2"' % c):
        assert where(cmd, target.path) == [(False, c.lower())], cmd
    assert verdict(hook(target.path, 'cmd /c "cd /d %s & git switch -c ok3"' % c)) is None
    assert NOMAN in (verdict(hook(clean.path, 'cmd /c "cd /d %s && git branch g5"' % l)) or "")
    (tmp_path / "two words").mkdir()
    spaced = G.interpret("cd /d %s/two words & git branch g6" % P(tmp_path), str(target.path), sh="cmd")
    assert [P(r["cwd"]) for r in spaced] == [P(tmp_path) + "/two words"]  # cmd's cd reads the rest of the line as one path


def test_text_substituted_into_a_command_may_change_the_state(target, tmp_path):
    """PowerShell runs $(..), (..) and @(..) in the current scope, so a Set-Location there moves the commands after it: a possible change.
    bash runs $(..), <(..) and backticks in a subshell, so a cd there never reaches the commands after it."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for tool, cmd in (("PowerShell", "echo $(Set-Location %s); git branch s1" % l), ("PowerShell", "Write-Output $(Set-Location %s); git branch s2" % l),
                      ("PowerShell", "echo (Set-Location %s); git branch s3" % l), ("PowerShell", "$out = (Set-Location %s); git branch s4" % l),
                      ("PowerShell", "echo (Get-Date; Set-Location %s); git branch s11" % l)):
        assert where(cmd, clean.path, tool) == both, (tool, cmd)  # a command inside substituted text is no command of the line
    for cmd in ("echo `cd %s`; git branch s5" % l, "echo $(cd %s); git branch s6" % l, "echo $(true; cd %s); git branch s8" % l,
                "echo $(true\ncd %s); git branch s9" % l, "cat <(true; cd %s); git branch s10" % l):
        assert where(cmd, clean.path) == [(False, c.lower())], cmd  # bash: a subshell
    assert where("echo $(true ) cd %s; git branch s12" % l, clean.path) == [(False, c.lower())]  # words after the ')' belong to echo
    reason = verdict(hook(clean.path, "echo $(Set-Location %s); git branch s7" % l, tool="PowerShell"))
    assert reason and NOMAN in reason
    assert verdict(hook(clean.path, "echo $(true; cd %s); git branch s13" % l)) is None  # judged in C only, which has a single lane
    assert where("git switch -c ok1; echo $(Set-Location %s)" % l, clean.path, "PowerShell") == [(False, c.lower())]  # only the commands after it
    assert where("Write-Host '(Set-Location %s)'; git switch -c ok2" % l, clean.path, "PowerShell") == [(False, c.lower())]  # a string runs nothing


def test_a_builtin_behind_a_program_wrapper_changes_nothing(target, tmp_path):
    """env, sudo, doas, nohup and the other program wrappers start a program: they cannot run cd, export or unset, so those change
    nothing in the shell; command and builtin run the builtin itself."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for cmd in ("env cd %s; git branch w1" % c, "sudo cd %s; git branch w2" % c, "nohup cd %s; git branch w3" % c, "env -i cd %s && git branch w4" % c,
                "doas pushd %s; git branch w5" % c):
        assert where(cmd, target.path) == [(False, l.lower())], cmd
    reason = verdict(hook(target.path, "env cd %s; git branch w6" % c))
    assert reason and NOMAN in reason
    gd = l.lower() + "/.git"
    assert where("export GIT_DIR=%s/.git; env unset GIT_DIR; git branch w7" % l, clean.path) == [(True, gd)]  # the redirect stays
    for cmd in ("command cd %s; git branch w8" % l, "builtin cd %s; git branch w9" % l):
        assert where(cmd, clean.path) == [(False, l.lower())], cmd
    reason = verdict(hook(clean.path, "command cd %s; git branch w10" % l))
    assert reason and NOMAN in reason


def test_env_and_sudo_directory_options_run_git_in_that_directory(target, tmp_path):
    """`env -C <dir>` / `--chdir` and `sudo -D <dir>` / `--chdir` run the wrapped git in <dir>, like git -C; a dynamic value leaves the
    repository unknown."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    spellings = ["env -C %s git branch d1", "env --chdir=%s git branch d2", "env --chdir %s git branch d3", "env -C%s git branch d4",
                 "env -u X -C %s git branch d5", "sudo -D %s git branch d6", "sudo --chdir=%s git branch d7", "sudo -u root -D %s git branch d8",
                 "sudo --chdir %s git branch d9"]
    for form in spellings:
        assert where(form % l, clean.path) == [(False, l.lower())], form
    for form in spellings[:1] + spellings[5:6]:
        reason = verdict(hook(clean.path, form % l))
        assert reason and NOMAN in reason, (form, reason)
    for cmd in ("env -C $D git branch d10", "sudo -D $D git branch d11"):
        assert UNPARSE in (verdict(hook(target.path, cmd)) or ""), cmd
    assert verdict(hook(target.path, "env -C %s git switch -c ok1" % c)) is None  # git runs in C, which has a single lane


def test_creations_hidden_in_assignments_parentheses_and_split_strings_are_judged(target, tmp_path):
    """PowerShell runs the command on the right of `$x =` and inside (..) and @(..); `env -S` splits its value into the command it runs."""
    q = '"'
    for tool, cmd, name in (("PowerShell", "$out = git branch h1", "h1"), ("PowerShell", "echo (git branch h2)", "h2"),
                            ("PowerShell", "$null = @(git branch h3)", "h3"), ("PowerShell", "[void](git branch h4)", "h4"),
                            ("Bash", "env -S 'git branch h5'", "h5"), ("Bash", "env -S'git branch h6'", "h6"),
                            ("Bash", "env -i --split-string=%sgit branch h7%s" % (q, q), "h7")):
        assert [n for r in records(tool, cmd, target.path) for n in r["names"]] == [name], (tool, cmd)
    for tool, cmd in (("PowerShell", "$out = git branch h8"), ("PowerShell", "echo (git branch h9)"), ("Bash", "env -S 'git branch h10'")):
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    for cmd in ('git commit -m "fix (git branch handling)"', "Write-Host '(git branch quoted)'", "$g = 'git'; $n = 5"):
        assert records("PowerShell", cmd, target.path) == [], cmd  # text inside a string, a plain value


def test_a_cd_the_shell_refuses_leaves_the_directory_unchanged(target, tmp_path):
    """bash and PowerShell refuse a cd with a second directory (`cd /d <dir>` in bash, `cd <dir> extra`): the shell stays where it was, so
    later commands are judged there, unresolved, like after a cd to a missing directory."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for tool, cmd in (("Bash", "cd /d %s; git branch r1" % c), ("PowerShell", "cd %s extra; git branch r2" % c)):
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and UNPARSE in reason and "does not exist" in reason, (tool, cmd, reason)
        cr = records(tool, cmd, target.path)[0]
        assert isinstance(cr["cwd"], G._Missing) and same_dir(cr["cwd"].prior, target.path), (cmd, cr)


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("bash"), reason="the premises are checked with Git Bash")
def test_the_shell_premises_of_definite_and_possible_changes(target, tmp_path):
    """What Git Bash really does with the forms above (read-only: pwd and rev-parse, nothing is created)."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    bash = shutil.which("bash")

    def run_in(cwd, script):
        p = subprocess.run([bash, "-c", script], cwd=str(cwd), capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=120)
        return p.stdout.decode("utf-8", "replace").strip().splitlines() or [""]

    if not run_in(target.path, "uname -s")[0].startswith(("MINGW", "MSYS")):
        pytest.skip("bash is not Git Bash")
    here = run_in(target.path, "pwd")[-1]
    for script in ("false && cd %s; pwd" % c, "true || cd %s && pwd" % c, "if false; then cd %s; fi; pwd" % c, "f() { cd %s; }; pwd" % c,
                   "cd %s & wait; pwd" % c, "(case a in a) cd %s;; esac); pwd" % c, "env cd %s; pwd" % c, "cd /d %s; pwd" % c):
        assert run_in(target.path, script)[-1] == here, script  # the shell is still in L
    assert run_in(target.path, "case a in a) cd %s;; esac; pwd" % c)[-1] != here
    for script in ("env -C %s git rev-parse --show-toplevel" % l, "env --chdir=%s git rev-parse --show-toplevel" % l):
        assert run_in(clean.path, script)[-1].lower() == l.lower(), script


@pytest.mark.parametrize("cmd", ["(" * 100000 + "x", "case " * 40000, "if " * 60000, "{ " * 90000, "f() { " * 30000, "esac) " * 30000, "& " * 90000,
                                 "case x in " + "a|" * 90000, "echo $(cd x) " * 15000, "false && cd x; " * 13000, "env -C x " * 20000 + "git branch y",
                                 "echo " + "(cd x) " * 25000, "cd " + "> " * 90000, "'" + "\\'" * 90000],
                         ids=["parens", "case", "if", "braces", "functions", "esac", "background", "patterns", "substitutions", "and-chains",
                              "env-chdir", "ps-parens", "redirections", "quotes"])
def test_the_definite_and_possible_walk_stays_linear(cmd):
    for sh in (None, "ps", "cmd"):
        start = time.monotonic()
        G.interpret(cmd, ".", sh=sh)
        G._unquoted(cmd)
        G._CHANGES.search(cmd)
        assert time.monotonic() - start < time_budget(5), (sh, cmd[:30])


# ---- state caps, bash subshells, && chains, one judgement per repository ---------------------------------------------------------------
PROTECTED = "would change the guard's own"


def hook_input(where_from, tool, **ti):
    """A hook call from the session directory `where_from` whose tool_input is exactly `ti` (it may carry a cwd of its own)."""
    return hook_body(json.dumps({"tool_name": tool, "tool_input": ti, "cwd": str(where_from)}).encode())


def nine_dirs(base, names=()):
    """Nine existing directories under `base` (the given names first)."""
    out = []
    for name in list(names) + ["n%d" % k for k in range(9 - len(names))]:
        (base / name).mkdir(parents=True, exist_ok=True)
        out.append(base / name)
    return out


def test_state_caps_deny_only_a_line_that_creates_something_or_reads_a_relative_script(tmp_path):
    single = make(tmp_path, "single")
    multi = tmp_path / "multi"  # a directory outside any repository that holds repositories
    multi.mkdir()
    for name in ("api", "web", "docs", "infra"):
        make(multi, name)
    q = '"'
    for cwd, dirs in ((single.path, nine_dirs(tmp_path / "hops")), (multi, nine_dirs(multi, ("api", "web", "docs", "infra")))):
        (dirs[-1] / "mk.sh").write_bytes(b"git branch z9\n")  # only the ninth directory's script creates a branch
        allowed = [maybe_cds(dirs) + "; git status", maybe_cds(dirs) + "; npm test | grep -i high", maybe_cds(dirs) + "; echo %sdone at $(date +%%T)%s" % (q, q),
                   "; ".join("cd %s && git status -s" % P(d) for d in dirs) + "; echo %sdone at $(date +%%T)%s" % (q, q)]
        for cmd in allowed:  # nothing is created and no relative script is read: the states beyond the cap lose nothing
            assert verdict(hook(cwd, cmd)) is None, (cwd, cmd[-60:])
        groups = "; ".join("(cd %s && git pull)" % P(d) for d in dirs)
        assert len(records("terminal", groups, cwd)) == 0 and verdict(hook(cwd, groups, tool="terminal")) is None, cwd
        reason = verdict(hook(cwd, maybe_cds(dirs) + "; git switch -c x9"))
        assert reason and UNPARSE in reason and STATES in reason, (cwd, reason)
        reason = verdict(hook(cwd, maybe_cds(dirs) + "; bash ./mk.sh"))  # a relative script keeps the cap: the ninth state is not walked
        assert reason and UNPARSE in reason and STATES in reason, (cwd, reason)
        reason = verdict(hook(cwd, maybe_cds(dirs[:7]) + "; " + "git status; " * 2000))  # an incomplete walk is denied in every case
        assert reason and "more walking" in reason, cwd


def test_bash_subshells_background_lists_and_substitutions_keep_the_state_they_started_in(target, guard, tmp_path):
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for cmd in ("(cd %s); git branch b1" % l, "cd %s & git branch b2" % l, "cd %s | cat; git branch b3" % l, "echo $(cd %s); git branch b4" % l,
                "cat <(cd %s); git branch b5" % l, "echo `cd %s`; git branch b6" % l):
        assert where(cmd, clean.path) == [(False, c.lower())], cmd  # bash runs each in a subshell: git stays in C
        assert verdict(hook(clean.path, cmd)) is None, cmd
    for tool, cmd in (("Bash", "cat x | cd %s; git branch b7" % l), ("terminal", "(cd %s); git branch b8" % l), ("PowerShell", "(Set-Location %s); git branch b9" % l)):
        assert where(cmd, clean.path, tool) == both, (tool, cmd)  # the last pipeline command, a shell the hook cannot name, PowerShell
        reason = verdict(hook(clean.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    multi = tmp_path / "multi"
    multi.mkdir()
    for name in ("api", "web", "docs", "infra"):
        make(multi, name)
    assert verdict(hook(multi, "(cd api && git pull); (cd web && git pull); (cd docs && git pull); (cd infra && git pull)")) is None
    p = make(tmp_path, "planned")
    for sub in ("pkg/a", "pkg/b"):
        (p.path / sub).mkdir(parents=True)
    plan(guard, p, "agent/planned", "docs/planned.md")
    cmd = "(cd pkg/a && git status -s); (cd pkg/b && git status -s); git switch -c agent/planned"
    assert where(cmd, p.path, name="agent/planned") == [(False, P(p.path).lower())]  # no state names pkg/a/pkg/b
    assert verdict(hook(p.path, cmd)) is None


def test_a_cd_into_a_directory_the_same_and_chain_creates_is_followed(target, guard, tmp_path):
    l = target
    plan(guard, l, "agent/planned", "docs/planned.md")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(l.path), str(origin)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    wt = P(tmp_path / "wt-planned")
    allowed = ["mkdir -p tmpdemo && cd tmpdemo && git init && git checkout -b main", "git init demo2 && cd demo2 && git switch -c main",
               "git clone %s vendor-copy && cd vendor-copy && git checkout -b fix-123" % P(origin),
               "mkdir -p out/site && cd out/site && git init -q && git checkout -q -b gh-pages"]
    allowed += ["git clone %s && cd origin && git switch -c fix-2" % P(origin), "mkdir -p q/r && git -C q/r init && cd q/r && git switch -c fix-3",
                "git init -b main -- s && cd s && git switch -c fix-4", "mkdir -p deep/er && cd deep && git init && git switch -c fix-5"]
    for cmd in allowed:  # the chain made a new repository: it holds no lane, so nothing is judged there
        assert verdict(hook(l.path, cmd)) is None, cmd
    reason = verdict(hook(l.path, "mkdir -p build2 && cd build2 && git checkout -b unplanned-q"))  # git finds L from the new directory
    assert reason and NOMAN in reason and "'unplanned-q'" in reason, reason
    cr = records("Bash", "mkdir -p build2 && cd build2 && git checkout -b unplanned-q", l.path, "unplanned-q")[0]
    assert cr["cwd"].follow[0] == "dir" and same_dir(cr["cwd"].prior, l.path)
    reason = verdict(hook(l.path, "git worktree add %s -b agent/planned main && cd %s && git switch -c agent/sub" % (wt, wt)))
    assert reason and NOMAN in reason and "'agent/sub'" in reason, reason  # judged in the repository the worktree belongs to
    for cmd in ("cd nothere && git switch -c x1", "mkdir newpkg; cd newpkg; git init; git checkout -b main2"):
        reason = verdict(hook(l.path, cmd))  # nothing earlier in the same && chain makes the target: the missing-directory rule
        assert reason and UNPARSE in reason and "does not exist" in reason, (cmd, reason)
    cmd = "mkdir -p d3 && cd d3 && git init; git switch -c y3"  # after the chain ends the commands are judged in L, and unresolved
    crs = records("Bash", cmd, l.path, "y3")
    assert len(crs) == 2 and sorted(isinstance(c["cwd"], G._Missing) for c in crs) == [False, True]
    assert all(same_dir(getattr(c["cwd"], "prior", c["cwd"]), l.path) and not getattr(c["cwd"], "follow", None) for c in crs)
    assert verdict(hook(l.path, cmd)) is not None


def fast_branches(repo, names):
    """One branch per name, each with a commit of its own on top of main (git fast-import: quick for many branches)."""
    base = repo.git("rev-parse", "main")
    stream = []
    for n in names:
        body = ("%s\n" % n).encode()
        stream += [b"commit refs/heads/" + n.encode(), b"committer t <t@example.invalid> 1700000000 +0000", b"data 1", b"c", b"from " + base.encode(),
                   b"M 100644 inline f/" + n.encode() + b".txt", b"data %d" % len(body), body]
    repo.git("fast-import", "--quiet", inp=b"\n".join(stream) + b"\n")


def test_a_creation_seen_in_several_states_is_judged_once_per_repository(guard, tmp_path, monkeypatch):
    b = make(tmp_path, "big")
    fast_branches(b, ["lane%02d" % k for k in range(40)])
    for sub in ("pkg/a", "pkg/b", "pkg/c", "pkg/d"):
        (b.path / sub).mkdir(parents=True)
    plan(guard, b, "agent/big-planned", "docs/big.md")
    c = make(tmp_path, "other")
    gathered, judged = [], []
    real_gather, real_parallel = G.gather, G.parallel
    monkeypatch.setattr(G, "gather", lambda g, *a, **k: (gathered.append(P(g.common).lower()), real_gather(g, *a, **k))[1])
    monkeypatch.setattr(G, "parallel", lambda g, *a, **k: (judged.append(P(g.common).lower()), real_parallel(g, *a, **k))[1])
    creation = "git switch -c agent/big-planned"
    ifs = "".join('if [ -n "$X" ]; then cd %s/pkg/%s; fi; ' % (P(b.path), x) for x in "abcd")
    lines = {"one": creation, "five": ifs + creation, "two": "[ -d src ] && cd src; " + creation,
             "six": ifs + 'if [ -n "$X" ]; then cd %s; fi; ' % P(c.path) + creation}
    counts = {}
    for key, cmd in lines.items():
        del gathered[:], judged[:]
        start = time.monotonic()
        assert verdict(hook(b.path, cmd)) is None, key
        counts[key] = (sorted(gathered), sorted(judged), time.monotonic() - start)
    assert len(where(lines["five"], b.path)) == 5  # five records in one worktree
    bkey = counts["one"][1][0]  # B's common directory as git names it
    assert counts["one"][1] == [bkey] and counts["one"][0] and set(counts["one"][0]) == {bkey}
    assert counts["five"][0] == counts["one"][0] == counts["two"][0]  # the same gathers as the one-state line
    assert counts["five"][1] == counts["two"][1] == [bkey]  # judged once
    others = [x for x in counts["six"][1] if x != bkey]
    assert len(counts["six"][1]) == 2 and len(others) == 1 and [x for x in counts["six"][0] if x == bkey] == counts["one"][0]  # B once, C once
    assert counts["five"][2] < time_budget(G.BUDGET_S), counts["five"][2]


def diverged_clone(tmp_path, name="diverged"):
    """A clone whose main is ahead 1 and behind 1 of origin/main (the integration target is uncertain), with no other branch, worktree or claim."""
    origin = make(tmp_path, name + "-origin")
    d = Repo(tmp_path / name)
    subprocess.run(["git", "clone", "-q", str(origin.path), str(d.path)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
    d.commit("local.txt", "mine\n", msg="local")
    origin.commit("remote.txt", "theirs\n", msg="remote")
    d.git("fetch", "-q")
    return d


AUTO_PAYLOADS = [("Agent", None, {"prompt": "x", "isolation": "worktree"}), ("Task", None, {"prompt": "x", "isolation": "worktree"}),
                 ("EnterWorktree", None, {}), ("mcp__ccd_session__start_session", None, {"use_worktree": True}),
                 ("Bash", "gh pr checkout 12", {}), ("Bash", "claude --worktree", {})]


def test_auto_named_creations_fall_back_to_a_cheap_lane_signal(target, tmp_path, monkeypatch):
    d = diverged_clone(tmp_path)

    def calls():
        return [(tool, hook(d.path, cmd, tool=tool, **ti)) for tool, cmd, ti in AUTO_PAYLOADS]
    for tool, r in calls():  # no claim, no other branch, no second worktree: allowed with the undecided warning
        assert verdict(r, quiet=False) is None, (tool, r)
        assert "TARGET_UNCERTAIN" in r.err and "auto-named creation is allowed" in r.err, (tool, r.err)
    claim = d.path / ".git" / "magos" / "claims" / "agent" / "x.claim"
    second = tmp_path / "second-wt"
    signals = [(lambda: d.git("branch", "other"), lambda: d.git("branch", "-D", "other")),
               (lambda: (claim.parent.mkdir(parents=True), claim.write_bytes(b"state=active\nv=1\nbranch=agent/x\nentry=docs/\n")), lambda: claim.unlink()),
               (lambda: d.git("worktree", "add", "-q", "--detach", str(second)), lambda: d.git("worktree", "remove", "--force", str(second)))]
    for make_signal, remove in signals:
        make_signal()
        for tool, r in calls():
            reason = verdict(r, quiet=False)
            assert reason and UNPLAN in reason and "TARGET_UNCERTAIN" in reason, (tool, reason)
        remove()
    monkeypatch.setattr(G, "gather", lambda *a, **k: (_ for _ in ()).throw(G.GitFail("BUDGET_EXCEEDED", "the comparison ran out of time")))
    r = hook(target.path, None, tool="Agent", prompt="x", isolation="worktree")  # another branch exists: still denied
    reason = verdict(r, quiet=False)
    assert reason and UNPLAN in reason and "BUDGET_EXCEEDED" in reason


# ---- escapes, the session directory, unmodelled GIT_DIR, routed tools ------------------------------------------------------------------
def test_bash_backslash_escapes_are_removed_before_matching(target, guard, tmp_path):
    a = target
    b = make(tmp_path, "b")
    b.branch_with("agent/b", "src/a.py")
    cases = [(r"git switch -c feat\ure", "feature"), (r"git branch my\branch", "mybranch"), (r"git checkout -b hot\fix", "hotfix"),
             (r"git worktree add ../wtz -b my\lane", "mylane"), (r"git swi\tch -c newx", "newx"), (r"g\it switch -c newy", "newy"),
             (r"git --git-dir=%s/.git swi\tch -c newz" % P(b.path), "newz"), (r"bash -\c 'git branch e1'", "e1"),
             (r"find . -exec git branch viafind \;", "viafind")]
    for cmd, name in cases:
        reason = verdict(hook(a.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    newz = records("Bash", cases[6][0], a.path, "newz")
    assert [(c["redirect"], same_dir(c["gitdir"], b.path / ".git")) for c in newz] == [(True, True)]  # judged in B
    for cmd in (r"git switch -c 'feat\ure'", r'git switch -c "feat\ure"'):
        assert records("Bash", cmd, a.path) == [], cmd  # a quoted backslash survives: git refuses the name
    q = make(tmp_path, "q")
    plan(guard, q, "q", "docs/q.md")
    reason = verdict(hook(q.path, r"git worktree add ../wt\q"))
    assert reason and NOMAN in reason and "'wtq'" in reason, reason
    r = make(tmp_path, "armed")
    assert guard(r, "arm").rc == 0
    for tool, cmd in (("Bash", r"git config --local ma\gos.guard off"), ("Bash", r"git conf\ig --local magos.guard off"),
                      ("Bash", r"py -3 scripts/magos_guard.py ar\m"), ("Bash", r"rm .git\magos\ARMED"), ("PowerShell", r"Remove-Item .git\magos\ARMED")):
        reason = verdict(hook(r.path, cmd, tool=tool))
        assert reason and PROTECTED in reason, (tool, cmd, reason)
    assert verdict(hook(r.path, r"git log --grep ma\gos.guard")) is None


def test_a_tilde_session_directory_is_expanded(isolated_env, tmp_path):
    home = isolated_env
    t = make(home, "T")
    t.branch_with("agent/t", "src/a.py")
    empty, _ = session("empty", tmp_path)
    tool = "mcp__terminal__run_in_terminal"
    bodies = [{"tool_name": tool, "tool_input": {"command": "git branch rit3", "cwd": "~/T"}, "cwd": str(empty)},
              {"tool_name": tool, "tool_input": {"command": "git worktree add ../wtT -b rit10", "cwd": "~/T"}, "cwd": str(empty)},
              {"tool_name": tool, "tool_input": {"command": "git branch rit4", "workdir": "~/T"}, "cwd": str(empty)},
              {"tool_name": "Bash", "tool_input": {"command": "git branch rit5"}, "cwd": "~/T"}]
    if sys.platform == "win32":  # ~\ is a home spelling on Windows only
        bodies.append({"tool_name": tool, "tool_input": {"command": "git branch rit7", "cwd": "~\\T"}, "cwd": str(empty)})
    for body in bodies:
        reason = verdict(hook_body(json.dumps(body).encode()))
        assert reason and NOMAN in reason, body
    body = {"tool_name": tool, "tool_input": {"command": "git branch rit6", "cwd": "T"}, "cwd": str(home)}
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(body).encode(), cwd=empty)  # the hook process runs elsewhere
    assert NOMAN in (verdict(r) or "")  # the relative value is joined to the payload's cwd


def test_unmodelled_git_dir_spellings_make_the_repository_unknown(target, guard, tmp_path):
    a = P(target.path)
    b = make(tmp_path, "clean")
    c = make(tmp_path, "claimed")
    plan(guard, c, "wrc12", "docs/w.md")
    off = make(tmp_path, "off")
    off.git("config", "--local", "magos.guard", "off")
    lines = [("Bash", "read GIT_DIR <<< '%s/.git'; export GIT_DIR; git branch n11" % a), ("Bash", "IFS= read -r GIT_DIR <<< '%s/.git'; export GIT_DIR; git branch n25" % a),
             ("Bash", "printf -v GIT_DIR '%%s' '%s/.git'; export GIT_DIR; git branch n12" % a), ("Bash", "export GIT_DIR+=%s/.git; git branch n15" % a),
             ("Bash", "GIT_DIR+=%s/.git; export GIT_DIR; git branch n26" % a), ("Bash", "GIT_DIR+=%s/.git git branch n27" % a),
             ("Bash", "builtin export GIT_DIR=%s/.git; git branch n29" % a), ("Bash", "command export GIT_DIR=%s/.git; git branch n30" % a),
             ("Bash", "mapfile -t GIT_COMMON_DIR < f; git branch n31"), ("PowerShell", "Set-Content env:GIT_DIR '%s/.git'; git branch p2" % a),
             ("PowerShell", "sc env:GIT_DIR '%s/.git'; git branch p19" % a), ("PowerShell", "Set-Content -Path Env:/GIT_DIR -Value '%s/.git'; git branch p20" % a)]
    for cwd in (b.path, c.path, off.path):
        for tool, cmd in lines:
            reason = verdict(hook(cwd, cmd, tool=tool))
            assert reason and REDIRECT in reason, (cwd, tool, cmd, reason)
    for cmd in ("for GIT_DIR in '%s/.git'; do export GIT_DIR; git branch n40; done" % a, "export GIT_DIR; git branch n41",  # a value the walk never saw
                "declare -n ref=GIT_DIR; ref=%s/.git; export GIT_DIR; git branch n42" % a):
        assert [c for c in records("Bash", cmd, b.path) if c["redirect"] and c["gitdir"] is None], cmd
        assert verdict(hook(b.path, cmd)) is not None, cmd
    reason = verdict(hook(c.path, "printf -v GIT_DIR '%%s' '%s/.git'; export GIT_DIR; git worktree add %s -b wrc12" % (a, P(tmp_path / "wt-wrc12"))))
    assert reason and REDIRECT in reason  # the claim in C does not cover a creation whose repository is unknown
    assert verdict(hook(b.path, "read GIT_DIR <<< '%s/.git'; export GIT_DIR; git status" % a)) is None  # nothing is created
    assert verdict(hook(b.path, "read X <<< y; git branch ok1")) is None
    assert where("read X <<< y; git branch ok1", b.path) == [(False, P(b.path).lower())]


def test_every_routed_tool_with_a_string_command_is_inspected(target, tmp_path):
    empty, _ = session("empty", tmp_path)
    a = str(target.path)
    tools = ("mcp__serena__execute_shell_command", "mcp__iterm__write_to_terminal", "mcp__windows-mcp__Powershell-Tool", "mcp__terminal__open_terminal_tab",
             "mcp__x__run_command", "mcp__gbrain__run_doctor")
    for tool in tools:
        reason = verdict(hook_input(empty, tool, command="git branch se1", cwd=a))
        assert reason and NOMAN in reason and "'se1'" in reason, tool
        for bad in (["git", "branch", "se1"], 7):
            assert verdict(hook_input(empty, tool, command=bad, cwd=a)) is None, (tool, bad)
    reason = verdict(hook(empty, "git -C %s branch se2" % P(target.path), tool="Agent", prompt="x"))
    assert reason and NOMAN in reason and "'se2'" in reason
    for tool, cmd, ti in (("Agent", "echo hi", {"isolation": "worktree", "prompt": "x"}), ("mcp__ccd_session__start_session", "x", {"use_worktree": True})):
        reason = verdict(hook_input(empty, tool, command=cmd, cwd=a, **ti))  # the string command never replaces the tool's own judgement
        assert reason and UNPLAN in reason, tool


# ---- failures, snapshots that hide lanes, option spellings, pushes, refspecs, aliases, git's own commands --------------------------------
def nested(command, depth=100000, **top):
    """The raw bytes of a Bash payload with an extra key that holds arrays nested `depth` levels deep."""
    head = json.dumps(dict({"tool_name": "Bash", "tool_input": {"command": command}}, **top))[:-1]
    return (head + ', "x": ' + "[" * depth + "]" * depth + "}").encode()


def guard_child(body, cwd):
    """The guard's hook entry as a process of the running interpreter."""
    return subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--lang", "en", "hook", "claude", "pre-tool"], input=body, capture_output=True,
                          cwd=str(cwd), creationflags=NO_WINDOW, timeout=120)


def run_launcher(half, launcher, words, env=None, inp=b"{}"):
    """The launcher through cmd.exe (the Codex and Hermes entries on Windows) or through sh (Claude Code and the POSIX entries)."""
    e = dict(os.environ, **(env or {}))
    if half == "cmd":
        return subprocess.run('cmd.exe /d /s /c ""%s" %s"' % (launcher, " ".join(words)), input=inp, capture_output=True, env=e, creationflags=NO_WINDOW,
                              timeout=180)
    return subprocess.run([SH, str(launcher)] + list(words), input=inp, capture_output=True, env=e, creationflags=NO_WINDOW, timeout=180)


def launcher_halves():
    return (["cmd"] if sys.platform == "win32" else []) + (["sh"] if SH else [])


def is_deny(stdout):
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_any_exception_on_a_lane_looking_payload_denies(target, tmp_path, monkeypatch):
    lane = nested("git worktree add ../wt1 -b feat1", cwd=str(target.path))
    p = guard_child(lane, tmp_path)  # the payload cannot be decoded (RecursionError); its bytes name git
    assert p.returncode == 0 and is_deny(p.stdout), p
    for half in launcher_halves():  # soft mode passes the deny through
        r = run_launcher(half, ROOT / "hooks" / "run-guard.cmd", ["hook", "claude", "pre-tool"], inp=lane)
        assert r.returncode == 0 and is_deny(r.stdout), (half, r.returncode, r.stdout[:200], r.stderr[-400:])
    body = json.dumps(payload("Bash", "git worktree add ../w -b agent/crash", target.path)).encode()
    for exc in (RecursionError("deep"), MemoryError(), KeyboardInterrupt()):
        monkeypatch.setattr(G, "decide", lambda *a, _e=exc, **k: (_ for _ in ()).throw(_e))
        reason = verdict(hook_body(body), quiet=False)
        assert reason and "guard error" in reason and type(exc).__name__ in reason, exc
    monkeypatch.setattr(G, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaput")))
    monkeypatch.setattr(G, "extract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broken")))
    assert "guard error" in (verdict(hook_body(body), quiet=False) or "")  # recognising fails too: the command text names git
    paths = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "C:/x/.claude/git-work", "transcript_path": "C:/x/.claude/projects/git/t.jsonl"}
    r = hook_body(json.dumps(paths).encode())
    assert verdict(r, quiet=False) is None and "kaput" in r.err  # path fields never decide
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=b"{not json")  # nothing lane-like: allowed with a warning
    assert r.rc == 0 and r.out.strip() == "{}" and "unparseable hook payload" in r.err, r
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=b"{not json: git branch x")
    assert "unparseable hook payload" in (verdict(r) or "")
    plain = nested("ls")  # no path, no prefilter word
    p = guard_child(plain, tmp_path)
    decodes = subprocess.run([sys.executable, "-c", "import json, sys; json.loads(sys.stdin.buffer.read())"], input=plain,
                             capture_output=True).returncode == 0  # a large C stack (Linux) decodes 100,000 levels; Windows' does not
    assert p.returncode == 0 and json.loads(p.stdout) == {} and (b"warning" in p.stderr) != decodes, (decodes, p)


def test_too_many_claimants_and_truncated_remotes_engage_auto_mode(tmp_path, monkeypatch):
    many = make(tmp_path, "many")
    fast_branches(many, ["s%03d" % k for k in range(119)])
    for count in (119, 121):  # 119: the unmerged branches are other lanes; 121: more than the snapshot analyses, which hides lanes
        reason = verdict(hook(many.path, "git branch newlane"))  # quiet: engagement was decided, no undecided warning
        assert reason and NOMAN in reason, count
        reason = verdict(hook(many.path, None, tool="Agent", prompt="x", isolation="worktree"))
        assert reason and UNPLAN in reason, count
        if count == 119:
            fast_branches(many, ["t0", "t1"])
    g = G.open_repo(str(many.path))
    assert [u["code"] for u in G.gather(g)["unknowns"]] == ["TOO_MANY_CLAIMANTS"] and G.parallel(g, g.top) == (True, None)
    single = make(tmp_path, "single")
    real = G.gather
    monkeypatch.setattr(G, "gather", lambda g, *a, **k: (lambda s: dict(s, warnings=s["warnings"] + [{"code": "REMOTE_TRUNCATED", "text": "400 remotes"}]))(
        real(g, *a, **k)))
    reason = verdict(hook(single.path, "git branch newlane"))
    assert reason and NOMAN in reason


def test_bundled_and_abbreviated_branch_rename_options_are_creations(repo, guard, tmp_path):
    for k in range(1, 7):
        repo.git("branch", "f%d" % k)
    assert guard(repo, "arm").rc == 0
    before = branches(repo)
    cases = [("git branch -mf f1 n1", "n1"), ("git branch -fm f2 n2", "n2"), ("git branch -cf main n3", "n3"), ("git branch -Mf f3 n4", "n4"),
             ("git branch -Cf main n5", "n5"), ("git branch -qm f4 n6", "n6"), ("git branch --mov f5 n7", "n7"), ("git branch --cop main n8", "n8"),
             ("git branch --force -m f6 n9", "n9"), ("git branch -mf x2", "x2"), ("git branch -cf x3", "x3"), ("git branch --mov x4", "x4")]
    for cmd, name in cases:
        reason = verdict(hook(repo.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert records("Bash", "git branch -uorigin/main", repo.path) == []  # -u takes the rest of the word as its value
    assert [c["names"] for c in records("Bash", "git branch --co main x5", repo.path)] == [["main"]]  # --co is ambiguous: no new name
    assert verdict(hook(repo.path, "git branch --co main x5")) is None
    assert branches(repo) == before
    auto = make(tmp_path, "auto")
    plan(guard, auto, "lane1", "docs/l.md")
    auto.git("worktree", "add", "-q", "-b", "lane1", str(tmp_path / "lane1-wt"), "main")
    reason = verdict(hook(auto.path, "git branch -mf lane1 stolen"))
    assert reason and NOMAN in reason and "'stolen'" in reason


def test_short_option_values_written_together_are_names(target, guard, tmp_path):
    for tool, cmd, name in (("Bash", "git switch -cstk1 main", "stk1"), ("Bash", "git checkout -bstk2 main", "stk2"), ("Bash", "git checkout -Bstk3 main", "stk3"),
                            ("Bash", "git switch -Cstk4 main", "stk4"), ("Bash", "git checkout -qbstk10 main", "stk10"),
                            ("Bash", "git checkout --orphan=orph1", "orph1"), ("PowerShell", "git switch -cstk7 main", "stk7"),
                            ("Monitor", "git switch -cmon2 main", "mon2")):
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (tool, cmd, reason)
    c = make(tmp_path, "claims")
    plan(guard, c, "wt-stk5b", "docs/w.md")  # a claim for the directory name covers nothing: the branch is stk5b
    reason = verdict(hook(c.path, "git worktree add -bstk5b %s" % P(tmp_path / "wt-stk5b")))
    assert reason and NOMAN in reason and "'stk5b'" in reason, reason
    for cmd in ("claude -wstk8", "claude --worktree=stk9"):
        reason = verdict(hook(target.path, cmd))
        assert reason and UNPLAN in reason, cmd


def test_a_push_into_a_local_repository_is_judged_there(target, tmp_path):
    a = P(target.path)
    b = make(tmp_path, "B")
    off = make(tmp_path, "O")
    off.git("config", "--local", "magos.guard", "off")
    for cmd in ("git push ./ HEAD:refs/heads/psh1", "git push '%s' HEAD:psh2" % a, "git push file://%s HEAD:psh6" % a):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason, (cmd, reason)
    reason = verdict(hook(target.path, 'git push "$PWD" HEAD:psh5'))
    assert reason and UNPARSE in reason
    assert where("git push ../B HEAD:pshb", target.path) == [(False, P(b.path).lower())]
    assert verdict(hook(target.path, "git push ../B HEAD:pshb")) is None  # judged in B, which has a single lane
    assert records("Bash", "git push origin HEAD:psh7", target.path) == []  # a remote: its repository is not resolved
    assert where("git push B HEAD:pshw", tmp_path, name="pshw") == [(False, P(b.path).lower())]  # an existing directory names a repository
    assert where("git push 'refs/heads/*:refs/heads/g-*'", target.path) == []  # no repository argument: no refspec to judge
    globbed = records("Bash", "git push ../B 'refs/heads/*:refs/heads/g-*'", target.path)
    assert [(c["dynamic"], P(c["cwd"]).lower()) for c in globbed] == [(True, P(b.path).lower())]
    for cwd, name in ((b.path, "psh3"), (off.path, "psh8")):  # from another repository, also one that is off
        reason = verdict(hook(cwd, "git push '%s' HEAD:%s" % (a, name)))
        assert reason and NOMAN in reason and "'%s'" % name in reason and "--repo" in reason, (cwd, reason)


def test_glob_refspecs_are_dynamic_creations(target, tmp_path):
    target.git("branch", "feat-x")
    target.git("branch", "feat-y")
    single = make(tmp_path, "single")
    for cmd in ("git fetch . 'refs/heads/feat-*:refs/heads/cp-*'", "git push . 'refs/heads/*:refs/heads/x-*'", "git fetch origin '+refs/heads/*:refs/heads/*'"):
        reason = verdict(hook(target.path, cmd))
        assert reason and UNPARSE in reason and "glob refspec" in reason, (cmd, reason)
        assert verdict(hook(single.path, cmd)) is None, cmd  # not engaged
    reason = verdict(hook(target.path, "git fetch . feat-x:cpx2"))
    assert reason and NOMAN in reason and "'cpx2'" in reason


def test_git_global_options_with_separate_values_are_skipped(target, tmp_path):
    b = make(tmp_path, "b")
    b.branch_with("agent/b", "src/a.py")
    cases = [("git --attr-source HEAD branch atr1", "atr1"), ("git --attr-source HEAD worktree add %s -b atr2" % P(tmp_path / "wt-atr2"), "atr2"),
             ("git --namespace ns branch atr3", "atr3"), ("git --config-env core.x=ENV branch atr4", "atr4"), ("git --super-prefix sub/ branch atr5", "atr5"),
             ("git -c a.b=c branch atr6", "atr6"), ("git --attr-source HEAD --git-dir=%s/.git branch atr7" % P(b.path), "atr7")]
    for cmd, name in cases:
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert [(c["redirect"], same_dir(c["gitdir"], b.path / ".git")) for c in records("Bash", cases[-1][0], target.path, "atr7")] == [(True, True)]


def test_aliases_are_expanded_in_every_git_invocation(target):
    target.git("config", "--local", "alias.co", "checkout")
    for cmd, name in (("git switch main && git co -b al1", "al1"), ("git checkout main; git co -b al3 main", "al3"), ("git branch main; git co -b al9", "al9"),
                      ("git co -b al2", "al2")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert verdict(hook(target.path, "git status && git co main")) is None


def test_text_git_runs_for_rebase_exec_and_bisect_run_is_inspected(target, tmp_path):
    target.commit("docs/two.md", "two\n", msg="second")
    clean = make(tmp_path, "clean")
    for cmd, name in (("git rebase -q -x 'git branch rbx1' HEAD~1", "rbx1"), ("git rebase --exec 'git branch rbx2' HEAD~1", "rbx2"),
                      ("git rebase --exec='git branch rbx3' HEAD~1", "rbx3"), ("git bisect run git branch rbx4", "rbx4"),
                      ("git bisect run sh -c 'git branch rbx5'", "rbx5")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert verdict(hook(target.path, "git rebase -x 'make test' HEAD~1")) is None
    for cmd, name in (("git rebase -s ours -x 'git branch rbx7' HEAD~1", "rbx7"), ("git rebase -qx'git branch rbx8' HEAD~1", "rbx8"),
                      ("git rebase -Xours -S -x 'git branch rbx9' HEAD~1", "rbx9")):
        assert [n for c in records("Bash", cmd, target.path) for n in c["names"]] == [name], cmd
    cmd = "git -C %s rebase -x 'git branch rbx6' HEAD~1" % P(clean.path)
    assert where(cmd, target.path) == [(False, P(clean.path).lower())]  # the directory of the invocation
    assert verdict(hook(target.path, cmd)) is None


# ---- the launcher, user-only commands, audit records, the tamper filter ---------------------------------------------------------------
def test_launcher_words_start_wrappers_and_double_dash_hide_no_user_only_command(guard, tmp_path):
    armed = make(tmp_path, "armed")
    assert guard(armed, "arm").rc == 0
    plain = make(tmp_path, "plain")
    launcher = ROOT / "hooks" / "run-guard.cmd"
    q = '"'
    denied_lines = []
    for lw in (P(launcher), P(launcher).upper(), P(launcher).replace("/", "\\")):
        denied_lines += [("Bash", "cmd /c start %s%s /min /wait cmd /c call %s disarm --repo %s" % (q, q, lw, P(armed.path))), ("Bash", "%s%s%s disarm" % (q, lw, q)),
                         ("Bash", "%s%s%s --strict arm" % (q, lw, q)), ("Bash", "sh '%s' install --host codex --allow-downgrade" % lw),
                         ("PowerShell", "& %s%s%s install --host codex" % (q, lw, q))]
    denied_lines += [("PowerShell", "Start-Process py -ArgumentList '-3 %s disarm'" % P(SCRIPT)), ("Bash", "py -3 scripts/magos_guard.py -- install --host codex"),
                     ("Bash", "py -3 scripts/magos_guard.py --repo=. -- arm"),
                     ("Bash", "py -3 scripts/magos_guard.py --json -- override --fingerprint abcdefabcdef --reason x")]
    for cwd in (armed.path, plain.path):
        for tool, cmd in denied_lines:
            reason = verdict(hook(cwd, cmd, tool=tool))
            assert reason and "user-only" in reason, (cwd, tool, cmd, reason)
        for cmd in ("%s%s%s hook claude pre-tool" % (q, P(launcher), q), "py -3 scripts/magos_guard.py -- list", "py -3 scripts/magos_guard.py -- version"):
            assert verdict(hook(cwd, cmd)) is None, (cwd, cmd)


LAUNCH_STUB = '''import os, sys
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
sys.stdin.buffer.read()
sys.stdout.write("ok|" + " ".join(sys.argv[1:]))
'''
ONLY_HOOK = "MAGOS guard: the launcher runs only the hook subcommand; run other commands with the guard script itself in your own terminal"


def launcher_layout(tmp_path, stub):
    """A copy of the launcher whose guard script is `stub`."""
    base = tmp_path / "pkg"
    (base / "hooks").mkdir(parents=True)
    (base / "scripts").mkdir()
    shutil.copy(str(ROOT / "hooks" / "run-guard.cmd"), str(base / "hooks" / "run-guard.cmd"))
    (base / "scripts" / "magos_guard.py").write_bytes(stub.encode("utf-8"))
    return base / "hooks" / "run-guard.cmd"


def test_launcher_runs_only_the_hook_subcommand(tmp_path):
    halves = launcher_halves()
    if not halves:
        pytest.skip("neither cmd.exe nor sh is available")
    launcher = launcher_layout(tmp_path, LAUNCH_STUB)
    log = tmp_path / "starts.log"
    for half in halves:
        for words in (["disarm"], ["install", "--host", "codex"], ["--strict", "arm"], ["version"], ["doctor"], ["--lang", "en", "hook", "claude", "pre-tool"]):
            r = run_launcher(half, launcher, words, env={"STUB_LOG": str(log)})
            assert r.returncode == 2 and ONLY_HOOK in r.stderr.decode("utf-8", "replace"), (half, words, r)
            assert not log.exists(), (half, words)  # the guard never started
        for words in (["hook", "claude", "pre-tool"], ["--strict", "hook", "claude", "pre-tool"]):
            r = run_launcher(half, launcher, words, env={"STUB_LOG": str(log)})
            assert r.returncode == 0 and r.stdout.strip() == b"ok|hook claude pre-tool", (half, words, r)
        assert log.read_text(encoding="utf-8").splitlines() == ["hook claude pre-tool"] * 2, half
        log.unlink()


def test_arm_disarm_and_install_append_audit_records(repo, guard, tmp_path):
    home = tmp_path / "home"
    log = os.path.join(G.store(G.open_repo(str(repo.path))), "audit.log")

    def store_records():
        with open(log, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh.read().splitlines()]
    for args in (["arm", "--dry-run"], ["disarm", "--dry-run"], ["install", "--host", "codex", "--home", str(home), "--dry-run"]):
        assert guard(repo, *args).rc == 0, args
    assert not os.path.exists(log) and not (home / "audit.log").exists()  # a dry run appends nothing
    assert guard(repo, "arm").rc == 0 and guard(repo, "disarm").rc == 0
    recs = store_records()
    assert [r["op"] for r in recs] == ["arm", "disarm"] and all(r.get("ts") and r.get("by") for r in recs), recs
    first = guard(repo, "install", "--host", "codex", "--home", str(home))
    second = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert first.rc == 0 and second.rc == 0 and "unchanged" in second.out
    recs = [json.loads(x) for x in (home / "audit.log").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 2 and all(r["op"] == "install" and r["host"] == "codex" and r["to"] == G.GUARD_VERSION and r.get("ts") and r.get("source")
                                  for r in recs), recs
    assert recs[0]["from"] == "none" and recs[1]["from"] == G.GUARD_VERSION  # the unchanged install is recorded as well


def test_tamper_filter_covers_rename_cmdlets_child_shells_and_the_hermes_plugin(guard, tmp_path):
    armed = make(tmp_path, "armed")
    assert guard(armed, "arm").rc == 0
    plain = make(tmp_path, "plain")
    q = '"'
    lines = [("PowerShell", "Rename-Item -Path .git/magos/ARMED -NewName ARMED.off"), ("PowerShell", "Rename-Item .git/magos/ARMED x"),
             ("PowerShell", "ri .git/magos/ARMED"), ("PowerShell", "rni .git/magos/ARMED gone"), ("PowerShell", "mi .git/magos/ARMED gone"),
             ("PowerShell", "powershell -Command %sRemove-Item .git/magos/ARMED%s" % (q, q)), ("PowerShell", r"cmd /c del .git\magos\ARMED"),
             ("PowerShell", r"cmd /c rmdir /s /q .git\magos"), ("Bash", "bash -c 'rm .git/magos/ARMED'"), ("Bash", "sh -c %sunlink .git/magos/ARMED%s" % (q, q)),
             ("Bash", "bash -c 'git config --local magos.guard off'")]
    for tool, cmd in lines:
        reason = verdict(hook(armed.path, cmd, tool=tool))
        assert reason and PROTECTED in reason, (tool, cmd, reason)
    assert PROTECTED in (verdict(hook(plain.path, "bash -c 'git config --local magos.guard off'")) or "")  # magos.* is denied everywhere
    encoded = base64.b64encode("Remove-Item .git/magos/ARMED".encode("utf-16-le")).decode("ascii")
    assert PROTECTED in (verdict(hook(armed.path, "powershell -NoProfile -EncodedCommand %s" % encoded, tool="PowerShell")) or "")
    assert PROTECTED not in (verdict(hook(armed.path, "powershell -EncodedCommand !!!not-base64", tool="PowerShell")) or "")  # nothing decodes
    plugin = Path(os.environ["HERMES_HOME"]) / "plugins" / "magos"
    for rel in ("hooks/run-guard.cmd", "scripts/magos_guard.py"):
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_bytes(b"x\n")
    claimed = make(tmp_path, "claimed")
    plan(guard, claimed, "agent/c", "docs/c.md")
    launcher, script = P(plugin / "hooks" / "run-guard.cmd"), P(plugin / "scripts" / "magos_guard.py")
    for cmd in ("rm -f %s%s%s" % (q, launcher, q), "echo x > %s%s%s" % (q, script, q)):
        reason = verdict(hook(claimed.path, cmd))
        assert reason and PROTECTED in reason, (cmd, reason)
    for cmd in ("cat %s%s%s" % (q, launcher, q), "cat %s%s%s" % (q, script, q)):
        assert verdict(hook(claimed.path, cmd)) is None, cmd


def test_mcp_tools_without_a_command_are_answered_without_parsing(target, monkeypatch):
    opened, ran = [], []
    real_open, real_run = G.open_repo, G.Git.run
    monkeypatch.setattr(G, "open_repo", lambda p: (opened.append(p), real_open(p))[1])
    monkeypatch.setattr(G.Git, "run", lambda self, *a, **k: (ran.append(a), real_run(self, *a, **k))[1])
    for tool, ti in (("mcp__gbrain__get_page", {"slug": "x"}), ("mcp__x__shell", {}), ("mcp__terminal__read_terminal", {"lines": 50})):
        assert verdict(hook(target.path, None, tool=tool, **ti)) is None, tool
    assert opened == [] and ran == []  # no repository opened, no git run
    reason = verdict(hook(target.path, None, tool="mcp__ccd_session__start_session", use_worktree=True))
    assert reason and UNPLAN in reason
    reason = verdict(hook(target.path, None, tool="mcp__github__create_branch", branch="feat-q"))
    assert reason and NOMAN in reason and "'feat-q'" in reason


def test_read_only_uses_of_guard_paths_open_no_repository(repo, guard, tmp_path, monkeypatch):
    plan(guard, repo, "agent/c", "docs/c.md")
    home = Path(os.environ["MAGOS_HOME"])
    (home / "guard" / "scripts").mkdir(parents=True)
    (home / "guard" / "VERSION.json").write_bytes(b"{}\n")
    (home / "guard" / "scripts" / "magos_guard.py").write_bytes(b"x\n")
    h, out = P(home), P(tmp_path / "out")
    listed = tmp_path / "MAGOS-checkout" / "docs"
    listed.mkdir(parents=True)
    store = P(G.store(G.open_repo(str(repo.path))))
    opened = []
    real_open = G.open_repo
    monkeypatch.setattr(G, "open_repo", lambda p: (opened.append(p), real_open(p))[1])
    for tool, cmd in (("Bash", "cp %s/guard/VERSION.json %s/v.json" % (h, out)), ("Bash", "cp %s/guard/scripts/magos_guard.py ./g.py" % h),
                      ("PowerShell", "Copy-Item -Path %s/guard/VERSION.json -Destination ./v.json" % h), ("Bash", "ls %s > %s/ls.txt" % (P(listed), out))):
        del opened[:]
        assert verdict(hook(repo.path, cmd, tool=tool)) is None, cmd
        assert opened == [], (cmd, opened)  # a read of the guard's paths opens no repository
    for tool, cmd in (("Bash", "cp %s/v.json %s/guard/VERSION.json" % (out, h)), ("Bash", "cp -t %s/guard x" % h),
                      ("PowerShell", "Copy-Item x -Destination %s/guard/x" % h), ("Bash", "ln %s/guard/scripts/magos_guard.py %s/g.py" % (h, out)),
                      ("Bash", "ln -s %s/guard/scripts/magos_guard.py %s/g.py" % (h, out)), ("Bash", "cp -l %s/guard/scripts/magos_guard.py %s/g.py" % (h, out)),
                      ("Bash", "cp --link %s/guard/scripts/magos_guard.py %s/g.py" % (h, out)), ("Bash", "cp --target-directory=%s/guard x" % h),
                      ("Bash", "cp -t%s/guard x" % h), ("Bash", "cp --target-directory %s/guard x" % h), ("Bash", "cp -rt %s/guard x" % h),
                      ("Bash", "cp --target %s/guard x" % h)):
        reason = verdict(hook(repo.path, cmd, tool=tool))
        assert reason and PROTECTED in reason, (cmd, reason)  # a write into the guard home, or a link that a later write could follow
    del opened[:]
    reason = verdict(hook(repo.path, "cp x %s/claims/l.claim" % store))
    assert reason and PROTECTED in reason and len(opened) == 1, (reason, opened)


def git_bash():
    """Git for Windows' bash (not the WSL launcher), or None."""
    for cand in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if cand and os.path.isfile(cand):
            p = subprocess.run([cand, "-c", "uname -s"], capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=60)
            if p.stdout.startswith((b"MINGW", b"MSYS")):
                return cand
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="the cmd half of the launcher")
def test_cmd_half_passes_the_guard_stderr_through(tmp_path):
    bash = git_bash()
    if not bash:
        pytest.skip("no Git Bash to run the launcher as hooks.json does")
    stub = 'import sys\nsys.stdin.buffer.read()\nsys.stderr.write("MAGOS guard warning: could not decide whether another lane exists (stub)\\n")\nsys.stdout.write("{}")\n'
    launcher = launcher_layout(tmp_path, stub)
    r = subprocess.run([bash, "-c", '"%s" hook claude pre-tool' % P(launcher)], input=b"{}", capture_output=True, creationflags=NO_WINDOW, timeout=180)
    assert r.returncode == 0 and r.stdout.strip() == b"{}" and b"could not decide whether another lane exists (stub)" in r.stderr, r
    d = diverged_clone(tmp_path)
    body = json.dumps(payload("Bash", "git switch -c feature/x", d.path)).encode()
    r = subprocess.run([bash, "-c", '"%s" hook claude pre-tool' % P(ROOT / "hooks" / "run-guard.cmd")], input=body, capture_output=True,
                       env=dict(os.environ, MAGOS_LANG="en"), creationflags=NO_WINDOW, timeout=180)
    assert r.returncode == 0 and json.loads(r.stdout) == {}, r
    assert b"could not decide whether another lane exists" in r.stderr and b"TARGET_UNCERTAIN" in r.stderr, r.stderr


def test_escapes_of_every_shell_and_git_aliases_hide_no_creation_or_tamper_word(target, guard, tmp_path):
    a = target
    reason = verdict(hook(a.path, "cmd /c git switch -c feat^ure", tool="PowerShell"))  # cmd removes the caret
    assert reason and NOMAN in reason and "'feature'" in reason, reason
    for cmd in (r"git switch -c feat\ure", r"git sw\itch -c newq"):  # a shell the hook cannot name may remove the backslash: dynamic
        reason = verdict(hook(a.path, cmd, tool="terminal"))
        assert reason and UNPARSE in reason, (cmd, reason)
    if sys.platform == "win32":  # there the backslashes of a path are separators: the path stays a path
        cmd = r"git -C %s worktree add ..\wtn -b agent/wtn" % str(a.path)
        reason = verdict(hook(a.path, cmd, tool="terminal"))
        assert reason and NOMAN in reason and UNPARSE not in reason, reason
        plan(guard, a, "agent/wtn", "docs/wtn.md")
        assert verdict(hook(a.path, cmd, tool="terminal")) is None
    armed, plain = make(tmp_path, "armed"), make(tmp_path, "plain")
    assert guard(armed, "arm").rc == 0
    for r in (armed, plain):
        r.git("config", "--local", "alias.cfg", "config")
        for tool, cmd in (("PowerShell", "git config --local ma`gos.guard off"), ("PowerShell", "cmd /c git config --local ma^gos.guard off"),
                          ("Bash", "git -c alias.x=config x --local magos.guard off"), ("Bash", "git cfg --local magos.guard off")):
            reason = verdict(hook(r.path, cmd, tool=tool))
            assert reason and PROTECTED in reason, (r.path, tool, cmd, reason)
    for tool, cmd in (("Bash", r"rm .git/ma\gos/ARMED"), ("PowerShell", "Remove-Item .git/ma`gos/ARMED")):
        reason = verdict(hook(armed.path, cmd, tool=tool))
        assert reason and PROTECTED in reason, (tool, cmd, reason)
    for cmd in ("git commit -m 'git config --local magos.guard off'", "git log --grep ma^gos.guard", "git config --get magos.guard"):
        assert verdict(hook(armed.path, cmd)) is None, cmd


# ---- code-review fixes of the 1.0.2 release ---------------------------------------------------------------------------------------------
def test_relative_paths_after_a_failed_cd_resolve_where_the_shell_is(guard, tmp_path):
    a, b = make(tmp_path, "A"), make(tmp_path, "B")
    plan(guard, b, "other", "docs/other.md")  # B holds a claim: an unplanned branch there is denied
    for cmd in ("cd nonexist; git -C ../B switch -c x", "cd nonexist; cd ../B; git switch -c x", "cd nonexist; git push ../B HEAD:refs/heads/x"):
        reason = verdict(hook(a.path, cmd))
        assert reason and NOMAN in reason and "'x'" in reason, (cmd, reason)
    r = make(tmp_path, "R")
    plan(guard, r, "feat-x", "docs/x.md", worktree=r.path / "lanes" / "feat-x")
    assert verdict(hook(r.path, "mkdir -p lanes && cd lanes && git worktree add feat-x -b feat-x")) is None  # lanes/feat-x, as git creates it
    r2 = make(tmp_path, "R2")
    plan(guard, r2, "feat-x", "docs/x.md", worktree=r2.path / "lanes")
    reason = verdict(hook(r2.path, "mkdir -p lanes && cd lanes && git worktree add anywhere -b feat-x"))
    assert reason and "registered worktree path" in reason, reason  # git creates lanes/anywhere, not the registered lanes


def test_codex_argv_is_read_in_the_dialect_of_the_shell_it_runs(guard, tmp_path):
    a, b = make(tmp_path, "A"), make(tmp_path, "B")
    plan(guard, b, "other", "docs/other.md")
    sep = "\\" if os.name == "nt" else "/"  # PowerShell and cmd read a backslash as a separator on Windows
    argvs = [["powershell.exe", "-NoProfile", "-Command", "git -C ..%sB switch -c x" % sep], ["pwsh", "-Command", "git -C ..%sB switch -c x" % sep],
             ["bash", "-lc", "git -C ../B switch -c x"], ["git", "-C", "..%sB" % sep, "switch", "-c", "x"]]
    argvs += [["cmd", "/c", "git -C ..\\B switch -c x"]] if os.name == "nt" else []
    for argv in argvs:
        reason = verdict(hook(a.path, argv, host="codex"))
        assert reason and NOMAN in reason and "'x'" in reason, (argv, reason)
    assert G.shell_command(payload("Bash", ["git", "-C", "..\\B", "switch", "-c", "x"], a.path)) == ("git -C '..\\B' switch -c x", "bash")
    assert G.shell_command(payload("Bash", ["cmd", "/c", "git status"], a.path)) == ("git status", "cmd")
    assert G.shell_command(payload("Bash", ["pwsh", "-Command", "git status"], a.path)) == ("git status", "ps")
    assert G.shell_command(payload("terminal", "git status", a.path)) == ("git status", None)


def test_a_second_worktree_add_of_the_same_path_with_another_start_point_is_judged(target, tmp_path):
    wt = P(tmp_path / "dx")
    reason = verdict(hook(target.path, "git worktree add %s main || git worktree add %s HEAD~0" % (wt, wt)))
    assert reason and NOMAN in reason, reason


def test_copy_destinations_and_writers_in_every_spelling_are_tested(tmp_path):
    lines = [r"Copy-Item .\p.sh -Destination:C:\r\.git\hooks\reference-transaction", r"Copy-Item .\x.sh .git\magos\claims\f.claim -Force -ErrorAction Stop",
             "cp p.sh .git/hooks/reference-transaction -S .bak", "move evil .git/hooks/reference-transaction", "copy evil .git/magos/ARMED",
             "cpi evil .git/magos/ARMED", "sc .git/magos/ARMED x", "ac .git/magos/ARMED x", "ni .git/magos/ARMED", "clc .git/magos/ARMED",
             r"Copy-Item -Path .\p.sh .git\magos\ARMED"]
    for line in lines:
        assert G.protected(line) == ("guarded", G._STATE_MSG), line
    home = tmp_path / "guard home"
    roots = (G.pkey(str(home)),)
    for line in ('copy "%s/guard/x" .' % P(home), 'cpi "%s/guard/x" .' % P(home), 'Copy-Item "%s/guard/x" . -ErrorAction Stop' % P(home)):
        assert G.protected(line, roots=roots) is None, line  # copying out of the guard home
    assert G.protected('copy x "%s/guard/x"' % P(home), roots=roots) == ("guarded", G._STATE_MSG)


def test_a_quote_in_a_comment_hides_no_command(target):
    cases = [("Bash", "# Let's create the lane branch\ngit switch -c c1", "c1"), ("PowerShell", "# Let's go\ngit switch -c c4", "c4"),
             ("terminal", "# it's here\ngit switch -c c5", "c5"), ("Bash", "echo a #b'\ngit switch -c c6", "c6")]
    for tool, cmd, name in cases:
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (tool, cmd, reason)
    assert G.protected("# don't panic\nrm .git/magos/ARMED") == ("guarded", G._STATE_MSG)
    assert records("Bash", "# git switch -c c7\ngit status", target.path) == []  # a comment runs nothing in bash


def test_a_redirect_after_init_and_cd_is_judged_in_the_repository_it_names(target):
    gd = P(target.path / ".git")
    for cmd in ("git init -q n && cd n && git --git-dir=%s branch feat" % gd, "git init -q n && cd n && GIT_DIR=%s git branch feat" % gd):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'feat'" in reason, (cmd, reason)
    assert verdict(hook(target.path, "git init -q n && cd n && GIT_DIR=.git git branch x")) is None  # the new repository's own git directory


def test_two_letter_long_option_prefixes_create_and_rename(target):
    for cmd, name in (("git branch --mo agent/other zz2", "zz2"), ("git switch --cr zz1", "zz1"), ("git checkout --or zz3", "zz3"),
                      ("git switch --or zz4", "zz4")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert [c["names"] for c in records("Bash", "git branch --co main x5", target.path)] == [["main"]]  # --co names several options


def test_branch_sort_and_format_take_a_value_and_list_nothing(target):
    for cmd, name in (("git branch --sort refname zz8", "zz8"), ("git branch --format x zz9", "zz9"), ("git branch --sort -refname zz10", "zz10"),
                      ("git branch zz11 --sort refname", "zz11")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for cmd in ("git branch --format x", "git branch --sort refname"):
        assert records("Bash", cmd, target.path) == [], cmd


def test_push_and_fetch_option_values_are_not_the_repository(target):
    for cmd, name in (("git push --exec git-receive-pack . HEAD:refs/heads/zz5", "zz5"), ("git push --receive-pack git-receive-pack . HEAD:refs/heads/zz6", "zz6"),
                      ("git push --exe git-receive-pack . HEAD:refs/heads/zz7", "zz7"), ("git push -o ci.skip . HEAD:refs/heads/zz12", "zz12"),
                      ("git fetch --depth 1 . main:zz13", "zz13")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)


def test_a_bash_backslash_newline_joins_the_words(target):
    bs_nl = "\\" + "\n"  # a backslash, then a newline
    for tool, cmd, name in (("Bash", "git switch -c main" + bs_nl + "2", "main2"), ("Bash", 'git switch -c "fe' + bs_nl + 'at"', "feat"),
                            ("Bash", "git sw" + bs_nl + "itch -c feat2", "feat2"), ("PowerShell", "git switch -c `" + "\n" + "ps1", "ps1")):
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (tool, cmd, reason)


# ---- hardening of the 1.0.3 release ------------------------------------------------------------------------------------------------------
def test_update_ref_stdin_names_stop_at_a_backslash(target, guard):
    first = r"printf 'create refs/heads/x1\0HEAD\0' | git update-ref -z --stdin"
    for cmd, name in ((first, "x1"), (r"printf 'update refs/heads/x2\0HEAD\0\0' | git update-ref -z --stdin", "x2"),
                      (r"printf 'create refs/heads/x3\nHEAD' | git update-ref --stdin", "x3")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for cmd in (r"printf 'create refs/heads/a\x62c HEAD' | git update-ref --stdin", r"printf 'create refs/heads/\x61 HEAD' | git update-ref --stdin"):
        reason = verdict(hook(target.path, cmd))  # printf turns the escape into another name: no name can be read
        assert reason and UNPARSE in reason, (cmd, reason)
    plan(guard, target, "x1", "docs/x1.md")
    assert verdict(hook(target.path, first)) is None


def test_an_escaped_program_word_in_an_unknown_shell_is_that_program(target, tmp_path):
    for tool in ("terminal", "shell", "mcp__x__run_in_terminal"):  # the shell of these tools is not known
        for cmd in (r"g\it switch -c x", "g^it switch -c x", "g`it switch -c x"):
            reason = verdict(hook(target.path, cmd, tool=tool))
            assert reason and UNPARSE in reason, (tool, cmd, reason)
    reason = verdict(hook(target.path, r"env g\it switch -c x", tool="terminal"))
    assert reason and UNPARSE in reason, reason
    reason = verdict(hook(target.path, r"g\it switch -c b1"))  # bash removes the backslash: the name is known
    assert reason and NOMAN in reason and "'b1'" in reason, reason
    assert [(c["verb"], c["names"], c["dynamic"]) for c in G.interpret(r"g\it switch -c n1", str(target.path))] == [("switch", ["n1"], True)]
    other = make(tmp_path, "other")  # a directory change it makes is possible: the commands after it run in both directories
    assert where(r"c\d %s; git switch -c pc1" % P(other.path), target.path, tool="terminal", name="pc1") == sorted([(False, P(target.path).lower()),
                                                                                                                  (False, P(other.path).lower())])
    assert records("terminal", r"git status; c\at x", target.path) == []  # a word that spells no known program is no program


def test_rebase_exec_is_read_by_its_unique_prefixes(target):
    for cmd, name in (("git rebase --ex 'git branch r1' HEAD~1", "r1"), ("git rebase --exe='git branch r2' HEAD~1", "r2"),
                      ("git rebase --exec 'git branch r3' HEAD~1", "r3")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert G._rebase_exec(["--e", "x"]) == []  # --e names several options of git rebase
    assert G._rebase_exec(["--ex", "x", "--exe=y"]) == ["x", "y"]


def test_shallow_file_takes_a_value(target):
    for cmd, name in (("git --shallow-file v branch s1", "s1"), ("git --shallow-file v -C . switch -c s2", "s2")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)


def test_the_alias_check_skips_global_option_values(target, tmp_path):
    cwd, c = session("clean", tmp_path)
    c.git("config", "--local", "alias.nb", "branch")
    for cmd, name in (("git -C %s nb a1" % P(target.path), "a1"), ("g''it -C %s nb a2" % P(target.path), "a2")):
        reason = verdict(hook(cwd, cmd))  # the alias of the session repository is expanded in the repository -C names
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for cmd, subs in (("git -C ../B nb x", ["nb"]), ("git -c alias.x=y x", ["x"]), ("git --git-dir=d nb", ["nb"]), ("/usr/bin/git -C x status", ["status"])):
        assert G._git_subcommands(cmd) == subs, cmd
    start = time.monotonic()
    assert G._git_subcommands("git -C " * 30000) == []
    assert time.monotonic() - start < time_budget(2)


def test_refs_heads_in_any_case_is_a_branch(target):
    for cmd, name in (("git update-ref refs/HEADS/h1 HEAD", "h1"), ("git push . HEAD:refs/Heads/h2", "h2"), ("git fetch . main:refs/hEaDs/h3", "h3"),
                      ("printf 'create refs/HEADS/h4 HEAD' | git update-ref --stdin", "h4"), ("git symbolic-ref HEAD refs/HEADS/h5", "h5")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)


def test_update_ref_reads_its_options_as_git_does(target):
    for cmd, name in (("git update-ref -m -d refs/heads/u1 HEAD", "u1"), ("git update-ref -mwhy refs/heads/u2 HEAD", "u2"),
                      ("printf 'create refs/heads/u3 HEAD' | git update-ref --std", "u3"), ("printf 'create refs/heads/u4 HEAD' | git update-ref --s", "u4")):
        reason = verdict(hook(target.path, cmd))  # -m takes the next word as its message, --std and --s are --stdin
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for cmd in ("git update-ref -d refs/heads/agent/other", "git update-ref -zd refs/heads/agent/other", "git update-ref -dm why refs/heads/agent/other",
                "git update-ref --no-deref HEAD refs/heads/u5"):  # deletes, and an update of HEAD itself
        assert records("Bash", cmd, target.path) == [], cmd


def test_start_process_runs_git_in_its_working_directory(target, tmp_path):
    cwd, _c = session("clean", tmp_path)
    li = P(target.path)
    for cmd, name in (("Start-Process git -ArgumentList 'switch -c w1' -WorkingDirectory %s" % li, "w1"), ("Start-Process git -ArgumentList 'switch -c w2' -Wo:%s" % li, "w2"),
                      ("Start-Process git -ArgumentList 'switch -c w3' -WorkingDirectory:%s" % li, "w3"), ("Start-Process git -a 'switch -c w4' -wo %s" % li, "w4"),
                      ("Start-Process git -ArgumentList 'switch', '-c', 'w6' -WorkingDirectory %s" % li, "w6"),  # an array: the words go on after a comma
                      ("Start-Process git -ArgumentList: 'switch -c w8' -WorkingDirectory: %s" % li, "w8")):  # a colon with nothing after it takes the next word
        reason = verdict(hook(cwd, cmd, tool="PowerShell"))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
        assert where(cmd, cwd, tool="PowerShell", name=name) == [(False, li.lower())], cmd  # judged in L, not in the session directory
    here = "Start-Process git -ArgumentList 'switch -c w5'"
    assert verdict(hook(cwd, here, tool="PowerShell")) is None  # no -WorkingDirectory: it runs in C
    assert where(here, cwd, tool="PowerShell", name="w5") == [(False, P(cwd).lower())]
    reason = verdict(hook(target.path, "Start-Process git -ArgumentList 'switch -c w7' -WorkingDirectory $d", tool="PowerShell"))
    assert reason and UNPARSE in reason, reason  # a computed directory: the repository is not known
    assert G._start_process(["-Verb", "open", "-a", "x"], [False] * 4) is None  # no git among its words
    start = time.monotonic()
    G.interpret("Start-Process git -ArgumentList " + "a, " * 30000, str(cwd), sh="ps")  # a list of 30,000 words is read in linear time
    assert time.monotonic() - start < time_budget(5)


def test_powershell_options_are_read_in_every_spelling(target):
    def enc(text):
        return base64.b64encode(text.encode("utf-16-le")).decode("ascii")
    b = enc("git switch -c e1")
    lines = [("powershell -e %s" % b, "e1"), ("powershell -ec %s" % b, "e1"), ("pwsh -EncodedC %s" % b, "e1"), ("pwsh -en %s" % b, "e1"),
             ("powershell -Comm 'git switch -c e2'", "e2"), ("pwsh -Co 'git switch -c e3'", "e3"), ("pwsh -cwa 'git switch -c e4'", "e4"),
             ("bash -ec 'git switch -c e6'", "e6"), ("bash -ce 'git switch -c e7'", "e7")]  # any bundle of short options that holds a c
    for cmd, name in lines:
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for argv, name in ((["powershell", "-ec", b], "e1"), (["pwsh", "-Co", "git switch -c e3"], "e3"), (["powershell", "-Command", "git", "switch", "-c", "e5"], "e5")):
        reason = verdict(hook(target.path, argv, host="codex"))  # the words after a PowerShell command option are one text
        assert reason and NOMAN in reason and "'%s'" % name in reason, (argv, reason)
    assert G.shell_command(payload("Bash", ["powershell", "-Command", "git", "status"], target.path)) == ("git status", "ps")
    assert G.shell_command(payload("Bash", ["cmd", "/c", "git", "status"], target.path)) == ("git status", "cmd")
    assert G.shell_command(payload("Bash", ["pwsh", "-ec", b], target.path)) == ("git switch -c e1", "ps")
    assert G.shell_command(payload("Bash", ["pwsh", "-ec", "ANg="], target.path)) == (G._OPAQUE, "ps")  # a lone UTF-16 surrogate: no text, a dynamic creation
    assert G.shell_command(payload("Bash", [], target.path)) == ("", "bash")  # an empty argv runs nothing
    assert verdict(hook(target.path, "powershell -ex Bypass -Command 'git status'")) is None  # -ex is ExecutionPolicy
    assert [G._shell_flag("pwsh", w) for w in ("-ex", "-encodeda", "-NoProfile", "-File", "-", "-e", "--command", "/c", "-CommandWithArgs", "-commandw")] == \
        [None, None, None, None, None, "encoded", "command", "command", "command", "command"]
    assert G._shell_flag("bash", "-lc") == "command" and G._shell_flag("bash", "-ce") == "command" and G._shell_flag("bash", "-e") is None
    assert G._shell_flag("cmd", "/k") == "command" and G._shell_flag("bash", "--norc") is None
    for line in ("powershell -ec %s" % enc("magos_guard.py disarm"), "pwsh -Co 'magos_guard.py disarm'", "powershell -e %s" % enc("magos_guard.py install --host codex")):
        found = G.protected(line)
        assert found and found[0] == "always" and "user-only" in found[1], (line, found)
    assert G.protected("powershell -ex Bypass -Command 'git status'") is None


def test_the_powershell_backtick_is_the_escape_character(target):
    for cmd, name in (("g`it switch -c k1", "k1"), ("git switch -c fe`at", "feat"), ("git sw`itch -c k3", "k3")):
        reason = verdict(hook(target.path, cmd, tool="PowerShell"))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert verdict(hook(target.path, "gi`t switch -c k4", tool="PowerShell")) is None  # `t is a tab: the program is gi and a tab, no git
    assert [[w for w, _ in seg] for seg in G._lex("a`0b`tc", "ps") if isinstance(seg, list)] == [["a\0b\tc"]]
    assert [[w for w, _ in seg] for seg in G._lex("ma`gos.guard `$x `;", "ps") if isinstance(seg, list)] == [["magos.guard", "$x", ";"]]  # literal, never special
    assert [[d for _, d in seg] for seg in G._lex("a`$b", "ps") if isinstance(seg, list)] == [[False]]  # an escaped $ is a letter of the word
    assert [[w for w, _ in seg] for seg in G._lex("a`0b`tc", "bash") if isinstance(seg, list)] == [["a`0b`tc"]]  # the escape of another shell is no escape here


def test_the_gate_reads_words_without_quotes(target):
    for cmd, name in (("g''it switch -c q1", "q1"), ('"g"it switch -c q2', "q2"), ('g""it sw\'\'itch -c q3', "q3")):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    assert G._gated("g''it x") and G._gated('"g"it x') and G._gated("g\\it x") and G._gated("g^it x") and G._gated("g`it x")


def test_text_that_runs_a_script_is_walked(target):
    target.write("mk", "git switch -c fromscript\n")  # untracked
    for cmd in ("echo $(. ./mk)", "echo $(bash ./mk)", "bash <<EOF\n. ./mk\nEOF", ". ./mk", "bash ./mk", "sh ./mk", "FOO=1 sudo -E sh ./mk", "if true; then bash ./mk; fi",
                "find . -maxdepth 1 -exec sh ./mk {} \\;",  # find runs the command after its -exec
                r'echo \"; bash ./mk; echo \"'):  # an escaped quote opens no string: bash runs the script between the two
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'fromscript'" in reason, (cmd, reason)
    target.write("harmless.txt", "ls\n")
    for cmd in ("git status", "bash ./harmless.txt", "sh ./nonexistent", ". ./nonexistent", "cmd /c dir", "bash -lc 'ls -la'", "powershell -NoProfile -Command Get-Date"):
        assert verdict(hook(target.path, cmd)) is None, cmd  # ordinary commands stay allowed
    assert not G._gated("echo hi") and G._gated("run x.bash") and G._gated("x" * (G.MAX_TEXT + 1))
    for text in ("ls .", "echo sh bash cmd", "cat ./bash", "grep -r foo . | wc -l", "ls -la; echo done", "find . -name sh"):
        assert not G._gated(text), text  # a runner's name where no command starts is no gate
    for text in ("cmd /c dir", r"C:\Git\bin\bash.exe x", '& "C:\\Program Files\\Git\\bin\\bash.exe" ./mk', "timeout 5 bash ./mk", "xargs sh", "time . ./mk", "$out = bash ./mk",
                 "ls; (cd x && . ./mk)", "pwsh -File x", "find . -exec sh ./mk {} \\;"):
        assert G._gated(text), text
    start = time.monotonic()
    for text in ("(" * 30000, "FOO=1 " * 30000, "env " * 30000, "'" * 30000, '"x ' * 30000, "a;" * 30000):
        assert G._gated(text) in (True, False)
    assert time.monotonic() - start < time_budget(5)


def test_missing_directory_records_keep_their_prior_directory(target, tmp_path):
    cwd, _c = session("clean", tmp_path)
    li = P(target.path)
    line = "cd /nonexist; git switch -c m1; cd %s; cd /nonexist; git switch -c m1" % li
    reason = verdict(hook(cwd, line))
    assert reason and UNPARSE in reason, reason  # the second creation runs in L, the shell having stayed there
    inner = "cd /nonexist; echo $(git switch -c m2); cd %s; cd /nonexist; echo $(git switch -c m2)" % li
    assert verdict(hook(cwd, inner))  # the substituted text runs in L as well
    for cmd, name in ((line, "m1"), (inner, "m2")):
        priors = sorted(P(c["cwd"].prior).lower() for c in G.interpret(cmd, str(cwd)) if c["names"] == [name] and isinstance(c["cwd"], G._Missing))
        assert priors == sorted([P(cwd).lower(), li.lower()]), (cmd, priors)  # one record per prior directory
    assert verdict(hook(cwd, "cd /nonexist; git switch -c m1")) is None  # the prior directory alone is the clean repository
    chain = "git init nd && cd nd && git switch -c f1; cd nd; git switch -c f1"  # the chain follows its first cd into the new repository, the later cd stays in L
    reason = verdict(hook(target.path, chain))
    assert reason and UNPARSE in reason, reason
    follows = [c["cwd"].follow for c in G.interpret(chain, str(target.path)) if c["names"] == ["f1"]]
    assert sorted(f is None for f in follows) == [False, True]  # a record that follows the chain and one that does not stay two records


# ---- the update-ref and refs family of the review of release 1.0.3 -----------------------------------------------------------------------------
def must_be_dynamic(target, cmd, tool="Bash"):
    reason = verdict(hook(target.path, cmd, tool=tool))
    assert reason and UNPARSE in reason, (tool, cmd, reason)


def must_name(target, cmd, name, tool="Bash"):
    reason = verdict(hook(target.path, cmd, tool=tool))
    assert reason and NOMAN in reason and "'%s'" % name in reason, (tool, cmd, reason)


def must_pass(target, cmd, tool="Bash"):
    assert verdict(hook(target.path, cmd, tool=tool)) is None, (tool, cmd)


def test_update_ref_stdin_c_quoted_name_is_dynamic(target, guard):
    lines = [r"""printf 'update "refs/heads/q1" HEAD\n' | git update-ref --stdin""", r"""printf 'create "refs/heads/q2" HEAD\n' | git update-ref --stdin""",
             """git update-ref --stdin <<< 'update "refs/heads/q6" HEAD'""", """git update-ref --stdin <<EOF\nupdate "refs/heads/q7" HEAD\nEOF""",
             r"""printf 'update "refs/heads/\142" HEAD\n' | git update-ref --stdin""", """echo 'create "refs/heads/q8" HEAD' | git update-ref --stdin""",
             r"""printf 'create refs/tags/t HEAD\nsymref-create "refs/heads/q9" refs/heads/main\n' | git update-ref --stdin"""]
    for cmd in lines:  # git unquotes the name: the hook cannot tell which branch it is
        must_be_dynamic(target, cmd)
    plan(guard, target, "q1", "docs/q1.md")
    must_be_dynamic(target, lines[0])  # a claim for the name inside the quotes allows nothing the hook cannot read
    assert G._stdin_refs('create "refs/heads/x" HEAD') == ([], True)
    assert G._stdin_refs("update 'refs/heads/x' HEAD") == ([], True)


def test_update_ref_stdin_escaped_or_formatted_text_is_dynamic(target):
    lines = [r"printf 'update refs/he\x61ds/q3 HEAD\n' | git update-ref --stdin", r"printf 'update re\x66s/heads/q4 HEAD\n' | git update-ref --stdin",
             r"printf '%s refs/heads/q5 HEAD\n' update | git update-ref --stdin", r"echo -e 'update \x72efs/heads/q10 HEAD' | git update-ref --stdin",
             r"printf '%b' 'update refs/he\x61ds/q11 HEAD\n' | git update-ref --stdin", r"printf 'create refs/%s/q2 HEAD\n' heads | git update-ref --stdin",
             r"printf 'create %s HEAD\n' refs/heads/q4 | git update-ref --stdin", r"printf 'create refs/hea\144s/q3 HEAD\n' | git update-ref --stdin",
             r"printf 'start\ncre\x61te refs/heads/x HEAD\ncommit\n' | git update-ref --stdin",  # the verbs around it do not make it a readable text
             r"""printf 'create refs/heads/x %s\n' "$sha" | git update-ref --stdin""", "git update-ref --stdin <<EOF\ncreate refs/heads/$B HEAD\nEOF",
             "echo create refs/heads/x{a,b} HEAD | git update-ref --stdin", r"printf 'create\x20refs/heads/x HEAD\n' | git update-ref --stdin"]
    for cmd in lines:
        must_be_dynamic(target, cmd)
    for text in (r"create refs/heads/a\x62c HEAD", r"cre\x61te refs/heads/a HEAD", r"start\ncre\x61te refs/heads/a HEAD", r"create refs/heads/a\0123 HEAD",
                 r"create refs/heads/a\\b HEAD", "create refs/heads/a%sb HEAD"):
        assert G._stdin_refs(text)[1] is True, text


def test_update_ref_stdin_name_continued_after_a_quote_is_the_joined_name(target, guard):
    for cmd in (r"printf 'update refs/heads/main''x HEAD\n' | git update-ref --stdin", """echo "update refs/heads/main"x" HEAD" | git update-ref --stdin"""):
        must_name(target, cmd, "mainx")  # the shell joins the pieces: the new branch is mainx, not the existing main
    plan(guard, target, "mainx", "docs/mainx.md")
    must_pass(target, r"printf 'update refs/heads/main''x HEAD\n' | git update-ref --stdin")  # judged by the name the shell makes, so a claim for it allows it


def test_update_ref_stdin_from_an_unreadable_source_is_dynamic(target):
    unreadable = ["git commit -qm x ; git update-ref --stdin < instr.txt", 'git update-ref -m "start work" --stdin < instr.txt',
                  "git update-ref --stdin < instr.txt # update later", "git update-ref --stdin<instr.txt", "git update-ref --stdin 0< instr.txt",
                  "git update-ref --stdin < <(cat instr.txt)", "git update-ref --stdin < refs.txt; git commit --allow-empty -m x",
                  "cat refs.txt | git update-ref --stdin && git commit -m done", "echo 'create refs/heads/q HEAD' | cat | git update-ref --stdin",
                  "{ echo 'create refs/heads/q HEAD'; } | git update-ref --stdin", "echo hi | (git update-ref --stdin)", "git update-ref --stdin",
                  "exec 0< instr.txt; git update-ref --stdin", "cat f <<EOF | git update-ref --stdin\ncreate refs/heads/q HEAD\nEOF",
                  "git update-ref --stdin <<< 'delete refs/heads/agent/other' && git update-ref --stdin < f", "git update-ref --stdin <<< \"$x\"",
                  "bash -c \"git update-ref --stdin < f\""]
    for cmd in unreadable:
        must_be_dynamic(target, cmd)
    for cmd in ("printf 'create refs/heads/x HEAD\\n' | git update-ref --stdin", "git update-ref --stdin <<< 'create refs/heads/x HEAD'",
                "cat <<< 'create refs/heads/x HEAD' | git update-ref --stdin", "cat <<EOF | git update-ref --stdin\ncreate refs/heads/x HEAD\nEOF",
                "cat << EOF | git update-ref --stdin\ncreate refs/heads/x HEAD\nEOF", "git update-ref --stdin <<EOF\ncreate refs/heads/x HEAD\nEOF",
                "git update-ref --stdin <<'EOF'\ncreate refs/heads/x HEAD\nEOF", "bash -c \"printf 'create refs/heads/x HEAD\\n' | git update-ref --stdin\""):
        must_name(target, cmd, "x")  # a source the hook reads: the name it holds is judged
    must_name(target, "'create refs/heads/x HEAD' | git update-ref --stdin", "x", tool="PowerShell")
    must_name(target, "Write-Output 'create refs/heads/x HEAD' | git update-ref --stdin", "x", tool="PowerShell")
    must_name(target, "echo 'create refs/heads/x HEAD' | git update-ref --stdin", "x", tool="terminal")
    for cmd in ("git update-ref --stdin <<< 'delete refs/heads/agent/other'", "printf 'delete refs/heads/agent/other\\n' | git update-ref --stdin",
                "printf 'start\\nupdate refs/tags/v1 HEAD\\nupdate HEAD HEAD\\ncommit\\n' | git update-ref --stdin",
                "git update-ref -m 'why <here' --stdin <<< 'delete refs/heads/agent/other'", "git update-ref --stdin -z <<< 'verify refs/heads/agent/other'"):
        must_pass(target, cmd)  # nothing it holds creates a branch


def test_update_ref_stdin_every_create_and_update_needs_a_plain_name(target):
    for cmd in (r"""printf 'create refs/heads/a1 HEAD\ncreate "refs/heads/a2" HEAD\n' | git update-ref --stdin""",  # the second name hides behind a plain one
                r"""printf 'create refs/heads/a1\0HEAD\0create "refs/heads/a2"\0HEAD\0' | git update-ref -z --stdin""",
                "git update-ref --stdin <<EOF\ncreate refs/tags/a HEAD\\\ncreate refs/heads/b HEAD\nEOF",
                r"""printf 'create refs/heads/a HEAD\n''create "refs/heads/b" HEAD\n' | git update-ref --stdin"""):  # one printf format, joined by the shell
        must_be_dynamic(target, cmd)
    two = r"printf 'create refs/heads/a1 HEAD\ncreate refs/heads/a2 HEAD\n' | git update-ref --stdin"
    must_name(target, two, "a1")
    assert [c["names"] for c in records("Bash", two, target.path)] == [["a1", "a2"]]  # both instructions are read
    must_name(target, r"printf 'create refs/heads/feature/update-docs HEAD\n' | git update-ref --stdin", "feature/update-docs")  # a verb word inside a name is no verb
    table = [("create refs/heads/x HEAD", (["x"], False)), ("update refs/tags/v1 HEAD", ([], False)), ("update HEAD HEAD", ([], False)),
             ("update ORIG_HEAD HEAD", ([], False)), ("symref-create refs/heads/s refs/heads/main", (["s"], False)), ("delete refs/heads/old", ([], False)),
             (r"create refs/heads/a HEAD\ncreate refs/heads/b HEAD", (["a", "b"], False)), ("create refs/heads/x", (["x"], False)),
             (r"create refs/heads/x\0HEAD\0", (["x"], False)), ("create refs/heads/-x HEAD", (["-x"], False)),
             ("create refs/heads/a b HEAD", (["a b"], False)), ("create REFS/HEADS/x HEAD", (["x"], False)),
             ("", ([], True)), ("hello", ([], True)), ("create", ([], True)), ("create ", ([], True)), ('create "refs/heads/x" HEAD', ([], True)),
             ("create refs/heads/ HEAD", ([], True)), ("create refs/heads/x..y HEAD", (["x..y"], True)), ("create refs/heads/$B HEAD", ([], True)),
             ("create refs/heads/x$B HEAD", (["x"], True)), (r"create refs/heads/a\x62c HEAD", (["a"], True)), ("create heads/x HEAD", ([], True)),
             ("xcreate refs/heads/x HEAD", ([], True)), ("CREATE refs/heads/x HEAD", ([], True)), ("create refs/heads/x;y\nupdate foo", (["x;y"], True))]
    for text, want in table:
        assert G._stdin_refs(text) == want, text


def test_update_ref_stdin_is_read_only_where_it_is_run(target):
    mentions = ["""git grep -n "update-ref --stdin\\|create refs/heads/" -- docs""", """git log --oneline --grep="update-ref --stdin" --grep="create refs/heads/\"""",
                """git commit -m "tests: update-ref --stdin reads names (create refs/heads/ then a quote)\"""",
                "git show HEAD:docs/d.md | grep -n 'update-ref --stdin' | grep 'create refs/heads/'",
                "cat > notes.md <<'EOF'\nUse: printf 'create refs/heads/x HEAD\\n' | git update-ref --stdin\nEOF",
                'git commit -m "docs: note update-ref --stdin create refs/heads/foo"', 'git commit -m "docs: update-ref --stdin takes create refs/heads/newthing lines"',
                'echo "git update-ref --stdin reads: create refs/heads/new1 sha" >> notes.md', "cat > doc.md <<EOF\nuse git update-ref --stdin:\ncreate refs/heads/new2 HEAD\nEOF",
                "echo git update-ref --stdin takes create refs/heads/new3", "git grep update-ref --stdin -- docs"]
    for cmd in mentions:
        must_pass(target, cmd)  # no update-ref runs: nothing is created, and nothing is read as an instruction
    for cmd in ("\"$GIT\" update-ref --stdin <<< 'create refs/heads/x HEAD'", "/usr/bin/env git update-ref --stdin <<< 'create refs/heads/x HEAD'",
                "GIT=git; \"$GIT\" -C . update-ref --stdin <<< 'create refs/heads/x HEAD'", "git-update-ref --stdin <<< 'create refs/heads/x HEAD'"):
        must_name(target, cmd, "x")  # a git the walk cannot name is still read, in command position
    must_be_dynamic(target, "\"$GIT\" update-ref --stdin < f")
    must_be_dynamic(target, "git-update-ref --stdin < f")
    reason = verdict(hook(target.path, "git update-ref --stdin <<< 'create refs/heads/x HEAD'; git commit -m \"update-ref --stdin create refs/heads/foo\""))
    assert reason and "'x'" in reason and "'foo'" not in reason, reason  # only the command that runs it
    assert G._unseen_update_ref([("echo", False), ("git", False), ("update-ref", False), ("--stdin", False)]) is None
    assert G._unseen_update_ref([("git", False), ("grep", False), ("update-ref", False), ("--stdin", False)]) is None
    assert G._unseen_update_ref([("$g", True), ("update-ref", False), ("--stdin", False)])["file"] is False
    assert G._unseen_update_ref([("$g", True), ("update-ref", False), ("--stdin", False), ("<", False), ("f", False)])["file"] is True


def test_refs_prefix_in_any_case_is_a_branch(target):
    for cmd, name in (("git update-ref REFS/heads/zz1 HEAD", "zz1"), ("git update-ref Refs/Heads/zz2 HEAD", "zz2"), ("git update-ref rEfS/heads/c3 HEAD", "c3"),
                      ("git update-ref REFS/HEADS/c2 HEAD", "c2"), ("printf 'create REFS/heads/c6 HEAD' | git update-ref --stdin", "c6"),
                      (r"printf 'update Refs/Heads/q5 HEAD\n' | git update-ref --stdin", "q5"), ("git push . HEAD:REFS/heads/zz3", "zz3"),
                      ("git fetch . main:Refs/heads/zz4", "zz4"), ("git symbolic-ref HEAD REFS/heads/zz5", "zz5"),
                      ("git symbolic-ref REFS/heads/zz6 refs/heads/main", "zz6")):
        must_name(target, cmd, name)
    for cmd in ("git update-ref REFS/tags/t1 HEAD", "git update-ref refs/remotes/origin/x HEAD", "git update-ref refs/headſ/x HEAD", "git push . HEAD:REFS/tags/t",
                "git update-ref -d REFS/heads/agent/other", "git update-ref REFS/notes/x HEAD"):
        must_pass(target, cmd)  # a ref outside refs/heads/, and a letter outside ASCII that only looks like s
    assert G._HEADS.match("REFS/heads/x") and G._HEADS.match("rEfS/HeAdS/x") and not G._HEADS.match("refs/headſ/x") and not G._HEADS.match("heads/x")


def test_a_refspec_destination_under_refs_heads_is_the_branch_after_it(target):
    for cmd, name in (("git push . HEAD:refs/heads/refs/x1", "refs/x1"), ("git fetch . main:refs/heads/refs/x1b", "refs/x1b"),
                      ("git push . HEAD:refs/HEADS/refs/x2", "refs/x2"), ("git push . HEAD:REFS/heads/refs/x3", "refs/x3"),
                      ("git pull . main:refs/heads/refs/x4", "refs/x4"), ("git push . HEAD:x5", "x5"), ("git push . +HEAD:x6", "x6")):
        must_name(target, cmd, name)
    for cmd in ("git push . HEAD:refs/tags/t", "git push . HEAD:refs/refs/x", "git push . HEAD:refs/remotes/o/x", "git push . HEAD:refs/notes/x",
                "git push . HEAD:REFS/tags/t", "git fetch . main:refs/tags/t2"):
        must_pass(target, cmd)  # a destination that begins with refs/ outside refs/heads/ is no branch


def test_a_push_refspec_with_an_empty_source_creates_nothing(target):
    for cmd in ("git push . :refs/HEADS/nothere", "git push . +:refs/HEADS/nothere", "git push . :refs/heads/nothere", "git push . :nothere",
                "git push . :refs/HEADS/agent/other"):
        must_pass(target, cmd)  # git deletes the destination, or warns that it does not exist
    for cmd, name in (("git fetch . :refs/heads/zz9", "zz9"), ("git pull . :refs/heads/zz10", "zz10"), ("git push . HEAD:refs/heads/zz11", "zz11"),
                      ("git fetch . +:zz12", "zz12")):
        must_name(target, cmd, name)  # an empty source of fetch and pull is HEAD: the destination is created


def test_symbolic_ref_message_is_no_ref(target):
    for cmd, name in (("git symbolic-ref -m why HEAD refs/heads/z1", "z1"), ("git symbolic-ref -m why refs/heads/z2 refs/heads/main", "z2"),
                      ("git symbolic-ref -m why HEAD refs/HEADS/z5", "z5"), ("git symbolic-ref -qm why HEAD refs/heads/z7", "z7"),
                      ("git symbolic-ref -mwhy HEAD refs/heads/z4", "z4"), ("git symbolic-ref HEAD refs/heads/z6 -m why", "z6"),
                      ("git symbolic-ref -- HEAD refs/heads/z8", "z8")):
        must_name(target, cmd, name)
    for cmd in ("git symbolic-ref HEAD", "git symbolic-ref -q --short HEAD", "git symbolic-ref -m why HEAD refs/heads/agent/other", "git symbolic-ref HEAD refs/tags/x",
                "git symbolic-ref -m refs/heads/z9 HEAD"):
        must_pass(target, cmd)  # a read, an existing branch, and a reason that looks like a ref
    assert G._symbolic_ref_args(["-m", "why", "HEAD", "refs/heads/z"], [False] * 4) == [("HEAD", False), ("refs/heads/z", False)]
    assert G._symbolic_ref_args(["-qm", "why", "--", "-m", "x"], [False] * 5) == [("-m", False), ("x", False)]


def test_names_git_accepts_are_creations(target):
    for cmd, name in (("git update-ref refs/heads/-x9 HEAD", "-x9"), ("git push . HEAD:refs/heads/-x12", "-x12"), ("git fetch . main:-dash5", "-dash5"),
                      ('git update-ref "refs/heads/a b" HEAD', "a b"), ('git branch "a b"', "a b"), ('git switch -c "a b"', "a b"),
                      ('git checkout -b "a　b"', "a　b"), ('git worktree add -b "a\u0085b" ../wt', "a\u0085b"),
                      ("git update-ref --stdin <<< 'create refs/heads/-x HEAD'", "-x")):
        must_name(target, cmd, name)
    for cmd in ("git switch -c -x9", "git branch -- -x9", "git checkout -b -x9", 'git update-ref "refs/heads/a b" HEAD', 'git update-ref "refs/heads/a~b" HEAD',
                "git push . HEAD:refs/heads/a:b", 'git branch "a\tb"'):
        must_pass(target, cmd)  # git refuses these names (a dash makes an option of the branch name; an ASCII space, ~ and a control character are never allowed)
    assert G._BAD_NAME.search("a b") and G._BAD_NAME.search("a\x7fb") and G._BAD_NAME.search("a\x1fb") and not G._BAD_NAME.search("a b\u0085")
    assert [c["names"] for c in records("Bash", "git update-ref refs/heads/-x9 HEAD", target.path)] == [["-x9"]]
    assert records("Bash", "git branch -- -x9", target.path) == [] and records("Bash", "git switch -c -x9", target.path) == []


def test_update_ref_and_symbolic_ref_dynamic_ref_words_are_dynamic(target):
    dynamic = ["git update-ref $ref HEAD", 'git update-ref "$REF" HEAD', "git update-ref -- $ref HEAD", "git update-ref -m msg $ref HEAD", "git update-ref ${R} HEAD",
               "git update-ref $(printf refs/heads/d3) HEAD", "read r; git update-ref $r HEAD", "echo refs/heads/d8 | xargs -I{} git update-ref {} HEAD",
               "echo refs/heads/d9 HEAD | xargs git update-ref", "git symbolic-ref HEAD $ref", "git symbolic-ref HEAD $B", "git symbolic-ref $name refs/heads/main",
               "git symbolic-ref -m why HEAD $B", "git update-ref $dir/x HEAD"]
    for cmd in dynamic:
        must_be_dynamic(target, cmd)
    for tool in ("PowerShell", "terminal"):
        must_be_dynamic(target, "git update-ref $r HEAD", tool=tool)
    must_name(target, "ref=refs/heads/d1; git update-ref $ref HEAD", "d1")  # a variable the line assigns is read
    for cmd in ("git update-ref refs/tags/$T HEAD", "git update-ref -d $ref", "git update-ref HEAD $new", 'git update-ref -m "$msg" refs/tags/x HEAD',
                "echo refs/tags/t | xargs git update-ref refs/tags/x", "git symbolic-ref HEAD", "git symbolic-ref --short $x", "git symbolic-ref HEAD refs/tags/$T",
                "git update-ref -d --no-deref $ref"):
        must_pass(target, cmd)  # a delete, a dynamic value, and a word under another namespace name no branch


def test_the_refs_family_reads_in_linear_time(target):
    here = str(target.path)
    start = time.monotonic()
    piped = G.interpret("printf '" + "create refs/heads/x HEAD\\n" * 5000 + "' | git update-ref --stdin", here)
    doc = G.interpret("git update-ref --stdin <<EOF\n" + "create refs/heads/a HEAD\n" * 5000 + "EOF", here)
    deletes = G.interpret("git update-ref --stdin <<< 'delete refs/heads/a'; " * 3000, here)
    unseen = G.interpret("\"$GIT\" update-ref --stdin < f; " * 3000, here)
    symbolic = G.interpret("git symbolic-ref " + "-m x " * 20000 + "HEAD refs/heads/z", here)
    update = G.interpret("git update-ref " + "-m x " * 20000 + "refs/heads/z HEAD", here)
    for text in ("create " * 100000, "create refs/heads/x HEAD\\n" * 40000, "\\n" * 100000, "update refs/heads/" + "a" * 100000):
        G._stdin_refs(text)
    assert time.monotonic() - start < time_budget(15)
    assert [(c["names"][:1], len(c["names"]), c["dynamic"]) for c in piped] == [(["x"], 5000, False)]
    assert [(c["names"][:1], len(c["names"]), c["dynamic"]) for c in doc] == [(["a"], 5000, False)]
    assert deletes == [] and [c["dynamic"] for c in unseen] == [True]  # 3,000 identical unreadable sources are one record
    assert [c["names"] for c in symbolic] == [["z"]] and [c["names"] for c in update] == [["z"]]


# ---- redirections of the shell, bundled `git branch` options and hostile nesting of the review of release 1.0.3 -----------------------------------
def test_a_leading_redirection_hides_no_creation(target):
    for cmd, name in ((">/dev/null git switch -c r1", "r1"), ("2>/dev/null git switch -c r2", "r2"), ("&>f git switch -c r3", "r3"),
                      (">>f git switch -c r4", "r4"), ("<f git switch -c r5", "r5"), ("> /dev/null git switch -c r6", "r6"),
                      ("2> /dev/null git switch -c r7", "r7"), ("<<< x git switch -c r8", "r8"), (">&2 git switch -c r9", "r9"),
                      ("2>&1 git switch -c r10", "r10"), (">/dev/null 2>&1 git switch -c r11", "r11"), ("3>&1 git switch -c r12", "r12"),
                      (">|f git switch -c r13", "r13"), (">& /dev/null git switch -c r14", "r14"), ("<< EOF git switch -c r15\nbody\nEOF", "r15"),
                      ("FOO=1 >f git switch -c r16", "r16"), (">f env git switch -c r17", "r17"), ("time >f git switch -c r18", "r18"),
                      ("git>/dev/null switch -c r19", "r19"), ("git switch -c r20>/dev/null", "r20"), ('bash -c ">/dev/null git switch -c r21"', "r21"),
                      ("{fd}>f git switch -c r28", "r28"), ("{fd}> f git switch -c r29", "r29"), ('>"/dev/null" git switch -c r30', "r30"),
                      ("eval '>/dev/null git switch -c r31'", "r31"),
                      ("sh -c '2>/dev/null git switch -c r22'", "r22"), ("true && >/dev/null git switch -c r23", "r23"),
                      ("{ >/dev/null git switch -c r24; }", "r24"), ("( 2>&1 git switch -c r25 )", "r25"),
                      ("if true; then >/dev/null git switch -c r26; fi", "r26"), ("echo $(2>/dev/null git switch -c r27)", "r27"),
                      ('cmd /c ">nul git switch -c c1"', "c1")):
        must_name(target, cmd, name)
    for cmd, name in (("git 2>$null switch -c k1", "k1"), (">$null git switch -c k2", "k2"), ("git *> $null switch -c k3", "k3"),
                      ("git switch -c k4 2>&1", "k4")):
        must_name(target, cmd, name, tool="PowerShell")
    for cmd in (">/dev/null gh pr checkout 1", "gh 2>/dev/null pr checkout 1", "gt >/dev/null create x", "claude 2>/dev/null -w x"):
        reason = verdict(hook(target.path, cmd))
        assert reason and UNPLAN in reason, (cmd, reason)
    for cmd in (">/dev/null git status", "2>&1 git log --oneline", "git status >/dev/null 2>&1", "echo hi > out.txt", ">/dev/null echo git switch -c x",
                "> git switch -c x"):  # the last redirects into a file named git and runs `switch`
        must_pass(target, cmd)


def test_a_redirection_between_git_and_its_subcommand_hides_no_creation(target, tmp_path):
    for cmd, name in (("git >/dev/null switch -c m1", "m1"), ("git 2>/dev/null checkout -b m2", "m2"), ("git -C . >/dev/null switch -c m3", "m3"),
                      ("git -C >/dev/null . switch -c m4", "m4"), ("git -c core.x=y 2>&1 branch m5", "m5"), ("git > /dev/null switch -c m6", "m6"),
                      ("git <f switch -c m7", "m7"), ("git >|f branch m8", "m8"), ("git -C . 2>&1 worktree add -b m9 ../wt-m9", "m9")):
        must_name(target, cmd, name)
    cwd, c = session("clean", tmp_path)
    c.git("config", "--local", "alias.nb", "branch")
    for cmd, name in (("git -C %s >/dev/null switch -c d1" % P(target.path), "d1"), ("git -C %s 2>&1 nb d2" % P(target.path), "d2")):
        reason = verdict(hook(cwd, cmd))  # the repository -C names judges it, behind the redirection as well
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for cmd in ("git >/dev/null status", "git -C . 2>&1 log -1"):
        must_pass(target, cmd)


def test_a_redirection_among_the_words_of_a_git_invocation_is_no_argument(target):
    for cmd, name in (("git update-ref >/dev/null refs/heads/n1 HEAD", "n1"), ("git update-ref 2>/dev/null refs/heads/n2 HEAD", "n2"),
                      ("git update-ref 2> /dev/null refs/heads/n3 HEAD", "n3"), ("git update-ref -m msg >/dev/null refs/heads/n4 HEAD", "n4"),
                      ("git update-ref &>f refs/heads/n5 HEAD", "n5"), ("git update-ref >/dev/null --stdin <<< 'create refs/heads/n6 HEAD'", "n6"),
                      ("git symbolic-ref >/dev/null HEAD refs/heads/n7", "n7"), ("git symbolic-ref 2>&1 -m why HEAD refs/heads/n8", "n8"),
                      ("git branch >/dev/null n9", "n9"), ("git branch -m old n10 >/dev/null", "n10"), ("git switch -c >/dev/null n11", "n11")):
        must_name(target, cmd, name)
    for cmd in ("git update-ref >/dev/null -d refs/heads/agent/other", "git update-ref --stdin >/dev/null <<< 'delete refs/heads/agent/other'",
                "git update-ref >/dev/null refs/tags/t HEAD", "git symbolic-ref >/dev/null HEAD"):
        must_pass(target, cmd)
    assert [c["names"] for c in records("Bash", "git update-ref >/dev/null refs/heads/n1 HEAD", target.path)] == [["n1"]]
    assert [c["names"] for c in records("Bash", "git branch -m old n10 >/dev/null", target.path)] == [["n10"]]  # not the redirection that ends the words


def test_the_lexer_reads_redirection_operators_as_words():
    def show(text, sh="bash"):
        return [[("R%d:%s" % (w.take, w) if isinstance(w, G._Redir) else str(w)) for w, _d in ev] if isinstance(ev, list) else ev for ev in G._lex(text, sh)]
    assert show("git status 2>&1") == [["git", "status", "R1:2>&1"]]
    assert show("git >&2 status") == [["git", "R1:>&2", "status"]]
    assert show("echo hi &>f") == [["echo", "hi", "R1:&>f"]] and show("echo hi &>>f") == [["echo", "hi", "R1:&>>f"]]
    assert show("echo hi >|f") == [["echo", "hi", "R1:>|f"]] and show("echo hi >&2 | cat") == [["echo", "hi", "R1:>&2"], "|", ["cat"]]
    assert show("cat <<< x") == [["cat", "R2:<<<", "x"]] and show("cat << EOF") == [["cat", "R2:<<", "EOF"]] and show("cat <<-EOF") == [["cat", "R1:<<-EOF"]]
    assert show("git>/dev/null switch -c x") == [["git", "R1:>/dev/null", "switch", "-c", "x"]]
    assert show("echo a2>f") == [["echo", "a2", "R1:>f"]] and show("echo 2>f") == [["echo", "R1:2>f"]] and show("echo a>f") == [["echo", "a", "R1:>f"]]
    assert show("echo > f") == [["echo", "R2:>", "f"]] and show("echo 2> f") == [["echo", "R2:2>", "f"]] and show("echo >& f") == [["echo", "R2:>&", "f"]]
    assert show("echo $((1<<2))") == [["echo", "$((1<<2))"]] and show("echo ${x:-a>b}") == [["echo", "${x:-a>b}"]]
    assert not any(isinstance(w, G._Redir) for ev in G._lex("cat <(echo a) >(cat)", "bash") if isinstance(ev, list) for w, _d in ev)
    assert show("echo hi |& cat") == [["echo", "hi"], "|", ["cat"]] and show("a && b") == [["a"], "&&", ["b"]] and show("a & b") == [["a"], "&", ["b"]]
    assert show("git switch -c x &") == [["git", "switch", "-c", "x"], "&"] and show("echo hi >f&&git status") == [["echo", "hi", "R1:>f"], "&&", ["git", "status"]]
    assert show("{fd}>f git status") == [["R1:{fd}>f", "git", "status"]] and show("{fd}> f git status") == [["R2:{fd}>", "f", "git", "status"]]
    assert show("git 2>&1 status", "ps") == [["git", "R1:2>&1", "status"]] and show("git *>$null status", "ps") == [["git", "R1:*>$null", "status"]]
    assert show("git status 2>&1", "ps") == [["git", "status", "R1:2>&1"]] and show("echo hi &>f", "ps")[0][:2] == ["echo", "hi"]
    assert show("echo hi 2>&1 & git switch -c x", "cmd") == [["echo", "hi", "R1:2>&1"], "&", ["git", "switch", "-c", "x"]]
    assert show("echo a>f", "cmd") == [["echo", "a", "R1:>f"]] and show("git 2>&1 status", None) == [["git", "R1:2>&1", "status"]]
    assert show("echo *>f") == [["echo", "*", "R1:>f"]]  # bash: a glob, then the redirection
    for text in ("2>&1", ">&2", "<&3", "2>", "<<<", ">|f", "&>f"):  # every spelling is one word, taking a second one only when it is the operator alone
        word = next(w for ev in G._lex(text, "bash") if isinstance(ev, list) for w, _d in ev)
        assert isinstance(word, G._Redir) and word == text and word.take == (2 if text in ("2>", "<<<") else 1), text


def test_a_quoted_or_escaped_redirection_looking_word_is_a_word(target):
    for cmd, name in (("git -c '>x' branch x3", "x3"), ("git branch '>x'", ">x"), ("git branch \\>y", ">y"), ("git switch -c '>z'", ">z")):
        must_name(target, cmd, name)
    for cmd in ("git --git-dir '>' branch x1", "git --git-dir \\> branch x2"):  # the quoted word is the value of the option: a directory that is no repository
        reason = verdict(hook(target.path, cmd))
        assert reason and REDIRECT in reason, (cmd, reason)
    for cmd in ("'>f' git switch -c x4", '">" git switch -c x5', "git '>' switch -c x6"):
        must_pass(target, cmd)  # the program is `>f` or `>`, and the subcommand of git is `>`
    for text in ("'>x'", "\\>x", '">" y', "'2>&1' x"):
        assert not any(isinstance(w, G._Redir) for ev in G._lex(text, "bash") if isinstance(ev, list) for w, _d in ev), text


def test_the_word_gate_skips_leading_redirections(target):
    target.write("mk", "git switch -c fromscript\n")  # untracked
    for cmd in (">/dev/null bash ./mk", "2>&1 sh ./mk", "&>f . ./mk", "> out bash ./mk", "FOO=1 2>/dev/null source ./mk", "time >f bash ./mk",
                "echo ok | >/dev/null bash ./mk"):
        reason = verdict(hook(target.path, cmd))
        assert reason and NOMAN in reason and "'fromscript'" in reason, (cmd, reason)
    for text in (">/dev/null bash x", "2>&1 bash x", "&>f . x", "> out sh x", ">/dev/null\nbash x", "<f zsh x", ">& /dev/null cmd /c dir", "FOO=1 >f pwsh x"):
        assert G._gated(text) and G._runs_script(text), text
    for text in ("echo hi >/dev/null", "ls 2>&1", "echo '>x' bash", ">f echo bash", "echo hi >bash", "> bash", "ls >&2", "cat <(echo sh)"):
        assert not G._gated(text), text  # a runner as the target of a redirection, or in the arguments of another command, is no gate
    assert G._TOKEN.findall("2>&1 bash x") == ["2>&1", "bash", "x"] and G._TOKEN.findall("a &&b") == ["a", "&", "&", "b"]


def test_the_alias_check_and_the_tamper_filter_skip_redirections(target, tmp_path):
    cwd, c = session("clean", tmp_path)
    c.git("config", "--local", "alias.nb", "branch")
    for cmd, name in (("git 2>/dev/null -C %s nb a1" % P(target.path), "a1"), ("git -C %s >/dev/null nb a2" % P(target.path), "a2"),
                      ("git > /dev/null -C %s nb a3" % P(target.path), "a3"), ("git>/dev/null -C %s nb a4" % P(target.path), "a4")):
        reason = verdict(hook(cwd, cmd))
        assert reason and NOMAN in reason and "'%s'" % name in reason, (cmd, reason)
    for text, subs in (("git 2>/dev/null nb x", ["nb"]), ("git -C a >f nb y", ["nb"]), ("git -C '>' nb z", ["nb"]), ("git > f status", ["status"]),
                       ("git>f nb x", ["nb"]), ("git >f", []), ("git >", [])):
        assert G._git_subcommands(G._bare(text)) == subs, text
    start = time.monotonic()
    assert len(G._git_subcommands("git >f " * 30000)) == 29999 and time.monotonic() - start < time_budget(2)  # each git word is the subcommand of the one before
    for line in ("2>/dev/null rm .git/hooks/reference-transaction", "> out rm -f .git/hooks/x", ">f cp x .git/magos/claims/f.claim",
                 "FOO=1 2>&1 rm .git/magos/ARMED", ">/dev/null env rm .git/magos/ARMED"):
        assert G.protected(line) == ("guarded", G._STATE_MSG), line
    for line in ("rm -f out >/dev/null", "echo hi > x", ">f echo .git/hooks/x", "ls .git/hooks 2>&1"):
        assert G.protected(line) is None, line


def test_a_redirection_before_the_script_of_a_shell_hides_none(target):
    target.write("mk", "git switch -c fromscript\n")
    target.write("harmless.txt", "ls\n")
    for cmd, name in (("bash -c >/dev/null 'git switch -c s1'", "s1"), ("bash 2>&1 -c 'git switch -c s2'", "s2"), ('sh -c 2>/dev/null "git switch -c s3"', "s3"),
                      ("bash -lc >/dev/null 'git switch -c s4'", "s4"), ("bash >a >b >c >d ./mk", "fromscript"), ("bash 2>&1 ./mk", "fromscript"),
                      ("bash < ./mk", "fromscript"), ("bash -s < ./mk", "fromscript"), ("bash <./mk", "fromscript"), ("sh 0<./mk", "fromscript"),
                      (". 2>&1 ./mk", "fromscript"), ("source >/dev/null ./mk", "fromscript")):
        must_name(target, cmd, name)
    must_name(target, "powershell -Command 2>&1 'git switch -c s5'", "s5", tool="PowerShell")
    for cmd in ("bash -c >/dev/null 'git status'", "bash >a >b >c >d ./harmless.txt", "bash <<< 'ls'", "bash <(echo ls)", "sh 2>&1 -c 'ls -la'"):
        must_pass(target, cmd)
    assert G._input_files([("<", False), ("./mk", False), ("<x", False), ("0<y", False), ("<<<", False), ("t", False), ("<(a)", False), ("<", False)]) == ["./mk", "x", "y"]


def test_bundled_short_options_of_git_branch_are_read_left_to_right(target):
    for cmd in ("git branch -df old", "git branch -Df old", "git branch -Dr origin/old", "git branch -dr origin/old", "git branch -rd origin/old",
                "git branch -rD origin/old", "git branch -fd old", "git branch -dq old", "git branch -qd old", "git branch -vd old", "git branch -vvd old",
                "git branch -vu origin/main", "git branch -dr origin/feat-x origin/old", "git branch -uorigin/main", "git branch -lr 'x*'", "git branch -d -f old",
                "git branch -D -r origin/old", "git branch --delete -f old", "git branch -a", "git branch -vv", "git branch -r", "git branch -ra"):
        must_pass(target, cmd)  # a deletion, a listing or an upstream change creates no lane
        must_pass(target, cmd, tool="PowerShell")
    for cmd, name in (("git branch -mr old n1", "n1"), ("git branch -ma old n2", "n2"), ("git branch -cr old n3", "n3"), ("git branch -Cr old n4", "n4"),
                      ("git branch -fmr old n5", "n5"), ("git branch -m -r old n6", "n6"), ("git branch -m -a old n7", "n7"), ("git branch -c -r old n8", "n8"),
                      ("git branch -tdirect n9 main", "n9"), ("git branch -td n10 main", "n10"), ("git branch -ft n11 main", "n11"), ("git branch -f n12", "n12"),
                      ("git branch -v n13", "n13"), ("git branch -vf n14 main", "n14"), ("git branch -q n15", "n15")):
        must_name(target, cmd, name)
        must_name(target, cmd, name, tool="PowerShell")
    assert [G._branch_short(t) for t in ("-vvd", "-uorigin/d", "-tdm", "--delete", "-", "-f", "x")] == ["vvd", "u", "t", "", "", "f", ""]
    assert G._branch_moves(["-mr", "a", "b"]) and G._branch_moves(["-tc", "a"]) is False and G._branch_lists(["-vd", "a"]) and not G._branch_lists(["-td", "a"])


def test_a_chain_of_relative_c_options_is_linear(target):
    here = str(target.path)
    base = (here + "/" + "d" * 4100)[:4090]
    assert len(base) == 4090 and G._join(base, "a/bcdefghij") is None and G._join(None, "a/b") is None and G._join(base, "a") is not None
    big = ("C:/" if os.name == "nt" else "/") + "x" * 5000
    assert G._join(base, big) == big
    line = "git " + "-C a/b " * 27000 + "status; git switch -c zzpad"
    assert len(line) < G.MAX_TEXT
    start = time.monotonic()
    chain = G.interpret(line, here)
    inside = G.interpret("git " + "-C a/b " * 27000 + "switch -c zzin", here)
    aliased = G.interpret("git " + "-C a " * 20000 + "nb x", here)
    assert time.monotonic() - start < time_budget(5)
    assert [c["names"] for c in chain] == [["zzpad"]] and chain[0]["cwd"] == here  # the chain's own `status` creates nothing
    assert [(c["names"], c["cwd"]) for c in inside] == [(["zzin"], None)] and aliased == []  # a path past the limit is an unknown directory
    start = time.monotonic()
    seen = verdict(hook(target.path, line))
    assert time.monotonic() - start < time_budget(5)
    assert seen and NOMAN in seen and "'zzpad'" in seen, seen
    start = time.monotonic()
    reason = verdict(hook(target.path, "git " + "-C a/b " * 27000 + "switch -c zzin"))
    assert time.monotonic() - start < time_budget(5)
    assert reason and UNPARSE in reason, reason


def test_nested_groups_are_walked_in_linear_time(target):
    here, n = str(target.path), 98000
    deep = "(" * n + "git status" + ")" * n
    shapes = [("bash", deep, []), ("ps", deep, []), ("bash", "{ " * 49000 + "git status; " + "} " * 49000, []), ("ps", "{ " * 49000 + "git status; " + "} " * 49000, []),
              ("ps", "(" * n + ")" * n + "; git switch -c hz3", ["hz3"]), ("bash", "(" * n + ")" * n + "; git switch -c hz3", ["hz3"]),
              ("bash", "if true; then " * 10000 + "git status" + "; fi" * 10000, []), ("bash", ")" * 100000 + "; git switch -c hz4", ["hz4"]),
              ("bash", "} " * 90000 + "git switch -c hz5", ["hz5"])]
    for sh, text, names in shapes:
        assert len(text) <= G.MAX_TEXT
        start = time.monotonic()
        found = [c["names"][0] for c in G.interpret(text, here, sh=sh)]
        assert time.monotonic() - start < time_budget(5), (sh, text[:20], time.monotonic() - start)
        assert found == names, (sh, text[:20], found)
    for tool, text in (("PowerShell", "(" * n + ")" * n + "; git switch -c hz3"), ("Bash", "{ " * 49000 + "git status; " + "} " * 49000 + "git switch -c hz6")):
        start = time.monotonic()
        reason = verdict(hook(target.path, text, tool=tool))
        assert time.monotonic() - start < time_budget(5), (tool, time.monotonic() - start)
        assert reason and NOMAN in reason, (tool, reason)


def test_redirection_operators_are_read_in_linear_time(target):
    here = str(target.path)
    shapes = [">" * 199000 + " git switch -c x", ">&" * 66000 + " git switch -c x", "2>&1 " * 39000 + "git switch -c x", "> f " * 49000 + "git switch -c x",
              "git " + ">f " * 66000 + "switch -c x", "a>" * 99000, "{fd}>f " * 28000 + "git switch -c x", "<<< x " * 30000 + "git switch -c x",
              "&>f " * 45000 + "git switch -c x", ">|f " * 45000 + "git switch -c x", "1" * 199000 + ">f git switch -c x", "echo $((" + "1<<" * 60000 + "2))",
              "git " + "-C >f a " * 24000 + "switch -c x", "git update-ref " + ">f " * 60000 + "refs/heads/x HEAD", "bash " + ">f " * 60000 + "./mk"]
    for text in shapes:
        assert len(text) <= G.MAX_TEXT
        for sh in ("bash", "ps", None):
            start = time.monotonic()
            G.interpret(text, here, sh=sh)
            assert time.monotonic() - start < time_budget(5), (text[:12], sh, time.monotonic() - start)
        start = time.monotonic()
        G._gated(text), G.protected(text), G._git_subcommands(G._bare(text))
        assert time.monotonic() - start < time_budget(5), (text[:12], time.monotonic() - start)
    assert [c["names"] for c in G.interpret(shapes[2], here, sh="bash")] == [["x"]] and G.interpret(shapes[5], here, sh="bash") == []
    start = time.monotonic()
    reason = verdict(hook(target.path, shapes[3]))
    assert time.monotonic() - start < time_budget(5)
    assert reason and NOMAN in reason and "'x'" in reason, reason


# ---- sets (1.0.4): the host hook and the git layer around set-plan ---------------------------------------------------------------------
def set_lane(wtbase, set_name, lid, paths, deps=()):
    """A lane of a spec: the branch is agent/<set>/<id>, the worktree directory ends with -<set>-<id> after a prefix; it serves the requirement R1."""
    return {"id": lid, "title": "lane " + lid, "branch": "agent/%s/%s" % (set_name, lid), "worktree": P(Path(wtbase) / ("wt-%s-%s" % (set_name, lid))), "serves": ["R1"],
            "outcome": "the outcome of " + lid, "paths": list(paths), "depends_on": list(deps), "acceptance": "it works"}


def register_set(guard, repo, tmp_path, name, lanes):
    """set-plan of `name` against the main tip of `repo`: the spec lies outside every worktree.  -> the spec."""
    spec = {"v": 1, "title": name, "requirements": [{"id": "R1", "text": "the task is done"}], "base": repo.git("rev-parse", "main"), "sheet": "sheet", "notes": [],
            "shared": [], "lanes": lanes}
    f = Path(tmp_path) / ("spec-%s-%s.json" % (name, repo.path.name))
    f.write_text(json.dumps(spec), encoding="utf-8")
    r = guard(repo, "set-plan", "--set", name, "--target", "main", "--spec", str(f))
    assert r.rc == 0, r.out + r.err
    return spec


def demo_set(guard, repo, tmp_path, wtbase=None):
    wt = wtbase or Path(tmp_path) / "wt"
    return register_set(guard, repo, tmp_path, "demo", [set_lane(wt, "demo", "api", ["src/api/"]), set_lane(wt, "demo", "ui", ["src/ui/"], ["api"]),
                                                         set_lane(wt, "demo", "docs", ["docs/"])])


def raw_git(repo, *args, cwd=None):
    """subprocess.run of git in `repo` without a check, made again when the machine killed the child (conftest.crashed)."""
    return retried(lambda: subprocess.run(["git", *args], cwd=str(cwd or repo.path), capture_output=True, stdin=subprocess.DEVNULL, env=os.environ.copy()),
                   lambda p: crashed(p.stderr.decode("utf-8", "replace"), p.returncode))


def test_set_subcommands_are_not_user_only(guard, tmp_path):
    armed = make(tmp_path, "armed")
    assert guard(armed, "arm").rc == 0
    plan(guard, armed, "agent/held", "web/")  # the repository is armed and holds a claim
    empty, _ = session("empty", tmp_path)
    body = json.dumps({"v": 1, "sheet": "-> .git/magos/claims/x.claim; git switch -c x; rm .git/magos/ARMED; git worktree add ../w -b y"})
    g = "py -3 scripts/magos_guard.py"
    subs = ["set-plan --set demo --target main --spec -", "set-show --set demo --drift", "set-update --set demo --expect-revision 1 --lane api --state active --note x",
            "set-release --set demo --reason done --abandon"]
    launcher = P(ROOT / "hooks" / "run-guard.cmd")
    allowed = []
    for s in subs:
        allowed += [("Bash", "%s %s" % (g, s)), ("Bash", "%s --json --lang en %s" % (g, s)), ("Bash", "%s --repo=. --json %s" % (g, s)), ("Bash", "%s --rep . %s" % (g, s)),
                    ("Bash", "%s -- %s" % (g, s)), ("Bash", "bash -c '%s %s'" % (g, s)), ("Bash", 'cmd /c start "" /min %s %s' % (g, s)), ("Bash", "start %s %s" % (g, s)),
                    ("Bash", '"%s" --strict %s' % (launcher, s)), ("PowerShell", "& py -3 scripts/magos_guard.py %s" % s),
                    ("PowerShell", "Start-Process py -ArgumentList '-3 scripts/magos_guard.py %s'" % s), ("terminal", "%s %s" % (g, s))]
    allowed += [("Bash", "%s set-plan --set demo --target main --spec - <<'EOF'\n%s\nEOF" % (g, body)), ("Bash", "echo '%s' | %s --json set-plan --set demo --target main --spec -" % (body, g)),
                ("Bash", "printf '%%s' '%s' | %s --lang en set-plan --set demo --target main --spec - --dry-run" % (body, g)),
                ("PowerShell", "@'\n%s\n'@ | py -3 scripts/magos_guard.py set-plan --set demo --target main --spec -" % body),
                ("PowerShell", "'%s' | py -3 scripts/magos_guard.py --json set-plan --set demo --target main --spec -" % body),
                ("terminal", "cat spec.json | %s set-plan --set demo --target main --spec -" % g)]
    for cwd in (armed.path, empty):
        for tool, cmd in allowed:
            assert verdict(hook(cwd, cmd, tool=tool)) is None, (cwd, tool, cmd)
    for argv in (["py", "-3", "scripts/magos_guard.py", "set-show", "--set", "demo"], ["py", "-3", "scripts/magos_guard.py", "--json", "set-plan", "--set", "d", "--target", "main", "--spec", "-"],
                 ["bash", "-lc", g + " set-release --set demo"]):
        assert verdict(hook(armed.path, argv, host="codex")) is None, argv  # the Codex shell payloads
        assert verdict(hook(armed.path, argv, tool="shell", host="codex")) is None, argv
    assert G.protected("%s set-plan --set demo --target main --spec - <<'EOF'\n%s\nEOF" % (g, body)) is None
    assert G.protected("echo '%s' | %s set-plan --set demo --target main --spec -" % (body, g)) is None
    # the four user-only subcommands stay denied in the same spellings
    for sub_name in ("override --fingerprint 0123456789ab --reason y", "arm", "disarm", "install --host codex"):
        for line in ("%s %s" % (g, sub_name), "%s --json --lang en %s" % (g, sub_name), "%s --repo=. %s" % (g, sub_name), "bash -c '%s %s'" % (g, sub_name),
                     'cmd /c start "" /min %s %s' % (g, sub_name), "%s %s <<'EOF'\n%s\nEOF" % (g, sub_name, body), "echo '%s' | %s %s" % (body, g, sub_name),
                     '"%s" --strict %s' % (launcher, sub_name)):
            for cwd in (armed.path, empty):
                reason = verdict(hook(cwd, line))
                assert reason and "user-only" in reason, (cwd, line, reason)
    # the launcher refuses a set subcommand at run time, as it refuses every subcommand but hook
    halves = launcher_halves()
    if halves:
        stubbed = launcher_layout(tmp_path, LAUNCH_STUB)
        log = tmp_path / "starts.log"
        for half in halves:
            for words in (["set-plan", "--set", "demo", "--target", "main", "--spec", "-"], ["set-show", "--set", "demo"], ["set-update", "--set", "demo"], ["set-release", "--set", "demo"]):
                r = run_launcher(half, stubbed, words, env={"STUB_LOG": str(log)})
                assert r.returncode == 2 and ONLY_HOOK in r.stderr.decode("utf-8", "replace"), (half, words, r)
                assert not log.exists(), (half, words)  # the guard never started
    # the same text through the guard itself: the spec holds the words of a branch creation and of a write to the store, and nothing in it runs
    via = make(tmp_path, "viastdin")
    spec = {"v": 1, "title": "t", "requirements": [{"id": "R1", "text": "the task is done"}], "base": via.git("rev-parse", "main"), "sheet": body, "notes": [], "shared": [],
            "lanes": [set_lane(tmp_path / "wt-s", "demo", "api", ["src/api/"])]}
    out = guard(via, "set-plan", "--set", "demo", "--target", "main", "--spec", "-", stdin=json.dumps(spec).encode("utf-8"))
    assert out.rc == 0 and branches(via) == ["main"] and not (tmp_path / "wt-s").exists()
    assert json.loads((Path(via.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "sets" / "demo.json").read_text(encoding="utf-8"))["sheet"] == body


def test_agent_writes_under_the_sets_directory_stay_denied(guard, tmp_path):
    armed = make(tmp_path, "armed")
    assert guard(armed, "arm").rc == 0
    demo_set(guard, armed, tmp_path, tmp_path / "wt-a")
    held = make(tmp_path, "held")  # AUTO, but it holds the claims of a set
    demo_set(guard, held, tmp_path, tmp_path / "wt-h")
    plain = make(tmp_path, "plain")  # neither armed nor holding a claim
    def store_of(repo):
        return P(Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "sets" / "demo.json")
    plain_writes = [("Bash", "rm .git/magos/sets/demo.json"), ("Bash", "rm -f .git/magos/sets/demo.json"), ("PowerShell", "Remove-Item .git/magos/sets/demo.json"),
              ("PowerShell", "Remove-Item -Force .git\\magos\\sets\\demo.json"), ("Bash", "echo {} > .git/magos/sets/demo.json"), ("Bash", "cp evil.json .git/magos/sets/demo.json"),
              ("Bash", "mv evil.json .git/magos/sets/demo.json"), ("Bash", "sed -i s/1/2/ .git/magos/sets/demo.json"), ("Bash", "echo x | tee .git/magos/sets/demo.json"),
              ("Bash", "bash -c 'rm .git/magos/sets/demo.json'"), ("Bash", "sh -c \"echo {} > .git/magos/sets/demo.json\""),
              ("PowerShell", "powershell -Command \"Remove-Item .git/magos/sets/demo.json\""), ("PowerShell", "Set-Content .git/magos/sets/demo.json x"),
              ("PowerShell", "'{}' | Out-File .git/magos/sets/demo.json"), ("Bash", "printf '{}' > .git/magos/sets/other.json"), ("Bash", "truncate -s 0 .git/magos/sets/demo.json")]
    def writes_for(repo):
        store = store_of(repo)  # the absolute path of the record in every separator and case spelling the platform folds
        variants = [store] + ([store.replace("/", "\\"), store.upper(), store.lower()] if os.name == "nt" else [])
        return plain_writes + [(tool, line % v) for v in variants for tool, line in (("Bash", "rm -f %s"), ("Bash", "echo {} > %s"), ("PowerShell", "Remove-Item %s"),
                                                                                    ("PowerShell", "Set-Content %s x"), ("Bash", "cp evil.json %s"), ("Bash", "mv evil.json %s"))]
    reads = [("Bash", "cat .git/magos/sets/demo.json"), ("Bash", "type .git\\magos\\sets\\demo.json"), ("PowerShell", "Get-Content .git/magos/sets/demo.json"),
             ("Bash", "py -3 scripts/magos_guard.py set-show --set demo"), ("Bash", "grep -c revision .git/magos/sets/demo.json"), ("Bash", "ls .git/magos/sets")]
    for repo in (armed, held):
        for tool, cmd in writes_for(repo):
            reason = verdict(hook(repo.path, cmd, tool=tool))
            assert reason and PROTECTED in reason, (repo.path.name, tool, cmd, reason)
        for tool, cmd in reads + [("Bash", "cat %s" % store_of(repo))]:
            assert verdict(hook(repo.path, cmd, tool=tool)) is None, (repo.path.name, tool, cmd)
    for tool, cmd in writes_for(plain):
        assert PROTECTED not in (verdict(hook(plain.path, cmd, tool=tool)) or ""), (tool, cmd)  # as for the claims: only once the repository is armed or holds a claim
    assert Path(store_of(armed)).is_file()


OVERLAP = "the planned files overlap the existing branches/worktrees below"


def lane_worktree(repo, wt, branch, files=None, msg="lane"):
    """A real lane worktree on a new branch cut from main (the git layer of an armed repository lets it through), with one commit that adds `files`."""
    p = raw_git(repo, "worktree", "add", "-q", str(wt), "-b", branch, "main")
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    for rel, text in (files or {}).items():
        repo.commit(rel, text, cwd=wt, msg=msg)


def test_lane_creation_after_set_plan(guard, tmp_path):
    for mode in ("armed", "auto"):
        r = make(tmp_path, mode)
        if mode == "armed":
            assert guard(r, "arm").rc == 0
        wt = tmp_path / ("wt-" + mode)
        demo_set(guard, r, tmp_path, wt)
        l1, l3 = P(wt / "wt-demo-api"), P(wt / "wt-demo-docs")
        add = lambda path, branch: 'git worktree add "%s" -b %s main' % (path, branch)
        assert verdict(hook(r.path, add(l1, "agent/demo/api"))) is None, mode  # the registered path and branch
        spellings = [l1.replace("/", "\\"), l1.upper(), l1.lower()] if os.name == "nt" else []  # the same directory only where the platform folds
        for spelled in spellings:
            assert verdict(hook(r.path, add(spelled, "agent/demo/api"))) is None, (mode, spelled)  # another separator style or case is the same path
        reason = verdict(hook(r.path, add(P(tmp_path / ("elsewhere-" + mode)), "agent/demo/api")))
        assert reason and l1.lower() in reason.replace("\\", "/").lower(), (mode, reason)  # path_mismatch names the registered path
        assert verdict(hook(r.path, "git switch -c agent/demo/ui")) is None, mode
        assert NOMAN in (verdict(hook(r.path, "git switch -c agent/demo/rogue")) or ""), mode
        lane_worktree(r, wt / "wt-demo-api", "agent/demo/api", {"src/api/a.py": "a\n"})  # git lets the registered creation through
        if mode == "armed":
            rogue = raw_git(r, "switch", "-c", "agent/demo/rogue")
            assert rogue.returncode != 0 and b"MAGOS" in rogue.stderr and "agent/demo/rogue" not in branches(r)  # the backstop vetoes the unclaimed branch
        assert verdict(hook(r.path, add(l3, "agent/demo/docs"))) is None, mode  # api's files lie outside docs's manifest
        r.commit("docs/x.md", "x\n", cwd=wt / "wt-demo-api", msg="sibling commits a file of docs's manifest")
        reason = verdict(hook(r.path, add(l3, "agent/demo/docs")))
        assert reason and OVERLAP in reason and "agent/demo/api" in reason, (mode, reason)  # denied, naming the sibling
        assert "agent/demo/docs" not in branches(r)


def test_lane_creation_is_judged_against_the_set_target(guard, tmp_path):
    # TC-341: develop is one commit ahead of main and changes src/api/a.py; the guard's default target is main
    r = make(tmp_path, "target")
    r.branch_with("develop", "src/api/a.py")
    r.git("config", "magos.target", "main")
    wt, base = tmp_path / "wt-target", r.git("rev-parse", "develop")
    spec = {"v": 1, "title": "demo", "requirements": [{"id": "R1", "text": "the task is done"}], "base": base, "sheet": "sheet", "notes": [], "shared": [],
            "lanes": [set_lane(wt, "demo", "api", ["src/api/"])]}
    f = tmp_path / "spec-target.json"
    f.write_text(json.dumps(spec), encoding="utf-8")
    p = guard(r, "set-plan", "--set", "demo", "--target", "develop", "--spec", str(f))
    assert p.rc == 0, p.out + p.err
    add = 'git worktree add "%s" -b agent/demo/api %s' % (P(wt / "wt-demo-api"), base)
    assert verdict(hook(r.path, add)) is None  # judged against develop, the target in the lane's claim, as set-plan judged it
    plain = make(tmp_path, "plain")
    plain.branch_with("develop", "src/api/a.py")
    plain.git("config", "magos.target", "main")
    assert guard(plain, "plan", "--branch", "feat/x", "--paths", "docs/").rc == 0
    cf = Path(plain.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "claims" / "feat" / "x.claim"
    cf.write_text(cf.read_text(encoding="utf-8").replace("target=main", "target=develop").replace("entry=docs/", "entry=src/api/"), encoding="utf-8")
    reason = verdict(hook(plain.path, "git switch -c feat/x"))
    assert reason and OVERLAP in reason and "develop" in reason, reason  # a claim without set= keeps the default target, whatever its target= says
    r.git("branch", "-D", "develop")
    reason = verdict(hook(r.path, add))
    assert reason and "develop" in reason, reason  # a stored target that no longer resolves denies


def test_integration_branch_creation_is_allowed_and_unrelated_creation_stays_denied(guard, tmp_path):
    for mode in ("armed", "auto"):
        r = make(tmp_path, mode)
        if mode == "armed":
            assert guard(r, "arm").rc == 0
        wt = tmp_path / ("wt-" + mode)
        demo_set(guard, r, tmp_path, wt)
        forms = ["git switch -c agent/demo/integration", "git branch agent/demo/integration", "git checkout -b agent/demo/integration",
                 "git update-ref refs/heads/agent/demo/integration HEAD"]
        for cmd in forms:
            assert verdict(hook(r.path, cmd)) is None, (mode, cmd)  # the creation is judged for its name and its claim only
        if mode == "armed":
            for args in (("switch", "-c"), ("branch",), ("checkout", "-b"), ("update-ref", "refs/heads/")):
                if args[0] == "update-ref":
                    p = raw_git(r, "update-ref", "refs/heads/agent/demo/integration", "HEAD")
                else:
                    p = raw_git(r, *args, "agent/demo/integration")
                assert p.returncode == 0, (args, p.stderr.decode("utf-8", "replace"))  # and the git layer finds the claim file of the name
                raw_git(r, "switch", "main")
                assert raw_git(r, "branch", "-D", "agent/demo/integration").returncode == 0
        # api and ui are merged into the integration branch
        lane_worktree(r, wt / "wt-demo-api", "agent/demo/api", {"src/api/a.py": "a\n"})
        lane_worktree(r, wt / "wt-demo-ui", "agent/demo/ui", {"src/ui/u.py": "u\n"})
        assert raw_git(r, "switch", "-c", "agent/demo/integration").returncode == 0
        assert raw_git(r, "merge", "-q", "--no-ff", "-m", "merge the lanes", "agent/demo/api", "agent/demo/ui").returncode == 0
        assert raw_git(r, "switch", "main").returncode == 0
        late = P(wt / "wt-demo-docs")
        assert verdict(hook(r.path, 'git worktree add "%s" -b agent/demo/docs main' % late)) is None, mode  # the merged files lie outside docs's manifest
        assert verdict(hook(r.path, "git switch -c agent/demo/docs")) is None, mode
        reason = verdict(hook(r.path, "git worktree add ../late -b agent/demo/docs"))  # another path than the registered one: path_mismatch
        assert reason and late.lower() in reason.replace("\\", "/").lower() and NOMAN not in reason, (mode, reason)
        assert NOMAN in (verdict(hook(r.path, "git switch -c agent/demo/late")) or ""), mode
        assert NOMAN in (verdict(hook(r.path, "git worktree add ../late -b agent/demo/late")) or ""), mode
        # an unrelated branch over ui's manifest: the plan is denied naming ui's claim, and its creation without a plan too
        denied = guard(r, "plan", "--branch", "feature/ui", "--paths", "src/ui/x.py")
        assert denied.rc == 10 and "agent/demo/ui" in denied.out and "DENIES" in denied.out, (mode, denied)
        assert NOMAN in (verdict(hook(r.path, "git switch -c feature/ui")) or ""), mode
        assert not (store_claim(r, "feature/ui")).exists()


def store_claim(repo, branch):
    return Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "claims" / (branch.replace("/", os.sep) + ".claim")


def test_integration_branch_creation_is_judged_for_name_and_claim_only(guard, tmp_path):
    for name, lanes, forms in (
            ("wild", [("docs", ["docs/**/*.md"]), ("root", ["*.md"]), ("src", ["src/"])],
             ["git switch -c agent/wild/integration", "git branch agent/wild/integration", "git checkout -b agent/wild/integration",
              "git worktree add ../int -b agent/wild/integration main"]),
            ("wide", [("markdown", ["**/*.md"]), ("python", ["src/**/*.py"])],
             ["git update-ref refs/heads/agent/wide/integration HEAD", "git switch -c agent/wide/integration", "git worktree add ../int -b agent/wide/integration main"])):
        for mode in ("armed", "auto"):
            r = make(tmp_path, "%s-%s" % (name, mode))
            if mode == "armed":
                assert guard(r, "arm").rc == 0
            wt = tmp_path / ("wt-%s-%s" % (name, mode))
            register_set(guard, r, tmp_path, name, [set_lane(wt, name, lid, paths) for lid, paths in lanes])
            assert (store_claim(r, "agent/%s/integration" % name)).is_file()

            def allowed(label):
                for cmd in forms:
                    assert verdict(hook(r.path, cmd)) is None, (name, mode, label, cmd)  # no manifest, commit or unknown of the judgement denies it
            allowed("fresh")
            first = "agent/%s/%s" % (name, lanes[0][0])
            second = "agent/%s/%s" % (name, lanes[1][0])
            lane_worktree(r, wt / ("wt-%s-%s" % (name, lanes[0][0])), first, {"docs/a.md": "a\n", "src/x.py": "x\n"}, "the files the manifests match")
            lane_worktree(r, wt / ("wt-%s-%s" % (name, lanes[1][0])), second, {"README.md": "r\n"}, "the files the manifests match")
            allowed("after the lanes committed")
            bad = store_claim(r, "zz-unreadable")
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("garbage", encoding="utf-8")
            allowed("with an unreadable claim")
            if mode == "armed":  # the git layer reads the claim file of the name only
                integration = "agent/%s/integration" % name
                p = raw_git(r, "switch", "-c", integration)
                assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
                assert raw_git(r, "switch", "main").returncode == 0 and raw_git(r, "branch", "-D", integration).returncode == 0
                p = raw_git(r, "worktree", "add", "-q", str(tmp_path / ("int-%s-%s" % (name, mode))), "-b", integration, "main")
                assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
            assert NOMAN in (verdict(hook(r.path, "git switch -c agent/%s/other" % name)) or ""), (name, mode)
            third = "agent/%s/%s" % (name, lanes[-1][0])
            if len(lanes) > 2:  # a lane branch is judged in full: the unreadable claim denies it
                reason = verdict(hook(r.path, "git switch -c " + third))
                assert reason and "CLAIM_UNPARSEABLE" in reason, (name, mode, reason)


def test_the_integration_exemption_cannot_be_requested_by_an_agent(guard, tmp_path):
    for mode in ("armed", "auto"):
        r = make(tmp_path, "x-" + mode)
        if mode == "armed":
            assert guard(r, "arm").rc == 0
        demo_set(guard, r, tmp_path, tmp_path / ("wt-" + mode))
        claims = ".git/magos/claims"
        evil = "state=active\nv=1\nbranch=evil\nworktree=\ntarget=main\nbase=0\ncreated=x\nby=x\noverride=\nset=evil\nrole=integration\nentry=src/**\n"
        absolute = P(Path(r.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "claims" / "evil.claim")
        writes = [("Bash", "printf 'role=integration' >> %s/agent/demo/api.claim" % claims), ("Bash", "cat > %s/evil.claim <<'EOF'\n%sEOF" % (claims, evil)),
                  ("Bash", "cp evil.claim %s/evil.claim" % claims), ("PowerShell", "Set-Content %s 'role=integration'" % absolute),
                  ("PowerShell", "Set-Content %s/evil.claim -Value @'\n%s'@" % (claims, evil)), ("Bash", "bash -c \"echo role=integration >> %s/agent/demo/ui.claim\"" % claims),
                  ("PowerShell", "powershell -Command \"Add-Content %s/agent/demo/ui.claim 'role=integration'\"" % claims), ("Bash", "echo 'role=integration' | tee -a %s/agent/demo/docs.claim" % claims),
                  ("Bash", "sed -i 's/^set=demo/role=integration/' %s/agent/demo/docs.claim" % claims)]
        for tool, cmd in writes:
            reason = verdict(hook(r.path, cmd, tool=tool))
            assert reason and PROTECTED in reason, (mode, tool, cmd, reason)  # a hand-made claim with role=integration cannot be created by an agent
        plain = guard(r, "plan", "--branch", "x/y", "--paths", "src/z/")
        assert plain.rc == 0
        lines = store_claim(r, "x/y").read_text(encoding="utf-8").split("\n")
        assert not [x for x in lines if x.startswith(("set=", "lane=", "role="))]  # plan writes no extra key of its own
        assert lines[-2] == "entry=src/z/"
        # the remains of an interrupted registration: the record is gone, the integration claim stays
        sets = Path(r.git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "magos" / "sets" / "demo.json"
        sets.unlink()
        before = store_claim(r, "agent/demo/integration").read_text(encoding="utf-8").split("\n")
        assert "set=demo" in before and "role=integration" in before and "entry=.magos/integration/demo/" in before
        amended = guard(r, "plan", "--amend", "--branch", "agent/demo/integration", "--paths", "lib/")  # lib/ is owned by no demo lane
        assert amended.rc == 0, amended.out + amended.err
        after = store_claim(r, "agent/demo/integration").read_text(encoding="utf-8").split("\n")
        assert "role=integration" in after and "set=demo" in after and "entry=lib/" in after and "entry=.magos/integration/demo/" not in after  # the key stays, the shape is gone
        denied = guard(r, "plan", "--branch", "x/lib", "--paths", "lib/x.py")
        assert denied.rc == 10 and "agent/demo/integration" in denied.out, (mode, denied)  # an ordinary claim: judged by its entries
        assert NOMAN in (verdict(hook(r.path, "git switch -c x/lib")) or ""), mode
