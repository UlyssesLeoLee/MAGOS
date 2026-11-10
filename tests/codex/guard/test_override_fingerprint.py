"""Override without a fingerprint (TC-830 to TC-838): the live denials of a repository, `override` that takes the only one in a real terminal
and asks for a y instead of the retyped fingerprint, the MCP approval server that fills the fingerprint in, the routes of Claude Code and
Hermes that do not, and the texts."""
from __future__ import annotations

import json
import re
import string
import time

from conftest import G, ROOT, run
from test_approval import P, PY, QS, approvals, audit_lines, common
from test_mcp_approval import ACCEPT, approve_in_process, hosts, plan_denial, recording  # noqa: F401
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


def clear_denials(repo):
    d = common(repo) / "magos" / "denials"
    for f in list(d.glob("*")) if d.is_dir() else []:
        f.unlink()


def run_override(repo, *more, stdin=b"y\n", fp=None):
    base = ["--repo", str(repo.path), "--lang", "en", "override"] + (["--fingerprint", fp] if fp else []) + ["--reason", "typed by the user"]
    return run(base + list(more), stdin=stdin)


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
    clear_denials(repo)
    denial(repo, FP[1])
    assert G.resolve_fingerprint(g)[1]["fp"] == FP[1]
    clear_denials(repo)
    hostile = [("1" * 11 + "a", 10 ** 400), ("2" * 11 + "a", float("nan")), ("3" * 11 + "a", float("inf")), ("4" * 11 + "a", "soon"), ("5" * 11 + "a", True)]
    for fp, at in hostile:  # an `at` that is no finite number counts 0 and breaks nothing
        denial(repo, fp, at=at)
        (common(repo) / "magos" / "denials" / (fp + ".json")).write_text(
            json.dumps({"v": 1, "fp": fp, "lane": "agent/h", "branches": ["agent/b"], "target": None, "at": at, "expires": time.time() + 3600}), encoding="utf-8")
    kind, found = G.resolve_fingerprint(g)
    assert kind == "many" and len(found) == 5 and all(r["at"] == 0 for r in found), found
    assert G.denial_list(found, "en").count("\n") == 4
    clear_denials(repo)
    for k in range(30):  # junk named like a fingerprint does not hide a live record, and at most 20 records are kept
        (common(repo) / "magos" / "denials").mkdir(parents=True, exist_ok=True)
        (common(repo) / "magos" / "denials" / ("%012x.json" % (k + 1))).write_text("junk", encoding="utf-8")
    denial(repo, FP[1], age=3000)
    assert G.resolve_fingerprint(g)[1]["fp"] == FP[1]
    clear_denials(repo)
    for k in range(25):
        denial(repo, "%012x" % (k + 100), age=k)
    assert len(G.live_denials(g)) == 20
    clear_denials(repo)
    for k in range(7):
        denial(repo, FP[k], age=k * 10)
    kind, found = G.resolve_fingerprint(g)
    assert kind == "many" and len(found) == 7
    text = G.denial_list(found, "en")
    assert text.count("\n") == 6 and text.endswith(G.T("en", "show_more", n=1)) and FP[0] in text and FP[6] not in text, text


def test_a_removed_file_does_not_empty_the_list(repo, monkeypatch):
    g = G.open_repo(str(repo.path))
    denial(repo, FP[1])
    denial(repo, FP[2])
    real = G.os.path.getmtime

    def flaky(path):
        if str(path).endswith(FP[1] + ".json"):
            raise FileNotFoundError(path)
        return real(path)
    monkeypatch.setattr(G.os.path, "getmtime", flaky)
    assert G.resolve_fingerprint(g)[1]["fp"] == FP[2]


def test_a_denial_is_retired_when_it_is_answered_or_its_lane_is_planned(repo, monkeypatch):
    g = G.open_repo(str(repo.path))
    v = {"decision": "deny", "fingerprint": FP[1], "conflicts": [{"branch": "agent/b", "worktrees": []}], "target": {"name": "main"}}
    G.note_denial(g, "agent/a", v)
    G.note_denial(g, "agent/a", dict(v, fingerprint=FP[2]))  # a new denial of the lane supersedes the older one
    G.note_denial(g, "agent/c", dict(v, fingerprint=FP[3]))
    assert sorted(r["fp"] for r in G.live_denials(g)) == [FP[2], FP[3]]
    monkeypatch.setattr(G, "user_console", lambda: True)
    assert run_override(repo, fp=FP[2]).rc == 0  # the override has answered it
    assert [r["fp"] for r in G.live_denials(g)] == [FP[3]] and G.resolve_fingerprint(g)[1]["fp"] == FP[3]
    r = run(["--repo", str(repo.path), "--lang", "en", "plan", "--branch", "agent/c", "--paths", "docs/none.md"])  # a conflict-free plan of the lane
    assert r.rc == 0 and G.live_denials(g) == [], r


def test_the_console_shows_agent_text_as_the_dialogs_do(repo, monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: True)
    bad = "agent/x\x9b3A\x85\u202edocs\u2028\u2066y"
    hostile = "\x9b\x85\u202e\u2028\u2066"
    denial(repo, FP[1], lane=bad, target=bad, branches=(bad, "agent/b"))
    prompt = run_override(repo, stdin=b"n\n").err.replace("\r\n", "\n")
    assert "Override denial " + FP[1] in prompt and not [ch for ch in hostile if ch in prompt], prompt
    assert not [ch for ch in hostile if ch in G.denial_list(G.live_denials(G.open_repo(str(repo.path))), "en")]
    clear_denials(repo)
    denial(repo, FP[2], branches=["agent/n%d" % k for k in range(9)])
    for lang in ("en", "zh"):  # the count that follows the six names is in the language of the request
        r = run(["--repo", str(repo.path), "--lang", lang, "override", "--reason", "x"], stdin=b"n\n")
        assert G.T(lang, "show_more", n=3) in r.err.replace("\r\n", "\n"), (lang, r.err)
    assert G.T("zh", "show_more", n=3) != G.T("en", "show_more", n=3)


def test_the_count_of_many_denials_says_when_the_list_was_cut(repo, monkeypatch):
    for k in range(25):
        denial(repo, "%012x" % (k + 100), age=k)
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--reason", "x"])
    assert r.rc == 2 and G.T("en", "override_many_denials", n="20+", list="").split("\n")[0] in r.err, r
    assert G.T("en", "show_more", n="14+") in r.err, r  # 20 of the 25 were read: the rest is a floor
    clear_denials(repo)
    for k in range(3):
        denial(repo, FP[k])
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--reason", "x"])
    assert G.T("en", "override_many_denials", n=3, list="").split("\n")[0] in r.err and "more" not in r.err, r


def test_a_real_denial_goes_through_the_approval_server_without_a_fingerprint(repo, guard):
    fp = plan_denial(repo, guard)  # a real `plan` denial writes the record the server resolves
    assert [r["fp"] for r in G.live_denials(G.open_repo(str(repo.path)))] == [fp]
    r, res, msg = approve_in_process({"subcommand": "override", "repo": P(repo.path), "reason": "the user agreed"})
    assert r.rc == 0 and res["result"]["structuredContent"]["exit_code"] == 0, (r, res)
    text = msg["params"]["message"]
    assert fp in text and '"agent/x"' in text and G.T("en", "approval_fp_auto", fp=json.dumps(fp)) in text, text
    rec = json.loads((common(repo) / "magos" / "override" / (fp + ".json")).read_text(encoding="utf-8"))
    assert (rec["fp"], rec["reason"], rec["reason_by"], rec["via"]) == (fp, "the user agreed", "agent", "prompt")
    assert not (common(repo) / "magos" / "denials" / (fp + ".json")).exists()
    again = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py", "--json")
    assert again.rc == 0 and json.loads(again.out)["code"] == "OVERRIDDEN", again


def test_override_without_a_fingerprint_in_a_terminal(repo, monkeypatch):
    monkeypatch.setattr(G, "user_console", lambda: True)
    store = common(repo) / "magos"
    fp = FP[0]
    record = store / "override" / (fp + ".json")
    prompt = G.T("en", "override_confirm", fp=fp, lane='"agent/a"', target='"main"', branches='"agent/b", "agent/c"', reason='"typed by the user"')
    denial(repo, fp, lane="agent/a", target="main", branches=("agent/b", "agent/c"))
    for typed in (b"n\n", b"\n", b"yes please\n", (fp.upper() + "\n").encode("ascii"), b""):
        r = run_override(repo, stdin=typed)
        assert r.rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists(), (typed, r)
        assert prompt in r.err.replace("\r\n", "\n"), r.err
    for typed in (b"y\n", b"YES\n", b"Yes\n", (fp + "\n").encode("ascii")):  # y in any case, or the fingerprint as the earlier versions asked
        denial(repo, fp, lane="agent/a", target="main", branches=("agent/b", "agent/c"))  # the answered denial is retired: write it again
        r = run_override(repo, stdin=typed)
        assert r.rc == 0 and r.out.strip() == G.T("en", "overridden", fp=fp), (typed, r)
        assert prompt in r.err.replace("\r\n", "\n"), r.err
        assert not (store / "denials" / (fp + ".json")).exists()
        doc = json.loads(record.read_text(encoding="utf-8"))
        assert (doc["fp"], doc["reason"], doc["reason_by"], doc["via"]) == (fp, "typed by the user", "user", "terminal")
        line = audit_lines(store)[-1]
        assert (line["op"], line["fingerprint"], line["via"]) == ("override", fp, "terminal")
        record.unlink()
    denial(repo, fp, lane="agent/a", target="main", branches=("agent/b", "agent/c"))
    denial(repo, FP[1], lane="agent/d", target=None, branches=())
    r = run_override(repo)
    assert r.rc == 2 and not record.exists() and G.T("en", "override_many_denials", n=2, list="") .split("\n")[0] in r.err, r
    assert FP[0] in r.err and FP[1] in r.err and "agent/a" in r.err and "agent/d" in r.err
    clear_denials(repo)
    r = run_override(repo)
    assert r.rc == 2 and G.T("en", "override_no_denial") in r.err and not record.exists(), r
    denial(repo, fp)
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--reason", "r", "--approval=" + "A" * 43])
    assert r.rc == 2 and G.T("en", "override_token_needs_fp") in r.err and not record.exists(), r
    r = run_override(repo, fp=fp, stdin=b"y\n")  # a named fingerprint with a live record: y confirms
    assert r.rc == 0 and record.exists(), r
    record.unlink()
    denial(repo, fp)  # the answered denial was retired
    r = run_override(repo, fp=fp, stdin=(fp + "\n").encode("ascii"))  # and so does the retyped fingerprint
    assert r.rc == 0 and record.exists(), r
    record.unlink()
    clear_denials(repo)
    denial(repo, fp, age=4000)  # the record has expired: the fingerprint is retyped, as before
    assert run_override(repo, fp=fp, stdin=b"y\n").rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists()
    assert run_override(repo, fp=fp, stdin=(fp + "\n").encode("ascii")).rc == 0 and record.exists()
    clear_denials(repo)
    monkeypatch.setattr(G, "user_console", lambda: False)  # no console: nothing is asked
    denial(repo, fp)
    record.unlink()
    r = run_override(repo)
    assert r.rc == G.EXIT["CONSOLE_REQUIRED"] and not record.exists(), r


def test_the_approval_server_fills_in_the_fingerprint(hosts, repo):
    fp = FP[0]
    denial(repo, fp, lane="agent/a", target="main", branches=("agent/b",))
    log = []
    h = hosts(runner=recording(log))
    tool = {"subcommand": "override", "repo": P(repo.path), "reason": "the user agreed"}
    assert G.MCP_TOOL_SPEC["inputSchema"]["required"] == ["subcommand"]
    assert "Optional" in G.MCP_TOOL_SPEC["inputSchema"]["properties"]["fingerprint"]["description"]
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
    clear_denials(repo)
    res = h.result(h.call(tool))
    assert res["isError"] is True and "fingerprint: no live denial in this repository" in res["structuredContent"]["text"] and len(log) == 2
    # a given fingerprint is used as before, without the sentence
    denial(repo, FP[2])
    cid, msg = h.dialog(dict(tool, fingerprint=FP[2]))
    assert FP[2] in msg["params"]["message"]
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
    # a repository at magos.approval terminal reports its level, not the fingerprint
    repo.git("config", "magos.approval", "terminal")
    v = G.decide(body, "en", "claude")
    assert v and v[1] == G.T("en", "protected_level", why=G._USER_MSG), v
    repo.git("config", "--unset", "magos.approval")
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
    design = (ROOT / ".quality" / "docs" / "scripts" / "magos_guard.py.md").read_text(encoding="utf-8")
    section = design[design.index("## Override without a fingerprint"):design.index("## Change Notes")]
    rows = {}
    for line in section.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if line.startswith("| `") and len(cells) == 3:
            rows[cells[0].strip("`")] = (cells[1], cells[2])
    assert set(rows) == {"override_confirm", "override_no_denial", "override_many_denials", "override_token_needs_fp", "denial_line", "approval_fp_auto",
                         "approval_fingerprint"}, sorted(rows)
    for key, (zh, en_text) in rows.items():  # the table of the design is the table M
        assert (zh.replace("\\n", "\n"), en_text.replace("\\n", "\n")) == tuple(t.rstrip() for t in G.M[key]), key  # a table cell has no trailing blank
    en = G.T("en", "options", target="main", cmd="g", fp="0123456789ab")
    assert "magos_approve (subcommand override, the reason and the repository" in en and "fills in the fingerprint" in en
    assert G.T("en", "overridden", fp="f").endswith("then create it.") and G.T("zh", "overridden", fp="f").endswith("然后再创建它。")


def _hook_body(repo, cmd):
    return {"session_id": "s-1", "cwd": str(repo.path), "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
            "tool_use_id": "toolu_1"}


def test_a_denial_is_retired_wherever_its_lane_stops_waiting(repo, guard, tmp_path, monkeypatch):
    g = G.open_repo(str(repo.path))

    def lanes():
        return sorted(r["lane"] for r in G.live_denials(g))

    def create(branch, wt="../wl"):
        return G.decide(_hook_body(repo, 'git worktree add "%s" -b %s' % (wt, branch)), "en", "claude")

    def spec(ids):
        doc = {"v": 1, "title": "Demo", "requirements": [{"id": "R1", "text": "the task is done"}], "base": repo.git("rev-parse", "main").strip(),
               "sheet": "# Plan demo -> main  rev 1\n" + "".join("- [ ] %s\n" % i for i in ids), "notes": [], "shared": [], "lanes": []}
        for i in ids:
            doc["lanes"].append({"id": i, "title": "lane " + i, "branch": "agent/demo/" + i, "worktree": P(tmp_path / "wt" / ("wt-demo-" + i)),
                                 "serves": ["R1"], "outcome": "o", "paths": ["src/%s/" % i], "depends_on": [], "acceptance": "it works"})
        f = tmp_path / ("spec-%s.json" % "-".join(ids))
        f.write_text(json.dumps(doc), encoding="utf-8")
        return str(f)

    def lane_wt(i):
        return P(tmp_path / "wt" / ("wt-demo-" + i))
    denial(repo, FP[7], lane="agent/other")  # a live record of another lane stays through all of it
    # the host hook allows a creation it denied before
    assert guard(repo, "plan", "--branch", "agent/l", "--paths", "src/b.py").rc == 0
    repo.branch_with("agent/z", "src/b.py")
    v = create("agent/l")
    assert v and v[0] == "CONFLICT" and lanes() == ["agent/l", "agent/other"], (v, lanes())
    repo.git("branch", "-D", "agent/z")
    assert create("agent/l") is None and lanes() == ["agent/other"]
    # an unchanged plan of the lane
    repo.branch_with("agent/z", "src/b.py")
    assert create("agent/l")[0] == "CONFLICT" and lanes() == ["agent/l", "agent/other"]
    repo.git("branch", "-D", "agent/z")
    r = guard(repo, "--json", "plan", "--branch", "agent/l", "--paths", "src/b.py")
    assert r.rc == 0 and json.loads(r.out)["unchanged"] is True and lanes() == ["agent/other"], r
    # a denied amend waits for its wider manifest: the creation under the registered one leaves it
    repo.branch_with("agent/w", "src/c.py")
    assert guard(repo, "plan", "--amend", "--branch", "agent/l", "--paths", "src/b.py", "src/c.py").rc == 10 and lanes() == ["agent/l", "agent/other"]
    assert create("agent/l") is None and lanes() == ["agent/l", "agent/other"]
    repo.branch_with("agent/z", "src/b.py")  # a denial of the registered manifest, overridden and consumed by an unchanged plan
    v = create("agent/l")
    assert v and v[0] == "CONFLICT" and lanes() == ["agent/l", "agent/l", "agent/other"], (v, lanes())
    x = re.search(r"--fingerprint ([0-9a-f]{12})", v[1]).group(1)
    monkeypatch.setattr(G, "user_console", lambda: True)
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--fingerprint", x, "--reason", "ok"], stdin=b"y\n")
    assert r.rc == 0 and lanes() == ["agent/l", "agent/other"], r
    r = guard(repo, "--json", "plan", "--branch", "agent/l", "--paths", "src/b.py")
    assert r.rc == 0 and json.loads(r.out)["code"] == "OVERRIDDEN" and json.loads(r.out)["unchanged"] is True, r
    assert lanes() == ["agent/l", "agent/other"]  # the wider amend still waits
    repo.git("branch", "-D", "agent/z")
    repo.git("branch", "-D", "agent/w")
    assert guard(repo, "plan", "--amend", "--branch", "agent/l", "--paths", "src/b.py", "src/c.py").rc == 0 and lanes() == ["agent/other"]
    # release of the lane
    G.note_denial(g, "agent/l", {"decision": "deny", "fingerprint": FP[6], "conflicts": [{"branch": "agent/b", "worktrees": []}], "target": {"name": "main"}})
    assert lanes() == ["agent/l", "agent/other"]
    r = guard(repo, "release", "--branch", "agent/l", "--reason", "done")
    assert r.rc == 0 and lanes() == ["agent/other"], r
    # set-plan registers a lane that plan was denied
    repo.branch_with("agent/x", "src/a.py")
    assert guard(repo, "plan", "--branch", "agent/demo/api", "--paths", "src/a.py").rc == 10 and lanes() == ["agent/demo/api", "agent/other"]
    r = guard(repo, "set-plan", "--set", "demo", "--target", "main", "--spec", spec(["api", "web"]))
    assert r.rc == 0 and lanes() == ["agent/other"], (r, lanes())
    # an unchanged set-plan --amend after the conflict of a lane went away
    repo.branch_with("agent/y", "src/api/y.py")
    v = create("agent/demo/api", lane_wt("api"))
    assert v and v[0] == "CONFLICT" and lanes() == ["agent/demo/api", "agent/other"], (v, lanes())
    repo.git("branch", "-D", "agent/y")
    r = guard(repo, "set-plan", "--set", "demo", "--target", "main", "--spec", spec(["api", "web"]), "--amend", "--expect-revision", "1")
    assert r.rc == 0 and "unchanged" in r.out and lanes() == ["agent/other"], (r, lanes())
    # an amend that removes a lane
    repo.branch_with("agent/y", "src/web/y.py")
    assert create("agent/demo/web", lane_wt("web"))[0] == "CONFLICT" and lanes() == ["agent/demo/web", "agent/other"]
    r = guard(repo, "set-plan", "--set", "demo", "--target", "main", "--spec", spec(["api"]), "--amend", "--expect-revision", "1")
    assert r.rc == 0 and lanes() == ["agent/other"], (r, lanes())
    # set-release
    repo.branch_with("agent/v", "src/api/v.py")
    assert create("agent/demo/api", lane_wt("api"))[0] == "CONFLICT" and lanes() == ["agent/demo/api", "agent/other"]
    r = guard(repo, "set-release", "--set", "demo", "--abandon", "--reason", "dropped")
    assert r.rc == 0 and lanes() == ["agent/other"], (r, lanes())
    assert G.resolve_fingerprint(g)[1]["fp"] == FP[7]
    # one manifest in two spellings: the later denial supersedes the earlier
    deny = {"decision": "deny", "conflicts": [{"branch": "agent/q", "worktrees": []}], "target": {"name": "main"}}
    G.note_denial(g, "agent/s", dict(deny, fingerprint=FP[4]), ["src/s.py"])
    G.note_denial(g, "agent/s", dict(deny, fingerprint=FP[5]), ["./src/s.py"])
    assert sorted((r["lane"], r["fp"]) for r in G.live_denials(g)) == [("agent/other", FP[7]), ("agent/s", FP[5])]


def test_a_record_too_deep_to_read_breaks_nothing(repo, guard):
    g = G.open_repo(str(repo.path))
    deep = common(repo) / "magos" / "denials" / "cccccccccccc.json"
    deep.parent.mkdir(parents=True, exist_ok=True)
    deep.write_text("[" * 200000, encoding="utf-8")
    assert G.live_denials(g) == [] and G.denial_record(g, "cccccccccccc") is None
    r = run(["--repo", str(repo.path), "--lang", "en", "override", "--reason", "x"])
    assert r.rc == 2 and G.T("en", "override_no_denial") in r.err, r
    assert guard(repo, "plan", "--branch", "agent/free", "--paths", "docs/free.md").rc == 0
    assert guard(repo, "plan", "--branch", "agent/l", "--paths", "src/b.py").rc == 0
    repo.branch_with("agent/x", "src/a.py")
    r = guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert r.rc == 10 and "--fingerprint" in r.out, r
    v = G.mcp_validate({"subcommand": "override", "repo": P(repo.path), "reason": "x"}, "en")
    assert v[1] is None and v[0]["ns"].fingerprint == G.live_denials(g)[0]["fp"], v
    repo.branch_with("agent/z", "src/b.py")
    hv = G.decide(_hook_body(repo, "git worktree add ../wl -b agent/l"), "en", "claude")
    assert hv and hv[0] == "CONFLICT", hv
    assert deep.exists()  # a record that cannot be read stays until it expires


def test_the_resolved_record_is_the_one_shown(repo, hosts, monkeypatch):
    fp = FP[0]
    denial(repo, fp, lane="agent/a", target="main", branches=("agent/b",))
    real_resolve, real_record, done = G.resolve_fingerprint, G.denial_record, []

    def resolve(g):
        out = real_resolve(g)
        done.append(1)
        return out
    monkeypatch.setattr(G, "resolve_fingerprint", resolve)
    monkeypatch.setattr(G, "denial_record", lambda g, f: None if done else real_record(g, f))  # the record is gone once it was resolved
    monkeypatch.setattr(G, "user_console", lambda: True)
    r = run_override(repo, stdin=b"n\n")
    assert r.rc == G.EXIT["CONSOLE_REQUIRED"] and 'lane: "agent/a"' in r.err and "Type " + fp not in r.err, r
    done.clear()
    h = hosts(runner=recording([]))
    _cid, msg = h.dialog({"subcommand": "override", "repo": P(repo.path), "reason": "x"})
    text = msg["params"]["message"]
    assert '"agent/a"' in text and '"agent/b"' in text and G.T("en", "approval_fp_auto", fp=json.dumps(fp)) in text, text
    assert G.T("en", "approval_no_record") not in text, text
    h.answer(msg["id"], {"action": "cancel"})
    h.next()


def test_override_and_approval_records_too_deep_to_read(repo, guard):
    repo.branch_with("agent/x", "src/a.py")
    r = guard(repo, "--json", "plan", "--branch", "agent/new", "--paths", "src/a.py")
    fp = json.loads(r.out)["fingerprint"]
    over_dir = common(repo) / "magos" / "override"
    over_dir.mkdir(parents=True, exist_ok=True)
    (over_dir / (fp + ".json")).write_text("[" * 200000, encoding="utf-8")
    (common(repo) / "magos" / "denials" / (fp + ".json")).unlink()
    r = guard(repo, "--json", "plan", "--branch", "agent/new", "--paths", "src/a.py")
    assert r.rc == 10 and json.loads(r.out)["fingerprint"] == fp, r  # the override record counts as none
    assert (common(repo) / "magos" / "denials" / (fp + ".json")).exists()
    (over_dir / (fp + ".json")).write_text("[1, 2]", encoding="utf-8")  # a record that is no object counts as none as well
    assert guard(repo, "plan", "--branch", "agent/new", "--paths", "src/a.py").rc == 10
    token = "A" * 43
    root = approvals(repo)
    root.mkdir(parents=True, exist_ok=True)
    (root / (G.hashlib.sha256(token.encode("ascii")).hexdigest() + ".json")).write_text("[" * 200000, encoding="utf-8")
    r = run(["--repo", str(repo.path), "--lang", "en", "arm", "--approval=" + token])
    assert r.rc == G.EXIT["APPROVAL_UNKNOWN"] and "internal error" not in r.err, r
