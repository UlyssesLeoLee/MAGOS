"""1.0.7 one-click approval in Claude Code: the USER_ONLY registry, magos.approval, the strict recognition of one direct invocation of this
guard, the ask or allow that hands the host the rewritten command, the one-time token and its store, its verification in the command, the
denial records of the override dialog, the tamper filter for the approval stores, and the texts that state the click."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import SH, G, ROOT, SCRIPT, Repo, Result, crashed, payload, retried, run
from test_hook import denied

WIN = sys.platform == "win32"
PS = shutil.which("powershell") if WIN else None
REAL_WHICH = shutil.which
BARE_PY = re.compile(r"(?:py|python|python3(?:\.\d+)?)(?:\.exe)?", re.I)


def P(path):
    return str(path).replace("\\", "/")


S = P(SCRIPT)
QS = "'%s'" % S  # S as one single-quoted bash word
PY = "'%s'" % P(sys.executable)  # the interpreter that runs the hook, named by its path: the form every shell runs without py on PATH
LAUNCHER = ROOT / "hooks" / "run-guard.cmd"
needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX sh")


@pytest.fixture(autouse=True)
def bare_py(monkeypatch):
    """On Windows the hook resolves a bare py / python with shutil.which in its own PATH: pin those names to an .exe, so that the hook-level
    tests do not depend on the runner's PATH.  Every other name goes to the real which."""
    if WIN:
        monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "C:/Windows/py.exe" if BARE_PY.fullmatch(name) else REAL_WHICH(name, *a, **k))


def body_of(cwd, cmd, tool="Bash", tid="toolu_1", sid="s-1", **ti):
    body = payload(tool, cmd, cwd, **ti)
    body.update({k: v for k, v in (("tool_use_id", tid), ("session_id", sid)) if v is not None})
    return body


def hook(cwd, cmd, tool="Bash", host="claude", lang="en", tid="toolu_1", sid="s-1", **ti):
    """The hook in process: exit 0, stderr empty, ASCII stdout."""
    r = run(["--lang", lang, "hook", host, "pre-tool"], stdin=json.dumps(body_of(cwd, cmd, tool, tid, sid, **ti)).encode("utf-8"))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


def hook_proc(body):
    """The hook as its own process, as a host starts it."""
    def once():
        p = subprocess.run([sys.executable, "-B", str(SCRIPT), "--lang", "en", "hook", "claude", "pre-tool"], input=json.dumps(body).encode("utf-8"),
                           capture_output=True, timeout=120)
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
    r = retried(once, lambda r: crashed(r.out + r.err, r.rc))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


def answer(r):
    """The ask or allow: one object whose only key is hookSpecificOutput, an object of exactly four keys."""
    obj = json.loads(r.out)
    assert list(obj) == ["hookSpecificOutput"], obj
    h = obj["hookSpecificOutput"]
    assert set(h) == {"hookEventName", "permissionDecision", "permissionDecisionReason", "updatedInput"} and h["hookEventName"] == "PreToolUse", h
    assert h["permissionDecision"] in ("ask", "allow"), h
    return h


def token_of(command):
    return re.search(r"--approval=([A-Za-z0-9_-]{43})'?$", command).group(1)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def common(repo):
    return Path(repo.git("rev-parse", "--path-format=absolute", "--git-common-dir"))


def approvals(repo):
    return common(repo) / "magos" / "approvals"


def record(root, token, suffix=".json"):
    return json.loads((Path(root) / (sha(token) + suffix)).read_text(encoding="utf-8"))


def audit_lines(path):
    log = Path(path) / "audit.log"
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def armed(repo):
    return (common(repo) / "magos" / "ARMED").exists()


def new_repo(path):
    r = Repo(path)
    r.path.mkdir(parents=True)
    r.git("init", "-q")
    r.commit("a.txt", "a\n", msg="init")
    return r


def no_file_holds(token, *roots):
    for root in roots:
        for f in Path(root).rglob("*"):
            assert not f.is_file() or token.encode("ascii") not in f.read_bytes(), f


def run_sh(cmd, cwd):
    """The rewritten command as the Bash tool runs it: sh -c, stdin closed, so that no console is present."""
    def once():
        p = subprocess.run([SH, "-c", cmd], cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
    return retried(once, lambda r: crashed(r.out + r.err, r.rc))


def run_ps(cmd, cwd):
    """The rewritten command as the PowerShell tool runs it, stdin closed."""
    p = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", cmd], cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


# ---- registry and levels (TC-500 to TC-502) ---------------------------------------------------------------------------------------------
def test_user_only_registry_drives_the_filter_and_the_parser(capsys):
    assert [(u.name, u.auto_safe, u.scope) for u in G.USER_ONLY] == [("override", False, "repo"), ("arm", True, "repo"), ("disarm", False, "repo"),
                                                                       ("install", True, "home")]
    assert G._USER_ONLY == ("override", "arm", "disarm", "install")
    need = {"override": ["--fingerprint", "0123456789ab", "--reason", "r"], "arm": [], "disarm": [], "install": ["--host", "codex"]}
    for u in G.USER_ONLY:
        for form in (["--approval=abc"], ["--approval", "abc"]):
            ns = G.build_parser("x").parse_args([u.name] + need[u.name] + form)
            assert ns.approval == "abc" and ns.repo == "x" and G.user_only_row(ns) == u, (u, form)
    for bad in (["list", "--approval=x"], ["arm", "--appr=x"], ["arm", "--approval-x=y"]):  # options are never abbreviated
        with pytest.raises(SystemExit) as err:
            G.build_parser("x").parse_args(bad)
        assert err.value.code == 2, bad
    capsys.readouterr()
    with pytest.raises(SystemExit):
        G.build_parser("x").parse_args(["arm", "-h"])
    shown = capsys.readouterr().out
    assert "--dry-run" in shown and "--approval" not in shown
    assert G.user_only_row(G.build_parser("x").parse_args(["list"])) is None
    assert G.parse_quiet(["arm"]).repo is None and G.parse_quiet(["arm", "--bogus"]) is None and G.parse_quiet(["arm", "-h"]) is None
    token = "Tk_-" + "x" * 39
    r = run(["list", "--approval=" + token])
    assert r.rc == 2 and token not in r.out + r.err and "<redacted>" in r.err  # a usage error never shows a token


def test_approval_level_is_read_from_the_local_config_only(repo, isolated_env, monkeypatch):
    def level():
        return G.approval_level(G.open_repo(str(repo.path)))
    assert level() == ("prompt", None)
    for value, want in (("terminal", "terminal"), ("prompt", "prompt"), ("auto-safe", "auto-safe"), ("Auto-Safe", "auto-safe"), (" prompt ", "prompt"),
                        ("full-auto", "terminal"), ("yes", "terminal"), ("", "terminal")):
        repo.git("config", "--local", "magos.approval", value)
        got, raw = level()
        assert got == want and raw == value.strip(), (value, got, raw)
    repo.git("config", "--local", "--unset-all", "magos.approval")
    with open(str(isolated_env / ".gitconfig"), "a", encoding="utf-8") as fh:
        fh.write("[magos]\n  approval = terminal\n")
    assert level() == ("prompt", None)  # the global file cannot set it
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "magos.approval")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "terminal")
    assert level() == ("prompt", None)  # nor the environment
    repo.git("config", "--local", "--add", "magos.approval", "terminal")
    repo.git("config", "--local", "--add", "magos.approval", "auto-safe")
    assert level() == ("auto-safe", "auto-safe")  # git's last value
    assert G.approval_level(None) == ("prompt", None)


def test_doctor_prints_the_approval_level(repo, guard, tmp_path):
    r = guard(repo, "doctor")
    assert r.rc == 0 and "\napproval: prompt (magos.approval unset): " in r.out, r.out
    repo.git("config", "magos.approval", "auto-safe")
    r = guard(repo, "doctor")
    assert r.rc == 0 and "\napproval: auto-safe (magos.approval auto-safe): " in r.out, r.out
    repo.git("config", "magos.approval", "bogus")
    r = guard(repo, "doctor")
    assert r.rc == 1 and ('approval: terminal (magos.approval is "bogus", which is not terminal, prompt or auto-safe, so the guard fails closed; '
                          "set it in your own terminal: git config --local magos.approval prompt)") in r.out.splitlines(), r.out
    outside = tmp_path / "outside"
    outside.mkdir()
    lines = guard(outside, "doctor").out.splitlines()
    k = next(i for i, line in enumerate(lines) if line.startswith("repository: none at"))
    assert lines[k + 1].startswith("approval: prompt (no repository): ")


# ---- the ask (TC-503 to TC-511) -----------------------------------------------------------------------------------------------------------
def test_claude_hook_asks_for_a_direct_invocation_in_bash(repo, isolated_env):
    r = hook(repo.path, "py -3 %s --lang en arm" % QS, timeout=5000, description="listing", tid="toolu_1", sid="s-1")
    h = answer(r)
    assert h["permissionDecision"] == "ask"
    ui = h["updatedInput"]
    assert set(ui) == {"command", "timeout", "description"} and ui["timeout"] == 5000 and ui["description"] == "MAGOS user-only command: arm (approval)"
    token = token_of(ui["command"])
    assert ui["command"] == G.approval_command("bash", ["py", "-3", S, "--lang", "en", "arm"], token)
    rec = record(approvals(repo), token)
    assert set(rec) == {"v", "sub", "argv", "where", "via", "created", "expires", "tool_use_id", "session_id", "command_sha256", "used"}
    assert rec["v"] == 1 and rec["sub"] == "arm" and rec["argv"] == ["--lang", "en", "arm"] and os.path.samefile(rec["where"], str(common(repo)))
    assert rec["via"] == "prompt" and rec["expires"] - rec["created"] == pytest.approx(120) and rec["tool_use_id"] == "toolu_1" and rec["session_id"] == "s-1"
    assert rec["command_sha256"] == sha(ui["command"]) and rec["used"] is False
    no_file_holds(token, common(repo) / "magos", isolated_env)  # the store holds the token's SHA-256 only


def test_claude_hook_asks_for_a_direct_invocation_in_powershell(repo, guard):
    assert guard(repo, "arm").rc == 0
    h = answer(hook(repo.path, 'py -3 "%s" disarm' % S, tool="PowerShell"))
    token = token_of(h["updatedInput"]["command"])
    assert h["permissionDecision"] == "ask" and h["updatedInput"]["command"] == "& 'py' '-3' '%s' 'disarm' '--approval=%s'" % (S, token)
    rec = record(approvals(repo), token)
    assert rec["sub"] == "disarm" and rec["argv"] == ["disarm"]


SHAPES = [  # (tool, command, cause): the real guard in every shape but one direct invocation
    ("Bash", "cd . && py -3 {qs} arm", "SHAPE"), ("Bash", "py -3 {qs} arm | cat", "SHAPE"), ("Bash", "py -3 {qs} arm 2>&1", "SHAPE"),
    ("Bash", "py -3 {qs} arm > out", "SHAPE"), ("Bash", "X=1 py -3 {qs} arm", "SHAPE"), ("Bash", "env py -3 {qs} arm", "SHAPE"),
    ("Bash", "bash -c 'py -3 {s} arm'", "SHAPE"), ("Bash", "(py -3 {qs} arm)", "SHAPE"), ("Bash", "py -3 {qs} arm &", "SHAPE"),
    ("Bash", "py -3 {qs} arm\necho x", "SHAPE"), ("Bash", 'py -3 {qs} override --fingerprint 0123456789ab --reason "$R"', "DYNAMIC"),
    ("Bash", "py -m x {qs} arm", "SHAPE"), ("Bash", "py -3 -W error {qs} arm", "SHAPE"), ("Bash", "{qs} arm", "SHAPE"), ("Bash", '"{launcher}" arm', "SHAPE"),
    ("Bash", "py -3 magos_guard.py arm", "SCRIPT"), ("Bash", "py -3 {changed} arm", "SCRIPT"), ("Bash", "py -3 {qs} arm --bogus", "ARGS"),
    ("PowerShell", "Start-Process py -ArgumentList '-3 {s} arm'", "SHAPE"), ("PowerShell", "py -3 '{s}' arm; echo x", "SHAPE"),
    ("Monitor", "py -3 {qs} arm", "TOOL"), ("mcp__x__run_in_terminal", "py -3 {qs} arm", "TOOL"),
]


def shape_denied(r, cause):
    reason = denied(r)
    assert reason and "would change the guard's own" in reason and "user-only" in reason, reason
    assert reason.splitlines()[-1] == "[APPROVAL_%s]" % cause, reason
    return reason


def test_every_other_shape_of_the_real_guard_stays_denied(repo, tmp_path):
    changed = tmp_path / "copy" / "magos_guard.py"
    changed.parent.mkdir()
    changed.write_bytes(SCRIPT.read_bytes() + b"#")
    fill = {"s": S, "qs": QS, "launcher": P(LAUNCHER), "changed": "'%s'" % P(changed)}
    for tool, cmd, cause in SHAPES:
        shape_denied(hook(repo.path, cmd.format(**fill), tool=tool), cause)
    repo.git("config", "magos.approval", "auto-safe")
    agent = tmp_path / "x" / "python.exe"  # an agent-written executable is never allowed, and never offered
    agent.parent.mkdir()
    agent.write_bytes(b"MZ")
    shape_denied(hook(repo.path, "'%s' %s arm" % (P(agent), QS)), "INTERPRETER")
    assert not approvals(repo).exists()


def test_arguments_the_tool_shell_cannot_pass_intact_are_refused(repo):
    lead = ["py", "-3", S]
    for w in ("", 'a"b', "C:\\x\\", "--%"):
        assert G.approval_intact(lead, ["--reason", w], "ps") == "APPROVAL_POWERSHELL", w
    for w in ("/tmp/x", "--repo=/c/x", "-I/usr", "x=/y"):
        assert G.approval_intact(lead, [w], "bash", win=True) == "APPROVAL_PATHCONV", w
    for w in ("C:/x", "a b /c/y", "it's"):
        assert G.approval_intact(lead, ["--reason", w], "bash", win=True) is None, w
    for w in ("", 'a"b', "C:\\x\\", "--%", "/tmp/x", "--repo=/c/x", "-I/usr", "x=/y", "C:/x", "a b /c/y", "it's"):
        assert G.approval_intact(lead, ["--reason", w], "bash", win=False) is None, w
    cmd = "py -3 %s override --fingerprint 0123456789ab --reason ''"
    shape_denied(hook(repo.path, cmd % ("'%s'" % S), tool="PowerShell"), "POWERSHELL")
    assert answer(hook(repo.path, cmd % QS))["permissionDecision"] == "ask"


def test_a_command_that_carries_approval_is_denied(repo):
    given = G.T("en", "approval_given", why=G._USER_MSG)
    for tool, cmd in (("Bash", "py -3 %s arm --approval=abc" % QS), ("Bash", "py -3 %s arm --approval abc" % QS),
                      ("Bash", "bash -c 'py -3 %s arm --appr\"\"oval=x'" % S), ("PowerShell", "py -3 '%s' disarm '--approval=x'" % S),
                      ("Bash", "py -3 %s -- arm --approval=x" % QS), ("Bash", "py -3 %s arm -- --approval=x" % QS)):
        assert denied(hook(repo.path, cmd, tool=tool)) == given, cmd
    protected = G.T("en", "protected", why=G._USER_MSG)
    for cmd in ("py -3 %s arm --approval=abc" % QS, ["py", "-3", S, "arm", "--approval=abc"]):
        assert denied(hook(repo.path, cmd, host="codex")) == protected, cmd
    assert denied(hook(repo.path, "py -3 %s arm --approval=abc" % QS, tool="terminal", host="hermes")) == protected
    assert not approvals(repo).exists()


def test_the_hook_issued_command_passes_its_own_rerun(repo):
    x = answer(hook(repo.path, "py -3 %s --lang en arm" % QS, tid="toolu_9"))["updatedInput"]["command"]
    live = approvals(repo) / (sha(token_of(x)) + ".json")
    assert hook(repo.path, x, tid="toolu_9").out.strip() == "{}"
    given = G.T("en", "approval_given", why=G._USER_MSG)
    for cmd, tid in ((x, "toolu_other"), (x + " ", "toolu_9"), (x, None)):
        assert denied(hook(repo.path, cmd, tid=tid)) == given, (cmd, tid)
    rec = json.loads(live.read_text(encoding="utf-8"))
    live.write_text(json.dumps(dict(rec, expires=time.time() - 1)), encoding="utf-8")
    assert denied(hook(repo.path, x, tid="toolu_9")) == given
    live.write_text(json.dumps(rec), encoding="utf-8")
    assert hook(repo.path, x, tid="toolu_9").out.strip() == "{}"
    live.rename(live.with_suffix(".used"))
    assert denied(hook(repo.path, x, tid="toolu_9")) == given


def test_level_terminal_and_unknown_values_keep_the_terminal(repo):
    for value in ("terminal", "nonsense"):
        repo.git("config", "magos.approval", value)
        assert denied(hook(repo.path, "py -3 %s --lang en arm" % QS)) == G.T("en", "protected_level", why=G._USER_MSG), value
    assert not approvals(repo).exists()


def test_auto_safe_allows_arm_and_install_and_asks_for_the_rest(repo, tmp_path, isolated_env):
    repo.git("config", "magos.approval", "auto-safe")
    home = isolated_env / ".magos" / "approvals"
    for args, want in (("arm", "allow"), ("install --host codex", "allow"), ("disarm", "ask"), ("override --fingerprint 0123456789ab --reason r", "ask"),
                       ("install --host codex --home '%s'" % P(tmp_path / "other"), "ask"), ("install --host codex --allow-downgrade", "ask")):
        h = answer(hook(repo.path, "py -3 %s --lang en %s" % (QS, args)))
        assert h["permissionDecision"] == want, args
        rec = record(home if args.startswith("install") else approvals(repo), token_of(h["updatedInput"]["command"]))
        assert rec["via"] == ("auto-safe" if want == "allow" else "prompt"), args
        assert h["permissionDecisionReason"].startswith("MAGOS: %s runs without a click" % args.split()[0]) == (want == "allow"), args
    h = answer(hook(repo.path, "py -3 %s arm" % QS, dangerouslyDisableSandbox=True))
    assert h["permissionDecision"] == "allow" and "dangerouslyDisableSandbox" not in h["updatedInput"]
    h = answer(hook(repo.path, "py -3 %s disarm" % QS, dangerouslyDisableSandbox=True))
    assert h["permissionDecision"] == "ask" and h["updatedInput"]["dangerouslyDisableSandbox"] is True


def test_codex_and_hermes_keep_todays_denial(repo):
    cmd = "py -3 %s --lang en arm" % QS
    assert answer(hook(repo.path, cmd))["permissionDecision"] == "ask"
    shutil.rmtree(str(approvals(repo)))
    protected = G.T("en", "protected", why=G._USER_MSG)
    assert protected == ("MAGOS DENIES: this command would change the guard's own claims/switches/hooks (override / arm / disarm / install are user-only). "
                         "Only the user may do this, in their own terminal.")
    for host, tool, c in (("codex", "Bash", cmd), ("codex", "Bash", ["py", "-3", S, "arm"]), ("hermes", "terminal", cmd)):
        assert denied(hook(repo.path, c, tool=tool, host=host)) == protected, (host, c)
    assert not approvals(repo).exists()


# ---- where the token lives (TC-512 to TC-514) -------------------------------------------------------------------------------------------
@needs_sh
def test_mint_and_verify_agree_after_a_cd_and_for_a_relative_guard(repo):
    copy = repo.path / "tools" / "magos_guard.py"
    copy.parent.mkdir()
    copy.write_bytes(SCRIPT.read_bytes())
    src = repo.path / "src"
    for extra in ("", "--repo .. ", "--repo '%s' " % P(repo.path)):
        x = answer(hook(src, "%s ../tools/magos_guard.py %s--lang en arm --dry-run" % (PY, extra)))["updatedInput"]["command"]
        live = approvals(repo) / (sha(token_of(x)) + ".json")
        assert P(copy) in x and live.is_file(), x
        r = run_sh(x, src)
        assert r.rc == 0 and "would write" in r.out, r
        assert not live.exists() and live.with_suffix(".used").is_file()
    assert not armed(repo)


@pytest.mark.skipif(PS is None, reason="Windows PowerShell")
def test_windows_path_spellings_share_one_store(repo):
    cwd = str(repo.path).lower()
    h = answer(hook(cwd, "& %s '%s' --repo '%s' --lang en arm --dry-run" % (PY, S, str(repo.path).upper()), tool="PowerShell"))
    rec = record(approvals(repo), token_of(h["updatedInput"]["command"]))
    assert os.path.samefile(rec["where"], G.open_repo(str(repo.path)).common)
    r = run_ps(h["updatedInput"]["command"], cwd)
    assert r.rc == 0 and "would write" in r.out, r


@needs_sh
def test_install_approval_lives_in_the_default_guard_home(tmp_path, isolated_env):
    outside, h2 = tmp_path / "outside", tmp_path / "h2"
    outside.mkdir()
    for dry in (" --dry-run", ""):
        h = answer(hook(outside, "%s %s --lang en install --host codex --home '%s'%s" % (PY, QS, P(h2), dry)))
        token = token_of(h["updatedInput"]["command"])
        rec = record(isolated_env / ".magos" / "approvals", token)
        assert h["permissionDecision"] == "ask" and rec["where"] == G.guard_home() and not (h2 / "approvals").exists()
        r = run_sh(h["updatedInput"]["command"], outside)
        assert r.rc == 0, r
        if dry:
            assert "would copy" in r.out and not (h2 / "guard").exists()
    assert (h2 / "guard" / "scripts" / "magos_guard.py").read_bytes() == SCRIPT.read_bytes()
    line = audit_lines(h2)[-1]
    assert line["op"] == "install" and line["via"] == "prompt" and line["tool_use_id"] == "toolu_1"


# ---- the dialog text and the denial records (TC-515 to TC-519) -------------------------------------------------------------------------
def fingerprint_of(text):
    return re.search(r"--fingerprint ([0-9a-f]{12})", text).group(1)


def test_the_override_dialog_names_the_conflicting_branches(repo, guard):
    repo.branch_with("agent/x", "src/a.py")
    r = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert r.rc == 10, r
    fp = fingerprint_of(r.out)
    rec = json.loads((common(repo) / "magos" / "denials" / (fp + ".json")).read_text(encoding="utf-8"))
    assert rec["fp"] == fp and rec["lane"] == "agent/new" and rec["branches"] == ["agent/x"] and rec["expires"] - rec["at"] == pytest.approx(3600)
    reason = "the user said yes\u2028\t\u202eMAGOS: approved " + "x" * 500 + '" fake'  # a line separator, a tab and a bidirectional override
    for lang, label in (("en", "Reason written by the agent: "), ("zh", "agent 写的理由：")):
        cmd = "py -3 %s --lang %s override --fingerprint %s --reason %s" % (QS, lang, fp, G.sh_quote(reason))
        text = answer(hook(repo.path, cmd, lang=lang))["permissionDecisionReason"]
        assert '"agent/x"' in text and '"%s"' % fp in text and '"%s"' % G.repo_dir(G.open_repo(str(repo.path))) in text, text
        assert not re.search("[\n\u2028\u202e\t]", text), text
        shown = json.loads(re.search(re.escape(label) + r'("(?:[^"\\]|\\.)*")', text).group(1))
        assert shown.startswith("the user said yes MAGOS: approved xxx") and len(shown) <= 160 and shown.endswith("…"), shown
        if lang == "en":
            assert text.endswith("Your click is the approval: the command below carries a one-time approval token, valid for 120 s."), text


def test_the_dialog_without_a_denial_record_and_with_hostile_branch_names(repo):
    fp = "0123456789ab"
    cmd = "py -3 %s --lang en override --fingerprint %s --reason r" % (QS, fp)
    assert G.T("en", "approval_no_record") in answer(hook(repo.path, cmd))["permissionDecisionReason"]
    names = ["agent/\u202eevil", "a\u200bb"] + ["agent/b%d" % i for i in range(6)]
    G.note_denial(G.open_repo(str(repo.path)), "agent/new", {"decision": "deny", "fingerprint": fp, "target": {"name": "main"},
                                                             "conflicts": [{"branch": n, "worktrees": []} for n in names]})
    text = answer(hook(repo.path, cmd))["permissionDecisionReason"]
    assert '"agent/ evil", "a b", "agent/b0", "agent/b1", "agent/b2", "agent/b3" +2 more' in text and not re.search("[\u202e\u200b]", text), text
    path = common(repo) / "magos" / "denials" / (fp + ".json")
    rec = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(rec, expires=time.time() - 1)), encoding="utf-8")
    assert G.T("en", "approval_no_record") in answer(hook(repo.path, cmd))["permissionDecisionReason"]


def test_denial_records_are_written_by_plan_and_the_hook_only(repo, guard, monkeypatch):
    repo.branch_with("agent/x", "src/a.py")
    denials = common(repo) / "magos" / "denials"
    assert guard(repo, "check", "--branch", "n", "--paths", "src/a.py").rc == 10
    assert not denials.exists()
    assert guard(repo, "plan", "--branch", "agent/new", "--paths", "docs/").rc == 0
    repo.branch_with("agent/y", "docs/d.md")
    reason = denied(hook(repo.path, "git worktree add ../w -b agent/new"))
    fp = fingerprint_of(reason)
    rec = json.loads((denials / (fp + ".json")).read_text(encoding="utf-8"))
    assert rec["lane"] == "agent/new" and rec["branches"] == ["agent/y"], rec
    shutil.rmtree(str(denials))
    real = G.write_atomic

    def failing(path, data, mode=None):
        if "denials" in str(path):
            raise OSError("the disk is full")
        return real(path, data, mode)
    monkeypatch.setattr(G, "write_atomic", failing)
    assert denied(hook(repo.path, "git worktree add ../w -b agent/new")) == reason  # a failed record changes no verdict and no message
    assert not (denials / (fp + ".json")).exists()


def test_a_mint_that_cannot_write_fails_closed(repo):
    (common(repo) / "magos").mkdir(parents=True, exist_ok=True)
    approvals(repo).write_text("a file, not the store\n", encoding="utf-8")
    head, tail = G.T("en", "approval_unrecorded", why=G._USER_MSG, err="\0").split("\0")
    reason = denied(hook(repo.path, "py -3 %s arm" % QS))
    assert reason.startswith(head) and reason.endswith(tail) and "Error" in reason[len(head):-len(tail)], reason


def test_stale_records_are_pruned_only_when_a_token_is_minted(repo):
    root, den = approvals(repo), common(repo) / "magos" / "denials"
    root.mkdir(parents=True)
    den.mkdir()
    now = time.time()

    def put(path, expires=None, raw=None, age=None):
        path.write_bytes(raw if raw is not None else json.dumps({"v": 1, "expires": expires}).encode("utf-8"))
        if age is not None:
            os.utime(str(path), (now - age, now - age))
        return path
    gone = [put(root / (sha("a") + ".json"), now - 700), put(root / (sha("b") + ".used"), now - 700), put(root / (sha("f") + ".json"), raw=b"\xff\xfe{", age=1000),
            put(root / "x.json.1.tmp", raw=b"{", age=1000), put(den / "0123456789ab.json", now - 1)]
    stay = [put(root / (sha("c") + ".json"), now - 100), put(root / (sha("d") + ".json"), now + 100), put(root / "notes.txt", raw=b"mine")]
    assert hook(repo.path, "ls").out.strip() == "{}"
    assert all(p.exists() for p in gone + stay)  # a hook call that mints nothing reads no store
    token = token_of(answer(hook(repo.path, "py -3 %s arm" % QS))["updatedInput"]["command"])
    assert not [p for p in gone if p.exists()] and all(p.exists() for p in stay)
    assert sorted(os.listdir(str(root))) == sorted([p.name for p in stay if p.parent == root] + [sha(token) + ".json"])


# ---- end to end (TC-520 to TC-523) -------------------------------------------------------------------------------------------------------
@needs_sh
def test_end_to_end_bash_prompt_arm(repo, isolated_env):
    h = answer(hook_proc(body_of(repo.path, "%s %s --lang en arm" % (PY, QS), tid="toolu_e2e")))
    x, token = h["updatedInput"]["command"], token_of(h["updatedInput"]["command"])
    first = run_sh(x, repo.path)
    assert h["permissionDecision"] == "ask" and first.rc == 0, first
    assert armed(repo) and (common(repo) / "hooks" / "reference-transaction").is_file()
    line = audit_lines(common(repo) / "magos")[-1]
    assert line["op"] == "arm" and line["via"] == "prompt" and line["tool_use_id"] == "toolu_e2e", line
    store = {p: p.read_bytes() for p in (common(repo) / "magos").rglob("*") if p.is_file()}
    second = run_sh(x, repo.path)
    assert second.rc == 27 and G.T("en", "approval_used") in second.err, second
    assert {p: p.read_bytes() for p in (common(repo) / "magos").rglob("*") if p.is_file()} == store  # nothing changed, no audit line added
    assert token not in first.out + first.err + second.out + second.err
    no_file_holds(token, common(repo) / "magos", isolated_env)


@pytest.mark.skipif(PS is None, reason="Windows PowerShell")
def test_end_to_end_powershell_prompt_disarm(repo, guard):
    assert guard(repo, "arm").rc == 0
    h = answer(hook_proc(body_of(repo.path, "& %s '%s' --lang en disarm" % (PY, S), tool="PowerShell", tid="toolu_ps")))
    r = run_ps(h["updatedInput"]["command"], repo.path)
    assert h["permissionDecision"] == "ask" and r.rc == 0, r
    line = audit_lines(common(repo) / "magos")[-1]
    assert not armed(repo) and line["op"] == "disarm" and line["via"] == "prompt" and line["tool_use_id"] == "toolu_ps", line


@needs_sh
def test_end_to_end_override_by_click_then_replan(repo, guard):
    repo.branch_with("agent/x", "src/a.py")
    r = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert r.rc == 10, r
    fp = fingerprint_of(r.out)
    h = answer(hook_proc(body_of(repo.path, "%s %s --lang en override --fingerprint %s --reason 'the user agreed'" % (PY, QS, fp), tid="toolu_ov")))
    done = run_sh(h["updatedInput"]["command"], repo.path)
    assert h["permissionDecision"] == "ask" and done.rc == 0, done
    rec = json.loads((common(repo) / "magos" / "override" / (fp + ".json")).read_text(encoding="utf-8"))
    assert rec["reason"] == "the user agreed" and rec["reason_by"] == "agent" and rec["via"] == "prompt", rec
    line = audit_lines(common(repo) / "magos")[-1]
    assert line["op"] == "override" and line["reason_by"] == "agent" and line["via"] == "prompt" and line["tool_use_id"] == "toolu_ov", line
    r = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py", "--json")
    assert r.rc == 0 and json.loads(r.out)["code"] == "OVERRIDDEN", r


@needs_sh
def test_end_to_end_auto_safe_install_runs_without_a_click(repo, isolated_env):
    repo.git("config", "magos.approval", "auto-safe")
    h = answer(hook_proc(body_of(repo.path, "%s %s --lang en install --host codex" % (PY, QS), tid="toolu_in")))
    r = run_sh(h["updatedInput"]["command"], repo.path)
    assert h["permissionDecision"] == "allow" and r.rc == 0, r
    home = isolated_env / ".magos"
    assert (home / "guard" / "scripts" / "magos_guard.py").read_bytes() == SCRIPT.read_bytes()
    line = audit_lines(home)[-1]
    assert line["op"] == "install" and line["via"] == "auto-safe" and line["tool_use_id"] == "toolu_in", line


# ---- the verification in the command (TC-524 to TC-528) ---------------------------------------------------------------------------------
def test_the_terminal_path_records_via_terminal(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: True)
    base = ["--repo", str(repo.path), "--lang", "en"]
    assert run(base + ["arm"]).rc == 0 and run(base + ["disarm"]).rc == 0
    lines = audit_lines(common(repo) / "magos")[-2:]
    assert [(x["op"], x["via"], "tool_use_id" in x) for x in lines] == [("arm", "terminal", False), ("disarm", "terminal", False)], lines
    home = tmp_path / "h"
    assert run(base + ["install", "--host", "codex", "--home", str(home)]).rc == 0
    assert audit_lines(home)[-1]["via"] == "terminal"
    fp = "0123456789ab"
    r = run(base + ["override", "--fingerprint", fp, "--reason", "typed by the user"], stdin=(fp + "\n").encode("ascii"))
    assert r.rc == 0, r
    rec = json.loads((common(repo) / "magos" / "override" / (fp + ".json")).read_text(encoding="utf-8"))
    line = audit_lines(common(repo) / "magos")[-1]
    assert (rec["reason_by"], rec["via"]) == ("user", "terminal") and (line["op"], line["reason_by"], line["via"]) == ("override", "user", "terminal")


def test_token_errors_name_their_cause_and_exit_distinctly(repo, tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(G, "user_console", lambda: asked.append("console") or False)
    monkeypatch.setattr(G, "challenge", lambda *a: asked.append("challenge") or False)
    other = new_repo(tmp_path / "other")
    audit0 = len(audit_lines(common(repo) / "magos"))
    tokens = []

    def mint():  # every attempt consumes its token, a failed one too: each case gets a fresh one
        tokens.append(token_of(answer(hook(repo.path, "py -3 %s --lang en arm" % QS))["updatedInput"]["command"]))
        return tokens[-1]

    def refused(argv, code, key, cwd=repo.path, **kw):
        r = run(argv, cwd=cwd)
        assert r.rc == code and G.T("en", key, **kw) in r.err, (argv, r)
        assert not armed(repo) and not armed(other) and len(audit_lines(common(repo) / "magos")) == audit0
        assert not [t for t in tokens if t in r.out + r.err]
    arm = ["--lang", "en", "arm"]
    refused(arm + ["--approval=short"], 25, "approval_unknown")
    refused(arm + ["--approval=" + "Z" * 43], 25, "approval_unknown")
    live = approvals(repo) / (sha(mint()) + ".json")
    live.write_text(json.dumps(dict(json.loads(live.read_text(encoding="utf-8")), expires=time.time() - 1)), encoding="utf-8")
    refused(arm + ["--approval=" + tokens[-1]], 26, "approval_expired")
    refused(arm + ["--dry-run", "--approval=" + mint()], 28, "approval_mismatch", what="set of arguments")
    refused(["--lang", "en", "disarm", "--approval=" + mint()], 28, "approval_mismatch", what="subcommand")
    refused(["--repo", str(other.path)] + arm + ["--approval=" + mint()], 25, "approval_unknown")
    t = mint()
    (common(other) / "magos" / "approvals").mkdir(parents=True)
    shutil.copy(str(approvals(repo) / (sha(t) + ".json")), str(common(other) / "magos" / "approvals"))
    refused(["--repo", str(other.path)] + arm + ["--approval=" + t], 28, "approval_mismatch", what="repository")
    t = mint()
    refused(arm + ["--approval=" + t, "--approval=" + t], 28, "approval_mismatch", what="set of arguments")
    t = mint()
    r = run(arm + ["--approval=" + t], cwd=repo.path)
    assert r.rc == 0 and armed(repo) and audit_lines(common(repo) / "magos")[-1]["via"] == "prompt", r
    n = len(audit_lines(common(repo) / "magos"))
    r = run(arm + ["--approval=" + t], cwd=repo.path)
    assert r.rc == 27 and G.T("en", "approval_used") in r.err and len(audit_lines(common(repo) / "magos")) == n, r
    assert asked == [] and t not in r.out + r.err


@needs_sh
def test_two_uses_at_once_have_one_winner(repo):
    x = answer(hook(repo.path, "%s %s --lang en arm" % (PY, QS)))["updatedInput"]["command"]
    procs = [subprocess.Popen([SH, "-c", x], cwd=str(repo.path), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert sorted(p.returncode for p in procs) == [0, 27], outs
    assert [x["op"] for x in audit_lines(common(repo) / "magos")].count("arm") == 1


@needs_sh
def test_dry_run_with_a_token_consumes_it_and_writes_nothing_else(repo):
    x = answer(hook(repo.path, "%s %s --lang en arm --dry-run" % (PY, QS)))["updatedInput"]["command"]
    used = approvals(repo) / (sha(token_of(x)) + ".used")
    r = run_sh(x, repo.path)
    assert r.rc == 0 and "would write" in r.out and not armed(repo), r
    assert [p for p in (common(repo) / "magos").rglob("*") if p.is_file()] == [used]
    r = run_sh(x, repo.path)
    assert r.rc == 27, r


def test_the_console_path_stays_valid_at_every_level(repo, monkeypatch):
    base = ["--repo", str(repo.path), "--lang", "en"]
    for value in (None, "terminal", "prompt", "auto-safe", "bogus"):
        if value:
            repo.git("config", "magos.approval", value)
        monkeypatch.setattr(G, "user_console", lambda: True)
        for sub in ("arm", "disarm"):
            assert run(base + [sub]).rc == 0, (value, sub)
            line = audit_lines(common(repo) / "magos")[-1]
            assert (line["op"], line["via"], "tool_use_id" in line) == (sub, "terminal", False), (value, line)
        monkeypatch.setattr(G, "user_console", lambda: False)
        r = run(base + ["arm"])
        assert r.rc == 17 and "real terminal" in r.err and "Claude Code" in r.err and not armed(repo), (value, r)


# ---- tamper filter, quoting, the tool input, interpreters, texts (TC-529 to TC-536) ------------------------------------------------------
def test_writes_into_an_approval_store_are_always_denied(repo, isolated_env):
    for tool, cmd in (("Bash", "echo x > .git/magos/approvals/a.json"), ("Bash", "rm .git/magos/approvals/a.json"), ("Bash", "cp f .git/magos/approvals/"),
                      ("PowerShell", "Set-Content %s/magos/approvals/a.json x" % P(common(repo))), ("Bash", "rm %s/approvals/x.json" % P(isolated_env / ".magos"))):
        reason = denied(hook(repo.path, cmd, tool=tool))
        assert reason and "would change the guard's own" in reason and G._APPROVAL_MSG in reason, (cmd, reason)
    for cmd in ("cat .git/magos/approvals/a.json", "echo x > .git/magos/ARMED"):  # reading is free; ARMED is guarded state (no claim, not armed)
        assert hook(repo.path, cmd).out.strip() == "{}", cmd
    assert G.protected("tee .git/magos/approvals/x") == ("always", G._APPROVAL_MSG)


@needs_sh
def test_rewritten_commands_pass_every_word_intact(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    token = "A" * 43
    for value in ("a b", "it's", "$HOME `x` !x *", "中文 テスト", "", 'a"b', "~/x", "-x"):
        words = [P(sys.executable), P(probe), "--reason", value]
        want = ["--reason", value, "--approval=" + token]
        cmd = G.approval_command("bash", words, token)
        assert [w for w, _d in G._lex(cmd, "bash")[0]] == words + want[2:], cmd
        r = run_sh(cmd, tmp_path)
        assert r.rc == 0 and json.loads(r.out) == want, (cmd, r)
        if PS and G.approval_intact(words[:2], want[:2], "ps") is None:
            r = run_ps(G.approval_command("ps", words, token), tmp_path)
            assert r.rc == 0 and json.loads(r.out) == want, (value, r)


def test_updated_input_keeps_the_tool_input(repo):
    extra = {"timeout": 60000, "run_in_background": False, "description": "harmless listing", "x": {"k": [1]}, "dangerouslyDisableSandbox": True}
    kept = {k: v for k, v in extra.items() if k != "description"}
    ui = answer(hook(repo.path, "py -3 %s arm" % QS, **extra))["updatedInput"]
    assert {k: v for k, v in ui.items() if k not in ("command", "description")} == kept and ui["description"] == "MAGOS user-only command: arm (approval)"
    repo.git("config", "magos.approval", "auto-safe")
    h = answer(hook(repo.path, "py -3 %s arm" % QS, **extra))
    kept.pop("dangerouslyDisableSandbox")
    assert h["permissionDecision"] == "allow" and {k: v for k, v in h["updatedInput"].items() if k not in ("command", "description")} == kept


def test_interpreter_forms_of_a_direct_invocation(repo, tmp_path, monkeypatch):
    def inv(cmd):
        return G.approval_invocation({"tool_name": "Bash", "tool_input": {"command": cmd % QS}}, str(repo.path))
    for cmd in ("py %s arm", "py -3 %s arm", "py -3.14 %s arm", "py -3-64 %s arm", "python %s arm", "python3 %s arm", "python3.12 %s arm", "py.exe %s arm",
                PY + " %s arm", "py -3 -B -X utf8 %s arm", "py -I -E -u -s %s arm", "python -Xutf8 %s arm"):
        got, cause = inv(cmd)
        assert cause is None and got["words"][-1] == S and got["args"] == ["arm"], (cmd, cause)
    for cmd in ("pythonw %s arm", "python.cmd %s arm", "py -m x %s arm", "python -c x %s arm", "python -W error %s arm", "node %s arm", "%s arm",
                "py -3 -X dev %s arm"):
        assert inv(cmd) == (None, "APPROVAL_SHAPE"), cmd
    agent = tmp_path / "x" / "python.exe"
    agent.parent.mkdir()
    agent.write_bytes(b"MZ")
    for cmd in ("'%s' %%s arm" % P(agent), "~/py %s arm"):
        assert inv(cmd) == (None, "APPROVAL_INTERPRETER"), cmd
    if WIN:  # a .bat or .cmd shim would hand the quoted arguments to cmd.exe
        monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "C:/x/python.bat")
        assert inv("python %s arm") == (None, "APPROVAL_INTERPRETER")


NEW_TEXTS = {  # the messages of the approval path and the placeholders the code passes
    "protected_shape": {"why", "cmd"}, "protected_level": {"why"}, "approval_given": {"why"}, "approval_unrecorded": {"why", "err"},
    "approval_ask": {"sub", "what"}, "approval_auto": {"sub", "what"}, "approval_what_override": {"fp", "repo", "branches", "reason"},
    "approval_what_arm": {"repo", "dry"}, "approval_what_disarm": {"repo", "dry"}, "approval_what_install": {"home", "host", "dry"}, "approval_dry": set(),
    "approval_no_record": set(), "approval_desc": {"sub"}, "approval_unknown": set(), "approval_expired": set(), "approval_used": set(),
    "approval_mismatch": {"what"}, "what_sub": set(), "what_args": set(), "what_repo": set(), "what_home": set(),
}


def test_messages_of_the_approval_path_exist_in_both_languages():
    for key, names in NEW_TEXTS.items():
        zh, en = G.M[key]
        for text in (zh, en):
            assert set(re.findall(r"{(\w+)}", text)) == names, key
            assert not re.search(r"[{}]", text.format(**{n: "<%s>" % n for n in names})), key
        assert zh != en, key


def test_denial_and_doctor_texts_state_the_click(repo, guard, tmp_path):
    for lang, dialog, own, terminal in (("en", "dialog", "would change the guard's own", "real terminal"), ("zh", "对话框", "守卫自己的", "真实终端")):
        options = G.T(lang, "options", target="main", cmd="G", fp="f")
        assert "Claude Code" in options and dialog in options and re.search(r"magos\.approval (?:为 )?terminal", options) and "override --fingerprint f" in options
        for key, needle in (("protected_shape", dialog), ("protected_level", "magos.approval")):
            text = G.T(lang, key, why=G._USER_MSG, cmd="G")
            assert own in text and "user-only" in text and needle in text, (lang, key)
        need = G.T(lang, "need_tty")
        assert terminal in need and "Claude Code" in need, need
    assert G.T("en", "protected", why="W") == "MAGOS DENIES: this command would change the guard's own claims/switches/hooks (W). Only the user may do this, in their own terminal."
    assert G.T("zh", "protected", why="W") == "MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（W）。这类操作只能由用户在自己的终端里执行。"
    assert guard(repo, "arm").rc == 0
    (common(repo) / "magos" / "guard").write_text(G.guard_cmd(str(tmp_path / "gone" / "magos_guard.py")) + "\n", encoding="utf-8")
    r = guard(repo, "doctor")
    assert r.rc == 1 and "re-arm (%s): %s arm" % (G._USER_RUN, G.guard_cmd()) in r.out, r.out


def test_the_level_follows_the_repository_the_command_names(repo, tmp_path):
    b = new_repo(tmp_path / "b")
    repo.git("config", "magos.approval", "terminal")
    h = answer(hook(repo.path, "py -3 %s --repo '%s' --lang en arm" % (QS, P(b.path))))
    rec = record(approvals(b), token_of(h["updatedInput"]["command"]))
    assert h["permissionDecision"] == "ask" and os.path.samefile(rec["where"], str(common(b))) and not approvals(repo).exists()
    assert denied(hook(b.path, "py -3 %s --repo '%s' --lang en arm" % (QS, P(repo.path)))) == G.T("en", "protected_level", why=G._USER_MSG)


def test_an_older_or_changed_guard_copy_is_not_offered(repo, isolated_env):
    data = SCRIPT.read_bytes()
    line = ('GUARD_VERSION = "%s"' % G.GUARD_VERSION).encode("ascii")
    parts = G.GUARD_VERSION.split(".")
    older = ".".join(parts[:-1] + [str(int(parts[-1]) - 1)]) if int(parts[-1]) else "0.9"
    assert line in data
    copy = isolated_env / ".magos" / "guard" / "scripts" / "magos_guard.py"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(data.replace(line, ('GUARD_VERSION = "%s"' % older).encode("ascii")))
    shape_denied(hook(repo.path, "py -3 '%s' arm" % P(copy)), "SCRIPT")
    copy.write_bytes(data)
    assert answer(hook(repo.path, "py -3 '%s' arm" % P(copy)))["permissionDecision"] == "ask"
