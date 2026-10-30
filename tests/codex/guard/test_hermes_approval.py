"""1.0.8 approval in Hermes, the guard side: `hook hermes pre-tool --hermes-gate <gate>` (the hook the MAGOS Hermes plugin runs) answers one
direct invocation of this guard with the modify and approve of Hermes approval, reads the Hermes config, keeps the directory of the call,
records route hermes, and the Hermes entry under hooks: keeps the 1.0.7 denial; install --host hermes and doctor name the route
(TC-650 to TC-667, TC-672 to TC-676, TC-678, TC-681, TC-698, TC-699, TC-723 to TC-725).  The plugin's own callbacks are tested in
test_hermes_plugin.py."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import SH, G, ROOT, SCRIPT, Result, crashed, retried, run
from test_approval import LAUNCHER, P, PY, QS, S, approvals, armed, audit_lines, common, needs_sh, run_sh, sha
from test_hook import denied

WIN = sys.platform == "win32"
EXE = P(sys.executable)
OLD = "1.0.6"  # a guard version older than this one


@pytest.fixture(autouse=True)
def hermes_env(monkeypatch, isolated_env):
    for key in ("HERMES_YOLO_MODE", "HERMES_PLUGIN_HOST_PROCESS", "MAGOS_GUARD"):
        monkeypatch.delenv(key, raising=False)
    return isolated_env / ".hermes"


@pytest.fixture
def elsewhere(tmp_path):
    """The payload's cwd: the directory of the Hermes process, outside every repository of the test."""
    d = tmp_path / "hermes-process"
    d.mkdir()
    return d


def hpayload(cmd, cwd, tid="call_1", extra_tid="call_1", tool="terminal", **ti):
    body = {"hook_event_name": "pre_tool_call", "tool_name": tool, "tool_input": dict({"command": cmd}, **ti), "session_id": "s-1",
            "cwd": str(cwd), "extra": {"turn_id": "t-1"}}
    if tid is not None:
        body["tool_use_id"] = tid
    if extra_tid is not None:
        body["extra"]["tool_call_id"] = extra_tid
    return body


def H(cmd, cwd, gate="ask", lang="en", **kw):
    """The Hermes hook in process: with a gate value as the plugin runs it, without one as the entry under hooks: runs it."""
    r = run(["--lang", lang, "hook", "hermes", "pre-tool"] + (["--hermes-gate", gate] if gate else []),
            stdin=json.dumps(hpayload(cmd, cwd, **kw)).encode("utf-8"))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


def asked(r, approve=True):
    """The modify (and approve) object -> (command, message, rule_key); exactly these keys."""
    obj = json.loads(r.out)
    assert list(obj) == ["hermesApproval"], obj
    h = obj["hermesApproval"]
    assert set(h) == ({"modify", "approve"} if approve else {"modify"}), h
    assert set(h["modify"]) == {"command"}
    if not approve:
        return h["modify"]["command"], None, None
    assert set(h["approve"]) == {"message", "rule_key"}, h
    return h["modify"]["command"], h["approve"]["message"], h["approve"]["rule_key"]


def token_in(command):
    return re.search(r"--approval=([A-Za-z0-9_-]{43})$", command).group(1)


def rec_of(root, command, suffix=".json"):
    return json.loads((Path(root) / (sha(token_in(command)) + suffix)).read_text(encoding="utf-8"))


def q(path):
    return G.sh_quote(P(path))


def arm_cmd(repo, *rest):
    return " ".join([PY, QS, "--repo", q(repo.path)] + list(rest or ["--lang", "en", "arm"]))


def shape(r, cause):
    reason = denied(r)
    head = G.T("en", "protected_shape_hermes", why=G._USER_MSG, cmd=G.guard_cmd())
    assert reason == head + "\n[APPROVAL_%s]" % cause, reason
    return reason


def noask(how, **kw):
    return G.T("en", "protected_hermes_noask", why=G._USER_MSG, how=G.T("en", how, **kw))


# ---- the option and the two routes (TC-650 to TC-653) --------------------------------------------------------------------------------------
def test_the_gate_option_belongs_to_the_hermes_hook_only():
    for gate in G.HERMES_GATES:
        assert G.build_parser("x").parse_args(["hook", "hermes", "pre-tool", "--hermes-gate", gate]).hermes_gate == gate
    assert G.build_parser("x").parse_args(["hook", "hermes", "pre-tool"]).hermes_gate is None
    for args in (["hook", "claude", "pre-tool", "--hermes-gate", "ask"], ["hook", "codex", "pre-tool", "--hermes-gate", "ask"],
                 ["hook", "hermes", "pre-tool", "--hermes-gate", "maybe"]):
        r = run(args, stdin=b"{}")
        assert r.rc == 1 and r.out == "", (args, r)
    r = run(["hook", "-h"])
    assert r.rc == 0 and "pre-tool" in r.out and "--hermes-gate" not in r.out, r


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_hooks_entry_route_keeps_todays_denial(repo, elsewhere, monkeypatch, platform):
    protected = G.T("en", "protected", why=G._USER_MSG)
    assert denied(H(arm_cmd(repo), elsewhere, gate=None)) == protected
    assert denied(H(arm_cmd(repo), elsewhere, gate=None, tid=None, extra_tid="call_7")) == protected  # the native shell-hook payload
    assert not approvals(repo).exists()
    monkeypatch.setattr(sys, "platform", platform)
    snippet = G.host_snippet("hermes", "/h")
    command = "'\"/h/guard/hooks/run-guard.cmd\" hook hermes pre-tool'" if platform == "win32" else "'sh ''/h/guard/hooks/run-guard.cmd'' hook hermes pre-tool'"
    assert snippet == ('hooks:\n  pre_tool_call:\n    - matcher: "terminal"\n      command: %s\n      timeout: 25\n      fail_closed: true\n' % command)


def test_a_direct_invocation_gets_modify_and_approve(repo, elsewhere):
    r = H(arm_cmd(repo), elsewhere)
    command, message, key = asked(r)
    token = token_in(command)
    assert command == G.approval_command("bash", [EXE, S, "--repo", P(repo.path), "--lang", "en", "arm"], token)
    rec = rec_of(approvals(repo), command)
    assert set(rec) == {"v", "sub", "argv", "where", "via", "created", "expires", "tool_use_id", "session_id", "command_sha256", "used", "route"}
    assert rec["v"] == 1 and rec["sub"] == "arm" and rec["argv"] == ["--repo", P(repo.path), "--lang", "en", "arm"]
    assert os.path.samefile(rec["where"], str(common(repo))) and rec["via"] == "prompt" and rec["route"] == "hermes"
    assert rec["tool_use_id"] == "call_1" and rec["session_id"] == "s-1" and rec["command_sha256"] == sha(command) and rec["used"] is False
    assert rec["expires"] - rec["created"] == pytest.approx(330)
    assert message.startswith("MAGOS: approve the user-only guard command arm?") and json.dumps(P(repo.path)) in message and "330 s" in message
    assert token not in message and "--approval" not in message
    assert re.fullmatch(r"magos:arm:[0-9a-f]{32}", key), key


def test_every_request_has_its_own_rule_key_and_token(repo, elsewhere):
    first, second = (asked(H(arm_cmd(repo), elsewhere)) for _ in range(2))
    assert token_in(first[0]) != token_in(second[0]) and first[2] != second[2]
    third = asked(H(arm_cmd(repo), elsewhere, tid=None, extra_tid="call_9"))
    fourth = asked(H(arm_cmd(repo), elsewhere, tid=None, extra_tid=None))
    assert rec_of(approvals(repo), third[0])["tool_use_id"] == "call_9" and rec_of(approvals(repo), fourth[0])["tool_use_id"] is None
    for _c, _m, key in (first, second, third, fourth):
        assert key != "terminal" and not re.fullmatch(r"terminal:[0-9a-f]{12}", key)


# ---- levels and Hermes's own gate (TC-654 to TC-659) ---------------------------------------------------------------------------------------
def test_auto_safe_hands_over_the_whitelist_without_a_question(repo, elsewhere, tmp_path, isolated_env):
    repo.git("config", "magos.approval", "auto-safe")
    home_store = isolated_env / ".magos" / "approvals"
    other = P(tmp_path / "other-home")
    for cmd, workdir, root, approve in (
            (arm_cmd(repo), None, approvals(repo), False),
            (arm_cmd(repo, "--lang", "en", "disarm"), None, approvals(repo), True),
            ("%s %s install --host hermes" % (PY, QS), P(repo.path), home_store, False),
            ("%s %s install --host hermes --home %s" % (PY, QS, G.sh_quote(other)), P(repo.path), home_store, True),
            ("%s %s install --host hermes --allow-downgrade" % (PY, QS), P(repo.path), home_store, True)):
        r = H(cmd, elsewhere, **({"workdir": workdir} if workdir else {}))
        command, message, _key = asked(r, approve)
        rec = rec_of(root, command)
        assert rec["via"] == ("prompt" if approve else "auto-safe") and rec["route"] == "hermes", (cmd, rec)
        assert rec["expires"] - rec["created"] == pytest.approx(330 if approve else 120), (cmd, rec)
    command, _m, _k = asked(H(arm_cmd(repo), elsewhere, gate="bypass"), approve=False)
    assert rec_of(approvals(repo), command)["via"] == "auto-safe"


def test_level_terminal_keeps_the_terminal_in_hermes(repo, elsewhere):
    for value in ("terminal", "bogus"):
        repo.git("config", "magos.approval", value)
        assert denied(H(arm_cmd(repo), elsewhere)) == G.T("en", "protected_level", why=G._USER_MSG)
    assert not approvals(repo).exists()


def test_a_gate_that_would_not_ask_keeps_the_terminal(repo, elsewhere):
    assert denied(H(arm_cmd(repo), elsewhere, gate="bypass")) == noask("hermes_how_session")
    assert denied(H(arm_cmd(repo), elsewhere, gate="absent")) == noask("hermes_how_gate")
    assert not approvals(repo).exists()


def test_hermes_yolo_mode_in_the_environment_is_seen(repo, elsewhere, monkeypatch):
    for value in ("1", "true", " YES ", "on"):
        monkeypatch.setenv("HERMES_YOLO_MODE", value)
        assert denied(H(arm_cmd(repo), elsewhere)) == noask("hermes_how_env"), value
    for value in ("0", "no", ""):
        monkeypatch.setenv("HERMES_YOLO_MODE", value)
        asked(H(arm_cmd(repo), elsewhere))


OFF = ["approvals:\n  mode: off\n", 'approvals:\n  mode: "off"\n', "approvals:\n  mode: OFF\n", "approvals:\n  mode: oFf\n", "approvals:\n  mode: false\n",
       "approvals:\n  mode: FALSE\n", "approvals:\n  mode: NO\n", "---\napprovals:\n  mode: off\n", "approvals:\n  mode: n\n",
       "approvals:\n  mode: nO\n", "approvals:\n  mode: fAlse\n",  # strings to PyYAML (Hermes: manual): the guard is stricter
       "approvals:\n  mode: No\n", "approvals:\n  mode: off  # x\n", "﻿approvals:\r\n  mode: off\r\n"]
ASK = ["approvals:\n  mode: manual\n", "approvals:\n  mode: smart\n", "approvals:\n  mode: 'manual' # off\n", 'approvals:\n  mode: "on"\n',
       "approvals:\n  other:\n    mode: off\n", None]
UNREADABLE = ["approvals: {mode: off}\n", "approvals:\n  mode: manual\nx: 1\napprovals:\n  mode: off\n", "approvals:\n  mode: *a\n",
              'approvals:\n  mode: "a\\"b"\n', "approvals:\n\tmode: off\n", "directory",
              json.dumps({"approvals": {"mode": "off", "timeout": 60}}), json.dumps({"approvals": {"mode": "off"}}, indent=1),
              "? approvals\n: mode: off\n", "base: &b\n  approvals:\n    mode: off\n<<: *b\n", "- approvals\n", "--- {approvals: {mode: off}}\n"]


def put_config(hh, text):
    path = Path(hh) / "config.yaml"
    if path.is_dir():
        path.rmdir()
    elif path.exists():
        path.unlink()
    Path(hh).mkdir(parents=True, exist_ok=True)
    if text == "directory":
        path.mkdir()
    elif text is not None:
        path.write_bytes(text.encode("utf-8"))
    return P(path)


def test_the_hermes_config_reader_fails_closed(repo, elsewhere, hermes_env):
    for text in OFF:
        path = put_config(hermes_env, text)
        s = G.hermes_settings()
        assert s["error"] is None and G.hermes_mode_off(s), (text, s)
        assert denied(H(arm_cmd(repo), elsewhere)) == noask("hermes_how_mode", path=G._dialog(path, 200), value=G._dialog(s["mode"], 40)), text
    for text in ASK:
        put_config(hermes_env, text)
        s = G.hermes_settings()
        assert s["error"] is None and not G.hermes_mode_off(s), (text, s)
        asked(H(arm_cmd(repo), elsewhere))
    for text in UNREADABLE:
        path = put_config(hermes_env, text)
        s = G.hermes_settings()
        assert s["error"] and s["mode"] is None and s["timeout"] is None, (text, s)
        assert denied(H(arm_cmd(repo), elsewhere)) == noask("hermes_how_config", path=G._dialog(path, 200), err=G._dialog(s["error"], 200)), text
    put_config(hermes_env, "approvals:\n  mode: 'it''s'\n")
    assert G.hermes_settings()["mode"] == "it's"


def test_the_lifetime_follows_hermes_approvals_timeout(repo, elsewhere, hermes_env):
    for text, life in (("approvals:\n  timeout: 60\n", 150), ("approvals:\n  timeout: 600\n", 630), ("approvals:\n  timeout: 1200\n", 930),
                       ("approvals:\n  timeout: abc\n", 330), ("approvals:\n  timeout: -5\n", 150), (None, 330)):
        put_config(hermes_env, text)
        command, message, _k = asked(H(arm_cmd(repo), elsewhere))
        rec = rec_of(approvals(repo), command)
        assert rec["expires"] - rec["created"] == pytest.approx(life) and "within %d s" % life in message, (text, rec, message)
    # approvals.timeout as Hermes reads it: PyYAML's YAML 1.1 value, then int() (TC-659): what Hermes waits, the record outlives
    hermes_reads = {"0x3e8": 1000, "1_000": 1000, "1000.5": 1000, "'1000'": 1000, "0300": 192, "09": 9, "yes": 1, "off": 0, "~": 300, "": 300,
                    ".nan": 300, "10:00": 600, "0b1010": 10, "'0x10'": 300, "' 42 '": 42, "1.5e+3": 1500, "'1_0'": 10, "1e3": 300, ".inf": 900}
    for raw, t in hermes_reads.items():
        put_config(hermes_env, "approvals:\n  timeout: %s\n" % raw)
        s = G.hermes_settings()
        assert s["error"] is None and s["timeout"] == t and G.hermes_lifetime(s) == min(max(t, 120), 900) + 30, (raw, s)


# ---- recognition (TC-660 to TC-665) --------------------------------------------------------------------------------------------------------
def test_every_other_shape_stays_denied_with_a_cause(repo, elsewhere, tmp_path):
    changed = tmp_path / "changed" / "magos_guard.py"
    changed.parent.mkdir()
    changed.write_bytes(SCRIPT.read_bytes() + b"#")
    equal = tmp_path / "equal" / "magos_guard.py"
    equal.parent.mkdir()
    equal.write_bytes(SCRIPT.read_bytes())
    base, qr = arm_cmd(repo), q(repo.path)
    rows = [("cd %s && %s" % (qr, base), "SHAPE", {}), (base + " | cat", "SHAPE", {}), (base + " > out", "SHAPE", {}), ("X=1 " + base, "SHAPE", {}),
            ('bash -c "%s %s --repo %s arm"' % (EXE, S, P(repo.path)), "SHAPE", {}), (base + " &", "SHAPE", {}), (base + "\necho x", "SHAPE", {}),
            ('%s %s --repo %s override --fingerprint 0123456789ab --reason "$R2"' % (PY, QS, qr), "DYNAMIC", {}),
            (base + " --bogus", "ARGS", {}), ("%s %s --repo %s -- arm" % (PY, QS, qr), "SHAPE", {}),
            ("%s %s --repo %s arm" % (PY, q(changed), qr), "SCRIPT", {}), ("%s %s --repo %s install --host hermes" % (PY, q(equal), qr), "SCRIPT", {}),
            (base, "TOOL", {"background": True}), (base, "TOOL", {"pty": True}), (base, "TOOL", {"tool": "shell"})]
    for cmd, cause, ti in rows:
        shape(H(cmd, elsewhere, **ti), cause)
    assert not approvals(repo).exists()


def test_the_directory_must_come_from_the_call(repo, elsewhere, tmp_path, isolated_env):
    (repo.path / "a(b)").mkdir()
    copy = tmp_path / "copy" / "magos_guard.py"
    copy.parent.mkdir()
    copy.write_bytes(SCRIPT.read_bytes())
    qr = q(repo.path)
    for cmd, ti in (("%s %s arm" % (PY, QS), {}), ("%s %s --repo rel arm" % (PY, QS), {}), ("%s scripts/magos_guard.py --repo %s arm" % (PY, qr), {}),
                    ("%s %s install --host hermes --home rel" % (PY, QS), {}), ("%s %s arm" % (PY, QS), {"workdir": P(repo.path / "a(b)")}),
                    ("%s %s arm" % (PY, QS), {"workdir": "src"}), ("%s %s arm" % (PY, QS), {"workdir": "~/r"})):
        shape(H(cmd, elsewhere, **ti), "DIRECTORY")
    assert not approvals(repo).exists() and not (isolated_env / ".magos" / "approvals").exists()
    spellings = [P(repo.path)] + ([str(repo.path).replace("/", "\\").upper()] if WIN else [])
    for workdir in spellings:
        for cmd in ("%s %s --lang en arm" % (PY, QS), "%s ../copy/magos_guard.py --lang en arm" % PY):
            command, _m, _k = asked(H(cmd, elsewhere, workdir=workdir))
            assert os.path.samefile(rec_of(approvals(repo), command)["where"], str(common(repo))), (workdir, cmd)


def test_the_workdir_must_be_an_existing_absolute_directory(repo, elsewhere, tmp_path):
    """TC-723: a workdir is an existing directory named by an absolute path; on Windows a drive-less /x names another directory in Git Bash
    (its own root) than in Python (the current drive), so it names none."""
    bad = ["/Users/x/repo", P(tmp_path / "no-such-dir")] + ([P(repo.path)[2:]] if WIN else [])  # the last: the repository without its drive
    for workdir in bad:
        shape(H(arm_cmd(repo), elsewhere, workdir=workdir), "DIRECTORY")
    assert not approvals(repo).exists()
    for workdir in [P(repo.path)] + ([str(repo.path).replace("/", "\\")] if WIN else []):
        command, _m, _k = asked(H(arm_cmd(repo), elsewhere, workdir=workdir))
        assert os.path.samefile(rec_of(approvals(repo), command)["where"], str(common(repo))), workdir


def test_an_interpreter_word_with_a_tilde_is_refused(repo, elsewhere, monkeypatch):
    """TC-724: a first word that starts with ~ is refused before it is expanded, also when it expands to the hook's own interpreter: without a
    workdir Hermes names no directory (APPROVAL_DIRECTORY), Claude Code takes no ~ interpreter (APPROVAL_INTERPRETER)."""
    where, name = os.path.split(os.path.abspath(sys.executable))
    monkeypatch.setenv("HOME", where)
    monkeypatch.setenv("USERPROFILE", where)
    word = "~/" + name
    assert G.same_file(os.path.expanduser(word), sys.executable)  # the word names the interpreter that runs the hook
    cmd = " ".join([word, QS, "--repo", q(repo.path), "--lang", "en", "arm"])
    assert G.protected(cmd) == ("always", G._USER_MSG)
    shape(H(cmd, elsewhere), "DIRECTORY")
    claude = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(repo.path), "tool_use_id": "toolu_1", "session_id": "s-1"}
    head = G.T("en", "protected_shape", why=G._USER_MSG, cmd=G.guard_cmd())
    assert G.approval_answer(claude, str(repo.path), [], "en") == ("PROTECTED", head + "\n[APPROVAL_INTERPRETER]")
    assert G.decide(claude, "en", "claude") == ("PROTECTED", head + "\n[APPROVAL_INTERPRETER]")
    top = os.path.dirname(os.path.dirname(os.path.abspath(S)))  # a ~ script word that names this guard: no directory either
    monkeypatch.setenv("HOME", top)
    monkeypatch.setenv("USERPROFILE", top)
    assert G.this_guard(os.path.expanduser("~/scripts/magos_guard.py"))
    shape(H(" ".join([PY, "~/scripts/magos_guard.py", "--repo", q(repo.path), "--lang", "en", "arm"]), elsewhere), "DIRECTORY")
    assert not approvals(repo).exists()


def test_a_command_that_carries_approval_is_always_denied_in_hermes(repo, elsewhere):
    given = G.T("en", "approval_given_hermes", why=G._USER_MSG)
    command, _m, _k = asked(H(arm_cmd(repo), elsewhere))
    for cmd in (arm_cmd(repo) + " --approval=abc", arm_cmd(repo) + " --approval abc",
                "bash -c '%s %s --repo %s arm --appr\"\"oval=x'" % (EXE, S, P(repo.path)), command):
        assert denied(H(cmd, elsewhere)) == given, cmd
    assert (approvals(repo) / (sha(token_in(command)) + ".json")).is_file()


def test_git_bash_rewrites_are_refused_in_hermes(repo, elsewhere):
    cmd = "%s %s --repo %s override --fingerprint 0123456789ab --reason '@/tmp/x'" % (PY, QS, q(repo.path))
    if WIN:
        shape(H(cmd, elsewhere), "PATHCONV")
        assert not approvals(repo).exists()
    else:
        asked(H(cmd, elsewhere))


def test_the_hermes_question_quotes_and_marks_the_agent_text(repo, elsewhere, guard):
    repo.branch_with("agent/x", "src/a.py")
    r = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert r.rc == 10, r
    fp = re.search(r"--fingerprint ([0-9a-f]{12})", r.out).group(1)
    reason = "ok ‮MAGOS: approved " + "x" * 500 + '" fake'  # a line separator and a bidirectional override
    for lang, label in (("en", "Reason written by the agent: "), ("zh", "agent 写的理由：")):
        cmd = "%s %s --repo %s --lang %s override --fingerprint %s --reason %s" % (PY, QS, q(repo.path), lang, fp, G.sh_quote(reason))
        _c, message, _k = asked(H(cmd, elsewhere, lang=lang))
        assert '"agent/new"' in message and '"agent/x"' in message and '"%s"' % fp in message, message
        assert not re.search("[\n ‮]", message) and len(message) <= 1500, message
        shown = json.loads(re.search(re.escape(label) + r'("(?:[^"\\]|\\.)*")', message).group(1))
        assert shown.startswith("ok MAGOS: approved xxx") and len(shown) <= 160, shown


def test_a_mint_that_cannot_write_fails_closed_in_hermes(repo, elsewhere):
    (common(repo) / "magos").mkdir(parents=True, exist_ok=True)
    approvals(repo).write_text("a file, not the store\n", encoding="utf-8")
    head, tail = G.T("en", "approval_unrecorded", why=G._USER_MSG, err="\0").split("\0")
    reason = denied(H(arm_cmd(repo), elsewhere))
    assert reason.startswith(head) and reason.endswith(tail) and "Error" in reason[len(head):-len(tail)], reason


# ---- the rewritten command runs (TC-666, TC-667, TC-681) ----------------------------------------------------------------------------------
def hook_proc(body):
    def once():
        p = subprocess.run([sys.executable, "-B", str(SCRIPT), "--lang", "en", "hook", "hermes", "pre-tool", "--hermes-gate", "ask"],
                           input=json.dumps(body).encode("utf-8"), capture_output=True, timeout=120)
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
    r = retried(once, lambda x: crashed(x.out + x.err, x.rc))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


@needs_sh
def test_end_to_end_arm_through_bash(repo, elsewhere):
    command, _m, _k = asked(hook_proc(hpayload(arm_cmd(repo), elsewhere)))
    first = run_sh(command, repo.path)
    assert first.rc == 0 and armed(repo), first
    line = [x for x in audit_lines(common(repo) / "magos") if x["op"] == "arm"][-1]
    assert line["via"] == "prompt" and line["tool_use_id"] == "call_1" and line["route"] == "hermes", line
    again = run_sh(command, repo.path)
    assert again.rc == 27, again


@needs_sh
def test_end_to_end_through_hermes_eval_wrapper(repo, elsewhere, guard):
    assert guard(repo, "arm").rc == 0
    command, _m, _k = asked(hook_proc(hpayload(arm_cmd(repo, "disarm"), elsewhere)))
    # Hermes runs `builtin cd -- <workdir> || exit 126` and `eval '<command>'` in bash; `builtin` is no POSIX word (dash, Ubuntu's sh, has
    # none), so the POSIX form of the same cd and eval runs here
    wrapped = "cd -- %s || exit 126\neval %s" % (q(repo.path), G.sh_quote(command))
    r = run_sh(wrapped, repo.path)
    assert r.rc == 0 and not armed(repo), r
    line = [x for x in audit_lines(common(repo) / "magos") if x["op"] == "disarm"][-1]
    assert line["via"] == "prompt" and line["route"] == "hermes", line


@pytest.mark.skipif(not WIN or SH is None, reason="Windows with Git's sh only")
def test_windows_bare_py_through_git_bash(repo, elsewhere):
    if not shutil.which("py"):
        pytest.skip("py is not on PATH")
    command, _m, _k = asked(hook_proc(hpayload("py %s --repo %s --lang en arm" % (QS, q(repo.path)), elsewhere)))
    assert command.startswith("py ")
    r = run_sh(command, repo.path)
    assert r.rc == 0 and armed(repo), r


# ---- install and doctor (TC-672, TC-673, TC-678) ------------------------------------------------------------------------------------------
def make_plugin(hh, version=None, init=True, hook_line=True):
    d = Path(hh) / "plugins" / "magos"
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    (d / "hooks").mkdir(exist_ok=True)
    data = SCRIPT.read_bytes()
    if version:
        data = data.replace(b'GUARD_VERSION = "%s"' % G.GUARD_VERSION.encode(), b'GUARD_VERSION = "%s"' % version.encode())
    (d / "scripts" / "magos_guard.py").write_bytes(data)
    shutil.copyfile(str(LAUNCHER), str(d / "hooks" / "run-guard.cmd"))
    if init:
        text = (ROOT / "__init__.py").read_bytes() if hook_line else b"def register(ctx):\n    pass\n"
        (d / "__init__.py").write_bytes(text)
    return P(d)


def test_install_names_the_hermes_route(repo, guard, hermes_env):
    d = make_plugin(hermes_env)
    for case in ("plugin", "old", "none"):
        if case == "old":
            make_plugin(hermes_env, version=OLD)
        if case == "none":
            shutil.rmtree(str(hermes_env / "plugins"))
        r = guard(repo, "install", "--host", "hermes", "--dry-run")
        assert r.rc == 0 and G.host_snippet("hermes", G.guard_home()) in r.out, r
        notes = [x for x in r.out.splitlines() if x.startswith("NOTE: ")]
        if case == "plugin":
            assert "NOTE: the Hermes plugin %s (guard %s) runs the guard and asks for a user-only command in Hermes's approval prompt" % (d, G.GUARD_VERSION) in r.out
        else:
            assert any(x.startswith("NOTE: the entry below runs the guard in Hermes once it is approved") and "hermes plugins update magos" in x for x in notes), r.out


def hooks_entry(home):
    snippet = G.host_snippet("hermes", home)
    raw = next(x for x in snippet.splitlines() if "hook hermes pre-tool" in x).split("command:", 1)[1].strip()
    return snippet, raw[1:-1].replace("''", "'")


def doctor(repo):
    r = run(["--repo", str(repo.path), "--lang", "en", "doctor"])
    return r, [x for x in r.out.splitlines() if x.startswith(("hermes route", "hermes entry:", "hermes approvals"))]


def test_doctor_reports_the_hermes_route_and_approvals(repo, hermes_env, monkeypatch):
    r, lines = doctor(repo)
    assert r.rc == 0 and lines == [], r.out  # no Hermes home
    d = make_plugin(hermes_env)
    enabled = "plugins:\n  enabled:\n    - magos\n"
    put_config(hermes_env, enabled)
    r, lines = doctor(repo)
    assert r.rc == 0 and lines[0] == "hermes route: the plugin %s (guard %s) runs the guard and asks for a user-only command in Hermes's approval prompt" % (
        d, G.GUARD_VERSION), r.out
    assert lines[-1] == "hermes approvals: Hermes asks (approvals.mode unset), within 300 s; a session /yolo is not visible here"
    snippet, command = hooks_entry("/x")
    cfg = put_config(hermes_env, enabled + snippet)
    r, lines = doctor(repo)
    assert r.rc == 1 and any(x.startswith("hermes route: %s also holds a MAGOS entry under hooks:" % cfg) for x in lines), r.out
    assert any(x.startswith("hermes entry: %s holds the MAGOS entry under hooks:" % cfg) for x in lines)  # information beside the problem
    put_config(hermes_env, "plugins:\n  enabled: [homeassistant]\n")
    r, lines = doctor(repo)
    assert r.rc == 0 and lines[0] == "hermes route: magos is not in plugins.enabled of %s; Hermes loads no MAGOS callbacks" % cfg, r.out
    put_config(hermes_env, enabled)
    make_plugin(hermes_env, version=OLD)
    r, lines = doctor(repo)
    assert lines[0] == "hermes route: the plugin %s holds guard %s, not %s; update it (hermes plugins update magos) and restart Hermes" % (
        d, OLD, G.GUARD_VERSION), r.out
    make_plugin(hermes_env, hook_line=False)  # this guard's version, an __init__.py without the callbacks: a text of its own
    r, lines = doctor(repo)
    assert lines[0] == ("hermes route: the plugin %s holds guard %s, but its __init__.py registers no guard callbacks; update it (hermes plugins "
                        "update magos) and restart Hermes" % (d, G.GUARD_VERSION)), r.out
    make_plugin(hermes_env)
    put_config(hermes_env, enabled + "approvals:\n  mode: off\n  timeout: 60\n")
    r, lines = doctor(repo)
    assert lines[-1] == ("hermes approvals: approvals.mode is off in %s: Hermes approves without asking, so the guard refuses the click and user-only "
                         "commands run in the user's own terminal" % cfg) and r.rc == 0, r.out
    put_config(hermes_env, enabled + "approvals:\n  mode: manual\n  timeout: 60\n")
    assert doctor(repo)[1][-1] == "hermes approvals: Hermes asks (approvals.mode manual), within 60 s; a session /yolo is not visible here"
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    assert doctor(repo)[1][-1].startswith("hermes approvals: HERMES_YOLO_MODE is set here: Hermes approves without asking")
    monkeypatch.delenv("HERMES_YOLO_MODE")
    put_config(hermes_env, "directory")
    r, lines = doctor(repo)
    assert lines[-1].startswith("hermes approvals: %s cannot be read (" % cfg) and lines[-1].endswith("): the guard refuses the click"), r.out
    shutil.rmtree(str(hermes_env / "plugins"))
    put_config(hermes_env, snippet)
    r, lines = doctor(repo)
    assert lines[0].startswith("hermes route: no MAGOS plugin under %s/plugins" % P(hermes_env)), r.out
    assert any(x.startswith("hermes entry: %s holds the MAGOS entry under hooks:, but %s/shell-hooks-allowlist.json does not list its command"
                            % (cfg, P(hermes_env))) for x in lines) and r.rc == 1, r.out
    (hermes_env / "shell-hooks-allowlist.json").write_text(json.dumps({"approvals": [{"event": "pre_tool_call", "command": command}]}), encoding="utf-8")
    r, lines = doctor(repo)
    assert r.rc == 0 and not any(x.startswith("hermes entry:") for x in lines), r.out
    (hermes_env / "shell-hooks-allowlist.json").unlink()
    make_plugin(hermes_env)
    put_config(hermes_env, enabled + snippet)
    r, lines = doctor(repo)
    assert r.rc == 1 and any(x.startswith("hermes entry: ") for x in lines) and any("also holds a MAGOS entry" in x for x in lines), r.out


def test_the_hermes_route_reader(hermes_env):
    hermes_env.mkdir()
    r = G.hermes_route()
    assert (r["plugin"], r["version"], r["callbacks"], r["enabled"], r["entry"], r["consented"]) == (False, None, False, None, False, None)
    make_plugin(hermes_env, init=False)
    assert G.hermes_route()["plugin"] is False
    make_plugin(hermes_env, hook_line=False)
    r = G.hermes_route()
    assert r["plugin"] is True and r["version"] == G.GUARD_VERSION and r["callbacks"] is False
    make_plugin(hermes_env)
    assert G.hermes_route()["callbacks"] is True
    for text, want in (("plugins:\n  enabled:\n    - magos\n", True), ("plugins:\n  enabled: [a, magos]\n", True),
                       ("plugins:\n  disabled: [magos]\n", False), ("x: 1\n", None), ("plugins:\n  enabled:\n  - 'magos'\n", True)):
        put_config(hermes_env, text)
        assert G.hermes_route()["enabled"] is want, text
    snippet, command = hooks_entry("/x")
    put_config(hermes_env, "hooks:\n  pre_tool_call:\n    - matcher: \"terminal\"\n      command: 'other'\n")
    assert G.hermes_route()["entry"] is False and G.hermes_route()["consented"] is None
    put_config(hermes_env, snippet)
    allow = hermes_env / "shell-hooks-allowlist.json"
    for content, want in ((json.dumps({"approvals": [{"event": "pre_tool_call", "command": command, "approved_at": "x"}]}), True),
                          (json.dumps({"approvals": [{"event": "post_tool_call", "command": command}]}), False), (None, False), ("{not json", None)):
        if content is None:
            if allow.exists():
                allow.unlink()
        else:
            allow.write_text(content, encoding="utf-8")
        r = G.hermes_route()
        assert r["entry"] is True and r["consented"] is want, (content, r)


def test_a_flow_list_ends_at_its_first_bracket(hermes_env):
    """TC-725: a flow list ends at its first ]; a ] in the comment after it is no part of the last name, and a name that holds a ] is unread."""
    for raw, want in (("[magos] # see [docs]", ["magos"]), ("[magos, other] # [x]", ["magos", "other"]), ("[magos] # note", ["magos"]),
                      ('["a]b"]', None)):
        assert G._hermes_list(raw, []) == want, raw
    make_plugin(hermes_env)
    put_config(hermes_env, "plugins:\n  enabled: [magos] # see [docs]\n")
    r = G.hermes_route()
    assert r["plugin"] is True and r["version"] == G.GUARD_VERSION and r["enabled"] is True, r


# ---- texts, the other hosts and the command side (TC-674 to TC-676) -----------------------------------------------------------------------
HERMES_KEYS = ("protected_shape_hermes", "approval_given_hermes", "protected_hermes_noask", "hermes_how_session", "hermes_how_gate", "hermes_how_env",
               "hermes_how_mode", "hermes_how_config", "approval_ask_hermes")


def test_the_hermes_texts_exist_in_both_languages():
    import string
    for key in HERMES_KEYS:
        zh, en = G.M[key]
        fields = [sorted({f for _t, f, _s, _c in string.Formatter().parse(s) if f}) for s in (zh, en)]
        assert fields[0] == fields[1] and zh != en, key
        for lang in ("zh", "en"):
            text = G.T(lang, key, **{f: "V" for f in fields[0]})
            assert "{" not in text and "}" not in text, (key, lang)
    for key in ("protected_shape_hermes", "approval_given_hermes", "protected_hermes_noask"):
        assert "{why}" in G.M[key][1] and "would change the guard's own" in G.M[key][1], key


def test_claude_and_codex_outputs_are_not_changed_by_the_hermes_route(repo):
    r = run(["--lang", "en", "hook", "claude", "pre-tool"], stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": "py -3 %s --lang en arm" % QS},
                                                                              "cwd": str(repo.path), "tool_use_id": "toolu_1", "session_id": "s-1"}).encode("utf-8"))
    h = json.loads(r.out)["hookSpecificOutput"]
    assert h["permissionDecision"] == "ask"
    rec = rec_of(approvals(repo), h["updatedInput"]["command"].rstrip("'"))
    assert set(rec) == {"v", "sub", "argv", "where", "via", "created", "expires", "tool_use_id", "session_id", "command_sha256", "used"}
    assert G.approval_fields(rec) == {"tool_use_id": "toolu_1"}
    shutil.rmtree(str(approvals(repo)))
    r = run(["--lang", "en", "hook", "codex", "pre-tool"], stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": "py -3 %s --lang en arm" % QS},
                                                                             "cwd": str(repo.path)}).encode("utf-8"))
    assert denied(r) == G.T("en", "protected_codex", why=G._USER_MSG, call=json.dumps({"subcommand": "arm", "repo": P(repo.path)}),
                            ready=G.ready_command(["--repo=" + P(repo.path), "--lang=en", "arm"]))
    g = G.open_repo(str(repo.path))
    for row, args in ((G.USER_ONLY[0], ["override", "--fingerprint", "0123456789ab", "--reason", "r"]), (G.USER_ONLY[1], ["arm", "--dry-run"]),
                      (G.USER_ONLY[2], ["disarm"]), (G.USER_ONLY[3], ["install", "--host", "codex", "--allow-downgrade"])):
        ns = G.parse_quiet(args)
        t = {"g": g, "dest": G.guard_home()}
        for lang in ("en", "zh"):
            for auto in (False, True):
                assert G.approval_text(lang, row, ns, t, auto) == G.T(lang, "approval_auto" if auto else "approval_ask", sub=row.name,
                                                                         what=G.approval_what(lang, row, ns, t))


def test_the_command_verifies_a_hermes_record_unchanged(repo, monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: pytest.fail("the console was asked"))
    g = G.open_repo(str(repo.path))
    root = approvals(repo)
    root.mkdir(parents=True)

    def mint(sub, age, route):
        token = secrets.token_urlsafe(32)
        created = time.time() - age
        argv = ["--repo", P(repo.path), "--lang", "en", sub]
        rec = {"v": 1, "sub": sub, "argv": argv, "where": g.common, "via": "prompt", "created": created, "expires": created + 330,
               "tool_use_id": "call_1", "session_id": "s-1", "command_sha256": "0" * 64, "used": False, "route": route}
        (root / (hashlib.sha256(token.encode("ascii")).hexdigest() + ".json")).write_text(json.dumps(rec), encoding="utf-8")
        return run(argv + ["--approval=" + token])
    r = mint("arm", 200, "hermes")
    assert r.rc == 0 and armed(repo), r
    assert [x for x in audit_lines(common(repo) / "magos") if x["op"] == "arm"][-1]["route"] == "hermes"
    r = mint("disarm", 0, "x")
    assert r.rc == 0 and not armed(repo), r
    line = [x for x in audit_lines(common(repo) / "magos") if x["op"] == "disarm"][-1]
    assert "route" not in line and line["tool_use_id"] == "call_1"
    r = mint("arm", 340, "hermes")
    assert r.rc == 26 and not armed(repo), r


# ---- what the hook itself checks before it asks (TC-698, TC-699) -----------------------------------------------------------------------------
def test_a_command_that_also_creates_a_lane_gets_no_question(repo, elsewhere):
    payload = hpayload(arm_cmd(repo), elsewhere)
    creation = [{"names": ["agent/x"], "dynamic": False, "kind": "switch", "cwd": str(repo.path)}]
    for crs, want in ((creation, "SHAPE"), ([], None)):
        res = G.hermes_answer(payload, crs, "en", "ask")
        if want:
            assert res == ("PROTECTED", G.T("en", "protected_shape_hermes", why=G._USER_MSG, cmd=G.guard_cmd()) + "\n[APPROVAL_SHAPE]"), res
        else:
            assert isinstance(res, G.HermesApproval) and res.message, res
    assert len(list(approvals(repo).iterdir())) == 1  # only the plain invocation minted


def test_the_parsers_reading_of_the_appended_token_and_the_gate_value_are_checked(repo, elsewhere, monkeypatch):
    payload = hpayload(arm_cmd(repo), elsewhere)
    real = G.parse_quiet

    def elsewhere_read(words):  # a parser that reads the appended approval word otherwise than the command will
        ns = real(words)
        if ns is not None and getattr(ns, "approval", None):
            ns.approval = "not-the-probe"
        return ns
    monkeypatch.setattr(G, "parse_quiet", elsewhere_read)
    head = G.T("en", "protected_shape_hermes", why=G._USER_MSG, cmd=G.guard_cmd())
    assert G.hermes_answer(payload, [], "en", "ask") == ("PROTECTED", head + "\n[APPROVAL_ARGS]")
    monkeypatch.setattr(G, "parse_quiet", real)
    settings = G.hermes_settings()
    for gate in ("absent", "maybe", "", None, "ASK"):  # every value but ask fails closed
        assert G.hermes_noask(gate, settings) == ("hermes_how_gate", {}), gate
    assert G.hermes_noask("bypass", settings) == ("hermes_how_session", {}) and G.hermes_noask("ask", settings) is None
    assert not approvals(repo).exists()
