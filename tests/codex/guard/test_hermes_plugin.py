"""1.0.8 Hermes approval, the plugin side: the two pre_tool_call callbacks of `__init__.py` (verdict and approval), their gate
probe, the payload they hand the guard, their failures, and the pairing of a verdict's approve with its own call. The callbacks run
in process; their directives go through a reimplementation of Hermes's directive aggregation (hermes_cli/plugins.py,
_get_pre_tool_call_directive_details and _resolve_block_from_details), whose gate is a fake human. No Hermes runs."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from dataclasses import dataclass
from typing import Optional

import pytest

from conftest import G, ROOT, run
from test_approval import PY, QS, approvals, armed, needs_sh, new_repo, run_sh

OFF_SWITCHES = ("MAGOS_GUARD=off", "hermes plugins disable magos")
GUARD_CALL = "py -3 C:/x/magos_guard.py --repo C:/r arm"  # a command that names the guard; the fake guards below never read it


@pytest.fixture(autouse=True)
def hermes_env(monkeypatch):
    for key in ("HERMES_YOLO_MODE", "HERMES_PLUGIN_HOST_PROCESS", "MAGOS_GUARD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MAGOS_LANG", "en")  # the plugin's texts and the guard child's


def plugin():
    """A fresh copy of the shipped __init__.py (its marks start empty) and its two callbacks, as register() hands them to Hermes."""
    spec = importlib.util.spec_from_file_location("magos_plugin_hermes", ROOT / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Context:
        hooks = []

        def register_skill(self, name, path, description=""):
            pass

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

    ctx = Context()
    mod.register(ctx)
    assert [name for name, _ in ctx.hooks] == ["pre_tool_call", "pre_tool_call"]
    return mod, [callback for _, callback in ctx.hooks]


def call_kw(tid="call_1", sid="local-s1", turn="turn-1"):
    """The keyword arguments Hermes passes a pre_tool_call callback besides tool_name and args (observed, h-host-facts P5)."""
    return {"task_id": sid, "session_id": sid, "tool_call_id": tid, "turn_id": turn, "api_request_id": turn + ":api:1",
            "middleware_trace": [], "telemetry_schema_version": "hermes.observer.v1"}


@dataclass
class Outcome:
    blocked: Optional[str]  # the block message (the tool result) or None
    runs: Optional[dict]  # the args the terminal tool runs, None when blocked
    asked: list  # the (message, rule_key) the gate was asked with


def consume(callbacks, args, kw, gate_answer=lambda message, rule_key: False):
    """Hermes's aggregation: every callback gets the same args object of the call (a shallow copy of one keyword dict); each modify
    merges its args over the merged args; the first valid block wins over everything; else the first approve goes to the gate, whose
    denial blocks; else the merged args run."""
    call = dict(args)
    results = [r for r in (cb(tool_name="terminal", args=call, **kw) for cb in callbacks) if r is not None]
    merged, first_approve = None, None
    for result in results:
        if not isinstance(result, dict):
            continue
        action = result.get("action")
        if action == "modify":
            partial = result.get("args")
            if isinstance(partial, dict) and partial:
                merged = dict(merged if merged is not None else args, **partial)
            continue
        message = result.get("message") if isinstance(result.get("message"), str) and result.get("message") else None
        if action == "block" and message:
            return Outcome(message, None, [])
        if action == "approve" and first_approve is None:
            rule_key = result.get("rule_key")
            first_approve = (message, (rule_key.strip() or None) if isinstance(rule_key, str) else None)
    runs = merged if merged is not None else dict(args)
    if first_approve is None:
        return Outcome(None, runs, [])
    if not gate_answer(*first_approve):
        return Outcome("BLOCKED: User denied", None, [first_approve])
    return Outcome(None, runs, [first_approve])


def done(stdout=b"{}", returncode=0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")


def answering(mod, monkeypatch, *answers):
    """Replace the guard child by canned answers, one per call (bytes, or an exception to raise); -> the payloads it was given."""
    seen, queue = [], list(answers)

    def fake(payload, gate_value):
        seen.append((payload, gate_value))
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr(mod, "_run_guard", fake)
    return seen


def ask(command, message, rule_key):
    return json.dumps({"hermesApproval": {"modify": {"command": command}, "approve": {"message": message, "rule_key": rule_key}}}).encode()


# ---- TC-668: the two callbacks with the real guard through a simulated Hermes --------------------------------------------------------
@needs_sh
def test_the_two_callbacks_end_to_end_through_a_simulated_hermes(tmp_path, monkeypatch):
    mod, callbacks = plugin()
    monkeypatch.setattr(mod, "gate", lambda: "ask")
    r = new_repo(tmp_path / "r")
    R = str(r.path).replace("\\", "/")
    arm = {"command": "%s %s --repo '%s' --lang en arm" % (PY, QS, R)}

    denied_by_human = consume(callbacks, arm, call_kw("call_1"), lambda message, rule_key: False)
    assert denied_by_human.blocked and denied_by_human.runs is None and not armed(r)
    (message, rule_key), = denied_by_human.asked
    assert message.startswith("MAGOS: approve the user-only guard command arm?") and re.fullmatch(r"magos:arm:[0-9a-f]{32}", rule_key)
    assert [p.suffix for p in approvals(r).iterdir()] == [".json"]  # minted, never used

    approved = consume(callbacks, arm, call_kw("call_2"), lambda message, rule_key: True)
    assert approved.blocked is None and len(approved.asked) == 1 and approved.asked[0][1] != rule_key  # a new question, a new key
    assert approved.runs["command"] != arm["command"] and "--approval=" in approved.runs["command"]
    result = run_sh(approved.runs["command"], r.path)
    assert result.rc == 0 and armed(r), result

    vetoed = consume(callbacks + [lambda **k: {"action": "block", "message": "a shell hook says no"}], arm, call_kw("call_3"),
                     lambda message, rule_key: True)
    assert vetoed.blocked == "a shell hook says no" and vetoed.runs is None

    unmarked = consume([callbacks[0], lambda **k: mod._KEPT.clear(), callbacks[1]], arm, call_kw("call_4"), lambda m, k: True)
    assert unmarked.blocked and "was not prepared" in unmarked.blocked and unmarked.runs is None  # the approval callback blocks

    auto = new_repo(tmp_path / "auto")
    auto.git("config", "magos.approval", "auto-safe")
    A = str(auto.path).replace("\\", "/")
    quiet = consume(callbacks, {"command": "%s %s --repo '%s' --lang en arm" % (PY, QS, A)}, call_kw("call_5"))
    assert quiet.blocked is None and quiet.asked == []  # no gate at all
    assert run_sh(quiet.runs["command"], auto.path).rc == 0 and armed(auto)

    for number, command in enumerate(("ls", "%s %s --repo '%s' plan --branch x --paths a" % (PY, QS, R), "%s %s version" % (PY, QS))):
        plain = consume(callbacks, {"command": command}, call_kw("plain_%d" % number))
        assert plain.blocked is None and plain.asked == [] and plain.runs == {"command": command}, command
        if command != "ls":
            out = run_sh(command, r.path)
            assert out.rc == 0, (command, out)
    assert G.GUARD_VERSION in out.out  # the version printed
    claims = json.loads(run(["--repo", str(r.path), "--lang", "en", "list", "--json"]).out)
    assert [(c["branch"], c["state"]) for c in claims] == [("x", "planned")]  # the plan registered its claim
    assert mod._KEPT == {}  # every mark was taken by its own approval


# ---- TC-669: failures block and name the off switches; the off switch starts nothing -------------------------------------------------
def test_plugin_failures_block_and_the_off_switch_starts_nothing(tmp_path, monkeypatch):
    mod, (verdict, approval) = plugin()
    monkeypatch.setattr(mod, "gate", lambda: "ask")
    cases = [(subprocess.TimeoutExpired(["guard"], 25), "did not answer within 25 s"),
             (done(b"", 1), "exit code 1"),
             (done(b"garbage"), "no JSON object"),
             (done(b"\xff\xfe"), "no JSON object"),
             (done(b"[]"), "no known shape"),
             (done(b'{"hermesApproval": {"modify": {}}}'), "no known shape"),
             (done(ask("x --approval=t", "question", "terminal:1")), "no known shape"),
             (done(b'{"hermesApproval": {"modify": {"command": "x"}, "approve": "yes"}}'), "no known shape"),
             (FileNotFoundError(2, "No such file"), "could not be started"),
             (RuntimeError("boom"), "the plugin failed (RuntimeError: boom)")]
    answering(mod, monkeypatch, *[answer for answer, _ in cases])
    for number, (_, cause) in enumerate(cases):
        kw = call_kw("call_%d" % number)
        call = {"command": GUARD_CALL}  # Hermes hands both callbacks of one call the same args object
        directive = verdict(tool_name="terminal", args=call, **kw)
        assert directive["action"] == "block" and cause in directive["message"], (cause, directive)
        assert all(switch in directive["message"] for switch in OFF_SWITCHES) and "nothing ran" in directive["message"]
        assert approval(tool_name="terminal", args=call, **kw) is None  # the verdict's mark: no second block

    # A real guard child that is too slow, and one that exits non-zero.
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    fresh, (verdict2, _) = plugin()  # the shipped _run_guard, with the guard path and the limit replaced
    monkeypatch.setattr(fresh, "gate", lambda: "ask")
    monkeypatch.setattr(fresh, "GUARD", slow)
    monkeypatch.setattr(fresh, "GUARD_LIMIT_S", 1)
    directive = verdict2(tool_name="terminal", args={"command": "ls"}, **call_kw("slow"))
    assert "did not answer within 1 s" in directive["message"], directive
    failing = tmp_path / "failing.py"
    failing.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    monkeypatch.setattr(fresh, "GUARD", failing)
    assert "exit code 3" in verdict2(tool_name="terminal", args={"command": "ls"}, **call_kw("failing"))["message"]

    # After {}, a deny and an auto-safe modify, the approval callback of the same call returns nothing.
    answering(mod, monkeypatch, done(), done(b'{"decision": "block", "reason": "lane taken"}'),
              done(b'{"hermesApproval": {"modify": {"command": "x --approval=t"}}}'))
    expected = [None, {"action": "block", "message": "lane taken"}, {"action": "modify", "args": {"command": "x --approval=t"}}]
    for number, want in enumerate(expected):
        kw, call = call_kw("after_%d" % number), {"command": GUARD_CALL}
        assert verdict(tool_name="terminal", args=call, **kw) == want
        assert approval(tool_name="terminal", args=call, **kw) is None

    # The off switch and another tool: nothing starts, nothing is kept, nothing is returned.
    started = answering(mod, monkeypatch)
    for value in ("off", " OFF ", "Off\t"):
        monkeypatch.setenv("MAGOS_GUARD", value)
        assert verdict(tool_name="terminal", args={"command": GUARD_CALL}, **call_kw("off")) is None
        assert approval(tool_name="terminal", args={"command": GUARD_CALL}, **call_kw("off")) is None
    monkeypatch.delenv("MAGOS_GUARD")
    for tool in ("read_file", "process", ""):
        assert verdict(tool_name=tool, args={"command": GUARD_CALL}, **call_kw(tool)) is None
        assert approval(tool_name=tool, args={"command": GUARD_CALL}, **call_kw(tool)) is None
    assert started == [] and mod._KEPT == {}
    monkeypatch.setenv("MAGOS_GUARD", "auto")  # any other value leaves the guard on
    started = answering(mod, monkeypatch, done())
    assert verdict(tool_name="terminal", args={"command": "ls"}, **call_kw("on")) is None and len(started) == 1

    # In Chinese unless MAGOS_LANG is en; the off switches are named in both.
    monkeypatch.delenv("MAGOS_LANG")
    answering(mod, monkeypatch, done(b"", 1))
    message = verdict(tool_name="terminal", args={"command": "ls"}, **call_kw("zh"))["message"]
    assert "MAGOS 守卫" in message and "退出码 1" in message and all(switch in message for switch in OFF_SWITCHES)


# ---- TC-670: the gate probe fails closed ----------------------------------------------------------------------------------------------
def stub_hermes(monkeypatch, rule_key=True, field=True, yolo=False, mode="manual", presence=(None, True, False, False), raises=False):
    """Stub modules for the names the gate probe reads (tools.approval, tools.approval_context, hermes_cli.plugins), installed in the
    import table of this test process only."""
    tools, approval, context = (types.ModuleType(name) for name in ("tools", "tools.approval", "tools.approval_context"))
    hermes_cli, plugins = types.ModuleType("hermes_cli"), types.ModuleType("hermes_cli.plugins")

    def request_tool_approval(tool_name, reason, *, rule_key="", approval_callback=None):
        return {"approved": False}

    def request_tool_approval_old(tool_name, reason, *, approval_callback=None):
        return {"approved": False}

    def yolo_active():
        if raises:
            raise RuntimeError("renamed")
        return yolo

    @dataclass(frozen=True)
    class Directive:
        action: Optional[str] = None
        message: Optional[str] = None
        rule_key: Optional[str] = None

    @dataclass(frozen=True)
    class OldDirective:
        action: Optional[str] = None
        message: Optional[str] = None

    approval.request_tool_approval = request_tool_approval if rule_key else request_tool_approval_old
    approval._yolo_active = yolo_active
    approval._presence = lambda approval_callback=None: presence
    context._get_approval_mode = lambda: mode
    tools.approval, tools.approval_context = approval, context
    plugins._PreToolCallDirective = Directive if field else OldDirective
    hermes_cli.plugins = plugins
    for name, module in (("tools", tools), ("tools.approval", approval), ("tools.approval_context", context),
                         ("hermes_cli", hermes_cli), ("hermes_cli.plugins", plugins)):
        monkeypatch.setitem(sys.modules, name, module)


def test_the_gate_probe_fails_closed(monkeypatch):
    mod, _ = plugin()
    cases = [({"rule_key": False}, "absent"), ({"field": False}, "absent"), ({"yolo": True}, "bypass"), ({"mode": "off"}, "bypass"),
             ({"presence": (None, False, False, False)}, "bypass"), ({"raises": True}, "absent"), ({}, "ask"),
             ({"presence": (None, False, True, False)}, "ask"), ({"presence": (None, False, False, True)}, "ask")]
    for options, expected in cases:
        with monkeypatch.context() as patch:
            stub_hermes(patch, **options)
            assert mod.gate() == expected, options
    with monkeypatch.context() as patch:
        stub_hermes(patch)
        patch.setenv("HERMES_PLUGIN_HOST_PROCESS", "1")  # a plugin-host process: the probes would read another process
        assert mod.gate() == "absent"
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "tools", None)  # no tools package at all: the import fails
        assert mod.gate() == "absent"


# ---- TC-671: the payload has the shape of a Hermes shell-hook payload -----------------------------------------------------------------
def test_the_plugin_payload_has_the_shell_hook_shape(monkeypatch, tmp_path):
    mod, (verdict, _) = plugin()
    monkeypatch.setattr(mod, "gate", lambda: "ask")
    started = []

    def fake_run(argv, **kwargs):
        started.append((argv, kwargs))
        return done()
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    trace = object()
    args = {"command": "ls", "workdir": "/w"}
    assert verdict(tool_name="terminal", args=args, session_id="s", tool_call_id="c", turn_id="u",
                   middleware_trace=[trace, {("not", "a", "string"): 1, "lone": "\ud800"}]) is None
    (argv, kwargs), = started
    assert argv == [sys.executable, "-X", "utf8", "-B", str(ROOT / "scripts" / "magos_guard.py"), "hook", "hermes", "pre-tool",
                    "--hermes-gate", "ask"]
    assert kwargs["capture_output"] is True and kwargs["timeout"] == 25 and "shell" not in kwargs
    assert kwargs["creationflags"] == (subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    assert kwargs["env"] is None  # outside Hermes: the inherited environment
    payload = json.loads(kwargs["input"].decode("ascii"))
    assert payload == {"hook_event_name": "pre_tool_call", "tool_name": "terminal", "tool_input": args, "session_id": "s",
                       "tool_use_id": "c", "cwd": os.getcwd(),
                       "extra": {"tool_call_id": "c", "turn_id": "u", "middleware_trace": [str(trace), {"lone": "\ud800"}]}}

    # Hermes's active home reaches the child; a parent session id stands in for a missing session id; a lost directory is "".
    home = types.ModuleType("hermes_constants")
    home.get_hermes_home = lambda: tmp_path / "hermes home"
    monkeypatch.setitem(sys.modules, "hermes_constants", home)

    def lost():
        raise FileNotFoundError("the directory was removed")
    monkeypatch.setattr(mod.os, "getcwd", lost)
    verdict(tool_name="terminal", args={"command": "ls"}, parent_session_id="p", tool_call_id="c2")
    argv, kwargs = started[1]
    payload = json.loads(kwargs["input"].decode("ascii"))
    assert payload["session_id"] == "p" and payload["cwd"] == "" and payload["extra"] == {"tool_call_id": "c2"}
    assert kwargs["env"]["HERMES_HOME"] == str(tmp_path / "hermes home") and kwargs["env"]["MAGOS_LANG"] == "en"


# ---- TC-677: an approve directive never crosses calls -----------------------------------------------------------------------------------
def test_kept_approve_parts_never_cross_calls(monkeypatch):
    mod, callbacks = plugin()
    verdict, approval = callbacks
    monkeypatch.setattr(mod, "gate", lambda: "ask")
    key_a, key_b = "magos:arm:" + "a" * 32, "magos:disarm:" + "b" * 32
    answering(mod, monkeypatch, done(ask("A --approval=ta", "question A", key_a)), done(ask("B --approval=tb", "question B", key_b)))
    a, b = {"command": GUARD_CALL}, {"command": GUARD_CALL.replace("arm", "disarm")}
    kw_a, kw_b = call_kw("call_a"), call_kw("call_b")
    call_a, call_b = dict(a), dict(b)  # Hermes hands both callbacks of one call the same args object
    results_a = [verdict(tool_name="terminal", args=call_a, **kw_a)]
    results_b = [verdict(tool_name="terminal", args=call_b, **kw_b)]
    results_b.append(approval(tool_name="terminal", args=call_b, **kw_b))
    results_a.append(approval(tool_name="terminal", args=call_a, **kw_a))
    assert results_a == [{"action": "modify", "args": {"command": "A --approval=ta"}},
                         {"action": "approve", "message": "question A", "rule_key": key_a}]
    assert results_b == [{"action": "modify", "args": {"command": "B --approval=tb"}},
                         {"action": "approve", "message": "question B", "rule_key": key_b}]
    assert mod._KEPT == {}

    # Two interleaved calls alike in every keyword argument and in the command: each args object keeps its own mark.
    key_1, key_2 = "magos:arm:" + "1" * 32, "magos:arm:" + "2" * 32
    answering(mod, monkeypatch, done(ask("A1 --approval=t1", "question 1", key_1)), done(ask("A2 --approval=t2", "question 2", key_2)))
    one, two, kw = dict(a), dict(a), call_kw("call_same")
    assert verdict(tool_name="terminal", args=one, **kw) == {"action": "modify", "args": {"command": "A1 --approval=t1"}}
    assert verdict(tool_name="terminal", args=two, **kw) == {"action": "modify", "args": {"command": "A2 --approval=t2"}}
    assert approval(tool_name="terminal", args=two, **kw) == {"action": "approve", "message": "question 2", "rule_key": key_2}
    assert approval(tool_name="terminal", args=one, **kw) == {"action": "approve", "message": "question 1", "rule_key": key_1}
    assert mod._KEPT == {}

    # The same command in the same turn under another call id gets no mark of its own: the approval callback blocks it.
    blocked = approval(tool_name="terminal", args=dict(a), **call_kw("call_c"))
    assert blocked["action"] == "block" and "was not prepared" in blocked["message"]
    for spelled in ('py "C:/x/magos_gu""ard.py" arm', "py C:\\x\\MAGOS_GUARD.py arm", "py C:/x/magos_gu^ard.py arm"):
        assert approval(tool_name="terminal", args={"command": spelled}, **call_kw("call_d"))["action"] == "block", spelled
    assert approval(tool_name="terminal", args={"command": "ls"}, **call_kw("call_e")) is None
    assert approval(tool_name="terminal", args=None, **call_kw("call_f")) is None

    # A mark older than KEPT_S is dropped: its call's approval then blocks.
    answering(mod, monkeypatch, done(ask("A --approval=ta", "question A", key_a)))
    passed = consume(callbacks, a, kw_a, lambda m, k: True)
    assert passed.asked == [("question A", key_a)] and passed.runs == {"command": "A --approval=ta"}
    answering(mod, monkeypatch, done(ask("A --approval=ta", "question A", key_a)))
    late = dict(a)
    verdict(tool_name="terminal", args=late, **call_kw("late"))
    monkeypatch.setattr(mod, "KEPT_S", -1)
    assert approval(tool_name="terminal", args=late, **call_kw("late"))["action"] == "block"
    assert mod._KEPT == {}


# ---- TC-700: the verdict hands the guard the gate it probed --------------------------------------------------------------------------------
@pytest.mark.parametrize("probe,how", [({"yolo": True}, "hermes_how_session"), ({"mode": "off"}, "hermes_how_session"),
                                       ({"presence": (None, False, False, False)}, "hermes_how_session"), ({"raises": True}, "hermes_how_gate"),
                                       ({"rule_key": False}, "hermes_how_gate")])
def test_a_gate_that_would_not_ask_never_gets_a_question(tmp_path, monkeypatch, probe, how):
    mod, callbacks = plugin()
    stub_hermes(monkeypatch, **probe)  # the real probe reads the stubbed Hermes: bypass or absent
    r = new_repo(tmp_path / "r")
    cmd = {"command": "%s %s --repo '%s' --lang en arm" % (PY, QS, str(r.path).replace("\\", "/"))}
    out = consume(callbacks, cmd, call_kw("y1"), lambda message, rule_key: True)  # a gate that would approve without a human
    assert out.blocked == G.T("en", "protected_hermes_noask", why=G._USER_MSG, how=G.T("en", how)), out
    assert out.asked == [] and out.runs is None and not approvals(r).exists() and mod._KEPT == {}
