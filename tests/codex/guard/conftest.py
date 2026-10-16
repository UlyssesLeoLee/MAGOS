"""Shared fixtures for the lane guard tests: an isolated Git environment, real repositories with linked worktrees, in-process CLI runs."""
from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "magos_guard.py"


def _load():
    spec = importlib.util.spec_from_file_location("magos_guard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["magos_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load()
Result = namedtuple("Result", "rc out err")


def _find_sh():
    """The POSIX sh the launcher and git-layer tests run: sh on PATH, else Git for Windows' own sh.  Git's bin/sh.exe is a wrapper
    that puts /usr/bin on PATH, so the real usr/bin/sh.exe beside it is preferred: a test that empties PATH must get a shell
    without coreutils."""
    found = shutil.which("sh")
    for c in ([found] if found else []) + [r"C:\Program Files\Git\usr\bin\sh.exe", r"C:\Program Files\Git\bin\sh.exe"]:
        if c and os.path.isfile(c):
            real = os.path.join(os.path.dirname(os.path.dirname(c)), "usr", "bin", "sh.exe")
            return real if os.path.basename(os.path.dirname(c)).lower() == "bin" and os.path.isfile(real) else c
    return None


SH = _find_sh()  # None when no POSIX sh exists: the sh tests skip


def time_budget(seconds):
    """Wall-clock bound of a linear-time test. Line tracing (coverage, a debugger) slows the guard several times over;
    the bound still separates a linear walk from the quadratic blow-ups these tests exist to catch."""
    traced = sys.gettrace() is not None or "coverage" in sys.modules
    return seconds * (4 if traced else 1)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    for key in list(os.environ):
        if key.startswith(("GIT_", "MAGOS_")):
            monkeypatch.delenv(key, raising=False)
    (home / ".gitconfig").write_text("[user]\n  name = tester\n  email = t@example.invalid\n[init]\n  defaultBranch = main\n[core]\n  autocrlf = false\n  longpaths = true\n",
                                     encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("MAGOS_HOME", str(home / ".magos"))
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))  # install looks for the Hermes plugin's launcher there, never in the user's own Hermes
    return home


class Repo:
    """A throw-away repository (main worktree) plus helpers to add linked worktrees, branches, edits."""

    def __init__(self, path):
        self.path = Path(path)

    def git(self, *args, cwd=None, check=True, inp=None):
        p = subprocess.run(["git", *args], cwd=str(cwd or self.path), capture_output=True, input=inp,
                           stdin=None if inp is not None else subprocess.DEVNULL, env=os.environ.copy())
        if check and p.returncode:
            raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace")))
        return p.stdout.decode("utf-8", "replace").strip()

    def write(self, rel, text="x\n", base=None):
        p = Path(base or self.path) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
        return p

    def commit(self, rel, text="x\n", cwd=None, msg="c"):
        base = cwd or self.path
        self.write(rel, text, base)
        self.git("add", "-A", cwd=base)
        self.git("commit", "-q", "-m", msg, cwd=base)

    def branch_with(self, name, rel, text="changed\n"):
        """A local branch (no worktree) that is ahead of main by a commit touching rel."""
        wt = self.path.parent / ("tmp-" + name.replace("/", "-"))
        self.git("worktree", "add", "-q", "-b", name, str(wt), "main")
        self.commit(rel, text, cwd=wt, msg=name)
        self.git("worktree", "remove", "--force", str(wt))

    def worktree(self, name, branch=None):
        wt = self.path.parent / name
        self.git("worktree", "add", "-q", "-b", branch or name, str(wt), "main")
        return wt


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "repo")
    r.path.mkdir()
    r.git("init", "-q")
    for rel in ("src/a.py", "src/b.py", "docs/d.md", "README.md", "web/package-lock.json"):
        r.write(rel, "base\n")
    r.git("add", "-A")
    r.git("commit", "-q", "-m", "init")
    return r


def run(args, stdin=b"", cwd=None):
    """Run magos_guard.main in process with captured streams; returns Result(rc, out, err)."""
    out, err = io.BytesIO(), io.BytesIO()
    streams = (sys.stdin, sys.stdout, sys.stderr)
    fin = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
    fout = io.TextIOWrapper(out, encoding="utf-8", write_through=True)
    ferr = io.TextIOWrapper(err, encoding="utf-8", write_through=True)
    sys.stdin, sys.stdout, sys.stderr = fin, fout, ferr
    old_cwd = os.getcwd()
    try:
        if cwd:
            os.chdir(str(cwd))
        rc = G.main(list(args))
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    finally:
        os.chdir(old_cwd)
        fout.flush()
        ferr.flush()
        sys.stdin, sys.stdout, sys.stderr = streams
    return Result(rc, out.getvalue().decode("utf-8", "replace"), err.getvalue().decode("utf-8", "replace"))


@pytest.fixture
def guard():
    """guard(repo, *args) -> Result for `magos_guard --repo <repo> --lang en ...`."""
    def call(repo, *args, stdin=b""):
        old = G.user_console
        if args and args[0] in ("arm", "disarm", "install") and "--dry-run" not in args:
            G.user_console = lambda: True  # arm / disarm / install are user-only and need a console
        try:
            return run(["--repo", str(getattr(repo, "path", repo)), "--lang", "en", *args], stdin=stdin)
        finally:
            G.user_console = old
    return call


def payload(tool, command=None, cwd=None, **tool_input):
    body = dict(tool_input)
    if command is not None:
        body["command"] = command
    return {"tool_name": tool, "tool_input": body, "cwd": str(cwd) if cwd else None}
