"""hooks/run-guard.cmd: the polyglot launcher (cmd.exe half and sh half), its failure map and its pass-through contract."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

STUB = '''import os, sys
mode = os.environ.get("STUB", "ok")
data = sys.stdin.read()
if mode == "ok":
    sys.stdout.write("{}")
elif mode == "deny":
    print('{"decision": "block"}')
elif mode == "echo":
    sys.stdout.write(data + "|" + " ".join(sys.argv[1:]))
elif mode == "crash":
    sys.exit(7)
'''
LAUNCHER = ROOT / "hooks" / "run-guard.cmd"
SH = shutil.which("sh") or next((p for p in (r"C:\Program Files\Git\usr\bin\sh.exe", r"C:\Program Files\Git\bin\sh.exe") if os.path.exists(p)), None)


@pytest.fixture
def layout(tmp_path):
    base = tmp_path / "目录 with space"
    (base / "hooks").mkdir(parents=True)
    (base / "scripts").mkdir()
    shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
    (base / "scripts" / "magos_guard.py").write_text(STUB, encoding="utf-8")
    return base


def run_cmd(base, *args, env=None, stdin=b"", path=None):
    e = dict(os.environ, **(env or {}))
    if path is not None:
        e["PATH"] = path
    line = 'cmd.exe /d /s /c ""%s" %s"' % (base / "hooks" / "run-guard.cmd", " ".join(args))
    return subprocess.run(line, input=stdin, capture_output=True, env=e)


def run_sh(base, *args, env=None, stdin=b""):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([SH, str(base / "hooks" / "run-guard.cmd"), *args], input=stdin, capture_output=True, env=e)


needs_cmd = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe half of the launcher")
needs_sh = pytest.mark.skipif(SH is None, reason="no sh available")


@needs_cmd
def test_cmd_allow_deny_and_passthrough(layout):
    r = run_cmd(layout, "hook claude pre-tool", env={"STUB": "ok"})
    assert r.returncode == 0 and r.stdout.strip() == b"{}"
    r = run_cmd(layout, "hook claude pre-tool", env={"STUB": "deny"})
    assert r.returncode == 0 and b"block" in r.stdout
    r = run_cmd(layout, "hook claude pre-tool", env={"STUB": "echo"}, stdin=b'{"tool_name": "Bash"}')
    assert r.stdout.strip() == b'{"tool_name": "Bash"}|hook claude pre-tool'


@needs_cmd
def test_cmd_failure_map(layout):
    soft = run_cmd(layout, "hook claude pre-tool", env={"STUB": "crash"})
    assert soft.returncode == 0 and b"exit code 7" in soft.stderr  # a warning, never a deny
    strict = run_cmd(layout, "--strict hook claude pre-tool", env={"STUB": "crash"})
    assert strict.returncode == 2 and b"exit code 7" in strict.stderr
    (layout / "scripts" / "magos_guard.py").unlink()
    soft = run_cmd(layout, "hook claude pre-tool")
    assert soft.returncode == 0 and b"missing" in soft.stderr
    assert run_cmd(layout, "--strict hook claude pre-tool").returncode == 2
    off = run_cmd(layout, "hook claude pre-tool", env={"MAGOS_GUARD": "off"})
    assert off.returncode == 0 and off.stderr == b""


@needs_cmd
def test_cmd_without_python(layout):
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    soft = run_cmd(layout, "hook claude pre-tool", path=system32)
    assert soft.returncode == 0 and b"no Python 3 found" in soft.stderr
    assert run_cmd(layout, "--strict hook claude pre-tool", path=system32).returncode == 2


@needs_sh
def test_sh_half(layout):
    r = run_sh(layout, "hook", "claude", "pre-tool", env={"STUB": "echo"}, stdin=b"payload")
    assert r.returncode == 0 and r.stdout == b"payload|hook claude pre-tool"
    assert run_sh(layout, "hook", "claude", "pre-tool", env={"STUB": "deny"}).stdout.strip() == b'{"decision": "block"}'
    soft = run_sh(layout, "hook", "claude", "pre-tool", env={"STUB": "crash"})
    assert soft.returncode == 0 and b"exit code 7" in soft.stderr
    strict = run_sh(layout, "--strict", "hook", "claude", "pre-tool", env={"STUB": "crash"})
    assert strict.returncode == 2
    assert run_sh(layout, "hook", env={"MAGOS_GUARD": "off"}).returncode == 0
    (layout / "scripts" / "magos_guard.py").unlink()
    assert b"missing" in run_sh(layout, "hook").stderr and run_sh(layout, "--strict", "hook").returncode == 2


def test_launcher_file_shape():
    raw = LAUNCHER.read_bytes()
    assert b"\r" not in raw  # LF endings: the polyglot needs them
    assert raw.startswith(b": << 'CMDBLOCK'\n@echo off\n") and b"\nCMDBLOCK\n" in raw
