"""The git layer (reference-transaction hook written by `arm`), disarm, doctor and the installer."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from conftest import ROOT, G, run


def common(repo):
    return Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir"))


def hook_path(repo):
    return common(repo) / "hooks" / "reference-transaction"


def vetoed(repo, *args, cwd=None):
    """A git command that must be vetoed by the hook: returns stderr; asserts nothing was created."""
    p = repo_git_raw(repo, *args, cwd=cwd)
    assert p.returncode != 0, (args, p.stdout, p.stderr)
    assert b"MAGOS" in p.stderr, p.stderr
    return p.stderr.decode("utf-8", "replace")


def repo_git_raw(repo, *args, cwd=None):
    import subprocess
    return subprocess.run(["git", *args], cwd=str(cwd or repo.path), capture_output=True, stdin=subprocess.DEVNULL, env=os.environ.copy())


@pytest.fixture
def armed(repo, guard):
    assert guard(repo, "arm").rc == 0
    return repo


# ---- arm / disarm ----------------------------------------------------------------------------------------------------
def test_arm_writes_the_hook_and_switches(repo, guard):
    r = guard(repo, "arm")
    assert r.rc == 0 and "did write" in r.out
    s = common(repo) / "magos"
    assert (s / "ARMED").is_file() and (s / "lang").read_text(encoding="utf-8").strip() == "en" and "magos_guard.py" in (s / "guard").read_text(encoding="utf-8")
    text = hook_path(repo).read_bytes()
    assert text.decode("utf-8").replace("\r\n", "\n") == G.HOOK_SH and b"\r\n" not in text
    assert repo.git("config", "--local", "gc.packRefs") == "false" and repo.git("config", "--local", "maintenance.pack-refs.enabled") == "false"
    assert guard(repo, "arm").rc == 0  # idempotent


def test_arm_dry_run_and_console_gate(repo, guard):
    r = guard(repo, "arm", "--dry-run")
    assert r.rc == 0 and "would write" in r.out and not hook_path(repo).exists() and not (common(repo) / "magos" / "ARMED").exists()
    r = run(["--repo", str(repo.path), "--lang", "en", "arm"])  # no console: refused, nothing written
    assert r.rc == 17 and "real terminal" in r.err and not hook_path(repo).exists()
    assert guard(repo, "arm").rc == 0
    r = run(["--repo", str(repo.path), "--lang", "en", "disarm"])
    assert r.rc == 17 and hook_path(repo).exists()
    assert guard(repo, "disarm", "--dry-run").rc == 0 and hook_path(repo).exists()


def test_arm_refusals(repo, guard):
    repo.git("config", "--local", "core.hooksPath", "elsewhere")
    r = guard(repo, "arm")
    assert r.rc == 3 and "core.hooksPath" in r.err and not hook_path(repo).exists()
    repo.git("config", "--local", "--unset", "core.hooksPath")
    hook_path(repo).parent.mkdir(exist_ok=True)
    (hook_path(repo).parent / "reference-transaction.magos-prev").write_text("#!/bin/sh\n", encoding="utf-8")
    r = guard(repo, "arm")
    assert r.rc == 3 and ".magos-prev already exists" in r.err
    (hook_path(repo).parent / "reference-transaction.magos-prev").unlink()
    repo.git("config", "extensions.worktreeConfig", "true")
    wt = repo.worktree("wt-hooks", "agent/hooks")
    repo.git("config", "--worktree", "core.hooksPath", str(repo.path.parent / "other-hooks"), cwd=wt)
    r = guard(repo, "arm")
    assert r.rc == 3 and "different hook directories" in r.err


def test_disarm_restores_a_foreign_hook(repo, guard):
    hook_path(repo).parent.mkdir(exist_ok=True)
    marker = repo.path.parent / "foreign.log"
    hook_path(repo).write_bytes(('#!/bin/sh\necho "$1" >> "%s"\ncat >/dev/null\n' % str(marker).replace("\\", "/")).encode("utf-8"))
    os.chmod(hook_path(repo), 0o755)  # an active hook: git runs only executable hooks
    assert guard(repo, "arm").rc == 0
    assert (hook_path(repo).parent / "reference-transaction.magos-prev").is_file()
    repo.git("tag", "t1")  # a non-creation transaction: the foreign hook still runs (prepared, committed)
    seen = marker.read_text(encoding="utf-8").split()
    assert "prepared" in seen and "committed" in seen
    r = guard(repo, "disarm", "--dry-run")
    assert r.rc == 0 and "would remove" in r.out and hook_path(repo).read_text(encoding="utf-8").count("MAGOS lane guard")
    assert guard(repo, "disarm").rc == 0
    assert "MAGOS lane guard" not in hook_path(repo).read_text(encoding="utf-8")  # the foreign hook is back
    assert not (hook_path(repo).parent / "reference-transaction.magos-prev").exists() and not (common(repo) / "magos" / "ARMED").exists()
    assert guard(repo, "disarm").rc == 0  # nothing left to do


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes; MSYS sh treats a file with #! as executable")
def test_a_non_executable_foreign_hook_is_not_run(repo, guard):
    hook_path(repo).parent.mkdir(exist_ok=True)
    marker = repo.path.parent / "inactive.log"
    hook_path(repo).write_bytes(('#!/bin/sh\necho "$1" >> "%s"\ncat >/dev/null\n' % str(marker)).encode("utf-8"))
    os.chmod(hook_path(repo), 0o644)  # git would not run it
    assert guard(repo, "arm").rc == 0
    prev = hook_path(repo).parent / "reference-transaction.magos-prev"
    repo.git("tag", "t2")  # the transaction succeeds and the inactive hook stays inactive
    assert not marker.exists()
    os.chmod(prev, 0o755)
    repo.git("tag", "t3")
    seen = marker.read_text(encoding="utf-8").split()
    assert "prepared" in seen and "committed" in seen


# ---- vetoes ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("args", [
    ("branch", "x1"), ("switch", "-c", "x2"), ("checkout", "-b", "x3"), ("update-ref", "refs/heads/x4", "HEAD"), ("fetch", ".", "main:x5"),
    ("checkout", "--orphan", "x6"), ("switch", "--orphan", "x7"), ("branch", "x8", "main"),
])
def test_creations_without_a_claim_are_vetoed(armed, args):
    before = armed.git("for-each-ref", "refs/heads")
    msg = vetoed(armed, *args)
    assert "has no registered file manifest" in msg and "plan --branch" in msg
    assert armed.git("for-each-ref", "refs/heads") == before and armed.git("symbolic-ref", "HEAD") == "refs/heads/main"


def test_worktree_add_with_a_new_branch_leaves_nothing_behind(armed):
    target = armed.path.parent / "wt-veto"
    vetoed(armed, "worktree", "add", "-b", "agent/veto", str(target))
    assert not target.exists() and "agent/veto" not in armed.git("branch", "--list")
    assert armed.git("worktree", "list", "--porcelain").count("worktree ") == 1
    admin = common(armed) / "worktrees"
    assert not admin.exists() or not list(admin.iterdir())


def test_a_claim_lets_the_creation_through(armed, guard):
    assert guard(armed, "plan", "--branch", "agent/ok", "--paths", "docs/").rc == 0
    wt = armed.path.parent / "wt-ok"
    assert repo_git_raw(armed, "worktree", "add", "-b", "agent/ok", str(wt)).returncode == 0 and wt.exists()
    assert guard(armed, "plan", "--branch", "feature/two", "--paths", "src/b.py").rc == 0
    assert repo_git_raw(armed, "branch", "feature/two").returncode == 0
    assert guard(armed, "plan", "--branch", "unborn-one", "--paths", "web/").rc == 0
    assert repo_git_raw(armed, "checkout", "--orphan", "unborn-one").returncode == 0


def test_the_backstop_reads_refs_heads_in_any_case(armed, guard):
    before = armed.git("for-each-ref")
    msg = vetoed(armed, "update-ref", "refs/HEADS/y1", "HEAD")  # the case-insensitive file systems of Windows and macOS store it as the branch y1
    assert "'y1' has no registered file manifest" in msg and "plan --branch y1" in msg
    assert armed.git("for-each-ref") == before
    assert guard(armed, "plan", "--branch", "y2", "--paths", "docs/").rc == 0
    assert repo_git_raw(armed, "update-ref", "refs/HEADS/y2", "HEAD").returncode == 0
    arm = "[Hh][Ee][Aa][Dd][Ss]"  # both case arms of the hook: a ref, and the ref HEAD points at
    assert "\n  refs/%s/*) " % arm in G.HOOK_SH and "b=${ref#refs/%s/};" % arm in G.HOOK_SH
    assert "case $new in ref:refs/%s/*) b=${new#ref:refs/%s/}" % (arm, arm) in G.HOOK_SH
    assert "refs/heads/*)" not in G.HOOK_SH


def test_everything_else_passes(armed):
    armed.write("docs/d.md", "edit\n")
    for args in (("add", "-A"), ("commit", "-q", "-m", "edit"), ("tag", "v1"), ("fetch", "--all"), ("gc", "-q"),
                 ("pack-refs", "--all"), ("branch", "--list"), ("switch", "main"), ("worktree", "add", "--detach", str(armed.path.parent / "wt-det")),
                 ("worktree", "list"), ("reflog", "expire", "--all")):
        p = repo_git_raw(armed, *args)
        assert p.returncode == 0, (args, p.stderr)
    armed.write("docs/d.md", "again\n")
    assert repo_git_raw(armed, "stash", "push", "-u", "-m", "s").returncode == 0 and repo_git_raw(armed, "stash", "pop").returncode == 0
    armed.git("update-ref", "refs/magos-test/x", "HEAD")  # refs outside refs/heads are not branches


def test_existing_branch_checkout_into_a_worktree_passes(repo, guard):
    repo.git("branch", "pre-existing")
    assert guard(repo, "arm").rc == 0
    p = repo_git_raw(repo, "worktree", "add", str(repo.path.parent / "wt-pre"), "pre-existing")
    assert p.returncode == 0, p.stderr


def test_rebase_and_pull_do_not_trip_the_hook(repo, guard):
    repo.branch_with("feat", "src/a.py")
    assert guard(repo, "arm").rc == 0
    assert repo_git_raw(repo, "switch", "feat").returncode == 0
    repo.commit("docs/new.md", "n\n")
    assert repo_git_raw(repo, "rebase", "main").returncode == 0
    assert repo_git_raw(repo, "switch", "main").returncode == 0
    assert repo_git_raw(repo, "merge", "-q", "feat").returncode == 0


def test_hook_works_from_a_linked_worktree_and_subdirectory(armed, guard):
    wt = armed.path.parent / "wt-link"
    assert guard(armed, "plan", "--branch", "agent/link", "--paths", "docs/").rc == 0
    assert repo_git_raw(armed, "worktree", "add", "-b", "agent/link", str(wt)).returncode == 0
    vetoed(armed, "branch", "from-linked", cwd=wt)
    sub = wt / "src"
    vetoed(armed, "branch", "from-sub", cwd=sub)


def test_existing_lanes_are_never_stopped_by_the_backstop(repo, guard):
    """A lane whose claim was released (or that existed before arming) keeps committing: only creations are vetoed."""
    repo.branch_with("agent/old", "src/a.py")
    assert guard(repo, "arm").rc == 0
    wt = repo.path.parent / "wt-old"
    assert repo_git_raw(repo, "worktree", "add", str(wt), "agent/old").returncode == 0
    repo.write("docs/x.md", "x\n", base=wt)
    repo_git_raw(repo, "add", "-A", cwd=wt)
    assert repo_git_raw(repo, "commit", "-q", "-m", "advance", cwd=wt).returncode == 0
    # A rename writes the new name outside any reference transaction, so the backstop never sees it (lane-split §12):
    # the lane keeps working under its new name, and only the host hook judges a typed `git branch -m`.
    assert repo_git_raw(repo, "branch", "-m", "agent/old", "agent/renamed").returncode == 0
    assert repo.git("branch", "--list", "agent/renamed") and not repo.git("branch", "--list", "agent/old")


def test_hook_messages_follow_the_armed_language(repo, guard, monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: True)
    assert run(["--repo", str(repo.path), "--lang", "zh", "arm"]).rc == 0
    p = repo_git_raw(repo, "branch", "zhbranch")
    assert p.returncode != 0 and "拒绝" in p.stderr.decode("utf-8", "replace")


# ---- doctor --------------------------------------------------------------------------------------------------------
def test_doctor(repo, guard):
    r = guard(repo, "doctor")
    assert r.rc == 0 and "mode auto" in r.out and "not installed" in r.out and "claims without a branch or planned worktree: none" in r.out
    guard(repo, "plan", "--branch", "agent/orphan", "--paths", "docs/")
    assert "agent/orphan" in guard(repo, "doctor").out
    assert guard(repo, "arm").rc == 0
    r = guard(repo, "doctor")
    assert r.rc == 0 and "mode armed" in r.out and "self-test ok" in r.out and "branch __magos_selftest" not in repo.git("branch", "--list")
    hook_path(repo).write_bytes((hook_path(repo).read_text(encoding="utf-8") + "\n# edited\n").encode("utf-8"))
    r = guard(repo, "doctor")
    assert r.rc == 1 and "different from this version" in r.out
    hook_path(repo).unlink()
    r = guard(repo, "doctor")
    assert r.rc == 1 and "not installed" in r.out
    assert run(["--repo", str(repo.path.parent), "doctor"]).rc == 0  # not a repository: inert


def test_doctor_reports_a_broken_backstop(repo, guard):
    assert guard(repo, "arm").rc == 0
    # a hook that vetoes nothing leaves the self-test branch behind: doctor must notice and clean it up
    text = G.HOOK_SH.replace("exit 1; }", "exit 0; }", 1)
    hook_path(repo).write_bytes(text.encode("utf-8"))  # LF as is
    monkey = G.HOOK_SH
    G.HOOK_SH = text
    try:
        r = guard(repo, "doctor")
    finally:
        G.HOOK_SH = monkey
    assert r.rc == 1 and "self-test FAILED" in r.out and "__magos_selftest" not in repo.git("branch", "--list")


def test_doctor_flags_unreadable_claims_and_old_python(repo, guard, monkeypatch):
    g = G.open_repo(str(repo.path))
    p = Path(G.claim_path(g, "broken"))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("garbage", encoding="utf-8")
    r = guard(repo, "doctor")
    assert r.rc == 1 and "unreadable: 1" in r.out
    monkeypatch.setattr(G.sys, "version_info", (3, 8, 0))
    assert "TOO OLD" in guard(repo, "doctor").out


# ---- install ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host,suffix,needle", [("claude", "json", "EnterWorktree"), ("codex", "json", "commandWindows"), ("hermes", "yaml", "fail_closed")])
def test_install_copies_the_guard_and_prints_the_snippet(repo, guard, tmp_path, host, suffix, needle):
    home = tmp_path / "magos-home"
    r = guard(repo, "install", "--host", host, "--home", str(home))
    assert r.rc == 0 and needle in r.out and "never edits it" in r.out
    for rel in ("scripts/magos_guard.py", "hooks/run-guard.cmd"):  # the canonical copy keeps the layout and the exact bytes
        assert (home / "guard" / rel).read_bytes() == (ROOT / rel).read_bytes(), rel
    saved = (home / "guard" / "generated" / ("%s.%s" % (host, suffix))).read_text(encoding="utf-8")
    assert needle in saved and str(home).replace("\\", "/") in saved
    if suffix == "json":
        json.loads(saved)


def test_install_dry_run_and_default_home(repo, guard, tmp_path):
    home = tmp_path / "dry"
    r = guard(repo, "install", "--host", "codex", "--home", str(home), "--dry-run")
    assert r.rc == 0 and "would copy" in r.out and not home.exists()
    r = guard(repo, "install", "--host", "hermes", "--dry-run")  # MAGOS_HOME from the isolated environment
    assert ".magos" in r.out
    inplace = Path(G.__file__).parent.parent  # installing from the canonical copy onto itself must not truncate it
    home2 = tmp_path / "again"
    assert guard(repo, "install", "--host", "claude", "--home", str(home2)).rc == 0
    assert guard(repo, "install", "--host", "claude", "--home", str(home2)).rc == 0
    assert inplace.exists()
