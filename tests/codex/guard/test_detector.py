"""Command detector: lane-creating git commands in bash, PowerShell and cmd, plus the frozen labelled corpus."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from conftest import G

DATA = Path(__file__).parent / "data"
CWD = "C:/repo"


def creations(cmd, cwd=CWD, aliases=None):
    return G.interpret(cmd, cwd, 0, aliases)


def names(cmd, **kw):
    return [n for c in creations(cmd, **kw) for n in c["names"]]


def echo_pipe_forms():
    """The forms that pipe echoed text into a shell, with their expected names.  They live in a .jsonl data file because the
    Hermes plugin scanner rates such a line in a scanned text file (.py, .md, .json, ...) as critical, which makes an
    unattended install or update of the plugin refuse; test_package checks that no shipped text line has that shape."""
    return [json.loads(line) for line in (DATA / "echo_pipe_forms.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


ECHO_PIPE_FORMS = echo_pipe_forms()


# ---- the forms ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cmd,expected", [
    ("git worktree add ../w1 -b lane-a", ["lane-a"]), ("git worktree add -b lane-b ../w2 main", ["lane-b"]), ("git worktree add -B lane-c ../w3", ["lane-c"]),
    ("git worktree add ../lane-d", ["lane-d"]), ("git worktree add --lock --reason why ../w4 -b lane-e", ["lane-e"]),
    ("git switch -c s1", ["s1"]), ("git switch -C s2 main", ["s2"]), ("git switch --create s3", ["s3"]), ("git switch --create=s4", ["s4"]), ("git switch --crea s5", ["s5"]),
    ("git switch -fc s6", ["s6"]), ("git switch --orphan s7", ["s7"]),
    ("git checkout -b c1", ["c1"]), ("git checkout -B c2 origin/main", ["c2"]), ("git checkout -fb c3", ["c3"]), ("git checkout --orphan c4", ["c4"]),
    ("git branch b1", ["b1"]), ("git branch b2 main", ["b2"]), ("git branch -m old new", ["new"]), ("git branch -c old copy", ["copy"]), ("git branch -v b3", ["b3"]),
    ("git branch --track b4 origin/main", ["b4"]),
    ("git stash branch from-stash", ["from-stash"]),
    ("git update-ref refs/heads/u1 HEAD", ["u1"]), ("git update-ref -m msg refs/heads/u2 HEAD", ["u2"]), ("git update-ref --no-deref refs/heads/u3 HEAD", ["u3"]),
    ("git symbolic-ref HEAD refs/heads/orphan1", ["orphan1"]), ("git symbolic-ref refs/heads/alias1 refs/heads/main", ["alias1"]),
    ("git fetch . main:f1", ["f1"]), ("git fetch origin feature:f2", ["f2"]), ("git fetch origin +feature:refs/heads/f3", ["f3"]), ("git pull origin feature:f4", ["f4"]),
    ("git push . main:f5", ["f5"]),
    ("git switch --track origin/feat", ["feat"]), ("git checkout -t origin/feat2", ["feat2"]),
    ("echo 'create refs/heads/s1 HEAD' | git update-ref --stdin", ["s1"]),
    ("git update-ref --stdin <<EOF\ncreate refs/heads/s2 HEAD\nEOF", ["s2"]),
] + [(row["cmd"], row["names"]) for row in ECHO_PIPE_FORMS])
def test_lane_creating_forms(cmd, expected):
    assert names(cmd) == expected, cmd


@pytest.mark.parametrize("cmd", [
    "git status", "git branch", "git branch --list", "git branch -d x", "git branch -D x", "git branch -vv", "git branch -a", "git branch -r", "git branch --show-current",
    "git branch --contains abc", "git branch --unset-upstream", "git branch --set-upstream-to=origin/main", "git worktree list", "git worktree remove ../w", "git worktree move a b",
    "git checkout README.md", "git log --branches", "git push origin main:main", "git push origin x", "git fetch origin",
    "git update-ref -d refs/heads/x", "git symbolic-ref HEAD", "echo git branch x", "# git branch x", "ls -la",
    "cat <<'EOF'\ngit branch notes\nEOF", "cat > notes.md <<EOF\ngit checkout -b x\nEOF",
])
def test_negatives(cmd):
    assert [c for c in creations(cmd) if c["verb"] != "dwim"] == [], cmd


def test_repository_hints_wrappers_and_chains():
    assert creations("cd sub && git branch x", cwd="C:/repo")[0]["cwd"].replace("\\", "/").endswith("repo/sub")
    assert creations("git -C ../other branch x", cwd="C:/repo/a")[0]["cwd"].replace("\\", "/").endswith("repo/other")
    cr = creations("git --git-dir=/no/such/.git branch x")[0]  # a redirect: judged in the git directory it names, the shell directory stays
    assert cr["cwd"] == CWD and cr["redirect"] is True and cr["gitdir"] in (None, "/no/such/.git")  # None: no drive maps /no on Windows
    assert creations("cd $TARGET && git branch x")[0]["cwd"] is None
    assert names("FOO=1 BAR=2 git branch x") == ["x"]
    assert names("sudo git branch x") == ["x"] and names("timeout 5 git branch x") == ["x"] and names("env A=b git branch x") == ["x"]
    assert names("echo a; git branch one && git branch two || git branch three | cat") == ["one", "two", "three"]
    assert names("(git branch grouped)") == ["grouped"] and names("{ git branch braced; }") == ["braced"]
    assert names("if true; then git branch cond; fi") == ["cond"] and names("for x in a; do git branch loop-$x; done") == ["loop-$x"]
    assert names("! git branch neg") == ["neg"] and names("git status || { git branch alt; }") == ["alt"]
    assert names("find . -maxdepth 0 -exec git branch viafind \\;") == ["viafind"]
    assert creations("echo x | xargs git branch")[0]["dynamic"] is True
    assert names("git \\\n  branch continued") == ["continued"]


def test_shell_wrappers_and_powershell():
    assert names('bash -c "git branch inner"') == ["inner"] and names("sh -lc 'git switch -c deep'") == ["deep"]
    assert names('bash -c "bash -c \'git branch nested\'"') == ["nested"]
    assert names('powershell -NoProfile -Command "git branch ps1"') == ["ps1"] and names("pwsh -c 'git branch ps2'") == ["ps2"]
    assert names('cmd /c "git branch cmd1"') == ["cmd1"]
    script = base64.b64encode("git branch encoded".encode("utf-16-le")).decode("ascii")
    assert names("powershell -EncodedCommand " + script) == ["encoded"]
    assert creations("powershell -enc !!!not-base64")[0]["dynamic"] is True
    assert names('Invoke-Expression "git branch iex1"') == ["iex1"] and names('eval "git branch ev1"') == ["ev1"]
    assert names("& git branch call1") == ["call1"] and names("git.exe branch exe1") == ["exe1"]
    assert names("$g = 'git'; & $g branch viavar") == ["viavar"] and names("G=git; $G branch bashvar") == ["bashvar"]
    assert names("Set-Alias g git; g branch aliased") == ["aliased"]
    assert names("Start-Process git -ArgumentList 'branch','sp1' -Wait") == ["sp1"]
    assert names("if ($true) { git branch blk }") == ["blk"] and names("1..2 | ForEach-Object { git branch dyn$_ }") == ["dyn$_"]
    assert names("echo `git branch bt1`") == ["bt1"] and names("echo $(git branch sub1)") == ["sub1"]
    assert names("printf 'git branch pf\\n' | bash") == ["pf"]
    assert names("bash <<EOF\ngit branch here\nEOF") == ["here"] and names("sh <<< \"git branch hs\"") == ["hs"]
    assert names("cat <<EOF | bash\ngit branch pipe-here\nEOF") == ["pipe-here"]


def test_dynamic_names_and_invalid_names():
    for cmd in ("git branch $NAME", 'git switch -c "$(date)"', "git branch %B%", "git worktree add ../w -b $x", "git checkout -b"):
        cr = creations(cmd)
        assert cr and cr[0]["dynamic"] is True, cmd
    assert creations('git switch -c "feat/x y"') == []  # git refuses a name with a space: nothing is created
    assert creations("git branch ..bad") == [] and creations("git branch -x") == []


def test_tools_that_name_the_worktree_themselves():
    for cmd in ("gh pr checkout 12", "gt create -m x", "claude --worktree feat", "claude -w", "git flow feature start x"):
        cr = creations(cmd)
        assert cr and cr[0]["kind"] == "auto" and cr[0]["tool"] is True, cmd


def test_dwim_verbs_are_candidates_only():
    assert [(c["verb"], c["names"]) for c in creations("git switch feature-r")] == [("dwim", ["feature-r"])]
    assert [(c["verb"], c["names"]) for c in creations("git checkout feature-r")] == [("dwim", ["feature-r"])]
    assert [(c["verb"], c["kind"]) for c in creations("git worktree add ../w feature-r")] == [("dwim", "worktree"), ("wt-detached", "worktree")]
    assert [c["verb"] for c in creations("git worktree add ../w origin/feature-r")] == ["wt-detached"]


def test_detached_worktrees_are_lanes_keyed_by_their_directory():
    for cmd, commit in (("git worktree add --detach ../w", None), ("git worktree add ../w HEAD", "HEAD"), ("git worktree add --detach ../w v1.0", "v1.0")):
        cr = creations(cmd)[-1]
        assert (cr["verb"], cr["names"], cr["kind"], cr["commit"]) == ("wt-detached", ["detached/w"], "worktree", commit), cmd


def test_inline_and_configured_aliases():
    assert names("git -c alias.wta='worktree add' wta ../p6 -b viaalias") == ["viaalias"]
    assert names("git -c alias.sw='switch -c' sw al3") == ["al3"]
    assert names("git -c alias.x='!git branch shell1' x") == ["shell1"]
    assert names("git sw al4", aliases={"sw": "switch -c"}) == ["al4"]
    assert names("git mk al5", aliases={"mk": "!git branch from-shell"}) == ["from-shell"]
    assert names("git a1 x", aliases={"a1": "a2", "a2": "a3", "a3": "a4", "a4": "branch"}) == []  # alias chains are capped at depth 3


def test_script_files_are_read_when_small(tmp_path):
    (tmp_path / "mk.sh").write_text("#!/bin/sh\ngit branch from-script\n", encoding="utf-8")
    (tmp_path / "mk.ps1").write_bytes("\ufeffgit switch -c from-ps1\n".encode("utf-8"))
    (tmp_path / "huge.sh").write_text("git branch toolarge\n" + "#" * 70000, encoding="utf-8")
    here = str(tmp_path)
    assert names("bash mk.sh", cwd=here) == ["from-script"] and names("sh ./mk.sh", cwd=here) == ["from-script"] and names("./mk.sh", cwd=here) == ["from-script"]
    assert names("source mk.sh", cwd=here) == ["from-script"] and names(". ./mk.sh", cwd=here) == ["from-script"]
    assert names("powershell -File mk.ps1", cwd=here) == ["from-ps1"] and names(".\\mk.ps1", cwd=here) == ["from-ps1"]
    assert names("bash huge.sh", cwd=here) == [] and names("bash missing.sh", cwd=here) == []


def test_extract_for_each_host_payload():
    crs, why, cwd = G.extract({"tool_name": "Bash", "tool_input": {"command": "git branch x"}, "cwd": CWD})
    assert crs[0]["names"] == ["x"] and why is None and cwd == CWD
    crs, _, cwd = G.extract({"tool_name": "terminal", "tool_input": {"command": ["git", "branch", "y"], "workdir": "D:/w"}, "cwd": CWD})
    assert crs[0]["names"] == ["y"] and cwd == "D:/w"
    crs, _, _ = G.extract({"tool_name": "PowerShell", "tool_input": {"command": "git switch -c z"}})
    assert crs[0]["names"] == ["z"]
    assert G.extract({"tool_name": "Bash", "tool_input": {"command": "echo hello"}})[0] == []
    assert G.extract({"tool_name": "Bash", "tool_input": "oops"})[0] == []
    crs = G.extract({"tool_name": "EnterWorktree", "tool_input": {"name": "feat"}})[0]
    assert (crs[0]["names"], crs[0]["kind"]) == (["worktree-feat"], "worktree")
    crs = G.extract({"tool_name": "EnterWorktree", "tool_input": {}})[0]
    assert (crs[0]["names"], crs[0]["kind"]) == ([], "auto")
    assert G.extract({"tool_name": "EnterWorktree", "tool_input": {"path": "/existing"}})[0] == []
    for tool in ("Agent", "Task", "Workflow"):
        crs = G.extract({"tool_name": tool, "tool_input": {"prompt": "x", "isolation": "worktree"}})[0]
        assert crs and crs[0]["kind"] == "auto"
    assert G.extract({"tool_name": "Agent", "tool_input": {"prompt": "x"}})[0] == []
    crs = G.extract({"tool_name": "mcp__ccd_session__start_session", "tool_input": {"branch_name": "feat", "use_worktree": True}})[0]
    assert (crs[0]["names"], crs[0]["kind"]) == (["feat"], "worktree")
    crs = G.extract({"tool_name": "mcp__x__start_session", "tool_input": {"worktree": True}})[0]
    assert crs[0]["kind"] == "auto"
    crs = G.extract({"tool_name": "mcp__x__start_session", "tool_input": {"branch_name": "feat"}})[0]
    assert (crs[0]["names"], crs[0]["kind"]) == (["feat"], "worktree")  # the session tool makes its own worktree unless told not to
    assert G.extract({"tool_name": "mcp__x__start_session", "tool_input": {"branch_name": "feat", "use_worktree": False}})[0] == []
    crs = G.extract({"tool_name": "mcp__ccd_session__hand_off_to_session", "tool_input": {"title": "t"}})[0]
    assert crs[0]["kind"] == "auto"
    assert G.shell_text({"tool_name": "Read", "tool_input": {"command": "x"}}) is None


# ---- split_command ---------------------------------------------------------------------------------------------------
def test_split_command():
    segs = G.split_command("git switch -c \"a b\" 'c d'; echo $X `y` \"$Z\" (sub)")
    assert [w for w, _ in segs[0]] == ["git", "switch", "-c", "a b", "c d"]
    assert [(w, d) for w, d in segs[1]] == [("echo", False), ("$X", True), ("`y`", True), ("$Z", True), ("(sub)", True)]
    assert [w for w, _ in G.split_command('echo "say \\"hi\\""')[0]] == ["echo", 'say "hi"']
    assert G.split_command("   ") == [] and G.split_command("a && b | c") == [[("a", False)], [("b", False)], [("c", False)]]


def test_heredoc_bodies():
    text, bodies = G._heredocs("cat <<-'X'\n\tgit branch a\n\tX\ndone")
    assert "git branch a" not in text and bodies == []
    text, bodies = G._heredocs("sh <<X\ngit branch b\nX\nls")
    assert bodies == ["git branch b"] and text.endswith("ls")
    assert G._heredocs("echo a <<< b")[1] == []


# ---- the labelled corpus -------------------------------------------------------------------------------------------
EXISTING = {"existing", "main", "master", "develop"}
REMOTE_ONLY = {"feature-r", "feature-s"}


def detected(cmd):
    for c in creations(cmd):
        if (c["kind"] == "auto" and c["tool"]) or c["verb"] == "wt-detached":  # the corpus labels branch creations only
            continue
        found = [n for n in c["names"] if (n in REMOTE_ONLY if c["verb"] == "dwim" else n not in EXISTING)]
        if found or c["dynamic"]:
            return True
    return False


def test_corpus_floors_and_known_gaps():
    rows = [json.loads(line) for line in (DATA / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    gaps = json.loads((DATA / "known_gaps.json").read_text(encoding="utf-8"))
    assert len(rows) >= 1000
    tp = fp = fn = 0
    missed, falsepos = set(), set()
    for r in rows:
        if r["adv"] or r["scope"] != "in":
            continue
        hit = detected(r["cmd"])
        if r["branch"] and hit:
            tp += 1
        elif r["branch"]:
            fn += 1
            missed.add(r["id"])
        elif hit:
            fp += 1
            falsepos.add(r["id"])
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    assert precision >= 0.93 and recall >= 0.88, (precision, recall)
    assert missed <= set(gaps["missed"]) and falsepos <= set(gaps["false_positive"])  # a new miss must be justified in known_gaps.json


def test_every_corpus_row_is_handled_without_exceptions():
    for line in (DATA / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        G.interpret(row["cmd"], CWD)
        G.protected(row["cmd"])


# ---- tamper protection -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cmd,scope", [
    ("py -3 magos_guard.py override --fingerprint abc --reason x", "always"), ("python3 scripts/magos_guard.py arm --strict", "always"),
    ("bash -c 'python3 magos_guard.py install --host codex'", "always"), ("git config magos.guard off", "always"), ("git config --local magos.target x", "always"),
    ("git config core.hooksPath /tmp/h", "guarded"), ("GIT_CONFIG_COUNT=1 git branch x", "guarded"), ("git config --worktree x y", "guarded"),
    ("rm .git/hooks/reference-transaction", "guarded"), ("echo x > .git/magos/ARMED", "guarded"), ("Remove-Item $HOME/.magos/guard/x", "guarded"), ("Get-Content $HOME/.magos/guard/x", None),
])
def test_protected(cmd, scope):
    found = G.protected(cmd)
    assert (found[0] if found else None) == scope, cmd


@pytest.mark.parametrize("cmd", [
    "git config --get magos.guard", "git config --list", "git for-each-ref refs/heads", "py -3 magos_guard.py plan --branch x --paths y", "py -3 magos_guard.py check --branch x --paths y",
    "py -3 magos_guard.py list", "cat .git/hooks/reference-transaction", "ls .git/refs/heads",
])
def test_protected_allows_reads_and_agent_commands(cmd):
    assert G.protected(cmd) is None


# ---- review findings: no false denials for ordinary work, bundled flags, argv lists, Git Bash paths ------------------------
@pytest.mark.parametrize("cmd", [
    'git commit -m "chore: husky sets core.hooksPath for the repo"', 'grep -rn "core.hooksPath" .', 'grep -rn GIT_CONFIG_COUNT scripts', "git config --get core.hooksPath",
    "cat > NOTES.md <<'EOF'\nuse core.hooksPath and GIT_CONFIG_COUNT\nEOF", "echo x >> /repo/.git/info/exclude", "rm /repo/.git/index.lock", "cat .git/HEAD > /dev/null",
    'git commit -m "docs: describe .git/hooks and refs"', "git log -p -- .git/refs", "git config user.name x",
])
def test_protected_does_not_deny_ordinary_work(cmd):
    assert G.protected(cmd) is None, cmd


@pytest.mark.parametrize("cmd", [
    "git config core.hooksPath /tmp/hooks", "git -c core.hooksPath=/tmp/hooks branch x", "export GIT_CONFIG_COUNT=1", "GIT_CONFIG_PARAMETERS=x git branch y", "$env:GIT_CONFIG_COUNT = 1",
    "rm .git/hooks/reference-transaction", "cp evil .git/hooks/reference-transaction", "echo x > .git/refs/heads/y", "tee .git/magos/ARMED", "sed -i s/a/b/ .git/packed-refs",
    r"Remove-Item .git\magos\claims\x.claim", "git config --worktree core.bare true",
])
def test_protected_denies_real_writers(cmd):
    assert G.protected(cmd) is not None, cmd


def test_protected_user_only_subcommand_is_the_first_argument():
    assert G.protected("py -3 magos_guard.py --repo . --lang en override --fingerprint x --reason y") is not None
    assert G.protected("py -3 magos_guard.py plan --branch install --paths docs/") is None  # a branch named install is not the subcommand
    assert G.protected("x" * 100000 + " core.hooksPath") is None  # long input is bounded, never catastrophic


def test_git_bash_path_spellings_are_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(G.os, "name", "nt")
    assert G._norm_path("/c/Users/x") == "C:/Users/x" and G._norm_path("//d/y") == "D:/y" and G._norm_path("/c") == "C:/"
    assert G._norm_path("rel/path") == "rel/path"
    monkeypatch.setattr(G.os, "name", "posix")
    assert G._norm_path("/c/Users/x") == "/c/Users/x"
    assert G._norm_path("~").startswith(str(tmp_path.anchor)) or G._norm_path("~") != "~"


def test_bundled_worktree_flags_and_argv_lists():
    assert names("git worktree add -fb agent/x ../w main") == ["agent/x"] and names("git worktree add -fB agent/y ../w") == ["agent/y"]
    assert G.shell_text({"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "git branch listed"]}}) == "git branch listed"
    assert G.shell_text({"tool_name": "Bash", "tool_input": {"command": ["git", "branch", "two words"]}}) == "git branch 'two words'"
    assert G.shell_text({"tool_name": "Bash", "tool_input": {"command": ["pwsh", "-Command", "git branch x"]}}) == "git branch x"
    crs = G.extract({"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "cd /repo && git switch -c from-argv"]}, "cwd": CWD})[0]
    assert crs[0]["names"] == ["from-argv"]


def test_encoded_commands_reach_the_detector():
    script = base64.b64encode("git switch -c encoded-name".encode("utf-16-le")).decode("ascii")
    crs = G.extract({"tool_name": "PowerShell", "tool_input": {"command": "powershell -NoProfile -EncodedCommand " + script}, "cwd": CWD})[0]
    assert crs and crs[0]["names"] == ["encoded-name"]


def test_dynamic_subcommands_are_flagged():
    for cmd in ("git $CMD -c feature", 'git "$@"', "g=git; $g $SUB x"):
        cr = creations(cmd)
        assert cr and cr[0]["dynamic"] is True, cmd
