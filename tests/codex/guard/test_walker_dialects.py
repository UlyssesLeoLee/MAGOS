"""The walker's shell dialects (TC-816 to TC-818): Codex string commands on Windows read as PowerShell, cmd's cd words and its semicolon,
PowerShell's colon parameters of the directory commands; judged by the branch protection and by the creation check."""
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import G, payload
from test_approval import new_repo
from test_branch_protect import bp, common, console, decide, denies_main, protect, world  # noqa: F401

WIN = sys.platform == "win32"


def armed_repo(path):
    """A repository in ARMED mode (the marker the creation check reads) with one commit."""
    A = new_repo(path)
    store = common(A) / "magos"
    store.mkdir(parents=True, exist_ok=True)
    (store / "ARMED").write_text("", encoding="utf-8")
    return A


def test_codex_strings_on_windows_are_powershell(world, tmp_path):
    R, U = world.R, world.U
    sh = G.shell_command(payload("Bash", "git status", str(U.path)), "codex")[1]
    assert sh == ("ps" if WIN else "bash")
    assert G.shell_command(payload("Bash", "git status", str(U.path)), "claude")[1] == "bash"
    if not WIN:
        return
    r = str(R.path)
    for cmd in ("git -C %s commit -m x" % r, "Set-Location %s; git commit -m x" % r, "cd %s; git merge topic" % r):
        denies_main(decide(U.path, cmd, host="codex"), cmd)
    A = armed_repo(tmp_path / "A")
    v = decide(U.path, "git -C %s switch -c x" % str(A.path), host="codex")
    assert v and v[0] == "NO_MANIFEST", v


@pytest.mark.skipif(not WIN, reason="cmd.exe text with Windows paths")
def test_cmd_reads_cd_words_and_no_semicolon(world, tmp_path):
    R, U = world.R, world.U
    r = str(R.path)
    (R.path / "sub").mkdir(exist_ok=True)
    for t in ("cd/d %s & git commit -m x" % r, "cd %s\\sub & cd.. & git commit -m x" % r, "cd;%s & git commit -m x" % r,
              "chdir %s\\sub & cd.. & git commit -m x" % r):
        denies_main(decide(U.path, ["cmd.exe", "/c", t], host="codex"), t)
        denies_main(decide(U.path, 'cmd /c "%s"' % t), t)
    assert bp(decide(U.path, ["cmd.exe", "/c", "cd %s\\sub & cd\\ & git commit -m x" % r], host="codex")) is None
    A = armed_repo(tmp_path / "A")
    v = decide(U.path, ["cmd.exe", "/c", "cd/d %s & git switch -c x" % str(A.path)], host="codex")
    assert v and v[0] == "NO_MANIFEST", v
    assert decide(A.path, ["cmd.exe", "/c", "echo a; git switch -c x"], host="codex") is None  # one echo in cmd


def test_powershell_colon_parameters_name_the_directory(world):
    R, U = world.R, world.U
    r, u = str(R.path), str(U.path)
    for cmd in ("Set-Location -Path:%s; git commit -m x", "sl -LiteralPath:%s; git commit -m x", "cd -Pat:%s; git commit -m x",
                "Push-Location -LP:%s; git commit -m x", "Set-Location -PSPath:%s; git commit -m x"):
        denies_main(decide(U.path, cmd % r, tool="PowerShell"), cmd)
    for cmd in ("Set-Location -PassThru %s; git commit -m x", "Set-Location -Path:%s; git commit -m x"):
        assert bp(decide(U.path, cmd % u, tool="PowerShell")) is None, cmd
    assert subprocess.run(["git", "-C", r, "rev-parse", "--verify", "main"], capture_output=True).returncode == 0
