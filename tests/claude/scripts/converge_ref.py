# ```cypher
# CREATE
#   (file:File {name: "converge_ref.py", type: "file", language: "python"}),
#   (v_HARNESS_ROOTS:Variable {name: "HARNESS_ROOTS", type: "variable"}),
#   (v_PROJECT_HARNESS_ROOT:Variable {name: "PROJECT_HARNESS_ROOT", type: "variable"}),
#   (v_PROGRESS_FILES:Variable {name: "PROGRESS_FILES", type: "variable"}),
#   (v_HEAD_NAME_FILES:Variable {name: "HEAD_NAME_FILES", type: "variable"}),
#   (v_MERGE_STATUSES:Variable {name: "MERGE_STATUSES", type: "variable"}),
#   (v_COMMIT_LIST_LIMIT:Variable {name: "COMMIT_LIST_LIMIT", type: "variable"}),
#   (f_in_progress:Function {name: "in_progress", type: "function", signature: "in_progress(worktree: Path | str) -> dict"}),
#   (f_hidden_edits:Function {name: "hidden_edits", type: "function", signature: "hidden_edits(worktree: Path | str) -> list[str]"}),
#   (f_is_clean:Function {name: "is_clean", type: "function", signature: "is_clean(worktree: Path | str) -> bool"}),
#   (f_path_lines:Function {name: "path_lines", type: "function", signature: "path_lines(cwd: Path | str, *args: str) -> list[str]"}),
#   (f_ignored_files:Function {name: "ignored_files", type: "function", signature: "ignored_files(worktree: Path | str) -> list[str]"}),
#   (f_case_collisions:Function {name: "case_collisions", type: "function", signature: "case_collisions(names) -> set[str]"}),
#   (f_has_submodules:Function {name: "has_submodules", type: "function", signature: "has_submodules(worktree: Path | str) -> bool"}),
#   (f_harness_owned:Function {name: "harness_owned", type: "function", signature: "harness_owned(path: str, roots: tuple[str, ...]) -> bool"}),
#   (f_inventory:Function {name: "inventory", type: "function", signature: "inventory(invoking: Path | str, roots: tuple[str, ...]) -> list[dict]"}),
#   (f_checked_out:Function {name: "checked_out", type: "function", signature: "checked_out(items: list[dict]) -> tuple[dict, set]"}),
#   (f_worktree_blockers:Function {name: "worktree_blockers", type: "function", signature: "worktree_blockers(item: dict | None, discard_ignored: bool) -> list[str]"}),
#   (f_unique_commits:Function {name: "unique_commits", type: "function", signature: "unique_commits(repo: Path | str, target: str, sha: str) -> tuple[int, list[str], int]"}),
#   (f_predict_conflict:Function {name: "predict_conflict", type: "function", signature: "predict_conflict(repo: Path | str, target: str, sha: str) -> bool | None"}),
#   (f_local_upstreams:Function {name: "local_upstreams", type: "function", signature: "local_upstreams(repo: Path | str) -> dict[str, str]"}),
#   (f_classify:Function {name: "classify", type: "function", signature: "classify(repo: Path | str, target: str, name: str, sha: str, ctx: dict) -> dict"}),
#   (f_mark_dependencies:Function {name: "mark_dependencies", type: "function", signature: "mark_dependencies(entries: list[dict], target: str, tracking: dict[str, str]) -> None"}),
#   (f_mark_dependencies_remains:Function {name: "mark_dependencies.remains", type: "function", signature: "remains(entry: dict) -> bool"}),
#   (f_traced:Function {name: "traced", type: "function", signature: "traced(function)"}),
#   (f_traced_wrapper:Function {name: "traced.wrapper", type: "function", signature: "wrapper(*args, **kwargs)"}),
#   (f_survey:Function {name: "survey", type: "function", signature: "survey(invoking: Path | str, target: str, discard_ignored: bool=False, harness_roots: tuple[str, ...]=HARNESS_ROOTS) -> dict"}),
#   (f_survey_lambda_290_25:Function {name: "survey.lambda_290_25", type: "function", signature: "lambda_290_25(entry)"}),
#   (f_survey_gate:Function {name: "survey.gate", type: "function", signature: "gate(code: str, message: str) -> None"}),
#   (f_stop:Function {name: "stop", type: "function", signature: "stop(report: dict, code: str, message: str) -> dict"}),
#   (f_ignored_overlap:Function {name: "ignored_overlap", type: "function", signature: "ignored_overlap(repo: Path | str, changed: set[str]) -> list[str]"}),
#   (f_ignored_overlap_lambda_323_58:Function {name: "ignored_overlap.lambda_323_58", type: "function", signature: "lambda_323_58(value)"}),
#   (f_ignored_overlap_lambda_323_12:Function {name: "ignored_overlap.lambda_323_12", type: "function", signature: "lambda_323_12(value)"}),
#   (f_target_moved_only_by_plan:Function {name: "target_moved_only_by_plan", type: "function", signature: "target_moved_only_by_plan(repo: Path | str, old: str, new: str, recorded: set[str]) -> bool"}),
#   (f_delete_branch:Function {name: "delete_branch", type: "function", signature: "delete_branch(repo: Path | str, name: str, sha: str, target: str, ctx: dict, report: dict) -> None"}),
#   (f_delete_branch_skip:Function {name: "delete_branch.skip", type: "function", signature: "skip(reason: str) -> None"}),
#   (f_apply:Function {name: "apply", type: "function", signature: "apply(invoking: Path | str, target: str, discard_ignored: bool=False, earlier_preview: dict | None=None, validate: Callable[[Path], tuple[bool, str]] | None=None, hook: Callable[[str, str], None] | None=None, harness_roots: tuple[str, ...]=HARNESS_ROOTS) -> dict"}),
#   (f_apply_call_hook:Function {name: "apply.call_hook", type: "function", signature: "call_hook(event: str, name: str) -> None"}),
#   (file)-[:CONTAINS]->(v_HARNESS_ROOTS),
#   (file)-[:CONTAINS]->(v_PROJECT_HARNESS_ROOT),
#   (file)-[:CONTAINS]->(v_PROGRESS_FILES),
#   (file)-[:CONTAINS]->(v_HEAD_NAME_FILES),
#   (file)-[:CONTAINS]->(v_MERGE_STATUSES),
#   (file)-[:CONTAINS]->(v_COMMIT_LIST_LIMIT),
#   (file)-[:CONTAINS]->(f_in_progress),
#   (file)-[:CONTAINS]->(f_hidden_edits),
#   (file)-[:CONTAINS]->(f_is_clean),
#   (file)-[:CONTAINS]->(f_path_lines),
#   (file)-[:CONTAINS]->(f_ignored_files),
#   (file)-[:CONTAINS]->(f_case_collisions),
#   (file)-[:CONTAINS]->(f_has_submodules),
#   (file)-[:CONTAINS]->(f_harness_owned),
#   (file)-[:CONTAINS]->(f_inventory),
#   (file)-[:CONTAINS]->(f_checked_out),
#   (file)-[:CONTAINS]->(f_worktree_blockers),
#   (file)-[:CONTAINS]->(f_unique_commits),
#   (file)-[:CONTAINS]->(f_predict_conflict),
#   (file)-[:CONTAINS]->(f_local_upstreams),
#   (file)-[:CONTAINS]->(f_classify),
#   (file)-[:CONTAINS]->(f_mark_dependencies),
#   (f_mark_dependencies)-[:CONTAINS]->(f_mark_dependencies_remains),
#   (file)-[:CONTAINS]->(f_traced),
#   (f_traced)-[:CONTAINS]->(f_traced_wrapper),
#   (file)-[:CONTAINS]->(f_survey),
#   (f_survey)-[:CONTAINS]->(f_survey_lambda_290_25),
#   (f_survey)-[:CONTAINS]->(f_survey_gate),
#   (file)-[:CONTAINS]->(f_stop),
#   (file)-[:CONTAINS]->(f_ignored_overlap),
#   (f_ignored_overlap)-[:CONTAINS]->(f_ignored_overlap_lambda_323_58),
#   (f_ignored_overlap)-[:CONTAINS]->(f_ignored_overlap_lambda_323_12),
#   (file)-[:CONTAINS]->(f_target_moved_only_by_plan),
#   (file)-[:CONTAINS]->(f_delete_branch),
#   (f_delete_branch)-[:CONTAINS]->(f_delete_branch_skip),
#   (file)-[:CONTAINS]->(f_apply),
#   (f_apply)-[:CONTAINS]->(f_apply_call_hook),
#   (f_apply)-[:CALLS]->(f_apply_call_hook),
#   (f_apply)-[:CALLS]->(f_delete_branch),
#   (f_apply)-[:CALLS]->(f_ignored_overlap),
#   (f_apply)-[:CALLS]->(f_path_lines),
#   (f_apply)-[:CALLS]->(f_stop),
#   (f_apply)-[:CALLS]->(f_survey),
#   (f_apply)-[:CALLS]->(f_target_moved_only_by_plan),
#   (f_classify)-[:CALLS]->(f_predict_conflict),
#   (f_classify)-[:CALLS]->(f_unique_commits),
#   (f_classify)-[:CALLS]->(f_worktree_blockers),
#   (f_classify)-[:USES]->(v_MERGE_STATUSES),
#   (f_delete_branch)-[:CALLS]->(f_checked_out),
#   (f_delete_branch)-[:CALLS]->(f_delete_branch_skip),
#   (f_delete_branch)-[:CALLS]->(f_inventory),
#   (f_delete_branch)-[:CALLS]->(f_worktree_blockers),
#   (f_ignored_files)-[:CALLS]->(f_path_lines),
#   (f_ignored_overlap)-[:CALLS]->(f_ignored_files),
#   (f_in_progress)-[:USES]->(v_HEAD_NAME_FILES),
#   (f_in_progress)-[:USES]->(v_PROGRESS_FILES),
#   (f_inventory)-[:CALLS]->(f_harness_owned),
#   (f_inventory)-[:CALLS]->(f_has_submodules),
#   (f_inventory)-[:CALLS]->(f_ignored_files),
#   (f_inventory)-[:CALLS]->(f_in_progress),
#   (f_inventory)-[:CALLS]->(f_is_clean),
#   (f_inventory)-[:USES]->(v_PROJECT_HARNESS_ROOT),
#   (f_is_clean)-[:CALLS]->(f_hidden_edits),
#   (f_mark_dependencies)-[:CALLS]->(f_mark_dependencies_remains),
#   (f_mark_dependencies_remains)-[:USES]->(v_MERGE_STATUSES),
#   (f_survey)-[:CALLS]->(f_case_collisions),
#   (f_survey)-[:CALLS]->(f_checked_out),
#   (f_survey)-[:CALLS]->(f_classify),
#   (f_survey)-[:CALLS]->(f_inventory),
#   (f_survey)-[:CALLS]->(f_local_upstreams),
#   (f_survey)-[:CALLS]->(f_mark_dependencies),
#   (f_survey)-[:CALLS]->(f_survey_gate),
#   (f_survey)-[:USES]->(v_MERGE_STATUSES),
#   (f_unique_commits)-[:USES]->(v_COMMIT_LIST_LIMIT);
# ```
"""Reference executor for the GitConverge contract (references/commands.md, section 6).

`survey()` is the read-only preview; `apply()` performs the merges and deletions. It follows the contract step by
step so the scenario oracles can be proven against real Git before an AI host is asked to do the same work.
Nothing here is shipped to users; it only runs against disposable fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import gitlab
from gitlab import git, out

HARNESS_ROOTS = ("~/.codex/worktrees",)
PROJECT_HARNESS_ROOT = (".claude", "worktrees")
PROGRESS_FILES = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "sequencer", "rebase-merge", "rebase-apply",
                  "BISECT_LOG")
HEAD_NAME_FILES = ("rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START")
MERGE_STATUSES = ("MERGE", "CONTAINED")
COMMIT_LIST_LIMIT = 20


def in_progress(worktree: Path | str) -> dict:
    """Operations underway in a worktree and the branch names they are working on (one rev-parse call)."""
    located = gitlab.git_paths(worktree, PROGRESS_FILES + HEAD_NAME_FILES)
    kinds = [name for name in PROGRESS_FILES if located[name].exists()]
    branches = []
    for name in HEAD_NAME_FILES:
        if located[name].is_file():
            value = located[name].read_text(encoding="utf-8").strip()
            if value:
                branches.append(value.removeprefix("refs/heads/"))
    return {"active": bool(kinds), "kinds": kinds, "branches": branches}


def hidden_edits(worktree: Path | str) -> list[str]:
    """Skip-worktree (S) and assume-unchanged (lowercase tag) entries present on disk: status cannot see their edits."""
    found = []
    for line in out(worktree, "ls-files", "-v").splitlines():
        tag, _, name = line.partition(" ")
        if (tag == "S" or tag.islower()) and (Path(worktree) / name).exists():
            found.append(name)
    return found


def is_clean(worktree: Path | str) -> bool:
    """Empty status with untracked files forced visible, and no flagged index entries that hide edits."""
    return out(worktree, "status", "--porcelain=v1", "--untracked-files=all") == "" and not hidden_edits(worktree)


def path_lines(cwd: Path | str, *args: str) -> list[str]:
    """A path listing with non-ASCII names printed as-is (`core.quotePath=false`); a name Git must still quote keeps
    its surrounding double quotes. The output is not stripped: a name may begin or end with a space."""
    return git(cwd, "-c", "core.quotePath=false", *args, check=True).stdout.splitlines()


def ignored_files(worktree: Path | str) -> list[str]:
    """Ignored entries (a trailing '/' marks a whole ignored directory) that `git worktree remove` deletes silently."""
    return path_lines(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory")


def case_collisions(names) -> set[str]:
    """Local branch names that equal another local branch name when case is ignored."""
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(name.lower(), []).append(name)
    return {name for group in groups.values() if len(group) > 1 for name in group}


def has_submodules(worktree: Path | str) -> bool:
    """True when at least one submodule is initialized (`git worktree remove` refuses those)."""
    status = git(worktree, "submodule", "status").stdout.splitlines()
    return any(line and line[0] != "-" for line in status)


def harness_owned(path: str, roots: tuple[str, ...]) -> bool:
    """True when the worktree lies under an agent-harness worktree root."""
    target = os.path.normcase(os.path.realpath(path))
    for root in roots:
        base = os.path.normcase(os.path.realpath(os.path.expanduser(root)))
        if target == base or target.startswith(base + os.sep):
            return True
    return False


def inventory(invoking: Path | str, roots: tuple[str, ...]) -> list[dict]:
    """Every worktree with the facts the contract needs: ownership, cleanliness, progress, ignored files."""
    top = out(invoking, "rev-parse", "--show-toplevel")
    items = gitlab.worktrees(invoking)
    roots = (*roots, str(Path(items[0]["path"]).joinpath(*PROJECT_HARNESS_ROOT)))
    for index, item in enumerate(items):
        item["main_worktree"] = index == 0
        item["invoking"] = gitlab.same_path(item["path"], top)
        item["exists"] = Path(item["path"]).is_dir()
        item["harness"] = harness_owned(item["path"], roots)
        if item["exists"]:
            item["progress"] = in_progress(item["path"])
            item["dirty"] = not is_clean(item["path"])
            item["ignored"] = ignored_files(item["path"])
            item["submodules"] = has_submodules(item["path"])
        else:
            item.update({"progress": {"active": False, "kinds": [], "branches": []}, "dirty": False, "ignored": [],
                         "submodules": False})
    return items


def checked_out(items: list[dict]) -> tuple[dict, set]:
    """Branch name -> worktree that holds it (a rebase or bisect counts), plus the branches that are mid-operation."""
    holder, busy = {}, set()
    for item in items:
        if item["branch"]:
            holder[item["branch"]] = item
        for name in item["progress"]["branches"]:
            holder.setdefault(name, item)
            busy.add(name)
        if item["progress"]["active"] and item["branch"]:
            busy.add(item["branch"])
    return holder, busy


def worktree_blockers(item: dict | None, discard_ignored: bool) -> list[str]:
    """Delete blockers that come from the worktree holding a branch (one ladder for preview and recheck)."""
    if item is None:
        return []
    if item["main_worktree"] or item["invoking"]:
        return ["BLOCKED_ACTIVE_OWNER"]
    found = []
    if item["locked"]:
        found.append("BLOCKED_LOCKED")
    if item["harness"]:
        found.append("BLOCKED_ACTIVE_OWNER")
    if item["dirty"]:
        found.append("BLOCKED_DIRTY")
    if item["submodules"]:
        found.append("BLOCKED_SUBMODULE")
    if item["ignored"] and not discard_ignored:
        found.append("BLOCKED_IGNORED_FILES")
    return found


def unique_commits(repo: Path | str, target: str, sha: str) -> tuple[int, list[str], int]:
    """Exact unique-commit count, a bounded oneline list, and how many commits the list omits."""
    span = f"refs/heads/{target}..{sha}"
    count = int(out(repo, "rev-list", "--count", span))
    lines = out(repo, "log", "--oneline", "--no-decorate", f"--max-count={COMMIT_LIST_LIMIT}", span).splitlines()
    return count, lines, max(0, count - len(lines))


def predict_conflict(repo: Path | str, target: str, sha: str) -> bool | None:
    """Best-effort conflict prediction; None when this Git has no `merge-tree --write-tree`."""
    proc = git(repo, "merge-tree", "--write-tree", "--no-messages", f"refs/heads/{target}", sha)
    return {0: False, 1: True}.get(proc.returncode)


def local_upstreams(repo: Path | str) -> dict[str, str]:
    """Branch -> the local branch it tracks (branch.<x>.remote is '.'), read in one for-each-ref call."""
    tracking = {}
    for line in out(repo, "for-each-ref", "--format=%(refname:lstrip=2)|%(upstream)", "refs/heads").splitlines():
        name, _, upstream = line.partition("|")
        if upstream.startswith("refs/heads/"):
            tracking[name] = upstream.removeprefix("refs/heads/")
    return tracking


def classify(repo: Path | str, target: str, name: str, sha: str, ctx: dict) -> dict:
    """Merge status (first match of UNRELATED, IN_PROGRESS, CONTAINED, MERGE) plus worktree delete blockers."""
    entry = {"name": name, "sha": sha, "status": "MERGE", "blockers": [], "worktree": None, "unique": 0, "commits": [],
             "more": 0, "predicted_conflict": None, "delete": False}
    holder = ctx["holder"].get(name)
    if holder is not None and not holder["invoking"]:
        entry["worktree"] = holder["path"]
    if name in ctx["collisions"]:
        entry["status"] = "UNKNOWN"
        return entry
    base = git(repo, "merge-base", f"refs/heads/{target}", sha)
    if base.returncode == 1:
        entry["status"] = "BLOCKED_UNRELATED_HISTORY"
    elif name in ctx["busy"]:
        entry["status"] = "BLOCKED_IN_PROGRESS"
    elif base.stdout.strip() == sha:
        entry["status"] = "CONTAINED"
    else:
        entry["unique"], entry["commits"], entry["more"] = unique_commits(repo, target, sha)
        entry["predicted_conflict"] = predict_conflict(repo, target, sha)
    if entry["status"] in MERGE_STATUSES:
        entry["blockers"] = worktree_blockers(holder if entry["worktree"] else None, ctx["discard_ignored"])
    return entry


def mark_dependencies(entries: list[dict], target: str, tracking: dict[str, str]) -> None:
    """Add BLOCKED_UPSTREAM_OF_KEPT to every source a remaining branch tracks, repeated until nothing changes."""
    def remains(entry: dict) -> bool:
        return entry["status"] not in MERGE_STATUSES or bool(entry["blockers"])

    by_name = {entry["name"]: entry for entry in entries}
    remaining = {"main", target} | {entry["name"] for entry in entries if remains(entry)}
    changed = True
    while changed:
        changed = False
        for keeper in sorted(remaining):
            tracked = by_name.get(tracking.get(keeper, ""))
            if tracked and tracked["name"] not in remaining:
                tracked["blockers"].append("BLOCKED_UPSTREAM_OF_KEPT")
                remaining.add(tracked["name"])
                changed = True


def traced(function):
    """Record every git command the wrapped call makes (outermost call owns the trace)."""
    def wrapper(*args, **kwargs):
        owner = gitlab.TRACE is None
        if owner:
            gitlab.TRACE = []
        try:
            result = function(*args, **kwargs)
        finally:
            trace = gitlab.TRACE
            if owner:
                gitlab.TRACE = None
        if owner and isinstance(result, dict):
            result["commands"] = trace
        return result
    wrapper.__name__, wrapper.__doc__ = function.__name__, function.__doc__
    return wrapper


@traced
def survey(invoking: Path | str, target: str, discard_ignored: bool = False,
           harness_roots: tuple[str, ...] = HARNESS_ROOTS) -> dict:
    """The preview: gates, ordered plan, classifications, expected final state. Changes nothing."""
    repo = Path(invoking)
    heads = gitlab.refs(repo)
    plan = {"target": target, "tips": dict(heads), "gates": [], "sources": [], "merge_order": [], "final_branches": [],
            "removals": [], "unknown_owner_removals": [], "residual": [], "notes": {}}

    def gate(code: str, message: str) -> None:
        plan["gates"].append({"code": code, "message": message})

    if target not in heads:
        near = [name for name in heads if name.lower() == target.lower()]
        gate("TARGET_CASE_MISMATCH" if near else "TARGET_MISSING",
             f"did you mean '{near[0]}'? branch names match exactly" if near else f"local branch '{target}' does not exist")
    elif target == "main":
        gate("TARGET_IS_MAIN", "GitConverge never moves main; use GitIntegrate to change main")
    if "main" not in heads:
        gate("MAIN_MISSING", "local branch 'main' does not exist")
    collisions = case_collisions(heads)
    clashing = [name for name in (target, "main") if name in collisions]
    if clashing:
        gate("NAME_CASE_COLLISION", f"{', '.join(clashing)}: equal to another local branch name when case is ignored; "
                                    "make the names distinct first (git pack-refs --all, then git branch -m)")
    if plan["gates"]:
        return plan

    items = inventory(repo, harness_roots)
    holder, busy = checked_out(items)
    me = next(item for item in items if item["invoking"])
    plan["invoking"] = {"path": me["path"], "branch": me["branch"]}
    if me["detached"]:
        gate("INVOKING_DETACHED", "the invoking worktree is detached; commits there could become unreachable")
    if me["dirty"]:
        gate("INVOKING_DIRTY", "the invoking worktree has uncommitted, untracked, or hidden (skip-worktree) changes")
    if me["progress"]["active"]:
        gate("INVOKING_IN_PROGRESS", f"the invoking worktree has an operation in progress: {me['progress']['kinds']}")
    for name in (target, "main"):
        entry = holder.get(name)
        if entry and entry["prunable"] and not entry["exists"]:
            gate("TARGET_PRUNABLE_ENTRY" if name == target else "MAIN_PRUNABLE_ENTRY",
                 f"{name} is held only by a prunable worktree entry at {entry['path']}")
    if holder.get(target) and not holder[target]["invoking"] and not holder[target]["prunable"]:
        gate("TARGET_ELSEWHERE", f"{target} is checked out in {holder[target]['path']}; run the command from there")
    if target in busy:
        gate("TARGET_IN_PROGRESS", f"{target} has an operation in progress")
    if plan["gates"]:
        return plan

    ctx = {"holder": holder, "busy": busy, "discard_ignored": discard_ignored, "collisions": collisions}
    sources = [classify(repo, target, name, sha, ctx) for name, sha in sorted(heads.items())
               if name not in (target, "main")]
    mark_dependencies(sources, target, local_upstreams(repo))
    for entry in sources:
        entry["delete"] = entry["status"] in MERGE_STATUSES and not entry["blockers"]
    main_entry = classify(repo, target, "main", heads["main"], {**ctx, "discard_ignored": True})
    main_entry.update({"kept": True, "delete": False, "blockers": []})
    plan["sources"] = [main_entry, *sources]
    merging = sorted((entry for entry in sources if entry["status"] == "MERGE"),
                     key=lambda entry: (-entry["unique"], entry["name"]))
    plan["merge_order"] = [entry["name"] for entry in ([main_entry] if main_entry["status"] == "MERGE" else []) + merging]
    removable = [entry for entry in sources if entry["delete"] and entry["worktree"]]
    plan["removals"] = [entry["worktree"] for entry in removable]
    plan["unknown_owner_removals"] = [entry["worktree"] for entry in removable]  # fixtures carry no lane records
    residual = [entry for entry in sources if not entry["delete"]]
    plan["residual"] = [{"name": entry["name"], "reason": entry["status"] if entry["status"] not in MERGE_STATUSES
                         else entry["blockers"]} for entry in residual]
    plan["final_branches"] = sorted({"main", target} | {entry["name"] for entry in residual})
    tags = set(out(repo, "tag", "--list").splitlines())
    origin_main = git(repo, "rev-parse", "--verify", "-q", "refs/remotes/origin/main").stdout.strip()
    plan["notes"] = {
        "tag_collisions": sorted(tags & set(heads)),
        "main_vs_origin": out(repo, "rev-list", "--left-right", "--count", "refs/heads/main...refs/remotes/origin/main")
        if origin_main else None,
        "remote_branches": out(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").splitlines(),
        "detached_worktrees": [item["path"] for item in items if item["detached"] and not item["progress"]["active"]],
        "validation": "not identifiable"}
    return plan


def stop(report: dict, code: str, message: str) -> dict:
    """Record why the command stopped; callers return the report right away."""
    report["stopped"] = {"code": code, "message": message}
    return report


def ignored_overlap(repo: Path | str, changed: set[str]) -> list[str]:
    """Changed paths that equal, contain, or lie under an ignored entry (case-folded when core.ignorecase is true).

    A name Git still quotes (a quote, backslash, or control character in it) cannot be compared safely, so when the
    worktree has ignored entries, any such name on either side makes every changed path count as overlapping."""
    fold = git(repo, "config", "--get", "--bool", "core.ignorecase").stdout.strip() == "true"
    norm = (lambda value: value.casefold()) if fold else (lambda value: value)
    listed = ignored_files(repo)
    if changed and listed and any(name.startswith('"') for name in [*listed, *changed]):
        return sorted(changed)
    ignored = [norm(entry.rstrip("/")) for entry in listed]
    hits = []
    for path in changed:
        candidate = norm(path)
        if any(candidate == entry or candidate.startswith(entry + "/") or entry.startswith(candidate + "/")
               for entry in ignored):
            hits.append(path)
    return sorted(hits)


def target_moved_only_by_plan(repo: Path | str, old: str, new: str, recorded: set[str]) -> bool:
    """True when every first-parent commit in old..new is a merge whose second parent is a recorded source tip."""
    if not gitlab.is_ancestor(repo, old, new):
        return False
    for line in out(repo, "rev-list", "--first-parent", "--parents", f"{old}..{new}").splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[2] not in recorded:
            return False
    return True


def delete_branch(repo: Path | str, name: str, sha: str, target: str, ctx: dict, report: dict) -> None:
    """Recheck, remove the worktree if any, unset a lagging upstream, then `branch -d`. Never -D or --force."""
    def skip(reason: str) -> None:
        report["skipped"].append({"branch": name, "reason": reason})

    if gitlab.refs(repo).get(name) != sha:
        return skip("tip moved since the plan")
    if not gitlab.is_ancestor(repo, sha, f"refs/heads/{target}"):
        return skip("tip is not contained in the target")
    holder, busy = checked_out(inventory(repo, ctx["harness_roots"]))
    if name in busy:
        return skip("BLOCKED_IN_PROGRESS")
    entry = holder.get(name)
    blockers = worktree_blockers(entry, ctx["discard_ignored"])
    if blockers:
        return skip(blockers[0])
    if entry:
        removal = git(repo, "worktree", "remove", entry["path"])
        if removal.returncode:
            still = any(gitlab.same_path(item["path"], entry["path"]) for item in gitlab.worktrees(repo))
            return skip(f"worktree remove failed rc={removal.returncode}; entry still listed={still}; "
                        f"{removal.stderr.strip()[:120]}")
        report["ops"].append(f"worktree remove {entry['path']}")
    saved = None
    full, _, short = out(repo, "for-each-ref", "--format=%(upstream)|%(upstream:short)", f"refs/heads/{name}").partition("|")
    upstream_exists = bool(full) and git(repo, "rev-parse", "--verify", "-q", full).returncode == 0
    if upstream_exists and not gitlab.is_ancestor(repo, sha, full):
        saved = short
        git(repo, "branch", "--unset-upstream", name)
        report["ops"].append(f"unset-upstream {name} (was {saved})")
    deletion = git(repo, "branch", "-d", name)
    if deletion.returncode:
        if saved:
            git(repo, "branch", f"--set-upstream-to={saved}", name)
        return skip(f"branch -d failed: {deletion.stderr.strip()[:120]}")
    report["ops"].append(f"delete {name}")
    report["deleted"][name] = sha


@traced
def apply(invoking: Path | str, target: str, discard_ignored: bool = False, earlier_preview: dict | None = None,
          validate: Callable[[Path], tuple[bool, str]] | None = None, hook: Callable[[str, str], None] | None = None,
          harness_roots: tuple[str, ...] = HARNESS_ROOTS) -> dict:
    """Run the contract's apply procedure. `hook(event, name)` lets tests change the repository mid-run."""
    repo = Path(invoking)

    def call_hook(event: str, name: str) -> None:
        if hook:
            with gitlab.untraced():
                hook(event, name)

    plan = survey(repo, target, discard_ignored, harness_roots)
    report = {"plan": plan, "stopped": None, "ops": [], "skipped": [], "deleted": {}, "appeared_after_preview": [],
              "worktree_appeared": [], "start_sha": plan["tips"].get(target), "end_sha": None,
              "validation": "not identifiable", "final_branches": None}
    if plan["gates"]:
        return stop(report, plan["gates"][0]["code"], plan["gates"][0]["message"])
    if earlier_preview:
        earlier = earlier_preview["tips"]
        moved = sorted(name for name, sha in earlier.items()
                       if name != target and name in plan["tips"] and plan["tips"][name] != sha)
        recorded = {sha for name, sha in earlier.items() if name != target}
        if target in earlier and plan["tips"][target] != earlier[target] and \
                not target_moved_only_by_plan(repo, earlier[target], plan["tips"][target], recorded):
            moved.append(target)
        if moved:
            return stop(report, "STALE_PREVIEW", f"tips changed since the preview: {moved}; show a new preview")
        report["appeared_after_preview"] = sorted(set(plan["tips"]) - set(earlier))
        before = {entry["name"]: entry.get("worktree") for entry in earlier_preview.get("sources", [])}
        report["worktree_appeared"] = sorted(
            entry["name"] for entry in plan["sources"] if entry["name"] in before and entry["worktree"]
            and not (before[entry["name"]] and gitlab.same_path(before[entry["name"]], entry["worktree"])))
    untouched = set(report["appeared_after_preview"])
    keep = untouched | set(report["worktree_appeared"])
    ctx = {"harness_roots": harness_roots, "discard_ignored": discard_ignored}
    call_hook("after_plan", "")
    if plan["invoking"]["branch"] != target:
        switched = git(repo, "switch", "--no-overwrite-ignore", target)
        if switched.returncode:
            return stop(report, "SWITCH_REFUSED", switched.stderr.strip())
        report["ops"].append(f"switch {plan['invoking']['branch']} -> {target}")
    by_name = {entry["name"]: entry for entry in plan["sources"]}
    for name in plan["merge_order"]:
        entry = by_name[name]
        if name in untouched:
            continue
        call_hook("before_merge", name)
        if gitlab.refs(repo).get(name) != entry["sha"]:
            report["skipped"].append({"branch": name, "reason": "tip moved since the plan"})
            continue
        if gitlab.is_ancestor(repo, entry["sha"], f"refs/heads/{target}"):
            report["ops"].append(f"skip {name}: contained by an earlier merge")
            continue
        base = out(repo, "merge-base", f"refs/heads/{target}", entry["sha"])
        overlap = ignored_overlap(repo, set(path_lines(repo, "diff", "--name-only", base, entry["sha"])))
        if overlap:
            return stop(report, "BLOCKED_IGNORED_OVERWRITE", f"merging {name} would overwrite ignored files: {overlap}")
        merged = git(repo, "merge", "--no-ff", "-m", f"Merge branch '{name}' into {target}", entry["sha"])
        if merged.returncode:
            if gitlab.git_paths(repo, ("MERGE_HEAD",))["MERGE_HEAD"].exists():
                git(repo, "merge", "--abort")
            return stop(report, "MERGE_FAILED", f"{name}: {(merged.stdout + merged.stderr).strip()[:200]}")
        report["ops"].append(f"merge {name}")
    if validate:
        with gitlab.untraced():
            ok, detail = validate(repo)
        report["validation"] = f"{'passed' if ok else 'failed'}: {detail}"
        if not ok:
            return stop(report, "VALIDATION_FAILED", detail)
    for entry in plan["sources"]:
        if entry.get("kept") or not entry["delete"] or entry["name"] in keep:
            continue
        call_hook("before_delete", entry["name"])
        delete_branch(repo, entry["name"], entry["sha"], target, ctx, report)
    report["end_sha"] = out(repo, "rev-parse", f"refs/heads/{target}")
    report["final_branches"] = sorted(gitlab.refs(repo))
    return report
