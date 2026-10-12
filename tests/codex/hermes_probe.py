"""Deterministic Hermes probe for a MAGOS fixture; no model is called.

Run with Hermes's own Python from inside a trusted fixture whose project-local
package lives at .agents/skills/MAGOS:

    <hermes venv python> hermes_probe.py <hermes-agent dir> <git-command name> <user instruction>

It prints one line "MAGOS_PROBE_RESULT <json>" describing how Hermes itself
registers, scans and renders the skills. The rendered message is the same text
Hermes's interactive CLI sends for a slash command (cli.py uses
build_skill_invocation_message), so the runner can pass it to `hermes -z`.
"""

import json
import sys
from pathlib import Path

hermes_agent, instruction = sys.argv[1], sys.argv[3]
command_key = "/" + sys.argv[2].lstrip("/")  # a leading "/" would be mangled by MSYS shells
sys.path.insert(0, hermes_agent)

from agent import skill_utils  # noqa: E402
from agent.skill_commands import build_skill_invocation_message, scan_skill_commands  # noqa: E402
from tools.skills_guard import scan_skill  # noqa: E402
from tools.skills_tool import skill_view  # noqa: E402

package = (Path.cwd() / ".agents" / "skills" / "MAGOS").resolve()
expected = ["/multi-agent-git-orchestrator", "/git-recon", "/git-analyze", "/git-recommend",
            "/git-integrate", "/git-cleanup", "/git-converge", "/git-sweep"]
commands = scan_skill_commands()
registered = {}
for key in expected:
    info = commands.get(key)
    registered[key] = None if info is None else {
        "skill_dir": info["skill_dir"],
        "from_fixture": Path(info["skill_dir"]).resolve().is_relative_to(package),
        "description": info["description"],
    }

source = getattr(skill_utils, "_PROJECT_SCAN_SOURCE", "community")
guard = {}
for directory in [package, *sorted(package.glob("skills/*"))]:
    result = scan_skill(directory, source=source)
    guard[directory.relative_to(package).as_posix() or "."] = {
        "verdict": result.verdict,
        "findings": sorted({getattr(finding, "pattern_id", None) or getattr(finding, "category", "?")
                            for finding in result.findings}),
    }

message = build_skill_invocation_message(command_key, instruction) or ""
adapter_dir = package / "skills" / command_key.lstrip("/")
root_view = json.loads(skill_view("multi-agent-git-orchestrator", file_path="references/commands.md"))
dotdot_view = json.loads(skill_view(command_key.lstrip("/"), file_path="../../SKILL.md"))

result = {
    "project_skill_tier_trusted": bool(skill_utils.get_project_skills_dirs()),
    "registered": registered,
    "guard": guard,
    "guard_source": source,
    "invocation": {
        "command": command_key,
        "found": bool(message),
        "has_skill_directory": f"[Skill directory: {adapter_dir}]" in message,
        "has_user_instruction": instruction in message,
    },
    "root_skill_reference_view": {"success": root_view.get("success", "content" in root_view),
                                  "error": root_view.get("error")},
    "dotdot_view": {"success": dotdot_view.get("success", "content" in dotdot_view),
                    "error": dotdot_view.get("error")},
    "message": message,
}
print("MAGOS_PROBE_RESULT " + json.dumps(result, ensure_ascii=False))
