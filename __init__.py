"""Hermes native plugin entry for MAGOS (``hermes plugins install UlyssesLeoLee/MAGOS``).

Registers every ``skills/<name>/SKILL.md`` under the plugin namespace, so Hermes offers them as ``/magos:git-recon``
and so on, the same names the Claude Code and Codex plugins use. Without this file Hermes would load the package
through its portable ``plugin.json`` and name the commands ``/agent-plugin-magos-<digest>:git-recon``.

Hermes lists every registered plugin skill in the system prompt's ``<available_skills>`` index, with the
``description`` passed here; it does not read a plugin skill's SKILL.md description, so without one the model sees
only the bare name. The index is how the model decides to load a skill on its own, so the orchestrator gets a
trigger-rich line, and the commands that write to a repository get a line telling the model to leave them to the
user. The skills are read-only instructions; this module registers nothing else.
"""

from pathlib import Path

INDEX_DESCRIPTIONS = {
    "git-orchestrator": (
        "Multi-agent / multi-worktree Git coordination: lane planning, branch and worktree safety, merge and "
        "integration order, cleanup, branch strategy (分支策略, ブランチ戦略). Load it when agents overwrite each "
        "other's work, branches or worktrees sprawl, or it is unclear what is safe to merge or delete."
    ),
    "git-recon": "Read-only snapshot of branches, worktrees and risks. Use /magos:git-recon when the user asks for it.",
    "git-analyze": "Read-only analysis of one branch or worktree. Use /magos:git-analyze when the user asks for it.",
    "git-recommend": "Read-only next-step advice for the repository. Use /magos:git-recommend when the user asks.",
    "git-integrate": "Writes to the repository: run only when the user types /magos:git-integrate. Never load it yourself.",
    "git-cleanup": "Deletes branches and worktrees: run only when the user types /magos:git-cleanup. Never load it yourself.",
    "git-converge": "Merges and deletes branches: run only when the user types /magos:git-converge. Never load it yourself.",
    "git-sweep": "Merges, deletes and pushes remote deletions: run only when the user types /magos:git-sweep. Never load it yourself.",
    "git-plan": "Registers lane claims and, with --converge --apply, merges the lanes: run only when the user types /magos:git-plan. Never load it yourself.",
}


def register(ctx):
    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.is_file():
            ctx.register_skill(child.name, skill_md, description=INDEX_DESCRIPTIONS.get(child.name, ""))
