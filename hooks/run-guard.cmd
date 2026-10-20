: << 'CMDBLOCK'
@echo off
REM MAGOS guard launcher (polyglot: cmd.exe runs this block, POSIX sh runs everything after CMDBLOCK). LF endings, no labels, no goto.
REM Contract: guard exit 0 = allow or deny (the deny is a JSON object on stdout). Any other exit, a missing script or no Python is a FAILURE:
REM --strict turns it into exit 2 (block), default (soft) into a warning and exit 0.
REM NoDefaultCurrentDirectoryInExePath keeps cmd.exe and the guard from running a py, python or git planted in the working directory.
REM Only the hook subcommand runs through the launcher (after an optional --strict); any other first argument is refused with exit 2.
REM The guard's stderr reaches the host unchanged.
setlocal
set "NoDefaultCurrentDirectoryInExePath=1"
if /i "%MAGOS_GUARD%"=="off" exit /b 0
set "STRICT="
set "GARGS=%*"
set "FIRST=%~1"
if /i "%~1"=="--strict" set "STRICT=1" & set "GARGS=%2 %3 %4 %5 %6" & set "FIRST=%~2"
if not "%FIRST%"=="hook" (1>&2 echo MAGOS guard: the launcher runs only the hook subcommand; run other commands with the guard script itself in your own terminal& exit /b 2)
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
for %%I in ("%~dp0..\scripts\magos_guard.py") do set "GUARD=%%~fI"
set "STOP=To stop the guard: set MAGOS_GUARD=off in the host's environment, or remove the MAGOS entry from the host's hook configuration (for example Claude Code: claude plugin disable magos)"
set "KIND="
set "WHY="
set "RC=9009"
if not exist "%GUARD%" set "KIND=missing" & set "WHY=the guard script is missing: %GUARD%"
REM Each interpreter is looked up on PATH by a for search (never in the working directory) and run by its full path through call, so that a
REM .bat or .cmd shim returns here. A name that is not on PATH is never started; one that exits 9009 (the Microsoft Store stub) passes on.
set "PYEXE="
for %%I in (py.exe) do set "PYEXE=%%~$PATH:I"
if not defined WHY if defined PYEXE call "%PYEXE%" -3 -X utf8 -B "%GUARD%" %GARGS%
if not defined WHY if defined PYEXE set "RC=%ERRORLEVEL%"
REM py.exe exits 103 or 112 when the Python launcher finds no runtime (or none at the path it was given): it passes on like a missing one.
if "%RC%"=="103" set "RC=9009"
if "%RC%"=="112" set "RC=9009"
set "PYEXE="
if "%RC%"=="9009" for %%I in (python.exe) do set "PYEXE=%%~$PATH:I"
if not defined WHY if defined PYEXE call "%PYEXE%" -X utf8 -B "%GUARD%" %GARGS%
if not defined WHY if defined PYEXE set "RC=%ERRORLEVEL%"
set "PYEXE="
if "%RC%"=="9009" for %%I in (python.bat) do set "PYEXE=%%~$PATH:I"
if not defined WHY if defined PYEXE call "%PYEXE%" -X utf8 -B "%GUARD%" %GARGS%
if not defined WHY if defined PYEXE set "RC=%ERRORLEVEL%"
set "PYEXE="
if "%RC%"=="9009" for %%I in (python.cmd) do set "PYEXE=%%~$PATH:I"
if not defined WHY if defined PYEXE call "%PYEXE%" -X utf8 -B "%GUARD%" %GARGS%
if not defined WHY if defined PYEXE set "RC=%ERRORLEVEL%"
if not defined WHY if "%RC%"=="9009" set "KIND=nopython" & set "WHY=no Python 3 found (looked for py.exe, python.exe, python.bat and python.cmd on PATH)"
if not defined WHY if not "%RC%"=="0" set "KIND=failed" & set "WHY=the guard script failed with exit code %RC%"
if not defined WHY exit /b 0
setlocal EnableDelayedExpansion
if "%KIND%"=="missing" 1>&2 echo MAGOS guard: !WHY!. Restore it: run magos_guard.py install again for this host from the current MAGOS package, or reinstall the plugin. !STOP!.
if "%KIND%"=="nopython" 1>&2 echo MAGOS guard: !WHY!. Install Python 3.9 or later, then diagnose with: py -3 "!GUARD!" doctor. !STOP!.
if "%KIND%"=="failed" 1>&2 echo MAGOS guard: !WHY!. Diagnose: py -3 "!GUARD!" doctor. !STOP!.
if defined STRICT (exit /b 2) else (exit /b 0)
CMDBLOCK

# ---- POSIX part (Linux, macOS, and Git Bash when sh runs this file); cmd.exe never reaches it ----
# Only shell builtins run before the guard, so a bare sh without coreutils on PATH works: ${0%/*} instead of dirname, read instead of
# cat. The payload is read once and handed to each candidate interpreter; the next candidate is tried only when one is missing: exit
# 127, or 9009 (the Windows "not found" code and the Microsoft Store stub's), which sh sees as 49, or, for py -3 only, 103 or 112 (the
# Python launcher found no runtime). Each candidate's stdout is held back until its exit code is known, so a stub's text never precedes
# the verdict.
[ "$MAGOS_GUARD" = "off" ] && exit 0
STRICT=
if [ "$1" = "--strict" ]; then STRICT=1; shift; fi
if [ "$1" != hook ]; then
    printf '%s\n' "MAGOS guard: the launcher runs only the hook subcommand; run other commands with the guard script itself in your own terminal" >&2
    exit 2
fi
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 NoDefaultCurrentDirectoryInExePath=1
bs='\'
case "$0" in
    *"$bs"*) d=${0%["$bs"/]*} ;;  # a Windows spelling (Git Bash): cut at the last separator of either kind
    */*) d=${0%/*}; [ -n "$d" ] || d=/ ;;
    *) d=. ;;
esac
# pwd -W (a builtin of MSYS and Git Bash) gives the Windows spelling, which a Windows Python opens whatever characters the path holds;
# other shells refuse the option and print the pwd path.
HERE="$(CDPATH= cd -- "$d" 2>/dev/null && { pwd -W 2>/dev/null || pwd; })"
GUARD="${HERE%/*}/scripts/magos_guard.py"
fail() {
    g="$GUARD"
    if command -v cygpath >/dev/null 2>&1; then g="$(cygpath -w "$GUARD" 2>/dev/null)" || g="$GUARD"; fi
    case "$1" in
        nohere) why="cannot locate the launcher directory from $0"; fix="Run the launcher by its full path" ;;
        missing) why="the guard script is missing: $g"
                 fix="Restore it: run magos_guard.py install again for this host from the current MAGOS package, or reinstall the plugin" ;;
        nopython) why="no Python 3 found (tried python3, py -3, python)"; fix="Install Python 3.9 or later, then diagnose with: python3 \"$g\" doctor" ;;
        *) why="the guard script failed with exit code $1"; fix="Diagnose: $cmd \"$g\" doctor" ;;
    esac
    printf '%s\n' "MAGOS guard: $why. $fix. To stop the guard: set MAGOS_GUARD=off in the host's environment, or remove the MAGOS entry from the host's hook configuration (for example Claude Code: claude plugin disable magos)." >&2
    if [ -n "$STRICT" ]; then exit 2; else exit 0; fi
}
[ -n "$HERE" ] || fail nohere
[ -f "$GUARD" ] || fail missing
payload=
while IFS= read -r line; do payload="$payload$line
"; done
payload="$payload$line"
for cmd in python3 "py -3" python; do  # a Python 2 `python` is reached only when neither Python 3 name exists
    command -v "${cmd%% *}" >/dev/null 2>&1 || continue
    out="$(printf '%s' "$payload" 2>/dev/null | $cmd -X utf8 -B "$GUARD" "$@"; echo ".$?")"
    rc="${out##*.}"
    out="${out%.*}"
    case "$rc" in 127|9009|49) continue ;; esac
    if [ "$cmd" = "py -3" ]; then case "$rc" in 103|112) continue ;; esac; fi  # the Python launcher found no runtime
    printf '%s' "$out"
    [ "$rc" = 0 ] && exit 0
    fail "$rc"
done
fail nopython
