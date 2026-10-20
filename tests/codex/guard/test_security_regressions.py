"""Replay of the confirmed high and medium findings of the 1.0.2 security audit and of the code review of release 1.0.2, plus controls,
against the hook entry run as its own process: one case per line of data/security_regressions.jsonl, each with the verdict the guard must
give, for a deny the words its reason must hold (so a deny for another reason does not pass), and a wall-clock bound."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import ROOT, SCRIPT, time_budget

DATA = Path(__file__).resolve().parent / "data" / "security_regressions.jsonl"
CASES = [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
NESTED = 2000000
LAUNCHER = ROOT / "hooks" / "run-guard.cmd"
GITCONFIG = ("[user]\n  name = tester\n  email = t@example.invalid\n[init]\n  defaultBranch = main\n[core]\n  autocrlf = false\n  longpaths = true\n"
             "[alias]\n  nb = branch\n")  # the global alias `nb` is the subcommand `branch`
# the claim of `rel.claim` as release 1.0.1 stored it (no `v=` line), under a name the Windows alias rule refuses: it ends in `.claim`
CLAIM_1_0_1 = ("state=active\nbranch=rel.claim\nworktree=\ntarget=main\nbase={base}\ncreated=2026-01-01T00:00:00Z\nby=old\noverride=\nentry=docs/\n")


def lab_env(home):
    """An environment that names no Git or MAGOS state of the machine: its own HOME, global Git config, guard home and Hermes home."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MAGOS_"))}
    env.update(HOME=str(home), USERPROFILE=str(home), GIT_CONFIG_GLOBAL=str(home / ".gitconfig"), GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", MAGOS_HOME=str(home / ".magos"), HERMES_HOME=str(home / ".hermes"))
    return env


def git(env, cwd, *args, inp=None):
    p = subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, input=inp, stdin=None if inp is not None else subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    assert p.returncode == 0, (args, p.stderr.decode("utf-8", "replace"))
    return p.stdout.decode("utf-8", "replace").strip()


def make_repo(env, path, branch="main"):
    path.mkdir(parents=True)
    git(env, path, "init", "-q", "-b", branch)
    (path / "a.txt").write_bytes(b"base\n")
    git(env, path, "add", "-A")
    git(env, path, "commit", "-q", "-m", "init")
    return path


def make_lane_repo(env, path, lane):
    """A repository holding main and the unmerged lane branch `lane`, with main checked out."""
    make_repo(env, path)
    git(env, path, "switch", "-q", "-c", lane)
    (path / "a.txt").write_bytes(b"lane\n")
    git(env, path, "commit", "-q", "-am", "lane")
    git(env, path, "switch", "-q", "main")
    return path


def build_lab(root):
    """E: a directory outside any repository holding L (main plus an unmerged lane branch), C (a single-lane repository), four plain
    repositories and the script `mk` (`git switch -c zz33`); T: a repository without main, master, develop or trunk; M: main plus 125
    unmerged local branches; R: main, an unmerged lane and the claim of `rel.claim` as release 1.0.1 stored it."""
    home = Path(os.path.realpath(str(root))) / "home"
    home.mkdir()
    (home / ".gitconfig").write_bytes(GITCONFIG.encode("utf-8"))
    env = lab_env(home)
    E = home / "E"
    L = make_lane_repo(env, E / "L", "feat-x")
    C = make_repo(env, E / "C")
    for name in ("api", "web", "docs", "infra"):
        make_repo(env, E / name)
    (E / "mk").write_bytes(b"git switch -c zz33\n")
    T = make_repo(env, home / "T", branch="work")
    M = make_repo(env, home / "M")
    head = git(env, M, "rev-parse", "HEAD")
    stream = "".join("commit refs/heads/many-%03d\ncommitter t <t@example.invalid> 1700000000 +0000\ndata %d\nb%03d\nfrom %s\n\n" % (i, 4, i, head)
                     for i in range(125))  # one commit ahead of main each, written by one fast-import run
    git(env, M, "fast-import", "--quiet", inp=stream.encode("ascii"))
    R = make_lane_repo(env, home / "R", "feat-y")
    claims = R / ".git" / "magos" / "claims"
    claims.mkdir(parents=True)
    (claims / "rel.claim.claim").write_bytes(CLAIM_1_0_1.format(base=git(env, R, "rev-parse", "main")).encode("utf-8"))
    return {"env": env, "home": home, "E": E, "L": L, "C": C, "T": T, "M": M, "R": R}


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    return build_lab(tmp_path_factory.mktemp("security-lab"))


def expand(text, lab):
    words = {"{L_from_home}": os.path.relpath(str(lab["L"]), str(lab["home"])).replace("\\", "/"), "{L_native}": str(lab["L"]),
             "{C_native}": str(lab["C"]), "{L}": lab["L"].as_posix(), "{C}": lab["C"].as_posix(), "{launcher}": str(LAUNCHER)}
    for key, value in words.items():
        text = text.replace(key, value)
    return text


def body_of(case, lab):
    tool_input = {k: expand(v, lab) if isinstance(v, str) else v for k, v in case.get("tool_input", {}).items()}
    if "command" in case:
        tool_input["command"] = expand(case["command"], lab)
    if "build" in case:  # a hostile line made of repeated parts, [[text, times], ..], too long to keep in the data file
        tool_input["command"] = "".join(text * times for text, times in case["build"])
    body = {"tool_name": case["tool"], "tool_input": tool_input, "cwd": str(lab[case["cwd"]])}
    if case.get("raw") == "nested":  # an extra key nested deeper than any decoder's recursion or stack limit
        return (json.dumps(body)[:-1] + ', "x": ' + "[" * NESTED + "]" * NESTED + "}").encode("utf-8")
    return json.dumps(body).encode("utf-8")


def verdict_of(stdout):
    """(verdict, deny reason) of the hook's stdout."""
    out = json.loads(stdout.decode("utf-8"))
    if out == {}:
        return "allow", ""
    spec = out.get("hookSpecificOutput", {})
    if out.get("decision") == "block" and spec.get("permissionDecision") == "deny":
        return "deny", spec.get("permissionDecisionReason", "")
    return "unexpected %r" % (out,), ""


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_audit_finding_stays_fixed(case, lab):
    body = body_of(case, lab)
    start = time.monotonic()
    p = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--lang", "en", "hook", "claude", "pre-tool"], input=body, capture_output=True,
                       cwd=str(lab["home"]), env=lab["env"], creationflags=NO_WINDOW, timeout=300)
    elapsed = time.monotonic() - start
    stderr = p.stderr.decode("utf-8", "replace")
    assert p.returncode == 0, (case["id"], p.returncode, stderr)
    verdict, reason = verdict_of(p.stdout)
    assert verdict == case["expect"], (case["id"], p.stdout.decode("utf-8", "replace"), stderr)
    assert case.get("reason", "") in reason, (case["id"], reason)
    assert elapsed < time_budget(5), (case["id"], elapsed)


def test_the_cases_cover_every_replayed_finding():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) == 76
    findings = {i.split("/")[0] for i in ids}
    assert findings == {"h-overdeny-01", "h-overdeny-03", "h-overdeny-04", "h-bypass-1", "h-bypass-2", "h-upgrade-02", "NF-bypass-01", "NF-bypass-02",
                        "NF-state-1", "launcher-n1", "launcher-n7", "critic-new-01", "critic-new-02", "bypass-3", "dir-change", "control",
                        "g1-updateref-escapes", "g3-refs-case",  # the review of release 1.0.3: the update-ref and refs family
                        "g5-gate-and-cd", "g6-launcher-claims-overdeny", "g2-gitopts", "g4-powershell",  # redirections, bundled branch options, hostile nesting
                        *("cr-%02d" % n for n in (*range(1, 14), 15))}  # cr-14 is a launcher case, which a hook payload cannot express
    for c in CASES:
        assert c["expect"] in ("allow", "deny") and c["cwd"] in ("E", "L", "C", "T", "M", "R"), c
        assert set(c) <= {"id", "tool", "cwd", "command", "build", "tool_input", "raw", "expect", "reason"}, c
        assert ("reason" in c) == (c["expect"] == "deny") and c.get("reason", "x").strip(), c  # every deny names the reason it must give
    assert {c["expect"] for c in CASES if c["id"].startswith("control/")} == {"allow", "deny"}
