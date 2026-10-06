# ```cypher
# CREATE
#   (file:File {name: "scenarios.py", type: "file", language: "python"}),
#   (v_TARGET:Variable {name: "TARGET", type: "variable"}),
#   (v_REGISTRY:Variable {name: "REGISTRY", type: "variable"}),
#   (f_scenario:Function {name: "scenario", type: "function", signature: "scenario(id: str, title: str, mode: str='apply', discard: bool=False, claude: bool=True, platforms: tuple[str, ...] | None=None, report: tuple[str, ...]=(), lang: str | None=None, command: str='GitConverge', cmd_args: str='', inspects: bool | None=True)"}),
#   (f_scenario_register:Function {name: "scenario.register", type: "function", signature: "register(builder)"}),
#   (f_oracle:Function {name: "oracle", type: "function", signature: "oracle(id: str)"}),
#   (f_oracle_register:Function {name: "oracle.register", type: "function", signature: "register(function)"}),
#   (f_plan_oracle:Function {name: "plan_oracle", type: "function", signature: "plan_oracle(id: str)"}),
#   (f_plan_oracle_register:Function {name: "plan_oracle.register", type: "function", signature: "register(function)"}),
#   (f_stop_code:Function {name: "stop_code", type: "function", signature: "stop_code(result: dict, key: str='report') -> str | None"}),
#   (f_flow:Function {name: "flow", type: "function", signature: "flow(id: str)"}),
#   (f_flow_register:Function {name: "flow.register", type: "function", signature: "register(function)"}),
#   (f_base:Function {name: "base", type: "function", signature: "base(root: Path, origin: bool=True, gitignore: str | None=None) -> dict"}),
#   (f_lane:Function {name: "lane", type: "function", signature: "lane(ctx: dict, name: str, files: list[tuple[str, str]], worktree: str | None=None, start: str | None=None, push: bool=False) -> Path | None"}),
#   (f_commit_on:Function {name: "commit_on", type: "function", signature: "commit_on(ctx: dict, name: str, path: str, text: str) -> str"}),
#   (f_build_happy_path:Function {name: "build_happy_path", type: "function", signature: "build_happy_path(root: Path) -> dict"}),
#   (f_check_happy_path:Function {name: "check_happy_path", type: "function", signature: "check_happy_path(ctx, before, after)"}),
#   (f_plan_happy_path:Function {name: "plan_happy_path", type: "function", signature: "plan_happy_path(ctx, result)"}),
#   (f_build_preview:Function {name: "build_preview", type: "function", signature: "build_preview(root: Path) -> dict"}),
#   (f_check_preview:Function {name: "check_preview", type: "function", signature: "check_preview(ctx, before, after)"}),
#   (f_plan_preview:Function {name: "plan_preview", type: "function", signature: "plan_preview(ctx, result)"}),
#   (f_build_preview_english:Function {name: "build_preview_english", type: "function", signature: "build_preview_english(root: Path) -> dict"}),
#   (f__other_command:Function {name: "_other_command", type: "function", signature: "_other_command(id: str, title: str, command: str, cmd_args: str, lang: str | None, inspects: bool=True)"}),
#   (f_expects_plan:Function {name: "expects_plan", type: "function", signature: "expects_plan(scen: dict) -> bool"}),
#   (f_build_ordering:Function {name: "build_ordering", type: "function", signature: "build_ordering(root: Path) -> dict"}),
#   (f_check_ordering:Function {name: "check_ordering", type: "function", signature: "check_ordering(ctx, before, after)"}),
#   (f_plan_ordering:Function {name: "plan_ordering", type: "function", signature: "plan_ordering(ctx, result)"}),
#   (f_build_conflict:Function {name: "build_conflict", type: "function", signature: "build_conflict(root: Path) -> dict"}),
#   (f_check_conflict:Function {name: "check_conflict", type: "function", signature: "check_conflict(ctx, before, after)"}),
#   (f_plan_conflict:Function {name: "plan_conflict", type: "function", signature: "plan_conflict(ctx, result)"}),
#   (f_build_conflict_predicted:Function {name: "build_conflict_predicted", type: "function", signature: "build_conflict_predicted(root: Path) -> dict"}),
#   (f_check_conflict_predicted:Function {name: "check_conflict_predicted", type: "function", signature: "check_conflict_predicted(ctx, before, after)"}),
#   (f_plan_conflict_predicted:Function {name: "plan_conflict_predicted", type: "function", signature: "plan_conflict_predicted(ctx, result)"}),
#   (f_build_rerun:Function {name: "build_rerun", type: "function", signature: "build_rerun(root: Path) -> dict"}),
#   (f_flow_rerun:Function {name: "flow_rerun", type: "function", signature: "flow_rerun(ctx, ref, scen)"}),
#   (f_check_rerun:Function {name: "check_rerun", type: "function", signature: "check_rerun(ctx, before, after)"}),
#   (f_plan_rerun:Function {name: "plan_rerun", type: "function", signature: "plan_rerun(ctx, result)"}),
#   (f_build_unrelated:Function {name: "build_unrelated", type: "function", signature: "build_unrelated(root: Path) -> dict"}),
#   (f_check_unrelated:Function {name: "check_unrelated", type: "function", signature: "check_unrelated(ctx, before, after)"}),
#   (f_plan_unrelated:Function {name: "plan_unrelated", type: "function", signature: "plan_unrelated(ctx, result)"}),
#   (f__blocked_worktree_builder:Function {name: "_blocked_worktree_builder", type: "function", signature: "_blocked_worktree_builder(root: Path, kind: str) -> dict"}),
#   (f__blocked_oracle:Function {name: "_blocked_oracle", type: "function", signature: "_blocked_oracle(ctx, before, after)"}),
#   (f_build_dirty:Function {name: "build_dirty", type: "function", signature: "build_dirty(root: Path) -> dict"}),
#   (f_check_dirty:Function {name: "check_dirty", type: "function", signature: "check_dirty(ctx, before, after)"}),
#   (f_build_locked:Function {name: "build_locked", type: "function", signature: "build_locked(root: Path) -> dict"}),
#   (f_check_locked:Function {name: "check_locked", type: "function", signature: "check_locked(ctx, before, after)"}),
#   (f_build_harness:Function {name: "build_harness", type: "function", signature: "build_harness(root: Path) -> dict"}),
#   (f_check_harness:Function {name: "check_harness", type: "function", signature: "check_harness(ctx, before, after)"}),
#   (f_build_rebase:Function {name: "build_rebase", type: "function", signature: "build_rebase(root: Path) -> dict"}),
#   (f_check_rebase:Function {name: "check_rebase", type: "function", signature: "check_rebase(ctx, before, after)"}),
#   (f_plan_rebase:Function {name: "plan_rebase", type: "function", signature: "plan_rebase(ctx, result)"}),
#   (f__ignored_worktree_builder:Function {name: "_ignored_worktree_builder", type: "function", signature: "_ignored_worktree_builder(root: Path) -> dict"}),
#   (f_build_ignored_kept:Function {name: "build_ignored_kept", type: "function", signature: "build_ignored_kept(root: Path) -> dict"}),
#   (f_check_ignored_kept:Function {name: "check_ignored_kept", type: "function", signature: "check_ignored_kept(ctx, before, after)"}),
#   (f_build_ignored_discard:Function {name: "build_ignored_discard", type: "function", signature: "build_ignored_discard(root: Path) -> dict"}),
#   (f_check_ignored_discard:Function {name: "check_ignored_discard", type: "function", signature: "check_ignored_discard(ctx, before, after)"}),
#   (f_build_overwrite:Function {name: "build_overwrite", type: "function", signature: "build_overwrite(root: Path) -> dict"}),
#   (f_check_overwrite:Function {name: "check_overwrite", type: "function", signature: "check_overwrite(ctx, before, after)"}),
#   (f_plan_overwrite:Function {name: "plan_overwrite", type: "function", signature: "plan_overwrite(ctx, result)"}),
#   (f_build_tag_shadow:Function {name: "build_tag_shadow", type: "function", signature: "build_tag_shadow(root: Path) -> dict"}),
#   (f_check_tag_shadow:Function {name: "check_tag_shadow", type: "function", signature: "check_tag_shadow(ctx, before, after)"}),
#   (f_plan_tag_shadow:Function {name: "plan_tag_shadow", type: "function", signature: "plan_tag_shadow(ctx, result)"}),
#   (f__gate_builder:Function {name: "_gate_builder", type: "function", signature: "_gate_builder(root: Path) -> dict"}),
#   (f__unchanged_oracle:Function {name: "_unchanged_oracle", type: "function", signature: "_unchanged_oracle(ctx, before, after)"}),
#   (f_build_case:Function {name: "build_case", type: "function", signature: "build_case(root: Path) -> dict"}),
#   (f_plan_case:Function {name: "plan_case", type: "function", signature: "plan_case(ctx, result)"}),
#   (f_build_target_main:Function {name: "build_target_main", type: "function", signature: "build_target_main(root: Path) -> dict"}),
#   (f_build_target_missing:Function {name: "build_target_missing", type: "function", signature: "build_target_missing(root: Path) -> dict"}),
#   (f_build_detached:Function {name: "build_detached", type: "function", signature: "build_detached(root: Path) -> dict"}),
#   (f_build_invoking_dirty:Function {name: "build_invoking_dirty", type: "function", signature: "build_invoking_dirty(root: Path) -> dict"}),
#   (f_build_elsewhere:Function {name: "build_elsewhere", type: "function", signature: "build_elsewhere(root: Path) -> dict"}),
#   (f_build_target_prunable:Function {name: "build_target_prunable", type: "function", signature: "build_target_prunable(root: Path) -> dict"}),
#   (f_plan_target_prunable:Function {name: "plan_target_prunable", type: "function", signature: "plan_target_prunable(ctx, result)"}),
#   (f_build_main_prunable:Function {name: "build_main_prunable", type: "function", signature: "build_main_prunable(root: Path) -> dict"}),
#   (f_plan_main_prunable:Function {name: "plan_main_prunable", type: "function", signature: "plan_main_prunable(ctx, result)"}),
#   (f_build_from_target:Function {name: "build_from_target", type: "function", signature: "build_from_target(root: Path) -> dict"}),
#   (f_check_from_target:Function {name: "check_from_target", type: "function", signature: "check_from_target(ctx, before, after)"}),
#   (f_build_on_other:Function {name: "build_on_other", type: "function", signature: "build_on_other(root: Path) -> dict"}),
#   (f_check_on_other:Function {name: "check_on_other", type: "function", signature: "check_on_other(ctx, before, after)"}),
#   (f_build_upstream:Function {name: "build_upstream", type: "function", signature: "build_upstream(root: Path) -> dict"}),
#   (f_check_upstream:Function {name: "check_upstream", type: "function", signature: "check_upstream(ctx, before, after)"}),
#   (f_build_prunable:Function {name: "build_prunable", type: "function", signature: "build_prunable(root: Path) -> dict"}),
#   (f_check_prunable:Function {name: "check_prunable", type: "function", signature: "check_prunable(ctx, before, after)"}),
#   (f_build_stale:Function {name: "build_stale", type: "function", signature: "build_stale(root: Path) -> dict"}),
#   (f_flow_stale:Function {name: "flow_stale", type: "function", signature: "flow_stale(ctx, ref, scen)"}),
#   (f_check_stale:Function {name: "check_stale", type: "function", signature: "check_stale(ctx, before, after)"}),
#   (f_plan_stale:Function {name: "plan_stale", type: "function", signature: "plan_stale(ctx, result)"}),
#   (f_build_appeared:Function {name: "build_appeared", type: "function", signature: "build_appeared(root: Path) -> dict"}),
#   (f_flow_appeared:Function {name: "flow_appeared", type: "function", signature: "flow_appeared(ctx, ref, scen)"}),
#   (f_check_appeared:Function {name: "check_appeared", type: "function", signature: "check_appeared(ctx, before, after)"}),
#   (f_build_tip_moves:Function {name: "build_tip_moves", type: "function", signature: "build_tip_moves(root: Path) -> dict"}),
#   (f_flow_tip_moves:Function {name: "flow_tip_moves", type: "function", signature: "flow_tip_moves(ctx, ref, scen)"}),
#   (f_flow_tip_moves_hook:Function {name: "flow_tip_moves.hook", type: "function", signature: "hook(event: str, name: str) -> None"}),
#   (f_check_tip_moves:Function {name: "check_tip_moves", type: "function", signature: "check_tip_moves(ctx, before, after)"}),
#   (f_build_validation:Function {name: "build_validation", type: "function", signature: "build_validation(root: Path) -> dict"}),
#   (f_flow_validation:Function {name: "flow_validation", type: "function", signature: "flow_validation(ctx, ref, scen)"}),
#   (f_flow_validation_lambda_783_66:Function {name: "flow_validation.lambda_783_66", type: "function", signature: "lambda_783_66(repo)"}),
#   (f_check_validation:Function {name: "check_validation", type: "function", signature: "check_validation(ctx, before, after)"}),
#   (f_build_busy:Function {name: "build_busy", type: "function", signature: "build_busy(root: Path) -> dict"}),
#   (f_flow_busy:Function {name: "flow_busy", type: "function", signature: "flow_busy(ctx, ref, scen)"}),
#   (f_check_busy:Function {name: "check_busy", type: "function", signature: "check_busy(ctx, before, after)"}),
#   (f_plan_busy:Function {name: "plan_busy", type: "function", signature: "plan_busy(ctx, result)"}),
#   (f_build_upstream_kept:Function {name: "build_upstream_kept", type: "function", signature: "build_upstream_kept(root: Path) -> dict"}),
#   (f_check_upstream_kept:Function {name: "check_upstream_kept", type: "function", signature: "check_upstream_kept(ctx, before, after)"}),
#   (f_build_submodule:Function {name: "build_submodule", type: "function", signature: "build_submodule(root: Path) -> dict"}),
#   (f_check_submodule:Function {name: "check_submodule", type: "function", signature: "check_submodule(ctx, before, after)"}),
#   (f_build_target_tag_shadow:Function {name: "build_target_tag_shadow", type: "function", signature: "build_target_tag_shadow(root: Path) -> dict"}),
#   (f_check_target_tag_shadow:Function {name: "check_target_tag_shadow", type: "function", signature: "check_target_tag_shadow(ctx, before, after)"}),
#   (f_plan_target_tag_shadow:Function {name: "plan_target_tag_shadow", type: "function", signature: "plan_target_tag_shadow(ctx, result)"}),
#   (f__overwrite_builder:Function {name: "_overwrite_builder", type: "function", signature: "_overwrite_builder(root: Path, gitignore: str, source_files: list[tuple[str, str]], local: dict[str, str]) -> dict"}),
#   (f__overwrite_oracle:Function {name: "_overwrite_oracle", type: "function", signature: "_overwrite_oracle(ctx, before, after)"}),
#   (f__overwrite_plan:Function {name: "_overwrite_plan", type: "function", signature: "_overwrite_plan(ctx, result)"}),
#   (f_build_overwrite_case:Function {name: "build_overwrite_case", type: "function", signature: "build_overwrite_case(root: Path) -> dict"}),
#   (f_check_overwrite_case:Function {name: "check_overwrite_case", type: "function", signature: "check_overwrite_case(ctx, before, after)"}),
#   (f_plan_overwrite_case:Function {name: "plan_overwrite_case", type: "function", signature: "plan_overwrite_case(ctx, result)"}),
#   (f_build_overwrite_dir_file:Function {name: "build_overwrite_dir_file", type: "function", signature: "build_overwrite_dir_file(root: Path) -> dict"}),
#   (f_build_overwrite_file_dir:Function {name: "build_overwrite_file_dir", type: "function", signature: "build_overwrite_file_dir(root: Path) -> dict"}),
#   (f_build_sequencer:Function {name: "build_sequencer", type: "function", signature: "build_sequencer(root: Path) -> dict"}),
#   (f_check_sequencer:Function {name: "check_sequencer", type: "function", signature: "check_sequencer(ctx, before, after)"}),
#   (f_plan_sequencer:Function {name: "plan_sequencer", type: "function", signature: "plan_sequencer(ctx, result)"}),
#   (f_build_skip_worktree:Function {name: "build_skip_worktree", type: "function", signature: "build_skip_worktree(root: Path) -> dict"}),
#   (f_check_skip_worktree:Function {name: "check_skip_worktree", type: "function", signature: "check_skip_worktree(ctx, before, after)"}),
#   (f_build_claude_session:Function {name: "build_claude_session", type: "function", signature: "build_claude_session(root: Path) -> dict"}),
#   (f_check_claude_session:Function {name: "check_claude_session", type: "function", signature: "check_claude_session(ctx, before, after)"}),
#   (f_build_dependency:Function {name: "build_dependency", type: "function", signature: "build_dependency(root: Path) -> dict"}),
#   (f_check_dependency:Function {name: "check_dependency", type: "function", signature: "check_dependency(ctx, before, after)"}),
#   (f_build_main_in_progress:Function {name: "build_main_in_progress", type: "function", signature: "build_main_in_progress(root: Path) -> dict"}),
#   (f_check_main_in_progress:Function {name: "check_main_in_progress", type: "function", signature: "check_main_in_progress(ctx, before, after)"}),
#   (f_plan_main_in_progress:Function {name: "plan_main_in_progress", type: "function", signature: "plan_main_in_progress(ctx, result)"}),
#   (f_build_worktree_appeared:Function {name: "build_worktree_appeared", type: "function", signature: "build_worktree_appeared(root: Path) -> dict"}),
#   (f_flow_worktree_appeared:Function {name: "flow_worktree_appeared", type: "function", signature: "flow_worktree_appeared(ctx, ref, scen)"}),
#   (f_check_worktree_appeared:Function {name: "check_worktree_appeared", type: "function", signature: "check_worktree_appeared(ctx, before, after)"}),
#   (f_build_rerun_interrupted:Function {name: "build_rerun_interrupted", type: "function", signature: "build_rerun_interrupted(root: Path) -> dict"}),
#   (f_flow_rerun_interrupted:Function {name: "flow_rerun_interrupted", type: "function", signature: "flow_rerun_interrupted(ctx, ref, scen)"}),
#   (f_check_rerun_interrupted:Function {name: "check_rerun_interrupted", type: "function", signature: "check_rerun_interrupted(ctx, before, after)"}),
#   (f_plan_rerun_interrupted:Function {name: "plan_rerun_interrupted", type: "function", signature: "plan_rerun_interrupted(ctx, result)"}),
#   (f_invariants:Function {name: "invariants", type: "function", signature: "invariants(ctx: dict, before: dict, after: dict) -> list[tuple[str, bool]]"}),
#   (f_rel:Function {name: "rel", type: "function", signature: "rel(ctx: dict, path: str | Path) -> str"}),
#   (f_snapshot:Function {name: "snapshot", type: "function", signature: "snapshot(ctx: dict) -> dict"}),
#   (f_snapshot_lambda_1162_43:Function {name: "snapshot.lambda_1162_43", type: "function", signature: "lambda_1162_43(entry)"}),
#   (file)-[:CONTAINS]->(v_TARGET),
#   (file)-[:CONTAINS]->(v_REGISTRY),
#   (file)-[:CONTAINS]->(f_scenario),
#   (f_scenario)-[:CONTAINS]->(f_scenario_register),
#   (file)-[:CONTAINS]->(f_oracle),
#   (f_oracle)-[:CONTAINS]->(f_oracle_register),
#   (file)-[:CONTAINS]->(f_plan_oracle),
#   (f_plan_oracle)-[:CONTAINS]->(f_plan_oracle_register),
#   (file)-[:CONTAINS]->(f_stop_code),
#   (file)-[:CONTAINS]->(f_flow),
#   (f_flow)-[:CONTAINS]->(f_flow_register),
#   (file)-[:CONTAINS]->(f_base),
#   (file)-[:CONTAINS]->(f_lane),
#   (file)-[:CONTAINS]->(f_commit_on),
#   (file)-[:CONTAINS]->(f_build_happy_path),
#   (file)-[:CONTAINS]->(f_check_happy_path),
#   (file)-[:CONTAINS]->(f_plan_happy_path),
#   (file)-[:CONTAINS]->(f_build_preview),
#   (file)-[:CONTAINS]->(f_check_preview),
#   (file)-[:CONTAINS]->(f_plan_preview),
#   (file)-[:CONTAINS]->(f_build_preview_english),
#   (file)-[:CONTAINS]->(f__other_command),
#   (file)-[:CONTAINS]->(f_expects_plan),
#   (file)-[:CONTAINS]->(f_build_ordering),
#   (file)-[:CONTAINS]->(f_check_ordering),
#   (file)-[:CONTAINS]->(f_plan_ordering),
#   (file)-[:CONTAINS]->(f_build_conflict),
#   (file)-[:CONTAINS]->(f_check_conflict),
#   (file)-[:CONTAINS]->(f_plan_conflict),
#   (file)-[:CONTAINS]->(f_build_conflict_predicted),
#   (file)-[:CONTAINS]->(f_check_conflict_predicted),
#   (file)-[:CONTAINS]->(f_plan_conflict_predicted),
#   (file)-[:CONTAINS]->(f_build_rerun),
#   (file)-[:CONTAINS]->(f_flow_rerun),
#   (file)-[:CONTAINS]->(f_check_rerun),
#   (file)-[:CONTAINS]->(f_plan_rerun),
#   (file)-[:CONTAINS]->(f_build_unrelated),
#   (file)-[:CONTAINS]->(f_check_unrelated),
#   (file)-[:CONTAINS]->(f_plan_unrelated),
#   (file)-[:CONTAINS]->(f__blocked_worktree_builder),
#   (file)-[:CONTAINS]->(f__blocked_oracle),
#   (file)-[:CONTAINS]->(f_build_dirty),
#   (file)-[:CONTAINS]->(f_check_dirty),
#   (file)-[:CONTAINS]->(f_build_locked),
#   (file)-[:CONTAINS]->(f_check_locked),
#   (file)-[:CONTAINS]->(f_build_harness),
#   (file)-[:CONTAINS]->(f_check_harness),
#   (file)-[:CONTAINS]->(f_build_rebase),
#   (file)-[:CONTAINS]->(f_check_rebase),
#   (file)-[:CONTAINS]->(f_plan_rebase),
#   (file)-[:CONTAINS]->(f__ignored_worktree_builder),
#   (file)-[:CONTAINS]->(f_build_ignored_kept),
#   (file)-[:CONTAINS]->(f_check_ignored_kept),
#   (file)-[:CONTAINS]->(f_build_ignored_discard),
#   (file)-[:CONTAINS]->(f_check_ignored_discard),
#   (file)-[:CONTAINS]->(f_build_overwrite),
#   (file)-[:CONTAINS]->(f_check_overwrite),
#   (file)-[:CONTAINS]->(f_plan_overwrite),
#   (file)-[:CONTAINS]->(f_build_tag_shadow),
#   (file)-[:CONTAINS]->(f_check_tag_shadow),
#   (file)-[:CONTAINS]->(f_plan_tag_shadow),
#   (file)-[:CONTAINS]->(f__gate_builder),
#   (file)-[:CONTAINS]->(f__unchanged_oracle),
#   (file)-[:CONTAINS]->(f_build_case),
#   (file)-[:CONTAINS]->(f_plan_case),
#   (file)-[:CONTAINS]->(f_build_target_main),
#   (file)-[:CONTAINS]->(f_build_target_missing),
#   (file)-[:CONTAINS]->(f_build_detached),
#   (file)-[:CONTAINS]->(f_build_invoking_dirty),
#   (file)-[:CONTAINS]->(f_build_elsewhere),
#   (file)-[:CONTAINS]->(f_build_target_prunable),
#   (file)-[:CONTAINS]->(f_plan_target_prunable),
#   (file)-[:CONTAINS]->(f_build_main_prunable),
#   (file)-[:CONTAINS]->(f_plan_main_prunable),
#   (file)-[:CONTAINS]->(f_build_from_target),
#   (file)-[:CONTAINS]->(f_check_from_target),
#   (file)-[:CONTAINS]->(f_build_on_other),
#   (file)-[:CONTAINS]->(f_check_on_other),
#   (file)-[:CONTAINS]->(f_build_upstream),
#   (file)-[:CONTAINS]->(f_check_upstream),
#   (file)-[:CONTAINS]->(f_build_prunable),
#   (file)-[:CONTAINS]->(f_check_prunable),
#   (file)-[:CONTAINS]->(f_build_stale),
#   (file)-[:CONTAINS]->(f_flow_stale),
#   (file)-[:CONTAINS]->(f_check_stale),
#   (file)-[:CONTAINS]->(f_plan_stale),
#   (file)-[:CONTAINS]->(f_build_appeared),
#   (file)-[:CONTAINS]->(f_flow_appeared),
#   (file)-[:CONTAINS]->(f_check_appeared),
#   (file)-[:CONTAINS]->(f_build_tip_moves),
#   (file)-[:CONTAINS]->(f_flow_tip_moves),
#   (f_flow_tip_moves)-[:CONTAINS]->(f_flow_tip_moves_hook),
#   (file)-[:CONTAINS]->(f_check_tip_moves),
#   (file)-[:CONTAINS]->(f_build_validation),
#   (file)-[:CONTAINS]->(f_flow_validation),
#   (f_flow_validation)-[:CONTAINS]->(f_flow_validation_lambda_783_66),
#   (file)-[:CONTAINS]->(f_check_validation),
#   (file)-[:CONTAINS]->(f_build_busy),
#   (file)-[:CONTAINS]->(f_flow_busy),
#   (file)-[:CONTAINS]->(f_check_busy),
#   (file)-[:CONTAINS]->(f_plan_busy),
#   (file)-[:CONTAINS]->(f_build_upstream_kept),
#   (file)-[:CONTAINS]->(f_check_upstream_kept),
#   (file)-[:CONTAINS]->(f_build_submodule),
#   (file)-[:CONTAINS]->(f_check_submodule),
#   (file)-[:CONTAINS]->(f_build_target_tag_shadow),
#   (file)-[:CONTAINS]->(f_check_target_tag_shadow),
#   (file)-[:CONTAINS]->(f_plan_target_tag_shadow),
#   (file)-[:CONTAINS]->(f__overwrite_builder),
#   (file)-[:CONTAINS]->(f__overwrite_oracle),
#   (file)-[:CONTAINS]->(f__overwrite_plan),
#   (file)-[:CONTAINS]->(f_build_overwrite_case),
#   (file)-[:CONTAINS]->(f_check_overwrite_case),
#   (file)-[:CONTAINS]->(f_plan_overwrite_case),
#   (file)-[:CONTAINS]->(f_build_overwrite_dir_file),
#   (file)-[:CONTAINS]->(f_build_overwrite_file_dir),
#   (file)-[:CONTAINS]->(f_build_sequencer),
#   (file)-[:CONTAINS]->(f_check_sequencer),
#   (file)-[:CONTAINS]->(f_plan_sequencer),
#   (file)-[:CONTAINS]->(f_build_skip_worktree),
#   (file)-[:CONTAINS]->(f_check_skip_worktree),
#   (file)-[:CONTAINS]->(f_build_claude_session),
#   (file)-[:CONTAINS]->(f_check_claude_session),
#   (file)-[:CONTAINS]->(f_build_dependency),
#   (file)-[:CONTAINS]->(f_check_dependency),
#   (file)-[:CONTAINS]->(f_build_main_in_progress),
#   (file)-[:CONTAINS]->(f_check_main_in_progress),
#   (file)-[:CONTAINS]->(f_plan_main_in_progress),
#   (file)-[:CONTAINS]->(f_build_worktree_appeared),
#   (file)-[:CONTAINS]->(f_flow_worktree_appeared),
#   (file)-[:CONTAINS]->(f_check_worktree_appeared),
#   (file)-[:CONTAINS]->(f_build_rerun_interrupted),
#   (file)-[:CONTAINS]->(f_flow_rerun_interrupted),
#   (file)-[:CONTAINS]->(f_check_rerun_interrupted),
#   (file)-[:CONTAINS]->(f_plan_rerun_interrupted),
#   (file)-[:CONTAINS]->(f_invariants),
#   (file)-[:CONTAINS]->(f_rel),
#   (file)-[:CONTAINS]->(f_snapshot),
#   (f_snapshot)-[:CONTAINS]->(f_snapshot_lambda_1162_43),
#   (f__blocked_oracle)-[:USES]->(v_TARGET),
#   (f__blocked_worktree_builder)-[:CALLS]->(f_base),
#   (f__blocked_worktree_builder)-[:CALLS]->(f_lane),
#   (f__gate_builder)-[:CALLS]->(f_base),
#   (f__gate_builder)-[:CALLS]->(f_lane),
#   (f__ignored_worktree_builder)-[:CALLS]->(f_base),
#   (f__ignored_worktree_builder)-[:CALLS]->(f_lane),
#   (f__other_command)-[:CALLS]->(f_oracle),
#   (f__other_command)-[:CALLS]->(f_scenario),
#   (f__overwrite_builder)-[:CALLS]->(f_base),
#   (f__overwrite_builder)-[:CALLS]->(f_lane),
#   (f__overwrite_oracle)-[:USES]->(v_TARGET),
#   (f__overwrite_plan)-[:CALLS]->(f_stop_code),
#   (f_base)-[:USES]->(v_TARGET),
#   (f_build_appeared)-[:CALLS]->(f_base),
#   (f_build_appeared)-[:CALLS]->(f_lane),
#   (f_build_busy)-[:CALLS]->(f_base),
#   (f_build_busy)-[:CALLS]->(f_lane),
#   (f_build_case)-[:CALLS]->(f__gate_builder),
#   (f_build_claude_session)-[:CALLS]->(f_base),
#   (f_build_claude_session)-[:CALLS]->(f_lane),
#   (f_build_claude_session)-[:USES]->(v_TARGET),
#   (f_build_conflict)-[:CALLS]->(f_base),
#   (f_build_conflict)-[:CALLS]->(f_lane),
#   (f_build_conflict_predicted)-[:CALLS]->(f_base),
#   (f_build_conflict_predicted)-[:CALLS]->(f_lane),
#   (f_build_conflict_predicted)-[:USES]->(v_TARGET),
#   (f_build_dependency)-[:CALLS]->(f_base),
#   (f_build_dependency)-[:CALLS]->(f_lane),
#   (f_build_detached)-[:CALLS]->(f__gate_builder),
#   (f_build_dirty)-[:CALLS]->(f__blocked_worktree_builder),
#   (f_build_elsewhere)-[:CALLS]->(f__gate_builder),
#   (f_build_elsewhere)-[:USES]->(v_TARGET),
#   (f_build_from_target)-[:CALLS]->(f_build_elsewhere),
#   (f_build_happy_path)-[:CALLS]->(f_base),
#   (f_build_happy_path)-[:CALLS]->(f_commit_on),
#   (f_build_happy_path)-[:CALLS]->(f_lane),
#   (f_build_harness)-[:CALLS]->(f__blocked_worktree_builder),
#   (f_build_ignored_discard)-[:CALLS]->(f__ignored_worktree_builder),
#   (f_build_ignored_kept)-[:CALLS]->(f__ignored_worktree_builder),
#   (f_build_invoking_dirty)-[:CALLS]->(f__gate_builder),
#   (f_build_locked)-[:CALLS]->(f__blocked_worktree_builder),
#   (f_build_main_in_progress)-[:CALLS]->(f_base),
#   (f_build_main_in_progress)-[:CALLS]->(f_lane),
#   (f_build_main_in_progress)-[:USES]->(v_TARGET),
#   (f_build_main_prunable)-[:CALLS]->(f__gate_builder),
#   (f_build_on_other)-[:CALLS]->(f_base),
#   (f_build_on_other)-[:CALLS]->(f_lane),
#   (f_build_ordering)-[:CALLS]->(f_base),
#   (f_build_ordering)-[:CALLS]->(f_lane),
#   (f_build_overwrite)-[:CALLS]->(f_base),
#   (f_build_overwrite)-[:CALLS]->(f_lane),
#   (f_build_overwrite_case)-[:CALLS]->(f__overwrite_builder),
#   (f_build_overwrite_dir_file)-[:CALLS]->(f__overwrite_builder),
#   (f_build_overwrite_file_dir)-[:CALLS]->(f__overwrite_builder),
#   (f_build_preview)-[:CALLS]->(f_build_happy_path),
#   (f_build_preview_english)-[:CALLS]->(f_build_happy_path),
#   (f_build_prunable)-[:CALLS]->(f_base),
#   (f_build_prunable)-[:CALLS]->(f_lane),
#   (f_build_prunable)-[:USES]->(v_TARGET),
#   (f_build_rebase)-[:CALLS]->(f_base),
#   (f_build_rebase)-[:CALLS]->(f_lane),
#   (f_build_rebase)-[:USES]->(v_TARGET),
#   (f_build_rerun)-[:CALLS]->(f_build_conflict),
#   (f_build_rerun_interrupted)-[:CALLS]->(f_build_conflict),
#   (f_build_sequencer)-[:CALLS]->(f_base),
#   (f_build_sequencer)-[:CALLS]->(f_lane),
#   (f_build_skip_worktree)-[:CALLS]->(f_base),
#   (f_build_skip_worktree)-[:CALLS]->(f_lane),
#   (f_build_stale)-[:CALLS]->(f_base),
#   (f_build_stale)-[:CALLS]->(f_lane),
#   (f_build_submodule)-[:CALLS]->(f_base),
#   (f_build_submodule)-[:CALLS]->(f_lane),
#   (f_build_tag_shadow)-[:CALLS]->(f_base),
#   (f_build_tag_shadow)-[:CALLS]->(f_lane),
#   (f_build_tag_shadow)-[:USES]->(v_TARGET),
#   (f_build_target_main)-[:CALLS]->(f__gate_builder),
#   (f_build_target_missing)-[:CALLS]->(f__gate_builder),
#   (f_build_target_prunable)-[:CALLS]->(f__gate_builder),
#   (f_build_target_prunable)-[:USES]->(v_TARGET),
#   (f_build_target_tag_shadow)-[:CALLS]->(f_base),
#   (f_build_target_tag_shadow)-[:CALLS]->(f_lane),
#   (f_build_target_tag_shadow)-[:USES]->(v_TARGET),
#   (f_build_tip_moves)-[:CALLS]->(f_base),
#   (f_build_tip_moves)-[:CALLS]->(f_lane),
#   (f_build_unrelated)-[:CALLS]->(f_base),
#   (f_build_unrelated)-[:CALLS]->(f_lane),
#   (f_build_unrelated)-[:USES]->(v_TARGET),
#   (f_build_upstream)-[:CALLS]->(f_base),
#   (f_build_upstream)-[:CALLS]->(f_commit_on),
#   (f_build_upstream)-[:CALLS]->(f_lane),
#   (f_build_upstream_kept)-[:CALLS]->(f_base),
#   (f_build_upstream_kept)-[:CALLS]->(f_lane),
#   (f_build_validation)-[:CALLS]->(f__gate_builder),
#   (f_build_worktree_appeared)-[:CALLS]->(f_base),
#   (f_build_worktree_appeared)-[:CALLS]->(f_lane),
#   (f_check_appeared)-[:USES]->(v_TARGET),
#   (f_check_claude_session)-[:USES]->(v_TARGET),
#   (f_check_conflict)-[:USES]->(v_TARGET),
#   (f_check_conflict_predicted)-[:USES]->(v_TARGET),
#   (f_check_dependency)-[:USES]->(v_TARGET),
#   (f_check_dirty)-[:CALLS]->(f__blocked_oracle),
#   (f_check_from_target)-[:USES]->(v_TARGET),
#   (f_check_happy_path)-[:USES]->(v_TARGET),
#   (f_check_harness)-[:CALLS]->(f__blocked_oracle),
#   (f_check_ignored_discard)-[:USES]->(v_TARGET),
#   (f_check_ignored_kept)-[:USES]->(v_TARGET),
#   (f_check_locked)-[:CALLS]->(f__blocked_oracle),
#   (f_check_main_in_progress)-[:USES]->(v_TARGET),
#   (f_check_on_other)-[:USES]->(v_TARGET),
#   (f_check_ordering)-[:USES]->(v_TARGET),
#   (f_check_overwrite)-[:USES]->(v_TARGET),
#   (f_check_overwrite_case)-[:CALLS]->(f__overwrite_oracle),
#   (f_check_rebase)-[:USES]->(v_TARGET),
#   (f_check_rerun)-[:USES]->(v_TARGET),
#   (f_check_rerun_interrupted)-[:USES]->(v_TARGET),
#   (f_check_sequencer)-[:USES]->(v_TARGET),
#   (f_check_skip_worktree)-[:USES]->(v_TARGET),
#   (f_check_submodule)-[:USES]->(v_TARGET),
#   (f_check_tag_shadow)-[:USES]->(v_TARGET),
#   (f_check_target_tag_shadow)-[:USES]->(v_TARGET),
#   (f_check_unrelated)-[:USES]->(v_TARGET),
#   (f_check_upstream)-[:USES]->(v_TARGET),
#   (f_check_upstream_kept)-[:USES]->(v_TARGET),
#   (f_check_validation)-[:USES]->(v_TARGET),
#   (f_check_worktree_appeared)-[:USES]->(v_TARGET),
#   (f_flow_appeared)-[:CALLS]->(f_lane),
#   (f_flow_appeared)-[:CALLS]->(f_snapshot),
#   (f_flow_register)-[:USES]->(v_REGISTRY),
#   (f_flow_rerun)-[:CALLS]->(f_snapshot),
#   (f_flow_rerun_interrupted)-[:CALLS]->(f_snapshot),
#   (f_flow_stale)-[:CALLS]->(f_commit_on),
#   (f_flow_stale)-[:CALLS]->(f_snapshot),
#   (f_flow_tip_moves_hook)-[:CALLS]->(f_commit_on),
#   (f_flow_worktree_appeared)-[:CALLS]->(f_snapshot),
#   (f_lane)-[:USES]->(v_TARGET),
#   (f_oracle_register)-[:USES]->(v_REGISTRY),
#   (f_plan_case)-[:USES]->(v_TARGET),
#   (f_plan_conflict)-[:CALLS]->(f_stop_code),
#   (f_plan_conflict_predicted)-[:CALLS]->(f_stop_code),
#   (f_plan_happy_path)-[:USES]->(v_TARGET),
#   (f_plan_main_in_progress)-[:CALLS]->(f_stop_code),
#   (f_plan_oracle_register)-[:USES]->(v_REGISTRY),
#   (f_plan_overwrite)-[:CALLS]->(f_stop_code),
#   (f_plan_overwrite_case)-[:CALLS]->(f__overwrite_plan),
#   (f_plan_preview)-[:CALLS]->(f_plan_happy_path),
#   (f_plan_rerun)-[:CALLS]->(f_stop_code),
#   (f_plan_rerun_interrupted)-[:CALLS]->(f_stop_code),
#   (f_plan_stale)-[:CALLS]->(f_stop_code),
#   (f_plan_target_tag_shadow)-[:USES]->(v_TARGET),
#   (f_scenario_register)-[:USES]->(v_REGISTRY),
#   (f_snapshot)-[:CALLS]->(f_rel),
#   (file)-[:CALLS]->(f__other_command),
#   (file)-[:CALLS]->(f_flow),
#   (file)-[:CALLS]->(f_oracle),
#   (file)-[:CALLS]->(f_plan_oracle),
#   (file)-[:CALLS]->(f_scenario);
# ```
"""GitConverge scenarios: fixture builders, snapshots, and end-state oracles.

A scenario is a disposable repository topology plus a statement of what must be true afterwards. The oracles read only
Git state (refs, worktrees, files), so the same scenario judges the reference executor and an AI host alike.

Registration: `@scenario(id, title, ...)` on the builder, `@oracle(id)` on the end-state check, optional
`@plan_oracle(id)` for preview-level facts the reference executor exposes, optional `@flow(id)` for multi-step runs.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import gitlab
from gitlab import commit, git, init_repo, out

TARGET = "agent/release"
REGISTRY: dict[str, dict] = {}


def scenario(id: str, title: str, mode: str = "apply", discard: bool = False, claude: bool = True,
             platforms: tuple[str, ...] | None = None, report: tuple[str, ...] = (), lang: str | None = None,
             command: str = "GitConverge", cmd_args: str = "", inspects: bool | None = True):
    """Register a scenario builder. `mode` is 'preview' or 'apply'; `claude=False` keeps it reference-only.

    `report` lists words a real host's final answer must contain, and `lang` is the `--lang` value the runtime runner
    passes (None = the Chinese default); both are checked by the Claude runtime runner only. `command` selects another
    command to run (then `cmd_args` are its arguments); only GitConverge scenarios run on the reference executor.
    `inspects=False` marks a run that must stop before touching the repository (an argument error): the runtime runner
    then expects no git command instead of treating their absence as "never inspected". `inspects=None` means either is
    correct (a refusal the arguments alone can justify, such as a `main` target).
    """
    def register(builder):
        REGISTRY[id] = {"id": id, "title": title, "mode": mode, "discard": discard, "claude": claude,
                        "platforms": platforms, "report": report, "lang": lang, "command": command, "cmd_args": cmd_args,
                        "inspects": inspects,
                        "build": builder, "oracle": None,
                        "plan_oracle": None, "flow": None}
        return builder
    return register


def oracle(id: str):
    """Attach the end-state oracle: fn(ctx, before, after) -> list[(name, passed)]."""
    def register(function):
        REGISTRY[id]["oracle"] = function
        return function
    return register


def plan_oracle(id: str):
    """Attach preview-level checks: fn(ctx, result) -> list[(name, passed)] for the reference executor only."""
    def register(function):
        REGISTRY[id]["plan_oracle"] = function
        return function
    return register


def stop_code(result: dict, key: str = "report") -> str | None:
    """Stop code of a run inside a flow result; None when the run did not stop (tolerant so oracles report FAIL, not crash)."""
    stopped = (result.get(key) or {}).get("stopped")
    return stopped["code"] if stopped else None


def flow(id: str):
    """Attach a custom run: fn(ctx, ref, scen) -> dict with optional 'plan' / 'report' entries."""
    def register(function):
        REGISTRY[id]["flow"] = function
        return function
    return register


# ---------------------------------------------------------------- builders


def base(root: Path, origin: bool = True, gitignore: str | None = None) -> dict:
    """Repository on TARGET with a main branch, a bare origin, and a shared file; returns the scenario context."""
    repo = init_repo(root / "repo")
    if gitignore:
        commit(repo, ".gitignore", gitignore, "ignore rules")
    commit(repo, "shared.txt", "shared\n", "shared base")
    ctx = {"root": root, "repo": repo, "arg": TARGET, "origin": None, "harness_roots": (str(root / "harness"),),
           "watch": {}, "shas": {}}
    if origin:
        bare = gitlab.init_bare(root / "origin.git")
        git(repo, "remote", "add", "origin", str(bare), check=True)
        git(repo, "push", "-q", "-u", "origin", "main", check=True)
        ctx["origin"] = bare
    git(repo, "switch", "-q", "-c", TARGET, check=True)
    commit(repo, "release.txt", "release\n", "release base")
    ctx["shas"][TARGET] = out(repo, "rev-parse", f"refs/heads/{TARGET}")
    ctx["shas"]["main"] = out(repo, "rev-parse", "refs/heads/main")
    return ctx


def lane(ctx: dict, name: str, files: list[tuple[str, str]], worktree: str | None = None, start: str | None = None,
         push: bool = False) -> Path | None:
    """Create branch `name` at `start` (default TARGET) with one commit per file; keep a linked worktree if asked."""
    repo = ctx["repo"]
    where = ctx["root"] / (worktree or f"tmp-{name.replace('/', '-')}")
    git(repo, "worktree", "add", "-q", "-b", name, str(where), start or f"refs/heads/{TARGET}", check=True)
    for path, text in files:
        commit(where, path, text, f"{name}: {path}")
    if push:
        git(where, "push", "-q", "-u", "origin", name, check=True)
    if not worktree:
        git(repo, "worktree", "remove", str(where), check=True)
    ctx["shas"][name] = out(repo, "rev-parse", f"refs/heads/{name}")
    return where if worktree else None


def commit_on(ctx: dict, name: str, path: str, text: str) -> str:
    """Add a commit to a branch that is not checked out anywhere, through a temporary worktree."""
    where = ctx["root"] / f"tmp-on-{name.replace('/', '-')}"
    git(ctx["repo"], "worktree", "add", "-q", str(where), name, check=True)
    sha = commit(where, path, text, f"{name}: {path}")
    git(ctx["repo"], "worktree", "remove", str(where), check=True)
    ctx["shas"][name] = sha
    return sha


@scenario("happy-path", "Everything ahead is merged into the target and only main and the target remain")
def build_happy_path(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/c", [])  # contained: no commits beyond the target
    lane(ctx, "agent/a", [("a1.txt", "a1\n"), ("a2.txt", "a2\n")])
    ctx["wt_b"] = lane(ctx, "agent/b", [("b1.txt", "b1\n")], worktree="wt-b")
    commit_on(ctx, "main", "m.txt", "main ahead\n")
    ctx["shas"]["main"] = out(ctx["repo"], "rev-parse", "refs/heads/main")
    return ctx


@oracle("happy-path")
def check_happy_path(ctx, before, after):
    repo, shas = ctx["repo"], ctx["shas"]
    tree = set(out(repo, "ls-tree", "-r", "--name-only", f"refs/heads/{TARGET}").splitlines())
    merges = int(out(repo, "rev-list", "--merges", "--count", f"{shas[TARGET]}..refs/heads/{TARGET}"))
    return [("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("main was not moved", after["heads"].get("main") == shas["main"]),
            ("every source tip is contained in the target",
             all(gitlab.is_ancestor(repo, shas[name], f"refs/heads/{TARGET}") for name in shas)),
            ("files from every source are present", {"a1.txt", "a2.txt", "b1.txt", "m.txt"} <= tree),
            ("three real merge commits (main, a, b)", merges == 3),
            ("linked worktree of a deleted branch is gone", "wt-b" not in [Path(w["path"]).name for w in after["worktrees"]]),
            ("invoking worktree is on the target and clean",
             after["invoking_head"] == TARGET and all(w["status"] == "" for w in after["worktrees"] if w["exists"])),
            ("remote refs are untouched", after["origin"] == before["origin"]),
            ("no merge left in progress", not after["merge_head"])]


@plan_oracle("happy-path")
def plan_happy_path(ctx, result):
    plan = result["report"]["plan"] if "report" in result else result["plan"]
    states = {entry["name"]: entry["status"] for entry in plan["sources"]}
    return [("main merges first, then by descending unique commits", plan["merge_order"] == ["main", "agent/a", "agent/b"]),
            ("agent/c is classified CONTAINED", states.get("agent/c") == "CONTAINED"),
            ("expected final branches are main and the target", plan["final_branches"] == sorted(["main", TARGET])),
            ("the clean worktree is scheduled for removal", [Path(p).name for p in plan["removals"]] == ["wt-b"])]


@scenario("preview-readonly", "Without --apply nothing changes and the plan is reported", mode="preview")
def build_preview(root: Path) -> dict:
    return build_happy_path(root)


@oracle("preview-readonly")
def check_preview(ctx, before, after):
    return [("preview changes no ref, worktree, or file", before == after)]


@plan_oracle("preview-readonly")
def plan_preview(ctx, result):
    return plan_happy_path(ctx, result)


@scenario("preview-lang-english", "--lang English makes the preview reply English; the repository stays untouched",
          mode="preview", lang="English")
def build_preview_english(root: Path) -> dict:
    return build_happy_path(root)


oracle("preview-lang-english")(check_preview)
plan_oracle("preview-lang-english")(plan_preview)


def _other_command(id: str, title: str, command: str, cmd_args: str, lang: str | None, inspects: bool = True):
    """Register a read-only run of another command on the happy-path repository (Claude runtime only).

    `lang` is what the reply must be written in; `cmd_args` may already carry `--lang` (the runner then adds nothing).
    """
    scenario(id, title, mode="preview", lang=lang, command=command, cmd_args=cmd_args, inspects=inspects)(build_happy_path)
    oracle(id)(check_preview)


_other_command("recon-default-chinese", "GitRecon without --lang replies in Chinese", "GitRecon", "", None)
_other_command("recon-lang-english", "GitRecon --lang English replies in English", "GitRecon", "", "English")
_other_command("analyze-lang-english", "GitAnalyze with a target and --lang English replies in English", "GitAnalyze",
               "agent/a", "English")
_other_command("recommend-goal-lang", "--lang in the middle of GitRecommend's free-text goal is honored", "GitRecommend",
               "which branches --lang English should merge first", "English")
_other_command("recon-lang-missing", "--lang without a value is an error in Chinese; the command does not run", "GitRecon",
               "--lang", None, inspects=False)


def expects_plan(scen: dict) -> bool:
    """GitConverge runs that get past the gates report a plan naming every local branch; gate refusals do not."""
    return scen["command"] == "GitConverge" and scen["oracle"] is not _unchanged_oracle


@scenario("ordering-and-containment", "Larger sources merge first so a contained source needs no second merge")
def build_ordering(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/mid", [("m1.txt", "m1\n")])
    lane(ctx, "agent/big", [("g1.txt", "g1\n"), ("g2.txt", "g2\n")], start="refs/heads/agent/mid")
    lane(ctx, "agent/t2", [("t2a.txt", "x\n"), ("t2b.txt", "x\n")])
    lane(ctx, "agent/t1", [("t1a.txt", "x\n"), ("t1b.txt", "x\n")])
    return ctx


@oracle("ordering-and-containment")
def check_ordering(ctx, before, after):
    merges = int(out(ctx["repo"], "rev-list", "--merges", "--count", f"{ctx['shas'][TARGET]}..refs/heads/{TARGET}"))
    return [("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("three merges: big (which carries mid), t1, t2", merges == 3)]


@plan_oracle("ordering-and-containment")
def plan_ordering(ctx, result):
    plan = result["report"]["plan"] if "report" in result else result["plan"]
    return [("order is big, then the 2-commit tie by name, then mid",
             plan["merge_order"] == ["agent/big", "agent/t1", "agent/t2", "agent/mid"])]


@scenario("conflict-stops", "A conflicting source aborts its merge, stops the command, and deletes nothing")
def build_conflict(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/ok", [("ok.txt", "ok\n")])
    lane(ctx, "agent/x1", [("x1a.txt", "x\n"), ("shared.txt", "from x1\n")])
    lane(ctx, "agent/x2", [("shared.txt", "from x2\n")])
    return ctx


@oracle("conflict-stops")
def check_conflict(ctx, before, after):
    repo, shas = ctx["repo"], ctx["shas"]
    merged = [name for name in ("agent/x1", "agent/x2") if gitlab.is_ancestor(repo, shas[name], f"refs/heads/{TARGET}")]
    return [("no branch was deleted", set(before["heads"]) <= set(after["heads"])),
            ("no merge is left in progress", not after["merge_head"]),
            ("the working tree is clean", all(w["status"] == "" for w in after["worktrees"] if w["exists"])),
            ("the two conflicting sources are not both merged", len(merged) < 2),
            ("main was not moved", after["heads"].get("main") == shas["main"])]


@plan_oracle("conflict-stops")
def plan_conflict(ctx, result):
    plan = result["report"]["plan"]
    predicted = {entry["name"]: entry["predicted_conflict"] for entry in plan["sources"]}
    return [("the stop reason is MERGE_FAILED", stop_code(result) == "MERGE_FAILED"),
            ("per-source merge-tree cannot see the x1/x2 clash (documented blind spot)",
             predicted["agent/x1"] is False and predicted["agent/x2"] is False)]


@scenario("conflict-predicted", "A source that clashes with the target tip itself is predicted and then stops the apply")
def build_conflict_predicted(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/ok", [("ok.txt", "ok\n")])
    lane(ctx, "agent/clash", [("shared.txt", "from the lane\n")])
    commit(ctx["repo"], "shared.txt", "from the target\n", "target edits shared.txt")
    ctx["shas"][TARGET] = out(ctx["repo"], "rev-parse", f"refs/heads/{TARGET}")
    return ctx


@oracle("conflict-predicted")
def check_conflict_predicted(ctx, before, after):
    return [("no branch was deleted", set(before["heads"]) <= set(after["heads"])),
            ("no merge is left in progress", not after["merge_head"]),
            ("the clashing source is not merged",
             not gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/clash"], f"refs/heads/{TARGET}")),
            ("the working tree is clean", all(w["status"] == "" for w in after["worktrees"] if w["exists"]))]


@plan_oracle("conflict-predicted")
def plan_conflict_predicted(ctx, result):
    plan = result["report"]["plan"]
    predicted = {entry["name"]: entry["predicted_conflict"] for entry in plan["sources"]}
    return [("merge-tree predicts the clash against the target tip", predicted["agent/clash"] is True),
            ("the clean source is predicted clean", predicted["agent/ok"] is False),
            ("the stop reason is MERGE_FAILED", stop_code(result) == "MERGE_FAILED")]


@scenario("rerun-after-stop", "After the conflict is resolved by discarding the loser, a rerun finishes the job")
def build_rerun(root: Path) -> dict:
    return build_conflict(root)


@flow("rerun-after-stop")
def flow_rerun(ctx, ref, scen):
    first = ref.apply(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])
    git(ctx["repo"], "branch", "-D", "agent/x2", check=True)  # the user resolves the conflict by dropping x2
    ctx["baseline"] = snapshot(ctx)
    second = ref.apply(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])
    return {"report": second, "first": first}


@oracle("rerun-after-stop")
def check_rerun(ctx, before, after):
    return [("only main and the target remain after the rerun", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("x1 and ok are contained in the target",
             all(gitlab.is_ancestor(ctx["repo"], ctx["shas"][n], f"refs/heads/{TARGET}") for n in ("agent/x1", "agent/ok")))]


@plan_oracle("rerun-after-stop")
def plan_rerun(ctx, result):
    return [("the first run stopped on the conflict", stop_code(result, "first") == "MERGE_FAILED"),
            ("the rerun was not stopped", stop_code(result) is None)]


@scenario("unrelated-history", "An orphan branch is neither merged nor deleted and the rest still converges")
def build_unrelated(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    git(ctx["repo"], "switch", "-q", "--orphan", "gh-pages", check=True)
    commit(ctx["repo"], "site.txt", "site\n", "orphan root")
    git(ctx["repo"], "switch", "-q", TARGET, check=True)
    ctx["shas"]["gh-pages"] = out(ctx["repo"], "rev-parse", "refs/heads/gh-pages")
    return ctx


@oracle("unrelated-history")
def check_unrelated(ctx, before, after):
    return [("the orphan branch survives unchanged", after["heads"].get("gh-pages") == ctx["shas"]["gh-pages"]),
            ("the orphan history was not merged",
             not gitlab.is_ancestor(ctx["repo"], ctx["shas"]["gh-pages"], f"refs/heads/{TARGET}")),
            ("the ordinary source was merged and deleted",
             "agent/a" not in after["heads"] and gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/a"], f"refs/heads/{TARGET}")),
            ("branches are main, the target, and gh-pages", sorted(after["heads"]) == sorted(["main", TARGET, "gh-pages"]))]


@plan_oracle("unrelated-history")
def plan_unrelated(ctx, result):
    plan = result["report"]["plan"]
    states = {entry["name"]: entry["status"] for entry in plan["sources"]}
    return [("gh-pages is BLOCKED_UNRELATED_HISTORY", states["gh-pages"] == "BLOCKED_UNRELATED_HISTORY"),
            ("the residual list names gh-pages", [r["name"] for r in plan["residual"]] == ["gh-pages"])]


def _blocked_worktree_builder(root: Path, kind: str) -> dict:
    ctx = base(root)
    lane(ctx, "agent/ok", [("ok.txt", "ok\n")])
    ctx["wt"] = lane(ctx, "agent/held", [("held.txt", "held\n")], worktree="wt-held")
    if kind == "dirty":
        (ctx["wt"] / "held.txt").write_text("edited but uncommitted\n", encoding="utf-8")
        (ctx["wt"] / "scratch.txt").write_text("untracked\n", encoding="utf-8")
        ctx["watch"] = {"held": ctx["wt"] / "held.txt", "scratch": ctx["wt"] / "scratch.txt"}
    elif kind == "locked":
        git(ctx["repo"], "worktree", "lock", "--reason", "agent busy", str(ctx["wt"]), check=True)
    elif kind == "harness":
        git(ctx["repo"], "worktree", "remove", str(ctx["wt"]), check=True)
        (root / "harness").mkdir()
        ctx["wt"] = root / "harness" / "wt-held"
        git(ctx["repo"], "worktree", "add", "-q", str(ctx["wt"]), "agent/held", check=True)
    return ctx


def _blocked_oracle(ctx, before, after):
    wt = Path(ctx["wt"])
    return [("the held branch is kept", after["heads"].get("agent/held") == ctx["shas"]["agent/held"]),
            ("its worktree directory is kept", wt.is_dir()),
            ("its committed content was still merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/held"], f"refs/heads/{TARGET}")),
            ("the other source was merged and deleted", "agent/ok" not in after["heads"]),
            ("branches are main, the target, and the held branch", sorted(after["heads"]) == sorted(["main", TARGET, "agent/held"]))]


@scenario("dirty-source-worktree", "A dirty worktree keeps its branch; committed content is merged; edits survive")
def build_dirty(root: Path) -> dict:
    return _blocked_worktree_builder(root, "dirty")


@oracle("dirty-source-worktree")
def check_dirty(ctx, before, after):
    return _blocked_oracle(ctx, before, after) + [
        ("uncommitted edit is intact", after["files"]["held"] == "edited but uncommitted\n"),
        ("untracked file is intact", after["files"]["scratch"] == "untracked\n")]


@scenario("locked-source-worktree", "A locked worktree keeps its branch and stays locked")
def build_locked(root: Path) -> dict:
    return _blocked_worktree_builder(root, "locked")


@oracle("locked-source-worktree")
def check_locked(ctx, before, after):
    held = [w for w in after["worktrees"] if w["branch"] == "agent/held"]
    return _blocked_oracle(ctx, before, after) + [("the worktree is still locked", bool(held) and bool(held[0]["locked"]))]


@scenario("harness-owned-worktree", "A worktree under an agent-harness root is never removed", claude=False)
def build_harness(root: Path) -> dict:
    return _blocked_worktree_builder(root, "harness")


@oracle("harness-owned-worktree")
def check_harness(ctx, before, after):
    return _blocked_oracle(ctx, before, after)


@scenario("rebase-in-progress", "A branch mid-rebase in a worktree is neither merged nor deleted")
def build_rebase(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/ok", [("ok.txt", "ok\n")])
    ctx["wt"] = lane(ctx, "agent/topic", [("topic.txt", "topic side\n")], worktree="wt-topic")
    commit(ctx["repo"], "shared.txt", "target side\n", "target moves on")
    ctx["shas"][TARGET] = out(ctx["repo"], "rev-parse", f"refs/heads/{TARGET}")
    rebase = git(ctx["wt"], "rebase", "--exec", "false", f"refs/heads/{TARGET}")
    assert rebase.returncode != 0, "fixture needs a rebase that stopped"
    assert gitlab.git_paths(ctx["wt"], ("rebase-merge",))["rebase-merge"].is_dir(), "rebase-merge must exist"
    assert git(ctx["repo"], "merge-tree", "--write-tree", f"refs/heads/{TARGET}", ctx["shas"]["agent/topic"]).returncode == 0
    return ctx


@oracle("rebase-in-progress")
def check_rebase(ctx, before, after):
    wt = Path(ctx["wt"])
    return [("the topic branch tip is unchanged", after["heads"].get("agent/topic") == ctx["shas"]["agent/topic"]),
            ("its stale tip was not merged",
             not gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/topic"], f"refs/heads/{TARGET}")),
            ("the rebase is still in progress", gitlab.git_paths(wt, ("rebase-merge",))["rebase-merge"].is_dir()),
            ("the ordinary source was merged and deleted", "agent/ok" not in after["heads"]),
            ("branches are main, the target, and topic", sorted(after["heads"]) == sorted(["main", TARGET, "agent/topic"]))]


@plan_oracle("rebase-in-progress")
def plan_rebase(ctx, result):
    plan = result["report"]["plan"]
    states = {entry["name"]: entry["status"] for entry in plan["sources"]}
    return [("the rebasing branch is BLOCKED_IN_PROGRESS", states["agent/topic"] == "BLOCKED_IN_PROGRESS")]


def _ignored_worktree_builder(root: Path) -> dict:
    ctx = base(root, gitignore=".env\n")
    ctx["wt"] = lane(ctx, "agent/cfg", [("cfg.txt", "cfg\n")], worktree="wt-cfg")
    (ctx["wt"] / ".env").write_text("LOCAL_SECRET\n", encoding="utf-8")
    ctx["watch"] = {"env": ctx["wt"] / ".env"}
    return ctx


@scenario("ignored-files-kept", "A worktree holding ignored files is kept unless --discard-ignored is given")
def build_ignored_kept(root: Path) -> dict:
    return _ignored_worktree_builder(root)


@oracle("ignored-files-kept")
def check_ignored_kept(ctx, before, after):
    return [("the branch is kept", "agent/cfg" in after["heads"]),
            ("the worktree and its ignored file are intact", after["files"]["env"] == "LOCAL_SECRET\n"),
            ("its committed content was merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/cfg"], f"refs/heads/{TARGET}"))]


@scenario("ignored-files-discard", "--discard-ignored removes the worktree and its ignored files", discard=True)
def build_ignored_discard(root: Path) -> dict:
    return _ignored_worktree_builder(root)


@oracle("ignored-files-discard")
def check_ignored_discard(ctx, before, after):
    return [("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("the worktree directory is gone", not Path(ctx["wt"]).exists())]


@scenario("ignored-overwrite-merge", "A merge that would overwrite an ignored local file stops before merging")
def build_overwrite(root: Path) -> dict:
    ctx = base(root, gitignore=".env\n")
    lane(ctx, "agent/envsrc", [(".env", "FROM_SOURCE\n")])
    (ctx["repo"] / ".env").write_text("LOCAL_SECRET\n", encoding="utf-8")
    ctx["watch"] = {"env": ctx["repo"] / ".env"}
    return ctx


@oracle("ignored-overwrite-merge")
def check_overwrite(ctx, before, after):
    return [("the local ignored file is untouched", after["files"]["env"] == "LOCAL_SECRET\n"),
            ("the source branch is kept", "agent/envsrc" in after["heads"]),
            ("the target did not move", after["heads"].get(TARGET) == ctx["shas"][TARGET])]


@plan_oracle("ignored-overwrite-merge")
def plan_overwrite(ctx, result):
    return [("the stop reason is BLOCKED_IGNORED_OVERWRITE", stop_code(result) == "BLOCKED_IGNORED_OVERWRITE")]


@scenario("tag-shadow", "A tag named like a branch never stands in for the branch")
def build_tag_shadow(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "feat", [("feat.txt", "feat\n")])
    git(ctx["repo"], "tag", "feat", f"refs/heads/{TARGET}", check=True)
    return ctx


@oracle("tag-shadow")
def check_tag_shadow(ctx, before, after):
    return [("the branch content was merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["feat"], f"refs/heads/{TARGET}")),
            ("the branch was deleted and only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("the tag is untouched", "feat" in after["tags"])]


@plan_oracle("tag-shadow")
def plan_tag_shadow(ctx, result):
    plan = result["report"]["plan"]
    return [("the collision is reported", plan["notes"]["tag_collisions"] == ["feat"])]


def _gate_builder(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    return ctx


def _unchanged_oracle(ctx, before, after):
    return [("a stopped command changes nothing", before == after)]


@scenario("case-variant-target", "A differently-cased target is rejected, even with --apply", report=(TARGET,))
def build_case(root: Path) -> dict:
    ctx = _gate_builder(root)
    ctx["arg"] = "Agent/Release"
    return ctx


oracle("case-variant-target")(_unchanged_oracle)


@plan_oracle("case-variant-target")
def plan_case(ctx, result):
    gates = result["report"]["plan"]["gates"]
    return [("the gate is TARGET_CASE_MISMATCH and suggests the real name",
             bool(gates) and gates[0]["code"] == "TARGET_CASE_MISMATCH" and TARGET in gates[0]["message"])]


@scenario("target-is-main", "main is never a target", inspects=None)
def build_target_main(root: Path) -> dict:
    ctx = _gate_builder(root)
    ctx["arg"] = "main"
    return ctx


oracle("target-is-main")(_unchanged_oracle)


@scenario("target-missing", "A missing target is rejected")
def build_target_missing(root: Path) -> dict:
    ctx = _gate_builder(root)
    ctx["arg"] = "agent/nope"
    return ctx


oracle("target-missing")(_unchanged_oracle)


@scenario("invoking-detached", "A detached invoking worktree is a gate")
def build_detached(root: Path) -> dict:
    ctx = _gate_builder(root)
    git(ctx["repo"], "switch", "-q", "--detach", check=True)
    return ctx


oracle("invoking-detached")(_unchanged_oracle)


@scenario("invoking-dirty", "A dirty invoking worktree is a gate")
def build_invoking_dirty(root: Path) -> dict:
    ctx = _gate_builder(root)
    (ctx["repo"] / "stray.txt").write_text("untracked\n", encoding="utf-8")
    ctx["watch"] = {"stray": ctx["repo"] / "stray.txt"}
    return ctx


oracle("invoking-dirty")(_unchanged_oracle)


@scenario("target-checked-out-elsewhere", "A target held by another worktree is a gate: run from that worktree",
          report=("wt-target",))
def build_elsewhere(root: Path) -> dict:
    ctx = _gate_builder(root)
    git(ctx["repo"], "switch", "-q", "main", check=True)
    ctx["wt_target"] = root / "wt-target"
    git(ctx["repo"], "worktree", "add", "-q", str(ctx["wt_target"]), TARGET, check=True)
    return ctx


oracle("target-checked-out-elsewhere")(_unchanged_oracle)


@scenario("target-prunable-entry", "A target held only by a missing-directory worktree entry is a gate")
def build_target_prunable(root: Path) -> dict:
    ctx = _gate_builder(root)
    git(ctx["repo"], "switch", "-q", "main", check=True)
    git(ctx["repo"], "worktree", "add", "-q", str(root / "wt-gone"), TARGET, check=True)
    gitlab.rmtree(root / "wt-gone")
    return ctx


oracle("target-prunable-entry")(_unchanged_oracle)


@plan_oracle("target-prunable-entry")
def plan_target_prunable(ctx, result):
    gates = result["report"]["plan"]["gates"]
    return [("the gate is TARGET_PRUNABLE_ENTRY", bool(gates) and gates[0]["code"] == "TARGET_PRUNABLE_ENTRY")]


@scenario("main-prunable-entry", "A main held only by a missing-directory worktree entry is a gate")
def build_main_prunable(root: Path) -> dict:
    ctx = _gate_builder(root)
    git(ctx["repo"], "worktree", "add", "-q", str(root / "wt-main"), "main", check=True)
    gitlab.rmtree(root / "wt-main")
    return ctx


oracle("main-prunable-entry")(_unchanged_oracle)


@plan_oracle("main-prunable-entry")
def plan_main_prunable(ctx, result):
    gates = result["report"]["plan"]["gates"]
    return [("the gate is MAIN_PRUNABLE_ENTRY", bool(gates) and gates[0]["code"] == "MAIN_PRUNABLE_ENTRY")]


@scenario("run-from-target-worktree", "Running from the worktree that holds the target works and leaves main's worktree alone")
def build_from_target(root: Path) -> dict:
    ctx = build_elsewhere(root)
    ctx["main_repo"] = ctx["repo"]
    ctx["repo"] = ctx["wt_target"]
    return ctx


@oracle("run-from-target-worktree")
def check_from_target(ctx, before, after):
    return [("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("the main worktree still stands on main",
             out(ctx["main_repo"], "symbolic-ref", "--short", "HEAD") == "main"),
            ("the source was merged", gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/a"], f"refs/heads/{TARGET}"))]


@scenario("invoking-on-other-branch", "The invoking worktree moves to the target and its old branch is merged and deleted")
def build_on_other(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/current", [("cur.txt", "cur\n")])
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    git(ctx["repo"], "switch", "-q", "agent/current", check=True)
    return ctx


@oracle("invoking-on-other-branch")
def check_on_other(ctx, before, after):
    return [("the invoking worktree is now on the target", after["invoking_head"] == TARGET),
            ("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("the former current branch was merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/current"], f"refs/heads/{TARGET}"))]


@scenario("upstream-behind", "A branch whose upstream lags is merged and deleted without -D; the remote keeps its copy")
def build_upstream(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/pushed", [("p1.txt", "p1\n")], push=True)
    commit_on(ctx, "agent/pushed", "p2.txt", "p2 after push\n")
    return ctx


@oracle("upstream-behind")
def check_upstream(ctx, before, after):
    return [("the lagging branch is gone and only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("its latest commit is contained in the target",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/pushed"], f"refs/heads/{TARGET}")),
            ("the remote still has its own copy", any("agent/pushed" in line for line in (after["origin"] or [])))]


@scenario("detached-and-prunable", "A detached worktree is left alone and a missing branch worktree is removed by path only")
def build_prunable(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/gone", [("gone.txt", "gone\n")], worktree="wt-gone")
    gitlab.rmtree(root / "wt-gone")
    git(ctx["repo"], "worktree", "add", "-q", "--detach", str(root / "wt-det"), f"refs/heads/{TARGET}", check=True)
    ctx["detached_sha"] = commit(root / "wt-det", "det.txt", "only on a detached head\n", "detached work")
    gitlab.rmtree(root / "wt-det")
    return ctx


@oracle("detached-and-prunable")
def check_prunable(ctx, before, after):
    heads = [w["head"] for w in after["worktrees"]]
    return [("the missing-directory branch was merged and deleted", "agent/gone" not in after["heads"]),
            ("the detached worktree entry is still listed", ctx["detached_sha"] in heads),
            ("the detached commit still exists", git(ctx["repo"], "cat-file", "-e", ctx["detached_sha"]).returncode == 0),
            ("the gone branch's worktree entry was removed", all(Path(w["path"]).name != "wt-gone" for w in after["worktrees"]))]


@scenario("stale-preview", "A source that moves after the preview stops the apply", claude=False)
def build_stale(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    lane(ctx, "agent/b", [("b1.txt", "b\n")])
    return ctx


@flow("stale-preview")
def flow_stale(ctx, ref, scen):
    preview = ref.survey(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])
    commit_on(ctx, "agent/b", "b2.txt", "b moved after the preview\n")
    ctx["baseline"] = snapshot(ctx)
    return {"report": ref.apply(ctx["repo"], ctx["arg"], earlier_preview=preview, harness_roots=ctx["harness_roots"]),
            "plan": preview}


@oracle("stale-preview")
def check_stale(ctx, before, after):
    return [("nothing changed after the stale-preview stop", before == after)]


@plan_oracle("stale-preview")
def plan_stale(ctx, result):
    return [("the stop reason is STALE_PREVIEW", stop_code(result) == "STALE_PREVIEW")]


@scenario("appeared-after-preview", "A branch created after the preview is left untouched", claude=False)
def build_appeared(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    return ctx


@flow("appeared-after-preview")
def flow_appeared(ctx, ref, scen):
    preview = ref.survey(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])
    lane(ctx, "agent/late", [("late.txt", "late\n")])
    ctx["baseline"] = snapshot(ctx)
    return {"report": ref.apply(ctx["repo"], ctx["arg"], earlier_preview=preview, harness_roots=ctx["harness_roots"]),
            "plan": preview}


@oracle("appeared-after-preview")
def check_appeared(ctx, before, after):
    return [("the late branch still exists unmerged", after["heads"].get("agent/late") == ctx["shas"]["agent/late"]),
            ("the late branch was not merged",
             not gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/late"], f"refs/heads/{TARGET}")),
            ("the previewed source was merged and deleted", "agent/a" not in after["heads"])]


@scenario("tip-moves-mid-run", "A tip that moves between merge and delete is skipped and its new commit survives", claude=False)
def build_tip_moves(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    lane(ctx, "agent/b", [("b1.txt", "b\n")])
    return ctx


@flow("tip-moves-mid-run")
def flow_tip_moves(ctx, ref, scen):
    def hook(event: str, name: str) -> None:
        if event == "before_delete" and name == "agent/b":
            ctx["moved_sha"] = commit_on(ctx, "agent/b", "b2.txt", "b gains a commit during the run\n")
    return {"report": ref.apply(ctx["repo"], ctx["arg"], hook=hook, harness_roots=ctx["harness_roots"])}


@oracle("tip-moves-mid-run")
def check_tip_moves(ctx, before, after):
    return [("the moved branch keeps its new commit", after["heads"].get("agent/b") == ctx["moved_sha"]),
            ("the unmoved branch was deleted", "agent/a" not in after["heads"])]


@scenario("validation-fails", "A failing post-merge check keeps the merges and deletes nothing", claude=False)
def build_validation(root: Path) -> dict:
    return _gate_builder(root)


@flow("validation-fails")
def flow_validation(ctx, ref, scen):
    return {"report": ref.apply(ctx["repo"], ctx["arg"], validate=lambda repo: (False, "tests failed"),
                                harness_roots=ctx["harness_roots"])}


@oracle("validation-fails")
def check_validation(ctx, before, after):
    return [("the merge is kept",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/a"], f"refs/heads/{TARGET}")),
            ("no branch was deleted", set(before["heads"]) <= set(after["heads"]))]


@scenario("worktree-remove-failure", "A worktree another process is using is not half-deleted, and its branch is kept",
          claude=False, platforms=("win32",))
def build_busy(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    ctx["wt"] = lane(ctx, "agent/busy", [("busy.txt", "busy\n")], worktree="wt-busy")
    return ctx


@flow("worktree-remove-failure")
def flow_busy(ctx, ref, scen):
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(ctx["wt"]))
    try:
        return {"report": ref.apply(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])}
    finally:
        holder.kill()
        holder.wait()


@oracle("worktree-remove-failure")
def check_busy(ctx, before, after):
    return [("the branch whose worktree could not be removed is kept", "agent/busy" in after["heads"]),
            ("the unrelated source was deleted", "agent/a" not in after["heads"])]


@plan_oracle("worktree-remove-failure")
def plan_busy(ctx, result):
    reasons = [item["reason"] for item in result["report"]["skipped"] if item["branch"] == "agent/busy"]
    return [("the skip names the failed worktree removal", bool(reasons) and "worktree remove failed" in reasons[0])]


@scenario("upstream-of-kept", "A branch that a kept branch tracks is merged but kept")
def build_upstream_kept(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/x", [("x1.txt", "x\n")])
    git(ctx["repo"], "branch", "--set-upstream-to=agent/x", "main", check=True)
    return ctx


@oracle("upstream-of-kept")
def check_upstream_kept(ctx, before, after):
    return [("the tracked branch is kept", "agent/x" in after["heads"]),
            ("its content was merged", gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/x"], f"refs/heads/{TARGET}"))]


@scenario("submodule-worktree", "A worktree with an initialized submodule is kept because git refuses to remove it")
def build_submodule(root: Path) -> dict:
    ctx = base(root)
    subsrc = init_repo(root / "subsrc")
    ctx["wt"] = lane(ctx, "agent/sub", [("sub.txt", "sub\n")], worktree="wt-sub")
    added = git(ctx["wt"], "-c", "protocol.file.allow=always", "submodule", "add", str(subsrc), "libs/sub")
    assert added.returncode == 0, added.stderr
    git(ctx["wt"], "commit", "-q", "-m", "agent/sub: add submodule", check=True)
    ctx["shas"]["agent/sub"] = out(ctx["repo"], "rev-parse", "refs/heads/agent/sub")
    return ctx


@oracle("submodule-worktree")
def check_submodule(ctx, before, after):
    return [("the branch is kept", "agent/sub" in after["heads"]),
            ("the worktree is kept", Path(ctx["wt"]).is_dir()),
            ("its committed content was merged", gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/sub"], f"refs/heads/{TARGET}"))]


# ---------------------------------------------------------------- review-driven scenarios


@scenario("target-tag-shadow", "A tag named like the target never stands in for the target branch")
def build_target_tag_shadow(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/feat", [("feat.txt", "feat\n")], push=True)
    git(ctx["repo"], "tag", TARGET, ctx["shas"]["agent/feat"], check=True)
    return ctx


@oracle("target-tag-shadow")
def check_target_tag_shadow(ctx, before, after):
    return [("the source's commits reached the target branch",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/feat"], f"refs/heads/{TARGET}")),
            ("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET])),
            ("the tag is untouched", TARGET in after["tags"])]


@plan_oracle("target-tag-shadow")
def plan_target_tag_shadow(ctx, result):
    plan = result["report"]["plan"]
    states = {entry["name"]: entry["status"] for entry in plan["sources"]}
    return [("the source is MERGE, not CONTAINED", states.get("agent/feat") == "MERGE"),
            ("the collision with the target is reported", TARGET in plan["notes"]["tag_collisions"])]


def _overwrite_builder(root: Path, gitignore: str, source_files: list[tuple[str, str]], local: dict[str, str]) -> dict:
    ctx = base(root, gitignore=gitignore)
    lane(ctx, "agent/src", source_files)
    ctx["watch"] = {}
    for relative, content in local.items():
        target = ctx["repo"] / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        ctx["watch"][relative] = target
    return ctx


def _overwrite_oracle(ctx, before, after):
    return [("every ignored local file is intact", after["files"] == before["files"]),
            ("the source branch is kept", "agent/src" in after["heads"]),
            ("the target did not move", after["heads"].get(TARGET) == ctx["shas"][TARGET])]


def _overwrite_plan(ctx, result):
    return [("the stop reason is BLOCKED_IGNORED_OVERWRITE", stop_code(result) == "BLOCKED_IGNORED_OVERWRITE")]


@scenario("ignored-overwrite-case", "A source path that differs from an ignored local file only in case stops the merge")
def build_overwrite_case(root: Path) -> dict:
    ctx = _overwrite_builder(root, ".env\n", [(".ENV", "FROM_SOURCE\n")], {".env": "LOCAL_SECRET\n"})
    ctx["ignorecase"] = git(ctx["repo"], "config", "--get", "--bool", "core.ignorecase").stdout.strip() == "true"
    return ctx


@oracle("ignored-overwrite-case")
def check_overwrite_case(ctx, before, after):
    if not ctx["ignorecase"]:
        return [("case-sensitive filesystem: .env is intact", after["files"] == before["files"])]
    return _overwrite_oracle(ctx, before, after)


@plan_oracle("ignored-overwrite-case")
def plan_overwrite_case(ctx, result):
    return _overwrite_plan(ctx, result) if ctx["ignorecase"] else [("case-sensitive filesystem: no stop needed", True)]


@scenario("ignored-overwrite-dir-file", "A source file named like an ignored local directory stops the merge")
def build_overwrite_dir_file(root: Path) -> dict:
    return _overwrite_builder(root, "logs/\n", [("logs", "a file now\n")], {"logs/app.log": "precious log\n"})


oracle("ignored-overwrite-dir-file")(_overwrite_oracle)
plan_oracle("ignored-overwrite-dir-file")(_overwrite_plan)


@scenario("ignored-overwrite-file-dir", "A source directory named like an ignored local file stops the merge")
def build_overwrite_file_dir(root: Path) -> dict:
    return _overwrite_builder(root, "cache\n", [("cache/x.txt", "inside\n")], {"cache": "precious cache\n"})


oracle("ignored-overwrite-file-dir")(_overwrite_oracle)
plan_oracle("ignored-overwrite-file-dir")(_overwrite_plan)


@scenario("sequencer-in-progress", "A paused cherry-pick sequence keeps its branch: neither merged nor deleted")
def build_sequencer(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/donor", [("shared.txt", "donor side\n"), ("d2.txt", "second pick\n")])
    ctx["wt"] = lane(ctx, "agent/topic", [("shared.txt", "topic side\n")], worktree="wt-topic")
    donor = ctx["shas"]["agent/donor"]
    picked = git(ctx["wt"], "cherry-pick", f"{donor}~1", donor)
    assert picked.returncode != 0, "the first pick must conflict"
    (ctx["wt"] / "shared.txt").write_text("resolved\n", encoding="utf-8")
    git(ctx["wt"], "add", "shared.txt", check=True)
    git(ctx["wt"], "commit", "-q", "--no-edit", check=True)
    assert gitlab.git_paths(ctx["wt"], ("sequencer",))["sequencer"].is_dir(), "sequencer must remain"
    ctx["shas"]["agent/topic"] = out(ctx["repo"], "rev-parse", "refs/heads/agent/topic")
    return ctx


@oracle("sequencer-in-progress")
def check_sequencer(ctx, before, after):
    wt = Path(ctx["wt"])
    return [("the topic branch is kept at its tip", after["heads"].get("agent/topic") == ctx["shas"]["agent/topic"]),
            ("its half-finished tip was not merged",
             not gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/topic"], f"refs/heads/{TARGET}")),
            ("the worktree and its sequencer survive", wt.is_dir() and
             gitlab.git_paths(wt, ("sequencer",))["sequencer"].is_dir())]


@plan_oracle("sequencer-in-progress")
def plan_sequencer(ctx, result):
    states = {entry["name"]: entry["status"] for entry in result["report"]["plan"]["sources"]}
    return [("the topic branch is BLOCKED_IN_PROGRESS", states.get("agent/topic") == "BLOCKED_IN_PROGRESS")]


@scenario("skip-worktree-edits", "Edits hidden by skip-worktree keep the worktree and branch")
def build_skip_worktree(root: Path) -> dict:
    ctx = base(root)
    ctx["wt"] = lane(ctx, "agent/cfg", [("conf.txt", "default\n")], worktree="wt-cfg")
    git(ctx["wt"], "update-index", "--skip-worktree", "conf.txt", check=True)
    (ctx["wt"] / "conf.txt").write_text("local override\n", encoding="utf-8")
    assert out(ctx["wt"], "status", "--porcelain=v1", "--untracked-files=all") == "", "status must look clean"
    ctx["watch"] = {"conf": ctx["wt"] / "conf.txt"}
    return ctx


@oracle("skip-worktree-edits")
def check_skip_worktree(ctx, before, after):
    return [("the hidden edit survives", after["files"]["conf"] == "local override\n"),
            ("the branch is kept", "agent/cfg" in after["heads"]),
            ("its committed content was merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/cfg"], f"refs/heads/{TARGET}"))]


@scenario("claude-session-worktree", "A Claude Code session worktree under <repo>/.claude/worktrees is never removed")
def build_claude_session(root: Path) -> dict:
    ctx = base(root)
    exclude = gitlab.git_paths(ctx["repo"], ("info/exclude",))["info/exclude"]
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a", encoding="utf-8") as handle:
        handle.write(".claude/\n")
    lane(ctx, "agent/ok", [("ok.txt", "ok\n")])
    ctx["wt"] = ctx["repo"] / ".claude" / "worktrees" / "session"
    git(ctx["repo"], "worktree", "add", "-q", "-b", "worktree-session", str(ctx["wt"]), f"refs/heads/{TARGET}", check=True)
    ctx["shas"]["worktree-session"] = commit(ctx["wt"], "session.txt", "session work\n", "session work")
    return ctx


@oracle("claude-session-worktree")
def check_claude_session(ctx, before, after):
    return [("the session branch is kept", "worktree-session" in after["heads"]),
            ("the session worktree is kept", Path(ctx["wt"]).is_dir()),
            ("its committed content was merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["worktree-session"], f"refs/heads/{TARGET}")),
            ("the ordinary source was merged and deleted", "agent/ok" not in after["heads"])]


@scenario("dependency-of-remaining-lane", "A branch that a kept lane tracks is merged but kept")
def build_dependency(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    ctx["wt"] = lane(ctx, "agent/b", [("b1.txt", "b\n")], worktree="wt-b", start="refs/heads/agent/a")
    git(ctx["repo"], "branch", "--set-upstream-to=agent/a", "agent/b", check=True)
    (ctx["wt"] / "wip.txt").write_text("work in progress\n", encoding="utf-8")
    return ctx


@oracle("dependency-of-remaining-lane")
def check_dependency(ctx, before, after):
    return [("the dirty lane is kept", "agent/b" in after["heads"]),
            ("the branch it tracks is kept", "agent/a" in after["heads"]),
            ("both were merged", all(gitlab.is_ancestor(ctx["repo"], ctx["shas"][n], f"refs/heads/{TARGET}")
                                     for n in ("agent/a", "agent/b"))),
            ("the lane's upstream still resolves",
             git(ctx["wt"], "rev-parse", "--verify", "-q", "@{upstream}").returncode == 0)]


@scenario("main-in-progress", "main mid-merge in the main worktree is neither merged nor a crash")
def build_main_in_progress(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    lane(ctx, "agent/clash", [("shared.txt", "from clash\n")], start="refs/heads/main")
    git(ctx["repo"], "switch", "-q", "main", check=True)
    commit(ctx["repo"], "shared.txt", "from main\n", "main edits shared.txt")
    ctx["shas"]["main"] = out(ctx["repo"], "rev-parse", "refs/heads/main")
    merged = git(ctx["repo"], "merge", "--no-edit", "refs/heads/agent/clash")
    assert merged.returncode != 0, "main must stop mid-merge"
    ctx["main_repo"] = ctx["repo"]
    ctx["repo"] = root / "wt-target"
    git(ctx["main_repo"], "worktree", "add", "-q", str(ctx["repo"]), TARGET, check=True)
    return ctx


@oracle("main-in-progress")
def check_main_in_progress(ctx, before, after):
    return [("the main worktree is still mid-merge",
             git(ctx["main_repo"], "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0),
            ("main's commit was not merged into the target",
             not gitlab.is_ancestor(ctx["repo"], ctx["shas"]["main"], f"refs/heads/{TARGET}")),
            ("the ordinary source was merged and deleted", "agent/a" not in after["heads"])]


@plan_oracle("main-in-progress")
def plan_main_in_progress(ctx, result):
    states = {entry["name"]: entry["status"] for entry in result["report"]["plan"]["sources"]}
    return [("main is BLOCKED_IN_PROGRESS", states.get("main") == "BLOCKED_IN_PROGRESS"),
            ("the run did not stop", stop_code(result) is None)]


@scenario("worktree-appeared-after-preview", "A worktree added after the preview keeps its branch", claude=False)
def build_worktree_appeared(root: Path) -> dict:
    ctx = base(root)
    lane(ctx, "agent/a", [("a1.txt", "a\n")])
    return ctx


@flow("worktree-appeared-after-preview")
def flow_worktree_appeared(ctx, ref, scen):
    preview = ref.survey(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])
    ctx["wt"] = ctx["root"] / "wt-late"
    git(ctx["repo"], "worktree", "add", "-q", str(ctx["wt"]), "agent/a", check=True)
    ctx["baseline"] = snapshot(ctx)
    return {"report": ref.apply(ctx["repo"], ctx["arg"], earlier_preview=preview, harness_roots=ctx["harness_roots"]),
            "plan": preview}


@oracle("worktree-appeared-after-preview")
def check_worktree_appeared(ctx, before, after):
    return [("the branch is kept", "agent/a" in after["heads"]),
            ("its new worktree is kept", Path(ctx["wt"]).is_dir()),
            ("its previewed tip was still merged",
             gitlab.is_ancestor(ctx["repo"], ctx["shas"]["agent/a"], f"refs/heads/{TARGET}"))]


@scenario("rerun-after-interrupted-apply", "A rerun in the same conversation finishes an interrupted apply", claude=False)
def build_rerun_interrupted(root: Path) -> dict:
    return build_conflict(root)


@flow("rerun-after-interrupted-apply")
def flow_rerun_interrupted(ctx, ref, scen):
    preview = ref.survey(ctx["repo"], ctx["arg"], harness_roots=ctx["harness_roots"])
    first = ref.apply(ctx["repo"], ctx["arg"], earlier_preview=preview, harness_roots=ctx["harness_roots"])
    git(ctx["repo"], "branch", "-D", "agent/x2", check=True)  # the user resolves the conflict by dropping x2
    ctx["baseline"] = snapshot(ctx)
    second = ref.apply(ctx["repo"], ctx["arg"], earlier_preview=first["plan"], harness_roots=ctx["harness_roots"])
    return {"report": second, "first": first}


@oracle("rerun-after-interrupted-apply")
def check_rerun_interrupted(ctx, before, after):
    return [("only main and the target remain", sorted(after["heads"]) == sorted(["main", TARGET]))]


@plan_oracle("rerun-after-interrupted-apply")
def plan_rerun_interrupted(ctx, result):
    return [("the first run stopped on the conflict", stop_code(result, "first") == "MERGE_FAILED"),
            ("the rerun is not treated as a stale preview", stop_code(result) is None)]


def invariants(ctx: dict, before: dict, after: dict) -> list[tuple[str, bool]]:
    """Hard stops every scenario must respect: main, tags, the remote, and remote-tracking refs never change."""
    return [("invariant: main did not move", after["heads"].get("main") == before["heads"].get("main")),
            ("invariant: tags unchanged", after["tag_refs"] == before["tag_refs"]),
            ("invariant: remote unchanged", after["origin"] == before["origin"]),
            ("invariant: remote-tracking refs unchanged", after["remote_refs"] == before["remote_refs"]),
            ("invariant: no merge left in progress", not after["merge_head"])]


# ---------------------------------------------------------------- snapshots


def rel(ctx: dict, path: str | Path) -> str:
    """Path relative to the fixture root, in POSIX form, so evidence does not depend on the temp directory."""
    try:
        return Path(os.path.relpath(os.path.realpath(str(path)), os.path.realpath(str(ctx["root"])))).as_posix()
    except ValueError:
        return str(path)


def snapshot(ctx: dict) -> dict:
    """Everything an oracle compares: refs, worktrees with status, remote refs, HEAD, merge state, watched files."""
    repo = ctx["repo"]
    trees = []
    for item in gitlab.worktrees(repo):
        exists = Path(item["path"]).is_dir()
        trees.append({"path": rel(ctx, item["path"]), "branch": item["branch"], "detached": item["detached"],
                      "locked": bool(item["locked"]), "prunable": bool(item["prunable"]), "head": item["head"],
                      "exists": exists,
                      "status": out(item["path"], "status", "--porcelain=v1", "--untracked-files=all") if exists else None})
    origin = None
    if ctx.get("origin"):
        origin = out(ctx["origin"], "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    head = git(repo, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip() or "(detached)"
    merge_head = git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
    files = {label: (Path(path).read_text(encoding="utf-8") if Path(path).is_file() else None)
             for label, path in ctx.get("watch", {}).items()}
    tag_refs = out(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/tags").splitlines()
    remote_refs = out(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes").splitlines()
    return {"heads": gitlab.refs(repo), "tags": sorted(out(repo, "tag", "--list").splitlines()), "tag_refs": tag_refs,
            "remote_refs": remote_refs,
            "worktrees": sorted(trees, key=lambda entry: entry["path"]), "origin": origin, "invoking_head": head,
            "merge_head": merge_head, "files": files}
