"""hooks/run-guard.cmd, the polyglot launcher (cmd.exe half and sh half), and hooks/run-guard, the POSIX launcher: their failure map, their
pass-through contract, and the entries that run each (The launchers (version 1.1.3))."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from conftest import G, ROOT, SCRIPT, SH, _find_sh, time_budget

STUB = '''import os, sys
mode = os.environ.get("STUB", "ok")
data = sys.stdin.buffer.read()
if os.environ.get("STUB_LOG"):
    with open(os.environ["STUB_LOG"], "a") as log:
        log.write("run\\n")
if mode == "ok":
    sys.stdout.write("{}")
elif mode == "deny":
    print('{"decision": "block"}')
elif mode == "echo":  # bytes in, bytes out: no newline translation hides what the launcher passed
    sys.stdout.buffer.write(data + b"|" + " ".join(sys.argv[1:]).encode())
elif mode == "env":
    sys.stdout.write(os.environ.get("NoDefaultCurrentDirectoryInExePath", "unset"))
elif mode == "crash":
    sys.exit(7)
elif mode == "argv0":  # the guard path exactly as the launcher handed it to Python
    sys.stdout.write(sys.argv[0])
'''
LAUNCHER = ROOT / "hooks" / "run-guard.cmd"
POSIX = ROOT / "hooks" / "run-guard"
POLYGLOT_SHA256 = "2c976b333e2aecc719cc5dd8f558a496e49bd5667bfafa876aaa8ee165b66523"  # run-guard.cmd of 1.1.2, kept for the entries merged before
SH_FILE = "run-guard.cmd"  # the launcher run_sh starts by default; the sh_file fixture switches it to the POSIX launcher
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
STOP = "To stop the guard: set MAGOS_GUARD=off in the host's environment, or remove the MAGOS entry from the host's hook configuration"
CLAUDE_EXAMPLE = "(for example Claude Code: claude plugin disable magos)"


@pytest.fixture
def layout(tmp_path):
    base = tmp_path / "目录 with space"
    (base / "hooks").mkdir(parents=True)
    (base / "scripts").mkdir()
    shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
    shutil.copy(POSIX, base / "hooks" / "run-guard")
    (base / "scripts" / "magos_guard.py").write_text(STUB, encoding="utf-8")
    return base


@pytest.fixture(params=["run-guard.cmd", "run-guard"])
def sh_file(request, monkeypatch):
    """Each sh case runs the sh half of the polyglot launcher and the POSIX launcher."""
    monkeypatch.setattr(sys.modules[__name__], "SH_FILE", request.param)
    return request.param


def _env(env, path, base_env=None):
    e = dict(os.environ if base_env is None else base_env, **(env or {}))
    if path is not None:
        e["PATH"] = path
    return e


def run_cmd(base, *words, env=None, stdin=b"", path=None, cwd=None, launcher=None, base_env=None):
    """The launcher through cmd.exe, as the Codex and Hermes entries run it on Windows."""
    line = 'cmd.exe /d /s /c ""%s" %s"' % (launcher or base / "hooks" / "run-guard.cmd", " ".join(words))
    return subprocess.run(line, input=b"" if stdin is None else stdin, capture_output=True, env=_env(env, path, base_env), cwd=cwd, creationflags=NO_WINDOW, timeout=120)


def run_sh(base, *words, env=None, stdin=b"", path=None, cwd=None, launcher=None, base_env=None):
    """The launcher through sh, as Claude Code (shell: bash) and the POSIX Codex and Hermes entries run it."""
    return subprocess.run([SH, str(launcher or base / "hooks" / SH_FILE), *" ".join(words).split()], input=b"" if stdin is None else stdin, capture_output=True,
                          env=_env(env, path, base_env), cwd=cwd, creationflags=NO_WINDOW, timeout=120)


def run_posix(base, *words, launcher=None, **kw):
    """The POSIX launcher hooks/run-guard through sh, as every sh or bash entry runs it (a .cmd launcher named stands for the one beside it)."""
    if launcher is not None and str(launcher).endswith(".cmd"):
        launcher = Path(str(launcher)[:-4])
    return run_sh(base, *words, launcher=launcher or base / "hooks" / "run-guard", **kw)


def halves():
    """The launchers this platform can run: the cmd.exe half on Windows, and wherever an sh exists the sh half and the POSIX launcher."""
    return ([run_cmd] if sys.platform == "win32" else []) + ([run_sh, run_posix] if SH else [])


def without_search_guard():
    """os.environ without NoDefaultCurrentDirectoryInExePath, whatever its case (Claude Code itself exports it)."""
    return {k: v for k, v in os.environ.items() if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}


def names_path(text, path):
    """True when text names the absolute path: natively, or on Windows with either separator (pwd -W gives forward slashes, cmd and cygpath
    backslashes) or in the MSYS /c/... spelling, whatever the case."""
    native = str(path)
    if sys.platform != "win32":
        return native in text
    flat, seen = native.replace("\\", "/").lower(), text.replace("\\", "/").lower()
    return flat in seen or ("/" + flat[0] + flat[2:]) in seen


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
def test_sh_half(layout, sh_file):
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
    cmd, posix = raw.decode("utf-8").split("\nCMDBLOCK\n")
    assert '\nsetlocal\nset "NoDefaultCurrentDirectoryInExePath=1"\n' in cmd  # set before any program is looked up
    assert "export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 NoDefaultCurrentDirectoryInExePath=1\n" in posix
    code = "\n".join(line for line in posix.splitlines() if not line.lstrip().startswith("#"))
    words = code.replace("(", " ").replace(")", " ").replace('"', " ").replace(";", " ").split()
    assert "dirname" not in words and "cat" not in words and "-c" not in words  # builtins only before the guard; no probe interpreter


MARKER_CS = r'''using System; using System.IO;
class Marker { static int Main(string[] a) {
  File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "marker.txt"), "FAKEGIT " + string.Join(" ", a) + Environment.NewLine);
  Console.WriteLine("FAKE-EXE-RAN"); return 0; } }
'''


def _csc():
    root = os.environ.get("WINDIR", r"C:\Windows")
    return next((p for p in (os.path.join(root, "Microsoft.NET", fw, "v4.0.30319", "csc.exe") for fw in ("Framework64", "Framework"))
                 if os.path.isfile(p)), None)


def _plant(directory):
    """Marker programs that log to marker.txt when run: py.cmd, py.bat, python.cmd, python.bat, and git.exe when csc exists."""
    directory.mkdir()
    for name in ("py.cmd", "py.bat", "python.cmd", "python.bat"):
        (directory / name).write_bytes(b'@echo PLANTED %* >> "%~dp0marker.txt"\r\n')
    csc = _csc()
    if csc:
        (directory.parent / "marker.cs").write_text(MARKER_CS, encoding="utf-8")
        built = subprocess.run([csc, "/nologo", "/out:%s" % (directory / "git.exe"), str(directory.parent / "marker.cs")], capture_output=True,
                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=120)
        assert built.returncode == 0, built.stdout
    return csc is not None


@needs_cmd
def test_launcher_never_runs_programs_from_the_working_directory(tmp_path, layout):
    plant = tmp_path / "plant"
    has_git = _plant(plant)
    marker = plant / "marker.txt"
    env = without_search_guard()
    # Positive control: without the variable, cmd.exe runs the planted py.cmd (and git.exe) from the working directory.
    control = subprocess.run("cmd.exe /d /c py -3 -c 0", capture_output=True, env=env, cwd=str(plant), stdin=subprocess.DEVNULL,
                             creationflags=NO_WINDOW, timeout=120)
    assert marker.exists() and b"PLANTED" in marker.read_bytes(), control
    if has_git:
        control = subprocess.run("cmd.exe /d /c git --version", capture_output=True, env=env, cwd=str(plant), stdin=subprocess.DEVNULL,
                                 creationflags=NO_WINDOW, timeout=120)
        assert b"FAKE-EXE-RAN" in control.stdout, control
    marker.unlink()
    body = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git switch -c feat"}, "cwd": str(plant)}).encode()
    for runner in halves():
        r = runner(None, "hook", "codex", "pre-tool", stdin=body, cwd=str(plant), launcher=LAUNCHER, base_env=env)
        assert r.returncode == 0 and json.loads(r.stdout) == {}, (runner.__name__, r)  # the real guard's verdict: plant is no repository
        assert not marker.exists(), (runner.__name__, marker.read_bytes())
        # The launcher itself hands the variable to the guard it starts, so a guard copy from before 1.0.2 is covered as well.
        r = runner(layout, "hook", "codex", "pre-tool", env={"STUB": "env"}, stdin=b"{}", cwd=str(plant), base_env=env)
        assert r.returncode == 0 and r.stdout == b"1", (runner.__name__, r)
        assert not marker.exists(), (runner.__name__, marker.read_bytes())


def _bin(directory, scripts):
    directory.mkdir()
    for name, text in scripts.items():
        (directory / name).write_bytes(text.encode("utf-8"))
        os.chmod(directory / name, 0o755)
    return directory


def _runs(real):
    """A stub interpreter that runs `real` (dropping py's -3)."""
    return "#!/bin/sh\n[ \"$1\" = -3 ] && shift\nexec '%s' \"$@\"\n" % real.replace("\\", "/")


@needs_sh
def test_sh_half_reads_stdin_once_and_runs_the_guard_directly(tmp_path, layout, sh_file):
    # python3 exits 127 and py -3 9009 after printing the Microsoft Store stub text on stdout; each reads its stdin first, as an
    # interpreter would. python runs the real interpreter. No dirname, cat or cygpath is on this PATH.
    stubs = _bin(tmp_path / "stubs", {
        "python3": "#!/bin/sh\nwhile IFS= read -r l; do :; done\nexit 127\n",
        "py": "#!/bin/sh\nwhile IFS= read -r l; do :; done\n"
              "echo 'Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut.'\nexit 9009\n",
        "python": _runs(sys.executable)})
    assert not any(shutil.which(tool, path=str(stubs)) for tool in ("dirname", "cat", "cygpath"))
    log = tmp_path / "runs.log"
    payload = b'{"tool_name": "Bash", "tool_input": {"command": "git status"}}\nsecond line \\ with a backslash\n\n'
    r = run_sh(layout, "hook", "claude", "pre-tool", env={"STUB": "echo", "STUB_LOG": str(log)}, stdin=payload, path=str(stubs))
    assert r.returncode == 0 and r.stdout == payload + b"|hook claude pre-tool", r  # the whole payload, trailing newlines included
    assert log.read_text().splitlines() == ["run"], r  # the guard ran once
    assert b"Microsoft Store" not in r.stdout  # the stub's text never precedes the verdict
    # A guard that fails is a failure, not a reason to try the next interpreter.
    reals = _bin(tmp_path / "reals", {name: _runs(sys.executable) for name in ("python3", "python", "py")})
    log.unlink()
    soft = run_sh(layout, "hook", "claude", "pre-tool", env={"STUB": "crash", "STUB_LOG": str(log)}, stdin=payload, path=str(reals))
    assert soft.returncode == 0 and b"exit code 7" in soft.stderr and log.read_text().splitlines() == ["run"], soft
    strict = run_sh(layout, "--strict", "hook", "claude", "pre-tool", env={"STUB": "crash", "STUB_LOG": str(log)}, stdin=payload,
                    path=str(reals))
    assert strict.returncode == 2 and log.read_text().splitlines() == ["run", "run"], strict
    empty = tmp_path / "empty"
    empty.mkdir()
    none = run_sh(layout, "--strict", "hook", "claude", "pre-tool", stdin=payload, path=str(empty))
    assert none.returncode == 2 and b"no Python 3 found" in none.stderr, none


@needs_sh
def test_sh_half_prefers_py_3_over_a_python_2_python(tmp_path, layout, sh_file):
    # No python3; `python` is a Python 2 that fails on the guard (SyntaxError, exit 1) and logs that it was started; py -3 is real.
    log, started = tmp_path / "runs.log", tmp_path / "python2.log"
    stubs = _bin(tmp_path / "stubs", {
        "python": "#!/bin/sh\necho started >> '%s'\necho 'SyntaxError: future feature annotations is not defined' >&2\nexit 1\n" % str(started).replace("\\", "/"),
        "py": _runs(sys.executable)})
    r = run_sh(layout, "--strict", "hook", "claude", "pre-tool", env={"STUB": "echo", "STUB_LOG": str(log)}, stdin=b"{}", path=str(stubs))
    assert r.returncode == 0 and r.stdout == b"{}|hook claude pre-tool", r  # the guard ran under py -3 and its verdict came through
    assert log.read_text().splitlines() == ["run"] and not started.exists(), r


def _host_neutral(text):
    assert STOP in text and CLAUDE_EXAMPLE in text, text
    assert text.count("claude plugin disable magos") == 1 and "To stop the guard: claude plugin disable magos" not in text, text


def test_failure_text_is_host_neutral_and_absolute(tmp_path):
    if not halves():
        pytest.skip("neither cmd.exe nor sh is available")
    base = tmp_path / "guard home"  # a launcher copied without its guard script
    (base / "hooks").mkdir(parents=True)
    shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
    shutil.copy(POSIX, base / "hooks" / "run-guard")
    guard = base / "scripts" / "magos_guard.py"
    for runner in halves():
        soft = runner(base, "hook", "codex", "pre-tool", stdin=b"{}")
        strict = runner(base, "--strict", "hook", "codex", "pre-tool", stdin=b"{}")
        assert soft.returncode == 0 and strict.returncode == 2, (runner.__name__, soft, strict)
        for r in (soft, strict):
            text = r.stderr.decode("utf-8", "replace")
            assert "the guard script is missing" in text and names_path(text, guard), (runner.__name__, text)
            assert "install again for this host" in text and "reinstall the plugin" in text, (runner.__name__, text)
            _host_neutral(text)
        guard.parent.mkdir(exist_ok=True)
        guard.write_text(STUB, encoding="utf-8")
        failed = runner(base, "hook", "codex", "pre-tool", env={"STUB": "crash"}, stdin=b"{}")
        text = failed.stderr.decode("utf-8", "replace")
        assert failed.returncode == 0 and "exit code 7" in text and "Diagnose: " in text and names_path(text, guard), (runner.__name__, text)
        _host_neutral(text)
        guard.unlink()


@pytest.mark.parametrize("half", ["sh", "posix", "cmd"])
def test_a_non_git_payload_through_the_launcher_is_fast(tmp_path, half):
    """One interpreter start per call: an ordinary command outside any repository finishes well inside a fixed bound."""
    if half == "cmd" and sys.platform != "win32":
        pytest.skip("cmd.exe half of the launcher")
    if half != "cmd" and not SH:
        pytest.skip("no sh available")
    runner = {"sh": run_sh, "posix": run_posix, "cmd": run_cmd}[half]
    body = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": str(tmp_path)}).encode()
    times = []
    for _ in range(3):
        start = time.monotonic()
        r = runner(None, "hook", "claude", "pre-tool", stdin=body, cwd=str(tmp_path), launcher=LAUNCHER)
        times.append(time.monotonic() - start)
        assert r.returncode == 0 and json.loads(r.stdout) == {}, r
    assert min(times) < time_budget(2.5), times


def _shim(directory, name, body):
    """A cmd script `name` in `directory` whose body is one line, the way pyenv-win and similar tools put python on PATH."""
    directory.mkdir(exist_ok=True)
    (directory / name).write_bytes(("@echo off\r\n%s\r\n" % body).encode("utf-8"))
    return directory


@needs_cmd
def test_cmd_half_returns_from_a_bat_interpreter_shim(tmp_path, layout):
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")

    def on_path(*dirs):
        return os.pathsep.join([str(d) for d in dirs] + [system32])
    real = sys.executable
    # A pyenv-win style python.bat is the only interpreter on PATH: the launcher returns from it and maps the guard's exit code.
    bat = _shim(tmp_path / "bat", "python.bat", '"%s" %%*' % real)
    for strict in ((), ("--strict",)):
        r = run_cmd(layout, *strict, "hook claude pre-tool", env={"STUB": "crash"}, path=on_path(bat))
        assert r.returncode == (2 if strict else 0) and b"exit code 7" in r.stderr and b"Diagnose: " in r.stderr, (strict, r)
        r = run_cmd(layout, *strict, "hook claude pre-tool", env={"STUB": "deny"}, path=on_path(bat))
        assert r.returncode == 0 and json.loads(r.stdout) == {"decision": "block"}, (strict, r)
    broken = _shim(tmp_path / "broken", "python.bat", "exit /b 1")
    soft = run_cmd(layout, "hook claude pre-tool", path=on_path(broken))
    strict = run_cmd(layout, "--strict hook claude pre-tool", path=on_path(broken))
    assert soft.returncode == 0 and strict.returncode == 2 and b"exit code 1" in soft.stderr and b"exit code 1" in strict.stderr, (soft, strict)
    # A real python.exe and no py.exe: the launcher runs it.
    venv = tmp_path / "venv"
    subprocess.run([real, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True, stdin=subprocess.DEVNULL,
                   creationflags=NO_WINDOW, timeout=120)
    scripts = venv / "Scripts"
    assert (scripts / "python.exe").is_file() and not (scripts / "py.exe").exists()
    r = run_cmd(layout, "hook claude pre-tool", env={"STUB": "echo"}, stdin=b"payload", path=on_path(scripts))
    assert r.returncode == 0 and r.stdout == b"payload|hook claude pre-tool", r
    # A python.bat that exits 9009 (a Store stub) passes on to the python.cmd shim, which runs the guard.
    chain = _shim(tmp_path / "chain", "python.bat", "exit /b 9009")
    _shim(chain, "python.cmd", '"%s" %%*' % real)
    soft = run_cmd(layout, "hook claude pre-tool", env={"STUB": "crash"}, path=on_path(chain))
    strict = run_cmd(layout, "--strict hook claude pre-tool", env={"STUB": "crash"}, path=on_path(chain))
    assert soft.returncode == 0 and strict.returncode == 2 and b"exit code 7" in soft.stderr and b"exit code 7" in strict.stderr, (soft, strict)
    # No interpreter at all: no Python 3 found, never the exit code of a program that does not exist.
    for words, rc in (("hook claude pre-tool", 0), ("--strict hook claude pre-tool", 2)):
        r = run_cmd(layout, words, path=system32)
        assert r.returncode == rc and b"no Python 3 found" in r.stderr and b"exit code 1" not in r.stderr, (words, r)


def _exit_exe(path, code):
    """A py.exe that exits with `code`, built with the .NET Framework compiler."""
    path.parent.mkdir(parents=True, exist_ok=True)
    source = path.with_suffix(".cs")
    source.write_text("class P { static int Main() { return %d; } }\n" % code, encoding="utf-8")
    built = subprocess.run([_csc(), "/nologo", "/out:%s" % path, str(source)], capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
                           timeout=120)
    assert built.returncode == 0, built.stdout
    return path.parent


def _py_without_a_runtime_in_cmd(tmp_path, layout):
    """cmd half: py.exe exiting 103 or 112 (no Python runtime) passes on to the python.bat shim; exiting 1 is a guard failure."""
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    shim_log = tmp_path / "bat" / "shim.log"
    bat = _shim(tmp_path / "bat", "python.bat", 'echo ran>> "%%~dp0shim.log"& "%s" %%*' % sys.executable)

    def on_path(*dirs):
        return os.pathsep.join([str(d) for d in dirs] + [system32])
    for code in (103, 112):
        py = _exit_exe(tmp_path / ("py%d" % code) / "py.exe", code)
        if shim_log.exists():
            shim_log.unlink()
        for strict in ((), ("--strict",)):
            r = run_cmd(layout, *strict, "hook claude pre-tool", env={"STUB": "echo"}, stdin=b"payload", path=on_path(py, bat))
            assert r.returncode == 0 and r.stdout == b"payload|hook claude pre-tool" and r.stderr == b"", (code, strict, r)  # the shim's guard ran
        assert shim_log.read_text().count("ran") == 2, code
        # Nothing after py.exe: the launcher reports that no Python was found, never the exit code of py.exe.
        for words, rc in (("hook claude pre-tool", 0), ("--strict hook claude pre-tool", 2)):
            r = run_cmd(layout, words, path=on_path(py))
            assert r.returncode == rc and b"no Python 3 found" in r.stderr and b"exit code" not in r.stderr, (code, words, r)
    shim_log.unlink()
    py = _exit_exe(tmp_path / "py1" / "py.exe", 1)
    soft = run_cmd(layout, "hook claude pre-tool", env={"STUB": "echo"}, path=on_path(py, bat))
    strict = run_cmd(layout, "--strict hook claude pre-tool", env={"STUB": "echo"}, path=on_path(py, bat))
    assert soft.returncode == 0 and strict.returncode == 2 and b"exit code 1" in soft.stderr and b"exit code 1" in strict.stderr, (soft, strict)
    assert soft.stdout == b"" and not shim_log.exists()  # a guard failure starts no other interpreter


def _py_without_a_runtime_in_sh(tmp_path, layout):
    """sh half: py -3 exiting 103 or 112 passes on to `python`; exiting 1 is a guard failure. There is no python3."""
    log, started = tmp_path / "runs.log", tmp_path / "python.log"
    note = "echo started >> '%s'\n" % str(started).replace("\\", "/")
    python = "#!/bin/sh\n%sexec '%s' \"$@\"\n" % (note, sys.executable.replace("\\", "/"))
    for code in (103, 112):
        stubs = _bin(tmp_path / ("sh%d" % code), {"py": "#!/bin/sh\nwhile IFS= read -r l; do :; done\nexit %d\n" % code, "python": python})
        for strict in ((), ("--strict",)):
            r = run_sh(layout, *strict, "hook", "claude", "pre-tool", env={"STUB": "echo", "STUB_LOG": str(log)}, stdin=b"payload", path=str(stubs))
            assert r.returncode == 0 and r.stdout == b"payload|hook claude pre-tool" and r.stderr == b"", (code, strict, r)
        assert started.read_text().count("started") == 2 and log.read_text().splitlines() == ["run", "run"], code
        started.unlink()
        log.unlink()
        alone = _bin(tmp_path / ("alone%d" % code), {"py": "#!/bin/sh\nwhile IFS= read -r l; do :; done\nexit %d\n" % code})
        for words, rc in (("hook", 0), ("--strict hook", 2)):
            r = run_sh(layout, *words.split(), "claude", "pre-tool", stdin=b"payload", path=str(alone))
            assert r.returncode == rc and b"no Python 3 found" in r.stderr and b"exit code" not in r.stderr, (code, words, r)
    stubs = _bin(tmp_path / "sh1", {"py": "#!/bin/sh\nwhile IFS= read -r l; do :; done\nexit 1\n", "python": python})
    soft = run_sh(layout, "hook", "claude", "pre-tool", env={"STUB": "echo"}, stdin=b"payload", path=str(stubs))
    strict = run_sh(layout, "--strict", "hook", "claude", "pre-tool", env={"STUB": "echo"}, stdin=b"payload", path=str(stubs))
    assert soft.returncode == 0 and strict.returncode == 2 and b"exit code 1" in soft.stderr and b"exit code 1" in strict.stderr, (soft, strict)
    assert soft.stdout == b"" and not started.exists()  # a guard failure starts no other interpreter


def test_py_without_a_runtime_passes_on_to_the_next_interpreter(tmp_path, layout, monkeypatch):
    # Each half needs its own prerequisites (cmd.exe and csc on Windows, sh): the parts that cannot run here are skipped. The sh part runs
    # the sh half of the polyglot launcher and the POSIX launcher.
    parts = ([(_py_without_a_runtime_in_cmd, None)] if sys.platform == "win32" and _csc() else []) + (
        [(_py_without_a_runtime_in_sh, name) for name in ("run-guard.cmd", "run-guard")] if SH else [])
    if not parts:
        pytest.skip("neither cmd.exe with a C# compiler nor sh is available")
    for part, name in parts:
        if name:
            monkeypatch.setattr(sys.modules[__name__], "SH_FILE", name)
        base = tmp_path / ("%s-%s" % (part.__name__, name or "cmd"))
        base.mkdir()
        part(base, layout)


@needs_sh
def test_sh_half_gives_python_a_windows_path_for_any_directory_name(tmp_path, sh_file):
    names = ["s;c,o=m", "t`ick", "plain"] if sys.platform == "win32" else ["plain"]
    for name in names:
        base = tmp_path / name
        (base / "hooks").mkdir(parents=True)
        (base / "scripts").mkdir()
        shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
        shutil.copy(POSIX, base / "hooks" / "run-guard")
        (base / "scripts" / "magos_guard.py").write_text(STUB, encoding="utf-8")
        r = run_sh(base, "hook", "codex", "pre-tool", env={"STUB": "argv0"}, stdin=b"{}")
        given = r.stdout.decode("utf-8", "replace")
        assert r.returncode == 0 and r.stderr == b"" and given, (name, r)  # the guard started: no launcher warning
        expected = os.path.realpath(str(base / "scripts" / "magos_guard.py"))
        if sys.platform == "win32":  # the Windows spelling (pwd -W), never an MSYS path such as /tmp/... that Python would misread
            assert re.match(r"[A-Za-z]:/", given), (name, given)
            assert os.path.normcase(os.path.realpath(given)) == os.path.normcase(expected), (name, given)
        else:
            assert os.path.realpath(given) == expected, (name, given)


def test_launcher_cases_need_no_particular_sh_or_temp_directory(tmp_path):
    # Without any sh on PATH the sh cases skip and the cmd cases pass.
    stripped = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not _find_sh(d))
    assert _find_sh(stripped) is None
    r = subprocess.run([sys.executable, "-m", "pytest", __file__, "-q", "-p", "no:cacheprovider", "-rs", "-k",
                        "test_sh_half or test_cmd_allow_deny_and_passthrough"], capture_output=True, env=dict(os.environ, PATH=stripped),
                       cwd=str(ROOT), stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=300)
    out = r.stdout.decode("utf-8", "replace")
    assert r.returncode == 0 and "no sh available" in out, out
    assert re.search(r"\b1 passed, 8 skipped\b" if sys.platform == "win32" else r"\b9 skipped\b", out), out
    if SH is None:
        pytest.skip("no sh available")
    # A bare sh (no cygpath, no coreutils) names the missing guard by the path the launcher derives, also for a launcher under the system
    # temporary directory (MSYS mounts it as /tmp), wherever pytest keeps its own temporary directories.
    work = tempfile.mkdtemp(prefix="magos launcher ", dir=tempfile.gettempdir())
    try:
        base = Path(os.path.realpath(work)) / "guard home"  # the long spelling of a temp dir given in 8.3 form (CI runners)
        (base / "hooks").mkdir(parents=True)
        shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
        shutil.copy(POSIX, base / "hooks" / "run-guard")
        for runner in (run_sh, run_posix):
            r = runner(base, "hook", "codex", "pre-tool", stdin=b"{}", path=str(tmp_path))
            text = r.stderr.decode("utf-8", "replace")
            assert r.returncode == 0 and "the guard script is missing" in text and names_path(text, base / "scripts" / "magos_guard.py"), text
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- the POSIX launcher and the entries that run each launcher (TC-850 to TC-855) -----------------------------------------------
def _code_lines(text):
    return [line for line in text.split("\n") if not line.lstrip().startswith("#")]


def test_the_posix_launcher_file():
    raw = POSIX.read_bytes()
    assert raw.startswith(b"#!/bin/sh\n") and b"\r" not in raw and b"CMDBLOCK" not in raw, raw[:80]
    text = raw.decode("utf-8")
    assert not re.search(r"(?im)^\s*(?:@echo|setlocal|set \"|if /i|exit /b|for %%)", text)  # no cmd syntax at all
    half = LAUNCHER.read_text(encoding="utf-8").split("\nCMDBLOCK\n", 1)[1].lstrip("\n")
    import difflib
    diff = [d for d in difflib.ndiff(_code_lines(half), _code_lines(text.split("\n", 1)[1])) if d[:2] in ("- ", "+ ")]
    assert [d[2:] for d in diff if d.startswith("- ")] == ['[ "$MAGOS_GUARD" = "off" ] && exit 0',
                                                           'for cmd in python3 "py -3" python; do  # a Python 2 `python` is reached only when neither '
                                                           'Python 3 name exists'], diff
    assert [d[2:] for d in diff if d.startswith("+ ")] == ["set +eu", 'case "$MAGOS_GUARD" in [Oo][Ff][Ff]) exit 0 ;; esac',
                                                           "candidates='python3,py -3,python'", "[ \"$OS\" = Windows_NT ] && candidates='py -3,python3,python'",
                                                           "oldifs=$IFS", "IFS=,", "for cmd in $candidates; do", "    IFS=$oldifs"], diff
    import hashlib
    assert hashlib.sha256(LAUNCHER.read_bytes()).hexdigest() == POLYGLOT_SHA256  # the launcher of the entries merged before 1.1.3


def test_entries_name_the_launcher_of_their_shell(monkeypatch):
    for g in json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]:
        command = g["hooks"][0]["command"]
        assert command.startswith('sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-guard" ') and "run-guard.cmd" not in command, command
    for platform in ("win32", "linux"):
        monkeypatch.setattr(G.sys, "platform", platform)
        claude = json.loads(G.host_snippet("claude", "/h"))["hooks"]["PreToolUse"]
        assert [g["hooks"][0]["command"] for g in claude] == ["sh '/h/guard/hooks/run-guard' --strict hook claude pre-tool",
                                                              "sh '/h/guard/hooks/run-guard' hook claude pre-tool"], (platform, claude)
        codex = json.loads(G.host_snippet("codex", "/h"))["hooks"]["PreToolUse"][0]["hooks"][0]
        assert codex["command"] == "sh '/h/guard/hooks/run-guard' hook codex pre-tool", (platform, codex)
        assert codex["commandWindows"] == "& '/h/guard/hooks/run-guard.cmd' hook codex pre-tool; exit $LASTEXITCODE", (platform, codex)
        hermes = G.host_snippet("hermes", "/h")
        want = "'\"/h/guard/hooks/run-guard.cmd\" hook hermes pre-tool'" if platform == "win32" else "'sh ''/h/guard/hooks/run-guard'' hook hermes pre-tool'"
        assert "command: %s\n" % want in hermes, (platform, hermes)


def _bash():
    """Git for Windows' bash on Windows (not the WSL launcher), bash elsewhere, or None."""
    for cand in ((r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")) if sys.platform == "win32" else (shutil.which("bash"),)):
        if cand and os.path.isfile(cand):
            if sys.platform != "win32":
                return cand
            p = subprocess.run([cand, "-c", "uname -s"], capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=60)
            if p.stdout.startswith((b"MINGW", b"MSYS")):
                return cand
    return None


def test_the_hooks_json_command_runs_the_posix_launcher(tmp_path, repo, guard):
    bash = _bash()
    if not bash:
        pytest.skip("no bash to run the hooks.json commands")
    plugin = tmp_path / "plugin 目录" / "1.1.3"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    shutil.copy(POSIX, plugin / "hooks" / "run-guard")
    os.chmod(plugin / "hooks" / "run-guard", 0o644)  # no execute bit, no .cmd beside it: sh runs the file
    shutil.copy(SCRIPT, plugin / "scripts" / "magos_guard.py")
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(plugin), MAGOS_LANG="en")  # the Windows spelling with backslashes on Windows
    strict, soft = (g["hooks"][0]["command"] for g in json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"])

    def entry(command, body):
        return subprocess.run([bash, "-c", command], input=json.dumps(body).encode("utf-8"), capture_output=True, env=env, cwd=str(tmp_path),
                              creationflags=NO_WINDOW, timeout=180)
    r = entry(soft, {"tool_name": "Bash", "tool_input": {"command": "echo hi"}, "cwd": str(tmp_path)})
    assert r.returncode == 0 and json.loads(r.stdout) == {}, r
    assert guard(repo, "plan", "--branch", "agent/a", "--paths", "src/a.py").rc == 0  # a claim: the repository is engaged
    r = entry(soft, {"tool_name": "Bash", "tool_input": {"command": "git switch -c agent/unplanned"}, "cwd": str(repo.path)})
    assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny", r
    (plugin / "scripts" / "magos_guard.py").unlink()
    r = entry(strict, {"tool_name": "EnterWorktree", "tool_input": {"name": "x"}, "cwd": str(tmp_path)})
    assert r.returncode == 2 and b"the guard script is missing" in r.stderr, r
    r = entry(soft, {"tool_name": "Bash", "tool_input": {"command": "echo hi"}, "cwd": str(tmp_path)})
    assert r.returncode == 0 and b"the guard script is missing" in r.stderr and r.stdout == b"", r
    assert not (plugin / "hooks" / "run-guard.cmd").exists()


@needs_sh
def test_the_posix_launcher_tries_py_first_on_windows(tmp_path, layout):
    log = tmp_path / "order.log"

    def stub(name):
        return "#!/bin/sh\necho %s >> '%s'\n[ \"$1\" = -3 ] && shift\nexec '%s' \"$@\"\n" % (name, str(log).replace("\\", "/"),
                                                                                         sys.executable.replace("\\", "/"))
    stubs = _bin(tmp_path / "stubs", {"python3": stub("python3"), "py": stub("py"), "python": stub("python")})
    plain = {k: v for k, v in os.environ.items() if k.upper() != "OS"}
    for os_value, first in (("Windows_NT", "py"), (None, "python3")):
        base_env = dict(plain, **({"OS": os_value} if os_value else {}))
        r = run_posix(layout, "hook", "claude", "pre-tool", env={"STUB": "echo"}, stdin=b"{}", path=str(stubs), base_env=base_env)
        assert r.returncode == 0 and r.stdout == b"{}|hook claude pre-tool", (os_value, r)
        assert log.read_text().split() == [first], (os_value, log.read_text())
        log.unlink()
    (stubs / "py").unlink()  # a missing first candidate passes on to the next
    r = run_posix(layout, "hook", "claude", "pre-tool", env={"STUB": "echo"}, stdin=b"{}", path=str(stubs), base_env=dict(plain, OS="Windows_NT"))
    assert r.returncode == 0 and log.read_text().split() == ["python3"], (r, log.read_text())


def test_install_and_doctor_handle_both_launchers(repo, guard, tmp_path, monkeypatch):
    home = tmp_path / "mh"
    slashed = str(home).replace("\\", "/")
    assert guard(repo, "install", "--host", "codex", "--home", str(home)).rc == 0
    for name in ("run-guard", "run-guard.cmd"):
        copy = home / "guard" / "hooks" / name
        assert copy.read_bytes() == (ROOT / "hooks" / name).read_bytes(), name
        if os.name != "nt":
            assert copy.stat().st_mode & 0o111, name
    base = guard(repo, "doctor", "--home", str(home))
    assert "the same as this guard" in base.out and "run-guard.cmd through sh" not in base.out, base.out
    saved = (home / "guard" / "hooks" / "run-guard").read_bytes()
    (home / "guard" / "hooks" / "run-guard").write_bytes(b"#!/bin/sh\nexit 0\n")
    r = guard(repo, "doctor", "--home", str(home))
    assert r.rc == 1 and "DIFFERS" in r.out and "the launcher %s/guard/hooks/run-guard (" % slashed in r.out, r.out
    (home / "guard" / "hooks" / "run-guard").unlink()  # a guard home an install before 1.1.3 wrote
    r = guard(repo, "doctor", "--home", str(home))
    assert r.rc == 1 and "the launcher %s/guard/hooks/run-guard is missing" % slashed in r.out and "e3b0c44298fc" not in r.out, r.out
    (home / "guard" / "hooks" / "run-guard").write_bytes(saved)
    generated = home / "guard" / "generated"
    old = json.loads((generated / "codex.json").read_text(encoding="utf-8"))
    old["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "sh '%s/guard/hooks/run-guard.cmd' hook codex pre-tool" % slashed
    (generated / "codex.json").write_text(json.dumps(old), encoding="utf-8")
    (generated / "hermes.yaml").write_text("hooks:\n  pre_tool_call:\n    - matcher: \"terminal\"\n      command: 'sh ''%s/guard/hooks/run-guard.cmd'' "
                                           "hook hermes pre-tool'\n      timeout: 25\n      fail_closed: true\n" % slashed, encoding="utf-8")
    claude = {"hooks": {"PreToolUse": [{"matcher": "^EnterWorktree$", "hooks": [{
        "type": "command", "command": "'%s/guard/hooks/run-guard.cmd' --strict hook claude pre-tool" % slashed, "shell": "bash", "timeout": 25}]}]}}
    (generated / "claude.json").write_text(json.dumps(claude), encoding="utf-8")
    r = guard(repo, "doctor", "--home", str(home))
    assert r.rc == base.rc and r.out.count("it runs run-guard.cmd through sh") == 2, r.out
    assert "install --host codex" in r.out and "install --host hermes" in r.out
    assert "claude entry %s/guard/generated/claude.json: it runs run-guard.cmd" % slashed in r.out and "starts cmd.exe" in r.out, r.out
    assert "install --host claude" in r.out and "~/.claude/settings.json" in r.out
    hermes = tmp_path / "hermes-home"
    (hermes / "plugins" / "magos" / "hooks").mkdir(parents=True)
    (hermes / "plugins" / "magos" / "hooks" / "run-guard").write_bytes(POSIX.read_bytes())
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    assert G.pkey(os.path.abspath(str(hermes / "plugins" / "magos"))) in G.tamper_roots()


def test_the_posix_launcher_ignores_inherited_shell_options(tmp_path, repo, guard):
    bash = _bash()
    if not bash:
        pytest.skip("no bash to run the hooks.json commands")
    plugin = tmp_path / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    shutil.copy(POSIX, plugin / "hooks" / "run-guard")
    strict, soft = (g["hooks"][0]["command"] for g in json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"])
    assert guard(repo, "plan", "--branch", "agent/a", "--paths", "src/a.py").rc == 0
    allowed = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}, "cwd": str(tmp_path)}
    denied = {"tool_name": "Bash", "tool_input": {"command": "git switch -c agent/unplanned"}, "cwd": str(repo.path)}
    worktree = {"tool_name": "EnterWorktree", "tool_input": {"name": "x"}, "cwd": str(tmp_path)}
    plain = {k: v for k, v in os.environ.items() if k not in ("SHELLOPTS", "MAGOS_GUARD")}

    def entry(command, body, **extra):
        env = dict(plain, CLAUDE_PLUGIN_ROOT=str(plugin), MAGOS_LANG="en", **extra)
        return subprocess.run([bash, "-c", command], input=json.dumps(body).encode("utf-8"), capture_output=True, env=env, cwd=str(tmp_path),
                              creationflags=NO_WINDOW, timeout=180)
    for options in ("nounset", "errexit", "errexit:nounset"):
        shutil.copy(SCRIPT, plugin / "scripts" / "magos_guard.py")
        r = entry(soft, allowed, SHELLOPTS=options)
        assert r.returncode == 0 and json.loads(r.stdout) == {}, (options, r)
        r = entry(soft, denied, SHELLOPTS=options)
        assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny", (options, r)
        (plugin / "scripts" / "magos_guard.py").unlink()
        r = entry(strict, worktree, SHELLOPTS=options)
        assert r.returncode == 2 and b"the guard script is missing" in r.stderr, (options, r)
    for value in ("OFF", "Off", "off"):  # the script is missing: the launcher ends before it looks for it
        for command in (strict, soft):
            r = entry(command, worktree, MAGOS_GUARD=value)
            assert r.returncode == 0 and r.stdout == b"" and r.stderr == b"", (value, command, r)


def test_install_names_a_hermes_plugin_that_is_out_of_date(tmp_path, monkeypatch):
    hermes = tmp_path / "hermes-home"
    plugin = hermes / "plugins" / "magos"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    (plugin / "hooks" / "run-guard.cmd").write_bytes(LAUNCHER.read_bytes())  # the layout of a Hermes plugin before 1.1.3
    (plugin / "scripts" / "magos_guard.py").write_text('GUARD_VERSION = "1.1.2"\n', encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    for platform in ("linux", "win32"):
        monkeypatch.setattr(G.sys, "platform", platform)
        launcher, note = G.hermes_plugin()
        assert launcher is None and note and "holds guard 1.1.2, not %s" % G.GUARD_VERSION in note, (platform, note)
    (plugin / "scripts" / "magos_guard.py").write_bytes(SCRIPT.read_bytes())
    monkeypatch.setattr(G.sys, "platform", "linux")
    launcher, note = G.hermes_plugin()
    assert launcher is None and note and "has no run-guard," in note, note
    monkeypatch.setattr(G.sys, "platform", "win32")
    launcher, note = G.hermes_plugin()
    assert launcher and launcher.endswith("/hooks/run-guard.cmd") and note is None, (launcher, note)
