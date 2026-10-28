"""Hermes native plugin entry for MAGOS (``hermes plugins install UlyssesLeoLee/MAGOS``).

Registers every ``skills/<name>/SKILL.md`` under the plugin namespace, so Hermes offers them as ``/magos:git-recon``
and so on, the same names the Claude Code and Codex plugins use. Without this file Hermes would load the package
through its portable ``plugin.json`` and name the commands ``/agent-plugin-magos-<digest>:git-recon``.

Hermes lists every registered plugin skill in the system prompt's ``<available_skills>`` index, with the
``description`` passed here; it does not read a plugin skill's SKILL.md description, so without one the model sees
only the bare name. The index is how the model decides to load a skill on its own, so the orchestrator gets a
trigger-rich line, and the commands that write to a repository get a line telling the model to leave them to the
user. The skills are read-only instructions.

The module also runs the MAGOS guard on every call of Hermes's ``terminal`` tool, through two ``pre_tool_call``
callbacks. The verdict runs this plugin's own ``scripts/magos_guard.py`` (``hook hermes pre-tool --hermes-gate``) and
turns its answer into a Hermes directive: nothing, a block, or a modify that hands Hermes the command the guard rebuilt
with a one-time approval token. For a user-only guard command the approval callback then hands Hermes the guard's
question, so Hermes asks the user in its own approval prompt before the rewritten command runs. A guard that fails
blocks the call. MAGOS_GUARD=off in Hermes's environment, or ``hermes plugins disable magos``, turns the guard off.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
import threading
import time
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

GUARD = Path(__file__).parent / "scripts" / "magos_guard.py"  # the guard this plugin ships, never a copy elsewhere
GUARD_TOOLS = ("terminal",)  # the Hermes tool that runs shell commands
GUARD_LIMIT_S = 25  # the guard's run limit, below Hermes's 30 s limit for a pre_tool_call callback
KEPT_S = 120  # a verdict's mark older than this is dropped
_KEPT = {}  # call key -> (time.monotonic() of the verdict, the approve directive or None)
_KEPT_LOCK = threading.Lock()
_GUARD_WORD = re.compile(r"magos_guard", re.I)
_QUOTING = re.compile(r"[\\`^'\"]")  # removed before _GUARD_WORD is looked for, so magos_gu""ard still names the guard

_TEXT = {
    "en": {
        "block": "MAGOS guard (Hermes plugin): %s; nothing ran. To stop the guard: MAGOS_GUARD=off in Hermes's environment, "
                 "or hermes plugins disable magos.",
        "timeout": "the guard did not answer within %d s",
        "exit": "the guard ended with exit code %d",
        "no_json": "the guard printed no JSON object",
        "shape": "the guard printed an answer of no known shape",
        "start": "the guard could not be started (%s)",
        "failed": "the plugin failed (%s)",
        "unprepared": "the approval of this guard command was not prepared by the plugin's verdict",
    },
    "zh": {
        "block": "MAGOS 守卫（Hermes 插件）：%s；没有运行任何命令。要关闭守卫：在 Hermes 的环境中设置 MAGOS_GUARD=off，"
                 "或运行 hermes plugins disable magos。",
        "timeout": "守卫在 %d s 内没有回答",
        "exit": "守卫以退出码 %d 结束",
        "no_json": "守卫没有输出 JSON 对象",
        "shape": "守卫的回答格式无法识别",
        "start": "无法启动守卫（%s）",
        "failed": "插件出错（%s）",
        "unprepared": "插件的判定没有为这条守卫命令准备审批",
    },
}


def _text(key, *values):
    """A text in Chinese unless MAGOS_LANG is en, as the guard itself chooses."""
    texts = _TEXT["en" if os.environ.get("MAGOS_LANG") == "en" else "zh"]
    return texts[key] % values if values else texts[key]


def _block(cause):
    """A block directive whose message names the cause and the two off switches."""
    return {"action": "block", "message": _text("block", cause)}


def _off():
    """MAGOS_GUARD=off (any case, surrounding blanks ignored) in Hermes's environment turns both callbacks off."""
    return (os.environ.get("MAGOS_GUARD") or "").strip().lower() == "off"


def _key(kw, args):
    """The call a mark belongs to: Hermes hands both callbacks of one call the same keyword arguments and the same args."""
    command = args.get("command") if isinstance(args, dict) else None
    return (str(kw.get("session_id") or ""), str(kw.get("tool_call_id") or ""), str(kw.get("turn_id") or ""),
            command if isinstance(command, str) else "")


def _prune(now):
    """Drop the marks older than KEPT_S; the caller holds _KEPT_LOCK."""
    for key in [key for key, (at, _approve) in _KEPT.items() if now - at > KEPT_S]:
        del _KEPT[key]


def gate():
    """What Hermes's approval gate would do with an approve directive of this call, read in Hermes's process.

    absent: a plugin-host process (whose probes would read another process), a Hermes without the plugin approve
    directive (request_tool_approval without rule_key, or _PreToolCallDirective without a rule_key field), or an import
    or probe that raised. bypass: the gate would answer without a human (yolo in any form, approvals.mode off, or no
    interactive CLI, gateway or ask bridge). ask otherwise. These names are Hermes internals: read, never patched."""
    if os.environ.get("HERMES_PLUGIN_HOST_PROCESS"):
        return "absent"
    try:
        from hermes_cli import plugins as hermes_plugins
        from tools import approval, approval_context
        if "rule_key" not in inspect.signature(approval.request_tool_approval).parameters:
            return "absent"
        if "rule_key" not in hermes_plugins._PreToolCallDirective.__dataclass_fields__:
            return "absent"
        if approval._yolo_active() or approval_context._get_approval_mode() == "off":
            return "bypass"
        _callback, cli, gateway, ask = approval._presence()
        return "ask" if (cli or gateway or ask) else "bypass"
    except Exception:  # noqa: BLE001 - any doubt about the gate keeps the user-only command in the user's terminal
        return "absent"


def _payload(tool_name, args, kw):
    """The call in the shape of a Hermes shell-hook payload, which the guard's Hermes hook reads."""
    try:
        cwd = os.getcwd()  # Hermes's own directory, as in a shell-hook payload: not the directory the command runs in
    except OSError:
        cwd = ""
    return {"hook_event_name": "pre_tool_call", "tool_name": tool_name,
            "tool_input": args if isinstance(args, dict) else None,
            "session_id": kw.get("session_id") or kw.get("parent_session_id") or "",
            "tool_use_id": kw.get("tool_call_id") or "", "cwd": cwd,
            "extra": {k: v for k, v in kw.items() if k not in ("session_id", "parent_session_id")}}


def _env():
    """The guard's environment: Hermes's own, with HERMES_HOME set to the home Hermes runs with; None (inherit) when
    Hermes names none."""
    try:
        from hermes_constants import get_hermes_home
        home = str(get_hermes_home())
    except Exception:  # noqa: BLE001 - outside Hermes, or an older Hermes: the inherited environment
        return None
    env = dict(os.environ)
    env["HERMES_HOME"] = home
    return env


def _run_guard(payload, gate_value):
    """The one place that starts a process: this plugin's guard, as an argument list without a shell."""
    return subprocess.run([sys.executable, "-X", "utf8", "-B", str(GUARD), "hook", "hermes", "pre-tool", "--hermes-gate", gate_value],
                          input=json.dumps(payload, ensure_ascii=True, default=str, skipkeys=True).encode("ascii"),
                          capture_output=True, timeout=GUARD_LIMIT_S, env=_env(),
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)


def _answer(answer):
    """The guard's answer -> (the verdict's directive, the approve directive to keep or None)."""
    if answer == {}:
        return None, None
    if isinstance(answer, dict) and answer.get("decision") == "block" and isinstance(answer.get("reason"), str) \
            and answer["reason"]:
        return {"action": "block", "message": answer["reason"]}, None
    hermes = answer.get("hermesApproval") if isinstance(answer, dict) else None
    modify = hermes.get("modify") if isinstance(hermes, dict) else None
    if not (isinstance(modify, dict) and isinstance(modify.get("command"), str) and modify["command"]):
        return _block(_text("shape")), None
    ask = hermes.get("approve")
    if ask is None:  # auto-safe: the rewritten command runs without a question
        return {"action": "modify", "args": {"command": modify["command"]}}, None
    if not (isinstance(ask, dict) and isinstance(ask.get("message"), str) and ask["message"]
            and isinstance(ask.get("rule_key"), str) and ask["rule_key"].startswith("magos:")):
        return _block(_text("shape")), None
    return ({"action": "modify", "args": {"command": modify["command"]}},
            {"action": "approve", "message": ask["message"], "rule_key": ask["rule_key"]})


def verdict(tool_name="", args=None, **kw):
    """The first pre_tool_call callback: run the guard on a terminal call and return its directive."""
    if tool_name not in GUARD_TOOLS or _off():
        return None
    approve = None
    try:
        done = _run_guard(_payload(tool_name, args, kw), gate())
        if done.returncode != 0:
            directive = _block(_text("exit", done.returncode))
        else:
            try:
                answer = json.loads(done.stdout.decode("utf-8"))
            except ValueError:  # also a stdout that is not UTF-8
                directive = _block(_text("no_json"))
            else:
                directive, approve = _answer(answer)
    except subprocess.TimeoutExpired:
        directive = _block(_text("timeout", GUARD_LIMIT_S))
    except OSError as err:
        directive = _block(_text("start", err))
    except Exception as err:  # noqa: BLE001 - nothing raises out of the callback: an unexpected failure blocks the call
        directive = _block(_text("failed", "%s: %s" % (type(err).__name__, err)))
    with _KEPT_LOCK:  # a mark for every call answered here: a question keeps its approve directive, every other answer None
        now = time.monotonic()
        _prune(now)
        _KEPT[_key(kw, args)] = (now, approve)
    return directive


def approval(tool_name="", args=None, **kw):
    """The second pre_tool_call callback: the approve directive the verdict kept for this very call, once."""
    if tool_name not in GUARD_TOOLS or _off():
        return None
    with _KEPT_LOCK:
        _prune(time.monotonic())
        mark = _KEPT.pop(_key(kw, args), None)
    if mark is not None:
        return mark[1]
    command = args.get("command") if isinstance(args, dict) else None
    if isinstance(command, str) and _GUARD_WORD.search(_QUOTING.sub("", command)):
        return _block(_text("unprepared"))  # a question the verdict could not hand over never turns into a modify without one
    return None


def register(ctx):
    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.is_file():
            ctx.register_skill(child.name, skill_md, description=INDEX_DESCRIPTIONS.get(child.name, ""))
    ctx.register_hook("pre_tool_call", verdict)
    ctx.register_hook("pre_tool_call", approval)
