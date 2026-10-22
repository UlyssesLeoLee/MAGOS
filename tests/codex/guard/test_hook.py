"""Host hook entry: payloads of Claude Code, Codex and Hermes, engagement modes, revalidation, tamper protection and failure handling."""
from __future__ import annotations

import json

import pytest

from conftest import G, payload, run


def hook(repo, tool="Bash", command=None, host="claude", env=None, **tool_input):
    body = payload(tool, command, repo.path if hasattr(repo, "path") else repo, **tool_input)
    r = run(["--lang", "en", "hook", host, "pre-tool"], stdin=json.dumps(body).encode("utf-8"))
    assert r.rc == 0, r
    return r


def denied(r):
    if r.out.strip() == "{}":
        return None
    obj = json.loads(r.out)
    assert set(obj) == {"decision", "reason", "hookSpecificOutput"} and obj["decision"] == "block"
    assert obj["hookSpecificOutput"] == {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": obj["reason"]}
    assert r.out.isascii() and r.err == ""
    return obj["reason"]


def plan(guard, repo, branch, *paths, worktree=None):
    args = ["plan", "--branch", branch, "--paths", *paths] + (["--worktree", str(worktree)] if worktree else [])
    r = guard(repo, *args)
    assert r.rc == 0, r.out
    return r


# ---- allow ---------------------------------------------------------------------------------------------------------
def test_plain_commands_and_single_lane_repositories_are_unaffected(repo):
    for cmd in ("git status", "git log --oneline", "echo hi", "ls", "git checkout main", "git commit -m x"):
        assert denied(hook(repo, command=cmd)) is None, cmd
    assert denied(hook(repo, command="git switch -c feature/one")) is None  # AUTO: nothing else exists, branch-only creation is not parallel work
    assert denied(hook(repo, "Read", file_path="x")) is None
    assert run(["hook", "claude", "pre-tool"], stdin=json.dumps(payload("Bash", "git worktree add ../w -b x", cwd="C:/definitely/not/a/repo")).encode()).out.strip() == "{}"


# ---- named worktree creation (always guarded in AUTO) ---------------------------------------------------------------
def test_named_worktree_needs_a_manifest(repo, guard):
    reason = denied(hook(repo, command="git worktree add ../wt-new -b agent/new"))
    assert "agent/new" in reason and "plan --branch agent/new" in reason and "nothing was created" in reason
    plan(guard, repo, "agent/new", "docs/", worktree=repo.path.parent / "wt-new")
    assert denied(hook(repo, command="git worktree add ../wt-new -b agent/new")) is None
    mismatch = denied(hook(repo, command="git worktree add ../elsewhere -b agent/new"))
    assert "registered worktree path" in mismatch and "elsewhere" in mismatch
    assert denied(hook(repo, command="git worktree add ../wt-new -b agent/other")) is not None  # a different branch has no claim


def test_revalidation_denies_when_a_sibling_dirties_a_planned_file(repo, guard):
    plan(guard, repo, "agent/late", "src/a.py")
    assert denied(hook(repo, command="git worktree add ../w -b agent/late")) is None
    wt = repo.worktree("wt-sib", "agent/sib")
    repo.write("src/a.py", "sibling edit\n", base=wt)
    reason = denied(hook(repo, command="git worktree add ../w -b agent/late"))
    assert "agent/sib" in reason and "src/a.py" in reason and "uncommitted" in reason


def test_committed_evidence_is_read_from_the_top_under_diff_relative(repo, guard):
    plan(guard, repo, "agent/late", "src/a.py")
    repo.branch_with("agent/x", "src/a.py")
    repo.git("config", "diff.relative", "true")  # git diff lists only the changes below the directory it starts in, relative to it
    create = 'git worktree add "%s" -b agent/late' % (repo.path.parent / "w").as_posix()
    for where in (repo.path, repo.path / "src"):
        r = guard(where, "--json", "check", "--branch", "agent/late", "--paths", "src/a.py")
        v = json.loads(r.out)
        assert r.rc == 10 and [(c["branch"], [(e["kind"], e["files"]) for e in c["evidence"]]) for c in v["conflicts"]] == [("agent/x", [("committed", ["src/a.py"])])], (where, v)
        reason = denied(hook(where, command=create))
        assert reason and "agent/x" in reason and "src/a.py" in reason, (where, reason)


def test_override_recorded_in_the_claim_survives_revalidation(repo, guard, monkeypatch):
    repo.branch_with("agent/x", "src/a.py")
    fp = json.loads(guard(repo, "--json", "plan", "--branch", "agent/ov", "--paths", "src/a.py").out)["fingerprint"]
    monkeypatch.setattr(G, "user_console", lambda: True)
    assert run(["--repo", str(repo.path), "override", "--fingerprint", fp, "--reason", "ok"], stdin=(fp + "\n").encode()).rc == 0
    assert guard(repo, "plan", "--branch", "agent/ov", "--paths", "src/a.py").rc == 0
    assert denied(hook(repo, command="git worktree add ../w -b agent/ov")) is None  # the claim carries the override fingerprint
    repo.commit("src/b.py", "x\n", cwd=repo.path)  # the target moves: fingerprint changes, the override no longer applies
    repo.git("branch", "-f", "agent/x", "agent/x")
    assert "agent/x" in (denied(hook(repo, command="git worktree add ../w -b agent/ov")) or "")


def test_unreadable_claim_denies(repo, guard):
    plan(guard, repo, "agent/bad", "docs/")
    g = G.open_repo(str(repo.path))
    path = G.claim_path(g, "agent/bad")
    text = open(path, encoding="utf-8").read().replace("entry=docs/", "entry=/absolute")
    open(path, "w", encoding="utf-8").write(text)
    assert "CLAIM_UNPARSEABLE" in denied(hook(repo, command="git worktree add ../w -b agent/bad"))


# ---- branch-only creations (AUTO engages only when another lane exists) ---------------------------------------------
def test_branch_only_creation_engages_when_another_lane_exists(repo, guard):
    assert denied(hook(repo, command="git switch -c feature/x")) is None
    repo.branch_with("agent/other", "src/a.py")
    assert "feature/x" in denied(hook(repo, command="git switch -c feature/x"))
    assert "feature/y" in denied(hook(repo, command="git checkout -b feature/y"))
    assert denied(hook(repo, command="git checkout main")) is None


def test_open_claim_alone_makes_lanes_parallel(repo, guard):
    plan(guard, repo, "agent/only", "docs/")
    assert "feature/z" in denied(hook(repo, command="git branch feature/z"))


def test_another_dirty_worktree_is_parallel_but_the_own_dirt_is_not(repo, guard):
    repo.write("src/a.py", "own dirt\n")  # the creating worktree's own uncommitted work does not make it parallel
    assert denied(hook(repo, command="git switch -c feature/own")) is None
    wt = repo.worktree("wt-dirty", "agent/dirty")
    repo.write("web/x.js", "n\n", base=wt)
    assert denied(hook(repo, command="git switch -c feature/own2")) is not None


def test_existing_branch_names_are_not_creations(repo, guard):
    repo.branch_with("agent/other", "src/a.py")
    repo.git("branch", "existing")
    for cmd in ("git switch existing", "git checkout existing", "git switch -C existing", "git branch -f existing main", "git worktree add ../w existing"):
        assert denied(hook(repo, command=cmd)) is None, cmd


def test_dwim_creations_need_a_remote_only_name(repo, guard):
    repo.branch_with("agent/other", "src/a.py")
    sha = repo.git("rev-parse", "main")
    repo.git("update-ref", "refs/remotes/origin/feature-r", sha)
    assert "feature-r" in denied(hook(repo, command="git switch feature-r"))
    assert "feature-r" in denied(hook(repo, command="git checkout feature-r"))
    assert "feature-r" in denied(hook(repo, command="git worktree add ../w feature-r"))
    assert denied(hook(repo, command="git switch no-such-branch")) is None  # neither local nor remote: git will refuse it
    assert denied(hook(repo, command="git checkout README.md")) is None


def test_dynamic_names(repo, guard):
    repo.branch_with("agent/other", "src/a.py")
    assert "dynamic" in denied(hook(repo, command="git switch -c $NAME"))  # once another lane exists, a creation must name its branch literally
    assert "dynamic" in denied(hook(repo, command="git worktree add ../w -b $NAME"))
    assert "dynamic" in denied(hook(repo, command="cd $X && git worktree add ../w -b lane"))


# ---- unplannable tools -----------------------------------------------------------------------------------------------
def test_auto_named_worktrees_cannot_be_planned(repo, guard):
    assert denied(hook(repo, "Agent", prompt="x", isolation="worktree")) is None  # AUTO, nothing else exists
    repo.branch_with("agent/other", "src/a.py")
    for tool in ("Agent", "Task", "Workflow"):
        reason = denied(hook(repo, tool, prompt="x", isolation="worktree"))
        assert "names the branch or worktree itself" in reason and tool in reason
    assert "gh pr checkout" in denied(hook(repo, command="gh pr checkout 12"))
    assert denied(hook(repo, "EnterWorktree")) is not None
    assert denied(hook(repo, "mcp__ccd_session__start_session", use_worktree=True)) is not None


def test_enter_worktree_and_session_tools_with_names(repo, guard):
    assert "worktree-feat" in denied(hook(repo, "EnterWorktree", name="feat"))
    plan(guard, repo, "worktree-feat", "docs/")
    assert denied(hook(repo, "EnterWorktree", name="feat")) is None
    assert denied(hook(repo, "EnterWorktree", path="/existing/worktree")) is None
    assert "sess-1" in denied(hook(repo, "mcp__ccd_session__start_session", branch_name="sess-1", use_worktree=True))
    plan(guard, repo, "sess-1", "src/b.py")
    assert denied(hook(repo, "mcp__ccd_session__start_session", branch_name="sess-1", use_worktree=True)) is None


# ---- host payload shapes ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host,tool,key", [("claude", "Bash", "command"), ("claude", "PowerShell", "command"), ("codex", "Bash", "command"), ("hermes", "terminal", "command")])
def test_every_host_gets_the_same_deny_object(repo, host, tool, key):
    r = hook(repo, tool, "git worktree add ../w -b agent/new", host=host)
    assert "agent/new" in denied(r)


def test_codex_command_list_and_hermes_workdir(repo, guard):
    body = {"tool_name": "Bash", "tool_input": {"command": ["git", "worktree", "add", "../w", "-b", "agent/listed"]}, "cwd": str(repo.path)}
    assert "agent/listed" in denied(run(["--lang", "en", "hook", "codex", "pre-tool"], stdin=json.dumps(body).encode()))
    body = {"tool_name": "terminal", "tool_input": {"command": "git worktree add ../w -b agent/herm", "workdir": str(repo.path)}, "cwd": "C:/elsewhere"}
    assert "agent/herm" in denied(run(["--lang", "en", "hook", "hermes", "pre-tool"], stdin=json.dumps(body).encode()))


def test_chinese_is_the_default_language(repo):
    body = payload("Bash", "git worktree add ../w -b agent/zh", repo.path)
    out = run(["hook", "claude", "pre-tool"], stdin=json.dumps(body).encode()).out
    obj = json.loads(out)
    assert out.isascii() and "\\u62d2\\u7edd" in out  # ASCII-escaped on the wire
    assert "拒绝创建" in obj["reason"]  # and Chinese once decoded
    assert "agent/zh" in obj["reason"] and "MAGOS" in obj["reason"] and "DENIES" not in obj["reason"]


# ---- modes -----------------------------------------------------------------------------------------------------------
def test_off_switches(repo, monkeypatch):
    assert denied(hook(repo, command="git worktree add ../w -b agent/x")) is not None
    repo.git("config", "--local", "magos.guard", "off")
    assert denied(hook(repo, command="git worktree add ../w -b agent/x")) is None
    repo.git("config", "--local", "--unset", "magos.guard")
    monkeypatch.setenv("MAGOS_GUARD", "off")
    assert denied(hook(repo, command="git worktree add ../w -b agent/x")) is None


def test_armed_mode_guards_branch_only_and_denies_unknowns(repo, guard):
    repo.git("branch", "-m", "main", "master")  # two target candidates and no pinned target: the target is uncertain
    repo.git("branch", "develop")
    assert guard(repo, "arm").rc == 0
    assert "feature/a" in denied(hook(repo, command="git switch -c feature/a"))  # nothing else exists, but the repository is armed
    assert "dynamic" in denied(hook(repo, command="git switch -c $X"))
    assert denied(hook(repo, command="git worktree add ../w -b agent/u")) is not None
    assert guard(repo, "plan", "--branch", "agent/u", "--paths", "docs/").rc == 11  # unknown is not safe: no claim, so nothing can be created


# ---- tamper protection -------------------------------------------------------------------------------------------------
def test_user_only_commands_are_denied_everywhere(repo, tmp_path):
    for cmd in ("py -3 magos_guard.py override --fingerprint abc --reason x", "python3 scripts/magos_guard.py arm", "bash -c 'python3 magos_guard.py disarm'", "git config magos.guard off"):
        assert "user" in denied(hook(repo, command=cmd)).lower(), cmd
    r = run(["hook", "claude", "pre-tool"], stdin=json.dumps(payload("Bash", "python magos_guard.py install --host codex", cwd=tmp_path)).encode())
    assert denied(r) is not None  # even outside a repository


def test_state_edits_are_denied_once_claims_or_the_hook_exist(repo, guard):
    assert denied(hook(repo, command="git config core.hooksPath /tmp/hooks")) is None  # ordinary use in a repository without any lane
    plan(guard, repo, "agent/t", "docs/")
    for cmd in ("git config core.hooksPath /tmp/hooks", "GIT_CONFIG_COUNT=1 git branch x", "rm -rf .git/magos", "echo x > .git/hooks/reference-transaction"):
        assert "guard's own" in denied(hook(repo, command=cmd)), cmd
    for cmd in ("git config --get magos.guard", "git for-each-ref", "cat .git/hooks/pre-commit.sample"):
        assert denied(hook(repo, command=cmd)) is None, cmd


# ---- aliases ---------------------------------------------------------------------------------------------------------
def test_git_aliases_are_resolved_from_the_repository_config(repo, guard):
    repo.git("config", "alias.nb", "switch -c")
    repo.git("config", "alias.mk", "!git branch")
    repo.branch_with("agent/other", "src/a.py")
    assert "viaalias" in denied(hook(repo, command="git nb viaalias"))
    assert "viashell" in denied(hook(repo, command="git mk viashell"))
    assert denied(hook(repo, command="git unknowncmd")) is None
    assert G.load_aliases(G.open_repo(str(repo.path))) == {"nb": "switch -c", "mk": "!git branch"}


# ---- failure handling ------------------------------------------------------------------------------------------------
def test_unparseable_payloads(repo):
    assert "unparseable" in denied(run(["hook", "claude", "pre-tool"], stdin=b"{not json git worktree add"))
    assert run(["hook", "claude", "pre-tool"], stdin=b"{not json").out.strip() == "{}"
    assert run(["hook", "claude", "pre-tool"], stdin=b"[1,2]").out.strip() == "{}"
    assert run(["hook", "claude", "pre-tool"], stdin=b"").out.strip() == "{}"
    body = ("\ufeff" + json.dumps(payload("Bash", "git worktree add ../w -b agent/bom", repo.path))).replace("\n", "\r\n").encode("utf-8")  # PowerShell pipes BOM + CRLF
    assert "agent/bom" in denied(run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=body))


def test_internal_errors_fail_closed_only_for_lane_creation(repo, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaput")
    monkeypatch.setattr(G, "decide", boom)
    reason = denied(hook(repo, command="git worktree add ../w -b agent/crash"))
    assert "guard error" in reason and "kaput" in reason and "doctor" in reason
    r = hook(repo, command="echo hello")
    assert r.out.strip() == "{}" and "kaput" in r.err  # unrelated calls pass with a warning
    monkeypatch.setattr(G, "extract", boom)
    assert "guard error" in denied(hook(repo, command="git worktree add ../w -b agent/crash2"))


def test_gather_failure_in_auto_allows_branch_only(repo, guard, monkeypatch):
    repo.branch_with("agent/other", "src/a.py")
    monkeypatch.setattr(G, "gather", lambda *a, **k: (_ for _ in ()).throw(G.GitFail("GIT_FAILED", "boom")))
    assert denied(hook(repo, command="git switch -c feature/q")) is None  # not engaged: AUTO cannot tell, so it stays out of the way
    assert denied(hook(repo, command="git worktree add ../w -b agent/q")) is not None  # a named worktree always needs its claim


# ---- review findings -------------------------------------------------------------------------------------------------
def test_git_bash_spelled_targets_are_judged_not_waved_through(repo, guard, tmp_path, monkeypatch):
    other = tmp_path / "unrelated"
    other.mkdir()
    plan(guard, repo, "agent/planned", "docs/")
    spelled = "/" + str(repo.path).replace("\\", "/").replace(":", "", 1)  # /C/Users/... as Git Bash prints it
    body = payload("Bash", "cd %s && git worktree add ../w -b agent/other" % spelled, other)
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(body).encode())
    assert "agent/other" in (denied(r) or "")
    body = payload("Bash", "cd /does/not/exist && git worktree add ../w -b agent/other2", repo.path)  # a form we cannot map to a directory
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(body).encode())
    assert denied(r) is not None  # an unresolvable target falls back to the session repository, and the dynamic target is refused
    body = payload("Bash", "cd %s && git init x && cd x && git switch -c main2" % str(other).replace("\\", "/"), repo.path)
    assert denied(run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(body).encode())) is None  # a real directory that is not a repository


def test_bundled_flags_and_session_tools(repo, guard):
    assert "agent/x" in denied(hook(repo, command="git worktree add -fb agent/x ../w main"))
    assert "sess" in denied(hook(repo, "mcp__ccd_session__start_session", branch_name="sess"))  # use_worktree omitted: the session still gets a worktree
    assert denied(hook(repo, "mcp__ccd_session__start_session", branch_name="sess", use_worktree=False)) is None
    repo.branch_with("agent/other", "src/a.py")
    assert "names the branch or worktree itself" in denied(hook(repo, "mcp__ccd_session__hand_off_to_session", title="t"))


def test_ordinary_work_in_an_existing_lane_is_never_denied(repo, guard):
    plan(guard, repo, "agent/planned", "docs/y.md")
    wt = repo.worktree("wt-existing", "agent/existing")
    for cmd in ('git commit -m "chore: husky sets core.hooksPath for the repo"', 'grep -rn "core.hooksPath" .', "git config --get core.hooksPath", "git merge main", "git rebase main",
                "cat .git/HEAD > /dev/null", "git push origin agent/existing"):
        body = payload("Bash", cmd, wt)
        assert denied(run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(body).encode())) is None, cmd
    for tool, ti in (("Edit", {"file_path": str(wt / "src" / "a.py")}), ("Write", {"file_path": str(wt / "new.py")})):
        body = payload(tool, None, wt, **ti)
        assert denied(run(["hook", "claude", "pre-tool"], stdin=json.dumps(body).encode())) is None
