"""
CREATE
  (file:File {name: "run_contract_cases.py", type: "file", language: "python"}),
  (main:Function {name: "main", type: "function", signature: "main() -> int"}),
  (run_case:Function {name: "run_case", type: "function", signature: "run_case(spec: dict) -> dict"}),
  (path_ctor:Function {name: "Path", type: "function"}),
  (path_resolve:Function {name: "Path.resolve", type: "function"}),
  (root:Variable {name: "ROOT", type: "variable"}),
  (tests_dir:Variable {name: "TESTS_DIR", type: "variable"}),
  (cases_dir:Variable {name: "CASES_DIR", type: "variable"}),
  (manifest:Variable {name: "MANIFEST", type: "variable"}),
  (specs:Variable {name: "specs", type: "variable"}),
  (results:Variable {name: "results", type: "variable"}),
  (passed:Variable {name: "passed", type: "variable"}),
  (spec:Variable {name: "spec", type: "variable"}),
  (check:Variable {name: "check", type: "variable"}),
  (source_path:Variable {name: "source_path", type: "variable"}),
  (source:Variable {name: "source", type: "variable"}),
  (missing:Variable {name: "missing", type: "variable"}),
  (match:Variable {name: "match", type: "variable"}),
  (value:Variable {name: "value", type: "variable"}),
  (check_results:Variable {name: "check_results", type: "variable"}),
  (case_dir:Variable {name: "case_dir", type: "variable"}),
  (evidence_dir:Variable {name: "evidence_dir", type: "variable"}),
  (result:Variable {name: "result", type: "variable"}),
  (lines:Variable {name: "lines", type: "variable"}),
  (path_read_text:Function {name: "Path.read_text", type: "function"}),
  (path_exists:Function {name: "Path.exists", type: "function"}),
  (path_mkdir:Function {name: "Path.mkdir", type: "function"}),
  (path_write_text:Function {name: "Path.write_text", type: "function"}),
  (json_loads:Function {name: "json.loads", type: "function"}),
  (json_dumps:Function {name: "json.dumps", type: "function"}),
  (regex_search:Function {name: "re.search", type: "function"}),
  (match_group:Function {name: "Match.group", type: "function"}),
  (str_endswith:Function {name: "str.endswith", type: "function"}),
  (mapping_get:Function {name: "mapping.get", type: "function"}),
  (list_append:Function {name: "list.append", type: "function"}),
  (list_extend:Function {name: "list.extend", type: "function"}),
  (all_fn:Function {name: "all", type: "function"}),
  (any_fn:Function {name: "any", type: "function"}),
  (sum_fn:Function {name: "sum", type: "function"}),
  (len_fn:Function {name: "len", type: "function"}),
  (print_fn:Function {name: "print", type: "function"}),
  (system_exit:Function {name: "SystemExit", type: "function"}),
  (file)-[:CONTAINS]->(main),
  (file)-[:CONTAINS]->(run_case),
  (file)-[:CONTAINS]->(root),
  (file)-[:CONTAINS]->(tests_dir),
  (file)-[:CONTAINS]->(cases_dir),
  (file)-[:CONTAINS]->(manifest),
  (root)-[:USES]->(tests_dir),
  (cases_dir)-[:USES]->(tests_dir),
  (manifest)-[:USES]->(tests_dir),
  (file)-[:CALLS]->(path_ctor),
  (file)-[:CALLS]->(path_resolve),
  (main)-[:CALLS]->(run_case),
  (main)-[:CALLS]->(path_read_text),
  (main)-[:CALLS]->(json_loads),
  (main)-[:CALLS]->(any_fn),
  (main)-[:CALLS]->(sum_fn),
  (main)-[:CALLS]->(len_fn),
  (main)-[:CALLS]->(print_fn),
  (run_case)-[:CALLS]->(path_read_text),
  (run_case)-[:CALLS]->(path_exists),
  (run_case)-[:CALLS]->(path_mkdir),
  (run_case)-[:CALLS]->(path_write_text),
  (run_case)-[:CALLS]->(json_dumps),
  (run_case)-[:CALLS]->(regex_search),
  (run_case)-[:CALLS]->(match_group),
  (run_case)-[:CALLS]->(str_endswith),
  (run_case)-[:CALLS]->(mapping_get),
  (run_case)-[:CALLS]->(len_fn),
  (run_case)-[:CALLS]->(list_append),
  (run_case)-[:CALLS]->(list_extend),
  (run_case)-[:CALLS]->(all_fn),
  (main)-[:USES]->(root),
  (main)-[:USES]->(tests_dir),
  (main)-[:USES]->(cases_dir),
  (main)-[:USES]->(manifest),
  (main)-[:USES]->(specs),
  (main)-[:USES]->(results),
  (main)-[:USES]->(passed),
  (run_case)-[:USES]->(root),
  (run_case)-[:USES]->(spec),
  (run_case)-[:USES]->(check),
  (run_case)-[:USES]->(source_path),
  (run_case)-[:USES]->(source),
  (run_case)-[:USES]->(missing),
  (run_case)-[:USES]->(match),
  (run_case)-[:USES]->(value),
  (run_case)-[:USES]->(cases_dir),
  (run_case)-[:USES]->(check_results),
  (run_case)-[:USES]->(case_dir),
  (run_case)-[:USES]->(evidence_dir),
  (run_case)-[:USES]->(result),
  (run_case)-[:USES]->(lines),
  (run_case)-[:USES]->(passed),
  (file)-[:CALLS]->(main),
  (file)-[:CALLS]->(system_exit);
"""

import json
import re
from pathlib import Path

import agent_plugin
import install_layout

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parents[2]
CASES_DIR = TESTS_DIR / "cases"
MANIFEST = TESTS_DIR / "cases.json"


def run_case(spec: dict) -> dict:
    check_results = []
    for check in spec["checks"]:
        if check.get("kind") in ("install_layout", "agent_plugin"):
            module = install_layout if check["kind"] == "install_layout" else agent_plugin
            try:
                check_results.extend(module.check(ROOT))
            except Exception as error:  # noqa: BLE001 - a crash is a red row, not an aborted run without evidence
                check_results.append({"file": f"{check['kind']}: the check could not run", "passed": False,
                                      "missing": [f"{type(error).__name__}: {error}"]})
            continue
        source_path = ROOT / check["file"]
        source = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
        missing = [snippet for snippet in check["contains"] if snippet not in source]
        if "pattern" in check:
            match = re.search(check["pattern"], source, re.MULTILINE)
            if not match:
                missing.append(f"pattern not found: {check['pattern']}")
            else:
                value = match.group(1)
                minimum, maximum = check["length"]
                if not minimum <= len(value) <= maximum:
                    missing.append(f"value length {len(value)} outside {minimum}..{maximum}")
                if check.get("ends_with") and not value.endswith(check["ends_with"]):
                    missing.append(f"value does not end with {check['ends_with']!r}")
        check_results.append({"file": check["file"], "passed": not missing, "missing": missing})

    case_dir = CASES_DIR / spec["id"]
    evidence_dir = case_dir / "evidence"
    case_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    passed = all(result["passed"] for result in check_results)
    result = {
        "case": spec["id"],
        "skill": spec["skill"],
        "feature": spec["feature"],
        "passed": passed,
        "scope": "source-contract; AI host runtime is not invoked",
        "checks": check_results,
    }
    (evidence_dir / "input.json").write_text(json.dumps(spec["test_object"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (evidence_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {spec['id']}", "", f"- Skill: `{spec['skill']}`", f"- Feature: {spec['feature']}", f"- Result: **{'PASS' if passed else 'FAIL'}**", "", "## Expected behavior", ""]
    lines.extend(f"- {item}" for item in spec["expected"])
    lines.extend(["", "## Contract checks", ""])
    lines.extend(f"- {'PASS' if check['passed'] else 'FAIL'} `{check['file']}`" + (f" — missing: {', '.join(check['missing'])}" if check["missing"] else "") for check in check_results)
    lines.extend(["", "Evidence scope: source-contract check; no AI host CLI is invoked.", ""])
    (evidence_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> int:
    specs = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = [run_case(spec) for spec in specs]
    for result in results:
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['case']}")
    passed = sum(1 for result in results if result["passed"])
    print(f"{passed}/{len(results)} source-contract cases passed")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
