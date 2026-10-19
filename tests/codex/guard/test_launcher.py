"""hooks/run-guard.cmd: the polyglot launcher (cmd.exe half and sh half), its failure map and its pass-through contract."""
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

from conftest import ROOT, SH, _find_sh

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
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
STOP = "To stop the guard: set MAGOS_GUARD=off in the host's environment, or remove the MAGOS entry from the host's hook configuration"
CLAUDE_EXAMPLE = "(for example Claude Code: claude plugin disable magos)"


@pytest.fixture
def layout(tmp_path):
    base = tmp_path / "目录 with space"
    (base / "hooks").mkdir(parents=True)
    (base / "scripts").mkdir()
    shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
    (base / "scripts" / "magos_guard.py").write_text(STUB, encoding="utf-8")
    return base


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
    return subprocess.run([SH, str(launcher or base / "hooks" / "run-guard.cmd"), *" ".join(words).split()], input=b"" if stdin is None else stdin, capture_output=True,
                          env=_env(env, path, base_env), cwd=cwd, creationflags=NO_WINDOW, timeout=120)


def halves():
    """The launcher halves this platform can run: cmd.exe on Windows, sh wherever one exists."""
    return ([run_cmd] if sys.platform == "win32" else []) + ([run_sh] if SH else [])


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
def test_sh_half_reads_stdin_once_and_runs_the_guard_directly(tmp_path, layout):
    # python3 exits 127 and python 9009 after printing the Microsoft Store stub text on stdout; each reads its stdin first, as an
    # interpreter would. py -3 runs the real interpreter. No dirname, cat or cygpath is on this PATH.
    stubs = _bin(tmp_path / "stubs", {
        "python3": "#!/bin/sh\nwhile IFS= read -r l; do :; done\nexit 127\n",
        "python": "#!/bin/sh\nwhile IFS= read -r l; do :; done\n"
                  "echo 'Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut.'\nexit 9009\n",
        "py": _runs(sys.executable)})
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


def _host_neutral(text):
    assert STOP in text and CLAUDE_EXAMPLE in text, text
    assert text.count("claude plugin disable magos") == 1 and "To stop the guard: claude plugin disable magos" not in text, text


def test_failure_text_is_host_neutral_and_absolute(tmp_path):
    if not halves():
        pytest.skip("neither cmd.exe nor sh is available")
    base = tmp_path / "guard home"  # a launcher copied without its guard script
    (base / "hooks").mkdir(parents=True)
    shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
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


@pytest.mark.parametrize("half", ["sh", "cmd"])
def test_a_non_git_payload_through_the_launcher_is_fast(tmp_path, half):
    """One interpreter start per call: an ordinary command outside any repository finishes well inside a fixed bound."""
    if half == "cmd" and sys.platform != "win32":
        pytest.skip("cmd.exe half of the launcher")
    if half == "sh" and not SH:
        pytest.skip("no sh available")
    runner = run_sh if half == "sh" else run_cmd
    body = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "cwd": str(tmp_path)}).encode()
    times = []
    for _ in range(3):
        start = time.monotonic()
        r = runner(None, "hook", "claude", "pre-tool", stdin=body, cwd=str(tmp_path), launcher=LAUNCHER)
        times.append(time.monotonic() - start)
        assert r.returncode == 0 and json.loads(r.stdout) == {}, r
    assert min(times) < 2.5, times


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


@needs_sh
def test_sh_half_gives_python_a_windows_path_for_any_directory_name(tmp_path):
    names = ["s;c,o=m", "t`ick", "plain"] if sys.platform == "win32" else ["plain"]
    for name in names:
        base = tmp_path / name
        (base / "hooks").mkdir(parents=True)
        (base / "scripts").mkdir()
        shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
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
    assert re.search(r"\b1 passed, 3 skipped\b" if sys.platform == "win32" else r"\b4 skipped\b", out), out
    if SH is None:
        pytest.skip("no sh available")
    # A bare sh (no cygpath, no coreutils) names the missing guard by the path the launcher derives, also for a launcher under the system
    # temporary directory (MSYS mounts it as /tmp), wherever pytest keeps its own temporary directories.
    work = tempfile.mkdtemp(prefix="magos launcher ", dir=tempfile.gettempdir())
    try:
        base = Path(work) / "guard home"
        (base / "hooks").mkdir(parents=True)
        shutil.copy(LAUNCHER, base / "hooks" / "run-guard.cmd")
        r = run_sh(base, "hook", "codex", "pre-tool", stdin=b"{}", path=str(tmp_path))
        text = r.stderr.decode("utf-8", "replace")
        assert r.returncode == 0 and "the guard script is missing" in text and names_path(text, base / "scripts" / "magos_guard.py"), text
    finally:
        shutil.rmtree(work, ignore_errors=True)
