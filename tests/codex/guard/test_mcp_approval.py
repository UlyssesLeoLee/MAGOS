"""1.0.8 approval in Codex: the MCP approval server (`mcp`, its tool magos_approve, the elicitation form, the snapshot, the in-process run), the
Codex hook's denial that names the tool and its exact arguments, the deny of `mcp` on every host, the subcommand slot of a guard run, the
generated [mcp_servers.magos] entry and the Codex lines of doctor (TC-600 to TC-649, TC-683 to TC-697)."""
from __future__ import annotations

import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import SH, G, ROOT, SCRIPT, Result, crashed, retried, run, time_budget
from test_approval import LAUNCHER, P, QS, S, approvals, armed, audit_lines, common, new_repo, no_file_holds, sha
from test_hook import denied

WIN = sys.platform == "win32"
FORM = {"elicitation": {"form": {}, "url": {}}}
CLIENT = {"name": "fake-host", "version": "1"}
ACCEPT = {"action": "accept", "content": {"approve": True}}
SUBS = ["plan", "check", "list", "release", "override", "hook", "arm", "disarm", "install", "doctor", "version", "set-plan", "set-show", "set-update",
        "set-release"]


class Host:
    """A fake MCP host: the server in a thread of this process, joined to it by two OS pipes; it reads the server's lines into a queue."""

    def __init__(self, lang="en", runner=None):
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        self.out = os.fdopen(w1, "wb", buffering=0)
        self.inp = os.fdopen(r2, "rb")
        self.server = G.McpServer(os.fdopen(r1, "rb"), os.fdopen(w2, "wb", buffering=0), lang, runner=runner)
        self.codes, self.seen, self.box, self.ids = [], [], queue.Queue(), iter(range(100, 10 ** 6))
        self.thread = threading.Thread(target=lambda: self.codes.append(self.server.serve()), daemon=True)
        self.thread.start()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in iter(self.inp.readline, b""):
            self.seen.append(line)
            self.box.put(json.loads(line.decode("ascii")))
        self.box.put(None)

    def send(self, obj):
        self.out.write((json.dumps(obj) + "\n").encode("utf-8"))

    def send_raw(self, data):
        self.out.write(data)

    def request(self, method, params=None):
        ident = next(self.ids)
        self.send(dict({"jsonrpc": "2.0", "id": ident, "method": method}, **({"params": params} if params is not None else {})))
        return ident

    def notify(self, method, params=None):
        self.send(dict({"jsonrpc": "2.0", "method": method}, **({"params": params} if params is not None else {})))

    def next(self, timeout=60):
        try:
            return self.box.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("the server sent nothing within %s s" % timeout)

    def start(self, caps=None):
        i = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": FORM if caps is None else caps, "clientInfo": CLIENT})
        assert self.next()["id"] == i
        self.notify("notifications/initialized")

    def call(self, arguments, thread="th-1"):
        params = {"_meta": {"threadId": thread, "progressToken": 1}, "name": "magos_approve"}
        if arguments is not None:
            params["arguments"] = arguments
        return self.request("tools/call", params)

    def answer(self, eid, result):
        self.send({"jsonrpc": "2.0", "id": eid, "result": result})

    def dialog(self, arguments, thread="th-1"):
        """-> (call id, the elicitation/create request) for a call that opens a dialog."""
        cid = self.call(arguments, thread)
        msg = self.next()
        assert msg.get("method") == "elicitation/create", msg
        return cid, msg

    def result(self, cid):
        msg = self.next()
        assert msg.get("id") == cid and "result" in msg, msg
        res = msg["result"]
        assert res["content"] == [{"type": "text", "text": res["structuredContent"]["text"]}], res
        assert set(res["structuredContent"]) == {"approved", "exit_code", "text"}, res
        assert res["isError"] == (res["structuredContent"]["exit_code"] is None or res["structuredContent"]["exit_code"] != 0), res
        return res

    def pinged(self):
        """A ping is answered next: nothing else came before it."""
        i = self.request("ping")
        assert self.next() == {"jsonrpc": "2.0", "id": i, "result": {}}

    def close(self):
        if not self.out.closed:
            self.out.close()
        self.thread.join(30)
        for f in (self.server.rfile, self.server.wfile):
            try:
                f.close()
            except OSError:
                pass
        return self.codes[0] if self.codes else None


@pytest.fixture
def hosts():
    made = []

    def make(lang="en", runner=None, start=True, caps=None):
        h = Host(lang, runner)
        made.append(h)
        if start:
            h.start(caps)
        return h
    yield make
    for h in made:
        h.close()


def recording(log, code=0, text="did write", files_of=None):
    """A runner that records its argument list (and, with `files_of`, the files of that store when it is called) and returns (code, text)."""
    def runner(argv):
        log.append((list(argv), sorted(os.listdir(str(files_of))) if files_of is not None and Path(files_of).is_dir() else None))
        return code, text
    return runner


def arm_args(repo, **kw):
    return dict({"subcommand": "arm", "repo": P(repo.path)}, **kw)


def store_exists(*roots):
    return any(Path(r).exists() for r in roots)


def body(cwd, cmd, tool="Bash", **extra):
    b = {"session_id": "s-1", "turn_id": "t-1", "cwd": str(cwd) if cwd else None, "hook_event_name": "PreToolUse", "tool_name": tool,
         "tool_input": {"command": cmd}, "tool_use_id": "exec-1"}
    b.update(extra)
    return b


def hook(cwd, cmd, host="codex", tool="Bash", lang="en", extra_args=(), **extra):
    r = run(["--lang", lang, "hook", host, "pre-tool"] + list(extra_args), stdin=json.dumps(body(cwd, cmd, tool, **extra)).encode("utf-8"))
    assert r.rc == 0 and r.err == "" and r.out.isascii(), r
    return r


def codex_text(args, argv, lang="en"):
    return G.T(lang, "protected_codex", why=G._USER_MSG, call=json.dumps(args), ready=G.ready_command(argv))


def plan_denial(repo, guard):
    repo.branch_with("agent/x", "src/a.py")
    r = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert r.rc == 10, r
    return re.search(r"--fingerprint ([0-9a-f]{12})", r.out).group(1)


# ---- the server's protocol (TC-600 to TC-604) ----------------------------------------------------------------------------------------------
def test_mcp_is_a_hidden_subcommand(capsys):
    ap = G.build_parser("x")
    with pytest.raises(SystemExit):
        ap.parse_args(["-h"])
    shown = capsys.readouterr().out
    listed = "{%s}" % ",".join(SUBS)
    for text in (shown, ap.format_usage()):
        assert listed in text and "mcp" not in text and "SUPPRESS" not in text, text
    assert G.parse_quiet(["mcp"]).cmd == "mcp" and G.HOST_ONLY == ("mcp",)


def test_initialize_and_ping(hosts):
    h = hosts(start=False)
    for v, want in (("2025-06-18", "2025-06-18"), ("2025-11-25", "2025-11-25"), ("7", "2025-06-18")):
        i = h.request("initialize", {"protocolVersion": v, "capabilities": FORM, "clientInfo": CLIENT})
        assert h.next() == {"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": want, "capabilities": {"tools": {}},
                                                                   "serverInfo": {"name": "magos", "version": G.GUARD_VERSION}}}
    h.notify("notifications/initialized")
    h.send({"jsonrpc": "2.0", "id": "p", "method": "ping"})
    assert h.next() == {"jsonrpc": "2.0", "id": "p", "result": {}}  # the notification got no answer before it


def test_tools_list_names_one_tool_with_its_schema(hosts):
    h = hosts()
    i = h.request("tools/list", {})
    msg = h.next()
    assert msg["id"] == i and msg["result"] == {"tools": [G.MCP_TOOL_SPEC]}
    tool = G.MCP_TOOL_SPEC
    assert tool["name"] == "magos_approve" and tool["title"] == "MAGOS approval"
    schema = tool["inputSchema"]
    assert schema["required"] == ["subcommand"] and schema["additionalProperties"] is False and schema["type"] == "object"
    props = schema["properties"]
    assert {k: v["type"] for k, v in props.items()} == {"subcommand": "string", "repo": "string", "fingerprint": "string", "reason": "string",
                                                         "host": "string", "dry_run": "boolean"}
    assert props["subcommand"]["enum"] == ["override", "arm", "disarm", "install"] and props["host"]["enum"] == ["claude", "codex", "hermes"]
    assert props["fingerprint"]["pattern"] == "^[0-9a-f]{12}$"
    assert tool["annotations"] == {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}


def test_unknown_methods_and_tools(hosts):
    h = hosts()
    for method in ("resources/list", "resources/templates/list", "prompts/list", "x/y"):
        i = h.request(method, {})
        msg = h.next()
        assert msg["id"] == i and msg["error"]["code"] == -32601, msg
    h.notify("notifications/progress", {"progressToken": 1})
    h.notify("x")
    h.answer(99, {"x": 1})  # a response to no request of the server
    i = h.request("tools/call", {"name": "other", "arguments": {}})
    msg = h.next()
    assert msg["id"] == i and msg["error"]["code"] == -32602, msg


def test_framing_and_size_limit(hosts, monkeypatch):
    h = hosts()
    h.send_raw(b"\n")
    for raw, code in ((b"{not json\n", -32700), (b"\xff\xfe\n", -32700), (b"[1,2]\n", -32600), (b'"x"\n', -32600),
                      (b'{"id": 1, "method": "ping"}\n', -32600), (b'{"jsonrpc": "2.0", "id": true, "method": "ping"}\n', -32600),
                      (b'{"jsonrpc": "2.0", "id": 3, "method": 5}\n', -32600)):
        h.send_raw(raw)
        msg = h.next()
        assert msg["id"] is None and msg["error"]["code"] == code, (raw, msg)
    h.send_raw(b'{"jsonrpc": "2.0", "id": 7, "method": "ping"}\r\n')
    assert h.next() == {"jsonrpc": "2.0", "id": 7, "result": {}}
    monkeypatch.setattr(G, "MCP_LINE", 200)  # read by a reader that starts after the patch
    h2 = hosts(start=False)
    h2.send_raw(b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"x": "' + b"y" * 1000 + b'"}}\n')
    msg = h2.next()
    assert msg["id"] is None and msg["error"]["code"] == -32600, msg
    h2.pinged()


# ---- the tool call: arguments and the command line (TC-605 to TC-608) ---------------------------------------------------------------------
def test_arguments_are_validated_before_any_dialog(hosts, repo, isolated_env):
    r, fp = P(repo.path), "0123456789ab"
    over = {"subcommand": "override", "repo": r, "fingerprint": fp, "reason": "ok"}
    cases = [
        (None, ["subcommand"]), ({"subcommand": "rm"}, ["subcommand"]), (arm_args(repo, x=1), ["x"]), (arm_args(repo, host="codex"), ["host"]),
        (arm_args(repo, fingerprint=fp), ["fingerprint"]), ({"subcommand": "override", "repo": r}, ["fingerprint", "reason"]),
        (dict(over, fingerprint="ABCDEF012345"), ["fingerprint"]), (dict(over, fingerprint="0123"), ["fingerprint"]),
        (dict(over, reason=""), ["reason"]), (dict(over, reason="   "), ["reason"]), (dict(over, dry_run=True), ["dry_run"]),
        ({"subcommand": "install"}, ["host"]), ({"subcommand": "install", "host": "vim"}, ["host"]), (dict(arm_args(repo), repo=5), ["repo"]),
        (arm_args(repo, dry_run="yes"), ["dry_run"]), (dict(over, reason="r" * 4097), ["reason"]),
    ] + [(dict(over, reason="a%sb" % ch), ["reason"]) for ch in ("\0", "\x1b", "\ud800")]
    h = hosts(runner=recording([]))
    for arguments, keys in cases:
        res = h.result(h.call(arguments))  # the call's own result comes first: no elicitation/create
        sc = res["structuredContent"]
        assert res["isError"] is True and sc["approved"] is False and sc["exit_code"] is None, (arguments, res)
        head = G.T("en", "mcp_invalid", errors="\0").split("\0")[0]
        assert sc["text"].startswith(head), sc["text"]
        named = [line.strip().split(":")[0] for line in sc["text"].splitlines() if line.startswith("  ")]
        assert all(k in named for k in keys), (arguments, sc["text"])
    assert not store_exists(approvals(repo), isolated_env / ".magos" / "approvals")


def test_repo_must_be_an_absolute_existing_directory(hosts, repo, tmp_path):
    (repo.path / "f.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    bad = ["src", "~/r", P(repo.path / "f.txt"), P(tmp_path / "missing")] + (["C:r", "/xy/z"] if WIN else [])
    for spelling in bad:
        assert G.mcp_validate({"subcommand": "arm", "repo": spelling}, "en") == (None, ["repo: not the absolute path of an existing directory"]), spelling
    assert G.mcp_validate({"subcommand": "arm", "repo": P(outside)}, "en") == (None, ["repo: not a git repository"])
    if WIN:
        upper = str(repo.path).upper()
        bash = "/%s/%s" % (P(repo.path)[0].lower(), P(repo.path)[3:])
        for spelling, want in ((upper, os.path.normpath(upper).replace("\\", "/")), (bash, P(repo.path))):
            v, errors = G.mcp_validate({"subcommand": "arm", "repo": spelling}, "en")
            assert errors is None and v["argv"][0] == "--repo=" + want, (spelling, v, errors)
    plan, errors = G.mcp_plan({"subcommand": "install", "host": "codex", "repo": P(outside)}, "en")
    assert errors is None and plan["level"] == "prompt" and plan["argv"] == ["--lang=en", "install", "--host=codex"]
    h = hosts(runner=recording([]))
    for arguments in ({"subcommand": "install", "host": "codex", "repo": P(outside)},
                      {"subcommand": "override", "repo": P(repo.path), "fingerprint": "0123456789ab", "reason": "a\tb"}):
        cid, _msg = h.dialog(arguments)
        h.answer(_msg["id"], {"action": "decline"})
        assert h.result(cid)["structuredContent"]["approved"] is False


def test_the_command_line_is_built_from_single_word_options(repo):
    r, fp = P(repo.path), "0123456789ab"
    for reason in ("--repo /evil", "-x", "--approval=" + "A" * 43, "a=b", 'it\'s "ok"', "用户同意"):
        v, errors = G.mcp_validate({"subcommand": "override", "repo": r, "fingerprint": fp, "reason": reason}, "en")
        assert errors is None and v["argv"] == ["--repo=" + r, "--lang=en", "override", "--fingerprint=" + fp, "--reason=" + reason], (reason, v)
    rows = [({"subcommand": "arm", "repo": r, "dry_run": True}, ["--repo=" + r, "--lang=en", "arm", "--dry-run"]),
            ({"subcommand": "disarm", "repo": r, "dry_run": False}, ["--repo=" + r, "--lang=en", "disarm"]),
            ({"subcommand": "install", "host": "codex", "dry_run": True}, ["--lang=en", "install", "--host=codex", "--dry-run"])]
    for arguments, want in rows:
        v, errors = G.mcp_validate(arguments, "en")
        assert errors is None and v["argv"] == want, (arguments, v)
        ns = G.parse_quiet(want + ["--approval=" + "B" * 43])
        assert G.user_only_row(ns).name == arguments["subcommand"] and ns.approval == "B" * 43 and ns.lang == "en"
        assert getattr(ns, "dry_run", False) == bool(arguments.get("dry_run")) and "--" not in want
        assert not [w for w in want if w.startswith("--approval")]
    v, _e = G.mcp_validate({"subcommand": "override", "repo": r, "fingerprint": fp, "reason": "--repo /evil"}, "en")
    ns = G.parse_quiet(v["argv"] + ["--approval=" + "B" * 43])
    assert ns.reason == "--repo /evil" and ns.repo == r and ns.fingerprint == fp


def test_a_command_line_the_parser_reads_otherwise_is_refused(repo, monkeypatch):
    real = G.parse_quiet
    for field, value in (("reason", "other"), ("approval", "B" * 43)):
        def changed(words, field=field, value=value):
            ns = real(words)
            setattr(ns, field, value)
            return ns
        monkeypatch.setattr(G, "parse_quiet", changed)
        arguments = {"subcommand": "override", "repo": P(repo.path), "fingerprint": "0123456789ab", "reason": "ok"}
        assert G.mcp_validate(arguments, "en") == (None, ["the guard's parser reads these arguments otherwise"])
        assert G.mcp_plan(arguments, "en") == (None, ["the guard's parser reads these arguments otherwise"])


# ---- levels, the form and the dialog (TC-609 to TC-612) -----------------------------------------------------------------------------------
def test_a_client_without_an_elicitation_form_gets_the_terminal(hosts, repo):
    ready = G.ready_command(["--repo=" + P(repo.path), "--lang=en", "arm"])
    for caps in ({}, {"elicitation": {"url": {}}}):
        log = []
        h = hosts(runner=recording(log), caps=caps)
        res = h.result(h.call(arm_args(repo)))
        assert res["structuredContent"]["text"] == G.T("en", "mcp_no_form", ready=ready) and res["isError"] is True
        assert log == [] and not approvals(repo).exists()


def test_level_terminal_opens_no_dialog(hosts, repo):
    ready = G.ready_command(["--repo=" + P(repo.path), "--lang=en", "arm"])
    h = hosts(runner=recording([]))
    for value in ("terminal", "nonsense"):
        repo.git("config", "magos.approval", value)
        res = h.result(h.call(arm_args(repo)))
        assert res["structuredContent"]["text"] == G.T("en", "mcp_terminal", sub="arm", ready=ready), res
    assert not approvals(repo).exists()


def test_auto_safe_asks_in_the_mcp_route(hosts, repo, isolated_env):
    repo.git("config", "magos.approval", "auto-safe")
    log = []
    h = hosts(runner=recording(log))
    for k, (arguments, root) in enumerate(((arm_args(repo), approvals(repo)), ({"subcommand": "install", "host": "codex", "repo": P(repo.path)},
                                                                             isolated_env / ".magos" / "approvals"))):
        cid, msg = h.dialog(arguments)
        assert len(log) == k  # nothing ran before the answer
        h.answer(msg["id"], ACCEPT)
        assert h.result(cid)["structuredContent"]["exit_code"] == 0
        recs = [json.loads(p.read_text(encoding="utf-8")) for p in Path(root).glob("*.json")]
        assert len(recs) == 1 and recs[0]["via"] == "prompt", recs
    assert len(log) == 2


def test_the_dialog_request_and_its_text(hosts, repo, guard, isolated_env):
    g = G.open_repo(str(repo.path))
    h = hosts(runner=recording([]))
    _cid, msg = h.dialog(arm_args(repo))
    assert isinstance(msg["id"], int) and set(msg["params"]) == {"mode", "message", "requestedSchema"} and msg["params"]["mode"] == "form"
    assert msg["params"]["requestedSchema"] == {"type": "object", "properties": {"approve": {"type": "boolean", "title": "Approve",
                                                "description": G.T("en", "mcp_approve_field")}}, "required": ["approve"]}
    assert '"default"' not in json.dumps(msg)
    assert msg["params"]["message"].split("\n") == [
        "MAGOS: approve the user-only guard command arm?",
        'Repository: %s (Git directory %s)' % (json.dumps(P(os.path.realpath(G.repo_dir(g)))), json.dumps(P(os.path.realpath(g.common)))),
        G.T("en", "approval_what_arm", repo=json.dumps(G.repo_dir(g)), dry=""),
        "Tick Approve, then Accept: that approves exactly this, once. Anything else runs nothing."]
    h.answer(msg["id"], {"action": "cancel"})
    h.next()
    hz = hosts(lang="zh", runner=recording([]))
    _cid, msg = hz.dialog({"subcommand": "install", "host": "codex"})
    lines = msg["params"]["message"].split("\n")
    assert lines[1] == G.T("zh", "mcp_where_home", home=json.dumps(G.guard_home(), ensure_ascii=False)), lines
    assert msg["params"]["requestedSchema"]["properties"]["approve"]["description"] == G.T("zh", "mcp_approve_field")
    hz.answer(msg["id"], {"action": "cancel"})
    hz.next()
    fp = plan_denial(repo, guard)
    _cid, msg = h.dialog({"subcommand": "override", "repo": P(repo.path), "fingerprint": fp, "reason": "the user agreed"})
    text = msg["params"]["message"]
    assert '"agent/new"' in text and '"main"' in text and '"agent/x"' in text and 'Reason written by the agent: "the user agreed"' in text, text


# ---- the run on Accept (TC-613 to TC-631) -------------------------------------------------------------------------------------------------
def test_accept_mints_the_record_and_runs_the_snapshot(hosts, repo):
    log = []
    h = hosts(runner=recording(log, files_of=approvals(repo)))
    cid, msg = h.dialog(arm_args(repo), thread="th-1")
    assert not approvals(repo).exists() and log == []
    h.answer(msg["id"], ACCEPT)
    res = h.result(cid)
    (argv, files), = log
    assert argv[:-1] == ["--repo=" + P(repo.path), "--lang=en", "arm"] and re.fullmatch(r"--approval=[A-Za-z0-9_-]{43}", argv[-1])
    token = argv[-1][len("--approval="):]
    assert files == [sha(token) + ".json"]
    rec = json.loads((approvals(repo) / (sha(token) + ".json")).read_text(encoding="utf-8"))
    assert rec["v"] == 1 and rec["sub"] == "arm" and rec["argv"] == argv[:-1] and os.path.samefile(rec["where"], str(common(repo)))
    assert rec["via"] == "prompt" and rec["tool_use_id"] is None and rec["session_id"] == "th-1" and rec["command_sha256"] is None
    assert rec["used"] is False and rec["route"] == "mcp" and rec["client"] == "fake-host/1" and rec["expires"] - rec["created"] == pytest.approx(120)
    sc = res["structuredContent"]
    assert res["isError"] is False and sc["approved"] is True and sc["exit_code"] == 0
    assert sc["text"] == G.T("en", "mcp_ran", sub="arm", code=0, out="did write")


def test_accept_runs_the_guard_in_process(hosts, repo, monkeypatch, isolated_env, tmp_path):
    calls = []
    monkeypatch.setattr(G, "challenge", lambda *a, **k: calls.append("challenge"))
    monkeypatch.setattr(G, "user_console", lambda: calls.append("console"))
    tokens = []

    def runner(argv):
        tokens.append(argv[-1][len("--approval="):])
        return G.mcp_command(argv)
    h = hosts(runner=runner)
    hook_file = common(repo) / "hooks" / "reference-transaction"
    for sub in ("arm", "disarm"):
        cid, msg = h.dialog({"subcommand": sub, "repo": P(repo.path)})
        h.answer(msg["id"], ACCEPT)
        res = h.result(cid)
        assert res["structuredContent"]["exit_code"] == 0, res
        assert armed(repo) == (sub == "arm") and hook_file.exists() == (sub == "arm")
    assert calls == []
    lines = [x for x in audit_lines(common(repo) / "magos") if x["op"] in ("arm", "disarm")]
    assert [(x["op"], x["via"], x["tool_use_id"], x["route"], x["client"]) for x in lines] == [
        ("arm", "prompt", None, "mcp", "fake-host/1"), ("disarm", "prompt", None, "mcp", "fake-host/1")]
    assert sorted(p.name for p in approvals(repo).iterdir()) == sorted(sha(t) + ".used" for t in tokens)
    for t in tokens:
        assert all(t.encode("ascii") not in line for line in h.seen)
        no_file_holds(t, common(repo) / "magos", isolated_env, tmp_path)


ANSWERS = [  # (answer, key): Accept forms without approve true, the other actions, a result that is no object and an error answer
    ({"result": {"action": "accept", "content": {}}}, "mcp_unticked"), ({"result": {"action": "accept", "content": {"approve": False}}}, "mcp_unticked"),
    ({"result": {"action": "accept", "content": {"approve": "true"}}}, "mcp_unticked"), ({"result": {"action": "accept", "content": {"approve": 1}}}, "mcp_unticked"),
    ({"result": {"action": "accept", "content": {"x": True}}}, "mcp_unticked"), ({"result": {"action": "accept"}}, "mcp_unticked"),
    ({"result": {"action": "accept", "content": None}}, "mcp_unticked"), ({"result": {"action": "accept", "content": [True]}}, "mcp_unticked"),
    ({"result": {"action": "decline"}}, "decline"), ({"result": {"action": "cancel"}}, "cancel"), ({"result": {"action": "maybe"}}, "maybe"),
    ({"result": "x"}, "mcp_failed"), ({"error": {"code": -1, "message": "no"}}, "mcp_failed"),
]


def test_only_accept_with_approve_true_runs(hosts, repo):
    log = []
    h = hosts(runner=recording(log))
    ready = G.ready_command(["--repo=" + P(repo.path), "--lang=en", "arm"])
    for ans, key in ANSWERS:
        cid, msg = h.dialog(arm_args(repo))
        h.send(dict({"jsonrpc": "2.0", "id": msg["id"]}, **ans))
        sc = h.result(cid)["structuredContent"]
        assert sc["exit_code"] is None and sc["approved"] is False, (ans, sc)
        if key == "mcp_unticked":
            assert sc["text"] == G.T("en", "mcp_unticked", sub="arm", ready=ready), sc
        elif key == "mcp_failed":
            head, tail = G.T("en", "mcp_failed", sub="arm", err="\0", ready=ready).split("\0")
            assert sc["text"].startswith(head + "the dialog ended with an error") and sc["text"].endswith(tail), sc
        else:
            assert sc["text"] == G.T("en", "mcp_refused", sub="arm", action='"%s"' % key, ready=ready), sc
    assert log == [] and not approvals(repo).exists()


def test_a_cancelled_call_runs_nothing(hosts, repo):
    log = []
    h = hosts(runner=recording(log))
    cid, msg = h.dialog(arm_args(repo))
    h.notify("notifications/cancelled", {"requestId": cid, "reason": "user interrupted"})
    assert h.next() == {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": msg["id"], "reason": "the tool call was cancelled"}}
    h.answer(msg["id"], ACCEPT)
    h.pinged()  # the cancelled call got no answer and the late Accept ran nothing
    assert log == [] and not approvals(repo).exists()
    _cid2, msg2 = h.dialog(arm_args(repo))
    assert msg2["id"] == msg["id"] + 1


def test_no_answer_in_time_withdraws_the_dialog(hosts, repo, monkeypatch):
    monkeypatch.setattr(G, "MCP_CLICK_S", 0.5)
    log = []
    h = hosts(runner=recording(log))
    cid, msg = h.dialog(arm_args(repo))
    t0, stop = time.monotonic(), []

    def pings():
        while not stop:
            h.request("ping")
            time.sleep(0.1)
    threading.Thread(target=pings, daemon=True).start()
    got = []
    try:
        while not any(m.get("id") == cid for m in got):
            got.append(h.next(10))
    finally:
        stop.append(1)
    elapsed = time.monotonic() - t0
    assert 0.4 <= elapsed <= time_budget(1), elapsed
    assert {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": msg["id"], "reason": "no answer within 0.5 s"}} in got
    ready = G.ready_command(["--repo=" + P(repo.path), "--lang=en", "arm"])
    assert got[-1]["result"]["structuredContent"]["text"] == G.T("en", "mcp_late", sub="arm", s=0.5, ready=ready)
    assert any(m.get("result") == {} for m in got)  # the pings were answered meanwhile
    time.sleep(0.3)
    h.answer(msg["id"], ACCEPT)
    time.sleep(0.3)
    assert log == [] and not approvals(repo).exists()


def test_one_dialog_at_a_time(hosts, repo):
    log = []
    h = hosts(runner=recording(log))
    cid, msg = h.dialog(arm_args(repo))
    res = h.result(h.call({"subcommand": "disarm", "repo": P(repo.path)}))
    assert res["structuredContent"]["text"] == G.T("en", "mcp_busy") and res["isError"] is True
    h.pinged()
    h.answer(msg["id"], ACCEPT)
    assert h.result(cid)["structuredContent"]["exit_code"] == 0
    assert [argv[2] for argv, _f in log] == ["arm"]


def test_end_of_input_runs_nothing(hosts, repo):
    log = []
    h = hosts(runner=recording(log))
    h.dialog(arm_args(repo))
    assert h.close() == 0 and log == [] and not approvals(repo).exists()


def test_nothing_is_read_again_after_the_click(hosts, repo, guard, monkeypatch):
    fp = plan_denial(repo, guard)
    log = []
    h = hosts(runner=recording(log))
    arguments = {"subcommand": "override", "repo": P(repo.path), "fingerprint": fp, "reason": "ok"}
    cid, msg = h.dialog(arguments)
    snapshot = G.mcp_validate(arguments, "en")[0]["argv"]
    repo.git("config", "magos.approval", "terminal")
    path = common(repo) / "magos" / "denials" / (fp + ".json")
    path.write_text(json.dumps(dict(json.loads(path.read_text(encoding="utf-8")), lane="agent/other")), encoding="utf-8")
    reads = []
    for name in ("approval_level", "denial_record", "open_repo"):
        monkeypatch.setattr(G, name, lambda *a, name=name, **k: reads.append(name))
    h.answer(msg["id"], ACCEPT)
    res = h.result(cid)
    assert reads == [] and [argv[:-1] for argv, _f in log] == [snapshot]
    assert res["structuredContent"]["text"] == G.T("en", "mcp_ran", sub="override", code=0, out="did write")
    assert '"agent/new"' in msg["params"]["message"] and "agent/other" not in msg["params"]["message"]


def test_output_is_scrubbed_and_capped(hosts, repo):
    def runner(argv):
        return 0, argv[-1][len("--approval="):] + "x" * 20000
    h = hosts(runner=runner)
    cid, msg = h.dialog(arm_args(repo))
    h.answer(msg["id"], ACCEPT)
    text = h.result(cid)["structuredContent"]["text"]
    out = ("<redacted>" + "x" * 20000)
    assert text == G.T("en", "mcp_ran", sub="arm", code=0, out=out[:8000] + "\n... (%d more characters)" % (len(out) - 8000))
    assert not re.search(r"[A-Za-z0-9_-]{43}", text.replace("x" * 43, ""))


def test_a_failing_command_is_an_error_result(hosts, repo):
    repo.git("config", "core.hooksPath", "elsewhere")
    h = hosts(runner=G.mcp_command)
    cid, msg = h.dialog(arm_args(repo))
    h.answer(msg["id"], ACCEPT)
    res = h.result(cid)
    sc = res["structuredContent"]
    assert res["isError"] is True and sc["approved"] is True and sc["exit_code"] == 3 and "arm refused" in sc["text"], res
    assert sc["text"].startswith(G.T("en", "mcp_ran", sub="arm", code=3, out=""))


def test_a_record_that_cannot_be_written_runs_nothing(hosts, repo):
    (common(repo) / "magos").mkdir(parents=True, exist_ok=True)
    approvals(repo).write_text("a file, not the store\n", encoding="utf-8")
    log = []
    h = hosts(runner=recording(log))
    cid, msg = h.dialog(arm_args(repo))
    h.answer(msg["id"], ACCEPT)
    sc = h.result(cid)["structuredContent"]
    assert sc["exit_code"] is None and "the approval could not be recorded (" in sc["text"] and sc["text"].startswith("MAGOS: arm did not run: ")
    assert log == []


def test_an_internal_failure_is_answered_and_the_session_goes_on(hosts, repo, monkeypatch):
    def runner(argv):
        raise RuntimeError("boom")
    h = hosts(runner=runner)
    cid, msg = h.dialog(arm_args(repo))
    h.answer(msg["id"], ACCEPT)
    sc = h.result(cid)["structuredContent"]
    assert sc["exit_code"] is None and "RuntimeError: boom" in sc["text"] and sc["text"].startswith("MAGOS: arm did not run: ")

    def broken(self, ident, params):
        raise KeyError("x")
    monkeypatch.setattr(G.McpServer, "_list", broken)
    i = h.request("tools/list", {})
    assert h.next() == {"jsonrpc": "2.0", "id": i, "error": {"code": -32603, "message": "Internal error: KeyError"}}
    h.pinged()


def test_only_the_protocol_reaches_stdout(monkeypatch):
    seen, real_validate, real_serve = [], G.mcp_validate, G.McpServer.serve

    def validate(arguments, lang):
        G.out_text("stray")
        return real_validate(arguments, lang)

    def serve(self):
        seen.append((sys.stdout, sys.stderr))
        return real_serve(self)
    monkeypatch.setattr(G, "mcp_validate", validate)
    monkeypatch.setattr(G.McpServer, "serve", serve)
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": FORM, "clientInfo": CLIENT}},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "magos_approve", "arguments": {"subcommand": "rm"}}}]
    out, err = io.BytesIO(), io.BytesIO()
    held = sys.stdin, sys.stdout, sys.stderr
    fout = io.TextIOWrapper(out, encoding="utf-8", write_through=True)
    ferr = io.TextIOWrapper(err, encoding="utf-8", write_through=True)
    sys.stdin = io.TextIOWrapper(io.BytesIO(b"".join(json.dumps(m).encode("ascii") + b"\n" for m in lines)), encoding="utf-8")
    sys.stdout, sys.stderr = fout, ferr
    try:
        rc = G.main(["--lang", "en", "mcp"])
        after = sys.stdout
    finally:
        fout.flush()
        ferr.flush()
        sys.stdin, sys.stdout, sys.stderr = held
    got = [json.loads(x) for x in out.getvalue().decode("ascii").splitlines()]
    assert rc == 0 and [m["id"] for m in got] == [1, 2, 3] and all(m["jsonrpc"] == "2.0" for m in got)
    assert "stray" in err.getvalue().decode("utf-8") and b"stray" not in out.getvalue()
    assert seen and seen[0][0] is seen[0][1] is ferr and after is fout


def test_a_host_that_cannot_be_written_ends_the_server():
    class Broken:
        def write(self, data):
            raise OSError("the pipe is gone")

        def flush(self):
            pass
    assert G.McpServer(io.BytesIO(b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n'), Broken(), "en").serve() == 1


def test_the_runner_captures_and_restores_the_streams(repo):
    held = sys.stdin, sys.stdout, sys.stderr
    code, text = G.mcp_command(["--repo=" + P(repo.path), "--lang=en", "arm", "--bogus"])
    assert code == 2 and "unrecognized arguments: --bogus" in text and (sys.stdin, sys.stdout, sys.stderr) == held
    code, text = G.mcp_command(["--repo=" + P(repo.path), "--lang=en", "arm", "--dry-run"])
    assert code == 0 and "would write" in text and (sys.stdin, sys.stdout, sys.stderr) == held
    assert all(a is b for a, b in zip((sys.stdin, sys.stdout, sys.stderr), held))


class Proc:
    """The server as its own process, as Codex starts it: one JSON-RPC message per line on its pipes."""

    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-B", str(SCRIPT), "--lang", "en", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=os.environ.copy(), creationflags=0x08000000 if WIN else 0)
        self.box, self.lines = queue.Queue(), []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in iter(self.p.stdout.readline, b""):
            self.lines.append(line)
            self.box.put(json.loads(line.decode("ascii")))

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def next(self):
        return self.box.get(timeout=120)

    def finish(self):
        self.p.stdin.close()
        rc = self.p.wait(120)
        err = self.p.stderr.read().decode("utf-8", "replace")
        return Result(rc, b"".join(self.lines).decode("ascii"), err)


def approve_in_process(arguments):
    """initialize, one tools/call, Accept, end of input -> (Result, the call's result)."""
    def once():
        s = Proc()
        s.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": FORM, "clientInfo": CLIENT}})
        assert s.next()["id"] == 1
        s.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        s.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "magos_approve", "arguments": arguments}})
        msg = s.next()
        assert msg.get("method") == "elicitation/create", msg
        s.send({"jsonrpc": "2.0", "id": msg["id"], "result": ACCEPT})
        res = s.next()
        return s.finish(), res, msg
    return retried(once, lambda r: crashed(r[0].out + r[0].err, r[0].rc))


def test_end_to_end_subprocess_arm(repo):
    r, res, _msg = approve_in_process(arm_args(repo))
    assert r.rc == 0 and r.err == "" and armed(repo), r
    assert res["id"] == 2 and res["result"]["structuredContent"]["exit_code"] == 0
    assert all(json.loads(line) for line in r.out.splitlines()) and "--approval=" not in r.out + r.err


def test_end_to_end_subprocess_override_then_replan(repo, guard):
    fp = plan_denial(repo, guard)
    r, res, msg = approve_in_process({"subcommand": "override", "repo": P(repo.path), "fingerprint": fp, "reason": "the user agreed"})
    assert r.rc == 0 and res["result"]["structuredContent"]["exit_code"] == 0 and '"agent/x"' in msg["params"]["message"], (r, res)
    rec = json.loads((common(repo) / "magos" / "override" / (fp + ".json")).read_text(encoding="utf-8"))
    assert rec["reason_by"] == "agent" and rec["via"] == "prompt" and rec["reason"] == "the user agreed"
    line = [x for x in audit_lines(common(repo) / "magos") if x["op"] == "override"][-1]
    assert line["route"] == "mcp" and line["client"] == "fake-host/1" and line["tool_use_id"] is None and line["host"] == "cli"
    again = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py", "--json")
    assert again.rc == 0 and json.loads(again.out)["code"] == "OVERRIDDEN", again


def test_install_through_the_server(hosts, isolated_env):
    h = hosts(runner=G.mcp_command)
    cid, msg = h.dialog({"subcommand": "install", "host": "codex"})
    h.answer(msg["id"], ACCEPT)
    assert h.result(cid)["structuredContent"]["exit_code"] == 0
    home = isolated_env / ".magos"
    assert (home / "guard" / "scripts" / "magos_guard.py").read_bytes() == SCRIPT.read_bytes()
    used = list((home / "approvals").glob("*.used"))
    assert len(used) == 1 and json.loads(used[0].read_text(encoding="utf-8"))["where"] == G.guard_home()
    last = audit_lines(home)[-1]
    assert last["op"] == "install" and last["via"] == "prompt" and last["route"] == "mcp" and last["client"] == "fake-host/1"


def test_each_call_has_its_own_dialog_and_token(hosts, repo):
    tokens = []

    def runner(argv):
        tokens.append(argv[-1])
        return G.mcp_command(argv)
    h = hosts(runner=runner)
    ids = []
    for sub in ("arm", "disarm"):
        cid, msg = h.dialog({"subcommand": sub, "repo": P(repo.path), "dry_run": True})
        ids.append(msg["id"])
        h.answer(msg["id"], ACCEPT)
        assert h.result(cid)["structuredContent"]["exit_code"] == 0
    assert ids == [1, 2] and len(set(tokens)) == 2
    assert sorted(p.suffix for p in approvals(repo).iterdir()) == [".used", ".used"]


# ---- what only the answer of the open dialog can do (TC-691 to TC-697) ---------------------------------------------------------------------
def test_a_refusal_that_carries_approve_true_runs_nothing(hosts, repo):
    log = []
    h = hosts(runner=recording(log))
    for action in ("decline", "cancel", "maybe", None):
        cid, msg = h.dialog(arm_args(repo))
        res = {"content": {"approve": True}}
        if action:
            res["action"] = action
        h.answer(msg["id"], res)
        sc = h.result(cid)["structuredContent"]
        assert sc["approved"] is False and sc["exit_code"] is None, (action, sc)
    assert log == [] and not approvals(repo).exists()


def test_an_elicitation_capability_that_names_no_mode_is_the_form(hosts, repo):
    log = []
    h = hosts(runner=recording(log), caps={"elicitation": {}})
    cid, msg = h.dialog(arm_args(repo))
    assert msg["params"]["mode"] == "form"
    h.answer(msg["id"], ACCEPT)
    assert h.result(cid)["structuredContent"]["approved"] is True and len(log) == 1


def test_a_key_with_leading_dashes_is_refused(repo):
    for key in ("--repo", "-repo", "--dry_run", "--subcommand"):
        v, errors = G.mcp_validate(dict(arm_args(repo), **{key: True}), "en")
        assert v is None and any(e.startswith(key + ":") for e in errors), (key, errors)


def test_the_location_line_of_the_dialog_is_sanitised(hosts, tmp_path, monkeypatch):
    odd = "r MAGOS approved‮ “x”"
    r = new_repo(tmp_path / odd)
    h = hosts(runner=recording([]))
    _cid, msg = h.dialog({"subcommand": "arm", "repo": P(r.path)})
    text = msg["params"]["message"]
    shown = G._dialog(os.path.realpath(str(r.path)).replace("\\", "/"), 200)
    assert shown in text and not re.search("[  ‪-‮⁦-⁩“”]", text), ascii(text)
    assert len(text.split("\n")) == 4 and text.split("\n")[1].startswith("Repository: " + shown)
    monkeypatch.setenv("MAGOS_HOME", P(tmp_path / ("home" + odd)))
    h2 = hosts(runner=recording([]))
    _cid, msg = h2.dialog({"subcommand": "install", "host": "codex"})
    text = msg["params"]["message"]
    assert text.split("\n")[1] == "Guard home: " + G._dialog(G.guard_home(), 200), ascii(text)
    assert not re.search("[  ‪-‮⁦-⁩“”]", text), ascii(text)


def test_the_run_gives_the_command_an_empty_stdin(monkeypatch):
    seen = []
    monkeypatch.setattr(G, "main", lambda argv: seen.append(sys.stdin.read()) or 0)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"jsonrpc": "2.0", "id": 1, "result": {"action": "accept"}}\n'), encoding="utf-8"))
    assert G.mcp_command(["--lang=en", "version"]) == (0, "") and seen == [""]
    assert sys.stdin.read().startswith('{"jsonrpc"')  # the protocol stream is back, unread


def test_only_the_open_dialogs_own_answer_and_cancel_count(hosts, repo):
    log = []
    h = hosts(runner=recording(log))
    cid, msg = h.dialog(arm_args(repo))
    assert msg["id"] == 1
    for other in (2, "1", True, None):  # another request id, a string, a boolean equal to 1, no id
        h.send({"jsonrpc": "2.0", "id": other, "result": ACCEPT})
        h.pinged()
    h.notify("notifications/cancelled", {"requestId": cid + 50, "reason": "another call"})
    h.notify("notifications/cancelled", {"requestId": True})
    h.pinged()
    assert log == []
    h.answer(msg["id"], ACCEPT)
    h.request("ping")
    assert h.next().get("id") == cid and len(log) == 1  # the dialog was still open: its Accept ran


def test_the_wait_for_the_click_is_120_seconds(hosts, repo, monkeypatch):
    real, skew = time.monotonic, [0.0]
    monkeypatch.setattr(G.time, "monotonic", lambda: real() + skew[0])
    log = []
    h = hosts(runner=recording(log))
    cid, msg = h.dialog(arm_args(repo))
    skew[0] = 118.0
    h.pinged()  # within 120 s: the dialog stays open
    skew[0] = 121.0
    h.request("ping")
    got = [h.next(10), h.next(10), h.next(10)]
    assert {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": msg["id"], "reason": "no answer within 120 s"}} in got
    late = next(m for m in got if m.get("id") == cid)
    assert "within 120 s" in late["result"]["structuredContent"]["text"] and G.MCP_CLICK_S == 120 and log == []


# ---- the mcp deny and the Codex hook (TC-632 to TC-637) ----------------------------------------------------------------------------------
def test_the_tamper_filter_reads_mcp_in_every_spelling():
    launcher = P(LAUNCHER)
    for text in ("python magos_guard.py mcp", "py -3 %s mcp" % S, "%s --repo x mcp" % S, "%s --lang=en mcp" % S, "%s -- mcp" % S, "%s m\\cp" % S,
                 "%s 'mcp'" % S, "bash -c 'python3 %s mcp'" % S, "cmd /c py %s mcp" % S, 'powershell -Command "py %s mcp"' % S,
                 "Start-Process py -ArgumentList '-3','%s','mcp'" % S, "Start-Process py %s,mcp" % S, "Start-Process py -ArgumentList '-3 %s mcp'" % S,
                 "cat x && py %s mcp" % S, '"%s" mcp' % launcher, '"%s" --strict mcp' % launcher):
        assert G.protected(text) == ("always", G._HOST_MSG), text


def test_mcp_without_a_guard_word_is_ordinary():
    assert G.protected("py -3 %s mcp" % S) is not None
    for text in ('git commit -m "add mcp"', "cat docs/mcp.md", "mcp", "py -3 %s --unknown mcp" % S, "py -3 %s plan --branch mcp --paths x" % S,
                 "py -3 %s list" % S):
        assert G.protected(text) is None, text


def test_every_host_denies_a_tool_command_that_starts_mcp(repo, tmp_path, isolated_env):
    outside = tmp_path / "outside"
    outside.mkdir()
    want = G.T("en", "protected_mcp")
    cmd = "py -3 %s mcp" % QS
    for where in (repo.path, outside):
        for level in ("prompt", "auto-safe"):
            repo.git("config", "magos.approval", level)
            for tool in ("Bash", "PowerShell"):
                assert denied(hook(where, cmd, host="claude", tool=tool)) == want, (where, tool)
        assert denied(hook(where, cmd)) == want
        assert denied(hook(where, ["bash", "-lc", "python3 %s mcp" % S])) == want
        assert denied(hook(where, cmd, host="hermes", tool="terminal")) == want
        assert denied(hook(where, cmd, host="hermes", tool="terminal", extra_args=["--hermes-gate", "ask"])) == want
    assert not store_exists(approvals(repo), isolated_env / ".magos" / "approvals")


def test_the_codex_denial_names_the_tool_and_its_exact_arguments(repo, tmp_path):
    r, fp = P(repo.path), "0123456789ab"
    arm = ({"subcommand": "arm", "repo": r}, ["--repo=" + r, "--lang=en", "arm"])
    outside = tmp_path / "outside"
    outside.mkdir()
    rows = [
        (repo.path, "py -3 %s arm" % QS) + arm, (repo.path, ["py", "-3", S, "arm"]) + arm,
        (repo.path / "src", ["bash", "-lc", "python3 %s --repo .. --lang zh --json arm --dry-run" % S],
         {"subcommand": "arm", "repo": r, "dry_run": True}, ["--repo=" + r, "--lang=en", "arm", "--dry-run"]),
        (repo.path, ["powershell.exe", "-Command", "py -3 '%s' disarm" % S], {"subcommand": "disarm", "repo": r}, ["--repo=" + r, "--lang=en", "disarm"]),
        (repo.path, "py -3 %s override --fingerprint %s --reason 'the user said ok'" % (QS, fp),
         {"subcommand": "override", "repo": r, "fingerprint": fp, "reason": "the user said ok"},
         ["--repo=" + r, "--lang=en", "override", "--fingerprint=" + fp, "--reason=the user said ok"]),
        (repo.path, "py -3 %s install --host codex" % QS, {"subcommand": "install", "repo": r, "host": "codex"}, ["--lang=en", "install", "--host=codex"]),
        (outside, "py -3 %s install --host codex" % QS, {"subcommand": "install", "host": "codex"}, ["--lang=en", "install", "--host=codex"]),
        (repo.path, "py -3 %s arm --approval=abc" % QS) + arm,
    ]
    for cwd, cmd, args, argv in rows:
        reason = denied(hook(cwd, cmd))
        assert reason == codex_text(args, argv), (cmd, reason)
        assert "would change the guard's own" in reason and "user-only" in reason and "magos_approve" in reason
        call = json.dumps(args)
        assert call.isascii() and json.loads(call) == args


def test_the_codex_denial_of_a_form_the_tool_does_not_take(repo, isolated_env, tmp_path):
    form = G.T("en", "protected_codex_form", why=G._USER_MSG, cmd=G.guard_cmd())
    h = P(tmp_path / "h")
    for cmd in ("Start-Process py %s,disarm" % S, "bash -c 'py -3 %s arm'" % S, "py -3 %s install --host codex --home %s" % (QS, h),
                "py -3 %s install --host codex --allow-downgrade" % QS, "py -3 %s override --fingerprint XYZ --reason r" % QS,
                "py -3 %s --repo /no/such arm" % QS, 'py -3 %s arm "$R"' % QS):
        assert denied(hook(repo.path, cmd)) == form, cmd
    assert not store_exists(approvals(repo), isolated_env / ".magos" / "approvals")


def test_no_magos_hook_stands_before_the_tool(repo, tmp_path, monkeypatch):
    codex = json.loads(G.host_snippet("codex", P(tmp_path)))["hooks"]["PreToolUse"][0]["matcher"]
    names = ("mcp__magos__magos_approve", "mcp__plugin_magos_magos__magos_approve")
    for matcher in (codex, G.claude_matcher(), G.claude_matcher(strict=True)):
        assert not any(re.search(matcher, n) for n in names), matcher
    opened = []
    monkeypatch.setattr(G, "open_repo", lambda *a, **k: opened.append(a))
    for name in names:
        for arguments in ({"subcommand": "arm", "repo": P(repo.path)}, {"subcommand": "disarm", "repo": P(repo.path)},
                          {"subcommand": "override", "repo": P(repo.path), "fingerprint": "0123456789ab", "reason": "r"},
                          {"subcommand": "install", "host": "codex"}):
            for host in ("claude", "codex", "hermes", None):
                assert G.decide({"tool_name": name, "tool_input": arguments, "cwd": str(repo.path)}, "en", host) is None
    assert opened == [] and G.MCP_TOOL == "magos_approve"


# ---- the subcommand slot of a guard run (TC-683 to TC-689) -----------------------------------------------------------------------------------
DYNAMIC_SLOTS = [  # (tool, command template): a plain command that runs the guard with a subcommand the hook cannot read as a plain word
    ("Bash", "x={sub}; python3 {s} $x"), ("Bash", "python3 {s} $(echo {sub})"), ("Bash", "python3 {s} ${{X:-{sub}}}"), ("Bash", "python3 {s} `echo {sub}`"),
    ("Bash", "a=({sub}); python3 {s} ${{a[0]}}"), ("Bash", "python3 {s} $'{sub}'"), ("Bash", "printf '%s\\n' {sub} | xargs python3 {s}"),
    ("Bash", "echo {sub} | xargs -I XX python3 {s} XX"), ("Bash", "echo {sub} | xargs -I plan python3 {s} plan"),
    ("Bash", "printf x | xargs -I{{}} sh -c \"python3 '{s}' {{}} < /tmp/in.$$\""), ("Bash", "eval python3 {s} '$x'"), ("Bash", '"$PY" {s} $x'),
    ("Bash", 'c="python3 {s}"; $c {sub}'), ("Bash", "g() {{ python3 {s} \"$@\"; }}; g {sub}"), ("Bash", "find . -name x -exec python3 {s} {{}} +"),
    ("Bash", "python3 {s} --repo $R plan"), ("Bash", "python3 {s} mc?"), ("Bash", "python3 -X utf8 {s} -- $x"), ("Bash", "nohup {s} $x"),
    ("PowerShell", "$a='{sub}'; py -3 {s} $a"), ("PowerShell", "& py -3 {s} @a"), ("PowerShell", "py -3 {s} $($a)"),
    ("PowerShell", "Start-Process py -ArgumentList {s},$a"), ("PowerShell", "Invoke-Expression \"py {s} $a\""), ("PowerShell", "iex ('py {s} ' + $a)"),
    ("PowerShell", "function g {{ py {s} @args }}; g {sub}"), ("PowerShell", "cmd /c py {s} %X%"),
    ("Bash", "timeout 30s python3 {s} $x"), ("Bash", "uv run python {s} $x"), ("Bash", "poetry run python {s} $x"), ("Bash", "uv run {s} $x"),
    ("Bash", "conda run -n env python {s} $x"), ("Bash", "ionice -c3 python3 {s} $x"), ("Bash", "flock /tmp/l python3 {s} $x"),
    ("Bash", "echo mcp | ionice -c3 xargs python3 {s}"),
]
ALLOWED_GUARD_RUNS = [  # ordinary agent use and texts that merely name the guard or mcp (no deny on any host)
    "py -3 {qs} plan --branch agent/x --paths a b", "py -3 {qs} check --branch agent/x --paths a", "py -3 {qs} list --json", "py -3 {qs} doctor",
    "py -3 {qs} --json version", "py -3 {qs} --repo . set-show --set demo", "py -3 {qs} -- list", "py -3 {qs} --help", "py -3 {qs} --repo=. --unknown install",
    "py -3 {qs} plan --branch agent/x --paths mcp", "py -3 {qs} plan --branch \"$B\" --paths $P", "py -3 \"$HOME/x/magos_guard.py\" plan --branch x --paths a",
    "cat {qs}", "git add {qs} tests/x.py", "grep -n mcp {qs}", "wc -l {qs}", "py -3 -m pytest -k magos_guard", "py -3 -m py_compile {qs}",
    "git ls-files | xargs grep -l magos_guard.py", "codex mcp list", "echo mcp", 'git commit -m "the mcp server of magos_guard.py"',
    'git commit -m "magos_guard.py and __init__.py: deny dynamic words"', "Start-Process py '{s}','list'", "grep -n python3 {qs}", "rg python {qs}",
    "timeout 30s python3 {qs} list", "uv run python {qs} plan --branch x --paths a", "ionice -c3 python3 {qs} doctor", "flock /tmp/l python3 {qs} --help",
    "grep -rn xargs {qs}",
]


def slot_text(lang="en"):
    return G.T(lang, "protected_slot", cmd=G.guard_cmd(), subs="|".join(G.AGENT_SUBS))


def decided(repo, cmd, host, gate=None, tool="Bash"):
    res = G.decide({"tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(repo.path), "tool_use_id": "t-1", "session_id": "s-1"}, "en", host, gate)
    return res[1] if isinstance(res, tuple) and not isinstance(res, (G.Approval, G.HermesApproval)) else res


def test_the_tamper_filter_denies_a_dynamic_or_fed_subcommand():
    for tool, form in DYNAMIC_SLOTS:
        for sub in ("mcp", "hook", "disarm", "plan"):
            text = form.format(s=S, sub=sub)
            assert G.protected(text) == ("always", G._SLOT_MSG), (tool, text)
    assert G.protected("py -3 %s ('mcp')" % S) == ("always", G._HOST_MSG)  # a static piece in a PowerShell expression is read as written
    assert G.protected("x=disarm; python3 %s $x arm" % S) == ("always", G._SLOT_MSG)
    assert G.protected("python3 %s --repo $R arm" % S) == ("always", G._USER_MSG)  # a user-only word keeps its own path (Approval)


def test_every_host_denies_a_dynamic_subcommand_with_one_text(repo, isolated_env):
    want = slot_text()
    for tool, form in DYNAMIC_SLOTS[:3] + DYNAMIC_SLOTS[6:7] + DYNAMIC_SLOTS[19:20]:
        cmd = form.format(s=QS, sub="mcp")
        assert denied(hook(repo.path, cmd, host="claude", tool=tool)) == want, cmd
        assert denied(hook(repo.path, cmd)) == want, cmd
        for extra in ([], ["--hermes-gate", "ask"]):
            assert denied(hook(repo.path, cmd, host="hermes", tool="terminal", extra_args=extra)) == want, (extra, cmd)
    for host, gate in ((None, None), ("claude", None), ("codex", None), ("hermes", None), ("hermes", "ask"), ("hermes", "bypass")):
        assert decided(repo, "x=mcp; python3 %s $x" % QS, host, gate) == want, host
    every = ((None, None, "Bash"), ("claude", None, None), ("codex", None, "Bash"), ("hermes", None, "terminal"), ("hermes", "ask", "terminal"))
    for tool, form in DYNAMIC_SLOTS:  # every spelling, in process, on every host (claude with the form's own tool)
        cmd = form.format(s=QS, sub="mcp")
        for host, gate, t in every:
            assert decided(repo, cmd, host, gate, t or tool) == want, (host, gate, cmd)
    assert not store_exists(approvals(repo), isolated_env / ".magos" / "approvals")


def test_a_tool_command_never_runs_the_hook_subcommand(repo, tmp_path, isolated_env):
    want = slot_text()
    inner = json.dumps({"hook_event_name": "pre_tool_call", "tool_name": "terminal", "tool_input": {"command": "py -3 %s --repo %s disarm" % (S, P(repo.path))},
                        "session_id": "s", "tool_use_id": "x", "cwd": "/", "extra": {}})
    every = (("claude", "Bash", []), ("codex", "Bash", []), ("hermes", "terminal", []), ("hermes", "terminal", ["--hermes-gate", "ask"]))
    for cmd in ("py -3 %s hook claude pre-tool" % QS, '"%s" hook claude pre-tool' % P(LAUNCHER), '"%s" --strict hook codex pre-tool' % P(LAUNCHER),
                "py -3 %s --lang en hook hermes pre-tool --hermes-gate=ask < p.json" % QS, "cat p.json | py -3 %s hook hermes pre-tool --hermes-gate ask" % QS,
                "py -3 %s --repo=. --json hook claude pre-tool" % QS, "env A=1 python3 %s hook claude pre-tool" % S,
                "Start-Process %s -ArgumentList hook,hermes,pre-tool -RedirectStandardInput p.json -Wait" % QS, "uv run %s hook claude pre-tool" % QS,
                "timeout 30s python3 %s hook claude pre-tool" % QS):
        assert G.protected(cmd) == ("always", G._SLOT_MSG), cmd
        for host, tool, extra in every:
            assert denied(hook(repo.path, cmd, host=host, tool=tool, extra_args=extra)) == want, (host, cmd)
    feed = "echo '%s' | py -3 %s hook hermes pre-tool --hermes-gate ask" % (inner, QS)  # the payload's own command is read as well
    assert G.protected(feed) is not None
    for host, tool, extra in every:
        assert denied(hook(repo.path, feed, host=host, tool=tool, extra_args=extra)) is not None, host
    assert not store_exists(approvals(repo), isolated_env / ".magos" / "approvals")


def test_ordinary_guard_runs_and_texts_that_name_the_guard_or_mcp_pass(repo):
    for form in ALLOWED_GUARD_RUNS:
        cmd = form.format(s=S, qs=QS)
        assert G.protected(cmd) is None, cmd
        for host, gate in ((None, None), ("claude", None), ("codex", None), ("hermes", None), ("hermes", "ask")):
            assert decided(repo, cmd, host, gate) is None, (host, cmd)
    for cmd in ("py -3 %s list --json" % QS, "codex mcp list", "py -3 %s plan --branch agent/x --paths mcp" % QS):
        for host, tool in (("claude", "Bash"), ("claude", "PowerShell"), ("codex", "Bash"), ("hermes", "terminal")):
            assert hook(repo.path, cmd, host=host, tool=tool).out.strip() == "{}", (host, cmd)


def test_the_mcp_and_slot_denials_are_the_same_on_every_host(repo):
    for cmd, want in (("py -3 %s mcp" % QS, G.T("en", "protected_mcp")), ("python3 %s hook claude pre-tool" % QS, slot_text())):
        for host, gate in ((None, None), ("claude", None), ("codex", None), ("hermes", None), ("hermes", "ask"), ("hermes", "absent")):
            for tool in (("Bash", "PowerShell") if host != "hermes" else ("terminal",)):
                assert decided(repo, cmd, host, gate, tool) == want, (host, gate, tool, cmd)


def test_every_subcommand_of_the_parser_is_classified():
    choices = set(next(a for a in G.build_parser()._actions if a.dest == "cmd").choices)
    tables = [set(G.AGENT_SUBS), set(G._USER_ONLY), set(G.HOST_ONLY), {"hook"}]
    assert set().union(*tables) == choices and sum(len(t) for t in tables) == len(choices)
    for lang in ("zh", "en"):
        text = slot_text(lang)
        assert "{" not in text and "xargs" in text and "|".join(G.AGENT_SUBS) in text and G.guard_cmd() in text


def test_the_reviewers_self_click_is_denied_before_it_runs(repo, isolated_env):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {"elicitation": {}}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "magos_approve", "arguments": {"subcommand": "arm", "repo": P(repo.path)}}},
            {"jsonrpc": "2.0", "id": 1, "result": {"action": "accept", "content": {"approve": True}}}]
    lines = " ".join("'%s'" % json.dumps(m) for m in msgs)
    py = P(sys.executable)
    for cmd in ("x=mcp; printf '%%s\\n' %s | '%s' '%s' $x" % (lines, py, S),
                "printf '%%s\\n' %s > /tmp/in.$$; echo mcp | xargs -I{} sh -c \"'%s' '%s' {} < /tmp/in.$$\"" % (lines, py, S)):
        for host, tool, extra in (("claude", "Bash", []), ("codex", "Bash", []), ("hermes", "terminal", []), ("hermes", "terminal", ["--hermes-gate", "ask"])):
            assert denied(hook(repo.path, cmd, host=host, tool=tool, extra_args=extra)) == slot_text(), (host, cmd[:60])
    assert not armed(repo) and not store_exists(approvals(repo), isolated_env / ".magos" / "approvals")


# ---- install and doctor (TC-638 to TC-641)-------------------------------------------------------------------------------------------------
def test_install_for_codex_prints_and_writes_the_mcp_entry(repo, guard, tmp_path):
    tomllib = pytest.importorskip("tomllib") if sys.version_info >= (3, 11) else None
    name = "home 家" + ("" if WIN else " \"q\" \\b 'a'")
    home = tmp_path / name
    r = guard(repo, "install", "--host", "codex", "--home", str(home), "--dry-run")
    hh = G.guard_home(str(home))
    assert r.rc == 0 and G.host_snippet("codex", hh) in r.out and G.codex_mcp_toml(hh) in r.out, r
    assert "Or add the server with: %s (this sets neither env_vars nor the timeouts)" % G.codex_mcp_add(hh) in r.out
    assert not home.exists()
    r = guard(repo, "install", "--host", "codex", "--home", str(home))
    assert r.rc == 0, r
    gen = home / "guard" / "generated"
    assert (gen / "codex.json").read_text(encoding="utf-8") == G.host_snippet("codex", hh)
    text = (gen / "codex-mcp.toml").read_text(encoding="utf-8")
    assert text == G.codex_mcp_toml(hh) and text.startswith("[mcp_servers.magos]\n")
    if tomllib is not None:
        entry = tomllib.loads(text)["mcp_servers"]["magos"]
        assert entry == {"command": sys.executable, "args": ["-I", "-B", "%s/guard/scripts/magos_guard.py" % hh, "mcp"],
                         "env_vars": ["MAGOS_HOME", "MAGOS_LANG"], "startup_timeout_sec": 30, "tool_timeout_sec": 600}
    home2 = tmp_path / "h2"
    assert guard(repo, "install", "--host", "claude", "--home", str(home2)).rc == 0
    assert not (home2 / "guard" / "generated" / "codex-mcp.toml").exists()


def test_toml_strings():
    tomllib = pytest.importorskip("tomllib") if sys.version_info >= (3, 11) else None
    assert G._toml_str('a"b\\c') == '"a\\"b\\\\c"'
    assert G._toml_str("\0\x1b\x7f") == '"\\u0000\\u001B\\u007F"'
    assert G._toml_str("\t\U0001F600家") == '"\t\U0001F600家"'
    for s in ('a"b\\c', "\t", "\0", "\x1b", "\x7f", "\U0001F600", "家"):
        if tomllib is not None:
            assert tomllib.loads("k = %s\n" % G._toml_str(s))["k"] == s, repr(s)


def test_doctor_reports_the_codex_route(repo, guard, tmp_path, isolated_env):
    outside = tmp_path / "outside"
    outside.mkdir()

    def doctor(where):
        r = run(["--repo", str(where), "--lang", "en", "doctor"])
        before = r.out[:r.out.index("repository:")]
        return r, before
    for where in (outside, repo.path):
        r, before = doctor(where)
        assert "mcp server: answers initialize and tools/list (magos_approve)\n" in before and "codex mcp entry: none generated" in before, r.out
        assert "\ncodex: only Codex shows whether it runs the server" in before and r.rc == 0, r.out
    assert guard(repo, "install", "--host", "codex").rc == 0
    home = G.guard_home()
    toml = Path(home) / "guard" / "generated" / "codex-mcp.toml"
    script = "%s/guard/scripts/magos_guard.py" % home
    for where in (outside, repo.path):
        r, before = doctor(where)
        assert "codex mcp entry %s: %s %s (guard %s)" % (P(toml), sys.executable, script, G.GUARD_VERSION) in before and r.rc == 0, r.out
    good = toml.read_text(encoding="utf-8")
    toml.write_text(good.replace(G._toml_str(sys.executable), G._toml_str(P(tmp_path / "gone" / "python.exe"))), encoding="utf-8")
    redo = "%s install --host codex" % G.guard_cmd()
    r, before = doctor(repo.path)
    assert "does NOT EXIST" in before and redo in before and r.rc == 1, r.out
    old = tmp_path / "old" / "magos_guard.py"
    old.parent.mkdir()
    old.write_bytes(SCRIPT.read_bytes().replace(b'GUARD_VERSION = "%s"' % G.GUARD_VERSION.encode(), b'GUARD_VERSION = "1.0.1"'))
    toml.write_text(good.replace(G._toml_str(script), G._toml_str(P(old))), encoding="utf-8")
    r, before = doctor(repo.path)
    assert "declares 1.0.1, not this guard %s" % G.GUARD_VERSION in before and redo in before and r.rc == 1, r.out
    old.write_bytes(SCRIPT.read_bytes().replace(b'GUARD_VERSION = "%s"' % G.GUARD_VERSION.encode(), b'GUARD_VERSION = "9.9.9"'))
    r, before = doctor(repo.path)  # a newer guard: install would refuse, so doctor names that MAGOS instead
    assert "declares 9.9.9, NEWER than this guard %s; run doctor from that MAGOS" % G.GUARD_VERSION in before and redo not in before and r.rc == 1, r.out
    toml.write_text(good, encoding="utf-8")
    plug = tmp_path / "plug"
    (plug / "scripts").mkdir(parents=True)
    shutil.copyfile(str(SCRIPT), str(plug / "scripts" / "magos_guard.py"))
    (plug / "mcp.json").write_bytes(b'{"mcpServers": {}}\n')
    p = retried(lambda: subprocess.run([sys.executable, "-B", str(plug / "scripts" / "magos_guard.py"), "--repo", str(repo.path), "--lang", "en", "doctor"],
                                       capture_output=True, timeout=300, env=os.environ.copy()), lambda p: crashed(p.stderr.decode("utf-8", "replace"), p.returncode))
    out = p.stdout.decode("utf-8", "replace")
    assert "\ncodex plugin file: mcp.json %s\n" % sha256(b'{"mcpServers": {}}\n')[:12] in out[:out.index("repository:")], out


def sha256(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def test_the_server_self_test_fails_closed(repo, monkeypatch):
    assert G.mcp_selftest() == (True, "")
    with monkeypatch.context() as m:
        m.setattr(G.McpServer, "serve", lambda self: 1)
        ok, why = G.mcp_selftest()
        assert ok is False and why
    monkeypatch.setattr(G, "MCP_TOOL_SPEC", dict(G.MCP_TOOL_SPEC, name="other"))
    ok, why = G.mcp_selftest()
    assert ok is False and why
    r = run(["--repo", str(repo.path), "--lang", "en", "doctor"])
    assert r.rc == 1 and "\nmcp server: FAILED: " in r.out, r.out


# ---- texts, quoting and capped ids (TC-642 to TC-645) ------------------------------------------------------------------------------------
def test_audit_fields_name_the_route():
    assert G.approval_fields(None) == {}
    assert G.approval_fields({"tool_use_id": "toolu_1", "via": "prompt"}) == {"tool_use_id": "toolu_1"}
    assert G.approval_fields({"tool_use_id": None, "route": "mcp", "client": "fake-host/1"}) == {"tool_use_id": None, "route": "mcp", "client": "fake-host/1"}


CODEX_KEYS = ("protected_codex", "protected_codex_form", "protected_codex_never", "protected_mcp", "mcp_ask", "mcp_approve_field", "mcp_where_repo",
              "mcp_where_home", "mcp_ran", "mcp_refused", "mcp_unticked", "mcp_late", "mcp_busy", "mcp_no_form", "mcp_terminal", "mcp_invalid",
              "mcp_failed", "protected_slot", "ready_own")


def test_messages_of_the_codex_route(repo, guard, tmp_path):
    import string
    for key in CODEX_KEYS:
        zh, en = G.M[key]
        fields = [sorted({f for _t, f, _s, _c in string.Formatter().parse(s) if f}) for s in (zh, en)]
        assert fields[0] == fields[1] and zh != en, key
        for lang in ("zh", "en"):
            text = G.T(lang, key, **{f: "V" for f in fields[0]})
            assert "{" not in text and "}" not in text, (key, lang)
    for lang, terminal in (("en", "real terminal"), ("zh", "真实终端")):
        need = G.T(lang, "need_tty")
        assert terminal in need and "Claude Code" in need and "Codex" in need and "Hermes" in need, need
    assert all(w in G._USER_RUN for w in ("Claude Code", "Codex", "Hermes", "your own terminal"))
    options = G.T("en", "options", target="main", cmd="G", fp="0123456789ab")  # the texts of every host name every route (1.0.8 Change Notes)
    assert all(w in options for w in ("Claude Code's dialog", "magos_approve", "Hermes's approval prompt", "own terminal")), options
    assert "the host's dialog" in G.T("en", "approval_unknown") and "120" not in G.T("en", "approval_expired")
    footer = guard(repo, "install", "--host", "claude", "--dry-run").out  # the footer every host's install prints
    assert "Codex: trust the entry in /hooks. Hermes: with the MAGOS Hermes plugin no entry is needed" in footer, footer
    for value in ("prompt", "auto-safe"):
        repo.git("config", "magos.approval", value)
        line = next(x for x in guard(repo, "doctor").out.splitlines() if x.startswith("approval: "))
        assert "magos_approve" in line, line
        if value == "auto-safe":
            assert "install to the default guard home without --allow-downgrade" in line
    outside = tmp_path / "outside"
    outside.mkdir()
    line = next(x for x in guard(outside, "doctor").out.splitlines() if x.startswith("approval: prompt (no repository): "))
    assert "magos_approve" in line and "Hermes" in line


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_ready_command_quotes_for_the_users_shell(monkeypatch, tmp_path, platform):
    argv = ["--repo=C:/a b/r", "--lang=en", "override", "--fingerprint=0123456789ab", "--reason=it's $HOME, ok"]
    real = sys.platform
    monkeypatch.setattr(sys, "platform", platform)
    text, lead = G.ready_command(argv), G.guard_cmd()
    monkeypatch.setattr(sys, "platform", real)
    if platform == "win32":
        assert text == lead + " '--repo=C:/a b/r' --lang=en override --fingerprint=0123456789ab '--reason=it''s $HOME, ok'"
        assert lead == 'py -3 "%s"' % S
        return
    assert text == lead + " '--repo=C:/a b/r' --lang=en override --fingerprint=0123456789ab '--reason=it'\\''s $HOME, ok'"
    assert lead == 'python3 "%s"' % S
    if SH is None:
        return
    probe = tmp_path / "probe.py"
    probe.write_text("import sys\nprint('\\n'.join(sys.argv[1:]))\n", encoding="utf-8")
    line = "'%s' '%s'%s" % (P(sys.executable), P(probe), text[len(lead):])
    p = subprocess.run([SH, "-c", line], capture_output=True, timeout=120, env=dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*"))
    assert p.stdout.decode("utf-8").splitlines() == argv, p


BS = "\\"
READY_REASONS = ['plain words', "it's ok", 'say "hi"', 'cost $HOME and $(whoami)', 'tick `n back', 'a" --fingerprint=000000000000 "--lang=en',
                 'semi; Write-Host pwned', "a' ; Write-Host pwned; '", '%PATH% & echo x', 'unicode \u201cquoted\u201d \u2018x\u2019', 'end' + BS,
                 'back' + BS + '" x', 'fix "a b" now', 'y' + BS + '" --fingerprint=000000000000', 'trail space' + BS, 'two' + BS + BS, 'tab\there',
                 'mid' + BS + 'dle x']


def test_the_windows_ready_command_reaches_the_guard_unchanged(monkeypatch, tmp_path):
    """TC-690: a word Windows PowerShell 5.1 would split or rejoin (a '"', or a blank and a trailing backslash) shows the ready_own text; every
    other word reaches the guard exactly as the ready command names it (powershell.exe, when present, runs each line against a probe)."""
    real = sys.platform
    monkeypatch.setattr(sys, "platform", "win32")
    rows = []
    for reason in READY_REASONS:
        argv = ["--repo=C:/Users/x/repo", "--lang=en", "override", "--fingerprint=abcdefabcdef", "--reason=" + reason]
        text = G.ready_command(argv)
        own = '"' in reason or (re.search(r"\s", reason) is not None and reason.endswith(BS))
        want = argv[:-1] + ["--reason=" + G.T("en", "ready_own")] if own else argv
        assert (G.T("en", "ready_own") in text) == own and '"' not in text[len(G.guard_cmd()):], (reason, text)
        rows.append((text, want))
    assert G.T("zh", "ready_own") in G.ready_command(["--lang=zh", "--reason=x\"y"], "zh")
    assert G.ready_command(["--reason=x\"y"]) == G.guard_cmd() + " '--reason=%s'" % G.T("en", "ready_own")
    monkeypatch.setattr(sys, "platform", "linux")
    assert G.ready_command(["--reason=fix \"a b\" now"]) == G.guard_cmd() + " '--reason=fix \"a b\" now'"  # sh reads the words as written
    monkeypatch.setattr(sys, "platform", real)
    ps = shutil.which("powershell.exe") if WIN else None
    if ps is None:
        return
    probe = tmp_path / "probe_argv.py"
    probe.write_text("import sys, json\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    lead = G.guard_cmd()
    for text, want in rows:
        script = tmp_path / "ready.ps1"
        script.write_text("& '%s' -I '%s'%s\n" % (sys.executable.replace("'", "''"), P(probe), text[len(lead):]), encoding="utf-8-sig")
        p = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        assert json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1]) == want, (text, p)


def test_client_and_thread_ids_are_capped(hosts, repo):
    long_name = "n\x01" * 250
    got = G._client_name({"name": long_name, "version": "9"})
    assert len(got) <= 80 and not re.search(r"[\x00-\x1f]", got)
    assert G._client_name({"name": "x"}) == "x" and G._client_name({"name": "x", "version": "2"}) == "x/2" and G._client_name(["x"]) is None
    log = []
    h = hosts(runner=recording(log))
    for thread, want in ((5, None), ("t" * 300, "t" * 200)):
        cid, msg = h.dialog(arm_args(repo), thread=thread)
        h.answer(msg["id"], ACCEPT)
        h.result(cid)
        token = log[-1][0][-1][len("--approval="):]
        assert json.loads((approvals(repo) / (sha(token) + ".json")).read_text(encoding="utf-8"))["session_id"] == want


# ---- Codex's own answers and payloads (TC-646 to TC-649) ---------------------------------------------------------------------------------
def test_the_answer_codex_gives_an_empty_form_under_never_runs_nothing(hosts, repo, guard):
    for lang in ("en", "zh"):
        form = G.mcp_form(lang)
        assert form == {"type": "object", "properties": {"approve": {"type": "boolean", "title": "Approve", "description": G.T(lang, "mcp_approve_field")}},
                        "required": ["approve"]} and "default" not in json.dumps(form)
    fp = plan_denial(repo, guard)
    assert guard(repo, "arm").rc == 0
    h = hosts(runner=G.mcp_command)
    for arguments in ({"subcommand": "disarm", "repo": P(repo.path)}, {"subcommand": "override", "repo": P(repo.path), "fingerprint": fp, "reason": "ok"}):
        cid, msg = h.dialog(arguments)
        h.answer(msg["id"], {"action": "accept", "content": {}})
        sc = h.result(cid)["structuredContent"]
        assert sc["exit_code"] is None and sc["text"].startswith(G.T("en", "mcp_unticked", sub=arguments["subcommand"], ready="\0").split("\0")[0])
    assert armed(repo) and not (common(repo) / "magos" / "override").exists() and not approvals(repo).exists()


def test_the_codex_denial_under_policy_never_names_only_the_terminal(repo):
    r = P(repo.path)
    cmd = "py -3 %s arm" % QS
    never = G.T("en", "protected_codex_never", why=G._USER_MSG, ready=G.ready_command(["--repo=" + r, "--lang=en", "arm"]))
    assert denied(hook(repo.path, cmd, permission_mode="bypassPermissions")) == never
    plain = codex_text({"subcommand": "arm", "repo": r}, ["--repo=" + r, "--lang=en", "arm"])
    for mode in ("default", "acceptEdits", None):
        extra = {"permission_mode": mode} if mode else {}
        assert denied(hook(repo.path, cmd, **extra)) == plain, mode
    unmapped = G.T("en", "protected_codex_never", why=G._USER_MSG, ready=G.guard_cmd() + " <subcommand> <options>")
    assert denied(hook(repo.path, "Start-Process py %s,disarm" % S, permission_mode="bypassPermissions")) == unmapped
    claude = json.loads(hook(repo.path, cmd, host="claude", permission_mode="bypassPermissions").out)
    assert claude["hookSpecificOutput"]["permissionDecision"] == "ask"
    shutil.rmtree(str(approvals(repo)))
    hermes = hook(repo.path, cmd, host="hermes", tool="terminal", permission_mode="bypassPermissions")
    assert denied(hermes) == G.T("en", "protected", why=G._USER_MSG)


@pytest.mark.skipif(not WIN, reason="Codex runs a string command through powershell.exe on Windows only")
def test_the_codex_mapping_reads_a_windows_command_as_powershell(repo):
    r = P(repo.path)
    back = str(SCRIPT).replace("/", "\\")
    for cmd, sub in (("py -3 %s --repo %s arm" % (back, str(repo.path).replace("/", "\\")), "arm"), ("& '%s' disarm" % S, "disarm")):
        assert G.protected(cmd) == ("always", G._USER_MSG), cmd
        assert denied(hook(repo.path, cmd)) == codex_text({"subcommand": sub, "repo": r}, ["--repo=" + r, "--lang=en", sub]), cmd


def test_a_real_codex_payload_gets_a_deny_object(repo):
    r = P(repo.path)
    payload = {"session_id": "019a-thread", "turn_id": "1", "transcript_path": None, "cwd": str(repo.path), "hook_event_name": "PreToolUse",
               "model": "gpt-5", "permission_mode": "default", "tool_name": "Bash", "tool_input": {"command": "py -3 %s arm" % QS},
               "tool_use_id": "exec-0f4c9a2e-5b1d-4c7e-9a3f-2d6b8e1c0a7b"}

    def once():
        p = subprocess.run([sys.executable, "-B", str(SCRIPT), "--lang", "en", "hook", "codex", "pre-tool"], input=json.dumps(payload).encode("utf-8"),
                           capture_output=True, timeout=120)
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
    res = retried(once, lambda x: crashed(x.out + x.err, x.rc))
    assert res.rc == 0 and res.err == "" and res.out.isascii(), res
    obj = json.loads(res.out)
    assert obj["decision"] == "block" and obj["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert obj["reason"] == codex_text({"subcommand": "arm", "repo": r}, ["--repo=" + r, "--lang=en", "arm"])
    assert "updatedInput" not in res.out and not approvals(repo).exists()
