: << 'CMDBLOCK'
@echo off
REM MAGOS guard launcher (polyglot: cmd.exe runs this block, POSIX sh runs everything after CMDBLOCK). LF endings, no labels, no goto.
REM Contract: guard exit 0 = allow or deny (the deny is a JSON object on stdout). Any other exit, a missing script or no Python is a FAILURE:
REM --strict turns it into exit 2 (block), default (soft) into a warning and exit 0.
setlocal
if /i "%MAGOS_GUARD%"=="off" exit /b 0
set "STRICT="
set "GARGS=%*"
if /i "%~1"=="--strict" set "STRICT=1" & set "GARGS=%2 %3 %4 %5 %6"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "GUARD=%~dp0..\scripts\magos_guard.py"
set "WHY="
if not exist "%GUARD%" set "WHY=the guard script is missing: %GUARD%"
if not defined WHY py -3 -X utf8 -B "%GUARD%" %GARGS% 2>nul
set "RC=%ERRORLEVEL%"
if not defined WHY if "%RC%"=="9009" python -X utf8 -B "%GUARD%" %GARGS% 2>nul
if not defined WHY if "%RC%"=="9009" set "RC=%ERRORLEVEL%"
if not defined WHY if "%RC%"=="9009" set "WHY=no Python 3 found (tried py -3, python)"
if not defined WHY if not "%RC%"=="0" set "WHY=the guard script failed with exit code %RC%"
if not defined WHY exit /b 0
echo MAGOS guard: %WHY%. Diagnose: py -3 scripts\magos_guard.py doctor. To stop the guard: claude plugin disable magos. 1>&2
if defined STRICT (exit /b 2) else (exit /b 0)
CMDBLOCK

# ---- POSIX part (Linux, macOS, and Git Bash when sh runs this file); cmd.exe never reaches it ----
[ "$MAGOS_GUARD" = "off" ] && exit 0
STRICT=
if [ "$1" = "--strict" ]; then STRICT=1; shift; fi
fail() { echo "MAGOS guard: $1. Diagnose: python3 scripts/magos_guard.py doctor. To stop the guard: claude plugin disable magos." >&2; if [ -n "$STRICT" ]; then exit 2; else exit 0; fi; }
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/../scripts/magos_guard.py"
[ -f "$GUARD" ] || fail "the guard script is missing: $GUARD"
if command -v cygpath >/dev/null 2>&1; then GUARD="$(cygpath -w "$GUARD")"; fi
for cmd in python3 python "py -3"; do
    if $cmd -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' >/dev/null 2>&1; then
        $cmd -X utf8 -B "$GUARD" "$@"
        rc=$?
        [ "$rc" = "0" ] && exit 0
        fail "the guard script failed with exit code $rc"
    fi
done
fail "no Python 3 found (tried python3, python, py -3)"
