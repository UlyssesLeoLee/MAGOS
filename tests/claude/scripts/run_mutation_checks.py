# ```cypher
# CREATE
#   (file:File {name: "run_mutation_checks.py", type: "file", language: "python"}),
#   (v_RESULTS_DIR:Variable {name: "RESULTS_DIR", type: "variable"}),
#   (v_MUTATIONS:Variable {name: "MUTATIONS", type: "variable"}),
#   (f_fake:Function {name: "fake", type: "function", signature: "fake(args: list[str], returncode: int=0, stdout: str='', stderr: str='') -> subprocess.CompletedProcess"}),
#   (f_patch_git:Function {name: "patch_git", type: "function", signature: "patch_git(stack: ExitStack, pre=None, post=None) -> None"}),
#   (f_patch_git_lambda_52_63:Function {name: "patch_git.lambda_52_63", type: "function", signature: "lambda_52_63(cwd, *args)"}),
#   (f_patch_git_wrapper:Function {name: "patch_git.wrapper", type: "function", signature: "wrapper(cwd, *args, check=False)"}),
#   (f_wrap:Function {name: "wrap", type: "function", signature: "wrap(stack: ExitStack, name: str, around) -> None"}),
#   (f_m_global_prune:Function {name: "m_global_prune", type: "function", signature: "m_global_prune(stack)"}),
#   (f_m_global_prune_around:Function {name: "m_global_prune.around", type: "function", signature: "around(original)"}),
#   (f_m_global_prune_around_delete_branch:Function {name: "m_global_prune.around.delete_branch", type: "function", signature: "delete_branch(repo, name, sha, target, ctx, report)"}),
#   (f_m_force_delete:Function {name: "m_force_delete", type: "function", signature: "m_force_delete(stack)"}),
#   (f_m_force_delete_lambda_70_25:Function {name: "m_force_delete.lambda_70_25", type: "function", signature: "lambda_70_25(a)"}),
#   (f_m_force_remove_dirty:Function {name: "m_force_remove_dirty", type: "function", signature: "m_force_remove_dirty(stack)"}),
#   (f_m_force_remove_dirty_lambda_79_25:Function {name: "m_force_remove_dirty.lambda_79_25", type: "function", signature: "lambda_79_25(a)"}),
#   (f_m_force_remove_dirty_around:Function {name: "m_force_remove_dirty.around", type: "function", signature: "around(original)"}),
#   (f_m_force_remove_dirty_around_worktree_blockers:Function {name: "m_force_remove_dirty.around.worktree_blockers", type: "function", signature: "worktree_blockers(item, discard_ignored)"}),
#   (f_m_move_main:Function {name: "m_move_main", type: "function", signature: "m_move_main(stack)"}),
#   (f_m_move_main_around:Function {name: "m_move_main.around", type: "function", signature: "around(original)"}),
#   (f_m_move_main_around_apply:Function {name: "m_move_main.around.apply", type: "function", signature: "apply(invoking, target, *args, **kwargs)"}),
#   (f_m_merge_by_name:Function {name: "m_merge_by_name", type: "function", signature: "m_merge_by_name(stack)"}),
#   (f_m_merge_by_name_pre:Function {name: "m_merge_by_name.pre", type: "function", signature: "pre(args)"}),
#   (f_m_no_abort:Function {name: "m_no_abort", type: "function", signature: "m_no_abort(stack)"}),
#   (f_m_no_abort_lambda_102_25:Function {name: "m_no_abort.lambda_102_25", type: "function", signature: "lambda_102_25(a)"}),
#   (f_m_merge_x_theirs:Function {name: "m_merge_x_theirs", type: "function", signature: "m_merge_x_theirs(stack)"}),
#   (f_m_merge_x_theirs_lambda_106_25:Function {name: "m_merge_x_theirs.lambda_106_25", type: "function", signature: "lambda_106_25(a)"}),
#   (f_m_case_insensitive:Function {name: "m_case_insensitive", type: "function", signature: "m_case_insensitive(stack)"}),
#   (f_m_case_insensitive_around:Function {name: "m_case_insensitive.around", type: "function", signature: "around(original)"}),
#   (f_m_case_insensitive_around_call:Function {name: "m_case_insensitive.around.call", type: "function", signature: "call(invoking, target, *args, **kwargs)"}),
#   (f_m_no_ignored_overlap:Function {name: "m_no_ignored_overlap", type: "function", signature: "m_no_ignored_overlap(stack)"}),
#   (f_m_no_ignored_overlap_lambda_120_75:Function {name: "m_no_ignored_overlap.lambda_120_75", type: "function", signature: "lambda_120_75(repo, changed)"}),
#   (f_m_no_rebase_detection:Function {name: "m_no_rebase_detection", type: "function", signature: "m_no_rebase_detection(stack)"}),
#   (f_m_no_rebase_detection_lambda_125_42:Function {name: "m_no_rebase_detection.lambda_125_42", type: "function", signature: "lambda_125_42(worktree)"}),
#   (f_m_no_unrelated_check:Function {name: "m_no_unrelated_check", type: "function", signature: "m_no_unrelated_check(stack)"}),
#   (f_m_no_unrelated_check_post:Function {name: "m_no_unrelated_check.post", type: "function", signature: "post(args, proc)"}),
#   (f_m_ascending_order:Function {name: "m_ascending_order", type: "function", signature: "m_ascending_order(stack)"}),
#   (f_m_ascending_order_around:Function {name: "m_ascending_order.around", type: "function", signature: "around(original)"}),
#   (f_m_ascending_order_around_survey:Function {name: "m_ascending_order.around.survey", type: "function", signature: "survey(*args, **kwargs)"}),
#   (f_m_delete_without_recheck:Function {name: "m_delete_without_recheck", type: "function", signature: "m_delete_without_recheck(stack)"}),
#   (f_m_delete_without_recheck_around:Function {name: "m_delete_without_recheck.around", type: "function", signature: "around(original)"}),
#   (f_m_delete_without_recheck_around_delete_branch:Function {name: "m_delete_without_recheck.around.delete_branch", type: "function", signature: "delete_branch(repo, name, sha, target, ctx, report)"}),
#   (f_m_ignore_lock_gate:Function {name: "m_ignore_lock_gate", type: "function", signature: "m_ignore_lock_gate(stack)"}),
#   (f_m_ignore_lock_gate_around:Function {name: "m_ignore_lock_gate.around", type: "function", signature: "around(original)"}),
#   (f_m_ignore_lock_gate_around_worktree_blockers:Function {name: "m_ignore_lock_gate.around.worktree_blockers", type: "function", signature: "worktree_blockers(item, discard_ignored)"}),
#   (f_m_delete_main:Function {name: "m_delete_main", type: "function", signature: "m_delete_main(stack)"}),
#   (f_m_delete_main_around:Function {name: "m_delete_main.around", type: "function", signature: "around(original)"}),
#   (f_m_delete_main_around_survey:Function {name: "m_delete_main.around.survey", type: "function", signature: "survey(*args, **kwargs)"}),
#   (f_m_ignore_harness:Function {name: "m_ignore_harness", type: "function", signature: "m_ignore_harness(stack)"}),
#   (f_m_ignore_harness_lambda_178_73:Function {name: "m_ignore_harness.lambda_178_73", type: "function", signature: "lambda_178_73(path, roots)"}),
#   (f_m_no_stale_check:Function {name: "m_no_stale_check", type: "function", signature: "m_no_stale_check(stack)"}),
#   (f_m_no_stale_check_around:Function {name: "m_no_stale_check.around", type: "function", signature: "around(original)"}),
#   (f_m_no_stale_check_around_apply:Function {name: "m_no_stale_check.around.apply", type: "function", signature: "apply(invoking, target, discard_ignored=False, earlier_preview=None, **kwargs)"}),
#   (f_m_no_ignored_files_gate:Function {name: "m_no_ignored_files_gate", type: "function", signature: "m_no_ignored_files_gate(stack)"}),
#   (f_m_no_ignored_files_gate_lambda_190_73:Function {name: "m_no_ignored_files_gate.lambda_190_73", type: "function", signature: "lambda_190_73(worktree)"}),
#   (f_m_no_invoking_clean_gate:Function {name: "m_no_invoking_clean_gate", type: "function", signature: "m_no_invoking_clean_gate(stack)"}),
#   (f_m_no_invoking_clean_gate_lambda_194_68:Function {name: "m_no_invoking_clean_gate.lambda_194_68", type: "function", signature: "lambda_194_68(worktree)"}),
#   (f_m_mask_remove_failure:Function {name: "m_mask_remove_failure", type: "function", signature: "m_mask_remove_failure(stack)"}),
#   (f_m_mask_remove_failure_lambda_198_26:Function {name: "m_mask_remove_failure.lambda_198_26", type: "function", signature: "lambda_198_26(a, p)"}),
#   (f_m_bare_target_name:Function {name: "m_bare_target_name", type: "function", signature: "m_bare_target_name(stack)"}),
#   (f_m_bare_target_name_pre:Function {name: "m_bare_target_name.pre", type: "function", signature: "pre(args)"}),
#   (f_m_no_sequencer:Function {name: "m_no_sequencer", type: "function", signature: "m_no_sequencer(stack)"}),
#   (f_m_no_hidden_edits:Function {name: "m_no_hidden_edits", type: "function", signature: "m_no_hidden_edits(stack)"}),
#   (f_m_no_hidden_edits_lambda_214_72:Function {name: "m_no_hidden_edits.lambda_214_72", type: "function", signature: "lambda_214_72(worktree)"}),
#   (f_m_no_project_harness_root:Function {name: "m_no_project_harness_root", type: "function", signature: "m_no_project_harness_root(stack)"}),
#   (f_m_no_dependency_fixpoint:Function {name: "m_no_dependency_fixpoint", type: "function", signature: "m_no_dependency_fixpoint(stack)"}),
#   (f_m_no_dependency_fixpoint_lambda_222_77:Function {name: "m_no_dependency_fixpoint.lambda_222_77", type: "function", signature: "lambda_222_77(entries, target, tracking)"}),
#   (f_m_exact_ignored_overlap:Function {name: "m_exact_ignored_overlap", type: "function", signature: "m_exact_ignored_overlap(stack)"}),
#   (f_m_exact_ignored_overlap_exact:Function {name: "m_exact_ignored_overlap.exact", type: "function", signature: "exact(repo, changed)"}),
#   (f_quoted_lines:Function {name: "quoted_lines", type: "function", signature: "quoted_lines(cwd, *args)"}),
#   (f_m_quoted_paths:Function {name: "m_quoted_paths", type: "function", signature: "m_quoted_paths(stack)"}),
#   (f_m_quoted_paths_unguarded:Function {name: "m_quoted_paths.unguarded", type: "function", signature: "unguarded(repo, changed)"}),
#   (f_m_default_quotepath:Function {name: "m_default_quotepath", type: "function", signature: "m_default_quotepath(stack)"}),
#   (f_m_no_case_collisions:Function {name: "m_no_case_collisions", type: "function", signature: "m_no_case_collisions(stack)"}),
#   (f_m_no_case_collisions_lambda_254_75:Function {name: "m_no_case_collisions.lambda_254_75", type: "function", signature: "lambda_254_75(names)"}),
#   (f_m_target_move_always_stale:Function {name: "m_target_move_always_stale", type: "function", signature: "m_target_move_always_stale(stack)"}),
#   (f_m_target_move_always_stale_lambda_258_85:Function {name: "m_target_move_always_stale.lambda_258_85", type: "function", signature: "lambda_258_85(repo, old, new, recorded)"}),
#   (f_run_mutation:Function {name: "run_mutation", type: "function", signature: "run_mutation(name: str, description: str, install, names: list[str], expect_killed: bool, base: str | None) -> dict"}),
#   (f_main:Function {name: "main", type: "function", signature: "main() -> int"}),
#   (file)-[:CONTAINS]->(v_RESULTS_DIR),
#   (file)-[:CONTAINS]->(v_MUTATIONS),
#   (file)-[:CONTAINS]->(f_fake),
#   (file)-[:CONTAINS]->(f_patch_git),
#   (f_patch_git)-[:CONTAINS]->(f_patch_git_lambda_52_63),
#   (f_patch_git)-[:CONTAINS]->(f_patch_git_wrapper),
#   (file)-[:CONTAINS]->(f_wrap),
#   (file)-[:CONTAINS]->(f_m_global_prune),
#   (f_m_global_prune)-[:CONTAINS]->(f_m_global_prune_around),
#   (f_m_global_prune_around)-[:CONTAINS]->(f_m_global_prune_around_delete_branch),
#   (file)-[:CONTAINS]->(f_m_force_delete),
#   (f_m_force_delete)-[:CONTAINS]->(f_m_force_delete_lambda_70_25),
#   (file)-[:CONTAINS]->(f_m_force_remove_dirty),
#   (f_m_force_remove_dirty)-[:CONTAINS]->(f_m_force_remove_dirty_lambda_79_25),
#   (f_m_force_remove_dirty)-[:CONTAINS]->(f_m_force_remove_dirty_around),
#   (f_m_force_remove_dirty_around)-[:CONTAINS]->(f_m_force_remove_dirty_around_worktree_blockers),
#   (file)-[:CONTAINS]->(f_m_move_main),
#   (f_m_move_main)-[:CONTAINS]->(f_m_move_main_around),
#   (f_m_move_main_around)-[:CONTAINS]->(f_m_move_main_around_apply),
#   (file)-[:CONTAINS]->(f_m_merge_by_name),
#   (f_m_merge_by_name)-[:CONTAINS]->(f_m_merge_by_name_pre),
#   (file)-[:CONTAINS]->(f_m_no_abort),
#   (f_m_no_abort)-[:CONTAINS]->(f_m_no_abort_lambda_102_25),
#   (file)-[:CONTAINS]->(f_m_merge_x_theirs),
#   (f_m_merge_x_theirs)-[:CONTAINS]->(f_m_merge_x_theirs_lambda_106_25),
#   (file)-[:CONTAINS]->(f_m_case_insensitive),
#   (f_m_case_insensitive)-[:CONTAINS]->(f_m_case_insensitive_around),
#   (f_m_case_insensitive_around)-[:CONTAINS]->(f_m_case_insensitive_around_call),
#   (file)-[:CONTAINS]->(f_m_no_ignored_overlap),
#   (f_m_no_ignored_overlap)-[:CONTAINS]->(f_m_no_ignored_overlap_lambda_120_75),
#   (file)-[:CONTAINS]->(f_m_no_rebase_detection),
#   (f_m_no_rebase_detection)-[:CONTAINS]->(f_m_no_rebase_detection_lambda_125_42),
#   (file)-[:CONTAINS]->(f_m_no_unrelated_check),
#   (f_m_no_unrelated_check)-[:CONTAINS]->(f_m_no_unrelated_check_post),
#   (file)-[:CONTAINS]->(f_m_ascending_order),
#   (f_m_ascending_order)-[:CONTAINS]->(f_m_ascending_order_around),
#   (f_m_ascending_order_around)-[:CONTAINS]->(f_m_ascending_order_around_survey),
#   (file)-[:CONTAINS]->(f_m_delete_without_recheck),
#   (f_m_delete_without_recheck)-[:CONTAINS]->(f_m_delete_without_recheck_around),
#   (f_m_delete_without_recheck_around)-[:CONTAINS]->(f_m_delete_without_recheck_around_delete_branch),
#   (file)-[:CONTAINS]->(f_m_ignore_lock_gate),
#   (f_m_ignore_lock_gate)-[:CONTAINS]->(f_m_ignore_lock_gate_around),
#   (f_m_ignore_lock_gate_around)-[:CONTAINS]->(f_m_ignore_lock_gate_around_worktree_blockers),
#   (file)-[:CONTAINS]->(f_m_delete_main),
#   (f_m_delete_main)-[:CONTAINS]->(f_m_delete_main_around),
#   (f_m_delete_main_around)-[:CONTAINS]->(f_m_delete_main_around_survey),
#   (file)-[:CONTAINS]->(f_m_ignore_harness),
#   (f_m_ignore_harness)-[:CONTAINS]->(f_m_ignore_harness_lambda_178_73),
#   (file)-[:CONTAINS]->(f_m_no_stale_check),
#   (f_m_no_stale_check)-[:CONTAINS]->(f_m_no_stale_check_around),
#   (f_m_no_stale_check_around)-[:CONTAINS]->(f_m_no_stale_check_around_apply),
#   (file)-[:CONTAINS]->(f_m_no_ignored_files_gate),
#   (f_m_no_ignored_files_gate)-[:CONTAINS]->(f_m_no_ignored_files_gate_lambda_190_73),
#   (file)-[:CONTAINS]->(f_m_no_invoking_clean_gate),
#   (f_m_no_invoking_clean_gate)-[:CONTAINS]->(f_m_no_invoking_clean_gate_lambda_194_68),
#   (file)-[:CONTAINS]->(f_m_mask_remove_failure),
#   (f_m_mask_remove_failure)-[:CONTAINS]->(f_m_mask_remove_failure_lambda_198_26),
#   (file)-[:CONTAINS]->(f_m_bare_target_name),
#   (f_m_bare_target_name)-[:CONTAINS]->(f_m_bare_target_name_pre),
#   (file)-[:CONTAINS]->(f_m_no_sequencer),
#   (file)-[:CONTAINS]->(f_m_no_hidden_edits),
#   (f_m_no_hidden_edits)-[:CONTAINS]->(f_m_no_hidden_edits_lambda_214_72),
#   (file)-[:CONTAINS]->(f_m_no_project_harness_root),
#   (file)-[:CONTAINS]->(f_m_no_dependency_fixpoint),
#   (f_m_no_dependency_fixpoint)-[:CONTAINS]->(f_m_no_dependency_fixpoint_lambda_222_77),
#   (file)-[:CONTAINS]->(f_m_exact_ignored_overlap),
#   (f_m_exact_ignored_overlap)-[:CONTAINS]->(f_m_exact_ignored_overlap_exact),
#   (file)-[:CONTAINS]->(f_quoted_lines),
#   (file)-[:CONTAINS]->(f_m_quoted_paths),
#   (f_m_quoted_paths)-[:CONTAINS]->(f_m_quoted_paths_unguarded),
#   (file)-[:CONTAINS]->(f_m_default_quotepath),
#   (file)-[:CONTAINS]->(f_m_no_case_collisions),
#   (f_m_no_case_collisions)-[:CONTAINS]->(f_m_no_case_collisions_lambda_254_75),
#   (file)-[:CONTAINS]->(f_m_target_move_always_stale),
#   (f_m_target_move_always_stale)-[:CONTAINS]->(f_m_target_move_always_stale_lambda_258_85),
#   (file)-[:CONTAINS]->(f_run_mutation),
#   (file)-[:CONTAINS]->(f_main),
#   (f_m_ascending_order)-[:CALLS]->(f_wrap),
#   (f_m_bare_target_name)-[:CALLS]->(f_patch_git),
#   (f_m_case_insensitive)-[:CALLS]->(f_wrap),
#   (f_m_delete_main)-[:CALLS]->(f_wrap),
#   (f_m_delete_without_recheck)-[:CALLS]->(f_wrap),
#   (f_m_force_delete)-[:CALLS]->(f_patch_git),
#   (f_m_force_remove_dirty)-[:CALLS]->(f_patch_git),
#   (f_m_force_remove_dirty)-[:CALLS]->(f_wrap),
#   (f_m_global_prune)-[:CALLS]->(f_wrap),
#   (f_m_ignore_lock_gate)-[:CALLS]->(f_wrap),
#   (f_m_mask_remove_failure)-[:CALLS]->(f_patch_git),
#   (f_m_mask_remove_failure_lambda_198_26)-[:CALLS]->(f_fake),
#   (f_m_merge_by_name)-[:CALLS]->(f_patch_git),
#   (f_m_merge_x_theirs)-[:CALLS]->(f_patch_git),
#   (f_m_move_main)-[:CALLS]->(f_wrap),
#   (f_m_no_abort)-[:CALLS]->(f_patch_git),
#   (f_m_no_abort_lambda_102_25)-[:CALLS]->(f_fake),
#   (f_m_no_stale_check)-[:CALLS]->(f_wrap),
#   (f_m_no_unrelated_check)-[:CALLS]->(f_patch_git),
#   (f_m_no_unrelated_check_post)-[:CALLS]->(f_fake),
#   (f_main)-[:CALLS]->(f_run_mutation),
#   (f_main)-[:USES]->(v_MUTATIONS),
#   (f_main)-[:USES]->(v_RESULTS_DIR),
#   (f_patch_git_lambda_52_63)-[:CALLS]->(f_patch_git_wrapper),
#   (file)-[:CALLS]->(f_main);
# ```
"""Mutation checks: break the reference executor on purpose and confirm the scenarios notice.

Each mutation removes or inverts one rule of the GitConverge contract. A mutation is KILLED when at least one of the
named scenarios fails (an oracle or the command-policy check). A mutation that survives means the tests cannot see
that rule; the one expected survivor is a rule that Git itself enforces, so the end state does not change.
Run: python -X utf8 tests/claude/scripts/run_mutation_checks.py [--fixture-root <short path>]
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import converge_ref  # noqa: E402
import gitlab  # noqa: E402
import run_reference_cases  # noqa: E402
import scenarios  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "mutation"


def fake(args: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """A stand-in git result."""
    return subprocess.CompletedProcess(["git", *args], returncode, stdout, stderr)


def patch_git(stack: ExitStack, pre=None, post=None) -> None:
    """Route converge_ref's git/out through a wrapper; pre() may rewrite args or answer, post() may rewrite the result."""
    real = gitlab.git

    def wrapper(cwd, *args, check=False):
        if pre:
            changed = pre(list(args))
            if isinstance(changed, subprocess.CompletedProcess):
                return changed
            if changed is not None:
                args = tuple(changed)
        proc = real(cwd, *args, check=False)
        if post:
            proc = post(list(args), proc) or proc
        if check and proc.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    stack.enter_context(mock.patch.object(converge_ref, "git", wrapper))
    stack.enter_context(mock.patch.object(converge_ref, "out", lambda cwd, *args: wrapper(cwd, *args, check=True).stdout.strip()))


def wrap(stack: ExitStack, name: str, around) -> None:
    """Replace converge_ref.<name> with around(original) while the mutation is active."""
    stack.enter_context(mock.patch.object(converge_ref, name, around(getattr(converge_ref, name))))


def m_global_prune(stack):
    def around(original):
        def delete_branch(repo, name, sha, target, ctx, report):
            original(repo, name, sha, target, ctx, report)
            gitlab.git(repo, "worktree", "prune")
        return delete_branch
    wrap(stack, "delete_branch", around)


def m_force_delete(stack):
    patch_git(stack, pre=lambda a: ["branch", "-D", *a[2:]] if a[:2] == ["branch", "-d"] else None)


def m_force_remove_dirty(stack):
    def around(original):
        def worktree_blockers(item, discard_ignored):
            return [b for b in original(item, discard_ignored) if b not in ("BLOCKED_DIRTY", "BLOCKED_LOCKED")]
        return worktree_blockers
    wrap(stack, "worktree_blockers", around)
    patch_git(stack, pre=lambda a: [*a, "--force"] if a[:2] == ["worktree", "remove"] else None)


def m_move_main(stack):
    def around(original):
        def apply(invoking, target, *args, **kwargs):
            report = original(invoking, target, *args, **kwargs)
            gitlab.git(invoking, "branch", "-f", "main", target)
            return report
        return apply
    wrap(stack, "apply", around)


def m_merge_by_name(stack):
    def pre(args):
        if args[:2] == ["merge", "--no-ff"] and len(args) >= 5:
            label = args[3].split("'")[1]
            return [*args[:-1], label]
        return None
    patch_git(stack, pre=pre)


def m_no_abort(stack):
    patch_git(stack, pre=lambda a: fake(a) if a[:2] == ["merge", "--abort"] else None)


def m_merge_x_theirs(stack):
    patch_git(stack, pre=lambda a: ["merge", "-X", "theirs", *a[1:]] if a[:2] == ["merge", "--no-ff"] else None)


def m_case_insensitive(stack):
    def around(original):
        def call(invoking, target, *args, **kwargs):
            real = {name.lower(): name for name in gitlab.refs(invoking)}
            return original(invoking, real.get(target.lower(), target), *args, **kwargs)
        return call
    wrap(stack, "survey", around)
    wrap(stack, "apply", around)


def m_no_ignored_overlap(stack):
    stack.enter_context(mock.patch.object(converge_ref, "ignored_overlap", lambda repo, changed: []))


def m_no_rebase_detection(stack):
    stack.enter_context(mock.patch.object(converge_ref, "in_progress",
                                          lambda worktree: {"active": False, "kinds": [], "branches": []}))


def m_no_unrelated_check(stack):
    def post(args, proc):
        if args[:1] == ["merge-base"] and "--is-ancestor" not in args and proc.returncode == 1:
            return fake(args, stdout=args[1] + "\n")
        return None
    patch_git(stack, post=post)


def m_ascending_order(stack):
    def around(original):
        def survey(*args, **kwargs):
            plan = original(*args, **kwargs)
            if plan["merge_order"]:
                head, rest = plan["merge_order"][0], plan["merge_order"][1:]
                plan["merge_order"] = [head, *reversed(rest)] if head == "main" else list(reversed(plan["merge_order"]))
            return plan
        return survey
    wrap(stack, "survey", around)


def m_delete_without_recheck(stack):
    def around(original):
        def delete_branch(repo, name, sha, target, ctx, report):
            gitlab.git(repo, "branch", "-D", name)
            report["deleted"][name] = sha
        return delete_branch
    wrap(stack, "delete_branch", around)


def m_ignore_lock_gate(stack):
    def around(original):
        def worktree_blockers(item, discard_ignored):
            return [b for b in original(item, discard_ignored) if b != "BLOCKED_LOCKED"]
        return worktree_blockers
    wrap(stack, "worktree_blockers", around)


def m_delete_main(stack):
    def around(original):
        def survey(*args, **kwargs):
            plan = original(*args, **kwargs)
            for entry in plan.get("sources", []):
                if entry["name"] == "main":
                    entry["kept"], entry["delete"] = False, True
            return plan
        return survey
    wrap(stack, "survey", around)


def m_ignore_harness(stack):
    stack.enter_context(mock.patch.object(converge_ref, "harness_owned", lambda path, roots: False))


def m_no_stale_check(stack):
    def around(original):
        def apply(invoking, target, discard_ignored=False, earlier_preview=None, **kwargs):
            return original(invoking, target, discard_ignored, None, **kwargs)
        return apply
    wrap(stack, "apply", around)


def m_no_ignored_files_gate(stack):
    stack.enter_context(mock.patch.object(converge_ref, "ignored_files", lambda worktree: []))


def m_no_invoking_clean_gate(stack):
    stack.enter_context(mock.patch.object(converge_ref, "is_clean", lambda worktree: True))


def m_mask_remove_failure(stack):
    patch_git(stack, post=lambda a, p: fake(a) if a[:2] == ["worktree", "remove"] and p.returncode else None)


def m_bare_target_name(stack):
    def pre(args):
        changed = [arg.replace("refs/heads/agent/release", "agent/release") for arg in args]
        return changed if changed != args else None
    patch_git(stack, pre=pre)


def m_no_sequencer(stack):
    stack.enter_context(mock.patch.object(converge_ref, "PROGRESS_FILES",
                                          tuple(name for name in converge_ref.PROGRESS_FILES if name != "sequencer")))


def m_no_hidden_edits(stack):
    stack.enter_context(mock.patch.object(converge_ref, "hidden_edits", lambda worktree: []))


def m_no_project_harness_root(stack):
    stack.enter_context(mock.patch.object(converge_ref, "PROJECT_HARNESS_ROOT", ("no-such-root",)))


def m_no_dependency_fixpoint(stack):
    stack.enter_context(mock.patch.object(converge_ref, "mark_dependencies", lambda entries, target, tracking: None))


def m_exact_ignored_overlap(stack):
    def exact(repo, changed):
        return sorted(changed & set(converge_ref.ignored_files(repo)))
    stack.enter_context(mock.patch.object(converge_ref, "ignored_overlap", exact))


def quoted_lines(cwd, *args):
    """`converge_ref.path_lines` without `core.quotePath=false`: Git's default C-quoted path listing."""
    return converge_ref.git(cwd, *args, check=True).stdout.splitlines()


def m_quoted_paths(stack):
    """The pre-fix check: Git's default C-quoted listings compared as plain strings, with no guard for quoted names."""
    def unguarded(repo, changed):
        ignored = [entry.rstrip("/") for entry in converge_ref.ignored_files(repo)]
        return sorted(path for path in changed
                      if any(path == entry or path.startswith(entry + "/") or entry.startswith(path + "/")
                             for entry in ignored))
    stack.enter_context(mock.patch.object(converge_ref, "path_lines", quoted_lines))
    stack.enter_context(mock.patch.object(converge_ref, "ignored_overlap", unguarded))


def m_default_quotepath(stack):
    """Keep the quoted-name guard but list paths in Git's default C-quoted form: an ignored non-ASCII entry then
    looks unreadable and stops an unrelated merge."""
    stack.enter_context(mock.patch.object(converge_ref, "path_lines", quoted_lines))


def m_no_case_collisions(stack):
    stack.enter_context(mock.patch.object(converge_ref, "case_collisions", lambda names: set()))


def m_target_move_always_stale(stack):
    stack.enter_context(mock.patch.object(converge_ref, "target_moved_only_by_plan", lambda repo, old, new, recorded: False))


MUTATIONS = [
    ("global-prune", "run a repository-wide `git worktree prune` after deleting", m_global_prune,
     ["detached-and-prunable"], True),
    ("force-delete-D", "delete branches with `git branch -D`", m_force_delete, ["upstream-behind"], True),
    ("force-remove-dirty", "drop the dirty/locked gates and pass --force to worktree remove", m_force_remove_dirty,
     ["dirty-source-worktree"], True),
    ("move-main", "force main onto the target after the run", m_move_main, ["happy-path"], True),
    ("merge-by-name", "merge the bare branch name instead of the recorded SHA", m_merge_by_name, ["tag-shadow"], True),
    ("no-abort", "leave a conflicted merge in progress", m_no_abort, ["conflict-stops", "conflict-predicted"], True),
    ("merge-X-theirs", "resolve conflicts with -X theirs", m_merge_x_theirs, ["conflict-stops"], True),
    ("case-insensitive-target", "accept a differently-cased target name", m_case_insensitive,
     ["case-variant-target"], True),
    ("no-ignored-overlap-check", "skip the ignored-file overwrite check before a merge", m_no_ignored_overlap,
     ["ignored-overwrite-merge"], True),
    ("no-rebase-detection", "ignore a rebase in progress", m_no_rebase_detection, ["rebase-in-progress"], True),
    ("no-unrelated-check", "treat an orphan branch as mergeable", m_no_unrelated_check, ["unrelated-history"], True),
    ("ascending-order", "merge the smallest source first", m_ascending_order,
     ["ordering-and-containment", "preview-readonly"], True),
    ("delete-without-recheck", "delete with -D and no tip/ancestry recheck", m_delete_without_recheck,
     ["tip-moves-mid-run"], True),
    ("delete-main", "put main in the delete set", m_delete_main, ["happy-path"], True),
    ("ignore-harness-owner", "treat an agent-harness worktree as free", m_ignore_harness,
     ["harness-owned-worktree"], True),
    ("no-stale-check", "ignore an earlier preview", m_no_stale_check, ["stale-preview"], True),
    ("no-ignored-files-gate", "remove worktrees that hold ignored files", m_no_ignored_files_gate,
     ["ignored-files-kept"], True),
    ("no-invoking-clean-gate", "run from a dirty invoking worktree", m_no_invoking_clean_gate, ["invoking-dirty"], True),
    ("mask-remove-failure", "delete the branch even when worktree remove failed", m_mask_remove_failure,
     ["worktree-remove-failure"], True),
    ("bare-target-name", "use the bare target name in revision arguments", m_bare_target_name,
     ["target-tag-shadow"], True),
    ("no-sequencer", "ignore a paused cherry-pick sequence", m_no_sequencer, ["sequencer-in-progress"], True),
    ("no-hidden-edits", "treat skip-worktree edits as clean", m_no_hidden_edits, ["skip-worktree-edits"], True),
    ("no-project-harness-root", "forget <repo>/.claude/worktrees as a harness root", m_no_project_harness_root,
     ["claude-session-worktree"], True),
    ("no-dependency-fixpoint", "ignore branches that a remaining lane tracks", m_no_dependency_fixpoint,
     ["dependency-of-remaining-lane", "upstream-of-kept"], True),
    ("exact-ignored-overlap", "compare ignored paths by exact string only", m_exact_ignored_overlap,
     ["ignored-overwrite-dir-file", "ignored-overwrite-file-dir"], True),
    ("quoted-ignored-paths", "compare paths in Git's default C-quoted form, with no quoted-name guard", m_quoted_paths,
     ["ignored-overwrite-nonascii"], True),
    ("default-quotepath", "list paths without core.quotePath=false (the guard alone)", m_default_quotepath,
     ["ignored-nonascii-no-overlap"], True),
    ("no-case-collision-check", "ignore branch names that differ only in case", m_no_case_collisions,
     ["case-colliding-sources", "case-colliding-target"], True),
    ("target-move-always-stale", "treat the target's own merges as a stale preview", m_target_move_always_stale,
     ["rerun-after-interrupted-apply"], True),
    ("ignore-lock-gate", "drop the lock gate (Git still refuses to remove a locked worktree)", m_ignore_lock_gate,
     ["locked-source-worktree"], False),
]


def run_mutation(name: str, description: str, install, names: list[str], expect_killed: bool, base: str | None) -> dict:
    """Run the named scenarios with the mutation active; report which ones failed and why."""
    failures = []
    with ExitStack() as stack:
        install(stack)
        for scenario_id in names:
            outcome = run_reference_cases.run_one(scenarios.REGISTRY[scenario_id], base)
            if outcome["status"] in ("FAIL", "ERROR"):
                failed = [row["name"] for row in outcome["checks"] if not row["passed"]] or ["scenario crashed"]
                failures.append({"scenario": scenario_id, "status": outcome["status"], "failed_checks": failed})
            elif outcome["status"] == "SKIPPED":
                failures.append({"scenario": scenario_id, "status": "SKIPPED", "failed_checks": []})
    killed = any(item["status"] in ("FAIL", "ERROR") for item in failures)
    skipped_all = bool(failures) and all(item["status"] == "SKIPPED" for item in failures) and len(failures) == len(names)
    verdict = "SKIPPED" if skipped_all else "KILLED" if killed else "SURVIVED"
    return {"mutation": name, "description": description, "scenarios": names, "expect_killed": expect_killed,
            "verdict": verdict, "as_expected": skipped_all or killed == expect_killed, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", help="short directory for fixtures (Windows path length)")
    parser.add_argument("--only", action="append", help="mutation name; repeat to select several")
    options = parser.parse_args()
    chosen = [m for m in MUTATIONS if not options.only or m[0] in options.only]
    results = [run_mutation(*mutation, options.fixture_root) for mutation in chosen]
    for result in results:
        mark = "ok " if result["as_expected"] else "BAD"
        print(f"{mark} {result['verdict']:8} {result['mutation']}")
    wrong = [r for r in results if not r["as_expected"]]
    killed = sum(r["verdict"] == "KILLED" for r in results)
    print(f"{killed}/{len(results)} mutations killed; {len(wrong)} unexpected outcome(s)")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Mutation checks", "", f"- Killed: **{killed}/{len(results)}**; unexpected outcomes: **{len(wrong)}**", "",
             "| Mutation | Verdict | Expected | Caught by |", "|---|---|---|---|"]
    for r in results:
        caught = "; ".join(f"`{f['scenario']}`: {', '.join(f['failed_checks'])}" for f in r["failures"] if f["failed_checks"])
        lines.append(f"| `{r['mutation']}` — {r['description']} | {r['verdict']} | "
                     f"{'killed' if r['expect_killed'] else 'survive (Git enforces it)'} | {caught or '-'} |")
    (RESULTS_DIR / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if not wrong else 1


if __name__ == "__main__":
    raise SystemExit(main())
