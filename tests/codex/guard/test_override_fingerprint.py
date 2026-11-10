"""Override without a fingerprint (TC-830 to TC-834): the live denials of a repository, `override` that takes the only one in a real terminal
and asks for a y instead of the retyped fingerprint, the MCP approval server that fills the fingerprint in, the routes of Claude Code and
Hermes that do not, and the texts."""
from __future__ import annotations

import json
import re
import string
import time

import pytest

from conftest import G, run
from test_approval import P, PY, QS, approvals, audit_lines, common, hook_proc
from test_mcp_approval import ACCEPT, hosts, recording  # noqa: F401
from test_hermes_approval import H, hermes_env  # noqa: F401

FP = ["0123456789ab", "1123456789ab", "2123456789ab", "3123456789ab", "4123456789ab", "5123456789ab", "6123456789ab", "7123456789ab"]


def denial(repo, fp, lane="agent/a", target="main", branches=("agent/b",), age=0.0, ttl=3600.0, **extra):
    """A denial record of the creation check in the store of `repo`: written `age` seconds ago, valid for `ttl` seconds."""
    d = common(repo) / "magos" / "denials"
    d.mkdir(parents=True, exist_ok=True)
    now = time.time() - age
    doc = {"v": 1, "fp": fp, "lane": lane, "branches": list(branches), "target": target, "at": now, "expires": now + ttl}
    doc.update(extra)
    (d / (fp + ".json")).write_text(json.dumps(doc), encoding="utf-8")


def clear(repo):
    d = common(repo) / "magos" / "denials"
    for f in list(d.glob("*")) if d.is_dir() else []:
        f.unlink()


def test_live_denials_and_the_resolution(repo):
    g = G.open_repo(str(repo.path))
    assert G.live_denials(g) == [] and G.resolve_fingerprint(g) == ("none", None)
    denial(repo, FP[1], age=600)
    denial(repo, FP[2], age=300, branches=("agent/b", "agent/c"))
    denial(repo, FP[3], age=60)
    denial(repo, FP[4], age=4000)  # expired an hour ago
    denial(repo, FP[5], fp_other=1)
    (common(repo) / "magos" / "denials" / (FP[5] + ".json")).write_text(json.dumps({"v": 1, "fp": FP[6], "lane": "a", "branches": [], "expires": time.time() + 99}))
    (common(repo) / "magos" / "denials" / "cccccccccccc.json").write_text("x", encoding="utf-8")  # no JSON
    (common(repo) / "magos" / "denials" / "notafp.json").write_text("{}", encoding="utf-8")  # no fingerprint name
    doc = {"v": 1, "fp": FP[7], "lane": "agent/z", "branches": ["agent/b"], "target": None, "expires": time.time() + 3600}  # no `at`
    (common(repo) / "magos" / "denials" / (FP[7] + ".json")).write_text(json.dumps(doc), encoding="utf-8")
    live = G.live_denials(g)
    assert [r["fp"] for r in live] == [FP[3], FP[2], FP[1], FP[7]], live
    assert live[1]["branches"] == ["agent/b", "agent/c"] and live[3]["target"] is None and live[3]["at"] == 0
    kind, found = G.resolve_fingerprint(g)
    assert kind == "many" and [r["fp"] for r in found] == [FP[3], FP[2], FP[1], FP[7]]
    clear(repo)
    denial(repo, FP[1])
    assert G.resolve_fingerprint(g) == ("one", FP[1])
    clear(repo)
    for k in range(7):
        denial(repo, FP[k], age=k * 10)
    kind, found = G.resolve_fingerprint(g)
    assert kind == "many" and len(found) == 7
    text = G.denial_list(found, "en")
    assert text.count("\n") == 6 and text.endswith(G.T("en", "show_more", n=1)) and FP[0] in text and FP[6] not in text, text


def over(repo, *more, stdin=b"y\n", fp=None):
    base = ["--repo", str(repo.path), "--lang", "en", "override"] + (["--fingerprint", fp] if fp else []) + ["--reason", "typed by the user"]
    return run(base + list(more), stdin=stdin)


def test_override_without_a_fingerprint_in_a_terminal(repo, monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: True)
    store = common(repo) / "magos"
    fp = FP[0]
    record = store / "override" / (fp + ".json")
    denial(repo, fp, lane="agent/a", target="main", branches=("agent/b", "agent/c"))
    for typed in (b"n\n", b"\n", (fp + "\n").encode("ascii"), b"yes please\n", b""):
        r = over(repo, stdin=typed)
        assert r.rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists(), (typed, r)
        assert G.T("en", "override_confirm", fp=fp, lane="agent/a", target="main", branches="agent/b, agent/c", reason="typed by the user") in r.err.replace("\r\n", "\n"), r.err
    for typed in (b"y\n", b"YES\n", b"Yes\n"):
        r = over(repo, stdin=typed)
        assert r.rc == 0 and r.out.strip() == G.T("en", "overridden", fp=fp), (typed, r)
        doc = json.loads(record.read_text(encoding="utf-8"))
        assert (doc["fp"], doc["reason"], doc["reason_by"], doc["via"]) == (fp, "typed by the user", "user", "terminal")
        line = audit_lines(store)[-1]
        assert (line["op"], line["fingerprint"], line["via"]) == ("override", fp, "terminal")
        record.unlink()
    denial(repo, FP[1], lane="agent/d", target=None, branches=())
    r = over(repo)
    assert r.rc == 2 and not record.exists() and G.T("en", "override_many_denials", n=2, list="") .split("\n")[0] in r.err, r
    assert FP[0] in r.err and FP[1] in r.err and "agent/a" in r.err and "agent/d" in r.err
    clear(repo)
    r = over(repo)
    assert r.rc == 2 and G.T("en", "override_no_denial") in r.err and not record.exists(), r
    denial(repo, fp)
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--reason", "r", "--approval=" + "A" * 43])
    assert r.rc == 2 and G.T("en", "override_token_needs_fp") in r.err and not record.exists(), r
    r = over(repo, fp=fp, stdin=b"y\n")  # a named fingerprint with a live record: y confirms
    assert r.rc == 0 and record.exists(), r
    record.unlink()
    r = over(repo, fp=fp, stdin=(fp + "\n").encode("ascii"))  # and the retyped fingerprint does not
    assert r.rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists(), r
    clear(repo)
    denial(repo, fp, age=4000)  # the record has expired: the fingerprint is retyped, as before
    assert over(repo, fp=fp, stdin=b"y\n").rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists()
    assert over(repo, fp=fp, stdin=(fp + "\n").encode("ascii")).rc == 0 and record.exists()
    clear(repo)
    monkeypatch.setattr(G, "user_console", lambda: False)  # no console: nothing is asked
    denial(repo, fp)
    record.unlink()
    r = over(repo)
    assert r.rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists(), r


def test_the_approval_server_fills_in_the_fingerprint(hosts, repo):
    fp = FP[0]
    denial(repo, fp, lane="agent/a", target="main", branches=("agent/b",))
    log = []
    h = hosts(runner=recording(log))
    tool = {"subcommand": "override", "repo": P(repo.path), "reason": "the user agreed"}
    assert "fingerprint" not in G.MCP_TOOL_SPEC["inputSchema"].get("required", []) and "Optional" in G.MCP_TOOL_SPEC["inputSchema"]["properties"]["fingerprint"]["description"]
    cid, msg = h.dialog(tool)
    text = msg["params"]["message"]
    assert fp in text and '"agent/a"' in text and '"agent/b"' in text and G.T("en", "approval_fp_auto", fp=json.dumps(fp)) in text, text
    h.answer(msg["id"], ACCEPT)
    res = h.result(cid)
    (argv, _files), = log
    assert argv[:5] == ["--repo=" + P(repo.path), "--lang=en", "override", "--fingerprint=" + fp, "--reason=the user agreed"], argv
    assert res["structuredContent"]["approved"] is True and res["isError"] is False
    # a decline and an Accept without Approve run nothing
    for answer in ({"action": "decline"}, {"action": "accept", "content": {}}):
        cid, msg = h.dialog(tool)
        h.answer(msg["id"], answer)
        assert h.result(cid)["structuredContent"]["approved"] is False
    assert len(log) == 1
    # a denial that appears after the dialog opened changes nothing
    cid, msg = h.dialog(tool)
    denial(repo, FP[1], lane="agent/late")
    h.answer(msg["id"], ACCEPT)
    h.result(cid)
    assert log[1][0][3] == "--fingerprint=" + fp and len(log) == 2
    # several denials, none: errors of the call, no dialog
    res = h.result(h.call(tool))
    assert res["isError"] is True and "fingerprint: 2 live denials" in res["structuredContent"]["text"] and FP[1] in res["structuredContent"]["text"]
    clear(repo)
    res = h.result(h.call(tool))
    assert res["isError"] is True and "fingerprint: no live denial in this repository" in res["structuredContent"]["text"] and len(log) == 2
    # a given fingerprint is used as before, without the sentence
    denial(repo, FP[2])
    cid, msg = h.dialog(dict(tool, fingerprint=FP[2]))
    assert FP[2] in msg["params"]["message"] and G.T("en", "approval_fp_auto", fp=json.dumps(FP[2])).split(" ")[0] not in msg["params"]["message"].split("\n")[2][-80:]
    assert "approval_fp_auto" not in msg["params"]["message"] and "filled in by the guard" not in msg["params"]["message"]
    h.answer(msg["id"], {"action": "cancel"})
    h.next()


def test_the_hook_routes_without_a_fingerprint(repo, hermes_env, monkeypatch):
    denial(repo, FP[0])
    cmd = "%s %s --lang en override --reason x" % (PY, QS)
    body = {"session_id": "s-1", "cwd": str(repo.path), "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
            "tool_use_id": "toolu_1"}
    v = G.decide(body, "en", "claude")
    assert v and v[0] == "PROTECTED" and "[APPROVAL_FINGERPRINT]" in v[1] and v[1].endswith(G.T("en", "approval_fingerprint")), v
    assert not approvals(repo).exists() or not list(approvals(repo).glob("*.json"))
    hb = dict(body, tool_name="terminal", tool_input={"command": cmd, "workdir": str(repo.path)})
    v = G.decide(hb, "en", "hermes", "ask")
    assert v and v[0] == "PROTECTED" and "[APPROVAL_FINGERPRINT]" in v[1] and v[1].endswith(G.T("en", "approval_fingerprint")), v
    # Codex maps it onto magos_approve arguments without a fingerprint, and keeps one that is given
    c = G.decide(body, "en", "codex")
    call = json.dumps({"subcommand": "override", "repo": P(repo.path), "reason": "x"}, ensure_ascii=True)
    assert c and c[0] == "PROTECTED" and call in c[1] and "fingerprint" not in call, c
    with_fp = dict(body, tool_input={"command": cmd.replace("override", "override --fingerprint " + FP[0])})
    c = G.decide(with_fp, "en", "codex")
    assert json.dumps({"subcommand": "override", "repo": P(repo.path), "fingerprint": FP[0], "reason": "x"}, ensure_ascii=True) in c[1], c
    # with a fingerprint, Claude Code asks as before
    a = G.decide(with_fp, "en", "claude")
    assert isinstance(a, G.Approval) and a.decision == "ask" and FP[0] in a.reason, a


def test_the_override_texts(repo):
    keys = ("override_confirm", "override_no_denial", "override_many_denials", "override_token_needs_fp", "denial_line", "approval_fp_auto",
            "approval_fingerprint", "overridden", "options")
    fields = {"override_confirm": dict(fp="f", lane="l", target="t", branches="b", reason="r"), "override_many_denials": dict(n=2, list="x"),
              "denial_line": dict(fp="f", lane="l", target="t", age=3), "approval_fp_auto": dict(fp="f"), "overridden": dict(fp="f"),
              "options": dict(target="main", cmd="g", fp="f")}
    for key in keys:
        zh, en = G.T("zh", key, **fields.get(key, {})), G.T("en", key, **fields.get(key, {}))
        assert zh != en and zh and en, key
        for t in (zh, en):
            assert not [f for _l, f, _s, _c in string.Formatter().parse(t) if f], (key, t)
    en = G.T("en", "options", target="main", cmd="g", fp="0123456789ab")
    assert "magos_approve (subcommand override, the reason and the repository" in en and "fills in the fingerprint" in en
    assert G.T("en", "overridden", fp="f").endswith("only through it.") and G.T("zh", "overridden", fp="f").endswith("覆盖才会生效。")
