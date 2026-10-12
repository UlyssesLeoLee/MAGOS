"""Hermes native plugin entry for MAGOS (``hermes plugins install UlyssesLeoLee/MAGOS``).

Registers every ``skills/<name>/SKILL.md`` under the plugin namespace, so Hermes offers them as ``/magos:git-recon``
and so on, the same names the Claude Code and Codex plugins use. Without this file Hermes would load the package
through its portable ``plugin.json`` and name the commands ``/agent-plugin-magos-<digest>:git-recon``. The skills
are read-only instructions; this module registers nothing else.
"""

from pathlib import Path


def register(ctx):
    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.is_file():
            ctx.register_skill(child.name, skill_md)
