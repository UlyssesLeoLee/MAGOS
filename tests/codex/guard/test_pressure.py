"""End-to-end scenarios on real repositories: the lifecycle of a lane, the replica of the user's repository, and work-around attempts."""
from __future__ import annotations

import json
import os
import subprocess

from conftest import G, payload, run
from test_hook import denied, hook


def raw(repo, *args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd or repo.path), capture_output=True, stdin=subprocess.DEVNULL, env=os.environ.copy())


def test_lane_lifecycle_from_plan_to_release(repo, guard):
    wt = repo.path.parent / "wt-life"
    plan = guard(repo, "plan", "--branch", "agent/life", "--paths", "docs/", "src/a.py", "--worktree", str(wt))
    assert plan.rc == 0
    assert denied(hook(repo, command="git worktree add %s -b agent/life main" % str(wt).replace("\\", "/"))) is None
    assert raw(repo, "worktree", "add", str(wt), "-b", "agent/life", "main").returncode == 0
    rows = json.loads(guard(repo, "list", "--json").out)
    assert rows[0]["state"] == "active" and rows[0]["worktrees"]
    assert "agent/life" in guard(repo, "check", "--branch", "agent/second", "--paths", "docs/d.md").out  # a lane in progress blocks overlapping newcomers
    repo.commit("docs/d.md", "work\n", cwd=wt)
    assert guard(repo, "release", "--branch", "agent/life").rc == 16  # not merged: refused
    repo.git("merge", "-q", "agent/life")
    repo.git("worktree", "remove", "--force", str(wt))
    assert guard(repo, "release", "--branch", "agent/life", "--reason", "integrated").rc == 0
    assert guard(repo, "check", "--branch", "agent/second", "--paths", "docs/d.md").rc == 0  # the target holds the work now


def test_replica_of_the_users_repository(repo, guard):
    """Dirty primary worktree with hundreds of deleted files under tests/, branches develop_claude / test_claude / tests_codex."""
    for i in range(400):
        repo.write("tests/claude/results/r%03d.txt" % i, "r\n")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "tests tree")
    repo.git("branch", "-m", "main", "develop_claude")
    repo.git("branch", "test_claude")
    repo.git("branch", "tests_codex")
    repo.git("config", "--local", "magos.target", "develop_claude")
    for i in range(400):
        os.remove(repo.path / "tests" / "claude" / "results" / ("r%03d.txt" % i))
    first = guard(repo, "plan", "--branch", "agent/lane-guard", "--paths", "SKILL.md", "references/lane-split.md", "scripts/magos_guard.py", "hooks/")
    assert first.rc == 0
    second = guard(repo, "plan", "--branch", "agent/docs", "--paths", "references/")
    assert second.rc == 10 and "agent/lane-guard" in second.out and "declared" in second.out
    assert guard(repo, "plan", "--branch", "agent/tests", "--paths", "tests/claude/results/r001.txt").rc == 10  # the dirty primary worktree owns those paths
    assert guard(repo, "plan", "--branch", "agent/readme", "--paths", "README.md").rc == 0


def test_workaround_attempts_in_an_armed_repository(repo, guard):
    repo.branch_with("agent/other", "src/a.py")
    assert guard(repo, "arm").rc == 0
    attempts = ["git $CMD -c feature/a", "git switch -c $(echo feature/b)", "bash -c 'git branch feature/c'", "git branch feature/d && echo done",
                "powershell -Command \"git switch -c feature/e\"", "git -C %s checkout -b feature/f" % str(repo.path).replace("\\", "/")]
    for cmd in attempts:
        assert denied(hook(repo, command=cmd)) is not None, cmd
    before = repo.git("for-each-ref", "refs/heads")
    for args in (("branch", "feature/g"), ("update-ref", "refs/heads/feature/h", "HEAD"), ("switch", "-c", "feature/i")):  # the same by any other tool: the git layer
        p = raw(repo, *args)
        assert p.returncode != 0 and b"MAGOS" in p.stderr
    assert repo.git("for-each-ref", "refs/heads") == before


def test_user_commands_never_run_for_agents(repo):
    for cmd in ("py -3 magos_guard.py override --fingerprint abcdef123456 --reason ok", "git config --local magos.guard off"):
        assert denied(hook(repo, command=cmd)) is not None
    body = payload("Bash", "git config core.hooksPath none", repo.path)
    assert run(["hook", "claude", "pre-tool"], stdin=json.dumps(body).encode()).out.strip() == "{}"  # no lane exists yet: ordinary configuration
