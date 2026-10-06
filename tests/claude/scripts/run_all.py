# ```cypher
# CREATE
#   (file:File {name: "run_all.py", type: "file", language: "python"}),
#   (v_SCRIPTS:Variable {name: "SCRIPTS", type: "variable"}),
#   (v_HERE:Variable {name: "HERE", type: "variable"}),
#   (v_REPO:Variable {name: "REPO", type: "variable"}),
#   (v_SUMMARY:Variable {name: "SUMMARY", type: "variable"}),
#   (f_layers:Function {name: "layers", type: "function", signature: "layers(options: argparse.Namespace) -> list[tuple[str, list[str]]]"}),
#   (f_main:Function {name: "main", type: "function", signature: "main() -> int"}),
#   (file)-[:CONTAINS]->(v_SCRIPTS),
#   (file)-[:CONTAINS]->(v_HERE),
#   (file)-[:CONTAINS]->(v_REPO),
#   (file)-[:CONTAINS]->(v_SUMMARY),
#   (file)-[:CONTAINS]->(f_layers),
#   (file)-[:CONTAINS]->(f_main),
#   (f_layers)-[:USES]->(v_REPO),
#   (f_layers)-[:USES]->(v_SCRIPTS),
#   (f_main)-[:CALLS]->(f_layers),
#   (f_main)-[:USES]->(v_REPO),
#   (f_main)-[:USES]->(v_SUMMARY),
#   (file)-[:CALLS]->(f_main);
# ```
"""Run every GitConverge test layer that needs no AI model, and write tests/claude/results/summary.md.

Layers: Cypher headers, policy unit tests, Git behavior probes, source contracts, reference-executor scenarios,
mutation checks, Claude-harness fixture checks, the pre-existing codex source-contract suite, and the Agent Plugins
checker mutation tests.
Add --runtime to also run the core scenarios through the real Claude CLI (uses model quota).
Run: python -X utf8 tests/claude/scripts/run_all.py [--runtime] [--fixture-root <short path>]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
HERE = SCRIPTS.parent
REPO = HERE.parents[1]
SUMMARY = HERE / "results" / "summary.md"


def layers(options: argparse.Namespace) -> list[tuple[str, list[str]]]:
    """(label, argv) for each layer, cheapest first."""
    fixture = ["--fixture-root", options.fixture_root] if options.fixture_root else []
    python = [sys.executable, "-X", "utf8"]
    found = [
        ("cypher headers match the code", [*python, str(SCRIPTS / "cypher_header.py"), "--check"]),
        ("command policy unit tests", [*python, str(SCRIPTS / "test_command_policy.py")]),
        ("git behavior probes", [*python, str(SCRIPTS / "git_behavior_probes.py"), *fixture]),
        ("GitConverge source contracts", [*python, str(SCRIPTS / "run_claude_contracts.py")]),
        ("reference executor scenarios", [*python, str(SCRIPTS / "run_reference_cases.py"), *fixture]),
        ("mutation checks", [*python, str(SCRIPTS / "run_mutation_checks.py"), *fixture]),
        ("claude harness fixture check", [*python, str(SCRIPTS / "run_claude_cases.py"), "--fixture-check", "--case", "*", *fixture]),
        ("codex source contracts (existing suite)", [*python, str(REPO / "tests" / "codex" / "contracts" / "run_contract_cases.py")]),
        ("agent plugin checker mutation tests", [*python, str(REPO / "tests" / "codex" / "contracts" / "test_agent_plugin.py")]),
    ]
    if options.runtime:
        found.append(("claude runtime: core scenarios", [*python, str(SCRIPTS / "run_claude_cases.py"), *fixture]))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", action="store_true", help="also run the core scenarios through the real Claude CLI")
    parser.add_argument("--fixture-root", help="short directory for fixtures (Windows path length)")
    options = parser.parse_args()
    rows, failed = [], False
    for label, argv in layers(options):
        proc = subprocess.run(argv, cwd=str(REPO), text=True, encoding="utf-8", errors="replace", capture_output=True,
                              check=False)
        lines = [line for line in (proc.stdout + proc.stderr).strip().splitlines() if line.strip()]
        last = lines[-1] if lines else ""
        status = {0: "PASS", 2: "UNVERIFIED"}.get(proc.returncode, "FAIL")
        rows.append((label, status, last))
        failed = failed or status == "FAIL"
        print(f"{rows[-1][1]:5} {label}: {last}")
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    table = ["# GitConverge test summary", "", "| Layer | Result | Last line |", "|---|---|---|"]
    table += [f"| {label} | {status} | {last.replace('|', '/')} |" for label, status, last in rows]
    SUMMARY.write_text("\n".join(table) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
