"""The coverage gate of the CI coverage job.

    python -X utf8 tests/codex/coverage_gate.py [--report-only]

It reads `.quality/qguard.json`, runs its `coverage_commands` exactly as written (in the repository root, each within
`test_timeout_seconds`), and reads the LCOV report named by `coverage_report`. It fails (exit 1) when a command exits non-zero,
when the report is missing, when a source file is missing from the report, or when a source file or the project as a whole has
line coverage that is not strictly above `min_coverage_exclusive` (90 means 90.00 percent fails). A source file is a tracked
file that the quality hook counts as source: a code suffix, outside `tests/` and the other tool directories, not named
`test_*`, and not matched by `excluded_sources`. Every changed source file is such a file, so the gate holds each of them to
the limit. `--report-only` judges the report that is already there without running the commands.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".quality" / "qguard.json"
SOURCE_SUFFIXES = frozenset({".py", ".rs", ".cs", ".vb", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".c", ".cc", ".cpp", ".h",
                             ".hpp"})
IGNORED_DIRS = frozenset({".git", ".quality", ".uqh", ".claude", ".codex", ".qguard", ".venv", "venv", "node_modules", "target", "dist",
                          "build", "bin", "obj", "__pycache__", "coverage", "tests", "test", "testdata", "vendor"})


def load_config(path=CONFIG):
    with open(str(path), "rb") as fh:
        return json.loads(fh.read().decode("utf-8-sig"))


def coverage_commands(cfg):
    """The argv lists of `coverage_commands`, checked: a non-empty list of non-empty lists of strings."""
    commands = cfg.get("coverage_commands")
    if not isinstance(commands, list) or not commands:
        raise ValueError("coverage_commands is empty")
    for argv in commands:
        if not isinstance(argv, list) or not argv or not all(isinstance(word, str) for word in argv):
            raise ValueError("coverage_commands must be argv lists of strings: %r" % (argv,))
    return [list(argv) for argv in commands]


def limit_of(cfg):
    limit = float(cfg.get("min_coverage_exclusive", 90))
    if not 90 <= limit < 100:
        raise ValueError("min_coverage_exclusive must be at least 90 and below 100")
    return limit


def is_source(rel, cfg):
    pure = PurePosixPath(rel.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or any(part in IGNORED_DIRS for part in pure.parts[:-1]):
        return False
    name = pure.name.lower()
    if pure.suffix.lower() not in SOURCE_SUFFIXES or name.startswith("test_") or name.endswith("_test.py"):
        return False
    return not any(fnmatch.fnmatch(rel, pattern) for pattern in cfg.get("excluded_sources", []))


def tracked_sources(cfg, root=ROOT):
    listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, stdin=subprocess.DEVNULL, check=True).stdout
    return sorted(rel for rel in listed.decode("utf-8").split("\0") if rel and is_source(rel, cfg))


def key(path, root=ROOT):
    """One spelling of a path for comparison: absolute, real separators folded to '/', case folded where the platform folds it."""
    p = Path(path)
    p = p if p.is_absolute() else Path(root) / p
    return os.path.normcase(os.path.abspath(str(p))).replace("\\", "/")


def lcov_lines(text, root=ROOT):
    """{path key: {line: hits}} of an LCOV report; records of one file are merged by the larger hit count."""
    files, path, lines = {}, None, {}

    def finish():
        if path is not None:
            merged = files.setdefault(key(path, root), {})
            for number, hits in lines.items():
                merged[number] = max(hits, merged.get(number, 0))
    for item in text.splitlines():
        if item.startswith("SF:"):
            finish()
            path, lines = item[3:].strip(), {}
        elif item.startswith("DA:") and path is not None:
            fields = item[3:].split(",")
            if len(fields) >= 2:
                lines[int(fields[0])] = max(lines.get(int(fields[0]), 0), int(fields[1]))
        elif item.strip() == "end_of_record":
            finish()
            path, lines = None, {}
    finish()
    return files


def above(hit, total, limit):
    return total > 0 and hit * 100 > limit * total


def gate(report_text, sources, limit, root=ROOT):
    """-> (rows, failures): one row (path, covered, total) per source in the report, and every failure as text."""
    files = lcov_lines(report_text, root)
    rows, failures, every = [], [], []
    for rel in sources:
        lines = files.get(key(rel, root))
        if lines is None:
            failures.append("%s: not in the coverage report (unmeasured is not covered)" % rel)
            continue
        hit, total = sum(1 for hits in lines.values() if hits > 0), len(lines)
        rows.append((rel, hit, total))
        every.extend(lines.values())
        if not above(hit, total, limit):
            failures.append("%s: line coverage %d/%d = %.2f%%, must be above %g%%" % (rel, hit, total, 100.0 * hit / total if total else 0, limit))
    hit, total = sum(1 for hits in every if hits > 0), len(every)
    if not sources or not above(hit, total, limit):
        failures.append("project: line coverage %d/%d = %.2f%%, must be above %g%%" % (hit, total, 100.0 * hit / total if total else 0, limit))
    return rows, failures


def run_commands(cfg, root=ROOT):
    """Run the coverage commands in order, each with its output piped and then printed (no console handle is inherited); -> the failure
    text, or None when every command exits 0."""
    timeout = float(cfg.get("test_timeout_seconds", 600))
    for argv in coverage_commands(cfg):
        print("$ " + " ".join(argv), flush=True)
        try:
            done = subprocess.run(argv, cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired as err:
            sys.stdout.write((err.output or b"").decode("utf-8", "replace"))
            return "%s: %s" % (" ".join(argv), err)
        except OSError as err:
            return "%s: %s" % (" ".join(argv), err)
        sys.stdout.write(done.stdout.decode("utf-8", "replace"))
        sys.stdout.flush()
        if done.returncode != 0:
            return "%s: exit code %d" % (" ".join(argv), done.returncode)
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the coverage commands of .quality/qguard.json and gate every source file.",
                                     allow_abbrev=False)
    parser.add_argument("--report-only", action="store_true", help="judge the existing report without running the commands")
    args = parser.parse_args(argv)
    cfg = load_config()
    limit = limit_of(cfg)
    report = ROOT / cfg.get("coverage_report", ".quality/coverage/lcov.info")
    if not args.report_only:
        if report.exists():
            report.unlink()  # a report from an earlier run never counts
        failed = run_commands(cfg)
        if failed:
            print("coverage gate FAILED: " + failed)
            return 1
    if not report.is_file():
        print("coverage gate FAILED: no coverage report at %s" % report)
        return 1
    rows, failures = gate(report.read_text(encoding="utf-8"), tracked_sources(cfg), limit)
    for rel, hit, total in rows:
        print("%-40s %5d/%-5d %6.2f%%" % (rel, hit, total, 100.0 * hit / total if total else 0))
    for text in failures:
        print("coverage gate FAILED: " + text)
    if not failures:
        print("coverage gate passed: every source file and the project are above %g%%" % limit)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
