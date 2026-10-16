"""1.0.2 host-hook hardening: repository redirects, missing cd targets, hooked tools, the executable search order, user-only spellings,
undecided engagement, override through plan only, JSON errors and silent Git failures."""
from __future__ import annotations

import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from conftest import G, SCRIPT, Repo, payload, run, time_budget

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


def crashed(text):
    """A git child killed by a Windows NTSTATUS (0xC0000000 and up, e.g. STATUS_COMMITMENT_LIMIT when the machine runs low on virtual
    memory): the environment failed, not the guard.  Seen as `exit code N` in a warning or a deny reason."""
    return any(int(n) >= 0xC0000000 for n in re.findall(r"exit code (\d+)", text))


def hook_body(body):
    for _ in range(3):  # a transient crash of git is retried; a failure that persists still fails the test
        r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=body)
        if not crashed(r.out + r.err):
            break
    assert r.rc == 0, r
    return r


def hook(cwd, command=None, tool="Bash", host="claude", **tool_input):
    body = payload(tool, command, cwd, **tool_input)
    for _ in range(3):
        r = run(["--lang", "en", "hook", host, "pre-tool"], stdin=json.dumps(body).encode("utf-8"))
        if not crashed(r.out + r.err):
            break
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


def where(cmd, cwd, tool="Bash", name=None):
    """(redirect, directory or git directory) of each record the hook judges, as comparable lower-case paths."""
    return sorted((c["redirect"], P(c["gitdir"] if c["redirect"] else c["cwd"]).lower()) for c in records(tool, cmd, cwd, name))


def test_a_change_inside_a_subshell_or_a_pipeline_is_judged_before_and_after(target, tmp_path):
    """A cd / pushd / Set-Location or a GIT_DIR change inside ( .. ) or inside one command of a pipeline does not replace the state the
    line was in: the commands after it are judged in both states, the stricter verdict applies; inside the group the changed state holds."""
    clean = make(tmp_path, "clean")
    c, l = P(clean.path), P(target.path)
    from_lanes = [  # session in the lane-bearing repository: git runs there, so it must be judged there although the line names C
        ("Bash", "(cd %s); git branch s1" % c),
        ("Bash", "(cd %s && cd src); git branch s2" % c),
        ("Bash", "cd %s | cat; git branch s3" % c),
        ("Bash", "pushd %s | cat; git branch s4" % c),
        ("Bash", "cat x | cd %s; git branch s5" % c),
        ("Bash", "(export GIT_DIR=%s/.git); git branch s6" % c),
        ("Bash", "((cd %s); cd %s/src); git branch s7" % (c, c)),
        ("PowerShell", "(Set-Location %s); git branch s8" % c),
        ("PowerShell", "Set-Location %s | Out-Null; git branch s9" % c),
        ("Bash", '(cd %s; echo "(") ; git branch s16' % c),  # the ')' after a quoted '(' still ends the group
        ("Bash", "echo $(true; (cd %s); git branch s17)" % c),  # a group inside $( .. ): its ')' is not the one that closes $(
    ]
    for tool, cmd in from_lanes:
        reason = verdict(hook(target.path, cmd, tool=tool))
        assert reason and NOMAN in reason, (tool, cmd, reason)
    assert where("(cd %s); git branch s1" % c, target.path, name="s1") == sorted([(False, l.lower()), (False, c.lower())])
    reason = verdict(hook(clean.path, "(cd %s); git branch s10" % l))  # the other way round: judged in both, the lane-bearing one denies
    assert reason and NOMAN in reason
    for cmd in ("(cd %s; git branch s11)" % c, "(cd %s && git branch s12)" % c, "cd %s && git branch s13 | cat" % c):
        assert verdict(hook(target.path, cmd)) is None, cmd  # inside the group git runs in C, which has a single lane
        assert where(cmd, target.path) == [(False, c.lower())], cmd
    reason = verdict(hook(target.path, "(echo $(pwd); cd %s); git branch s14" % c))  # the ')' that closes $( does not end the group
    assert reason and NOMAN in reason
    assert verdict(hook(clean.path, "(cd %s); cd %s; git branch s15" % (l, c))) is None  # a later plain cd replaces every state


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


def test_more_scoped_states_than_the_hook_walks_are_denied(target, tmp_path):
    clean = make(tmp_path, "clean")
    hops = [tmp_path / ("h%d" % k) for k in range(9)]
    for d in hops:
        d.mkdir()
    cmd = "; ".join("(cd %s)" % P(d) for d in hops) + "; git branch o1"
    reason = verdict(hook(clean.path, cmd))
    assert reason and UNPARSE in reason and "a condition or a background job may change the directory or GIT_DIR, which leaves the command in " + STATES in reason
    assert verdict(hook(clean.path, "; ".join("(cd %s)" % P(d) for d in hops[:7]) + "; git branch o2")) is None  # eight states: walked
    empty, _ = session("empty", tmp_path)
    assert UNPARSE in (verdict(hook(empty, cmd)) or "")
    steps = "git status; " * 2000 + "git branch o3"  # every command walked in seven further states spends the budget
    many = "; ".join("(cd %s)" % P(d) for d in hops[:7]) + "; " + steps
    assert [c["why"] for c in G.interpret(many, str(clean.path), sh="bash") if c.get("anywhere")] == [G._OVER_WORK]
    assert "more walking" in (verdict(hook(clean.path, many)) or "")
    assert not [c for c in G.interpret(steps, str(clean.path), sh="bash") if c.get("anywhere")]  # one state: within the budget


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
    subs = "; ".join("(cd %s)" % P(d) for d in hops)
    nest = "git branch q " + "y " * 5000
    for level in range(3):
        nest = "; ".join("cd %s" % P(d) for d in hops[:7]) + "; bash <<E%d\n%s\nE%d" % (level, nest, level)
    lines = ["%s; echo $(git branch o1)" % cds, "%s; git branch o2" % subs, nest]
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
    for tool in ("mcp__terminal__run_in_terminal", "mcp__desktop-commander__start_process", "mcp__shell__execute_command", "mcp__x__exec_command",
                 "mcp__x__terminal", "mcp__x__shell"):
        assert NOMAN in (verdict(hook(target.path, "git branch m2", tool=tool)) or ""), tool
    for tool in ("mcp__gbrain__run_doctor", "mcp__terminal__read_terminal", "mcp__scheduled-tasks__run_scheduled_task"):
        assert verdict(hook(target.path, "git branch m2", tool=tool)) is None, tool
    assert verdict(hook(target.path, ["git", "branch", "m3"], tool="Monitor")) is None  # Monitor takes a string command only
    assert verdict(hook(target.path, None, tool="Monitor", description="x")) is None
    assert G.is_shell_tool("Monitor") and not G.is_shell_tool("mcp__terminal__read_terminal") and not G.is_shell_tool("BashOutput")


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
    """The first interpreter the launcher would pick (python3, python, py -3) that runs, with its version."""
    for cand in (["python3"], ["python"], ["py", "-3"]):
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
            for _ in range(3):  # a transient crash of git is retried
                p = subprocess.run(python + ["-X", "utf8", "-B", str(SCRIPT), "--lang", "en", "hook", "claude", "pre-tool"], input=body, capture_output=True,
                                   cwd=str(tmp_path), env=dict(os.environ), creationflags=NO_WINDOW, timeout=120)
                if not crashed((p.stdout + p.stderr).decode("utf-8", "replace")):
                    break
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
        assert where(cmd, target.path, tool) == both, (tool, cmd)
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
                      ("PowerShell", "Invoke-Command { Set-Location %s }; git branch f5" % c), ("Bash", "{ cd %s; } & git branch f6" % c)):
        assert where(cmd, target.path, tool) == both, (tool, cmd)
    reason = verdict(hook(target.path, "f() { cd %s; }; git branch f7" % c))
    assert reason and NOMAN in reason
    assert where("cd %s && { git switch -c ok1; }" % c, target.path) == [(False, c.lower())]
    assert where("{ cd %s; git switch -c ok2; }" % c, target.path) == [(False, c.lower())]
    assert verdict(hook(target.path, "cd %s && { git switch -c ok3; }" % c)) is None


def test_a_list_sent_to_the_background_keeps_the_state_it_started_in(target, tmp_path):
    """A list ended by '&' runs in a background job: its cd may never reach the shell, so later commands are judged before and after it.
    In cmd '&' runs the next command after the first one, and cmd's `cd /d` switches the drive and directory together."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for cmd in ("cd %s & git branch g1" % c, "x && cd %s & git branch g2" % c, "cd %s &\ngit branch g3" % c):
        assert where(cmd, target.path) == both, cmd
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
    """PowerShell runs $(..), (..) and @(..) in the current scope, so a Set-Location there moves the commands after it; a substitution is
    judged as a possible change in every shell (bash runs it in a subshell, which only adds a state)."""
    l, c, clean, both = lanes_and_clean(target, tmp_path)
    for tool, cmd in (("PowerShell", "echo $(Set-Location %s); git branch s1" % l), ("PowerShell", "Write-Output $(Set-Location %s); git branch s2" % l),
                      ("PowerShell", "echo (Set-Location %s); git branch s3" % l), ("PowerShell", "$out = (Set-Location %s); git branch s4" % l),
                      ("Bash", "echo `cd %s`; git branch s5" % l), ("Bash", "echo $(cd %s); git branch s6" % l),
                      ("Bash", "echo $(true; cd %s); git branch s8" % l), ("Bash", "echo $(true\ncd %s); git branch s9" % l),
                      ("Bash", "cat <(true; cd %s); git branch s10" % l), ("PowerShell", "echo (Get-Date; Set-Location %s); git branch s11" % l)):
        assert where(cmd, clean.path, tool) == both, (tool, cmd)  # a command inside substituted text is no command of the line
    assert where("echo $(true ) cd %s; git branch s12" % l, clean.path) == [(False, c.lower())]  # words after the ')' belong to echo
    reason = verdict(hook(clean.path, "echo $(Set-Location %s); git branch s7" % l, tool="PowerShell"))
    assert reason and NOMAN in reason
    reason = verdict(hook(clean.path, "echo $(true; cd %s); git branch s13" % l))
    assert reason and NOMAN in reason
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
