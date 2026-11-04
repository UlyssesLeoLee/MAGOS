"""Branch protection (TC-728 to TC-779): the record <git-common-dir>/magos/protected.json and its format gate, the user-only `protect` with
its three approval routes, the agent subcommand `protect-show`, the hook rule that refuses an agent's write to a protected branch (the refused
operations, the current branch, the unknown targets that fail closed), the tamper filter of a repository whose only guard state is a
protection, doctor, the texts and the exit codes."""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import G, SCRIPT, Result, crashed, payload, retried, run, time_budget
from test_approval import P, PY, QS, answer, approvals, audit_lines, bare_py, common, needs_sh, new_repo, run_sh, sha, token_of  # noqa: F401
from test_hermes_approval import H, asked, elsewhere, hermes_env  # noqa: F401
from test_hook import denied
from test_mcp_approval import ACCEPT, CLIENT, bare_exe, hosts  # noqa: F401
from test_gitplan_sets import custom_spec, lane, sp_args, write_spec

WIN = sys.platform == "win32"


# ---- helpers ---------------------------------------------------------------------------------------------------------------------------------
def gp(where, *args, lang="en"):
    """The guard in process on the repository `where` (a Repo or a path)."""
    return run(["--repo", str(getattr(where, "path", where)), "--lang", lang] + list(args))


def jgp(where, *args):
    """-> (exit code, the one JSON object) of `--json <args>`."""
    r = gp(where, "--json", *args)
    try:
        v = json.loads(r.out)
    except ValueError:
        raise AssertionError("no JSON (exit %s): %r %r" % (r.rc, r.out, r.err)) from None
    assert v["exit_code"] == r.rc and G.EXIT[v["code"]] == r.rc and r.err == "", (r, v)
    return r.rc, v


@pytest.fixture
def console(monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: True)


def protect(repo, *names):
    for n in names:
        r = gp(repo, "protect", "--branch", n)
        assert r.rc == 0, r


def store_of(repo):
    return common(repo) / "magos"


def rec_path(repo):
    return store_of(repo) / "protected.json"


def record_of(repo):
    return json.loads(rec_path(repo).read_text(encoding="utf-8"))


def repo_text(repo):
    return G._shown(G.repo_dir(G.open_repo(str(getattr(repo, "path", repo)))))


def hit(repo, op, b="main", lang="en"):
    return "BRANCH_PROTECTED", G.T(lang, "branch_protected", op=op, b=b, repo=repo_text(repo))


def decide(cwd, cmd, tool="Bash", host="claude", lang="en", **ti):
    return G.decide(payload(tool, cmd, cwd, **ti), lang, host)


def bp(v):
    """The text of a BRANCH_PROTECTED verdict, else None."""
    if v and not isinstance(v, (G.Approval, G.HermesApproval)) and v[0] == "BRANCH_PROTECTED":
        return v[1]
    return None


@contextlib.contextmanager
def lifted(*repos):
    """The repositories without their protection record for the duration (the verdict a repository without protection gives)."""
    moved = [(rec_path(r), rec_path(r).with_name("protected.json.away")) for r in repos if rec_path(r).exists()]
    for a, b in moved:
        os.replace(str(a), str(b))
    try:
        yield
    finally:
        for a, b in moved:
            os.replace(str(b), str(a))


def same_as_unprotected(cwd, cmd, *repos, **kw):
    """No BRANCH_PROTECTED verdict: the verdict equals that of the same payload without the records of `repos`."""
    v = decide(cwd, cmd, **kw)
    with lifted(*repos):
        w = decide(cwd, cmd, **kw)
    assert bp(v) is None and v == w, (cmd, v, w)
    return v


def unknown_text(v):
    t = bp(v)
    assert t is not None and "cannot be read" in t and "holds protected branches (" in t, v
    return t


def hook_proc(cwd, cmd, tool="Bash", host="claude", lang="en", extra=(), body=None):
    """The hook as its own process, as a host starts it."""
    b = body if body is not None else payload(tool, cmd, cwd)

    def once():
        p = subprocess.run([sys.executable, "-B", str(SCRIPT), "--lang", lang, "hook", host, "pre-tool"] + list(extra), input=json.dumps(b).encode("utf-8"),
                           capture_output=True, timeout=120, env=os.environ.copy())
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
    r = retried(once, lambda r: crashed(r.out + r.err, r.rc))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


class World:
    """R: main checked out in its main worktree and protected, topic checked out in the linked worktree W; U: a repository without a record."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.R = new_repo(tmp_path / "R")
        self.R.git("branch", "topic")
        self.W = tmp_path / "W"
        self.R.git("worktree", "add", "-q", str(self.W), "topic")
        self.U = new_repo(tmp_path / "U")


@pytest.fixture
def world(tmp_path, console):
    w = World(tmp_path)
    protect(w.R, "main")
    return w


# ---- protect and its record (TC-728 to TC-743) -------------------------------------------------------------------------------------------
def test_protect_sets_a_record_and_audits(tmp_path, console):
    R = new_repo(tmp_path / "R")
    R.git("branch", "topic")
    r = gp(R, "protect", "--branch", "main")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_ok", b="main", repo=repo_text(R)) and r.err == "", r
    data = rec_path(R).read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r" not in data
    rec = json.loads(data.decode("utf-8"))
    assert list(rec) == ["v", "branches"] and rec["v"] == 1 and len(rec["branches"]) == 1
    e = rec["branches"][0]
    assert list(e) == ["branch", "at", "by", "via", "reason"] and e["branch"] == "main" and e["via"] == "terminal" and e["reason"] == ""
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", e["at"]) and e["by"] == G.who(G.open_repo(str(R.path)))
    lines = [x for x in audit_lines(store_of(R)) if x["op"] == "protect"]
    assert len(lines) == 1
    a = lines[0]
    assert (a["action"], a["branch"], a["stored"], a["changed"], a["via"], a["reason"]) == ("set", "main", "main", True, "terminal", "")
    assert list(a)[:2] == ["ts", "by"]


def test_protect_is_idempotent_and_folds_case(world):
    R, before = world.R, rec_path(world.R).read_bytes()
    for name in ("main", "MAIN"):
        r = gp(R, "protect", "--branch", name)
        assert r.rc == 0 and r.out.strip() == G.T("en", "protect_same", b=name, repo=repo_text(R), stored="main"), r
    rc, v = jgp(R, "protect", "--branch", "Main")
    assert rc == 0 and v["changed"] is False and v["stored"] == "main" and v["protected"] == ["main"] and v["message"] == G.T(
        "en", "protect_same", b="Main", repo=repo_text(R), stored="main")
    assert rec_path(R).read_bytes() == before
    lines = [x for x in audit_lines(store_of(R)) if x["op"] == "protect"]
    assert [x["changed"] for x in lines] == [True, False, False, False]


def test_release_removes_every_matching_entry_and_the_last_removes_the_file(world):
    R = world.R
    (store_of(R) / "keep.txt").write_text("x", encoding="utf-8")
    r = gp(R, "protect", "--branch", "MAIN", "--release")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_ok_release", b="MAIN", repo=repo_text(R)), r
    assert not rec_path(R).exists() and (store_of(R) / "keep.txt").exists() and (store_of(R) / "audit.log").exists()
    r = gp(R, "protect", "--branch", "MAIN", "--release")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_same_release", b="MAIN", repo=repo_text(R)) and not rec_path(R).exists(), r
    rec_path(R).write_bytes(G.protect_bytes(None, [{"branch": "Main", "at": "x", "by": "y", "via": "terminal", "reason": ""},
                                                   {"branch": "main", "at": "x", "by": "y", "via": "terminal", "reason": ""}]))
    rc, v = jgp(R, "protect", "--branch", "main", "--release")
    assert rc == 0 and v["stored"] == "Main" and v["changed"] is True and v["protected"] == [] and not rec_path(R).exists(), v


def test_entries_are_ordered_and_a_missing_branch_can_be_protected(tmp_path, console):
    R = new_repo(tmp_path / "R")
    R.git("branch", "release/1.0")
    protect(R, "release/1.0", "main", "future")
    assert [e["branch"] for e in record_of(R)["branches"]] == ["future", "main", "release/1.0"]
    protect_rc = gp(R, "protect", "--branch", "main", "--release").rc
    assert protect_rc == 0 and [e["branch"] for e in record_of(R)["branches"]] == ["future", "release/1.0"]
    rc, v = jgp(R, "protect-show")
    assert rc == 0 and [(b["branch"], b["exists"]) for b in v["branches"]] == [("future", False), ("release/1.0", True)]


BAD_NAMES = ["", "-x", "a b", "a..b", "x.lock", "@", "a@{1}", "refs/heads/main", "REFS/x", "a" * 256, "a\x01", "a\ud800"]


def test_invalid_branch_names_are_refused(tmp_path, console):
    R = new_repo(tmp_path / "R")
    for name in BAD_NAMES:
        rc, v = jgp(R, "protect", "--branch=" + name)
        assert rc == 12 and v["code"] == "INVALID_MANIFEST" and [e["field"] for e in v["errors"]] == ["--branch"], (name, v)
        why = v["errors"][0]["text"]
        assert v["message"] == G.T("en", "protect_bad_name", b=G._shown(name), why=why), v
        if name.lower().startswith("refs/"):
            assert "short name" in why, why
        assert not store_of(R).exists(), name  # no store directory, no lock file
    ok = "b" * 255
    assert gp(R, "protect", "--branch", ok).rc == 0 and record_of(R)["branches"][0]["branch"] == ok


def test_reason_limits(tmp_path, console):
    R = new_repo(tmp_path / "R")
    for reason in ("r" * 201, "a\x07b", "a\ud800"):
        rc, v = jgp(R, "protect", "--branch", "main", "--reason", reason)
        assert rc == 24 and v["code"] == "INVALID_SPEC" and [e["field"] for e in v["errors"]] == ["--reason"], v
        assert v["message"].startswith(G.T("en", "set_invalid_args", errors="")), v
        assert not store_of(R).exists()
    assert gp(R, "protect", "--branch", "main", "--reason", "r" * 200).rc == 0
    assert record_of(R)["branches"][0]["reason"] == "r" * 200
    assert [x["reason"] for x in audit_lines(store_of(R)) if x["op"] == "protect"] == ["r" * 200]


def test_console_gate_and_dry_run(tmp_path, monkeypatch):
    R = new_repo(tmp_path / "R")
    monkeypatch.setattr(G, "user_console", lambda: False)
    r = gp(R, "protect", "--branch", "main")
    assert r.rc == 17 and r.out.strip() == G.T("en", "need_tty") and not store_of(R).exists(), r
    r = gp(R, "protect", "--branch", "main", "--dry-run")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_dry", b="main", repo=repo_text(R)) and not store_of(R).exists(), r
    r = gp(R, "protect", "--branch", "main", "--dry-run", "--release")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_same_release", b="main", repo=repo_text(R)) and not store_of(R).exists(), r
    monkeypatch.setattr(G, "user_console", lambda: True)
    protect(R, "main")
    monkeypatch.setattr(G, "user_console", lambda: False)
    before, log = rec_path(R).read_bytes(), (store_of(R) / "audit.log").read_bytes()
    r = gp(R, "protect", "--branch", "main", "--dry-run")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_same", b="main", repo=repo_text(R), stored="main"), r
    assert rec_path(R).read_bytes() == before and (store_of(R) / "audit.log").read_bytes() == log


@needs_sh
def test_protect_runs_with_a_claude_token(world):
    R = world.R
    gp(R, "protect", "--branch", "main", "--release")
    cmd = "%s %s --repo %s protect --branch main" % (PY, QS, G.sh_quote(P(R.path)))
    h = answer(G_hook(R.path, cmd))
    assert h["permissionDecision"] == "ask"
    command = h["updatedInput"]["command"]
    r = run_sh(command, R.path)
    assert r.rc == 0, r
    e = record_of(R)["branches"][0]
    assert e["branch"] == "main" and e["via"] == "prompt"
    assert [x.get("tool_use_id") for x in audit_lines(store_of(R)) if x["op"] == "protect"][-1] == "toolu_1"
    assert run_sh(command, R.path).rc == 27  # the token is used
    gp(R, "protect", "--branch", "main", "--release")
    command = answer(G_hook(R.path, cmd))["updatedInput"]["command"]
    before = sorted(os.listdir(str(store_of(R))))
    r = run_sh(command.replace("--branch main", "--branch topic"), R.path)
    assert r.rc == 28 and not rec_path(R).exists() and sorted(os.listdir(str(store_of(R)))) == before, r
    command = answer(G_hook(R.path, cmd))["updatedInput"]["command"]
    path = approvals(R) / (sha(token_of(command)) + ".json")
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["expires"] = time.time() - 1
    path.write_text(json.dumps(rec), encoding="utf-8")
    r = run_sh(command, R.path)
    assert r.rc == 26 and not rec_path(R).exists(), r


def G_hook(cwd, cmd, tool="Bash", host="claude", lang="en", tid="toolu_1"):
    body = payload(tool, cmd, cwd)
    body.update(tool_use_id=tid, session_id="s-1")
    r = run(["--lang", lang, "hook", host, "pre-tool"], stdin=json.dumps(body).encode("utf-8"))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


def test_the_sixty_fourth_branch_is_the_last(tmp_path, console):
    R = new_repo(tmp_path / "R")
    entries = [{"branch": "b%d" % k, "at": "2026-01-01T00:00:00Z", "by": "u", "via": "terminal", "reason": ""} for k in range(1, 64)]
    rec_path(R).parent.mkdir(parents=True)
    rec_path(R).write_bytes(G.protect_bytes(None, entries))
    assert gp(R, "protect", "--branch", "b64").rc == 0 and len(record_of(R)["branches"]) == 64
    before = rec_path(R).read_bytes()
    r = gp(R, "protect", "--branch", "b65")
    assert r.rc == 30 and r.out.strip() == G.T("en", "protect_limit", repo=repo_text(R), n=64) and rec_path(R).read_bytes() == before, r
    assert "64" in r.out
    assert gp(R, "protect", "--branch", "b1", "--release").rc == 0
    assert gp(R, "protect", "--branch", "b65").rc == 0 and len(record_of(R)["branches"]) == 64


UNREADABLE = [b"{", b"[]", b'{"v": "1", "branches": []}', b'{"v": true, "branches": []}', b'{"v": 0, "branches": []}', b'{"v": 1}',
              b'{"v": 1, "branches": {}}', b'{"v": 1, "branches": ["main"]}', b'{"v": 1, "branches": [{"branch": ""}]}',
              b'{"v": 1, "branches": [{"branch": "a\\u0007"}]}', b'{"v": 1, "branches": [], "branches": []}', b'{"v": 1, "branches": [], "x": NaN}',
              b'{"v": 1, "branches": []}' + b" " * (1048577 - len(b'{"v": 1, "branches": []}'))]


def doctor(repo):
    return run(["--repo", str(repo.path), "--lang", "en", "doctor"])


def test_an_unreadable_record_fails_closed_in_every_command(tmp_path, console):
    R = new_repo(tmp_path / "R")
    store_of(R).mkdir(parents=True)
    assert len(UNREADABLE[-1]) == 1048577
    for data in UNREADABLE:
        rec_path(R).write_bytes(data)
        rc, v = jgp(R, "protect", "--branch", "x")
        assert rc == 11 and v["code"] == "UNKNOWN" and [u["code"] for u in v["unknowns"]] == ["PROTECT_UNREADABLE"], (data[:40], v)
        assert v["message"].startswith("MAGOS: the branch protection record ") and "nothing was changed" in v["message"]
        assert rec_path(R).read_bytes() == data
        assert gp(R, "protect-show").rc == 11
        d = doctor(R)
        assert d.rc == 1 and "protection record protected.json cannot be read: " in d.out, (data[:40], d.out)
        assert rec_path(R).read_bytes() == data


def test_a_newer_record_is_never_misread(tmp_path, console):
    R = new_repo(tmp_path / "R")
    store_of(R).mkdir(parents=True)
    digits = "9" * 5000
    for data, v_text in ((b'{"v": 2, "branches": "x"}', "2"), (('{"v": %s}' % digits).encode("ascii"), digits)):
        rec_path(R).write_bytes(data)
        f = G.protect_path(G.open_repo(str(R.path))).replace(os.sep, "/")
        for args in (["protect", "--branch", "x"], ["protect", "--branch", "x", "--release"]):
            r = gp(R, *args)
            assert r.rc == 29 and r.out.strip() == G.T("en", "protect_newer", f=f, v=v_text) and "v=" + v_text in r.out, (args, r.out[:300])
        assert gp(R, "protect-show").rc == 29 and rec_path(R).read_bytes() == data
        d = doctor(R)
        assert d.rc == 1 and "protection record protected.json was written by a newer MAGOS (v=%s)" % v_text in d.out


def test_unknown_keys_are_kept(tmp_path, console):
    R = new_repo(tmp_path / "R")
    store_of(R).mkdir(parents=True)
    rec_path(R).write_text(json.dumps({"v": 1, "branches": [{"branch": "main", "at": "a", "by": "b", "via": "terminal", "reason": "", "ticket": 7}],
                                       "note": "x"}), encoding="utf-8")
    assert gp(R, "protect", "--branch", "dev").rc == 0
    rec = record_of(R)
    assert rec["note"] == "x" and rec["branches"][1]["ticket"] == 7 and rec["branches"][1]["branch"] == "main"
    assert list(rec["branches"][0]) == ["branch", "at", "by", "via", "reason"] and rec["branches"][0]["branch"] == "dev"
    assert gp(R, "protect", "--branch", "dev", "--release").rc == 0
    rec = record_of(R)
    assert rec == {"v": 1, "branches": [{"branch": "main", "at": "a", "by": "b", "via": "terminal", "reason": "", "ticket": 7}], "note": "x"}


HOLD = r"""
import os, sys, time
path = sys.argv[1]
fh = open(path, "a+b")
if os.name == "nt":
    import msvcrt
    fh.seek(0)
    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
sys.stdout.write("ready\n")
sys.stdout.flush()
sys.stdin.read()
"""


def test_lock_timeout(tmp_path, console, monkeypatch):
    R = new_repo(tmp_path / "R")
    store_of(R).mkdir(parents=True)
    p = subprocess.Popen([sys.executable, "-c", HOLD, str(store_of(R) / "lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert p.stdout.readline().strip() == b"ready"
        monkeypatch.setattr(G, "LOCK_S", 0.5)
        r = gp(R, "protect", "--branch", "main")
        assert r.rc == 13 and r.out.strip() == G.T("en", "lock", s=int(G.LOCK_S)), r
        assert not rec_path(R).exists() and not (store_of(R) / "audit.log").exists()
    finally:
        p.stdin.close()
        p.wait(30)


def test_protect_show_reads_without_writing(tmp_path, console):
    R = new_repo(tmp_path / "R")

    def snapshot():
        return sorted((str(f), f.read_bytes()) for f in store_of(R).rglob("*") if f.is_file()) if store_of(R).exists() else None
    r = gp(R, "protect-show")
    assert r.rc == 0 and r.out.strip() == G.T("en", "protect_show_none", repo=repo_text(R)) and not store_of(R).exists(), r
    rc, v = jgp(R, "protect-show")
    assert rc == 0 and v["branches"] == [] and v["enforced"] is True
    assert gp(R, "protect", "--branch", "main", "--reason", "freeze").rc == 0 and gp(R, "protect", "--branch", "future").rc == 0
    snap = snapshot()
    r = gp(R, "protect-show")
    lines = r.out.rstrip("\n").split("\n")
    assert lines[0] == G.T("en", "protect_show_head", repo=repo_text(R), n=2) and len(lines) == 3, lines
    assert lines[1].startswith("  future  does not exist yet  since ") and lines[1].endswith("via terminal")
    assert lines[2].startswith("  main  exists  since ") and lines[2].endswith("via terminal;  reason: freeze"), lines
    r = gp(R, "protect-show", "--branch", "MAIN")
    assert r.out.split("\n")[0] == G.T("en", "protect_show_one", b="MAIN", repo=repo_text(R), stored="main"), r
    for name in ("topic", "a b"):
        r = gp(R, "protect-show", "--branch", name)
        assert r.rc == 0 and r.out.split("\n")[0] == G.T("en", "protect_show_not", b=name, repo=repo_text(R)), r
    R.git("config", "--local", "magos.guard", "off")
    r = gp(R, "protect-show")
    assert r.out.rstrip("\n").split("\n")[-1] == G.T("en", "protect_show_off")
    rc, v = jgp(R, "protect-show", "--branch", "main")
    assert v["enforced"] is False and v["protected"] is True and v["stored"] == "main" and v["branch"] == "main"
    assert [set(b) for b in v["branches"]] == [{"branch", "at", "by", "via", "reason", "exists"}] * 2
    assert snapshot() == snap


def test_usage_and_not_a_repository(tmp_path, console):
    outside = tmp_path / "outside"
    outside.mkdir()
    for args in (["protect", "--branch", "main"], ["protect-show"]):
        r = gp(outside, *args)
        assert r.rc == 2 and "not a git repository" in r.err, r
    R = new_repo(tmp_path / "R")
    for args, word in ((["protect"], "--branch"), (["protect", "--branch", "main", "--release=x"], "--release"), (["protect", "--bra", "main"], "--bra")):
        r = gp(R, *args)
        assert r.rc == 2 and "usage:" in r.err and word in r.err and not store_of(R).exists(), (args, r)


def test_json_results(tmp_path, monkeypatch):
    R = new_repo(tmp_path / "R")
    monkeypatch.setattr(G, "user_console", lambda: True)
    seen = []
    ok_keys = {"decision", "code", "message", "exit_code", "action", "branch", "stored", "changed", "dry_run", "protected"}
    rc, v = jgp(R, "protect", "--branch", "main")  # TC-728
    seen.append(rc)
    assert rc == 0 and ok_keys <= set(v) and v["decision"] == "allow" and v["code"] == "OK" and v["action"] == "set" and v["changed"] is True
    rc, v = jgp(R, "protect", "--branch", "main", "--release")  # TC-730
    assert rc == 0 and ok_keys <= set(v) and v["action"] == "release" and v["protected"] == []
    rc, v = jgp(R, "protect", "--branch", "a b")  # TC-732
    assert rc == 12 and v["decision"] == "deny" and v["errors"][0]["field"] == "--branch"
    rc, v = jgp(R, "protect", "--branch", "main", "--reason", "x" * 201)
    assert rc == 24 and v["errors"][0]["field"] == "--reason"
    monkeypatch.setattr(G, "user_console", lambda: False)  # TC-734
    rc, v = jgp(R, "protect", "--branch", "main")
    assert rc == 17 and v["code"] == "CONSOLE_REQUIRED" and v["message"] == G.T("en", "need_tty")
    rc, v = jgp(R, "protect", "--branch", "main", "--dry-run")
    assert rc == 0 and ok_keys <= set(v) and v["dry_run"] is True and v["changed"] is False and v["protected"] == []
    monkeypatch.setattr(G, "user_console", lambda: True)
    store_of(R).mkdir(parents=True, exist_ok=True)
    rec_path(R).write_bytes(G.protect_bytes(None, [{"branch": "b%d" % k} for k in range(64)]))  # TC-736
    rc, v = jgp(R, "protect", "--branch", "z")
    assert rc == 30 and v["code"] == "PROTECT_LIMIT"
    rec_path(R).write_bytes(b"[]")  # TC-737
    rc, v = jgp(R, "protect", "--branch", "z")
    assert rc == 11 and v["unknowns"][0]["code"] == "PROTECT_UNREADABLE"
    rec_path(R).write_bytes(b'{"v": 3}')  # TC-738
    rc, v = jgp(R, "protect", "--branch", "z")
    assert rc == 29 and v["code"] == "PROTECT_NEWER_FORMAT" and set(v) == {"decision", "code", "message", "exit_code"}
    rc, v = jgp(R, "protect-show")
    assert rc == 29 and v["code"] == "PROTECT_NEWER_FORMAT"


# ---- the hook rule (TC-744 to TC-763) ------------------------------------------------------------------------------------------------------
CURRENT = [("git commit -m x", "git commit"), ("git commit --amend --no-edit", "git commit"), ("git merge topic", "git merge"),
           ("git merge --continue", "git merge --continue"), ("git merge --ff-only topic", "git merge"), ("git pull", "git pull"),
           ("git pull --rebase origin main", "git pull --rebase"), ("git cherry-pick abc", "git cherry-pick"), ("git cherry-pick --continue", "git cherry-pick"),
           ("git cherry-pick --abort", "git cherry-pick"), ("git cherry-pick -n abc", "git cherry-pick"), ("git revert HEAD", "git revert"),
           ("git rebase topic", "git rebase"), ("git rebase --continue", "git rebase --continue"), ("git am x.patch", "git am"), ("git am --abort", "git am"),
           ("git reset --hard HEAD~1", "git reset"), ("git reset --soft abc", "git reset"), ("git reset a.txt", "git reset"),
           ("git update-ref HEAD abc", "git update-ref")]


def test_current_branch_writes_are_refused(world):
    R = world.R
    for cmd, op in CURRENT:
        assert decide(R.path, cmd) == hit(R, op), cmd
        r = hook_proc(R.path, cmd)
        assert denied(r) == hit(R, op)[1] and r.out.count("\n") == 1, (cmd, r.out)


ALLOWED = ["git status", "git diff", "git log", "git show", "git blame a.txt", "git commit --dry-run", "git commit --help", "git merge -h", "git merge --abort",
           "git merge --quit", "git rebase --abort", "git rebase --quit", "git rebase --edit-todo", "git cherry-pick --quit", "git am --show-current-patch",
           "git am --quit", "git reset", "git reset --hard", "git reset HEAD a.txt", "git reset @", "git reset HEAD~1 -- a.txt", "git reset -p",
           "git stash", "git stash pop", "git restore --staged a.txt", "git tag v1", "git fetch origin",
           "git push origin main", "git switch topic", "git checkout main", "git switch -c feat main", "git branch feat main",
           "git update-ref --no-deref HEAD abc", "git worktree add --detach ../d main"]


def test_reads_and_index_only_forms_stay_allowed(world):
    for cmd in ALLOWED:
        same_as_unprotected(world.R.path, cmd, world.R)


EXPLICIT = [("git branch -f main topic", "main"), ("git branch -D main", "main"), ("git branch -d main", "main"), ("git branch --delete main", "main"),
            ("git branch -m main old", "main"), ("git branch -M topic main", "main"), ("git branch -c topic main", "main"), ("git branch future", "future"),
            ("git checkout -B main", "main"), ("git switch -C main", "main"), ("git switch -c future", "future"), ("git checkout --orphan future", "future"),
            ("git checkout --track origin/future", "future"), ("git checkout -t origin/future", "future"), ("git switch future", "future"),
            ("git checkout future", "future"),
            ("git update-ref refs/heads/main abc", "main"), ("git update-ref -d refs/heads/main", "main"),
            ("git symbolic-ref refs/heads/main refs/heads/topic", "main"), ("git push . topic:main", "main"), ("git push . :main", "main"),
            ("git push . +topic:refs/heads/main", "main"), ("git push --delete . main", "main"), ("git fetch . topic:main", "main"),
            ("git fetch origin +main:main", "main"), ("git pull origin main:main", "main"), ("git worktree add ../w main", "main"),
            ("git worktree add -b future ../w", "future"), ("git worktree add -B main ../w topic", "main"), ("git worktree add ../main", "main"),
            ("git stash branch future", "future"), ("git rebase topic main", "main"), ("git rebase --onto x y main", "main"), ("git rebase --root main", "main")]


def test_explicit_branch_writes_are_refused(world):
    protect(world.R, "future")
    world.R.git("update-ref", "refs/remotes/origin/future", "HEAD")  # future exists only on the remote
    for cmd, b in EXPLICIT:
        t = bp(decide(world.W, cmd))  # the repository is named by repo_dir of the directory the write runs in: the worktree W
        assert t is not None and t.startswith("MAGOS DENIES git ") and ("'%s' is protected in %s" % (b, repo_text(world.W))) in t, (cmd, t)
    t = bp(decide(world.R.path, "git reset --pathspec-from-file=f"))
    assert t is not None and "'main' is protected" in t, t


OTHERS = ["git merge main", "git rebase main", "git rebase --onto main topic", "git cherry-pick main", "git commit -m x", "git branch -u origin/main",
          "git branch --set-upstream-to=origin/main topic", "git branch --edit-description", "git branch -c main copy", "git switch main", "git checkout main",
          "git checkout --track origin/feat2", "git symbolic-ref HEAD refs/heads/main", "git update-ref refs/tags/main abc", "git worktree add -b feat ../w main",
          "git fetch . main:feat", "git push . main:feat", "git rebase -i -X ours --strategy=ort --autosquash main", "git rebase --exec 'make' -C4 main"]


def test_writes_to_other_branches_from_a_protected_one_stay_allowed(world):
    protect(world.R, "future")
    for cmd in OTHERS:
        same_as_unprotected(world.W, cmd, world.R)


def test_names_are_compared_folded(world):
    protect(world.R, "Release/1.0")
    for cmd, stored in (("git branch -f MAIN topic", "main"), ("git update-ref refs/HEADS/main abc", "main"), ("git update-ref REFS/heads/Main abc", "main"),
                        ("git push . topic:refs/heads/Main", "main"), ("git branch -D release/1.0", "Release/1.0")):
        t = bp(decide(world.W, cmd))
        assert t is not None and ("'%s' is protected" % stored) in t, (cmd, t)


def test_the_worktree_the_write_runs_in_decides(world):
    R, W = world.R, world.W
    r = G.sh_quote(P(R.path))
    for cmd in ("git -C %s commit -m x" % r, "cd %s && git commit -m x" % r, "cd %s; git merge topic" % r, "pushd %s; git commit -m x" % r,
                "env -C %s git merge topic" % r, "GIT_DIR=%s/.git git commit -m x" % P(R.path), 'bash -c "cd %s && git commit -m x"' % P(R.path),
                "git -c alias.ci=commit -C %s ci -m x" % r, 'git -C %s -c "alias.c=!git commit -m x" c' % r,
                'git rebase -x "git -C %s commit --allow-empty -m x" topic' % P(R.path)):
        t = bp(decide(W, cmd))
        assert t is not None and "'main' is protected in %s" % repo_text(R) in t, (cmd, t)
    same_as_unprotected(W, "git -C %s commit -m x" % G.sh_quote(P(W)), R)
    same_as_unprotected(R.path, "git -C %s commit -m x" % G.sh_quote(P(W)), R)


def split(t):
    """A deny naming main whose text ends with branch_protected_split."""
    assert t is not None and "'main' is protected" in t and t.endswith(" " + G.T("en", "branch_protected_split")), t
    return t


def test_a_checkout_in_the_same_line_counts(tmp_path, console):
    R2 = new_repo(tmp_path / "R2")
    R2.git("switch", "-q", "-c", "feat")
    protect(R2, "main")
    for cmd in ("git switch main && git merge feat", "git checkout main && git pull", "git switch main; git commit -m x", "git switch main || git commit -m x",
                "(git switch main) && git commit -m x"):
        split(bp(decide(R2.path, cmd)))
    for cmd in ("git switch $B && git commit -m x", "git checkout - && git commit -m x", "git checkout @{-1} && git commit -m x"):
        unknown_text(decide(R2.path, cmd))
    for cmd in ("git commit -m x; git checkout main", "git commit -m x && git switch main", "git switch topic && git commit -m x"):
        same_as_unprotected(R2.path, cmd, R2)


def test_a_detached_head_and_a_rebase_in_progress(world):
    R = world.R
    D, E = world.tmp / "D", world.tmp / "E"
    R.git("worktree", "add", "-q", "--detach", str(D), "main")
    same_as_unprotected(R.path, "git -C %s commit -m x" % G.sh_quote(P(D)), R)
    R.commit("a.txt", "topic\n", cwd=world.W, msg="on topic")
    R.git("worktree", "add", "-q", "-b", "rel", str(E), "main")
    R.commit("a.txt", "rel\n", cwd=E, msg="on rel")
    protect(R, "rel")
    r = R.git("rebase", "topic", cwd=E, check=False)  # git's own rebase stops on the conflict, HEAD detached
    gd = Path(R.git("rev-parse", "--path-format=absolute", "--git-dir", cwd=E))
    head = gd / "rebase-merge" / "head-name"
    assert head.read_text(encoding="utf-8").strip() == "refs/heads/rel", r
    assert R.git("rev-parse", "--abbrev-ref", "HEAD", cwd=E) == "HEAD"
    e = G.sh_quote(P(E))
    for c in ("git -C %s commit -m x" % e, "git -C %s rebase --continue" % e, "git -C %s rebase --skip" % e):
        t = bp(decide(R.path, c))
        assert t is not None and "'rel' is protected" in t, (c, t)
    same_as_unprotected(R.path, "git -C %s rebase --abort" % e, R)
    head.unlink()
    head.mkdir()
    unknown_text(decide(R.path, "git -C %s commit -m x" % e))


def test_an_unborn_branch_and_a_bare_repository(tmp_path, console):
    F = tmp_path / "F"
    F.mkdir()
    subprocess.run(["git", "init", "-q", str(F)], check=True)
    protect(F, "main")
    t = bp(decide(F, "git commit -m init"))
    assert t is not None and "'main' is protected" in t, t
    gp(F, "protect", "--branch", "main", "--release")
    protect(F, "dev")
    assert bp(decide(F, "git commit -m init")) is None
    R = new_repo(tmp_path / "R")
    B = tmp_path / "B.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(R.path), str(B)], check=True)
    protect(B, "main")
    sha = R.git("rev-parse", "HEAD")
    t = bp(decide(R.path, "git --git-dir=%s update-ref HEAD %s" % (G.sh_quote(P(B)), sha)))
    assert t is not None and "'main' is protected in %s" % G._shown(G.repo_dir(G.open_repo(str(B)))) in t, t
    assert bp(decide(R.path, "git --git-dir=%s update-ref --no-deref HEAD %s" % (G.sh_quote(P(B)), sha))) is None


UNKNOWN_LINES = ["git $c -m x", "git branch -D $B", "git update-ref refs/heads/$x abc", "git push . topic:$b", "printf main | xargs git branch -D",
                 "git update-ref --stdin < f", "git fetch . 'refs/heads/*:refs/heads/*'", "git push --all .", "git push --branches .", "git push --mirror .",
                 "git push --prune . x:y", "git push .", "git filter-branch -f HEAD", "git filter-repo --force", "git fast-import < s",
                 "git subtree pull -P d r main", "git flow feature finish x", "cd $D && git commit -m x", 'git -C "$R" merge x',
                 "git --git-dir=$G commit -m x"]


MORE_UNKNOWN = ["git rebase --whitespace fix main", "git rebase -C 3 x main", "git rebase --frobnicate main", "git bisect reset && git commit -m x",
                "gh pr checkout 5 && git commit -m x", "git push $R topic:main", "git symbolic-ref refs/heads/$x refs/heads/topic"]  # Unknown targets


def test_unknown_targets_fail_closed_where_protection_exists(world):
    for cmd in UNKNOWN_LINES + MORE_UNKNOWN:
        t = unknown_text(decide(world.W, cmd))
        assert "(main)" in t and t.startswith("MAGOS DENIES "), (cmd, t)
        assert bp(decide(world.U.path, cmd)) is None, cmd


def test_an_update_refs_rebase_fails_closed(world):
    lines = ["git rebase --update-refs main", "git -c rebase.updateRefs=true rebase main", "git pull --rebase --update-refs"]
    for cmd in lines:
        unknown_text(decide(world.W, cmd))
    same_as_unprotected(world.W, "git rebase main", world.R)
    world.R.git("config", "rebase.updateRefs", "true")
    t = unknown_text(decide(world.W, "git rebase main"))
    assert "rebase.updateRefs" in t
    same_as_unprotected(world.W, "git rebase --no-update-refs main", world.R)
    world.U.git("config", "rebase.updateRefs", "true")
    for cmd in lines + ["git rebase main", "git rebase --no-update-refs main"]:
        assert bp(decide(world.U.path, cmd)) is None, cmd


def test_update_ref_stdin_instructions(world):
    R = world.R
    for cmd in ('git update-ref --stdin <<< "delete refs/heads/main"', "printf 'update refs/heads/main abc\\n' | git update-ref --stdin",
                'git update-ref --stdin <<< "create refs/heads/MAIN abc"', 'git update-ref --stdin <<< "update HEAD abc"'):
        t = bp(decide(R.path, cmd))
        assert t is not None and "'main' is protected" in t, (cmd, t)
    for cmd in ('git update-ref --stdin <<< "update refs/heads/feat abc"', 'git update-ref --stdin <<< "verify refs/heads/main abc"',
                'git update-ref --stdin <<< "update refs/tags/main abc"'):
        same_as_unprotected(R.path, cmd, R)


def test_the_hook_fails_closed_on_an_unreadable_or_newer_record(world):
    R = world.R
    for data in (b"{", b'{"v": 7, "branches": []}'):
        rec_path(R).write_bytes(data)
        f = P(G.protect_path(G.open_repo(str(R.path))))
        for cmd in ("git commit -m x", "git switch -c feat", "git branch -D topic"):
            t = bp(decide(world.W, cmd))
            assert t is not None and f in t and ("cannot be read" in t or "newer MAGOS (v=7)" in t) and "every write to a branch" in t, (cmd, t)
        assert bp(decide(world.W, "git status")) is None
        assert bp(decide(world.U.path, "git commit -m x")) is None


def test_off_switches_silence_the_protection(world, tmp_path, monkeypatch):
    R = world.R
    R2 = new_repo(tmp_path / "R2")
    protect(R2, "main")
    R.git("config", "--local", "magos.guard", "off")
    assert bp(decide(R.path, "git commit -m x")) is None
    assert decide(R.path, "git -C %s commit -m x" % G.sh_quote(P(R2.path))) == hit(R2, "git commit")
    monkeypatch.setenv("MAGOS_GUARD", "off")
    assert bp(decide(R.path, "git commit -m x")) is None and bp(decide(R.path, "git -C %s commit -m x" % G.sh_quote(P(R2.path)))) is None


def test_protection_needs_no_claim_or_arm(tmp_path, console):
    R = new_repo(tmp_path / "R")
    protect(R, "main")
    assert G.guard_mode(G.open_repo(str(R.path))) == "auto"
    assert decide(R.path, "git commit -m x") == hit(R, "git commit")
    (store_of(R) / "ARMED").write_text("", encoding="utf-8")
    assert decide(R.path, "git commit -m x") == hit(R, "git commit")
    os.remove(str(store_of(R) / "ARMED"))
    g = G.open_repo(str(R.path))
    G.write_claim(g, "main", {"branch": "main", "entries": ["a.txt"], "created": G.now_iso(), "by": "t"})
    assert G.holds_claims(g)
    assert decide(R.path, "git commit -m x") == hit(R, "git commit")


def test_every_host_gets_the_same_deny(world):
    R = world.R
    for lang in ("zh", "en"):
        want = hit(R, "git commit", lang=lang)[1]
        bodies = [(payload("Bash", "git commit -m x", R.path), "claude", ()), (payload("PowerShell", "git commit -m x", R.path), "claude", ()),
                  (payload("Bash", ["bash", "-lc", "git commit -m x"], R.path), "codex", ()), (payload("terminal", "git commit -m x", R.path), "hermes", ()),
                  (payload("terminal", "git commit -m x", R.path), "hermes", ("--hermes-gate", "ask"))]
        for body, host, extra in bodies:
            r = hook_proc(R.path, None, host=host, lang=lang, extra=extra, body=body)
            obj = json.loads(r.out)
            assert obj == {"decision": "block", "reason": want, "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                                                     "permissionDecisionReason": want}}, (host, extra, r.out)
    assert not (store_of(R) / "denials").exists()


def test_tools_that_name_a_protected_branch(world):
    protect(world.R, "worktree-x")
    R = world.R
    t = bp(G.decide(payload("EnterWorktree", None, R.path, name="x"), "en", "claude"))
    assert t is not None and "'worktree-x' is protected" in t, t
    t = bp(G.decide(payload("mcp__ccd_session__start_session", None, R.path, branch="main", use_worktree=True), "en", "claude"))
    assert t is not None and "'main' is protected" in t, t
    body = payload("Agent", None, R.path, prompt="x", isolation="worktree")
    v = G.decide(body, "en", "claude")
    with lifted(R):
        w = G.decide(body, "en", "claude")
    assert bp(v) is None and v == w


def test_overflow_denies_a_write_only_where_protection_exists(world):
    dirs = []
    for k in range(9):
        d = world.tmp / "dirs" / ("d%d" % k)
        d.mkdir(parents=True)
        dirs.append(G.sh_quote(P(d)))
    states = "; ".join("false || cd %s" % d for d in dirs)
    commit, create = states + "; git commit -m x", states + "; git switch -c x"
    assert decide(world.U.path, commit) is None
    v = decide(world.U.path, create)
    assert v[0] == "UNPARSEABLE", v
    unknown_text(decide(world.R.path, commit))
    long = "echo " + "a" * (200001 - len("echo ; git commit -m x")) + "; git commit -m x"
    assert len(long) == 200001
    assert bp(decide(world.U.path, long)) is None
    # in R the tamper filter, which runs first, denies the text it cannot read: R holds protection, so its guarded finding counts
    assert decide(world.R.path, long) == ("PROTECTED", G.T("en", "protected", why="the command is too long to inspect"))


def test_an_exception_while_judging_a_write_fails_closed(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(G, "protection_verdict", boom)

    def hook_in(cwd, cmd):
        return run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(payload("Bash", cmd, cwd)).encode("utf-8"))
    r = hook_in(world.R.path, "git commit -m x")
    assert denied(r).startswith("MAGOS guard error (RuntimeError: boom)"), r
    r = hook_in(world.U.path, "git commit -m x")
    assert r.out.strip() == "{}" and "MAGOS guard warning: RuntimeError: boom" in r.err, r
    r = hook_in(world.U.path, "ls -la")
    assert r.out.strip() == "{}"
    monkeypatch.setattr(G, "holds_protection", boom)
    monkeypatch.setattr(G, "store_state", boom)  # the protection test itself (Finding the store) raises as well
    r = hook_in(world.U.path, "git commit -m x")
    assert denied(r).startswith("MAGOS guard error (RuntimeError: boom)"), r


def test_the_tamper_filter_covers_a_repository_with_only_protection(world):
    R, U = world.R, world.U
    assert not (store_of(R) / "ARMED").exists() and not G.holds_claims(G.open_repo(str(R.path)))
    protected = G.T("en", "protected", why=G._STATE_MSG)
    sha = R.git("rev-parse", "HEAD")
    store = P(store_of(R))
    lines = [("rm .git/magos/protected.json", "Bash"), ("echo {} > .git/magos/protected.json", "Bash"),
             ("Remove-Item %s\\protected.json" % store.replace("/", "\\"), "PowerShell"), ("echo %s > .git/refs/heads/main" % sha, "Bash"),
             ("printf x >> .git/packed-refs", "Bash")]
    for cmd, tool in lines + [("git config core.hooksPath x", "Bash")]:
        v = decide(R.path, cmd, tool=tool)
        assert v and v[0] == "PROTECTED" and v[1].startswith(G.T("en", "protected", why="")[:40]), (cmd, v)
    record = ("PROTECTED", G.T("en", "protected", why=G._PROTECT_MSG))
    assert decide(R.path, "rm .git/magos/protected.json") == record
    assert decide(R.path, "echo %s > .git/refs/heads/main" % sha) == ("PROTECTED", protected)
    assert decide(R.path, "cat .git/magos/protected.json") is None
    for k, (cmd, tool) in enumerate(lines):  # U holds no record: the record writes are denied everywhere, the ref writes are U's own
        v = decide(U.path, cmd.replace(store, P(store_of(U))), tool=tool)
        assert v == (record if k < 3 else None), (cmd, v)


def test_protect_is_user_only_and_protect_show_is_an_agent_subcommand(world):
    s = P(SCRIPT)
    user = ["python3 %s protect --branch main" % s, "python3 %s --repo %s protect --branch main --release" % (s, P(world.R.path)),
            "py -3 %s --json protect --branch x" % s, "Start-Process py %s,protect" % s, 'bash -c "python3 %s protect --branch main"' % s,
            'git commit -m "magos_guard.py protect notes"']
    shape = G.T("en", "protected_shape", why=G._USER_MSG, cmd=G.guard_cmd())
    for cmd in user:
        assert G.protected(cmd) == ("always", G._USER_MSG), cmd
        direct = cmd.startswith(("python3", "py -3"))
        v = decide(world.R.path, cmd)  # Claude Code asks only for a direct invocation
        assert isinstance(v, G.Approval) if direct else (v[0] == "PROTECTED" and v[1].startswith(shape)), (cmd, v)
        v = decide(world.R.path, cmd, host="codex")
        assert v[0] == "PROTECTED" and "magos_approve" in v[1], (cmd, v)
        v = decide(world.R.path, cmd, tool="terminal", host="hermes")  # the Hermes entry under hooks:
        assert v == ("PROTECTED", G.T("en", "protected", why=G._USER_MSG)), (cmd, v)
        v = G.decide(payload("terminal", cmd, world.R.path, workdir=P(world.R.path)), "en", "hermes", "ask")
        assert isinstance(v, G.HermesApproval) if direct else v[0] == "PROTECTED", (cmd, v)
    assert "protect" in G._USER_MSG
    for cmd in ("python3 %s protect-show" % s, "python3 %s --repo %s protect-show --branch main" % (s, P(world.R.path))):
        assert G.protected(cmd) is None, cmd
        for host, tool in (("claude", "Bash"), ("codex", "Bash"), ("hermes", "terminal")):
            assert decide(world.R.path, cmd, tool=tool, host=host) is None, (cmd, host)
        assert G.decide(payload("terminal", cmd, world.R.path), "en", "hermes", "ask") is None
    for cmd in ("python3 %s $(printf protect-show)" % s, "python3 %s protect-sho" % s):
        assert G.protected(cmd) == ("always", G._SLOT_MSG), cmd
    assert G.protected('git commit -m "protect main"') is None


def test_the_subcommand_tables_partition_the_parser():
    ap = G.build_parser()
    sub = next(a for a in ap._actions if a.dest == "cmd")
    tables = [list(G.AGENT_SUBS), [u.name for u in G.USER_ONLY], list(G.HOST_ONLY), ["hook"]]
    flat = [n for t in tables for n in t]
    assert sorted(flat) == sorted(sub.choices) and len(flat) == len(set(flat))
    assert next(u for u in G.USER_ONLY if u.name == "protect")[1:] == (False, "repo") and "protect-show" in G.AGENT_SUBS
    assert G.parse_quiet(["protect", "--branch", "m", "--approval=x"]).approval == "x"
    assert G.parse_quiet(["protect-show", "--approval=x"]) is None
    assert "--approval" not in sub.choices["protect"].format_help()
    usage = ap.format_usage()
    assert "protect," in usage and "protect-show" in usage and "mcp" not in usage


def test_claude_asks_for_protect_at_every_level_but_terminal(world, tmp_path):
    R = world.R
    cmd = "py -3 %s --repo %s protect --branch main" % (QS, G.sh_quote(P(R.path)))
    for level in ("prompt", "auto-safe"):
        R.git("config", "magos.approval", level)
        h = answer(G_hook(R.path, cmd))
        assert h["permissionDecision"] == "ask", (level, h)
        what = G.T("en", "approval_what_protect", b=json.dumps("main"), repo=G._dialog(G.repo_dir(G.open_repo(str(R.path))), 200), reason="", dry="")
        assert what in h["permissionDecisionReason"], h
    R.git("config", "magos.approval", "terminal")
    assert denied(G_hook(R.path, cmd)) == G.T("en", "protected_level", why=G._USER_MSG)
    R.git("config", "magos.approval", "prompt")
    h = answer(G_hook(R.path, cmd + " --release --reason 'x\u202ey'"))
    reason = G.T("en", "approval_protect_reason", reason=json.dumps("x y"))
    assert G.T("en", "approval_what_unprotect", b=json.dumps("main"), repo=G._dialog(G.repo_dir(G.open_repo(str(R.path))), 200), reason=reason,
               dry="") in h["permissionDecisionReason"], h
    outside = tmp_path / "outside"
    outside.mkdir()
    before = sorted(os.listdir(str(approvals(R))))
    t = denied(G_hook(outside, "py -3 %s protect --branch main" % QS))
    assert t.endswith("[APPROVAL_REPO]"), t
    assert sorted(os.listdir(str(approvals(R)))) == before


def test_codex_maps_protect_onto_magos_approve(world, hosts, bare_exe):
    R = world.R
    r = run(["--lang", "en", "hook", "codex", "pre-tool"], stdin=json.dumps({"tool_name": "Bash", "cwd": str(R.path), "tool_input": {
        "command": "python3 %s --repo %s protect --branch main --release" % (QS if not WIN else '"%s"' % P(SCRIPT), P(R.path))}}).encode("utf-8"))
    args = {"subcommand": "protect", "repo": P(R.path), "branch": "main", "release": True}
    argv = ["--repo=" + P(R.path), "--lang=en", "protect", "--branch=main", "--release"]
    assert denied(r) == G.T("en", "protected_codex", why=G._USER_MSG, call=json.dumps(args), ready=G.ready_command(argv)), r
    for arguments, err in (({"subcommand": "protect", "repo": P(R.path)}, "branch: required for protect"),
                           ({"subcommand": "protect", "repo": P(R.path), "branch": "main", "release": "yes"}, "release: true or false"),
                           ({"subcommand": "protect", "repo": P(R.path), "branch": "a\x01"}, "branch: holds a control character or a lone surrogate"),
                           ({"subcommand": "arm", "repo": P(R.path), "reason": "x"}, "reason: arm takes no reason")):
        v, errors = G.mcp_validate(arguments, "en")
        assert v is None and err in errors, (arguments, errors)
    v, errors = G.mcp_validate({"subcommand": "arm", "repo": P(R.path), "release": False}, "en")
    assert errors is None and v["argv"] == ["--repo=" + P(R.path), "--lang=en", "arm"]
    v, errors = G.mcp_validate({"subcommand": "protect", "repo": P(R.path), "branch": "main"}, "en")
    assert errors is None and v["args"] == {"subcommand": "protect", "repo": P(R.path), "branch": "main"} and v["ns"].reason == ""
    v, errors = G.mcp_validate(args, "en")
    assert errors is None and v["argv"] == argv and v["args"] == args
    h = hosts()
    cid, msg = h.dialog(args)
    assert G.T("en", "approval_what_unprotect", b=json.dumps("main"), repo=G._dialog(G.repo_dir(G.open_repo(str(R.path))), 200), reason="",
               dry="") in msg["params"]["message"], msg
    h.answer(msg["id"], ACCEPT)
    res = h.result(cid)
    assert res["structuredContent"]["exit_code"] == 0, res
    assert not rec_path(R).exists()
    line = [x for x in audit_lines(store_of(R)) if x["op"] == "protect"][-1]
    assert line["action"] == "release" and line["route"] == "mcp" and line["client"] == "%s/%s" % (CLIENT["name"], CLIENT["version"])


def test_hermes_asks_for_protect(world, elsewhere):
    R = world.R
    cmd = "%s %s --repo %s protect --branch main" % (PY, QS, G.sh_quote(P(R.path)))
    for level in ("prompt", "auto-safe"):
        R.git("config", "magos.approval", level)
        command, message, key = asked(H(cmd, elsewhere))
        assert G.T("en", "approval_what_protect", b=json.dumps("main"), repo=G._dialog(G.repo_dir(G.open_repo(str(R.path))), 200), reason="",
                   dry="") in message and "--approval=" in command and key.startswith("magos:protect:"), (level, message)
    assert denied(H(cmd, elsewhere, gate="bypass")) == G.T("en", "protected_hermes_noask", why=G._USER_MSG, how=G.T("en", "hermes_how_session"))
    assert denied(H(cmd, elsewhere, gate=None)) == G.T("en", "protected", why=G._USER_MSG)


def test_the_tool_schema_and_texts_name_protect():
    props = G.MCP_TOOL_SPEC["inputSchema"]["properties"]
    assert props["subcommand"]["enum"][-1] == "protect" and props["branch"]["type"] == "string" and props["release"]["type"] == "boolean"
    assert G.MCP_TOOL_SPEC["inputSchema"]["additionalProperties"] is False
    assert G.MCP_ARGS[-2:] == ("branch", "release") and G._MCP_TAKES["protect"] == ("repo", "branch", "release", "reason", "dry_run")
    assert "protect" in G.MCP_TOOL_SPEC["description"]
    for lang in ("zh", "en"):
        for key in ("mcp_invalid", "protected_codex_form", "protected_slot"):
            assert "protect" in G.M[key][0 if lang == "zh" else 1], (key, lang)
        for key in ("mcp_invalid", "protected_codex_form"):
            text = G.M[key][0 if lang == "zh" else 1]
            assert "branch" in text and "release" in text, (key, lang)


def test_doctor_reports_the_protection(tmp_path, console):
    R = new_repo(tmp_path / "R")
    base = doctor(R)
    assert "protected branches: none" in base.out.splitlines()
    R.git("branch", "release/1.0")
    protect(R, "main", "release/1.0")
    d = doctor(R)
    assert "protected branches: 2: main, release/1.0" in d.out.splitlines() and d.rc == base.rc, d.out
    rec_path(R).write_bytes(G.protect_bytes(None, [{"branch": "b%02d" % k} for k in range(25)]))
    line = next(x for x in doctor(R).out.splitlines() if x.startswith("protected branches: "))
    assert line == "protected branches: 25: %s +5 more" % ", ".join("b%02d" % k for k in range(20)), line
    for data in (b"{", b'{"v": 9}'):
        rec_path(R).write_bytes(data)
        assert doctor(R).rc == 1
    rec_path(R).write_bytes(G.protect_bytes(None, [{"branch": "main"}]))
    R.git("config", "--local", "magos.guard", "off")
    d = doctor(R)
    assert "protected branches are not enforced: magos.guard is off in this repository" in d.out.splitlines() and d.rc == base.rc, d.out


PROTECT_KEYS = ("branch_protected", "branch_protected_unknown", "branch_protected_record", "protect_why_unreadable", "protect_why_newer", "protect_unreadable",
                "protect_newer", "protect_bad_name", "protect_limit", "protect_ok", "protect_ok_release", "protect_same", "protect_same_release", "protect_dry",
                "protect_dry_release", "protect_show_none", "protect_show_head", "protect_show_line", "protect_show_reason", "protect_exists", "protect_absent",
                "protect_show_one", "protect_show_not", "protect_show_off", "approval_what_protect", "approval_what_unprotect", "approval_protect_reason")


def test_the_protection_messages():
    import string
    for key in PROTECT_KEYS:
        zh, en = G.M[key]
        fields = [sorted({f for _t, f, _s, _c in string.Formatter().parse(s) if f}) for s in (zh, en)]
        assert fields[0] == fields[1] and zh != en, key
        for lang in ("zh", "en"):
            text = G.T(lang, key, **{f: "V" for f in fields[0]})
            assert "{" not in text and "}" not in text, (key, lang)
    name = "a\x01b" + "c" * 100
    shown = G._shown(name)
    assert shown.startswith("a b") and len(shown) == 80
    assert G.T("en", "branch_protected", op="git commit", b=shown, repo="r").count(shown) == 3


def counted(monkeypatch):
    """Git.run counted: -> the list the calls (their first two arguments after --git-dir=) are added to."""
    calls, real = [], G.Git.run

    def counting(self, *args, **kw):
        calls.append([x for x in args if not x.startswith("--git-dir=")][:2])
        return real(self, *args, **kw)
    monkeypatch.setattr(G.Git, "run", counting)
    return calls


def hook_in(cwd, cmd, tool="Bash"):
    return run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps(payload(tool, cmd, cwd)).encode("utf-8"))


def test_a_repository_without_protection_costs_no_git_call(world, monkeypatch):
    calls = counted(monkeypatch)
    UW = world.tmp / "UW"
    world.U.git("worktree", "add", "-q", "-b", "uw", str(UW), "main")
    for where in (world.U.path, UW):
        calls.clear()
        t0 = time.monotonic()
        r = hook_in(where, "git commit -m x")
        assert time.monotonic() - t0 < time_budget(18)
        assert r.out.strip() == "{}" and calls == [], (where, calls)  # the store is found by the walk: no Git call
    calls.clear()
    r = hook_in(world.R.path, "git commit -m x")
    assert denied(r) is not None
    others = [c for c in calls if c[0] != "rev-parse"]
    assert len(others) <= 2 and ["worktree", "list"] in others, calls  # the opening, the magos.guard of the repository and one worktree list


def test_a_worktree_the_line_creates_writes_its_own_branch(world):
    R = world.R
    for cmd in ("git worktree add -b feat ../wf && cd ../wf && git commit -m x", "git worktree add --detach ../wd && cd ../wd && git commit -m x",
                "git init ../n && cd ../n && git commit -m x"):
        same_as_unprotected(R.path, cmd, R)
    t = bp(decide(R.path, "git worktree add -b main2 ../w2 && cd ../w2 && git branch -f main"))
    assert t is not None and "'main' is protected" in t, t


def test_a_local_push_is_judged_in_the_target_repository(world):
    R, U = world.R, world.U
    rel = os.path.relpath(str(R.path), str(U.path)).replace("\\", "/")
    url = "file://" + ("/" if WIN else "") + P(R.path)
    for cmd in ("git push %s topic:main" % rel, "git push %s :main" % url):
        t = bp(decide(U.path, cmd))
        assert t is not None and "'main' is protected in %s" % repo_text(R) in t, (cmd, t)
    for cmd in ("git push %s topic:feat" % rel, "git push origin topic:main"):
        same_as_unprotected(U.path, cmd, R)


def test_audit_lines_of_protect(world, hosts, guard):
    R = world.R
    gp(R, "protect", "--branch", "main", "--release")
    assert gp(R, "protect", "--branch", "dev", "--dry-run").rc == 0
    assert gp(R, "protect", "--branch", "a b").rc == 12
    lines = [x for x in audit_lines(store_of(R)) if x["op"] == "protect"]
    assert [(x["action"], x["branch"], x["via"]) for x in lines] == [("set", "main", "terminal"), ("release", "main", "terminal")]
    h = hosts()
    cid, msg = h.dialog({"subcommand": "protect", "repo": P(R.path), "branch": "main", "reason": "freeze"})
    h.answer(msg["id"], ACCEPT)
    assert h.result(cid)["structuredContent"]["exit_code"] == 0
    line = [x for x in audit_lines(store_of(R)) if x["op"] == "protect"][-1]
    assert line["route"] == "mcp" and line["client"] == "fake-host/1" and line["via"] == "prompt" and line["reason"] == "freeze"
    log = store_of(R) / "audit.log"
    os.remove(str(log))
    log.mkdir()
    rc, v = jgp(R, "protect", "--branch", "dev")
    assert rc == 0 and [w["code"] for w in v["warnings"]] == ["AUDIT_NOT_WRITTEN"] and "dev" in [e["branch"] for e in record_of(R)["branches"]], v


@pytest.mark.skipif(not WIN, reason="Windows only: a reader without share-delete blocks os.replace")
def test_a_busy_record_is_retried(world):
    R = world.R
    path = rec_path(R)
    before = path.read_bytes()
    hold = "import sys, time\nfh = open(sys.argv[1], 'rb')\nsys.stdout.write('ready\\n')\nsys.stdout.flush()\ntime.sleep(float(sys.argv[2]))\n"
    p = subprocess.Popen([sys.executable, "-c", hold, str(path), "0.5"], stdout=subprocess.PIPE)
    assert p.stdout.readline().strip() == b"ready"
    r = gp(R, "protect", "--branch", "dev")
    p.wait(30)
    assert r.rc == 0 and [e["branch"] for e in record_of(R)["branches"]] == ["dev", "main"], r
    before = path.read_bytes()
    p = subprocess.Popen([sys.executable, "-c", hold, str(path), "6"], stdout=subprocess.PIPE)
    try:
        assert p.stdout.readline().strip() == b"ready"
        r = gp(R, "protect", "--branch", "ops")
    finally:
        p.wait(30)
    assert r.rc == 11 and path.read_bytes() == before and not [f for f in os.listdir(str(store_of(R))) if f.endswith(".tmp")], r


def test_sets_meet_the_protection(tmp_path, console, guard):
    R = new_repo(tmp_path / "R")
    for rel in ("src/a.py",):
        R.write(rel, "base\n")
    R.git("add", "-A")
    R.git("commit", "-q", "-m", "files")
    spec = custom_spec(R, tmp_path, [lane(tmp_path, "api", ["src/"])])
    r = guard(R, "--json", *sp_args(write_spec(tmp_path, spec)))
    assert r.rc == 0, r
    protect(R, "main")
    same_as_unprotected(R.path, "git switch -c agent/demo/integration main", R)
    R.git("branch", "agent/demo/api")
    t = bp(decide(R.path, "git merge agent/demo/api"))
    assert t is not None and "'main' is protected" in t, t
    protect(R, "agent/demo/integration")
    t = bp(decide(R.path, "git switch -c agent/demo/integration main"))
    assert t is not None and "'agent/demo/integration' is protected" in t, t


def test_no_override_and_no_denial_record(world, console):
    R = world.R
    v = decide(R.path, "git commit -m x")
    assert v == hit(R, "git commit")
    text = v[1].replace(repo_text(R), "<repo>")
    assert not re.search(r"\b[0-9a-f]{12}\b", text) and "override" not in text and not (store_of(R) / "denials").exists()
    r = run(["--repo", str(R.path), "--lang", "en", "override", "--fingerprint", "0123456789ab", "--reason", "r"], stdin=b"0123456789ab\n")
    assert r.rc == 0 and (store_of(R) / "override" / "0123456789ab.json").exists(), r
    assert decide(R.path, "git commit -m x") == v


def test_nested_text_is_read_for_writes(world):
    R = world.R
    enc = base64.b64encode("git commit -m x".encode("utf-16-le")).decode("ascii")
    for cmd, tool in (("pwsh -EncodedCommand " + enc, "PowerShell"), ('cmd /c "git commit -m x"', "Bash"), ("bash <<'E'\ngit commit -m x\nE", "Bash"),
                      ("$(git commit -m x)", "Bash")):
        t = bp(decide(R.path, cmd, tool=tool))
        assert t is not None and "'main' is protected" in t, (cmd, t)
    for cmd in ("cat <<'E' > notes.txt\ngit commit -m x\nE", 'echo "git commit -m x"'):
        assert decide(R.path, cmd) is None, cmd


# ---- the review fixes (TC-781 to TC-798) ---------------------------------------------------------------------------------------------------
def denies_main(v, cmd=""):
    t = bp(v)
    assert t is not None and "'main' is protected" in t, (cmd, v)
    return t


def test_an_exempt_word_that_is_a_value_exempts_nothing(world):
    R = world.R
    for cmd in ("git commit -am --dry-run", "git commit -qm --dry-run", "git commit --mess --dry-run", "git commit -F --dry-run", "git merge -m --abort feat",
                "git merge --strategy-option --quit feat", "git cherry-pick -X --quit feat", "git revert --strategy-option --quit HEAD",
                "git am --exclude --quit x.patch", "git am --include --show-current-patch x"):
        denies_main(decide(R.path, cmd), cmd)
    for cmd in ("git commit --dry-run", "git commit -m x --dry-run", "git commit -am x --dry-run", "git merge --abort", "git merge --quit", "git cherry-pick --quit",
                "git revert --quit", "git am --show-current-patch", "git am --quit"):
        same_as_unprotected(R.path, cmd, R)


def test_an_unproven_exemption_is_a_write(world):
    for cmd in ("git merge --frobnicate --abort", "git commit --zap --dry-run", "git am --mystery --quit"):
        denies_main(decide(world.R.path, cmd), cmd)
        assert bp(decide(world.U.path, cmd)) is None, cmd


def test_a_local_remote_is_judged_like_dot(world):
    R, W = world.R, world.W
    R.git("remote", "add", "self", ".")
    R.git("remote", "add", "back", str(R.path))
    for cmd in ("git push self topic:main", "git fetch self topic:main", "git -c remote.me.url=. push me topic:main",
                "git -c remote.me.url=file://%s%s push me :main" % ("/" if WIN else "", P(R.path)), "git push back topic:main"):
        denies_main(decide(W, cmd), cmd)
    R.git("remote", "add", "web", "https://example.invalid/r.git")
    for cmd in ("git push web topic:main", "git -c remote.s.url=user@host:r.git push s topic:main", "git push nosuch topic:main", "git push self topic:feat"):
        same_as_unprotected(W, cmd, R)
    R.git("config", "remote.pushDefault", "self")
    t = unknown_text(decide(R.path, "git push"))
    assert "push.default" in t
    R.git("config", "--unset", "remote.pushDefault")
    R.git("config", "branch.topic.remote", ".")
    unknown_text(decide(W, "git push"))


RUNS_TEXT = [("git -c core.editor=x commit --amend", "core.editor"), ("git -c sequence.editor=x rebase -i main", "sequence.editor"),
             ("git -c core.fsmonitor=x status", "core.fsmonitor"), ("git -c core.pager=x log", "core.pager"), ("git -c core.sshCommand=x fetch origin", "core.sshCommand"),
             ("git -c credential.helper=x fetch origin", "credential.helper"), ("git -c diff.external=x diff", "diff.external"),
             ("git -c diff.t.textconv=x diff", "diff.t.textconv"), ("git -c merge.m.driver=x merge main", "merge.m.driver"),
             ("git -c filter.f.clean=x add a.txt", "filter.f.clean"), ("git -c difftool.d.cmd=x difftool", "difftool.d.cmd"),
             ("git --config-env=core.editor=E commit", "core.editor"), ("GIT_SEQUENCE_EDITOR=x git rebase -i main", "GIT_SEQUENCE_EDITOR"),
             ("GIT_EDITOR=x git merge main", "GIT_EDITOR"), ("env GIT_SSH_COMMAND=x git fetch origin", "GIT_SSH_COMMAND"), ("export GIT_PAGER=x; git log", "GIT_PAGER"),
             ("EDITOR=x git status", "EDITOR"), ("$env:GIT_EXTERNAL_DIFF='x'; git diff", "GIT_EXTERNAL_DIFF"), ("git config diff.external x", "diff.external"),
             ("git config --local core.editor x", "core.editor"),
             # the programs a signing key, a diff driver and a transport option name
             ("git -c gpg.program=x tag -s v1 -m x", "gpg.program"), ("git -c gpg.ssh.program=x tag -s v1 -m x", "gpg.ssh.program"),
             ("git -c gpg.x509.program=x commit -S -m x", "gpg.x509.program"), ("git -c diff.d.command=x diff", "diff.d.command"),
             ("git fetch --upload-pack=x origin", "--upload-pack"), ("git fetch --upload x origin", "--upload-pack"),
             ("git pull --upload-pack x origin main", "--upload-pack"), ("git ls-remote --upload-pack=x origin", "--upload-pack"),
             ("git ls-remote --exec=x origin", "--exec"), ("git clone -u x origin c", "-u"), ("git clone --upload-pack=x origin c", "--upload-pack"),
             ("git push --receive-pack=x origin topic", "--receive-pack"), ("git push --exec=x https://example.invalid/r.git topic", "--exec")]


def test_settings_that_run_command_text_fail_closed(world):
    for cmd, key in RUNS_TEXT:
        tool = "PowerShell" if cmd.startswith("$env:") else "Bash"
        t = unknown_text(decide(world.W, cmd, tool=tool))
        assert ("git runs command text from the" in t or "git runs the program the option" in t) and key in t, (cmd, t)
        assert bp(decide(world.U.path, cmd, tool=tool)) is None, cmd
    for cmd in ("git -c color.ui=never log", "git -c user.name=x status", "git config --get core.editor", "git -c alias.st=status st", "EDITOR=x ls",
                "git tag -s v1 -m x", "git -c gpg.format=ssh tag -s v1 -m x", "git fetch origin", "git ls-remote origin", "git clone origin c",
                "git push origin topic", "git fetch -u origin", "git -c diff.d.binary=true diff"):
        same_as_unprotected(world.W, cmd, world.R)
        assert bp(decide(world.U.path, cmd)) is None, cmd


def test_a_pathspec_file_reset_is_a_full_reset(world):
    for cmd in ("git reset --pathspec-from-file=f", "git reset --pathspec-from-file f HEAD~1", "git reset --pathspec-from-file=f --pathspec-file-nul"):
        denies_main(decide(world.R.path, cmd), cmd)
    for cmd in ("git reset -- a.txt", "git reset -p", "git reset HEAD a.txt", "git reset @"):
        same_as_unprotected(world.R.path, cmd, world.R)


def every_host(cwd, cmd, tool="Bash"):
    """decide() of the command on every host: Claude Code, Codex, the Hermes entry and the Hermes plugin's hook."""
    return [decide(cwd, cmd, tool=tool), decide(cwd, cmd, tool=tool, host="codex"), decide(cwd, cmd, tool="terminal", host="hermes"),
            G.decide(payload("terminal", cmd, cwd), "en", "hermes", "ask")]


def test_every_writer_of_the_record_is_refused_everywhere(world):
    A = str(store_of(world.R))
    a, w = P(A), A.replace("/", "\\")
    outside = world.tmp / "outside"
    outside.mkdir()
    writes = ["install /dev/null %s/protected.json" % a, "dd if=/dev/null of=%s/protected.json" % a, "fsutil file createnew %s\\protected.json 0" % w,
              "icacls %s\\protected.json /deny Everyone:R" % w, "tar -C %s -xf t.tar" % a, "unzip -d %s z.zip" % a, "Expand-Archive z.zip %s" % w,
              "rsync x %s/protected.json" % a, "robocopy x %s protected.json" % w, "xcopy x %s\\protected.json" % w, "mv x %s/protected.json" % a,
              "ren %s\\protected.json p.bak" % w, "rm -rf %s" % a, "find %s -delete" % a, "ls > %s/protected.json" % a]
    record = ("PROTECTED", G.T("en", "protected", why=G._PROTECT_MSG))
    for cmd in writes:
        assert G.protected(cmd) == ("always", G._PROTECT_MSG), cmd
        for where in (world.U.path, world.R.path, outside):
            assert every_host(where, cmd) == [record] * 4, (cmd, where)
    assert G.protected("cp x .git/magos/protected.json") == ("always", G._PROTECT_MSG)
    assert every_host(world.R.path, "cp x .git/magos/protected.json") == [record] * 4
    for cmd in ("cat %s/protected.json" % a, "Get-Content %s\\protected.json" % w, "ls %s" % a, "grep main %s/protected.json" % a,
                "find %s -name '*.json'" % a, "wc -c %s/protected.json" % a, "diff x %s/protected.json" % a, "test -f %s/protected.json" % a):
        assert G.protected(cmd) is None, cmd
        for where in (world.U.path, world.R.path, outside):
            assert every_host(where, cmd) == [None] * 4, (cmd, where)


def test_ref_writes_are_judged_in_the_repository_they_belong_to(world):
    R, U = world.R, world.U
    protected = ("PROTECTED", G.T("en", "protected", why=G._STATE_MSG))
    r = P(R.path)
    for cmd, tool in (("install x .git/refs/heads/main", "Bash"), ("dd if=x of=.git/refs/heads/main", "Bash"), ("mv x .git/HEAD", "Bash"),
                      ("robocopy . .git\\refs\\heads main", "PowerShell"), ("Copy-Item x .git/packed-refs", "PowerShell")):
        assert decide(R.path, cmd, tool=tool) == protected, cmd
    for cmd in ("cp x %s/.git/refs/heads/main" % r, "tee %s/.git/worktrees/w/HEAD" % r, "install x %s/.git/refs/heads/main" % r):
        assert decide(R.path, cmd) == protected and decide(U.path, cmd) == protected, cmd
    for cmd in ("cat .git/HEAD", "ls .git/refs/heads"):
        assert decide(R.path, cmd) is None and decide(U.path, cmd) is None, cmd
    assert decide(U.path, "install x .git/refs/heads/main") is None  # U holds no protection


CD_GIT = [("cd .git && rm -rf magos", "Bash"), ("cd .git/magos; echo {} > protected.json", "Bash"), ("cd .git/refs/heads && cp ../../../x main", "Bash"),
          ("pushd .git; mv magos m; popd", "Bash"), ("Set-Location .git\\magos; Remove-Item protected.json", "PowerShell"),
          ("(cd .git && rm magos/protected.json)", "Bash"), ('bash -c "cd .git && rm -r magos"', "Bash"), ("env -C .git rm -r magos", "Bash"),
          ("cd {R}/.git && install x HEAD", "Bash"), ("mv .git ../g", "Bash"), ("rm -rf .git", "Bash"), ("Remove-Item -Recurse .git", "PowerShell")]


def test_a_cd_into_the_git_directory_is_refused_where_protection_exists(world):
    R, U = world.R, world.U
    head = G.T("en", "protected", why="")[:40]
    record = ("PROTECTED", G.T("en", "protected", why=G._PROTECT_MSG))
    for cmd, tool in CD_GIT:
        v = decide(R.path, cmd.replace("{R}", P(R.path)), tool=tool)
        assert v and v[0] == "PROTECTED" and v[1].startswith(head), (cmd, v)
    for cmd in ("cd .git && cat HEAD", "cd .git && ls refs/heads", "cd .git; git status"):
        assert decide(R.path, cmd) is None, cmd
    for cmd, tool in CD_GIT:  # U: only the record rule (a word that names the record or its store) denies, never the git-directory rule
        v = decide(U.path, cmd.replace("{R}", P(U.path)), tool=tool)
        assert v in (None, record), (cmd, v)
    assert decide(U.path, "cd .git/magos; echo {} > protected.json") == record and decide(U.path, "cd .git && rm -rf magos") == record


def test_the_current_branch_follows_the_order_of_the_line(world, tmp_path, console):
    R, W = world.R, world.W
    R2 = new_repo(tmp_path / "R2")
    for cmd in ("git switch -c feat && git commit -am x", "git checkout -b f2 && git add -A && git commit -m x",
                "git stash && git switch topic && git stash pop && git commit -m x", "git switch -c agent/s/integration main && git merge agent/s/lane-a"):
        same_as_unprotected(R.path, cmd, R)
    for cmd in ("git commit -m x && git switch main", "git -C %s switch main && git commit -m x" % G.sh_quote(P(R2.path))):
        same_as_unprotected(W, cmd, R)
    split(bp(decide(W, "git switch main && git commit -m x")))
    for cmd in ("git switch main; git commit -m x", "git switch main || git commit -m x"):
        split(bp(decide(W, cmd)))


def test_a_path_checkout_is_no_switch(world):
    for cmd in ("git checkout main a.txt && git commit -m x", "git checkout main a.txt b.txt; git commit -m x", "git checkout main -- a.txt && git commit -m x"):
        same_as_unprotected(world.W, cmd, world.R)
    split(bp(decide(world.W, "git checkout main && git commit -m x")))
    # the patch and pathspec-file forms take paths: real git leaves HEAD where it was, so they move no current branch
    R = world.R
    R.write("f", "a.txt\n")
    R.git("checkout", "--pathspec-from-file=f", "topic")
    assert R.git("branch", "--show-current") == "main"
    for cmd in ("git checkout --pathspec-from-file=f topic && git commit -am x", "git checkout -p topic && git commit -m x",
                "git checkout --patch topic && git commit -m x", "git checkout --pathspec-from-file f --pathspec-file-nul topic && git commit -m x"):
        denies_main(decide(R.path, cmd), cmd)
    same_as_unprotected(R.path, "git checkout topic && git commit -m x", R)


def test_a_checkout_that_creates_a_protected_branch_is_refused(world, monkeypatch):
    R, W = world.R, world.W
    protect(R, "future")
    for ref in ("future", "feat2"):
        R.git("update-ref", "refs/remotes/origin/" + ref, "HEAD")
    for cmd in ("git checkout --track origin/future", "git checkout -t origin/future", "git switch future", "git checkout future",
                "git switch --track origin/future"):
        t = bp(decide(W, cmd))
        assert t is not None and "'future' is protected" in t, (cmd, t)
    for cmd in ("git switch main", "git checkout --track origin/feat2", "git switch feat2"):
        same_as_unprotected(W, cmd, R)
    calls = counted(monkeypatch)
    r = hook_in(W, "git switch future && git switch future")
    assert denied(r) is not None
    assert len([c for c in calls if c == ["rev-parse", "--verify"]]) == 1, calls


def test_the_store_is_found_without_git(world, tmp_path, monkeypatch):
    UW = tmp_path / "UW"
    world.U.git("worktree", "add", "-q", "-b", "uw", str(UW), "main")
    assert G.find_store(str(UW))[0] and G.store_state(str(UW))[0] == "none" and G.store_state(str(world.W))[0] == "held"
    calls = counted(monkeypatch)
    for where in (world.U.path, UW):
        calls.clear()
        assert hook_in(where, "git commit -m x").out.strip() == "{}" and calls == [], where
    assert denied(hook_in(world.R.path, "git commit -m x")) == hit(world.R, "git commit")[1]
    calls.clear()
    assert hook_in(world.W, "git commit -m x").out.strip() == "{}" and calls  # found through commondir, then judged with Git: topic
    B = tmp_path / "B.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(world.U.path), str(B)], check=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    odd = tmp_path / "odd"
    odd.mkdir()
    (odd / ".git").write_text("gitdir: %s\n" % P(tmp_path / "nowhere"), encoding="utf-8")
    for where, cmd, env in ((world.U.path, "git commit -m x", True), (outside, "git --git-dir=%s update-ref HEAD x" % P(B), False),
                            (outside, "git commit -m x", False), (odd, "git commit -m x", False)):
        if env:
            monkeypatch.setenv("GIT_DIR", str(world.U.path / ".git"))
        assert G.find_store(str(where)) is None or not env
        calls.clear()
        r = hook_in(where, cmd)
        assert r.out.strip() == "{}" and calls, (where, cmd, r)  # the layouts the walk does not understand: Git opens the repository, as before
        monkeypatch.delenv("GIT_DIR", raising=False)


def test_a_cd_to_a_missing_directory_is_unknown(world):
    for cmd in ("cd missing && git commit -m x", "cd missing; git commit -m x"):
        t = unknown_text(decide(world.R.path, cmd))
        assert "does not exist" in t, t
        assert bp(decide(world.U.path, cmd)) is None


def test_the_follow_into_a_created_directory_reads_its_branch(world):
    denies_main(decide(world.R.path, "mkdir -p sub/x && cd sub/x && git commit -m x"))
    same_as_unprotected(world.R.path, "git worktree add -b feat ../wf && cd ../wf && git commit -m x", world.R)
    assert bp(decide(world.U.path, "mkdir -p sub/x && cd sub/x && git commit -m x")) is None


def test_a_git_failure_while_judging_is_unknown(world, monkeypatch):
    real = G.Git.run

    def failing(self, *args, **kw):
        if args[:2] == ("worktree", "list"):
            raise G.GitFail("GIT_FAILED", "git worktree list: refused")
        return real(self, *args, **kw)
    monkeypatch.setattr(G.Git, "run", failing)
    t = unknown_text(decide(world.W, "git commit -m x"))
    assert "GIT_FAILED" in t, t
    assert bp(decide(world.U.path, "git commit -m x")) is None
    monkeypatch.setattr(G.Git, "run", real)
    monkeypatch.setattr(G, "HOOK_DEADLINE", time.monotonic() - 1)
    t = unknown_text(decide(world.W, "git commit -m x"))
    assert "BUDGET_EXCEEDED" in t, t
    calls = counted(monkeypatch)
    assert bp(decide(world.U.path, "git commit -m x")) is None and calls == []


def test_an_unreadable_head_of_a_git_directory_is_unknown(world, tmp_path, monkeypatch, console):
    B = tmp_path / "B.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(world.R.path), str(B)], check=True)
    protect(B, "main")
    sha = world.R.git("rev-parse", "HEAD")
    head = (B / "HEAD").read_bytes()
    (B / "HEAD").write_text("garbage\n", encoding="utf-8")
    unknown_text(decide(world.U.path, "git --git-dir=%s update-ref HEAD %s" % (G.sh_quote(P(B)), sha)))
    (B / "HEAD").write_bytes(head)
    real = G.Git.run

    def no_rev_parse(self, *args, **kw):
        if "rev-parse" in args:
            return (128, b"") if not kw.get("full") else (128, b"", b"")
        return real(self, *args, **kw)
    monkeypatch.setattr(G.Git, "run", no_rev_parse)
    unknown_text(decide(world.U.path, "GIT_DIR=%s git update-ref HEAD %s" % (G.sh_quote(P(B)), sha)))
    monkeypatch.setattr(G.Git, "run", real)
    subprocess.run(["git", "--git-dir=" + str(B), "branch", "dev", "main"], check=True)
    (B / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    assert bp(decide(world.U.path, "git --git-dir=%s update-ref HEAD %s" % (G.sh_quote(P(B)), sha))) is None


def test_a_worktree_git_does_not_list_is_unknown(world, tmp_path):
    R = world.R
    X, Y = tmp_path / "X", tmp_path / "Y"
    R.git("worktree", "add", "-q", "-b", "xb", str(X), "main")
    admin = Path(R.git("rev-parse", "--path-format=absolute", "--git-dir", cwd=X))
    import shutil
    shutil.rmtree(str(admin))
    Y.mkdir()
    (Y / ".git").write_bytes((world.W / ".git").read_bytes())
    for d in (X, Y):
        unknown_text(decide(R.path, "git -C %s commit -m x" % G.sh_quote(P(d))))
    UX = tmp_path / "UX"
    world.U.git("worktree", "add", "-q", "-b", "ux", str(UX), "main")
    shutil.rmtree(str(Path(world.U.git("rev-parse", "--path-format=absolute", "--git-dir", cwd=UX))))
    assert bp(decide(world.U.path, "git -C %s commit -m x" % G.sh_quote(P(UX)))) is None


def test_the_action_and_stored_fields(tmp_path, console):
    R = new_repo(tmp_path / "R")
    seen = []
    for args, action, stored, changed in ((["--branch", "main"], "set", "main", True), (["--branch", "MAIN"], "set", "main", False),
                                          (["--branch", "MAIN", "--release"], "release", "main", True), (["--branch", "none", "--release"], "release", None, False)):
        rc, v = jgp(R, "protect", *args)
        assert rc == 0 and (v["action"], v["stored"], v["changed"]) == (action, stored, changed), (args, v)
        seen.append((action, stored))
    assert [(x["action"], x["stored"]) for x in audit_lines(store_of(R)) if x["op"] == "protect"] == seen
