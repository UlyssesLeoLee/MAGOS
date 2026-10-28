#!/usr/bin/env python3
"""MAGOS lane guard: a lane's files are planned before the lane exists; creating a lane that overlaps another lane is denied.

One stdlib-only file (Python >= 3.9): CLI, PreToolUse hook entry for Claude Code / Codex / Hermes, the MCP approval server the host starts
(mcp), and the sh body of the git reference-transaction backstop. check / list / set-show never write, hook writes only approval and denial
records and mcp only approval records; plan / release / override / arm / disarm / install and the set
commands set-plan / set-update / set-release write only the claim store and the set records under <git-common-dir>/magos and the files they print.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import io
import json
import math
import os
import queue
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None
    import fcntl

if sys.platform == "win32":  # CreateProcess searches the working directory before PATH unless this is set: a git.exe planted there never runs
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"

GUARD_VERSION = "1.0.8"  # the one version constant of the guard; equals the package version (plugin.json, .claude-plugin/plugin.json, plugin.yaml, SKILL.md)
CLAIM_FORMAT = 1  # the claim file format this guard reads and writes (line `v=`); a claim of a newer format is never misread
SET_FORMAT = 1  # the set record format this guard reads and writes (field `v`); a record of a newer format is never misread
GS = "**"
BUDGET_S, MAX_CLAIMANTS, MAX_REMOTES, MAX_ENTRIES, LOCK_S, MAX_TEXT = 18.0, 120, 300, 200, 30.0, 200000
MAX_DIR = 4096  # the longest directory spelling the detector resolves: a longer one is an unknown directory
# The tools the host hooks inspect.  The Claude matchers (hooks/hooks.json, host_snippet) are built from this one table by claude_matcher().
HOOKED_TOOLS = {
    "shell": ("Bash", "PowerShell", "Monitor"),  # Claude Code tools that run a shell command
    "host_shell": ("terminal", "shell", "local_shell"),  # the shell tools of Hermes and Codex
    "isolation": ("Agent", "Task", "Workflow"),  # create a worktree when called with isolation: worktree
    "strict": ("EnterWorktree",),  # creates a worktree itself (the strict hook group)
    "mcp_session": ("start_session", "worktree", "branch", "hand_off_to_session"),  # MCP tools (name contains) that start work in a worktree
    # MCP tools (name contains) that may run a command: the matcher routes them; the guard inspects every MCP tool whose command is a string
    "mcp_shell": ("run_in_terminal", "terminal", "shell", "exec_command", "execute_command", "start_process", "command", "run_command", "exec", "execute",
                  "process", "bash", "powershell", "cmd"),
}
SHELL_TOOLS = HOOKED_TOOLS["shell"] + HOOKED_TOOLS["host_shell"]
EXIT = {"OK": 0, "OVERRIDDEN": 0, "CONFLICT": 10, "NO_MANIFEST": 10, "UNPLANNABLE": 10, "UNPARSEABLE": 10, "PROTECTED": 10, "UNKNOWN": 11,
        "INVALID_MANIFEST": 12, "LOCK_TIMEOUT": 13, "LANE_EXISTS": 14, "BRANCH_EXISTS": 15, "BLOCKED": 16, "CONSOLE_REQUIRED": 17, "ARM_REFUSED": 3,
        "DOWNGRADE_REFUSED": 18, "STALE": 19, "SET_EXISTS": 20, "SET_UNKNOWN": 21, "OUT_OF_LANE": 22, "SET_NEWER_FORMAT": 23, "INVALID_SPEC": 24,
        "APPROVAL_UNKNOWN": 25, "APPROVAL_EXPIRED": 26, "APPROVAL_USED": 27, "APPROVAL_MISMATCH": 28}
APPROVAL_LEVELS = ("terminal", "prompt", "auto-safe")  # magos.approval; unset is prompt, any other value terminal
APPROVAL_S, APPROVAL_GRACE_S, DENIAL_S = 120, 600, 3600  # token lifetime; how long an expired or used record names its cause; a denial record's lifetime
# Codex approval (MCP approval server): the protocol version answered to a client that names no date; the longest message line; the longest
# string argument; the longest output text of a result; how long the server waits for the click (Codex does not count that wait against its
# tool timeout; the token's own 120 s start at the mint, after the click)
MCP_PROTOCOL, MCP_LINE, MCP_FIELD, MCP_TEXT, MCP_CLICK_S = "2025-06-18", 1048576, 4096, 8000, 120
MCP_SERVER, MCP_TOOL = "magos", "magos_approve"  # the server name of the host configuration and its one tool
HERMES_GATES = ("ask", "bypass", "absent")  # --hermes-gate: what the MAGOS Hermes plugin found about Hermes's approval gate
HERMES_TIMEOUT_S, HERMES_LIFE_MIN_S, HERMES_LIFE_MAX_S, HERMES_LIFE_MARGIN_S = 300, 120, 900, 30  # a Hermes record that asks lives min(max(T, 120), 900) + 30 s
MARK = "MAGOS lane guard"  # identifies the reference-transaction hook this file wrote
HOOK_DEADLINE = None  # set for the duration of a hook call: every git call of that call shares one budget

# ---------------------------------------------------------------- messages (zh default, en)
M = {
    "conflict": ("MAGOS 拒绝创建「{b}」：计划修改的文件与下列已有分支/工作树重叠。已有分支与工作树不受任何影响；没有创建任何东西。",
                 "MAGOS DENIES creating '{b}': the planned files overlap the existing branches/worktrees below. Existing lanes are untouched; nothing was created."),
    "unknown": ("MAGOS 拒绝创建「{b}」：存在无法分析的对象，按“未知即不安全”处理。没有创建任何东西。",
                "MAGOS DENIES creating '{b}': something could not be analysed ('unknown is not safe'). Nothing was created."),
    "nomanifest": ("MAGOS 拒绝创建「{b}」：创建前必须先登记计划修改的文件清单（manifest），目前没有登记。已有分支与工作树不受影响；没有创建任何东西。",
                   "MAGOS DENIES creating '{b}': a planned file manifest must be registered BEFORE creation and none is. Existing lanes are untouched; nothing was created."),
    "how_plan": ("请先单独执行（不要与创建命令写在同一条命令里）：\n  {cmd} plan --branch {b} --paths '<文件或 glob>' '<另一个>'（glob 必须加引号）\n登记通过后再重新执行创建命令；只预览请用 check。",
                 "Run this first, as its own tool call (not chained with the creation command):\n  {cmd} plan --branch {b} --paths '<file or glob>' '<another>' (quote globs)\nThen re-run the creation command; use check to preview only."),
    "unparse_git": ("MAGOS 拒绝：无法确定这条命令创建的分支名（{why}），无法核对 manifest。请改写为分支名是字面量的 git 命令。没有创建任何东西。",
                    "MAGOS DENIES: cannot tell which branch this creates ({why}), so no manifest can be matched. Use a git command with a literal branch name. Nothing was created."),
    "unparse_redirect": ("MAGOS 拒绝：仓库被 --git-dir/GIT_DIR 重定向且无法解析；请改用 git -C <仓库>。没有创建任何东西。",
                         "MAGOS DENIES: the repository is redirected by --git-dir/GIT_DIR and cannot be resolved; use git -C <repo>. Nothing was created."),
    "undecided": ("MAGOS guard warning: 无法判断是否存在其他 lane（{why}）；{then}",
                  "MAGOS guard warning: could not decide whether another lane exists ({why}); {then}"),
    "undecided_auto": ("由工具自己命名的创建被拒绝。", "the auto-named creation is denied."),
    "undecided_claims": ("仓库有有效登记，按登记核对这次创建。", "the repository holds an open claim, so the creation is judged."),
    "undecided_allow": ("AUTO 模式放行这个只建分支的创建。", "auto mode allows this branch-only creation."),
    "undecided_auto_allow": ("没有其他 lane 的迹象（有效登记、其他本地分支或其他工作树），放行这个由工具自己命名的创建。",
                             "no claim, other local branch or other worktree exists, so the auto-named creation is allowed."),
    "unplannable": ("MAGOS 拒绝：{why} 由工具自己命名分支或工作树，无法事先登记。请先登记分支 worktree-<名称>（plan --branch worktree-<名称>），再调用 EnterWorktree name=<名称>；"
                    "或自己 git worktree add 后在其中工作；必须用这个工具时，请用户执行 git config --local magos.guard off。没有创建任何东西。",
                    "MAGOS DENIES: {why} names the branch or worktree itself, so it cannot be planned. Plan the branch worktree-<name> first (plan --branch worktree-<name>), "
                    "then call EnterWorktree name=<name>; or run git worktree add yourself and work there; if this tool is required, ask the user to run "
                    "git config --local magos.guard off. Nothing was created."),
    "protected": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。这类操作只能由用户在自己的终端里执行。",
                  "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). Only the user may do this, in their own terminal."),
    "path_mismatch": ("MAGOS 拒绝创建「{b}」：登记的工作树路径是 {want}，而这条命令创建在 {got}。请用登记时的路径，或重新 plan --amend。没有创建任何东西。",
                      "MAGOS DENIES creating '{b}': the registered worktree path is {want} but this command creates {got}. Use the registered path or plan --amend. Nothing was created."),
    "item": ("{i}. 分支 {b}  工作树 {w}{p}", "{i}. branch {b}  worktree {w}{p}"),
    "planned": ("  （仅登记，尚未创建）", "  (planned only, not created yet)"),
    "ev": ("   [{k}] {n} 个文件：{f}；命中你的条目：{m}", "   [{k}] {n} file(s): {f}; matched by your entries: {m}"),
    "ev_decl": ("   [{k}] 对方声明：{t}；与你的条目 {m} 重叠", "   [{k}] their entries: {t}; overlap your entries: {m}"),
    "k_committed": ("已提交", "committed"),
    "k_uncommitted": ("未提交（暂存/未暂存/未跟踪）", "uncommitted (staged/unstaged/untracked)"),
    "k_declared": ("账本中已声明", "declared in the ledger"),
    "options": ("可选处理：① 缩小或拆分 manifest；② 等对方合入 {target} 后再创建；③ 对方若已合并或已放弃，用 {cmd} release --branch <对方分支> 释放它的登记（未合并的工作不会被释放）；"
                "④ 仅在用户明确同意后，把 {cmd} override --fingerprint {fp} --reason \"<用户原话>\" 单独作为一条命令执行：在 Claude Code 中由用户在对话框里批准；"
                "在 Codex 中调用 MCP 工具 magos_approve（subcommand 为 override，并给出指纹、理由和仓库），由用户在 Codex 的对话框里批准；"
                "在装有 MAGOS Hermes 插件的 Hermes 中由用户在 Hermes 的审批提示中批准；没有这条途径时（Codex 中没有 MCP 服务器 magos，Hermes 中没有该插件）"
                "或 magos.approval 为 terminal 时，由用户本人在自己的终端里运行；"
                "覆盖只通过 plan 生效，之后必须重新 plan（re-plan）。",
                "Options: (1) shrink or split the manifest; (2) wait until they are merged into {target}; (3) if the other lane is merged or abandoned, release its claim with "
                "{cmd} release --branch <their branch> (unmerged work is never released); (4) only with the user's explicit consent, "
                "run {cmd} override --fingerprint {fp} --reason \"<user's words>\" as a command of its own: in Claude Code the user approves it in Claude Code's dialog; "
                "in Codex call the MCP tool magos_approve (subcommand override, the fingerprint, the reason and the repository) and the user approves it in "
                "Codex's dialog; in Hermes with the MAGOS Hermes plugin the user approves it in Hermes's approval prompt; where no such route exists "
                "(Codex without the MCP server magos, Hermes without the plugin) or with magos.approval terminal, the USER runs it in their own "
                "terminal; the override takes effect only through plan, so a re-plan is required."),
    "newer_only": ("只有能读取该格式的 MAGOS 才能处理这份登记：请升级本守卫（doctor 显示版本，install 刷新副本），或用写入它的那个 MAGOS 执行这条命令。",
                   "Only a MAGOS that reads that format can act on this claim: upgrade this guard (doctor shows its version, install refreshes the copy), "
                   "or run this command with the MAGOS that wrote it."),
    "ok_plan": ("MAGOS：已登记「{b}」的 manifest（{n} 条）。现在可以创建，例如：{example}",
                "MAGOS: registered the manifest of '{b}' ({n} entries). You may now create it, e.g.: {example}"),
    "ok_check": ("MAGOS：预览通过，没有发现重叠（未登记）。", "MAGOS: preview passed, no overlap found (nothing registered)."),
    "lane_exists": ("MAGOS：「{b}」已有一份不同的有效登记。用 --amend 修改，或先 release。", "MAGOS: '{b}' already has a different open claim. Change it with --amend, or release it first."),
    "branch_exists": ("MAGOS：分支「{b}」已经存在且没有有效登记，不能事后补登记。请换一个新分支名。", "MAGOS: branch '{b}' already exists without a claim; it cannot be registered after the fact. Choose a new branch name."),
    "lock": ("MAGOS：{s} 秒内没有拿到清单锁，未登记也未创建。请稍后重试。", "MAGOS: could not take the claim lock within {s} s; nothing registered. Retry."),
    "invalid": ("MAGOS：manifest 无效，未登记：\n{errors}", "MAGOS: the manifest is invalid, nothing registered:\n{errors}"),
    "blocked": ("MAGOS：拒绝 release：分支仍有未合并的工作，或其工作树有未提交的修改。", "MAGOS: release refused: the branch has unmerged work or its worktree has uncommitted changes."),
    "blocked_newer": ("MAGOS：拒绝 release：{why}", "MAGOS: release refused: {why}"),
    "blocked_format": ("MAGOS：拒绝 release：登记文件 {f} 的格式行无法识别（可能由更新版本的 MAGOS 写入）；请升级本守卫，或由用户检查该文件。",
                       "MAGOS: release refused: the claim file {f} has a format line this guard cannot read (a newer MAGOS may have written it); "
                       "upgrade this guard, or let the user inspect the file."),
    "blocked_alias": ("MAGOS：拒绝 release：「{b}」的登记存放在 {f}，不在它自己的路径上；请用户手工检查后删除。",
                      "MAGOS: release refused: the claim of '{b}' is stored in {f}, not at its own path; the user must inspect and remove it by hand."),
    "released": ("MAGOS：已释放「{b}」的登记。", "MAGOS: released the claim of '{b}'."),
    "overridden": ("MAGOS：已记录用户覆盖（指纹 {fp}，1 小时内有效）。", "MAGOS: recorded the user's override (fingerprint {fp}, valid for 1 hour)."),
    "need_tty": ("MAGOS：这条用户专属命令需要真实终端（当前标准输入不是控制台），或者由用户在 Claude Code 的对话框中批准，或者在 Codex 中通过 MCP 工具 "
                 "magos_approve 在 Codex 的对话框中批准，或者在 Hermes 的审批提示中批准（守卫会自己加上 --approval）。",
                 "MAGOS: this user-only command needs a real terminal (stdin is not a console), or the user's approval in Claude Code's dialog, in Codex "
                 "in Codex's dialog through the MCP tool magos_approve, or in Hermes in Hermes's approval prompt (the guard then adds --approval itself)."),
    # ---- approval (1.0.7): the Claude Code hook's answer to a user-only command, its dialog text and the command's token errors
    "protected_shape": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。只有用户能批准它：在 Claude Code 中，请把这条守卫命令单独作为一次 Bash 或 PowerShell "
                        "调用执行，前后不加任何内容，也不带 --approval：{cmd} <子命令> <选项>；用户随后在 Claude Code 自己的对话框中点击批准。否则由用户在自己的终端里执行。",
                        "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). Only the user approves it: in Claude Code, run this guard "
                        "command as a Bash or PowerShell call of its own, with nothing before or after it and without --approval: {cmd} <subcommand> <options>; "
                        "the user then approves it in Claude Code's own dialog. Otherwise the user runs it in their own terminal."),
    "protected_level": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。本仓库的 magos.approval 是 terminal（或是守卫不认识的值，按 terminal 处理）："
                        "这类操作只能由用户在自己的终端里执行。",
                        "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). This repository's magos.approval is terminal "
                        "(or a value the guard does not know, which counts as terminal): only the user may do this, in their own terminal."),
    "approval_given": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}），并且带有 --approval。批准令牌从不由 agent 提供：用户在 Claude Code 的对话框中批准时，"
                       "守卫会自己加上它。请去掉 --approval 后重新执行。",
                       "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}) and carries --approval. An agent never supplies an "
                       "approval token: the guard adds it itself when the user approves the command in Claude Code's dialog. Run the command without --approval."),
    "approval_unrecorded": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。批准记录无法写入（{err}），因此只能由用户在自己的终端里执行。",
                            "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). The approval could not be recorded ({err}), "
                            "so only the user may run it, in their own terminal."),
    "approval_ask": ("MAGOS：批准用户专属的守卫命令 {sub} 吗？{what}你的点击就是批准：下面的命令带有一次性批准令牌，120 秒内有效。",
                     "MAGOS: approve the user-only guard command {sub}? {what} Your click is the approval: the command below carries a one-time approval token, "
                     "valid for 120 s."),
    "approval_auto": ("MAGOS：{sub} 无需点击即执行（magos.approval 为 auto-safe：它只增加保护或复制守卫，不削弱任何东西）。{what}",
                      "MAGOS: {sub} runs without a click (magos.approval is auto-safe: it adds protection or copies the guard and weakens nothing). {what}"),
    "approval_what_override": ("它在 {repo} 中为拒绝 {fp} 记录一次覆盖，1 小时内有效，使该 lane 的下一次 plan 不顾重叠而通过；{denied}。agent 写的理由：{reason}。",
                               "It records an override of the denial {fp} in {repo}, valid for one hour, so that the next plan of that lane goes through despite the "
                               "overlap; {denied}. Reason written by the agent: {reason}."),
    "approval_denied": ("放行的 lane：{lane}（目标 {target}）；冲突的分支：{branches}", "the lane it lets through: {lane} (target {target}); conflicting branches: {branches}"),
    "approval_what_arm": ("它在 {repo} 中安装 git 后备钩子（reference-transaction 钩子和 ARMED，并把 gc.packRefs 与 maintenance.pack-refs.enabled 设为 false）{dry}。",
                          "It installs the git backstop in {repo} (the reference-transaction hook and ARMED; gc.packRefs and maintenance.pack-refs.enabled set to "
                          "false){dry}."),
    "approval_what_disarm": ("它从 {repo} 移除 git 后备钩子并恢复 pack-refs 设置；登记和审计日志保留{dry}。",
                             "It removes the git backstop from {repo} and restores the pack-refs settings; the claims and the audit log stay{dry}."),
    "approval_what_install": ("它把本守卫及其启动器从 {src} 复制到 {home}{down}，并打印 {host} 的钩子配置；它从不修改宿主配置{dry}。",
                              "It copies this guard and its launcher from {src} to {home}{down} and prints the {host} hook entry; it never edits the host "
                              "configuration{dry}."),
    "approval_dry": ("（--dry-run：不写入任何东西）", " (--dry-run: nothing is written)"),
    "approval_downgrade": ("（--allow-downgrade：会替换更新版本的守卫副本）", " (--allow-downgrade: replaces a newer guard copy)"),
    "approval_no_record": ("lane 与冲突的分支：此处没有记录（agent 收到的拒绝消息列出了它们）",
                           "the lane and the conflicting branches: not recorded here (the denial the agent received names them)"),
    "approval_desc": ("MAGOS 用户专属命令：{sub}（待批准）", "MAGOS user-only command: {sub} (approval)"),
    "approval_unknown": ("MAGOS：批准令牌在这里无效：存储中没有这个令牌（令牌错误、属于另一个仓库或守卫目录，或已过期并被清除）。没有执行任何操作。"
                         "请去掉 --approval 重新执行这条守卫命令，由用户在宿主的对话框中重新批准。",
                         "MAGOS: the approval token is not valid here: the store holds no such token (a wrong token, one of another repository or guard home, or "
                         "one that expired and was removed). Nothing was done. Run the guard command again without --approval; the user approves it again in "
                         "the host's dialog."),
    "approval_expired": ("MAGOS：批准令牌已过期（批准只在请求中说明的时间内有效）。没有执行任何操作。请去掉 --approval 重新执行这条守卫命令，由用户重新批准。",
                         "MAGOS: the approval token expired (an approval is valid only for the time its request stated). Nothing was done. Run the guard "
                         "command again without --approval; the user approves it again."),
    "approval_used": ("MAGOS：批准令牌已经用过（一次批准只执行一条命令一次）。没有执行任何操作。请去掉 --approval 重新执行这条守卫命令，由用户重新批准。",
                      "MAGOS: the approval token was already used (one approval runs one command once). Nothing was done. Run the guard command again without "
                      "--approval; the user approves it again."),
    "approval_mismatch": ("MAGOS：批准令牌是为另一{what}签发的。没有执行任何操作。请去掉 --approval 重新执行这条守卫命令，由用户重新批准。",
                          "MAGOS: the approval token was issued for another {what}. Nothing was done. Run the guard command again without --approval; the user "
                          "approves it again."),
    "what_sub": ("个子命令", "subcommand"),
    "what_args": ("组参数", "set of arguments"),
    "what_repo": ("个仓库", "repository"),
    "what_home": ("个守卫目录", "guard home"),
    # ---- Codex approval (1.0.8): the MCP approval server's dialog and results, the Codex hook's route, the mcp deny
    "protected_codex": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。在 Codex 中由用户在 Codex 自己的对话框里点击批准：请调用 MCP 服务器 magos 的工具 "
                        "magos_approve，参数正好是：{call} 不要自己执行这条守卫命令。如果这个工具不可用，或者 Codex 的审批策略是 never（Codex 会自行拒绝所有"
                        "对话框），则由用户在真实终端里执行：{ready}",
                        "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). In Codex the user approves it with a click in "
                        "Codex's own dialog: call the MCP tool magos_approve of the server magos with exactly these arguments: {call} Do not run the guard "
                        "command yourself. Where that tool is not available, or Codex's approval policy is never (Codex then declines every dialog by "
                        "itself), the user runs this in a real terminal: {ready}"),
    "protected_codex_form": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。在 Codex 中，用户专属命令由用户通过 MCP 服务器 magos 的工具 magos_approve "
                             "在 Codex 自己的对话框里点击批准：它只接受 subcommand（override、arm、disarm 或 install）、repo（仓库的绝对路径；install 可省略）、"
                             "fingerprint 和 reason（override）、host（install）以及 dry_run（arm、disarm、install），而这条命令不是它能接受的单独一次直接守卫"
                             "调用。请按用户的要求用相应参数调用 magos_approve，或者由用户在真实终端里执行：{cmd} <子命令> <选项>",
                             "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). In Codex the user approves a user-only "
                             "command with a click in Codex's own dialog, through the MCP tool magos_approve of the server magos: it takes only subcommand "
                             "(override, arm, disarm or install), repo (the absolute path of the repository; optional for install), fingerprint and reason "
                             "(override), host (install) and dry_run (arm, disarm, install), and this command is no single direct invocation of the guard "
                             "that it can take. Call magos_approve with the arguments of what the user asked for, or the user runs the command in a real "
                             "terminal: {cmd} <subcommand> <options>"),
    "protected_codex_never": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。Codex 的审批策略是 never，它会自行拒绝 magos_approve 的批准对话框，所以这里"
                              "没有点击批准的途径：只能由用户在真实终端里执行：{ready}",
                              "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). Codex runs with the approval policy "
                              "never, under which it declines the approval dialog of magos_approve by itself, so there is no click here: only the user runs "
                              "this, in a real terminal: {ready}"),
    "protected_mcp": ("MAGOS 拒绝：此命令会启动守卫的 MCP 批准服务器（mcp 子命令），它只能由宿主按照自己的配置启动；任何宿主上的工具命令都不能运行它。没有启动任何东西。",
                      "MAGOS DENIES: this command would start the guard's MCP approval server (the mcp subcommand), which only the host starts from its "
                      "own configuration; a tool command never runs it, on any host. Nothing was started."),
    "protected_slot": ("MAGOS 拒绝：此命令运行守卫脚本，但钩子无法确认它运行的是 agent 可以运行的子命令：子命令必须是写在命令里的一个普通单词，紧跟在脚本和它前面的普通选项之后，"
                       "守卫的参数也不能来自 xargs、parallel 或 find -exec。请这样写：{cmd} <{subs}> <选项>。hook 和 mcp 只由宿主运行；override、arm、disarm "
                       "和 install 由用户批准。没有运行任何东西。",
                       "MAGOS DENIES: this command runs the guard script, but the hook cannot see that it runs a subcommand an agent may run: the "
                       "subcommand must be one plain word written in the command, right after the script and the plain options before it, and the "
                       "guard must not take its words from xargs, parallel or find -exec. Write it as: {cmd} <{subs}> <options>. hook and mcp are "
                       "run only by the host; the user approves override, arm, disarm and install. Nothing ran."),
    "protected_long": ("MAGOS 拒绝：此命令超过钩子读取的长度（{n} 个字符），并且提到了 MAGOS，钩子无法判断它会运行什么。请把守卫命令单独作为一条短于 {n} 个字符的命令执行。"
                       "没有运行任何东西。",
                       "MAGOS DENIES: this command is longer than the hook reads ({n} characters) and names MAGOS, so the hook cannot tell what it "
                       "runs. Run the guard command as a command of its own, shorter than {n} characters. Nothing ran."),
    "mcp_ask": ("MAGOS：批准用户专属的守卫命令 {sub} 吗？\n{where}\n{what}\n先勾选 Approve，再点击 Accept（接受）：这只批准这一项，只执行一次。其他任何回答都不执行。",
                "MAGOS: approve the user-only guard command {sub}?\n{where}\n{what}\nTick Approve, then Accept: that approves exactly this, once. "
                "Anything else runs nothing."),
    "ready_own": ("<请在这里输入你自己的话>", "<type your own words here>"),  # a value PowerShell 5.1 would change on its way to the guard (ready_command)
    "mcp_approve_field": ("勾选即批准上面所述的这一条守卫命令，只执行一次。", "Tick to approve exactly the guard command described above, once."),
    "mcp_where_repo": ("仓库：{repo}（Git 目录 {common}）", "Repository: {repo} (Git directory {common})"),
    "mcp_where_home": ("守卫目录：{home}", "Guard home: {home}"),
    "mcp_ran": ("MAGOS：用户已在对话框中批准 {sub}；守卫已执行，退出码 {code}。输出：\n{out}",
                "MAGOS: the user approved {sub} in the dialog; the guard ran it and exited {code}. Its output:\n{out}"),
    "mcp_refused": ("MAGOS：{sub} 的批准对话框以 {action} 结束：用户拒绝或取消了它，或者宿主自行作答（在 Codex 中，审批策略 never 或不含 MCP elicitation 的 "
                    "granular 策略会拒绝所有对话框）。什么都没有执行。如果用户需要，由用户在真实终端里执行：{ready}",
                    "MAGOS: the approval dialog of {sub} ended with {action}: the user declined or cancelled it, or the host answered it by itself (in "
                    "Codex an approval policy of never, or a granular policy without MCP elicitations, declines every dialog). Nothing ran. If the user "
                    "wants it, the user runs this in a real terminal: {ready}"),
    "mcp_unticked": ("MAGOS：{sub} 的批准对话框被接受，但没有勾选 Approve（或回答不是勾选的 Approve）；什么都没有执行。用户在场时请再次调用 magos_approve，由用户勾选 "
                     "Approve 后再接受，或者由用户在真实终端里执行：{ready}",
                     "MAGOS: the approval dialog of {sub} was accepted without Approve ticked (or with an answer that is no ticked Approve); nothing ran. "
                     "Call magos_approve again so that the user ticks Approve, then accepts, or the user runs this in a real terminal: {ready}"),
    "mcp_late": ("MAGOS：{sub} 的批准对话框在 {s} 秒内没有得到回答；守卫已撤回它，什么都没有执行。用户在场时请再次调用 magos_approve，或者由用户在真实终端里执行：{ready}",
                 "MAGOS: no answer to the approval dialog of {sub} within {s} s; the guard withdrew it and nothing ran. Call magos_approve again when the "
                 "user is there, or the user runs this in a real terminal: {ready}"),
    "mcp_busy": ("MAGOS：这个服务器的另一个批准对话框仍未关闭；什么都没有执行。请在用户回答之后再次调用 magos_approve。",
                 "MAGOS: another approval dialog of this server is open; nothing ran. Call magos_approve again after the user has answered it."),
    "mcp_no_form": ("MAGOS：这个客户端没有声明 MCP elicitation 表单能力，无法显示批准对话框；什么都没有执行。由用户在真实终端里执行：{ready}",
                    "MAGOS: this client declares no MCP elicitation form, so it cannot show the approval dialog; nothing ran. The user runs this in a "
                    "real terminal: {ready}"),
    "mcp_terminal": ("MAGOS：该仓库的 magos.approval 是 terminal（或是守卫不认识的值，按 terminal 处理）：什么都没有执行；{sub} 只能由用户在真实终端里执行：{ready}",
                     "MAGOS: the repository's magos.approval is terminal (or a value the guard does not know, which counts as terminal): nothing ran; "
                     "only the user runs {sub}, in a real terminal: {ready}"),
    "mcp_invalid": ("MAGOS：参数无效，什么都没有执行：\n{errors}\nmagos_approve 只接受 subcommand（override、arm、disarm 或 install）、repo（仓库的绝对路径；install "
                    "可省略）、fingerprint 和 reason（override）、host（install）以及 dry_run（arm、disarm、install）。",
                    "MAGOS: invalid arguments, nothing ran:\n{errors}\nmagos_approve takes only subcommand (override, arm, disarm or install), repo (the "
                    "absolute path of the repository; optional for install), fingerprint and reason (override), host (install) and dry_run (arm, "
                    "disarm, install)."),
    "mcp_failed": ("MAGOS：{sub} 没有执行：{err}。由用户在真实终端里执行：{ready}", "MAGOS: {sub} did not run: {err}. The user runs this in a real terminal: {ready}"),
    # ---- Hermes approval (1.0.8): the Hermes hook's answer when the MAGOS Hermes plugin runs it, its question and its denials
    "protected_shape_hermes": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。只有用户能批准它：在 Hermes 中，请把这条守卫命令单独作为一次 terminal 调用"
                               "执行：在前台运行、不用 pty，前后不加任何内容，也不带 --approval；脚本用绝对路径，并用 --repo <仓库绝对路径>（或调用的 workdir）"
                               "指明仓库：{cmd} --repo <仓库> <子命令> <选项>；Hermes 随后在自己的审批提示中询问用户。否则由用户在自己的终端里执行。",
                               "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). Only the user approves it: in Hermes, "
                               "run this guard command as a terminal call of its own, in the foreground and without pty, with nothing before or after it and "
                               "without --approval, with an absolute script path and the repository named by --repo <absolute path> (or the call's "
                               "workdir): {cmd} --repo <repository> <subcommand> <options>; Hermes then asks the user in its own approval prompt. Otherwise "
                               "the user runs it in their own terminal."),
    "approval_given_hermes": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}），并且带有 --approval。批准令牌从不由 agent 提供：用户在 Hermes 的审批提示中"
                              "批准时，守卫会自己加上它。请去掉 --approval 后重新执行。",
                              "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}) and carries --approval. An agent never "
                              "supplies an approval token: the guard adds it itself when the user approves the command in Hermes's approval prompt. Run the "
                              "command without --approval."),
    "protected_hermes_noask": ("MAGOS 拒绝：此命令会修改守卫自己的清单/开关/钩子（{why}）。Hermes 在这里不会询问用户（{how}），因此一次点击不能证明用户同意：只能由用户"
                               "在自己的终端里执行。",
                               "MAGOS DENIES: this command would change the guard's own claims/switches/hooks ({why}). Hermes would not ask the user here "
                               "({how}), so a click could not show the user's consent: only the user may run it, in their own terminal."),
    "hermes_how_session": ("Hermes 报告它在这里无需询问即批准：/yolo、--yolo、approvals.mode off，或无人值守的运行（cron、-q、-z、无人值守的平台）",
                           "Hermes reports that it approves without asking here: /yolo, --yolo, approvals.mode off, or a run nobody attends (cron, -q, -z, "
                           "an unattended platform)"),
    "hermes_how_gate": ("这个 Hermes 不向插件提供审批请求，或 MAGOS 插件无法在此进程中查看它的审批状态",
                        "this Hermes has no approval request for plugins, or the MAGOS plugin cannot see its approval state in this process"),
    "hermes_how_env": ("设置了 HERMES_YOLO_MODE", "HERMES_YOLO_MODE is set"),
    "hermes_how_mode": ("{path} 中的 approvals.mode 是 {value}", "approvals.mode is {value} in {path}"),
    "hermes_how_config": ("无法读取 {path}（{err}）", "{path} cannot be read ({err})"),
    "approval_ask_hermes": ("MAGOS：批准用户专属的守卫命令 {sub} 吗？{what}批准后，这条命令在 {secs} 秒内执行，且只执行一次；once、session 和 always 都只批准这一次请求。",
                            "MAGOS: approve the user-only guard command {sub}? {what} Approving runs exactly this command once, within {secs} s; once, "
                            "session and always each approve this one request only."),
    # ---- sets (1.0.4): set-plan, set-show, set-update, set-release, and the plain plan / release refusing the claims of a set
    "set_invalid": ("MAGOS：set 规划无效，未登记也未创建任何东西：\n{errors}", "MAGOS: the set plan is invalid, nothing registered or created:\n{errors}"),
    "set_invalid_args": ("MAGOS：参数无效，未做任何修改：\n{errors}", "MAGOS: invalid arguments, nothing was changed:\n{errors}"),
    "set_stale_base": ("MAGOS：计划已过期，未写入任何东西：目标 {t} 现在位于 {live}，而计划基于 {base}。请重新调查仓库后再规划。",
                       "MAGOS: the plan is stale, nothing was written: target {t} is now at {live}, but the plan was made against {base}. Investigate the repository again and re-plan."),
    "set_stale_revision": ("MAGOS：计划已过期，未写入任何东西：set「{s}」现在是修订 {cur}，而你基于修订 {exp}。请先用 set-show 重新读取。",
                           "MAGOS: the plan is stale, nothing was written: set '{s}' is at revision {cur}, not {exp}. Read it again with set-show."),
    "set_exists": ("MAGOS：set「{s}」已存在（修订 {rev}）。用 --amend --expect-revision {rev} 修改，或先 set-release。",
                   "MAGOS: set '{s}' already exists (revision {rev}). Change it with --amend --expect-revision {rev}, or release it first with set-release."),
    "set_unknown": ("MAGOS：没有名为「{s}」的 set。", "MAGOS: there is no set named '{s}'."),
    "set_out_of_lane": ("MAGOS：拒绝把 lane {l} 标记为 ready：下列文件在它的 manifest 之外：{files}。请在该 lane 中撤销这些改动，或用 /GitPlan {s} --amend 修改计划。",
                        "MAGOS: refused to mark lane {l} ready: these files lie outside its manifest: {files}. Revert them in the lane, or amend the plan with /GitPlan {s} --amend."),
    "set_newer": ("MAGOS：set「{s}」由更新版本的 MAGOS 写入（v={v}）：请升级本守卫（doctor 显示版本，install 刷新副本），或用写入它的那个 MAGOS 执行这条命令。",
                  "MAGOS: set '{s}' was written by a newer MAGOS (v={v}): upgrade this guard (doctor shows its version, install refreshes the copy), or run this command with the MAGOS that wrote it."),
    "set_unreadable": ("MAGOS：set 记录 {f} 无法读取，未做任何修改；请用户检查该文件。", "MAGOS: the set record {f} cannot be read; nothing was changed. The user must inspect the file."),
    "set_conflict": ("MAGOS 拒绝登记 set「{s}」：下列 lane 的 manifest 与其他 lane 或已有分支重叠，或无法分析。没有登记也没有创建任何东西。",
                     "MAGOS DENIES registering set '{s}': the manifests of the lanes below overlap other lanes or existing branches, or could not be analysed. Nothing was registered or created."),
    "set_overlap": ("lane {a} 与 lane {b} 的 manifest 重叠：{pairs}", "lane {a} and lane {b} overlap: {pairs}"),
    "set_lane_item": ("lane {l}（分支 {b}）：", "lane {l} (branch {b}):"),
    "set_options": ("可选处理：① 缩小或拆分重叠的 lane；② 等对方合入 {target} 后再规划；③ 对方若已合并或已放弃，用 release 释放它的登记（未合并的工作不会被释放）。set-plan 不读取也不消耗用户覆盖（override）。",
                    "Options: (1) shrink or split the overlapping lanes; (2) wait until the others are merged into {target}; (3) if the other lane is merged or abandoned, release its claim with release "
                    "(unmerged work is never released). set-plan neither reads nor consumes an override."),
    "set_branch_exists": ("MAGOS：lane {l} 的分支「{b}」已经存在且没有有效登记，不能事后补登记。请换一个新分支名。",
                          "MAGOS: the branch '{b}' of lane {l} already exists without a claim; it cannot be registered after the fact. Choose a new branch name."),
    "set_lane_exists": ("MAGOS：lane {l} 的分支「{b}」已有一份不属于这个 set 的登记。请先 release 它，或换一个分支名。",
                        "MAGOS: the branch '{b}' of lane {l} already has a claim that is not this set's. Release it first, or choose another branch name."),
    "set_ok_plan": ("MAGOS：已登记 set「{s}」：{n} 个 lane，目标 {t}，基线 {base}，修订 {rev}。现在可以从基线逐个创建 lane，例如：{example}",
                    "MAGOS: registered set '{s}': {n} lanes, target {t}, base {base}, revision {rev}. You may now create the lanes from the base, e.g.: {example}"),
    "set_ok_amend": ("MAGOS：已修改 set「{s}」：修订 {old} → {rev}，{n} 个 lane。", "MAGOS: amended set '{s}': revision {old} -> {rev}, {n} lanes."),
    "set_ok_check": ("MAGOS：set「{s}」的预览通过，没有发现重叠；这是 --dry-run，未写入任何东西。",
                     "MAGOS: the preview of set '{s}' passed, no overlap found; this was a --dry-run and nothing was written."),
    "set_unchanged": ("MAGOS：set「{s}」没有变化（修订 {rev}），未写入任何东西。", "MAGOS: set '{s}' is unchanged (revision {rev}); nothing was written."),
    "set_ok_update": ("MAGOS：set「{s}」的 lane {l} 现在是 {st}，修订 {rev}。", "MAGOS: lane {l} of set '{s}' is now {st}, revision {rev}."),
    "set_released": ("MAGOS：已释放 set「{s}」及其 {n} 份登记。", "MAGOS: released set '{s}' and its {n} claims."),
    "set_blocked": ("MAGOS：拒绝 {op}：{why}", "MAGOS: {op} refused: {why}"),
    "set_why_state": ("lane {l} 的状态是 {st}，不是 integrated", "lane {l} is {st}, not integrated"),
    "set_why_unmerged": ("lane {l} 的分支 {b} 有未合并的工作", "the branch {b} of lane {l} has unmerged work"),
    "set_why_dirty": ("lane {l} 的工作树有未提交的修改", "the worktree of lane {l} has uncommitted changes"),
    "set_why_wt_missing": ("lane {l} 的工作树 {w} 在磁盘上缺失（例如已锁定但所在驱动器未挂载），无法确认其中没有未提交的工作",
                           "the worktree {w} of lane {l} is missing on disk (for example locked on an unmounted drive), so it cannot be known to hold no uncommitted work"),
    "set_why_operation": ("lane {l} 的工作树正在进行 {op}", "the worktree of lane {l} has a {op} in progress"),
    "set_why_missing": ("lane {l} 的分支 {b} 不存在", "the branch {b} of lane {l} does not exist"),
    "set_why_head_tip": ("--head {head} 不是分支 {b} 的当前提交 {tip}", "--head {head} is not the tip {tip} of branch {b}"),
    "set_why_head_recorded": ("--head {head} 不是 lane {l} 在 ready 时记录的 head {rec}", "--head {head} is not the head {rec} recorded for lane {l} at ready"),
    "set_why_ancestor": ("提交 {head} 既不在 {t} 中，也不在集成分支中", "commit {head} is in neither {t} nor the integration branch"),
    "set_why_shrink": ("lane {l} 已经改动了新 manifest 之外的文件：{files}", "lane {l} already changed files outside its new manifest: {files}"),
    "set_why_claim": ("lane {l} 的登记无法读取或来自更新版本的 MAGOS", "the claim of lane {l} cannot be read or comes from a newer MAGOS"),
    "set_why_integration": ("集成分支 {b} 不存在", "the integration branch {b} does not exist"),
    "set_why_base": ("lane {l} 与计划的基线没有共同历史", "lane {l} shares no history with the plan's base"),
    "lane_in_set": ("MAGOS：分支「{b}」是 set「{s}」的 lane，不能单独修改它的登记。用 set-plan --amend 修改，或先 set-release。",
                    "MAGOS: branch '{b}' is a lane of set '{s}'; its claim cannot be changed on its own. Use set-plan --amend, or set-release first."),
    "blocked_set": ("MAGOS：拒绝 release：「{b}」是 set「{s}」的登记。请用 set-release 一并释放。",
                    "MAGOS: release refused: '{b}' belongs to set '{s}'. Retire the whole set with set-release."),
    "show_head": ("set「{s}」→ {t}　基线 {base}　修订 {rev}　集成分支 {i}", "set '{s}' -> {t}  base {base}  revision {rev}  integration {i}"),
    "show_lane": ("{box} {l}　{st}　记录 {head}　当前 {tip}　领先 {n}　工作树 {wt}　分支 {b}", "{box} {l}  {st}  head {head}  tip {tip}  ahead {n}  worktree {wt}  branch {b}"),
    "show_wt_clean": ("干净", "clean"),
    "show_wt_dirty": ("有未提交修改", "dirty"),
    "show_wt_op": ("{op} 进行中", "{op} in progress"),
    "show_wt_absent": ("缺失", "absent"),
    "show_wt_unreadable": ("无法读取", "unreadable"),
    "show_out": ("越界文件（{l}）：{files}", "outside the manifest ({l}): {files}"),
    "show_shared": ("多个 lane 改动的文件：{files}", "changed by more than one lane: {files}"),
    "show_moved": ("目标已从 {base} 移到 {tip}；与 lane 重叠的文件：{files}", "the target moved from {base} to {tip}; files that overlap lanes: {files}"),
    "show_moved_ready": ("ready 之后分支又移动：{lanes}", "moved since ready: {lanes}"),
    "show_order": ("合并顺序：{order}", "merge order: {order}"),
    "set_line": ("  lane {l}  分支 {b}  工作树 {w}  {n} 条路径", "  lane {l}  branch {b}  worktree {w}  {n} entries"),
    "set_line_integration": ("  集成分支 {b}", "  integration branch {b}"),
    # ---- sets (1.0.4): the topic names of the lanes, the requirements they serve and the summary of what an integrated lane changed
    "set_why_changes_target": ("目标分支 {t} 不存在，无法计算 lane {l} 的改动摘要",
                               "the target branch {t} does not exist, so the summary of the changes of lane {l} cannot be computed"),
    "set_why_changes_history": ("lane {l} 与 {ref} 没有共同历史，无法计算改动摘要", "lane {l} shares no history with {ref}, so the summary of its changes cannot be computed"),
    "set_err_generic_id": ("lane id「{id}」是序号或泛称，看不出改动的主题。请改用 1 到 3 个单词的主题 slug（小写，连字符连接），例如 claim-store、sweep-readiness、readme-gitplan。",
                           "lane id '{id}' is an ordinal or generic name and does not show the topic of the change. Name the topic with 1 to 3 words in kebab-case, "
                           "for example claim-store, sweep-readiness, readme-gitplan."),
    "set_err_reserved_id": ("lane id「{id}」是保留名：integration 属于集成分支 agent/<set>/integration，con、prn、aux、nul、com1 至 com9、lpt1 至 lpt9 是 Windows 设备名。"
                            "请另选一个说明这个 lane 改动内容的主题 slug。",
                            "lane id '{id}' is reserved: integration belongs to the integration branch agent/<set>/integration, and con, prn, aux, nul, com1 to com9 "
                            "and lpt1 to lpt9 are Windows device names. Choose another topic slug that names what the lane changes."),
    "set_err_id_form": ("lane id「{id}」不是主题 slug：必须匹配 {rule}（小写字母、数字、连字符，1 到 24 个字符，不以连字符开头），并用 1 到 3 个单词说明改动的主题，例如 claim-store。{hint}",
                        "lane id '{id}' is not a topic slug: it must match {rule} (lowercase letters, digits and hyphens, 1 to 24 characters, not starting with a hyphen) "
                        "and name the topic of the change in 1 to 3 words, for example claim-store.{hint}"),
    "set_hint_slug": ("建议：{slug}。", "Suggestion: {slug}."),
    "set_err_branch_form": ("lane {l} 的分支必须是 {want}（agent/<set>/<lane id>），而不是「{got}」。请改用 {want}。",
                            "the branch of lane {l} must be {want} (agent/<set>/<lane id>), not '{got}'. Use {want}."),
    "set_err_worktree_form": ("lane {l} 的工作树目录名必须以 -{s}-{l} 结尾，而「{got}」不是。请改用，例如：{want}。",
                              "the worktree directory of lane {l} must have a name ending with -{s}-{l}, which '{got}' does not. Use, for example: {want}."),
    "set_err_worktree_device": ("lane {l} 的工作树目录名「{got}」在第一个点之前是 Windows 设备名 {dev}。请改用，例如：{want}。",
                                "the worktree directory name '{got}' of lane {l} is the Windows device name {dev} before its first dot. Use, for example: {want}."),
    "set_err_unserved": ("需求 {r}（{t}）没有任何 lane 负责。请用一个 lane 负责它：把 {r} 加入某个 lane 的 serves，或为它新增一个 lane。不要删除用户提出的需求。",
                         "requirement {r} ({t}) is served by no lane. Serve it with a lane: add {r} to the serves of a lane, or add a lane for it. "
                         "Never drop a requirement the user stated."),
    "set_err_serves_unknown": ("serves 里的「{r}」不是本规划 requirements 中的编号（已有：{ids}；编号逐字匹配，区分大小写）。",
                               "'{r}' in serves is no requirement id of this spec (known: {ids}; ids are matched exactly, case included)."),
    "set_err_serves_count": ("lane {l} 的 serves 需要 1 到 12 个需求编号（现在 {n} 个）。", "the serves of lane {l} needs 1 to 12 requirement ids ({n} given)."),
    "set_err_set_name": ("set 名称「{s}」无效：必须匹配 {rule}（小写字母、数字、连字符，1 到 24 个字符，不以连字符开头），并说明任务的主题。",
                         "the set name '{s}' is invalid: it must match {rule} (lowercase letters, digits and hyphens, 1 to 24 characters, not starting with a hyphen) "
                         "and name the topic of the task."),
    "set_err_set_device": ("set 名称「{s}」是 Windows 设备名，不能用作记录文件 sets/{s}.json 的名称。请另选一个说明任务主题的名称。",
                           "the set name '{s}' is a Windows device name and cannot name the record file sets/{s}.json. Choose another name that names the topic of the task."),
    "show_changes": ("    改动 {l}：{commits} 个提交，{files} 个文件，+{ins}/-{del}；路径 {paths}；{subjects}",
                     "    changes {l}: {commits} commits, {files} files, +{ins}/-{del}; paths {paths}; {subjects}"),
    "show_more": ("另有 {n} 项", "+{n} more"),
}


def T(lang, key, **kw):
    return M[key][0 if lang == "zh" else 1].format(**kw)


# ---------------------------------------------------------------- pure: fold, glob DP, manifest, evaluate, render
def _fc(c):
    for f in (str.casefold, str.lower):
        r = f(c)
        if len(r) == 1:
            return r
    return c


def fold(s):
    """NFC + per-code-point, length-preserving case fold (str.casefold would turn 'ß' into 'ss' and break '?')."""
    return "".join(_fc(c) for c in unicodedata.normalize("NFC", s))


class ManifestError(ValueError):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


Entry = namedtuple("Entry", "raw alts")  # alts: folded segment tuples; the second one over-approximates a [..] character class
_WILD = re.compile(r"[*?]")


def _inter(a, b, star, ok):
    """Can token sequences a and b describe one common sequence?  `star` matches any run (also empty); ok(x, y) compares plain tokens."""
    @lru_cache(maxsize=None)
    def f(i, j):
        if i == len(a) and j == len(b):
            return True
        if i < len(a) and a[i] == star and (f(i + 1, j) or (j < len(b) and f(i, j + 1))):
            return True
        if j < len(b) and b[j] == star and (f(i, j + 1) or (i < len(a) and f(i + 1, j))):
            return True
        return i < len(a) and j < len(b) and a[i] != star and b[j] != star and ok(a[i], b[j]) and f(i + 1, j + 1)
    return f(0, 0)


@lru_cache(maxsize=65536)
def seg_overlap(a, b):
    """May two segment globs (* ? literals) match one common name?  Exact."""
    if not (_WILD.search(a) or _WILD.search(b)):
        return a == b
    return _inter(a, b, "*", lambda x, y: "?" in (x, y) or x == y)


def segs_overlap(a, b):
    """May two path globs (segment tuples; ** = any number of segments, also none) match a common path?  Exact; also entry-vs-path."""
    return _inter(a, b, GS, seg_overlap)


def entries_overlap(a, b):
    return any(segs_overlap(x, y) for x in a.alts for y in b.alts)


def parse_entry(raw):
    """One manifest line -> Entry.  A literal path (or one ending in '/') means that path and everything below it."""
    s = raw.strip()

    def bad(code, why):
        return ManifestError(code, "%s: %r" % (why, raw))
    if not s or re.search(r"[\x00-\x1f]", s):
        raise bad("EMPTY", "empty entry or control character")
    if len(s) > 1024:
        raise bad("TOO_LONG", "entry longer than 1024 characters")
    s = unicodedata.normalize("NFC", s.replace("\\", "/"))
    if s[0] in ":!":
        raise bad("MAGIC", "pathspec magic / negation is not supported")
    if s[0] == "/" or re.match(r"[A-Za-z]:", s):
        raise bad("ABSOLUTE", "absolute paths are not allowed (use a path relative to the repository root)")
    segs = []
    for p in s.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise bad("DOTDOT", "'..' is not allowed")
        q = p.rstrip(". ")  # NTFS drops trailing dots and spaces
        f = fold(q)
        if not q or len(q) > 255:
            raise bad("BAD_SEGMENT", "empty or overlong path segment")
        if f == ".git" or re.fullmatch(r"git~\d+", f):
            raise bad("GITDIR", ".git is not allowed")
        if "**" in f and f != GS:
            raise bad("BAD_GLOB", "'**' must be a whole path segment")
        segs.append(f)
    if not segs or all(g == GS or not re.sub(r"[*?]", "", g) for g in segs):
        raise bad("UNIVERSAL", "too broad: name a directory or a file pattern")
    subtree = (all(g != GS and not _WILD.search(g) for g in segs) or s.endswith("/")) and segs[-1] != GS
    alts = [tuple(segs)]
    if any(re.search(r"\[[^\]]+\]", g) for g in segs):  # brackets are ordinary characters; also over-approximate them as a class
        alts.append(tuple(re.sub(r"\[[^\]]+\]", "?", g) for g in segs))
    return Entry(raw.strip(), tuple(a + ((GS,) if subtree else ()) for a in alts))


def parse_manifest(lines):
    items = [x.strip() for x in lines if x.strip() and not x.strip().startswith("#")]
    errors = [] if items else [("EMPTY", "the manifest has no entries")]
    if len(items) > MAX_ENTRIES:
        errors.append(("TOO_MANY", "more than %d entries" % MAX_ENTRIES))
    entries, seen = [], set()
    for raw in items[:MAX_ENTRIES]:
        try:
            e = parse_entry(raw)
        except ManifestError as err:
            errors.append((err.code, str(err)))
            continue
        if e.alts not in seen:
            seen.add(e.alts)
            entries.append(e)
    return entries, errors


@lru_cache(maxsize=262144)
def fpath(p):
    return tuple(fold(s) for s in p.split("/") if s)


def path_hit(entry, path):
    """Does a folded concrete path fall under the entry?  Also a changed FILE that the entry names literally as a directory."""
    for alt in entry.alts:
        lit = []
        for g in alt:
            if g == GS or _WILD.search(g):
                break
            lit.append(g)
        if segs_overlap(alt, path) or (len(path) < len(lit) and list(path) == lit[:len(path)]):
            return True
    return False


def lane_key(branch):
    return hashlib.sha1(fold(branch).encode("utf-8")).hexdigest()[:32]


def evaluate(entries, claimants, deadline=None):
    def tick():
        if deadline and time.monotonic() > deadline:
            raise GitFail("BUDGET_EXCEEDED", "the comparison ran out of time")
    out = []
    for c in claimants:
        tick()
        ev = []
        for kind in ("committed", "uncommitted"):
            hits = {}
            for n, p in enumerate(sorted(c["paths"][kind]), 1):
                if not n % 256:
                    tick()
                hits[p] = [e.raw for e in entries if path_hit(e, fpath(p))]
            files = [p for p, m in hits.items() if m]
            if files:
                ev.append({"kind": kind, "files": files, "matched": sorted({r for p in files for r in hits[p]}), "theirs": []})
        pairs = []
        for t in c["declared"]:
            tick()
            pairs += [(e.raw, t.raw) for e in entries if entries_overlap(e, t)]
        if pairs:
            ev.append({"kind": "declared", "files": [], "matched": sorted({a for a, _ in pairs}), "theirs": sorted({b for _, b in pairs})})
        if ev:
            out.append({"key": c["key"], "branch": c["branch"], "worktrees": sorted(c["worktrees"]), "planned": c.get("planned", False), "evidence": ev})
    return sorted(out, key=lambda x: (x["branch"] or "~", x["worktrees"]))


def fingerprint(key, conflicts, unknown_codes, target_sha):
    blob = json.dumps([key, sorted([c["key"], sorted([e["kind"], sorted(e["files"]), e["theirs"]] for e in c["evidence"])] for c in conflicts),
                       sorted(unknown_codes), target_sha], ensure_ascii=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()[:12]


def guard_cmd(script=None):
    """The command that runs a guard script (default: this one) in the user's shell."""
    return '%s "%s"' % ("py -3" if sys.platform == "win32" else "python3", os.path.abspath(script or __file__).replace("\\", "/"))


def _few(items, n=8):
    return ", ".join(items[:n]) + (" ..." if len(items) > n else "")


def conflict_lines(lang, v):
    """The lines that name every conflicting branch / worktree / evidence kind / files of a verdict, then its unknowns."""
    L = []
    for i, c in enumerate(v.get("conflicts", []), 1):
        L.append(T(lang, "item", i=i, b=c["branch"] or "(detached)", w=", ".join(c["worktrees"]) or "-", p=T(lang, "planned") if c.get("planned") else ""))
        for e in c["evidence"]:
            k = T(lang, "k_" + e["kind"])
            L.append(T(lang, "ev_decl", k=k, t=_few(e["theirs"]), m=_few(e["matched"])) if e["kind"] == "declared"
                     else T(lang, "ev", k=k, n=len(e["files"]), f=_few(e["files"]), m=_few(e["matched"])))
    return L + ["[%s] %s" % (u["code"], u["text"]) for u in v.get("unknowns", [])]


def render(lang, v, name):
    """Human message of a verdict, naming every conflicting branch / worktree / evidence kind / files."""
    if v["code"] == "NO_MANIFEST":
        return T(lang, "nomanifest", b=name) + "\n" + T(lang, "how_plan", cmd=guard_cmd(), b=name)
    L = []
    if v.get("conflicts"):
        L.append(T(lang, "conflict", b=name))
    elif v.get("unknowns"):
        L.append(T(lang, "unknown", b=name))
    L += conflict_lines(lang, v)
    if v["decision"] == "deny" and v.get("unknowns") and all(u["code"] == "CLAIM_NEWER_FORMAT" for u in v["unknowns"]):
        L.append(T(lang, "newer_only"))  # no shrink, wait, release or override: only a guard that reads that format can act on the claim
    elif v["decision"] == "deny" and v.get("fingerprint"):
        L.append(T(lang, "options", target=v.get("target", {}).get("name", "?"), cmd=guard_cmd(), fp=v["fingerprint"]))
    return "\n".join(L + ["(%s) %s" % (w["code"], w["text"]) for w in v.get("warnings", [])])


# ---------------------------------------------------------------- pure: command parsing (a UX layer: the git hook is the hard stop)
# What check_refname_format refuses in a name, in ASCII only: a space, a control character, ~ ^ : ? * [ \, '..', a leading or trailing '/', '.lock'.
# Whitespace and letters outside ASCII belong to a name git accepts; a leading dash is judged per verb (_DASH_REFS).
_BAD_NAME = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|^/|/$|\.lock$")
_DASH_REFS = ("update-ref", "symbolic-ref", "fetch", "pull", "push")  # the verbs whose operand is a full ref: `refs/heads/-x` is a ref, `-x` no branch name


_OPENERS = ("if", "while", "until", "for", "select", "case")  # POSIX-shell words that open a compound command: what runs inside may not run
_CLOSERS = ("fi", "done", "esac")
_CONT = re.compile(r"(?:\\|`)\r?\n[ \t]*")  # a line continuation
_PS_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "e": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}  # PowerShell's `0 `a `b `e `f `n `r `t `v


def _continued(cmd, sh):
    """The text with its line continuations read: bash removes a backslash-newline, so the words around it join; a PowerShell backtick-newline
    and the continuations of a shell the hook cannot name read as a space."""
    return _CONT.sub(" ", re.sub(r"\\\r?\n", "", cmd) if sh == "bash" else cmd)


class _Seg(list):
    """One command of a line: a list of (word, dynamic); `at` is the offset of its first word in the text the lexer read, `sub` tells that
    it starts inside a word's $( .. ), <( .. ) or PowerShell ( .. ) (text substituted into another command)."""
    at, sub = 0, False


# A redirection operator, with the file descriptor in front of it: a number, a variable name in braces (`{fd}>f`, bash), in PowerShell also a stream
# (`*>`); `>&`, `<&` and `&>` come before `>` and `<` so that `>&` alone is one operator and the target of `>& 2` is the next word.
_OPERATOR = r"(?:&>>?|>&|<&|>>?\|?|<<<|<<-?|<>|<)"
_REDIR_OP = re.compile(r"(?:[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\})?" + _OPERATOR)
_REDIR_OP_PS = re.compile(r"(?:[0-9]+|\*|\{[A-Za-z_][A-Za-z0-9_]*\})?" + _OPERATOR)
_FD_VAR = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}[<>]")  # `{fd}>` at a word start: the redirection of a variable's file descriptor, no brace block


class _Redir(str):
    """A word that is a redirection of the shell: the lexer read an unquoted, unescaped redirection operator at its start (`>f`, `2>&1`, `<<EOF`,
    or the operator alone: `>`, `2>`, `<<<`).  `take` is the number of words it occupies, 2 when its target is the next word.  It is the text it
    spells in every other respect."""
    take = 1


def _redirection(word, plain, ps=False):
    """`word` as a _Redir when it starts with a redirection operator written in its first `plain` characters (before any quote or escape), else
    `word`.  `<(` and `>(` are substituted text, no redirection."""
    m = (_REDIR_OP_PS if ps else _REDIR_OP).match(word)
    if m is None or m.end() > plain or word[m.end():m.end() + 1] == "(":
        return word
    r = _Redir(word)
    r.take = 1 if word[m.end():] else 2
    return r


def _skip_redirs(words, k):
    """The index of the first word from `k` on that is no redirection: the redirections of the shell standing there, with their targets, are skipped."""
    while k < len(words) and isinstance(words[k], _Redir):
        k += words[k].take
    return k


def _is_redirection(word):
    """Does the text of a word (as written, quotes kept) start with a redirection operator?  Text-based, for the word gate and the alias check,
    which read no lexer words; `<(` and `>(` are substituted text."""
    m = _REDIR_OP_PS.match(word)
    return m is not None and word[m.end():m.end() + 1] != "("


def _redir_like(old, text):
    """`text` as the redirection `old` becomes when an expansion changes its target: the operator and the number of words it takes stay."""
    r = _Redir(text)
    r.take = old.take
    return r


def _redir_indices(words, end):
    """The indices below `end` of the redirections of the shell among `words` and of their targets."""
    found, k = set(), 0
    while k < end:
        if isinstance(words[k], _Redir):
            found.update(range(k, min(k + words[k].take, end)))
            k += words[k].take
        else:
            k += 1
    return found


_IN_PATH = re.compile(r"[0-9]*<(?![<&>(])(.*)$", re.S)  # `<file` and `0<file`; `<` alone leaves the file to the next word


def _input_files(ins):
    """The file names the `<` redirections among `ins` (the input redirections _split_redirs returns) read: the target written with the
    operator, else the next word."""
    out = []
    for k, (w, _d) in enumerate(ins):
        m = _IN_PATH.match(w)
        if m and m.group(1):
            out.append(m.group(1))
        elif m and k + 1 < len(ins):
            out.append(ins[k + 1][0])
    return out


def _fd_word(parts, quoted, ps):
    """Is the word the lexer has read so far (`parts`, written outside quotes and escapes unless `quoted`) the number of a file descriptor, or in
    PowerShell `*`: the operator right after it is part of that word (`2>f`, `*>f`)?"""
    if quoted:
        return False
    w = "".join(parts)
    return (w.isascii() and w.isdigit()) or (ps and w == "*") or re.fullmatch(r"\{[A-Za-z_][A-Za-z0-9_]*\}", w) is not None


def _split_redirs(words, dyn):
    """-> (words, dynamic flags, input redirections): the words of a command without the redirections of the shell (git never sees them), and
    the input redirections (`<f`, `< f`, `<<< text`, `<<EOF`) with their targets as (word, dynamic) pairs, which an `update-ref --stdin` reads."""
    if not any(isinstance(w, _Redir) for w in words):
        return words, dyn, []
    out, od, ins, k = [], [], [], 0
    while k < len(words):
        w = words[k]
        if isinstance(w, _Redir):
            if re.match(r"(?:[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\})?<", w):
                ins += list(zip(words[k:k + w.take], dyn[k:k + w.take]))
            k += w.take
        else:
            out.append(w)
            od.append(dyn[k])
            k += 1
    return out, od, ins


def _lex(cmd, sh=None):
    """Split a shell / PowerShell / cmd command line into events: a segment (_Seg of (word, dynamic)) or a mark.  Marks: '(' and ')' open and
    close a parenthesised group that starts where a command may start; '{' and '}' a brace block; 'K(' and 'K)' a POSIX-shell compound
    command (if / while / until / for / select / case .. fi / done / esac; not read for PowerShell and cmd, whose blocks are braces and
    parentheses); '|' a pipe; '&&' and '||' join the commands of an and-or list; ';' (also a newline) ends a list; '&' ends a list that runs
    in the background (in cmd the next command follows it; a '&' with no command before it is PowerShell's call operator, and a '&' in a
    redirection or in '|&' is none).  Quotes are honoured and backslashes kept.  Parentheses and braces separate segments only where a
    command may start (PowerShell: a '{' that does not follow '$' or '@', and a '}' that closes no '{' of its word, always); elsewhere they
    belong to a (dynamic) word.  One stack pairs every parenthesis: a ')' that closes a parenthesis opened inside a word ($(..), <(..),
    PowerShell (..)) is no scope mark, also where it stands after a separator, and the command that word belongs to goes on after it; a
    segment that starts inside such a parenthesis is marked `sub`.  A ')' read into a word while a group is the innermost open parenthesis
    closes that group after the segment.  Inside `case`, a pattern ends at its ')' and an arm at ';;', ';&' or ';;&'; pattern words are
    dropped.  Escapes follow the shell that runs the text: in bash (POSIX quoting) a backslash outside quotes removes itself and makes the
    next character a literal part of the word (`feat\\ure` is `feature`, `\\;` stays in the word), and inside double quotes it is removed
    only before $, a backtick, '"', a backslash and a newline; in cmd a caret outside double quotes does the same; in PowerShell a backtick
    outside quotes removes itself and makes the next character literal, except that `0 `a `b `e `f `n `r `t `v stand for NUL, bell,
    backspace, escape, form feed, newline, carriage return, tab and vertical tab (_PS_ESCAPES); PowerShell and a shell the hook cannot name
    keep their backslashes (path separators there)."""
    segs, cur, parens, close, cases, at = [], [], [], [False], [], [0, False]  # at: offset of the segment's first word, and whether it is substituted
    # kw: cur holds reserved words only; pp: the characters at the start of the word written outside quotes and escapes (until ppx); op: the word
    # ends in an unquoted '<' or '>'
    st = {"w": [], "dyn": False, "has": False, "open": False, "q": False, "b": 0, "kw": True, "inword": 0, "pp": 0, "ppx": False, "op": ""}
    kw, ps, posix = sh not in ("ps", "cmd"), sh == "ps", sh == "bash"
    escape = "\\" if posix else "^" if sh == "cmd" else "`" if ps else None  # the character that quotes the next one outside quotes

    def flush():
        if cur:
            seg = _Seg(cur)
            seg.at, seg.sub = at
            segs.append(seg)
            cur.clear()
        st["kw"] = True

    def pop():  # -> the kind of the parenthesis a ')' closes (None: none is open)
        kind = parens.pop() if parens else None
        st["inword"] -= kind == "w"
        return kind

    def word_end():
        if not st["has"]:
            return
        w, dyn, quoted, mode = "".join(st["w"]), st["dyn"], st["q"], cases[-1] if cases else None
        plain_len = st["pp"]
        st.update(w=[], dyn=False, has=False, open=False, q=False, b=0, pp=0, ppx=False, op="")
        plain, first = not quoted and not dyn, st["kw"]  # first: the word stands where a command starts
        kw_here = kw and not st["inword"]  # inside a word's $( .. ) the text is a command of its own, judged as such
        if plain and w == "esac" and (mode == "pat" or (mode == "body" and first)):
            cases.pop()
            flush()
            segs.append("K)")
        elif mode == "pat":  # a pattern word: no command
            return
        elif plain and first and kw_here and w in _OPENERS:
            segs.append("K(")
            if w == "case":
                cases.append("head")
        elif plain and first and kw_here and w in _CLOSERS[:2]:
            flush()
            segs.append("K)")
        elif plain and mode == "head" and w == "in":
            cases[-1] = "pat"
        cur.append((_redirection(w, plain_len, ps), dyn))
        st["kw"] = st["kw"] and w in _KEYWORDS

    def seg_end(mark=None):
        word_end()
        flush()
        if close[0]:
            segs.append(")")
            close[0] = False
        if mark:
            segs.append(mark)
    cmd = _continued(cmd, sh)
    i, n, plain_to = 0, len(cmd), 0  # plain_to: the end of a comment line of a shell that may not read it as one (quotes there are plain)
    while i < n:
        c, mode = cmd[i], cases[-1] if cases else None
        nxt, prev = cmd[i + 1:i + 2], cmd[i - 1:i]
        if c == escape and nxt:  # an escaped character: literal, part of the word, never special (an escaped word is no reserved word)
            if not st["has"] and not cur:
                at[:] = [i, st["inword"] > 0]
            st["w"].append(_PS_ESCAPES.get(nxt, nxt) if ps else nxt)
            st["has"], st["q"], st["ppx"], st["op"] = True, True, True, ""
            i += 2
            continue
        if c == "#" and not st["has"] and i >= plain_to:  # a word that starts with # starts a comment in bash and PowerShell
            end = cmd.find("\n", i)
            end = n if end < 0 else end
            if posix or ps:
                i = end  # the newline still ends the command
                continue
            plain_to = end  # cmd or a shell the hook cannot name: the words are read, their quote characters are plain
        if mode == "pat" and c in ")|" and st["w"] == list("esac") and not st["q"]:  # `esac)` / `esac|`: the case ends before the ')' or '|'
            word_end()
            mode = cases[-1] if cases else None
        fdvar = c == "{" and not st["has"] and mode != "pat" and not (ps or sh == "cmd") and _FD_VAR.match(cmd, i) is not None
        glue = False  # a '&' or '|' that belongs to a redirection operator (`2>&1`, `>&2`, `&>f`, `>|f`), no command separator
        if c == "&" and nxt != "&" and mode != "pat":
            if st["op"]:
                glue = True
            elif nxt == ">" and not (ps or sh == "cmd"):
                word_end()
                glue = True
        elif c == "|" and st["op"] == ">" and nxt != "|" and mode != "pat" and not (ps or sh == "cmd"):
            glue = True
        if c in " \t\r" or (c == "\n" and mode == "pat"):
            word_end()
        elif mode == "pat" and c == "(" and not st["has"]:
            pass  # the optional '(' before a pattern
        elif mode == "pat" and c == "|":
            word_end()
        elif mode == "pat" and c == ")" and not st["open"]:
            seg_end()
            cases[-1] = "body"
        elif (c in ";\n&|" and not glue) or (c in "()" and not st["has"] and not cur) or (c == ")" and not st["open"]) or \
                (c == "{" and not fdvar and (not st["has"] or (ps and prev not in "$@"))) or (c == "}" and (not st["has"] or (ps and not st["b"]))):
            mark, arm = None, False
            if c == "|":
                mark = "||" if nxt == "|" else "|"
                i += 1 if nxt == "|" else 0
            elif c == "&":
                if nxt == "&":
                    mark, i = "&&", i + 1
                elif prev not in "<>|" and nxt != ">" and (cur or st["has"] or (segs and segs[-1] in (")", "}", "K)"))):  # also `{ .. } &`, `( .. ) &`
                    mark = "&"
            elif c in ";\n":
                mark, arm = ";", c == ";" and mode == "body" and nxt in (";", "&")  # the end of a case arm: ;; ;& ;;&
                i += (2 if cmd[i + 1:i + 3] == ";&" else 1) if arm else 0
            elif c == "(":
                parens.append("g")
                mark = "("
            elif c == ")":
                word_end()  # the word before it still stands inside the parenthesis
                if pop() == "w":  # it closes a word's $( .. ): the command that word belongs to goes on
                    i += 1
                    continue
                mark = ")"
            else:
                mark = c
            seg_end(mark)
            if arm:
                cases[-1] = "pat"
        elif c in "'\"" and i >= plain_to:
            j = i + 1
            while j < n and cmd[j] != c:
                if posix and c == '"' and cmd[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 2 if (c == '"' and cmd[j] in "\\`" and j + 1 < n and cmd[j + 1] == '"') else 1
            body = cmd[i + 1:j]
            if not st["has"] and not cur:
                at[:] = [i, st["inword"] > 0]
            if c == '"' and posix:
                text, dyn = _dq_posix(body)
            else:
                text, dyn = (body.replace('`"', '"').replace('\\"', '"'), bool(re.search(r"[$`]", body))) if c == '"' else (body, False)
            st["w"].append(text)
            st["has"], st["dyn"], st["open"], st["q"] = True, st["dyn"] or dyn, st["open"] or "(" in body, True
            st["ppx"], st["op"] = True, ""
            i = j
        else:
            if c in "<>" and st["has"] and not st["op"] and not (st["inword"] or st["b"] or mode == "pat") and nxt != "(" and \
                    not _fd_word(st["w"], st["q"], ps):
                word_end()  # a redirection operator ends the word before it, unless that is the number of a file descriptor (`2>f`)
            if not st["has"] and not cur:
                at[:] = [i, st["inword"] > 0]
            st["w"].append(c)
            st["op"] = c if c in "<>" or (glue and nxt == ">") else ""  # the '&' of `&>` takes the '>' after it into the word
            if not st["ppx"]:
                st["pp"] += 1
            if c == "(":
                parens.append("w")
                st["inword"] += 1
            elif c == ")" and parens and pop() == "g":
                close[0] = True
            elif c == "{":
                st["b"] += 1
            elif c == "}" and st["b"]:
                st["b"] -= 1
            st["has"], st["dyn"], st["open"] = True, st["dyn"] or c in "$`%()", st["open"] or c == "("
        i += 1
    seg_end()
    return segs


def _dq_posix(body):
    """The text of a double-quoted POSIX-shell string and whether it is dynamic: a backslash is removed only before $, a backtick, '"', a
    backslash and a newline; an unescaped $ or backtick expands."""
    out, dyn, k = [], False, 0
    while k < len(body):
        ch = body[k]
        if ch == "\\" and k + 1 < len(body) and body[k + 1] in '$`"\\\n':
            out.append(body[k + 1])
            k += 2
            continue
        dyn = dyn or ch in "$`"
        out.append(ch)
        k += 1
    return "".join(out), dyn


def split_command(cmd):
    """Split a shell / PowerShell command line into segments of (word, dynamic); quotes honoured, backslashes kept."""
    return [e for e in _lex(cmd) if isinstance(e, list)]


_WRAP = ("env", "command", "sudo", "doas", "time", "nohup", "exec", "call", "builtin", "nice", "xargs", "timeout", "watch", "wsl", "uv", "npx", "stdbuf",
         "setsid")
_SU_VALUE = ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U", "--user", "--group", "--chdir", "--host", "--prompt", "--role", "--type",
             "--other-user", "--close-from", "--command-timeout")  # options of the privilege wrappers that take the next word as their value
_KEYWORDS = ("if", "then", "else", "elif", "do", "while", "until", "!", "time", "function")
_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
_KNOWN = ("git", "gh", "gt", "claude", "cd", "pushd", "chdir", "set-location", "sl", "powershell", "pwsh", "cmd", "eval", "iex", "invoke-expression",
          "start-process", "set-alias", "sal", "find") + _SHELLS
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")  # NAME=value, and NAME+=value (appends to a value the hook may not know)
# The global options of git that take the next word as their value: the word after the value is the subcommand.
_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--attr-source", "--super-prefix", "--list-cmds",
               "--shallow-file"}
# The words that decide whether a command line is walked at all, read on the text with every escape character and quote removed (g\it and g''it are git).
_GATE = re.compile(r"git|gh|gt|claude|eval|iex|invoke-expression|\.sh|\.bash|\.ps1|source|-enc|base64", re.I)
_RUNNERS = frozenset((".", "bash", "sh", "zsh", "dash", "ksh", "powershell", "pwsh", "cmd"))  # the words that run a script or a shell
# A word of a command line (quotes kept in it) or a character that ends a command; a quote that never closes belongs to no word.  A word that
# starts with `>&`, `<&`, `&>` or `>|` (`2>&1`) is one token: the & and | of a redirection end no command.
_TOKEN = re.compile(r"""(?:[0-9]*[<>]&|&>>?|>\|)[^\s;&|(){}`'"]*|[;&|(){}`\n]|(?:[^\s;&|(){}`'"]|'[^']*'|"[^"]*")+""")


def _runs_script(text):
    """Does a command of `text` start with a word that runs a script or a shell (`. ./mk`, `bash ./mk`, `cmd /c ..`; also with .exe, behind a
    path, prefix assignments, keywords, wrappers and redirections, and after the -exec of find)?  One pass over the words; a word that follows a
    wrapper may be the program it starts."""
    start, wrapped, target = True, False, False
    for tok in _TOKEN.findall(text):
        if len(tok) == 1 and tok in ";&|(){}`\n":
            start, wrapped, target = True, False, False
        elif target:  # the target of a redirection that stands before the program: `> out bash ./mk`
            target = False
        elif _bare(tok).lower() in ("-exec", "-execdir"):  # find runs the command that follows
            start = True
        elif start and _is_redirection(tok):
            target = _REDIR_OP_PS.match(tok).end() == len(tok)
        elif start:
            names = {_exe(w) for w in (re.sub(r"[`^'\"]", "", tok), _bare(tok))}  # as written (a backslash is a separator), and unescaped
            if not names.isdisjoint(_RUNNERS):
                return True
            if not names.isdisjoint(_WRAP):
                wrapped = True
            elif not (wrapped or _ASSIGN.match(tok) or tok[:1] == "$" or tok in ("=", "+=") or not names.isdisjoint(_KEYWORDS)):  # `$x = bash ./mk`
                start = False
    return False


def _gated(text):
    """May the text create something?  Its words read without escapes and quotes name a command the detector knows, or a command of it starts
    with a word that runs a script or a shell (the script it runs is read).  A text too long to inspect is walked, which refuses it.  The words
    are also found with the quotes removed, so that a quote the shell reads as a literal (`echo \\"; bash ./mk`) hides none."""
    plain = re.sub(r"['\"]", "", text)
    return _GATE.search(re.sub(r"[\\`^]", "", plain)) is not None or len(text) > MAX_TEXT or _runs_script(text) or _runs_script(plain)


# What may stand between a pipe and the shell that reads it: prefix assignments, wrappers and their options (an option may take one value).
# Every word excludes the separators | ; &, so one attempt never runs past the next pipe; an option's value is never a wrapper or an
# assignment, so each word has one reading and the patterns stay linear in the command length.
_PIPE_WRAP = r"(?:command|builtin|exec|nohup|nice|time|setsid|stdbuf|sudo|doas|env)"
_TO_SHELL = (r"\|&?\s*(?:(?:[A-Za-z_][A-Za-z0-9_]*=[^\s|;&]*|%s|-[^\s|;&]+(?:\s+(?!%s\s|[A-Za-z_][A-Za-z0-9_]*=)[^\s|;&-][^\s|;&]*)?)\s+)*"
             % (_PIPE_WRAP, _PIPE_WRAP))
_SINK = re.compile(r"<<<|<\(|%s(?:(?:ba|z|da|k)?sh\b|powershell|pwsh)|\b(?:iex|invoke-expression)\b|-command\s+-" % _TO_SHELL, re.I)
_ECHO_PIPE = re.compile(r"\s*(?:echo|printf)\s(.*?)%s(?:ba|z|da|k)?sh\b" % _TO_SHELL, re.I | re.S)
_SUBST = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_QUOTED = re.compile(r"'([^']*)'|\"((?:[^\"\\]|\\.)*)\"")
_BUILTINS = frozenset("status log diff add commit push pull fetch merge rebase show stash tag remote config reset restore rev-parse ls-files grep blame clean "
                      "apply am cherry-pick revert describe bisect submodule gc fsck init clone mv rm reflog shortlog archive bundle cat-file for-each-ref ls-tree "
                      "merge-base show-ref update-index var version help worktree branch switch checkout symbolic-ref update-ref flow".split())


def _exe(word):
    return re.sub(r"\.(exe|cmd|bat)$", "", re.split(r"[\\/]", word)[-1].lower())


def _norm_path(p):
    """Git Bash spellings (/c/Users/x, //c/x) become Windows paths and ~ is expanded; everything else is unchanged."""
    m = re.match(r"^/{1,2}([A-Za-z])(?:/(.*))?$", p) if os.name == "nt" else None
    if m:
        return "%s:/%s" % (m.group(1).upper(), m.group(2) or "")
    return os.path.expanduser(p) if p.startswith("~") else p


class _Missing(str):
    """A directory a cd / pushd / chdir / Set-Location / sl named that does not exist when the hook runs.  The shell stays where it was:
    `.prior` is that directory, where the following commands run (the creation is then judged there, unresolved).  `.follow` is set
    while an earlier element of the same && chain creates the directory, so the later elements of that chain run inside it: (kind, data,
    token of the frame whose chain made it) with kind "new" after git init / git clone (a new repository holds no lane), "wt" after git
    worktree add (data: the directory it ran in) and "dir" after mkdir (data: the path; git finds the repository of its nearest existing
    ancestor).  Its repr carries both, so two records that differ only in them are two records."""
    follow = None

    def __repr__(self):
        return "_Missing(%s, %r, %r)" % (str.__repr__(self), getattr(self, "prior", None), self.follow)


def _missing(target, prior, follow=None):
    m = _Missing(target)
    m.prior, m.follow = prior, follow
    return m


def _join(base, p):
    """`p` resolved against the directory `base` (None: unknown); None when it names no directory we may judge.  Absolute spellings are
    classified here and never with os.path.isabs, whose Windows result for a rooted path without a drive differs from Python 3.13 on.
    A relative path after a failed cd resolves where the shell really is: the prior directory, or the target an earlier element of the
    same && chain creates (`follow`)."""
    p = _norm_path(p)
    if os.name == "nt":
        if re.match(r"[A-Za-z]:|[\\/]{2}[^\\/]", p):  # a drive or a UNC path
            return p
        if p.startswith("/"):
            return None  # a POSIX-rooted spelling _norm_path could not map to a drive
        if p.startswith("\\"):  # rooted on the drive of the current directory
            return None if base is None else os.path.splitdrive(getattr(base, "prior", base))[0] + p
    elif p.startswith("/"):
        return p
    if base is None:
        return None
    if isinstance(base, _Missing) and not base.follow:
        base = base.prior
    t = os.path.normpath(os.path.join(base, p))
    return None if len(t) > MAX_DIR else t  # no real directory is spelled longer: a chain of `-C a/b` never grows a path that every step copies


def _cd(here, p):
    """The shell directory after `cd p`: a target that is not an existing directory when the hook runs leaves the shell where it was."""
    t = _join(here, p)
    if isinstance(t, _Missing) or (t is not None and os.path.isdir(t)):
        return t
    return None if here is None else _missing(t or p, getattr(here, "prior", here))


def _gitdir_path(here, value, dynamic):
    """The git directory a --git-dir / GIT_DIR value names for an invocation that runs in `here` (as git resolves it: a relative value
    against the directory the invocation runs in), or None when it cannot be resolved."""
    if dynamic or not value:
        return None
    return _join(here, value)


_REDIRECTS = ("GIT_DIR", "GIT_COMMON_DIR")  # the variables that move git to another repository


def _gd_name(word):
    """The spelling of GIT_DIR or GIT_COMMON_DIR that `word` (NAME or NAME=value) names, or None.  POSIX: exactly that name.  Windows:
    any case, because git reads the process environment without regard to case (Git Bash still keeps each spelling as its own variable)."""
    name = word.split("=", 1)[0]
    name = name[:-1] if "=" in word and name.endswith("+") else name  # NAME+=value
    return name if name in _REDIRECTS or (os.name == "nt" and name.upper() in _REDIRECTS) else None


def _appends(word):
    """NAME+=value: the result depends on a value the hook cannot see."""
    return word.split("=", 1)[0].endswith("+") and "=" in word


def _gd_kind(name):
    """GIT_DIR or GIT_COMMON_DIR for a stored spelling (a `?n` suffix marks a value that may apply)."""
    return name.split("?")[0].upper()


class _GitDirs(dict):
    """The GIT_DIR and GIT_COMMON_DIR values of one command line by spelling: name -> (value, dynamic, exported); exported is True, False, or None when the
    shell may have exported the variable before the line (it reaches git only then).  `sh` is the shell that runs the line (bash, ps, cmd,
    or None when the hook cannot tell).  An operation of another shell, or of a shell the hook cannot name, may or may not take effect:
    an assignment adds its value as one that may apply and keeps the others, and a removal leaves the value as one that may still apply,
    so every repository git may reach is judged."""

    def __init__(self, cands=(), sh=None):
        super().__init__((k, (v, d, True if e else None)) for k, v, d, e in cands)
        self.sh, self.n = sh, 0

    def copy(self):
        c = _GitDirs(sh=self.sh)
        c.update(self)
        c.n = self.n
        return c

    def cands(self):
        """(name, value, dynamic, definite) for every value a git invocation may see; definite: it certainly sees one of them."""
        return tuple((k, v, d, e is True) for k, (v, d, e) in sorted(self.items()) if v is not None and e is not False)

    def _same(self, name, env):
        """The stored spellings one operation changes: the process environment ignores case on Windows, a bash variable never does."""
        return [k for k in self if k.split("?")[0] == name or (env and os.name == "nt" and k.split("?")[0].upper() == name.upper())]

    def assign(self, dialect, name, value, dyn, exported):
        """NAME=value in `dialect`; exported None keeps the export state (a bash shell variable), True exports it."""
        if dialect != self.sh:
            self.n += 1
            self["%s?%d" % (name, self.n)] = (value, dyn, None)
            return
        env = dialect != "bash"
        prev = next((self[k] for k in self._same(name, env) if "?" not in k), (None, False, None))
        for k in self._same(name, env):
            del self[k]
        self[name] = (value, dyn, prev[2] if exported is None else exported)

    def export(self, dialect, name, flag):
        """bash export NAME (flag True) or export -n NAME (flag False).  Exporting a name whose value the walk never saw exports a value set
        where the walker does not look (a for loop, an unmodelled assignment): the repository is unknown from here on."""
        cur = self.get(name)
        if cur is None:
            if flag and dialect == (self.sh or dialect):
                self.unknown(name)
            return
        if dialect == self.sh:
            self[name] = (cur[0], cur[1], flag)
        elif not flag and cur[2] is True:
            self[name] = (cur[0], cur[1], None)

    def unknown(self, name):
        """A change written in a spelling the walker does not model (read, printf -v, +=, builtin export, Set-Content Env: ...): from here
        on git's repository is unknown, so a creation is denied with the redirect message."""
        for k in self._same(name, True):
            del self[k]
        self[name] = ("$" + name, True, True)

    def remove(self, dialect, name):
        """unset NAME, Remove-Item Env:NAME, $env:NAME = $null, set NAME= ..."""
        env = dialect != "bash"
        for k in self._same(name, env):
            if dialect == self.sh:
                del self[k]
            elif self[k][2] is True:
                self[k] = (self[k][0], self[k][1], None)
        if dialect == self.sh:
            self[name] = (None, False, False)


def _with_rds(cr, here, cands):
    """Attach the GIT_DIR and GIT_COMMON_DIR values an invocation running in `here` may see; interpret() expands them into one record per
    repository.  Only a GIT_DIR value can certainly replace the repository git finds: under GIT_COMMON_DIR git writes the branch into the
    repository it finds from its directory (or GIT_DIR) but reads the config and runs the hooks of the GIT_COMMON_DIR repository."""
    rds = tuple((_gitdir_path(here, v, d), definite and _gd_kind(k) == "GIT_DIR") for k, v, d, definite in cands)
    return dict(cr, rds=rds) if rds else cr


def _expand(cr):
    """One record per repository the creation may land in: each --git-dir / GIT_DIR / GIT_COMMON_DIR value (gitdir None: it cannot be
    resolved), plus the directory the invocation runs in unless a GIT_DIR value certainly applies."""
    rds = cr.pop("rds", ())
    return [dict(cr, redirect=True, gitdir=g) for g, _ in rds] + ([cr] if not any(definite for _, definite in rds) else [])


def _cr(verb, names, cwd, dynamic, kind="branch", path=None, tool=False, commit=None):
    """A creation record.  kind: worktree (named worktree), branch (branch only) or auto (the tool names the worktree itself).
    A name is dropped when git certainly refuses it (_BAD_NAME; a leading dash for the verbs that read the word as a branch name, which
    git then takes for an option).  A bell in a name
    (PowerShell's `a) is judged as the letter a: git refuses the bell, so the stricter reading only denies more (``fe`at`` is named feat).
    redirect: True when the record is judged in the git directory `gitdir` (--git-dir / GIT_DIR; None: it cannot be resolved)."""
    dash = verb in _DASH_REFS
    names = [n for n in (n.replace("\a", "a") for n in names)
             if (_BAD_NAME.search(n) is None and (dash or not n.startswith("-"))) or re.search(r"[$`%()]", n)]
    return {"verb": verb, "names": names, "cwd": cwd, "dynamic": dynamic or any(re.search(r"[$`%()]", n) for n in names), "kind": kind, "path": path, "tool": tool,
            "commit": commit, "redirect": False, "gitdir": None}


# `refs/heads/` in any case of both words (ASCII letters only: refs/headſ/ is no branch).  The case-insensitive file systems of Windows and macOS
# store REFS/HEADS/x as the branch x.  The one place that reads it: the host hook (_HEADS and the patterns below) and the git layer (HOOK_SH).
_REFS_CI = "[Rr][Ee][Ff][Ss]/"
_HEADS_CI = _REFS_CI + "[Hh][Ee][Aa][Dd][Ss]/"
_HEADS = re.compile(_HEADS_CI)  # callers cut the name with t[11:]: the prefix is 11 characters whatever its case
_OUTSIDE_HEADS = re.compile(_REFS_CI + "(?![Hh][Ee][Aa][Dd][Ss]/)[^/$`%()]+/")  # a literal ref namespace other than heads: no branch


def _maybe_heads(word):
    """May the (dynamic) ref word name a branch?  Only a word that begins with a literal namespace other than `heads` (refs/tags/$T) cannot."""
    return _OUTSIDE_HEADS.match(word) is None


# The instructions of `git update-ref --stdin`, read from the text that feeds it.  A verb is a word of its own (`refs/heads/update-docs` holds
# none); the operand of `create` and `update` must be a plain name: a run of characters no shell, printf or git quoting changes.
_STDIN_START = r"(?:(?<!\w)|(?<=\\[ntr0]))"  # a word starts here, or right after a separator printf writes (`\n` ends in a letter)
_STDIN_WORD = re.compile(_STDIN_START + r"(?:create|update|delete|verify|option|start|prepare|commit|abort)(?![\w-])")
_STDIN_VERB = re.compile(_STDIN_START + r"(?:create|update)(?![\w-])")  # also the end of symref-create and symref-update
_STDIN_OPERAND = re.compile(r"[ \t]+([^\x00-\x20\x7f\"'\\$`%(){}]*)")
_STDIN_END = re.compile(r"$|[ \t\r\n]|\\(?:[ntr]|0(?![0-7]))")  # what may follow a plain operand: the end, a blank, a separator printf writes
_STDIN_ESC = re.compile(r"\\(?![ntr]|0(?![0-7]))")  # a backslash that is no separator: printf and echo -e turn it into another text
_STDIN_PSEUDO = re.compile(r"[A-Z][A-Z_]*")  # HEAD, ORIG_HEAD: no branch
_STDIN_OUTSIDE = re.compile(_REFS_CI + "(?![Hh][Ee][Aa][Dd][Ss]/).")  # refs/tags/v1: a ref outside refs/heads/


def _stdin_refs(text):
    """-> (names, dynamic) for the instructions of an `update-ref --stdin` written in `text`, the text the hook can read.  The record is dynamic
    unless the instructions are accounted for by plainly read names: an instruction word must stand in the text; every backslash must begin
    a separator printf writes (`\\n`, `\\t`, `\\r`, `\\0` not followed by an octal digit; printf turns `\\x62` into a letter); every `create` and
    `update` must be followed by blanks and a plain operand that ends at the end of the text, a blank or such a separator: `refs/heads/<name>`
    (the name is read; an empty name and a name git refuses are dynamic) or a literal ref outside refs/heads/ or a pseudo-ref.  A quote, `$`,
    `%`, a brace, a parenthesis or an escape in an operand, and a word that is no ref, are not plainly read."""
    names, dynamic = [], _STDIN_ESC.search(text) is not None or _STDIN_WORD.search(text) is None
    for m in _STDIN_VERB.finditer(text):
        op = _STDIN_OPERAND.match(text, m.end())
        if op is None:
            dynamic = True
            continue
        ref = op.group(1)
        if _STDIN_END.match(text, op.end()) is None:
            dynamic = True
        if _HEADS.match(ref):
            name = ref[11:]
            dynamic = dynamic or not name or _BAD_NAME.search(name) is not None
            if name:
                names.append(name)
        elif _STDIN_PSEUDO.fullmatch(ref) is None and _STDIN_OUTSIDE.match(ref) is None:
            dynamic = True
    return names, dynamic


# Where the instructions of an update-ref --stdin come from: the input redirections of its words, and the command before the pipe that feeds it.
_IN_STR = re.compile(r"\d*<<<")  # a here-string
_IN_DOC = re.compile(r"\d*<<(?!<)")  # a here-document
_IN_FILE = re.compile(r"\d*<(?!<)")  # < file, <file, 0<file, <(cmd): input the hook cannot read
_FEEDERS = ("echo", "printf", "write-output", "write-host")  # the commands whose words are the text they write


def _no_input():
    return {"here": [], "doc": False, "file": False}


def _input_of(src, word, dynamic, nxt):
    """Note in `src` the input redirection that `word` is (`nxt`: the next word and its dynamic flag, None at the end).  -> the number of words
    after it that it takes (the text of `<<<`, the file of `<`), None when `word` is no input redirection."""
    m = _IN_STR.match(word)
    if m:
        if word[m.end():]:
            src["here"].append((word[m.end():], dynamic))
            return 0
        src["here"].append(nxt or ("", True))
        return 1
    if _IN_DOC.match(word):
        src["doc"] = True
        return 1 if re.fullmatch(r"\d*<<-?", word) else 0  # `<< EOF`: the delimiter is the next word
    if _IN_FILE.match(word):
        src["file"] = True
        return 1 if re.fullmatch(r"\d*<", word) else 0
    return None


def _update_ref_args(a, ad):
    """`git update-ref`'s words (after the subcommand), read as git reads them.  -> (stdin, delete, positional words as (word, dynamic), input
    sources).  -m takes the rest of its word or else the next word, a short-option word deletes when it holds a d before any m, --stdin is also
    written as a unique prefix (and may have a redirection glued to it: --stdin<file), `--` ends the options."""
    stdin = delete = ended = False
    pos, src, k = [], _no_input(), 0
    while k < len(a):
        t, d = a[k], ad[k]
        took = _input_of(src, t, d, (a[k + 1], ad[k + 1]) if k + 1 < len(a) else None)
        if took is not None:
            k += took
        elif ended:
            pos.append((t, d))
        elif t == "--":
            ended = True
        elif t.startswith("--"):
            cut = re.search(r"[<>]", t)
            if cut:  # the shell ends the word at a redirection
                k += _input_of(src, t[cut.start():], d, (a[k + 1], ad[k + 1]) if k + 1 < len(a) else None) or 0
                t = t[:cut.start()]
            key = t[2:].split("=", 1)[0]
            stdin = stdin or (key != "" and "stdin".startswith(key))  # --s, --std ...
        elif t.startswith("-") and len(t) > 1:
            for j in range(1, len(t)):
                if t[j] == "m":
                    k += 0 if t[j + 1:] else 1
                    break
                delete = delete or t[j] == "d"
        else:
            pos.append((t, d))
        k += 1
    return stdin, delete, pos, src


def _symbolic_ref_args(a, ad):
    """`git symbolic-ref`'s positional words as (word, dynamic): -m takes the rest of its word or else the next word (also -qm <reason>), and
    `--` ends the options."""
    pos, k = [], 0
    while k < len(a):
        t = a[k]
        if t == "--":
            pos += list(zip(a[k + 1:], ad[k + 1:]))
            break
        if t.startswith("-"):
            j = t.find("m", 1) if not t.startswith("--") else -1
            if j > 0 and not t[j + 1:]:
                k += 1
        else:
            pos.append((t, ad[k]))
        k += 1
    return pos


def _unseen_update_ref(ev):
    """The input sources of `"$GIT" update-ref --stdin` and `/usr/bin/env git update-ref --stdin`, a git invocation the walk cannot name: a
    dynamic or git program word in command position (after prefix assignments, keywords and wrappers, which may be written with a path),
    git's global options, `update-ref`, and a --stdin word after it (or the program `git-update-ref` and a --stdin word).  None for any
    other command: a commit message, an echo operand, a `git grep` pattern or a here-document written to a file only mention
    `update-ref --stdin`."""
    words, dyn, ins = _split_redirs([w for w, _ in ev], [d for _, d in ev])  # the redirections stand anywhere; the input ones feed update-ref
    i = 0
    while i < len(words) and (_ASSIGN.match(words[i]) or _exe(words[i]) in _WRAP or words[i].lower() in _KEYWORDS or words[i] == "&"):
        i += 1
    prog = _exe(words[i]) if i < len(words) else ""
    if i >= len(words) or not (dyn[i] or prog in ("git", "git-update-ref")):
        return None
    if prog != "git-update-ref":
        i += 1
        while i < len(words) and words[i].startswith("-"):  # git's global options and the values of those that take one
            i += 2 if words[i] in _VALUE_OPTS else 1
        if words[i:i + 1] != ["update-ref"]:
            return None
    stdin, _delete, _pos, src = _update_ref_args(words[i + 1:] + [w for w, _ in ins], dyn[i + 1:] + [d for _, d in ins])  # the options follow the word at i
    return src if stdin else None


def _stdin_feed(src, up, docs):
    """-> (text, unseen) for an `update-ref --stdin`: the text of the sources of its instructions that the hook can read, and whether some
    source cannot be read (then the creation is dynamic).  `src` holds the input redirections of the invocation, `docs` the here-document bodies
    of the line, `up` the command before the pipe that feeds it: False (no pipe), None (a pipe from something that is no plain command) or the
    words of that command as (word, dynamic).  Readable: a here-string, the here-documents, the words of a directly piped echo, printf,
    Write-Output or Write-Host (also a single string word that holds a blank: PowerShell writes a string expression), a cat of here-documents.  An
    expansion in a readable source (a word with $, a backtick, %, ( or ), a body with $ or a backtick) makes it unreadable."""
    pieces, unseen = [], src["file"]
    for text, dyn in src["here"]:
        pieces.append(text)
        unseen = unseen or dyn
    doc = src["doc"]
    if up is None:
        unseen = True
    elif up:
        words = [w for w, _ in up]
        i = next((k for k, w in enumerate(words) if not _ASSIGN.match(w)), len(words))
        exe = _exe(words[i]) if i < len(words) else ""
        if exe in _FEEDERS:
            pieces.append(" ".join(words[i + 1:]))
            unseen = unseen or any(d for _, d in up)
        elif exe == "cat" and words[i + 1:]:
            inner, rest = _no_input(), []
            k = i + 1
            while k < len(up):
                took = _input_of(inner, up[k][0], up[k][1], up[k + 1] if k + 1 < len(up) else None)
                if took is None and not up[k][0].startswith("-"):
                    rest.append(up[k][0])
                k += 1 + (took or 0)
            for text, dyn in inner["here"]:
                pieces.append(text)
                unseen = unseen or dyn
            doc = doc or inner["doc"]
            unseen = unseen or inner["file"] or bool(rest) or not (inner["here"] or inner["doc"])
        elif len(words) == 1 and " " in words[0]:  # PowerShell and unknown shells: a string expression writes its text
            pieces.append(words[0])
            unseen = unseen or up[0][1]
        else:
            unseen = True
    elif not (src["here"] or doc):
        unseen = True  # no input at all: the terminal, or a file descriptor the hook cannot see
    if doc:
        pieces += docs
        unseen = unseen or not docs or any(re.search(r"[$`]", body) for body in docs)
    return "\n".join(pieces), unseen


def _short_value(tok, letters):
    """git's reading of a short-option word: the letters of `-xyz` from left to right, and at the first letter that takes a value (one of
    `letters`) the rest of the word is the value ('' when the value is the next word).  None: the word holds no such letter."""
    if len(tok) < 2 or tok[0] != "-" or tok[1] == "-":
        return None
    for k in range(1, len(tok)):
        if tok[k] in letters:
            return tok[k + 1:]
    return None


def _create_opt(tok, sub):
    """The branch name an option of `git switch|checkout` that creates a branch carries: '' when the name is the next word, None when `tok`
    is no such option.  Long options match by unique prefix (--crea) and carry `=<name>`; short ones may be bundled (-fc) and carry the
    name written after the creating letter (-cNAME, -qbNAME)."""
    longs, shorts = (("create", "force-create", "orphan"), "cC") if sub == "switch" else (("orphan",), "bB")
    if tok.startswith("--"):
        key = tok[2:].split("=", 1)[0]
        if len(key) >= 2 and any(name.startswith(key) for name in longs):
            return tok.split("=", 1)[1] if "=" in tok else ""
        return None
    return _short_value(tok, shorts)


_BRANCH_LONGS = ("move", "copy", "merged", "no-merged", "color", "no-color", "column", "no-column", "contains", "no-contains", "create-reflog",
                 "edit-description", "verbose", "quiet", "track", "no-track", "set-upstream-to", "unset-upstream", "remotes", "abbrev", "no-abbrev",
                 "all", "delete", "list", "show-current", "force", "sort", "points-at", "ignore-case", "omit-empty", "format", "recurse-submodules")


def _branch_short(tok):
    """The letters of a short-option word of `git branch`, read from left to right up to the first letter that takes a value (`u`, and `t`, whose
    tracking mode is the rest of its word): that letter is the last one returned.  '' for a word that is no short-option word."""
    if len(tok) < 2 or tok[0] != "-" or tok[1] == "-":
        return ""
    for k in range(1, len(tok)):
        if tok[k] in "ut":
            return tok[1:k + 1]
    return tok[1:]


def _branch_moves(args):
    """Does `git branch` rename or copy?  A short-option word holding m, M, c or C before a letter that takes a value (-u, -t), or a long option
    of at least two letters that is a prefix of exactly one of git branch's long options, --move or --copy (--mo; --co is ambiguous)."""
    for t in args:
        if t.startswith("--"):
            key = t[2:].split("=", 1)[0]
            hits = [full for full in _BRANCH_LONGS if full.startswith(key)]
            if len(key) >= 2 and len(hits) == 1 and hits[0] in ("move", "copy"):
                return True
        elif any(ch in "mMcC" for ch in _branch_short(t)):
            return True
    return False


def _branch_lists(args):
    """Does `git branch` create nothing, as it neither renames nor copies: it deletes, lists, shows the current branch, edits a description or
    sets an upstream?  A short-option word holding d, D, l, r, a or u before any other letter that takes a value (-d, -df, -rd, -vd, -vu <up>), or
    one of the long options that do."""
    for t in args:
        if t in ("--delete", "--list", "--show-current", "--contains", "--merged", "--no-merged", "--unset-upstream", "--points-at", "--edit-description") or \
                t.startswith(("--set-upstream-to", "--list")) or any(ch in "dDlrau" for ch in _branch_short(t)):
            return True
    return False


def _push_target(word, here):
    """The directory a `git push` repository argument names when it is a local repository (`./x`, `../x`, an absolute or drive path, a
    file:// URL, a word that names an existing directory); None for a remote name or another URL (the branch is created in the remote's
    repository, which the hook does not resolve); '' when the directory cannot be resolved."""
    w = word
    if w.lower().startswith("file://"):
        w = w[7:]
        if re.match(r"/[A-Za-z]:", w):
            w = w[1:]
    elif not (w in (".", "..") or w.startswith(("./", "../", ".\\", "..\\", "/", "\\", "~")) or re.match(r"[A-Za-z]:[\\/]", w)):
        t = _join(here, w) if here is not None and not re.search(r"[:@]", w) else None
        return t if t and os.path.isdir(t) else None
    return _join(here, w) or ""


# The long options of git push / fetch / pull that take a separate value (matched also by a unique prefix of at least three letters).
_PUSH_VALUED = ("repo", "receive-pack", "exec", "push-option")
_FETCH_VALUED = ("upload-pack", "server-option", "depth", "deepen", "shallow-since", "shallow-exclude", "refmap", "negotiation-tip", "jobs", "filter",
                 "recurse-submodules-default", "submodule-prefix")
_GLOB_WHY = "a glob refspec creates branches whose names the hook cannot list"
_PUSH_WHY = "the repository a push writes to is dynamic"


def _requote(words, dyn):
    """Words back into a command line: a literal word that holds a space or a shell character is quoted; a dynamic word stays as written."""
    return " ".join(shlex.quote(w) if not d and re.search(r"[\s'\"$`;&|<>()\\]", w) else w for w, d in zip(words, dyn))


def _rebase_exec(args):
    """The command texts `git rebase` runs: the value of -x / --exec / --exec= (also bundled, -qx <cmd>, and attached, -x<cmd>), and of a
    unique prefix of --exec of at least two letters (--ex, --exe=<cmd>; --e is ambiguous for git)."""
    out, k = [], 0
    while k < len(args):
        t = args[k]
        key = t[2:].split("=", 1)[0] if t.startswith("--") else None
        if key is not None and len(key) >= 2 and "exec".startswith(key):
            if "=" in t:
                out.append(t.split("=", 1)[1])
            elif k + 1 < len(args):
                out.append(args[k + 1])
                k += 1
        elif t.startswith("-") and not t.startswith("--"):
            for j in range(1, len(t)):
                if t[j] == "x":
                    if t[j + 1:]:
                        out.append(t[j + 1:])
                    elif k + 1 < len(args):
                        out.append(args[k + 1])
                        k += 1
                    break
                if t[j] in "sXCS":  # an option that takes a value: the rest of the word (or the next word) is its value
                    k += 1 if not t[j + 1:] and t[j] != "S" else 0
                    break
        k += 1
    return out


def parse_git(words, dyn, cwd, aliases=None, depth=0, gitdir=(), work=None, sh=None):
    """One `git ...` invocation -> list of creation records.  `gitdir` holds the GIT_DIR and GIT_COMMON_DIR values the environment may give
    this invocation (_GitDirs.cands()); a --git-dir option replaces the GIT_DIR values.  Each is resolved against the directory the
    invocation runs in after every -C (git applies -C first, whatever the option order).  --work-tree / GIT_WORK_TREE alone do not move the
    ref.  `work` is the walking budget interpret() shares with the text git runs itself (a `!` alias, rebase --exec, bisect run).  `sh`
    names the shell that wrote the words: where it is not known (None) a subcommand or a branch name that holds a backslash is dynamic,
    because that shell may remove the backslash."""
    words, dyn, ins = _split_redirs(words, dyn)  # git is never handed a redirection of the shell; an update-ref --stdin reads the input ones
    i, here, defs, rd = 1, cwd, dict(aliases or {}), tuple(gitdir or ())
    while i < len(words) and words[i].startswith("-"):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            here = None if dyn[i + 1] else _join(here, words[i + 1])
        elif w == "--git-dir" and i + 1 < len(words):
            rd = tuple(c for c in rd if _gd_kind(c[0]) != "GIT_DIR") + (("GIT_DIR", words[i + 1], dyn[i + 1], True),)
        elif w.startswith("--git-dir="):
            rd = tuple(c for c in rd if _gd_kind(c[0]) != "GIT_DIR") + (("GIT_DIR", w[10:], dyn[i], True),)
        elif w == "-c" and i + 1 < len(words) and words[i + 1].lower().startswith("alias."):
            defs[words[i + 1][6:].partition("=")[0]] = words[i + 1].partition("=")[2]
        i += 2 if w in _VALUE_OPTS else 1
    if i >= len(words):
        return []

    def C(verb, names, at, dynamic, **kw):
        if sh is None and any("\\" in n for n in names):  # the unknown shell may remove the backslash: the name git gets is not known
            dynamic = True
        return _with_rds(_cr(verb, names, at, dynamic, **kw), here, rd)
    sub, a, ad = words[i], words[i + 1:], dyn[i + 1:]
    if dyn[i] or (sh is None and "\\" in sub):  # git $CMD ...: the subcommand itself is dynamic, so nothing can be matched
        return [C("dynamic subcommand", [], here, True)]
    if sub in defs and depth < 3:  # an alias: expand it (a leading ! is a shell command, run with git's environment)
        val = defs[sub]
        if val.startswith("!"):
            return interpret(val[1:] + " " + " ".join(a + [w for w, _ in ins]), here, depth + 1, gitdir=rd, sh="bash", work=work)
        vw = [w for seg in split_command(val) for w in seg]
        return parse_git(["git"] + [w for w, _ in vw] + a + [w for w, _ in ins], [False] * (len(vw) + 1) + list(ad) + [d for _, d in ins], here, defs,
                         depth + 1, rd, work, sh)

    def take(**kw):
        for k, t in enumerate(a):
            v = _create_opt(t, sub)
            if v is None:
                continue
            if v:  # -cNAME, -qbNAME, --orphan=NAME: the name is written with the option
                return C(sub, [v], here, ad[k], **kw)
            return C(sub, [a[k + 1]] if k + 1 < len(a) else [], here, k + 1 >= len(a) or ad[k + 1], **kw)
        return None
    if sub == "worktree" and a[:1] == ["add"]:
        pos, k, branch = [], 1, None
        while k < len(a):
            v = _short_value(a[k], "bB")  # -b NAME, -bNAME, -fb NAME
            if v is not None:
                if branch is None:
                    branch = (v, ad[k]) if v else (a[k + 1], ad[k + 1]) if k + 1 < len(a) else ("", True)
                k += 1 if v else 2
                continue
            if a[k] == "--reason":
                k += 2
                continue
            if a[k] != "--" and not a[k].startswith("-"):
                pos.append((a[k], ad[k]))
            k += 1
        path = _join(here, pos[0][0]) if pos and not pos[0][1] else None
        if branch is not None:
            return [C("worktree add", [branch[0]] if branch[0] else [], here, not branch[0] or branch[1] or any(d for _, d in pos), kind="worktree",
                      path=path)]
        if len(pos) == 1 and "--detach" not in a:  # git names the branch after the directory (and creates it only when it is new)
            return [C("worktree add", [re.split(r"[\\/]", pos[0][0].rstrip("/\\"))[-1]], here, pos[0][1], kind="worktree", path=path)]
        detached = C("wt-detached", ["detached/" + re.split(r"[\\/]", pos[0][0].rstrip("/\\"))[-1]], here, bool(pos) and pos[0][1], kind="worktree", path=path,
                     commit=pos[1][0] if len(pos) > 1 else None) if pos else None
        if len(pos) == 2 and "--detach" not in a and "/" not in pos[1][0] and pos[1][0] not in ("HEAD", "@"):  # a remote-only branch name creates a branch
            return [C("dwim", [pos[1][0]], here, pos[1][1], kind="worktree", path=path), detached]
        return [detached] if detached else []
    if sub == "branch":
        move = _branch_moves(a)  # rename / copy: the last name is the new branch, whatever else (-r, -a) stands beside the option
        if not move and _branch_lists(a):
            return []
        # --sort <key> and --format <format> (and their unique prefixes) take the next word as their value and list nothing by themselves
        valued = {k + 1 for k, t in enumerate(a) if t in ("--so", "--sor", "--sort", "--form", "--forma", "--format")}
        pos = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-") and k not in valued]
        return [C(sub, [pos[-1 if move else 0][0]], here, pos[-1 if move else 0][1])] if pos else []
    if sub in ("switch", "checkout"):
        cr = take()
        if cr:
            return [cr]
        tracked = [t for t in a if t.startswith(("--track", "-t"))]
        pos = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-") and t != "--"]
        if tracked and pos:  # --track origin/x creates a local branch x
            return [C(sub, [pos[0][0].split("/", 1)[-1]], here, pos[0][1])]
        if sub == "switch" and len(pos) == 1 or sub == "checkout" and len(pos) == 1 and "--" not in a[:1]:
            return [C("dwim", [pos[0][0]], here, pos[0][1])]  # a remote-only name creates a tracking branch; enforce checks that
        return []
    if sub == "stash" and a[:1] == ["branch"]:
        return [C("stash branch", a[1:2], here, len(a) < 2 or ad[1])]
    if sub == "symbolic-ref":  # -m <reason> is no ref; HEAD <target> and <name> <target> write the branch the word names
        pos = _symbolic_ref_args(a, ad)
        words = [w for w, _ in pos]
        if len(pos) >= 2 and words[0] == "HEAD" and _HEADS.match(words[1]):
            return [C(sub, [words[1][11:]], here, False)]
        if pos and _HEADS.match(words[0]):
            return [C(sub, [words[0][11:]], here, False)]
        if len(pos) >= 2 and ((pos[0][1] and _maybe_heads(words[0])) or (words[0] == "HEAD" and pos[1][1] and _maybe_heads(words[1]))):
            return [C(sub, [], here, True)]  # a dynamic ref word that may name a branch, as for every other creating verb
        return []
    if sub == "update-ref":
        stdin, delete, pos, src = _update_ref_args(a + [w for w, _ in ins], ad + [d for _, d in ins])
        if stdin:  # the instructions arrive on stdin: interpret() reads them from the sources that feed it
            return [dict(C(sub, [], here, False), stdin=True, src=src)]
        if delete or not pos:
            return []
        word, dynamic = pos[0]  # the first positional word is the ref it writes
        if _HEADS.match(word):
            return [C(sub, [word[11:]], here, False)]
        known = word == "HEAD" or not _maybe_heads(word)  # a ref the word certainly names outside refs/heads/
        # behind xargs the input supplies words in any position: the appended `$stdin` marks it
        if not known and (dynamic or any(w == "$stdin" and d for w, d in pos)):
            return [C(sub, [], here, True)]
        return []
    if sub in ("fetch", "pull", "push"):
        longs, shorts = (_PUSH_VALUED, ("-o",)) if sub == "push" else (_FETCH_VALUED, ("-o", "-j"))
        valued = {k + 1 for k, t in enumerate(a) if t in shorts or (t.startswith("--") and "=" not in t and len(t) >= 5
                                                                    and any(full.startswith(t[2:]) for full in longs))}
        pk = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-") and k not in valued]
        names, glob = [], False
        for t, _d in pk[1:]:  # the destinations of the refspecs: under refs/heads/ (whatever follows is the name) or bare; refs/<other>/ is no branch
            m = re.fullmatch(r"\+?([^:]*):(?:%s([^:]+)|(?!%s)([^:]+))" % (_HEADS_CI, _REFS_CI), t)
            if m is None or (sub == "push" and not m.group(1)):  # a push with an empty source deletes its destination; fetch and pull read it as HEAD
                continue
            dest = m.group(2) or m.group(3)
            glob = glob or "*" in dest
            names += [] if "*" in dest else [dest]
        if not names and not glob:
            return []
        if sub == "push" and pk[0][0] != ".":  # a push creates the branch in the repository it pushes to
            target = "" if pk[0][1] else _push_target(pk[0][0], here)
            if target is None:
                return []  # a remote: its repository is not resolved
            if not target:
                return [dict(_cr("push", names, here, True), redirect=True, gitdir=None, why=_PUSH_WHY)]
            return ([_cr("push", names, target, False)] if names else []) + ([dict(_cr("push", [], target, True), why=_GLOB_WHY)] if glob else [])
        return ([C(sub, names, here, False)] if names else []) + ([dict(C(sub, [], here, True), why=_GLOB_WHY)] if glob else [])
    if sub == "rebase" and depth < 3:  # git runs the --exec text with a shell, in the directory and GIT_DIR state of this invocation
        return [c for text in _rebase_exec(a) for c in interpret(text, here, depth + 1, defs, rd, "bash", work=work)]
    if sub == "bisect" and a[:1] == ["run"] and len(a) > 1 and depth < 3:
        return interpret(_requote(a[1:], ad[1:]), here, depth + 1, defs, rd, "bash", work=work)
    if sub == "flow":
        return [C("git flow", [], here, True, kind="auto", tool=True)]
    return []


def _script(path, here):
    """Text of a script the command runs, when it is a small file we can read (bash x.sh, ./x.sh, .\\x.ps1, source x.sh)."""
    p = _join(here, path) if here else None
    try:
        if p and os.path.isfile(p) and os.path.getsize(p) <= 65536:
            with open(p, "rb") as fh:
                return fh.read().decode("utf-8-sig", "replace")
    except OSError:
        pass
    return None


def _heredocs(cmd, every=None):
    """-> (command text without heredoc bodies, [bodies fed to a shell]).  A body fed to cat or a file is data, not a command.  `every`, when a
    list is given, receives every body: an `update-ref --stdin` reads them as instructions."""
    lines, out, bodies, k = cmd.split("\n"), [], [], 0
    while k < len(lines):
        line = lines[k]
        out.append(line)
        k += 1
        m = re.search(r"<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", line)
        if m and "<<<" not in line:
            body = []
            while k < len(lines) and (lines[k].strip("\t") if m.group(1) else lines[k]).rstrip("\r") != m.group(3):
                body.append(lines[k])
                k += 1
            k += 1
            if every is not None:
                every.append("\n".join(body))
            if re.search(r"(?:^|[|;&\s])(?:sudo\s+)?(?:(?:ba|z|da|k)?sh|powershell|pwsh|source|iex|invoke-expression)\b", line, re.I):
                bodies.append("\n".join(body))
    return "\n".join(out), bodies


def _git_subcommands(text):
    """The subcommand after every `git` word, in text order: its first word after the global options and the values of those that take one
    (`git -C ../B nb x` names `nb`).  One right-to-left pass fills `first[p]`, the index of the first word from p on that is neither an option
    nor an option value, so the text is read once whatever the number of git words."""
    toks = re.sub(r"(?<![A-Za-z0-9_])git(?=[<>])", "git ", text).split()  # `git>/dev/null nb x`: the operator ends the word git
    first = [None] * (len(toks) + 2)
    for p in range(len(toks) - 1, -1, -1):
        if toks[p].startswith("-"):
            first[p] = first[p + (2 if toks[p] in _VALUE_OPTS else 1)]
        elif _is_redirection(toks[p]):  # a redirection between git and its subcommand: it and its target, when that is the next word, are no subcommand
            first[p] = first[p + (1 if _REDIR_OP_PS.match(toks[p]).end() < len(toks[p]) else 2)]
        else:
            first[p] = p
    subs = []
    for k, tok in enumerate(toks):
        if first[k + 1] is not None and re.search(r"(?:^|\W)git$", tok):
            m = re.match(r"[A-Za-z][\w-]*", toks[first[k + 1]])
            subs += [m.group(0)] if m else []
    return subs


_PS_ENV = re.compile(r"\$\{?env:([A-Za-z_][A-Za-z0-9_]*)\}?(\+?=)?(.*)$", re.I | re.S)
_ENV_PATH = re.compile(r"env:[\\/]?([A-Za-z_][A-Za-z0-9_]*)", re.I)
_SET_ENV = re.compile(r"setenvironmentvariable\(([^)]*)", re.I)
_TOOL_SHELL = {"Bash": "bash", "Monitor": "bash", "PowerShell": "ps"}  # the shell a hooked tool runs its command in (other tools: not known)
_SHELL_OF = dict([(s, "bash") for s in _SHELLS] + [("powershell", "ps"), ("pwsh", "ps"), ("cmd", "cmd")])
_OPAQUE = "git branch $opaque"  # the text of an encoded command that does not decode: a dynamic creation


def _shell_flag(exe, word):
    """How the shell `exe` reads the option word `word`: "command" (the words after it are the text it runs), "encoded" (the next word is
    the base64 UTF-16LE text it runs) or None.  powershell and pwsh read an option written with -, -- or / by its name or a prefix of it:
    -c, -co, -Comm ... -Command, -cwa and a prefix of -CommandWithArgs longer than -command run the words after them as text, -ec and a prefix
    of -EncodedCommand (-e, -en, -enc, -EncodedC) run an encoded command; -ex (ExecutionPolicy) and -encodeda (EncodedArguments) are neither.
    The POSIX shells read -c and the bundled short options that hold a c (-lc, -ec, -ce), cmd reads /c and /k."""
    flag = _bare(word).lower()
    if exe not in ("powershell", "pwsh"):
        return "command" if re.fullmatch(r"-[a-z]*c[a-z]*|/c|/k|//c", flag) else None
    m = re.fullmatch(r"(?:--?|/)([a-z]+)", flag)
    name = m.group(1) if m else ""
    if name == "ec" or (name and "encodedcommand".startswith(name)):
        return "encoded"
    if name and ("command".startswith(name) or name == "cwa" or (len(name) > 7 and "commandwithargs".startswith(name))):
        return "command"
    return None


def _decoded(word):
    """The text of a base64 UTF-16LE word (PowerShell's -EncodedCommand value), None when it is neither."""
    try:
        return base64.b64decode(word).decode("utf-16-le")
    except ValueError:
        return None


def _child_script(exe, rest, opaque=None):
    """The text the shell `exe` runs through the first command or encoded-command option among its arguments `rest` (a flag with no word
    after it has no value): the script after -c of a POSIX shell, the words after the option joined by spaces for powershell, pwsh and cmd,
    the decoded text of an encoded command (`opaque` when it does not decode); None when there is no such option."""
    for k, w in enumerate(rest[:-1]):
        kind = _shell_flag(exe, w)
        if kind == "encoded":
            text = _decoded(rest[k + 1])
            return opaque if text is None else text
        if kind:
            return rest[k + 1] if exe in _SHELLS else " ".join(rest[k + 1:])
    return None


def _start_process(rest, rdyn):
    """The git a PowerShell `Start-Process` starts, from the words after it: -> (the -ArgumentList text, (the -WorkingDirectory value, dynamic) or
    None), None when no git program is among its words.  Each parameter takes its value from the next word or after a colon, and is read by its
    full name or a prefix of it that names no other parameter (-a, -wo; -w would be Wait, WindowStyle or WorkingDirectory); a list written with
    commas is one value."""
    if not any(_exe(w) == "git" for w in rest):
        return None
    args, wd, k = "", None, 0
    while k < len(rest):
        word, k = rest[k], k + 1
        name, colon, value = word[1:].partition(":") if word.startswith("-") and len(word) > 1 else ("", "", "")
        name, dynamic = name.lower(), rdyn[k - 1]
        full = "argumentlist" if name and "argumentlist".startswith(name) else "workingdirectory" if len(name) > 1 and "workingdirectory".startswith(name) else None
        if full is None:
            continue
        if not value:  # `-ArgumentList 'x'`, and `-ArgumentList: 'x'` (a colon with nothing after it takes the next word)
            value, dynamic = (rest[k], rdyn[k]) if k < len(rest) else ("", False)
            k += 1
        parts = [value]
        while full == "argumentlist" and k < len(rest) and (parts[-1].endswith(",") or rest[k].startswith(",")):
            parts.append(rest[k])
            k += 1
        value = " ".join(parts)
        if full == "argumentlist":
            args = value
        else:
            wd = (value, dynamic)
    return args, wd


def _ps_env_item(rest, rdyn):
    """Set-Item / New-Item on the Env: drive -> (name, value, dynamic) when it sets a GIT_DIR spelling, else None."""
    opts, pos, k = {}, [], 0
    while k < len(rest):
        w = rest[k]
        if w.startswith("-") and len(w) > 1:
            key = next((full for full in ("path", "literalpath", "value", "name") if full.startswith(w[1:].lower())), None)
            if key and k + 1 < len(rest):
                opts[key] = (rest[k + 1], rdyn[k + 1])
                k += 1
        else:
            pos.append((w, rdyn[k]))
        k += 1
    path = opts.get("path") or opts.get("literalpath") or (pos.pop(0) if pos else ("", False))
    m = _ENV_PATH.fullmatch(path[0])
    if not m and re.fullmatch(r"env:[\\/]?", path[0], re.I) and "name" in opts:
        m = _ENV_PATH.fullmatch("env:" + opts["name"][0])
    name = _gd_name(m.group(1)) if m else None
    if not name:
        return None
    value = opts.get("value") or (pos[0] if pos else (None, True))  # None: no value given
    return name, value[0], value[1] or path[1]


def _git_dir_ops(gds, exe, rest, rdyn):
    """Apply a shell command that changes GIT_DIR (export / declare / unset / cmd set / Remove-Item, Set-Item and New-Item Env:);
    -> True when `exe` is one of them."""
    if exe in ("export", "declare", "typeset", "readonly", "local"):
        flags = [w for w in rest if w[:1] in "-+" and len(w) > 1]
        if exe != "export" and any(f.startswith("-") and "n" in f for f in flags):  # declare -n: a name reference the walker does not follow
            for w in rest:
                for part in w.split("=", 1):
                    if not part.startswith(("-", "+")) and _gd_name(part):
                        gds.unknown(_gd_name(part))
            return True
        unexport = any(f.startswith("+") and "x" in f for f in flags) or (exe == "export" and any(f.startswith("-") and "n" in f for f in flags))
        export = not unexport and (exe == "export" or any(f.startswith("-") and "x" in f for f in flags))
        for w, d in zip(rest, rdyn):
            name = None if w[:1] in "-+" else _gd_name(w)
            if name and "=" in w:
                gds.assign("bash", name, w.split("=", 1)[1], d or _appends(w), True if export else None)
            if name and (unexport or export and "=" not in w):
                gds.export("bash", name, export)
    elif exe in ("read", "readarray", "mapfile", "getopts", "let"):  # they assign the variables they name, from text the hook cannot see
        for w in rest:
            name = None if w.startswith("-") else _gd_name(w)
            if name:
                gds.unknown(name)
    elif exe == "printf":  # printf -v NAME ...
        for k, w in enumerate(rest):
            target = rest[k + 1] if w == "-v" and k + 1 < len(rest) else w[2:] if w.startswith("-v") and len(w) > 2 else None
            if target and _gd_name(target):
                gds.unknown(_gd_name(target))
    elif exe in ("set-content", "sc", "add-content", "ac"):  # Set-Content Env:GIT_DIR <value>: not modelled
        item = _ps_env_item(rest, rdyn)
        if item:
            gds.unknown(item[0])
    elif exe == "unset":
        for w in ([] if "-f" in rest else rest):
            name = None if w.startswith("-") else _gd_name(w)
            if name:
                gds.remove("bash", name)
    elif exe == "set":  # cmd: set GIT_DIR=x (set /p reads the value; an empty value removes the variable)
        k = next((k for k, w in enumerate(rest) if "=" in w and _gd_name(w)), None)
        if k is not None:
            name, value = _gd_name(rest[k]), rest[k].split("=", 1)[1]
            if any(w.lower() in ("/p", "/a") for w in rest[:k]):
                gds.assign("cmd", name, "%" + name + "%", True, True)
            elif value:
                gds.assign("cmd", name, value, rdyn[k], True)
            else:
                gds.remove("cmd", name)
    elif exe in ("remove-item", "ri", "rm", "del", "erase", "rd", "rmdir", "clear-item", "cli"):
        for w in rest:
            m = _ENV_PATH.fullmatch(w)
            if m and _gd_name(m.group(1)):
                gds.remove("ps", _gd_name(m.group(1)))
    elif exe in ("set-item", "si", "new-item", "ni"):
        item = _ps_env_item(rest, rdyn)
        if item and (item[1] or "").lower() in ("", "$null") and item[1] is not None:
            gds.remove("ps", item[0])
        elif item:
            gds.assign("ps", item[0], "$value" if item[1] is None else item[1], item[2], True)
    else:
        return False
    return True


MAX_CONTEXTS = 8  # directory / GIT_DIR states a command line is walked in, and in which text found inside it is judged
WORK_LIMIT = 8 * MAX_TEXT  # characters the detector walks for one command line, nested text and every further state included
STEP_COST = 128  # walking one command in one further state (a cd there may ask the file system), counted in characters
TEXT_COST = 8 * STEP_COST  # walking one substituted text in one state for the states it leaves (a nested walk), counted in characters
_STATEFUL = frozenset(("cd", "pushd", "chdir", "set-location", "sl", "push-location", "popd", "pop-location", "export", "declare", "typeset", "readonly",
                       "local", "unset", "set", "remove-item", "ri", "rm", "del", "erase", "rd", "rmdir", "clear-item", "cli", "set-item", "si", "new-item",
                       "ni", "set-alias", "sal", "start-process", "find", "eval", "iex", "invoke-expression", "git", "gh", "gt", "claude", "source", ".",
                       "powershell", "pwsh", "cmd", "read", "readarray", "mapfile", "getopts", "let", "printf", "set-content", "sc", "add-content", "ac",
                       "mkdir", "md") + _SHELLS)  # the commands whose effect depends on, or changes, the directory and GIT_DIR state
_PROGRAMS = frozenset(_KNOWN) | _STATEFUL | frozenset(_WRAP)


def _spelled(word):
    """The program a program word may name in a shell the hook cannot name, which may or may not remove a backslash, a backtick and a caret:
    the lower-case name of a program the detector knows that the word spells once the backtick and caret, or all three characters, are
    removed (`g\\it`, `g^it`, ``g`it``); None when the word as written names no other program than it reads as (a path keeps its backslashes)."""
    if not re.search(r"[\\`^]", word):
        return None
    base = _exe(word)
    for text in (re.sub(r"[`^]", "", word), re.sub(r"[\\`^]", "", word)):
        name = _exe(text)
        if name != base and name in _PROGRAMS:
            return name
    return None


_OVER_WORK = "the command takes more walking through nested text and directory or GIT_DIR states than the hook does"
_IN_PLACE = ("eval", "iex", "invoke-expression", "source", ".")  # text the current shell runs itself: its changes reach the commands after it
_DIR_CMDS = ("cd", "pushd", "chdir", "set-location", "sl", "push-location")
# Wrappers that start the command as a program of its own (env cannot run the cd builtin): a builtin behind them changes nothing in the shell.
_ALONE = frozenset(("env", "sudo", "doas", "nohup", "nice", "xargs", "timeout", "watch", "wsl", "uv", "npx", "stdbuf", "setsid", "exec"))
_ENV_VALUE = ("-C", "--chdir", "-u", "--unset", "-S", "--split-string", "-P", "-a", "--argv0")  # options of env that take the next word as their value
# Text that may change the directory or GIT_DIR of the shell that runs it (checked before such text is walked for its end states).
_CHANGES = re.compile(r"(?:^|[\s;&|({])(?:cd|pushd|popd|chdir|set-location|sl|push-location|pop-location|export|declare|typeset|readonly|local|unset|"
                      r"set|remove-item|ri|rm|del|erase|rd|rmdir|clear-item|cli|set-item|si|new-item|ni|eval|iex|invoke-expression|source|\.|read|"
                      r"readarray|mapfile|getopts|let|printf|set-content|sc|add-content|ac|builtin|command)"
                      r"(?=[\s;&|)}]|$)|\$\{?env:|setenvironmentvariable|\.ps1\b|git_(?:common_)?dir\s*\+?=", re.I)
_PS_PAREN = re.compile(r"(?<!\$)\(([^()]*)\)")  # a PowerShell (..) or @(..) inside a command: it runs its pipeline in the current scope


def _unquoted(text):
    """`text` with the inside of every quoted string blanked (same length): PowerShell runs no (..) written inside a string."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if (c == '"' and text[j] in "\\`" and j + 1 < n and text[j + 1] == '"') else 1
            out[i + 1:j] = " " * (min(j, n) - i - 1)
            i = j
        i += 1
    return "".join(out)


_REDIR = re.compile(r"\d*(?:>>?\|?|<<?<?|>&|<&)(.*)$", re.S)  # a redirection word: the operator and the target written with it


def _plain_args(rest, dyn):
    """The (word, dynamic) arguments of a command without its redirections (`>x`, `2>`, `> x`, `<<EOF`)."""
    out, skip = [], False
    for w, d in zip(rest, dyn):
        m = None if skip else _REDIR.match(w)
        if not skip and not m:
            out.append((w, d))
        skip = bool(m) and not m.group(1)
    return out


def _wrapped_dir(words, dyn, i):
    """The directory that `env -C <dir>` / `env --chdir[=]<dir>` or `sudo -D <dir>` / `sudo --chdir[=]<dir>` among the wrapper words
    words[:i] names for the program they run: (value, dynamic), or None."""
    found, via, k = None, None, 0
    while k < i:
        w = words[k]
        if w.lower() in _WRAP:
            via = w.lower()
        elif via in ("env", "sudo"):
            flag = "-C" if via == "env" else "-D"
            if w in (flag, "--chdir") and k + 1 < len(words):
                found, k = (words[k + 1], dyn[k + 1]), k + 1
            elif w.startswith("--chdir="):
                found = (w[8:], dyn[k])
            elif w.startswith(flag) and len(w) > 2:
                found = (w[2:], dyn[k])
        k += 1
    return found


def _env_split(words, dyn):
    """`env -S '<words>'` (also -S<words>, --split-string[=]<words>) runs the words of its value: they replace the option."""
    ow, od, k, via = [], [], 0, False
    while k < len(words):
        w = words[k]
        if w.lower() == "env":
            via = True
        elif via and (w in ("-S", "--split-string") and k + 1 < len(words) or w.startswith("--split-string=") or (w.startswith("-S") and len(w) > 2)):
            text, d = (words[k + 1], dyn[k + 1]) if w in ("-S", "--split-string") else (w.split("=", 1)[1] if w.startswith("--") else w[2:], dyn[k])
            part = [x for seg in split_command(text) for x in seg]
            ow += [x for x, _ in part]
            od += [d or xd for _, xd in part]
            k += 2 if w in ("-S", "--split-string") else 1
            continue
        elif via and not w.startswith("-") and not _ASSIGN.match(w):
            via = False  # the program: its own options are not env's
        ow.append(w)
        od.append(dyn[k])
        k += 1
    return ow, od


def _anywhere(verb, why):
    """A record that denies wherever the hook runs: the hook cannot tell which repository the command acts on."""
    return dict(_cr(verb, [], None, True), anywhere=True, why=why)


def _state_key(st):
    here, gds, dirs = st
    return isinstance(here, _Missing), here, getattr(here, "prior", None), getattr(here, "follow", None), tuple(sorted(gds.items())), tuple(dirs)


def _snap(states):
    return [[h, g.copy(), list(d)] for h, g, d in states]


def _merge(*groups):
    """The states of every group, each once (a state is [directory, _GitDirs, pushd stack])."""
    seen, out = set(), []
    for group in groups:
        for st in group:
            key = _state_key(st)
            if key not in seen:
                seen.add(key)
                out.append(st)
    return out


def _unfollow(states, token):
    """The && chain of the frame `token` names ended: a directory an element of it created is again a missing directory for the commands
    after it (the missing-directory rule: they run in the prior directory, unresolved)."""
    def ours(h):
        return getattr(h, "follow", None) is not None and h.follow[2] is token
    if not any(ours(h) for h, _g, _d in states):
        return states
    return _merge([[_missing(str(h), h.prior) if ours(h) else h, g, d] for h, g, d in states])


# Definite and possible changes.  A line is a list of commands joined by '&&' and '||' and ended by ';', a newline or '&'; groups, brace
# blocks and compound commands hold lists of their own (a frame each).  A change of the directory or of GIT_DIR / GIT_COMMON_DIR is
# definite for a later command only when the shell certainly makes it first: the first command of a list (it always runs), or a command
# joined to the later one by '&&' alone, starting from a command that is itself first or joined by '&&'.  Every other change is possible:
# the commands after it are walked in the states before and after it.  So a list that ends hands on every state its commands reached, a
# command after '||' runs in any of them, a list sent to the background keeps the state it started in as well, and a group, a brace block
# (a function body, a PowerShell script block) or a compound command keeps the state it was opened in; inside a compound command
# (if / while / until / for / select / case) every change is possible.  In bash a group, a background list, every pipeline command but the
# last and substituted text run in a subshell: the commands after them keep the states before them.  `made` holds the directories the
# current && chain created (mkdir, git init, git clone, git worktree add): a cd into one of them is followed by the later elements of the
# chain.
def _frame(kind, states):
    snap = _snap(states)  # read only while the frame is open: "open" when it closes, "start" through a copy
    return {"kind": kind, "open": snap, "start": snap, "entry": None, "reached": [], "conn": None, "inside": False, "cond": kind == "K(", "made": {},
            "token": object()}


def _enter(fr, states):
    """A command of the frame's current list starts: after '||' it runs when an earlier command failed, in any state the list reached."""
    if fr["conn"] == "||":
        states = _unfollow(_merge(_snap(fr["reached"]), states), fr["token"])
    fr["entry"], fr["inside"] = _snap(states), True
    return states


def _leave(fr, states):
    """The command ends: one that may not have run (after '||', or inside a compound command) keeps the states it was entered in."""
    if fr["inside"]:
        if fr["conn"] == "||" or fr["cond"]:
            states = _merge(fr["entry"], states)
        fr["reached"] = _merge(fr["reached"], _snap(states))
        fr["inside"] = False
    return states


def _end_list(fr, states, background=False, last=False, subshell=False):
    """The list ends (';', newline, '&', the end of its frame): the commands after it run in every state it reached; a list run in the
    background keeps the state it started in as well, and only that one where the background list runs in a subshell (bash).  `last`: the
    frame closes, no list follows in it."""
    states = _leave(fr, states)
    states = _merge(states, _snap(fr["reached"])) if len(fr["reached"]) > 1 else states
    if background:
        states = _snap(fr["start"]) if subshell else _merge(_snap(fr["start"]), states)
    states = _unfollow(states, fr["token"])
    if not last:
        fr.update(start=_snap(states), reached=[], conn=None, entry=None, made={})
    return states


_CLONE_VALUE = frozenset(("-o", "-b", "-u", "-c", "-j", "--origin", "--branch", "--upload-pack", "--template", "--reference", "--reference-if-able",
                          "--separate-git-dir", "--depth", "--shallow-since", "--shallow-exclude", "--jobs", "--filter", "--server-option", "--config",
                          "--bundle-uri", "--ref-format"))
_INIT_VALUE = frozenset(("-b", "--initial-branch", "--separate-git-dir", "--template", "--object-format", "--ref-format"))


def _git_new_repo(words, dyn, run):
    """The directory a `git init` / `git clone` invocation makes a new repository in (`run` for a bare `git init`), or None."""
    words, dyn, _ins = _split_redirs(words, dyn)
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            run = None if dyn[i + 1] else _join(run, words[i + 1])
        i += 2 if words[i] in _VALUE_OPTS else 1
    if i >= len(words) or words[i] not in ("init", "clone"):
        return None
    sub, args, k, pos = words[i], words[i + 1:], 0, []
    values = _INIT_VALUE if sub == "init" else _CLONE_VALUE
    while k < len(args):
        if args[k] == "--":
            pos += args[k + 1:]
            break
        if args[k].startswith("-"):
            k += 2 if args[k] in values else 1
            continue
        pos.append(args[k])
        k += 1
    if sub == "init":
        return _join(run, pos[0]) if pos else run
    if len(pos) >= 2:
        return _join(run, pos[1])
    name = re.split(r"[\\/:]", pos[0].rstrip("/\\"))[-1] if pos else ""
    name = name[:-4] if name.endswith(".git") else name
    return _join(run, name) if name else None


def interpret(cmd, cwd, depth=0, aliases=None, gitdir=(), sh=None, dirs=(), final=None, work=None):
    """Every lane-creating invocation inside a command line: recurses into bash -c / powershell -Command / cmd /c / -EncodedCommand / eval / $(..) /
    here-documents fed to a shell / quoted text fed to a shell, follows literal variables and aliases, and reads small script files.
    `gitdir` holds the GIT_DIR and GIT_COMMON_DIR values the line inherits (_GitDirs.cands()), `sh` names the shell that runs it (bash, ps,
    cmd; None: not known) and `dirs` its pushd stack.  A prefix or `env` assignment of GIT_DIR applies to its own invocation; an exported,
    PowerShell or cmd assignment to every later git invocation of the line until a removal ends it.  A standalone `GIT_DIR=x` that is not
    exported reaches git only if the shell exported GIT_DIR before, so a later creation is judged both in that repository and where it runs.
    The line is walked in a set of states (directory, GIT_DIR values, pushd stack).  Only a definite change replaces the states (see
    _frame): a change after '&&' or '||' that a later list does not certainly follow, inside a compound command, a brace block, or made by
    text the shell runs itself (eval, iex, source, `.`, a PowerShell script) is possible: the commands after it are walked in the states
    before and after it.  In bash a group, a background list, a pipeline command other than the last and substituted text ($(..), <(..),
    backticks) run in a subshell and change nothing after them; in PowerShell, cmd and a shell the hook cannot name they are possible changes
    as well.  A cd or export behind a program wrapper (env, sudo, ...) changes nothing; `env -C <dir>` and `sudo -D <dir>` run the program they
    wrap in <dir>.  Text found inside the line ($(..), here-documents, quoted text fed to a shell, a PowerShell (..)) is judged in every
    directory and GIT_DIR state the line passes through.  `final` receives the end states (directory, cands, pushd stack); `work` is the
    walking budget the whole line shares ([characters left of WORK_LIMIT, whether a script or source file was named by a relative path]).
    At the top of a walk the state caps deny only a line that yields a creation or names such a relative script: a line that creates
    nothing places nothing in a repository, whatever the number of states."""
    top = depth == 0 and final is None and work is None
    work = [WORK_LIMIT, False] if work is None else work
    if len(cmd) > MAX_TEXT:  # too long to inspect: whatever follows the padding must not pass unseen
        return [dict(_cr("long command", [], cwd, True), why="the command is longer than %d characters and is not inspected" % MAX_TEXT)]
    work[0] -= len(cmd)
    if work[0] < 0:
        return [_anywhere("nested text", _OVER_WORK)]
    out, early, env, galias, over, unseen_git = [], [], {}, {}, [], []
    states = [[cwd, _GitDirs(gitdir, sh), list(dirs)]]
    contexts, noted, bash = [], set(), sh == "bash"

    def note(here, cands):  # a missing directory counts with its prior directory and the && chain it follows
        key = (here, getattr(here, "prior", None), getattr(here, "follow", None), cands)
        if len(contexts) <= MAX_CONTEXTS and key not in noted:
            noted.add(key)
            contexts.append((here, cands))
    note(cwd, states[0][1].cands())
    docs = []  # every here-document body of the text: the instructions of an update-ref --stdin may be one
    cmd, bodies = _heredocs(cmd, docs)
    cmd = _continued(cmd, sh)  # the offsets of the substituted texts below are the lexer's
    subs = [(m.start(), m.group(1) or m.group(2) or "") for m in _SUBST.finditer(cmd)]
    subs += [(m.start(), cmd[m.start(1):m.end(1)]) for m in _PS_PAREN.finditer(_unquoted(cmd))] if sh == "ps" else []  # PowerShell (..), @(..)
    inner = []  # (text, shell) the line runs somewhere: judged after the walk in every context it passes through
    if depth < 3:
        inner += [(body, None) for body in bodies] + [(text, sh) for _, text in subs if text]
        pipe = _ECHO_PIPE.match(cmd)
        inner += [(pipe.group(1).strip(), "bash")] if pipe else []
        if _SINK.search(cmd):
            for m in _QUOTED.finditer(cmd):
                body = (m.group(1) or m.group(2) or "").replace("\\n", "\n")  # printf 'git branch x\n' | sh
                inner += [(body, None)] if re.search(r"\bgit\b", body) else []
        inner = [(text, ish) for text, ish in inner if _gated(text)]  # text without a gate word creates nothing

    def relative(path):  # a script named by a relative path: its text may differ from one directory to another
        if path and _join(None, path) is None:
            work[1] = True

    def made(path, kind):
        if path is not None:
            frames[-1]["made"][pkey(str(path))] = kind

    def segment(words, dyn):
        """Apply one command to every state.  -> (states changed, end states of text the current shell ran itself)."""
        if env:  # literal variables: g=git; $g branch x   /   $g = 'git'; & $g branch x
            for k, w in enumerate(words):
                nw = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: env.get(m.group(1), m.group(0)), w)
                if nw != w:
                    if isinstance(w, _Redir):  # the target of a redirection: the operator, and so the redirection, stays
                        nw = _redir_like(w, nw)
                    words[k], dyn[k] = nw, bool(re.search(r"[$`%()]", nw))
        ps = _PS_ENV.match(words[0]) if words else None
        if ps and _gd_name(ps.group(1)) and (ps.group(2) or words[1:2] in (["="], ["+="])):  # PowerShell $env:GIT_DIR = 'x' ($null or '' removes it)
            if ps.group(2) and (ps.group(3) or len(words) < 2):
                value, d = ps.group(3), bool(re.search(r"[$`%()]", ps.group(3)))
            else:
                at = 1 if ps.group(2) else 2
                value, d = (words[at], dyn[at]) if len(words) > at else ("", False)
            for st in states:
                if value.lower() in ("", "$null"):
                    st[1].remove("ps", _gd_name(ps.group(1)))
                else:  # += appends to a value the hook cannot see
                    st[1].assign("ps", _gd_name(ps.group(1)), value, d or ps.group(2) == "+=" or words[1:2] == ["+="], True)
            return True, []
        se = _SET_ENV.search(" ".join(words)) if words and "setenvironmentvariable(" in words[0].lower() else None
        if se:  # [Environment]::SetEnvironmentVariable('GIT_DIR', 'x'[, 'Process'])
            args = [a.strip() for a in se.group(1).split(",")]
            if _gd_name(args[0]) and (len(args) < 3 or args[2].lower().endswith("process")):
                value = args[1] if len(args) > 1 else ""
                for st in states:
                    if value.lower() in ("", "$null"):
                        st[1].remove("ps", _gd_name(args[0]))
                    else:
                        st[1].assign("ps", _gd_name(args[0]), value, bool(re.search(r"[$`%()]", value)), True)
            return True, []
        if len(words) >= 3 and words[1] == "=" and words[0].startswith("$"):  # PowerShell $name = 'value' or $name = <command>
            if len(words) == 3:
                env[words[0][1:]] = words[2]
            words, dyn = words[2:], dyn[2:]  # the right side runs when it is a command: $out = git switch -c x
        if len(words) > 1 and "env" in (w.lower() for w in words) and any(w.startswith(("-S", "--split-string")) for w in words):
            words, dyn = _env_split(words, dyn)
        if words and all(_ASSIGN.match(w) for w in words):  # NAME=value without a command: shell variables
            for w, d in zip(words, dyn):
                for st in states if _gd_name(w) else ():
                    st[1].assign("bash", _gd_name(w), w.split("=", 1)[1], d or _appends(w), None)
                name = w.split("=", 1)[0]
                if _appends(w):  # NAME+=value: a value the hook does not know
                    env.pop(name[:-1], None)
                else:
                    env[name] = w.split("=", 1)[1]
            return True, []
        low = [w.lower() for w in words]
        if low[:1] in (["for"], ["select"]) and len(words) > 1 and _gd_name(words[1]):  # for GIT_DIR in ...: the loop assigns it
            for st in states:
                st[1].unknown(_gd_name(words[1]))
            return True, []
        for k in range(len(words) - 1):  # builtin export GIT_DIR=x, command declare -x GIT_DIR=x: not modelled, the repository is unknown
            if low[k] in ("builtin", "command"):
                nxt = next((x for x in low[k + 1:] if not x.startswith("-")), "")
                names = [_gd_name(x) for x in words[k + 2:] if _gd_name(x)] if nxt in ("export", "declare", "typeset", "local", "readonly") else []
                for st in states:
                    for name in names:
                        st[1].unknown(name)
                if names:
                    return True, []
        i = 0
        while i < len(words):
            j = _skip_redirs(words, i)  # a redirection of the shell is no word of the command: >/dev/null git switch -c x, 2>&1 bash ./mk
            if j != i:
                i = j
                continue
            if not (_ASSIGN.match(words[i]) or words[i].lower() in _WRAP + _KEYWORDS or words[i] == "&" or (i == 0 and words[i].endswith(")")) or
                    (sh is None and _spelled(words[i]) in _WRAP)):  # a shell the hook cannot name may remove the escapes of en\v
                break
            name = words[i].lower() if words[i].lower() in _WRAP else _spelled(words[i]) if sh is None else None
            wrapped, vals = name in _WRAP, _SU_VALUE if name in ("sudo", "doas") else _ENV_VALUE if name == "env" else ()
            i += 1
            if wrapped:  # the wrapped program is the next known one; the value of a wrapper option (-u git) is never the program
                i = next((k for k in range(i, len(words)) if (_exe(words[k]) in _KNOWN or (sh is None and _spelled(words[k]) in _KNOWN)) and
                          words[k - 1] not in vals), len(words))
        if i >= len(words):
            return False, []
        redirs = _redir_indices(words, i)  # the redirections (and their targets) before the program: no assignment, wrapper or option among them
        exe, rest = _exe(galias.get(words[i], words[i])), words[i + 1:]
        spelled = _spelled(galias.get(words[i], words[i])) if sh is None and exe not in _KNOWN else None  # g\it, g^it, g`it: the shell may or may not remove them
        exe = spelled or exe
        if exe in ("gh", "gt", "claude", "source", "."):  # a redirection that stands before the subcommand or the script is no word of it
            rest = _split_redirs(rest, dyn[i + 1:])[0]
        script = re.search(r"\.(sh|ps1|bash)$", words[i], re.I) is not None
        if i == len(redirs) and exe not in _STATEFUL and not script:  # neither depends on nor changes the state
            return False, []
        isolated = not _ALONE.isdisjoint(low[:i])  # a builtin behind a program wrapper runs in no shell: env cd x changes nothing
        chdir = _wrapped_dir(words, dyn, i)  # env -C <dir> and the privilege wrapper -D <dir>: the wrapped program runs in <dir>
        kept = [False] * (i + 1)  # kept[k]: a -E / --preserve-env stands after word k (the wrapper keeps the environment)
        for k in range(i - 2, -1, -1):
            kept[k] = kept[k + 1] or words[k + 1] == "-E" or words[k + 1].startswith("--preserve-env")
        work[0] -= STEP_COST * (len(states) - 1)
        finals, n0, before = [], len(out), _snap(states) if spelled else None
        for st in states:
            here, gds, dirs = st
            run = here if chdir is None else None if chdir[1] else _join(here, chdir[0])  # where the invocation runs (None: unknown)
            inv = gds.copy()  # GIT_DIR of this invocation: prefix and env assignments set it, env -u / -i remove it
            after_env = after_exec = False  # an env / exec word stands before word k
            for k in range(i):
                if k in redirs:
                    continue
                w = words[k]
                unset = w[2:] if w.startswith("-u") and len(w) > 2 else w[8:] if w.startswith("--unset=") else \
                    words[k + 1] if w in ("-u", "--unset") and k + 1 < i and after_env else None
                if _ASSIGN.match(w) and _gd_name(w):
                    inv[_gd_name(w)] = (w.split("=", 1)[1], dyn[k] or _appends(w), True)
                elif after_env and unset and _gd_name(unset):
                    inv[_gd_name(unset)] = (None, False, False)
                elif (after_env and w in ("-i", "--ignore-environment", "-")) or (w == "-c" and after_exec):
                    inv.clear()
                elif low[k] == "doas" or (low[k] in ("sudo", "wsl") and not kept[k]):
                    for key, (v, d, e) in list(inv.items()):  # these may start the program with a clean environment
                        inv[key] = (v, d, None if e is True else e)
                after_env, after_exec = after_env or low[k] == "env", after_exec or low[k] == "exec"
            cands = inv.cands()
            note(run, cands)  # text fed to this invocation runs with its own GIT_DIR
            if words[i - 1:i] == ["xargs"] or (i and "xargs" in low[:i]):  # the names arrive on stdin
                if exe == "git":
                    out.extend(parse_git(words[i:] + ["$stdin"], dyn[i:] + [True], run, aliases, depth, cands, work, sh))
                    continue
            if exe in _DIR_CMDS + ("popd", "pop-location"):
                if isolated:
                    pass
                elif exe in ("popd", "pop-location"):  # back to the directory pushd left (unknown when the stack is not the line's own)
                    st[0] = dirs.pop() if dirs else None
                else:
                    tgt = [(w, d) for w, d in _plain_args(rest, dyn[i + 1:]) if not w.startswith("-") and not (sh == "cmd" and w.lower() == "/d")]
                    if sh == "cmd" and len(tgt) > 1:  # cmd's cd takes the rest of the line as one path
                        tgt = [(" ".join(w for w, _ in tgt), any(d for _, d in tgt))]
                    dirs += [here] if exe in ("pushd", "push-location") else []
                    if not tgt or tgt[0][1] or tgt[0][0] == "-":
                        st[0] = None
                    elif len(tgt) > 1:  # bash and PowerShell refuse a second directory: the shell stays where it was
                        st[0] = None if here is None else _missing(tgt[0][0], getattr(here, "prior", here))
                    else:
                        st[0] = _cd(here, tgt[0][0])
                        for f in reversed(frames) if isinstance(st[0], _Missing) and st[0] is not here else ():  # an earlier element of the && chain made it
                            kind = f["made"].get(pkey(str(st[0])))
                            if kind:
                                st[0] = _missing(str(st[0]), st[0].prior, kind + (f["token"],))
                                break
            elif _git_dir_ops(gds.copy() if isolated else gds, exe, rest, dyn[i + 1:]):
                pass
            elif exe in ("mkdir", "md"):  # a directory a later cd of the same && chain may enter
                args = [w for w, d in _plain_args(rest, dyn[i + 1:]) if not d and not w.startswith("-")]
                parents = any(w == "--parents" or (w.startswith("-") and not w.startswith("--") and "p" in w) for w in rest) or exe == "md" or sh == "ps"
                for w in args:
                    t = _join(run, w)
                    while t and not os.path.isdir(t):
                        made(t, ("dir", t))
                        up = os.path.dirname(t)
                        t = up if parents and up != t else None
            elif exe in ("set-alias", "sal"):
                pos = [w for w in rest if not w.startswith("-")]
                if len(pos) >= 2:
                    galias[pos[0]] = pos[1]
            elif exe == "start-process" and depth < 3:
                sp = _start_process(rest, dyn[i + 1:])
                if sp:  # git runs in the -WorkingDirectory, resolved against the shell's directory (a dynamic value: the repository is unknown)
                    at = run if sp[1] is None else None if sp[1][1] else _join(run, sp[1][0])
                    out.extend(interpret("git " + sp[0].replace(",", " "), at, depth + 1, aliases, cands, "ps", work=work))
            elif exe == "find" and depth < 3 and any(w in ("-exec", "-execdir") for w in rest):
                k = next(k for k, w in enumerate(rest) if w in ("-exec", "-execdir"))
                out.extend(interpret(" ".join(rest[k + 1:]).replace("\\;", " "), run, depth + 1, aliases, cands, work=work))
            elif exe in _SHELLS + ("powershell", "pwsh", "cmd") and depth < 3:
                plain, _plain_dyn, ins = _split_redirs(rest, dyn[i + 1:])  # the text and the script are read behind redirections
                child = _child_script(exe, plain, _OPAQUE)  # -c / -Command / -EncodedCommand in every spelling the shell reads
                handled = child is not None
                if handled:
                    out.extend(interpret(child, run, depth + 1, aliases, cands, _SHELL_OF[exe], work=work))
                files = [w for k, w in enumerate(plain) if not w.startswith("-") and (k == 0 or plain[k - 1].lower() != "-command")]  # option values come first
                files += _input_files(ins)  # the file a `<` redirection feeds to the shell is its script
                for w in [] if handled else files[:4]:
                    relative(w)
                text = None if handled else next((s for s in (_script(w, run) for w in files[:4]) if s), None)
                out.extend(interpret(text, run, depth + 1, aliases, cands, _SHELL_OF[exe], work=work) if text else [])
            elif exe in ("eval", "iex", "invoke-expression") and depth < 3:
                out.extend(interpret(" ".join(rest), run, depth + 1, aliases, cands, sh if exe == "eval" else "ps", dirs, None if isolated else finals, work))
            elif exe == "git":
                crs = parse_git(words[i:], dyn[i:], run, aliases, depth, cands, work, sh)
                out.extend(crs)
                for cr in crs:  # git worktree add <T>: a later cd of the chain enters a worktree of this repository
                    if cr["kind"] == "worktree" and isinstance(cr.get("path"), str) and isinstance(cr["cwd"], str) and                             not isinstance(cr["path"], _Missing) and not isinstance(cr["cwd"], _Missing):
                        made(cr["path"], ("wt", cr["cwd"]))
                new = _git_new_repo(words[i:], dyn[i:], run)
                if new is not None and (not isinstance(new, _Missing) or new.follow):  # git init <T> / git clone <src> <T>: a new repository holds no lane
                    made(new, ("new", None))
                    if new is here and getattr(here, "follow", None):  # git init inside a directory the chain entered
                        st[0] = _missing(str(here), here.prior, ("new", None, here.follow[2]))
            elif (exe == "gh" and rest[:2] == ["pr", "checkout"]) or (exe == "gt" and rest[:1] == ["create"]) or \
                    (exe == "claude" and any(w in ("-w", "--worktree") or w.startswith("--worktree=") or (w.startswith("-w") and w[2:3] not in ("", "-"))
                                             for w in rest)):
                out.append(_with_rds(_cr(exe + " " + " ".join(rest[:2]), [], run, True, kind="auto", tool=True), run, cands))
            elif script and depth < 3 or exe in ("source", "."):
                relative(rest[0] if exe in ("source", ".") and rest else words[i])
                text = _script(rest[0] if exe in ("source", ".") and rest else words[i], run)
                ps1 = words[i].lower().endswith(".ps1") or exe in ("source", ".") and rest[:1] and rest[0].lower().endswith(".ps1")
                in_place = (exe in _IN_PLACE or ps1) and not isolated  # PowerShell runs a script in the caller's process: its location and environment changes stay
                out.extend(interpret(text, run, depth + 1, aliases, cands, "ps" if ps1 else "bash", dirs if in_place else (), finals if in_place else None,
                                     work) if text else [])
        if spelled:  # the shell may or may not remove the escape: what the program creates is dynamic, what it changes is a possible change
            out[n0:] = [dict(cr, dynamic=True) for cr in out[n0:]]
            states[:] = _merge(before, states)
        return True, finals

    def substituted(states, text):
        """Text substituted into a command ($(..), backticks, a PowerShell (..)) may change the state of the shell that runs the command:
        the states it leaves join the ones before it.  bash runs it in a subshell: nothing changes."""
        if bash:
            return states
        ends = []
        for h, g, d in states:
            work[0] -= TEXT_COST
            if work[0] < 0:
                return states
            interpret(text, h, depth + 1, aliases, g.cands(), sh, d, ends, work)  # its creations are judged with the other inner texts
        return _merge(states, [[h, _GitDirs(c, sh), list(d)] for h, c, d in ends])

    def capped(states):
        if len(states) > MAX_CONTEXTS:
            over[:] = over or [dict(_anywhere("scoped change", "a subshell, a pipeline, eval, a condition or a background job may change the directory "
                                                               "or GIT_DIR, which leaves the command in more directory or GIT_DIR states than the hook judges"),
                                    cap=True)]
            states = states[:MAX_CONTEXTS]
        for st in states:
            note(st[0], st[1].cands())
        return states

    events, frames, closing = _lex(cmd, sh), [_frame("top", states)], {")": "(", "}": "{", "K)": "K("}
    opened = {"(": 0, "{": 0, "K(": 0}  # the open frames of each kind: a closer finds its opener in constant time, however deep the nesting
    starts = [ev.at for ev in events if isinstance(ev, list)] + [len(cmd) + 1]  # where each segment starts
    subs = sorted(s for s in subs if s[1] and _CHANGES.search(s[1])) if depth < 3 else []  # substituted texts that may change the state
    nseg = nsub = 0
    for k, ev in enumerate(events):
        if work[0] < 0:
            over = [_anywhere("nested text", _OVER_WORK)]
            break
        fr = frames[-1]
        if ev in ("(", "{", "K("):  # a group, a brace block, a compound command: it keeps the states it was opened in
            states = states if fr["inside"] else _enter(fr, states)
            frames.append(_frame(ev, states))
            opened[ev] += 1
            continue
        if ev == "|":
            continue
        if isinstance(ev, str) and ev in closing:
            if not opened[closing[ev]]:
                continue
            while True:
                f = frames.pop()
                opened[f["kind"]] -= 1
                ends = _end_list(f, states, last=True)
                states = _snap(f["open"]) if bash and f["kind"] == "(" else _merge(f["open"], ends)  # bash: a group is a subshell
                if f["kind"] == closing[ev]:
                    break
        elif ev in ("&&", "||"):
            states = _leave(fr, states)
            fr["conn"] = ev
            if ev == "||":  # the && chain ends: what it created is not entered by the commands after it
                fr["made"] = {}
        elif ev in (";", "&"):  # in cmd, '&' runs the next command after the first one
            states = _end_list(fr, states, background=ev == "&" and sh != "cmd", subshell=bash)
        else:
            states = states if fr["inside"] else _enter(fr, states)
            nxt, prv = events[k + 1] if k + 1 < len(events) else None, events[k - 1] if k else None
            apart = bash and (ev.sub or nxt == "|")  # bash runs it in a subshell: the commands after it keep the states before it
            piped = not apart and (ev.sub or "|" in (prv, nxt))  # in $( .. ) or a pipeline: a possible change
            before = _snap(states) if piped or apart else None
            made_at = len(out)
            changed, finals = segment([w for w, _ in ev], [d for _, d in ev])
            up = (events[k - 2] if k > 1 and isinstance(events[k - 2], list) else None) if prv == "|" else False  # the command before the pipe, if any
            for cr in out[made_at:]:
                if cr.get("stdin"):  # an update-ref --stdin: where its instructions come from is read after the walk
                    cr["up"] = up
            if not any(cr["verb"] == "update-ref" for cr in out[made_at:]):
                src = _unseen_update_ref(ev)  # `$g update-ref --stdin`: a git the walk cannot name
                if src is not None:
                    unseen_git.append((src, up))
            nseg, due = nseg + 1, []
            while nsub < len(subs) and subs[nsub][0] < starts[nseg]:  # the texts substituted into this command
                due.append(subs[nsub])
                nsub += 1
            if not changed and not due:
                continue
            states = _merge(states, [[h, _GitDirs(c, sh), list(d)] for h, c, d in finals]) if finals else states
            states = before if apart else _merge(before, states) if piped else states
            for _, text in due:
                states = substituted(states, text)
        states = capped(states)
    if work[0] < 0 and not over:  # the budget ran out in the last command's substituted text
        over = [_anywhere("nested text", _OVER_WORK)]
    while len(frames) > 1:  # blocks the line leaves open end with it
        f = frames.pop()
        ends = _end_list(f, states, last=True)
        states = _snap(f["open"]) if bash and f["kind"] == "(" else _merge(f["open"], ends)
    states = capped(_end_list(frames[0], states, last=True))
    if final is not None:
        final.extend((h, g.cands(), tuple(d)) for h, g, d in states)
    feeds = {}

    def feed(src, up):  # -> (names, dynamic) of the instructions of an update-ref --stdin whose input sources are `src` and `up`
        key = (tuple(src["here"]), src["doc"], src["file"], tuple(up) if up else up)
        if key not in feeds:
            text, unseen = _stdin_feed(src, up, docs)
            work[0] -= len(text) + STEP_COST
            names, odd = _stdin_refs(text)
            feeds[key] = (names, odd or unseen)
        return feeds[key]
    for cr in out:  # update-ref --stdin: the instructions are in the sources that feed it, or nowhere the hook can see
        if cr.get("stdin"):
            names, odd = feed(cr.pop("src", None) or _no_input(), cr.pop("up", False))
            cr.pop("stdin")
            named = _cr("update-ref", names, None, odd)
            cr.update(names=named["names"], dynamic=named["dynamic"] or cr["dynamic"])
    for src, up in unseen_git:  # fed to a git the walk did not see
        names, odd = feed(src, up)
        early += [_with_rds(_cr("update-ref", names, h, odd), h, c) for h, c in contexts[:MAX_CONTEXTS]]
    if work[0] < 0 and not over:
        over = [_anywhere("nested text", _OVER_WORK)]
    places = contexts
    if inner and len(contexts) > 1 and (len(contexts) > MAX_CONTEXTS or len(inner) * len(contexts) > 4096):  # too much to judge everywhere:
        early.append(dict(_anywhere("command substitution", "the command runs text from inside itself in more directory or GIT_DIR states than the hook judges"),
                          cap=True))
        places = contexts[:1]
    for text, ish in inner:
        for h, c in places:
            early += interpret(text, h, depth + 1, aliases, c, ish, work=work)
    seen, result = set(), []
    for cr in over + early + out:  # a creation seen twice (a quoted body and the command that runs it) counts once; a flag without a usable name is no creation
        for c in _expand(cr):
            key = repr(sorted(c.items(), key=str))
            if key not in seen and (c["names"] or c["dynamic"] or c["kind"] == "auto"):
                seen.add(key)
                result.append(c)
    if top and not work[1] and not any(not c.get("anywhere") for c in result):  # nothing is created and no relative script is read:
        result = [c for c in result if not c.get("cap")]  # the states beyond the cap lose nothing
    return result


_STATE_PATH = re.compile(r"(^|[\\/])\.git[\\/](hooks|refs|HEAD|magos|config)([\\/]|$)|(^|[\\/])packed-refs$|(^|[\\/])\.magos([\\/]|$)", re.I)
_WRITE_CMDS = frozenset("rm mv cp tee chmod del erase ren rename remove-item move-item copy-item set-content out-file add-content new-item clear-content "
                        "unlink truncate shred rmdir rd ln mklink rename-item rni ri mi move copy cpi sc ac ni clc".split())
_COPIES = ("cp", "copy-item", "copy", "cpi")  # tested on their destination only, unless they copy as a link
_WRITE_HINT = re.compile(r">|\b(?:%s|sed|find)\b" % "|".join(re.escape(w) for w in sorted(_WRITE_CMDS, key=len, reverse=True)), re.I)
UserOnly = namedtuple("UserOnly", "name auto_safe scope")
# The user-only subcommands, one row each (Approval).  auto_safe: magos.approval auto-safe lets the Claude Code hook allow it without a click (it
# adds protection or copies the guard and weakens nothing); scope: where its approvals live ("repo": <git-common-dir>/magos/approvals, "home":
# <default guard home>/approvals).
USER_ONLY = (UserOnly("override", False, "repo"), UserOnly("arm", True, "repo"), UserOnly("disarm", False, "repo"), UserOnly("install", True, "home"))
_USER_ONLY = tuple(u.name for u in USER_ONLY)
_READ_FLAGS = ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope")
_ENV_WRITE = re.compile(r"^(?:GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\d+|VALUE_\d+)=|\$env:GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\d+|VALUE_\d+)$)", re.I)
_USER_MSG = "override / arm / disarm / install are user-only"
_STATE_MSG = "the hooks, refs and claim store under .git and the guard home are the guard's state"
_APPROVAL_MSG = "the approval records under <git-common-dir>/magos/approvals and <guard home>/approvals are written by the host hook only"
_APPROVALS = re.compile(r"(?:^|[\\/])approvals(?:[\\/]|$)", re.I)  # a path segment named approvals, in a word that names the guard's state
_APPROVAL_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)
_APPROVAL_FILE = re.compile(r"[0-9a-f]{64}\.(?:json|used)")  # an approval record: the SHA-256 of its token, live (.json) or consumed (.used)
_DENIAL_FILE = re.compile(r"[0-9a-f]{12}\.json")  # a denial record: the fingerprint of its denial
_APPROVAL_WORD = re.compile(r"--approval(?![\w-])", re.I)
_APPROVAL_TOOLS = {"Bash": "bash", "PowerShell": "ps"}  # the tools whose shell the rewritten command is quoted for
_INTERPRETER = re.compile(r"(?:py|python|python3(?:\.\d+)?)(?:\.exe)?", re.I)  # the bare first word of a direct invocation
_INTERP_OPT = re.compile(r"-3(?:\.\d+)?(?:-(?:32|64))?|-[BEIsu]|-Xutf8")  # and the pair -X utf8
_BARE_SH = re.compile(r"[A-Za-z0-9_@%+=:,./-]+")  # a word bash reads as itself
_BARE_PS = re.compile(r"[A-Za-z0-9_+=:./-]+")  # a word PowerShell passes to a native program as itself (no , @ % $ or quote)
_USER_RUN = "user-only: approved in Claude Code's, Codex's or Hermes's dialog, or run in your own terminal"  # doctor's hint before a user-only command
Approval = namedtuple("Approval", "decision reason updated")  # the Claude Code hook's ask or allow of a user-only command
HOST_ONLY = ("mcp",)  # the subcommands only the host starts (Codex approval): a tool command that runs one is denied on every host
_HOST_MSG = "mcp is the guard's approval server, which only the host starts"
# The subcommands an agent runs (Approval routes, The subcommand of a guard run): a tool command that runs the guard with any other word in the subcommand slot
# (hook and mcp, which only a host runs, a dynamic or empty slot, an unknown word) is denied on every host; the user-only words keep their path.
AGENT_SUBS = ("plan", "check", "list", "release", "doctor", "version", "set-plan", "set-show", "set-update", "set-release")
_SLOT_MSG = "the guard runs with a subcommand that is no plain word an agent may run"
_LONG_MSG = "the command is too long to inspect and names MAGOS"
_LONG_HINT = re.compile(r"magos|run-guard", re.I)  # a text too long to read that may run the guard: denied on every host (protected)
MCP_ARGS = ("subcommand", "repo", "fingerprint", "reason", "host", "dry_run")  # the arguments of magos_approve, in the order the texts name them
_MCP_TAKES = {"override": ("repo", "fingerprint", "reason"), "arm": ("repo", "dry_run"), "disarm": ("repo", "dry_run"), "install": ("repo", "host", "dry_run")}
_HERMES_APPROVAL_TOOLS = {"terminal": "bash"}  # Hermes runs every terminal command with bash (Git Bash on Windows)
_HERMES_WORKDIR_CHARS = frozenset("/\\:_-.~ +@=,")  # with the letters and digits: the characters Hermes accepts in a workdir
_TRUTHY = ("1", "true", "yes", "on")
HermesApproval = namedtuple("HermesApproval", "command message rule_key")  # the Hermes hook's modify and approve; message and rule_key None under auto-safe


def _bare(word):
    """The reading of a word after the escapes of bash, PowerShell and cmd: every backslash, backtick, caret, ' and " removed."""
    return re.sub(r"[\\`^'\"]", "", word)


def _guard_word(word):
    """'launcher' for a word whose case-folded base name (after the last / or \\) is run-guard.cmd or run-guard, 'script' for a word ending in
    magos_guard or magos_guard.py, else None; either reading of the word counts."""
    for w in (word, _bare(word)):
        if re.split(r"[\\/]", w)[-1].lower() in ("run-guard.cmd", "run-guard"):
            return "launcher"
        if re.search(r"magos_guard(\.py)?$", w, re.I):
            return "script"
    return None


def _guard_slot(words, i, launcher):
    """The index of the subcommand slot of a guard word whose arguments start at words[i]: the first word after the launcher's leading
    --strict, the global options in any spelling argparse ever took (--repo and --lang with their value, --json, every --name=value) and a
    `--` (from Python 3.13 on argparse takes the word after it as the subcommand); len(words) when no word is left.  Any other option is the
    slot itself (argparse refuses it)."""
    k = i + 1 if launcher and i < len(words) and _bare(words[i]) == "--strict" else i
    while k < len(words) and _bare(words[k]).startswith("--"):
        t = _bare(words[k])
        if t == "--":
            k += 1
            break
        if "=" in t:
            k += 1
        elif "--repo".startswith(t) or "--lang".startswith(t):
            k += 2
        elif "--json".startswith(t):
            k += 1
        else:
            break
    return min(k, len(words))


def _guard_sub(rest, launcher):
    """The subcommand in `rest` (the words after a guard word) that a table names: a name of _USER_ONLY or HOST_ONLY in either reading of the
    word in the slot (_guard_slot); None for any other word."""
    k = _guard_slot(rest, 0, launcher)
    if k < len(rest):
        for w in (rest[k], _bare(rest[k])):
            if w in _USER_ONLY or w in HOST_ONLY:
                return w
    return None


def _slot_problem(pieces, pdyn, j, how, fed, start, quoted):
    """Is the guard piece pieces[j], which the shell runs (`how`: "program", "interp" or "weak", _run_marks), denied with _SLOT_MSG?  Yes when
    a piece after it up to and including its slot is dynamic (an unquoted value word-splits into the slot, a PowerShell array passes several
    words), when xargs, parallel or find -exec feeds it (`fed`: with -I any word becomes the replaced one), or when the slot is no exact
    AGENT_SUBS word in either reading: hook, mcp, an empty slot (a later word lands there), a glob, a splat (@a) and every other word.  An
    option argparse refuses and -h / --help stay allowed (nothing runs), except as an argument of Start-Process or start (`start`), whose
    own parameters (-ArgumentList, -RedirectStandardInput) stand there.  The slot is judged only for "program" and "interp": a "weak" guard
    (an interpreter met among the arguments of another program: `ionice -c3 python3 G`, also `grep -n python3 G`) and, in a quoted word read
    as a command (`quoted`), a "program" guard (a commit message names the script) are denied for a dynamic or fed slot only."""
    k = _guard_slot(pieces, j + 1, _guard_word(pieces[j]) == "launcher")
    if any(pdyn[j + 1:k + 1]) or fed:
        return True
    if how == "weak" or (quoted and how != "interp"):
        return False
    if k == len(pieces):
        return True
    w, b = pieces[k], _bare(pieces[k])
    if w in AGENT_SUBS or b in AGENT_SUBS:
        return False
    return start or not (b.startswith("-") and len(b) > 1)  # -h, --help and an option argparse refuses (also a negative number)


_ARG_FEEDERS = ("xargs", "parallel")  # wrappers that add words read from their input to the command they run (xargs -I replaces any word)
_FIND_RUN = ("-exec", "-execdir", "-ok", "-okdir")  # find runs the command after these with the paths it found
_STARTERS = ("start", "start-process", "saps")  # cmd's start and PowerShell's Start-Process: their arguments name a program and its words
_PY_EXE = re.compile(r"py|pyw|pythonw?|python3(?:\.\d+)?w?")  # the base name of a Python interpreter, as _exe returns it
# Tools that run a program of an environment, with the word that does it: their words up to the program are those of a wrapper.
_RUN_TOOLS = {"uv": "run", "uvx": None, "poetry": "run", "pdm": "run", "hatch": "run", "pipenv": "run", "rye": "run", "pixi": "run", "conda": "run",
              "mamba": "run", "micromamba": "run", "pyenv": "exec"}
_WRAP_VALUE = re.compile(r"[0-9]+(?:\.[0-9]+)?[smhd]?")  # a number or a duration after a wrapper (timeout 30s, nice -n 5)
_RUN_HINT = re.compile(r"magos_guard|run-guard|xargs|parallel|-exec|-ok")  # in the lower-case bare words: a command _run_marks must walk


def _run_marks(words, pieces, owners, pdyn, fed=False, start=False):
    """One forward pass over the pieces of one command: -> (marks, feeds, starts).  marks[j] for a guard piece the shell runs: "program" when
    it is the program of the command (after assignments, redirections, keywords and wrappers with their options and values), "interp" when
    an interpreter or shell and its options run it (python -m: the module), a dynamic program word runs it (`"$PY" G`), or it stands after
    Start-Process or start; "weak" when an interpreter met among the arguments of another program runs it (`ionice -c3 python3 G`, `flock
    /tmp/l python3 G`; also `grep -n python3 G`, which runs nothing); None for every other piece (an argument of another program: `git add
    G`, `grep x G`, `python -m pytest G`).  feeds[j]: xargs, parallel or a find -exec before piece j feeds what runs (`fed`: the text itself
    is fed).  starts[j]: piece j is an argument of Start-Process or start (`start`: the text is one)."""
    n = len(pieces)
    marks, feeds, starts = [None] * n, [fed] * n, [start] * n
    state, opt, skip, j, strong, then = ("sp" if start else "start"), False, -1, 0, True, None  # then: the word a run tool needs (uv run)
    while j < n:
        feeds[j], starts[j] = fed, state == "sp"
        p, w = pieces[j], words[owners[j]]
        b = _bare(p)
        x = _exe(b)
        if isinstance(w, _Redir) or owners[j] == skip:  # a redirection of the shell and its target: no word of the command
            skip = owners[j] + 1 if isinstance(w, _Redir) and w.take == 2 else skip
        elif b.lower() in _FIND_RUN:
            state, fed, opt = "start", True, False
        elif state == "sp":
            marks[j] = "interp" if _guard_word(p) else None
        elif state in ("start", "wrap"):
            a = _ASSIGN.match(p)
            if a and (_PY_EXE.fullmatch(_exe(_bare(p[a.end():]))) or _exe(_bare(p[a.end():])) in _SHELLS):
                state, strong = "interp", True  # c=python3 <guard>, a quoted value read as a command: $c then runs the guard
            elif a or (state == "start" and b in _KEYWORDS):
                pass
            elif state == "wrap" and then is not None and b == then:
                then = None
            elif x in _RUN_TOOLS:
                state, opt, then = "wrap", False, _RUN_TOOLS[x]
            elif x in _WRAP or x in _ARG_FEEDERS or x == "eval":
                state, fed, opt = "wrap", fed or x in _ARG_FEEDERS, False
            elif x in _STARTERS:
                state = "sp"
            elif _guard_word(p):
                marks[j], state = "program", "args"
            elif _PY_EXE.fullmatch(x) or x in _SHELLS or pdyn[j]:
                state, strong = "interp", True
            elif state == "wrap" and b.startswith("-"):
                opt = True
            elif state == "wrap" and (opt or _WRAP_VALUE.fullmatch(b)):  # the value of a wrapper's option, or a number or duration
                opt = False
            else:
                state = "args"
        elif state == "args":
            if _PY_EXE.fullmatch(x) or x in _SHELLS:  # an interpreter among the arguments of another program (ionice, flock, chrt, ...)
                state, strong = "interp", False
            elif x in _ARG_FEEDERS:  # xargs behind another program (ionice -c3 xargs python3 G) feeds the interpreter after it
                fed = True
        elif state == "interp":
            m = re.search(r"[cmXW]", b[1:]) if b.startswith("-") and not b.startswith("--") and len(b) > 1 else None
            if m and m.group() == "c":  # -c: the code is no script
                state = "args"
            elif m and m.group() == "m":  # -m <module>: a module named like the guard runs it
                val = b[1:][m.end():]
                if not val and j + 1 < n:
                    j += 1
                    feeds[j], starts[j] = fed, False
                if _guard_word(pieces[j]):
                    marks[j] = "interp" if strong else "weak"
                state = "args"
            elif m and not b[1:][m.end():] and j + 1 < n:  # -X and -W take the next word as their value
                j += 1
                feeds[j], starts[j] = fed, False
            elif b == "--check-hash-based-pycs" and j + 1 < n:  # the one long option with a value
                j += 1
                feeds[j], starts[j] = fed, False
            elif (b.startswith("-") and len(b) > 1) or _PY_EXE.fullmatch(x):  # an option; an interpreter named by $(command -v python3)
                pass
            else:
                marks[j], state = (("interp" if strong else "weak") if _guard_word(p) else None), "args"
        j += 1
    return marks, feeds, starts


def _user_only(rest, launcher):
    """Is the subcommand in `rest` (the words after a guard word) user-only (_guard_sub)?"""
    return _guard_sub(rest, launcher) in _USER_ONLY


_METHOD_TAIL = re.compile(r"\.[A-Za-z_]\w*\([^\\/]*$")  # a .Name(...) call at the end of a piece ("a,b".Split(',')); a path segment is none


def _pieces(words, dyn=None):
    """-> (owners, pieces, dynamic): the words cut at PowerShell's comma, which separates the elements of an array that a native command and
    Start-Process receive as separate arguments (`a,b`, `'a','b'`, `a, b`, `a ,b`, `@('a','b')`, `"a,b".Split(',')`, also `('a') b`).
    Each piece loses a .Name(...) call at its end and every @, ( and ) at its ends; an empty piece (a lone comma, a comma that starts or
    ends a word) is no word.  owners[j] is the index in `words` of the word that holds pieces[j]; dynamic[j] tells that the lexer read
    that word as dynamic (`dyn`, one flag per word) and the piece as written holds $, a backtick, %, ( or ) (`G,$a`: only `$a`)."""
    owners, pieces, dynamic = [], [], []
    for i, w in enumerate(words):
        for raw in w.split(","):
            p = re.sub(r"^[@(]+|[()]+$", "", _METHOD_TAIL.sub("", raw))
            if p:
                owners.append(i)
                pieces.append(p)
                dynamic.append(bool(dyn and dyn[i] and re.search(r"[$`%()]", raw)))
    return owners, pieces, dynamic


def user_only_row(args):
    """The USER_ONLY row of a parsed invocation, or None.  The one place that says which parsed invocation is user-only (an argument predicate
    of a row belongs here, and the same rule in _user_only)."""
    return next((u for u in USER_ONLY if u.name == getattr(args, "cmd", None)), None)


def _in_approvals(word):
    """Does a word that names the guard's state lie in an approval store (a path segment named approvals)?  Both readings count."""
    return any(_APPROVALS.search(w) for w in (word, _bare(word)))


def _child_text(words):
    """-> (index, text): the first child shell among `words` and the text it runs (None when it runs none), or (None, None): bash / sh / zsh /
    dash / ksh -c, cmd /c and /k, powershell and pwsh -Command, -CommandWithArgs or -EncodedCommand in every spelling the shell reads
    (_shell_flag)."""
    for i, w in enumerate(words):
        exe = _exe(_bare(w))
        if exe in _SHELLS + ("powershell", "pwsh", "cmd"):
            return i, _child_script(exe, words[i + 1:])
    return None, None


def _aliased_git(bares):
    """Does a git invocation among the (bare, lower-case) words define an alias (-c alias.<name>=...) or name a subcommand that is not a
    built-in git command?  An alias can run `git config`."""
    for g, x in enumerate(bares):
        if _exe(x) != "git":
            continue
        k, alias = g + 1, False
        while k < len(bares) and bares[k].startswith("-"):
            alias = alias or (bares[k] == "-c" and k + 1 < len(bares) and bares[k + 1].startswith("alias."))
            k += 2 if bares[k] in _VALUE_OPTS else 1
        if alias or (k < len(bares) and bares[k] not in _BUILTINS):
            return True
    return False


def _copy_destination(exe, args):
    """The destinations of a plain cp / Copy-Item / copy / cpi (-t / --target-directory, -Destination or -Destination:<path>, else every
    positional argument after the first, so an option value after the operands hides none), or None when cp copies as a link (-l, --link,
    -s, --symbolic-link): a link to a guard file lets a later write change the guard."""
    if exe == "cp":
        for a in args:
            key = a[2:].split("=", 1)[0] if a.startswith("--") else None
            if key is not None and len(key) >= 2 and ("link".startswith(key) or "symbolic-link".startswith(key)):
                return None
            letters = re.match(r"-([^tS]*)", a) if key is None else None  # -t and -S take the rest of the word as their value
            if letters and re.search(r"[ls]", letters.group(1)):
                return None
        for k, a in enumerate(args):
            key = a[2:].split("=", 1)[0] if a.startswith("--") else None
            if key and "target-directory".startswith(key):  # --target-directory and its unique prefixes, = or the next word
                return [a.split("=", 1)[1]] if "=" in a else args[k + 1:k + 2]
            value = _short_value(a, "tS") if key is None else None  # -t DIR, -tDIR, -rt DIR
            if value is not None and re.match(r"-[^tS]*t", a):
                return [value] if value else args[k + 1:k + 2]
        return [a for a in args if not a.startswith("-")][1:]
    pos, k, source = [], 0, False
    while k < len(args):
        a = args[k]
        name, _colon, value = a[1:].partition(":") if a.startswith("-") and len(a) > 1 else ("", "", "")
        name = name.lower()
        if name and len(name) >= 3 and "destination".startswith(name):
            return [value] if value else args[k + 1:k + 2]
        if name and any(full.startswith(name) for full in ("path", "literalpath", "filter", "include", "exclude", "credential", "tosession", "fromsession")):
            source = source or "path".startswith(name) or "literalpath".startswith(name)
            k += 1 if value else 2
            continue
        pos += [] if name else [a]
        k += 1
    return pos if source else pos[1:]  # with -Path / -LiteralPath named, every positional argument is the destination


def _state_word(word, roots, lazy=None):
    """Does a word name the guard's state: a .git/{hooks,refs,HEAD,magos,config}, packed-refs or .magos spelling, or an absolute path (any
    separator, Git Bash or case spelling the platform folds) inside one of `roots` (pkey form)?  Both readings of the word count, as written
    and with the escape characters and quotes removed.  `lazy` gives the store's root on demand: it is asked only for an absolute path with a
    segment named magos (the store is <git-common-dir>/magos), so a command that names no such path never opens the repository."""
    for w in dict.fromkeys((word, _bare(word))):
        if _STATE_PATH.search(w):
            return True
        p = _join(None, w) if w and (roots or lazy) else None  # absolute spellings only: a relative path is the documented limit
        if not p:
            continue
        k = pkey(p)
        rs = list(roots) + (lazy() if lazy and "magos" in re.split(r"[\\/]", k.lower()) else [])
        if any(k == r or k.startswith(r.rstrip(os.sep) + os.sep) for r in rs):
            return True
    return False


def protected(text, depth=0, roots=(), lazy=None, fed=False, start=False, quoted=False):
    """-> (scope, reason) or None.  scope 'always': user-only subcommands, the subcommands only a host runs, a guard run whose subcommand is
    no plain word an agent may run (_slot_problem), and magos.* config; 'guarded': edits of the guard's own state that matter once claims or
    the hook exist.  Words are inspected, never the whole text, so a commit message or a grep for these names passes; every keyword and path
    test reads each word as written and with its escape characters removed.  The text of a child shell (bash -c, cmd /c, powershell
    -Command ...), a here-document that a shell reads (bash <<E, sh -s <<E, cat <<E | bash: _heredocs) and a quoted word that names the
    guard script or its launcher are read with every check, to depth 3; `fed`, `start` and `quoted` carry what the outer command tells
    about that text (_run_marks, _slot_problem).  A finding of scope 'always' anywhere in the text wins over a 'guarded' one before it.  A
    text longer than MAX_TEXT is not read: when it names MAGOS (magos or run-guard, read without escape characters and quotes) it is
    'always' (_LONG_MSG), else 'guarded'.  `roots`: the absolute guard-home and Hermes-plugin directories (pkey form) whose absolute
    spellings count as the guard's state; `lazy` gives the store's root (see _state_word)."""
    if len(text) > MAX_TEXT:
        return ("always", _LONG_MSG) if _LONG_HINT.search(_bare(text)) else ("guarded", "the command is too long to inspect")
    head, bodies = _heredocs(text)
    first = None
    for seg in split_command(head):
        found = _protected_words([w for w, _ in seg], depth, roots, lazy, [d for _, d in seg], fed, start, quoted)
        if found and found[0] == "always":
            return found
        first = first or found
    for body in bodies if depth < 3 else ():  # a here-document a shell reads runs as commands, as interpret reads it
        found = protected(body, depth + 1, roots, lazy, fed)
        if found and found[0] == "always":
            return found
        first = first or found
    return first


def _protected_words(words, depth, roots, lazy, dyn=None, fed=False, start=False, quoted=False):
    lows = [w.lower() for w in words]
    bares = [_bare(w).lower() for w in words]
    seen = set(lows) | set(bares)

    def any_word(pred):
        return any(pred(x) for x in lows) or any(pred(x) for x in bares)
    # a guard piece and the pieces after it, its arguments: `Start-Process py <guard>,disarm` runs disarm
    owners, pieces, pdyn = _pieces(words, dyn)
    at = [(fed, start)] * len(words)  # (fed, start) where each word stands: those of its first piece, else those of the text
    if _RUN_HINT.search("\n".join(bares)):  # a guard word, or a feeder whose child text may hold one: the walk of _run_marks
        marks, feeds, starts = _run_marks(words, pieces, owners, pdyn, fed, start)
        for k in range(len(pieces) - 1, -1, -1):
            at[owners[k]] = (feeds[k], starts[k])
    else:
        marks, feeds, starts = [None] * len(pieces), [fed] * len(pieces), [start] * len(pieces)
    slot, j = None, 0  # slot: a guard run denied with _SLOT_MSG, returned once no user-only or host-only subcommand is found
    for i, w in enumerate(words):
        while j < len(pieces) and owners[j] == i:
            kind = _guard_word(pieces[j])
            k = _guard_slot(pieces, j + 1, kind == "launcher") if kind else len(pieces)
            sub = next((x for x in (pieces[k], _bare(pieces[k])) if x in _USER_ONLY or x in HOST_ONLY), None) if k < len(pieces) else None
            if sub in _USER_ONLY:  # also behind start, cmd /c start or Start-Process: found anywhere
                return "always", _USER_MSG
            if sub in HOST_ONLY:  # the approval server: only the host starts it (Codex approval)
                return "always", _HOST_MSG
            if kind and marks[j] and _slot_problem(pieces, pdyn, j, marks[j], feeds[j], starts[j], quoted):
                slot = slot or ("always", _SLOT_MSG)
            j += 1
        if depth < 3 and re.search(r"\s", w) and re.search(r"magos_guard|run-guard", w, re.I):  # Start-Process ... -ArgumentList '<guard> disarm'
            found = protected(w, depth + 1, roots, lazy, at[i][0], at[i][1], True)
            if found and found[1] != _SLOT_MSG:
                return found
            slot = slot or found
    ci, child = _child_text(words) if depth < 3 else (None, None)
    found = protected(child, depth + 1, roots, lazy, at[ci][0]) if child else None
    if found and found[1] != _SLOT_MSG:
        return found
    slot = slot or found
    if slot:  # a user-only or host-only subcommand anywhere in the command keeps its own reason
        return slot
    reads = any(f in seen for f in _READ_FLAGS)
    magos = any_word(lambda x: x.startswith("magos."))
    if magos and not reads and ("config" in seen or _aliased_git(bares)):
        return "always", "magos.* git config switches"
    if ("config" in seen and "core.hookspath" in seen and not reads) or any_word(lambda x: x.startswith("core.hookspath=")) or \
            ("config" in seen and "--worktree" in seen) or any(_ENV_WRITE.match(w) or _ENV_WRITE.match(_bare(w)) for w in words):
        return "guarded", "core.hooksPath / GIT_CONFIG_* / worktree config can switch the git layer off"
    e, redirs = None, _redir_indices(words, len(words))  # the program: the first word that is no assignment, wrapper or redirection of the shell
    for k, w in enumerate(words):
        if k not in redirs and not _ASSIGN.match(w) and bares[k] not in _WRAP:
            e = k
            break
    exe = _exe(bares[e]) if e is not None else ""
    if exe in _WRITE_CMDS or (exe == "sed" and "-i" in words) or (exe == "find" and "-delete" in seen):
        targets = _copy_destination(exe, words[e + 1:]) if exe in _COPIES else None
        hits = [w for w in (words[e + 1:] if targets is None else targets) if _state_word(w, roots, lazy)]
        if hits:  # an approval store is written by the host hook only, in every repository
            return ("always", _APPROVAL_MSG) if any(_in_approvals(w) for w in hits) else ("guarded", _STATE_MSG)
    for k, w in enumerate(words):  # a redirect into the guard's state
        m = re.match(r"(?:\d|&)?>>?\|?(.*)$", w)
        target = (m.group(1) or (words[k + 1] if k + 1 < len(words) else "")) if m else ""
        if target and _state_word(target, roots, lazy):
            return ("always", _APPROVAL_MSG) if _in_approvals(target) else ("guarded", _STATE_MSG)
    return None


def claude_matcher(strict=False):
    """The PreToolUse matcher of a Claude Code hook group, built from HOOKED_TOOLS (hooks/hooks.json carries the same strings)."""
    if strict:
        names = HOOKED_TOOLS["strict"]
        return "^%s$" % names[0] if len(names) == 1 else "^(%s)$" % "|".join(names)
    return "^(%s)$|^mcp__.*(%s)" % ("|".join(HOOKED_TOOLS["shell"] + HOOKED_TOOLS["isolation"]), "|".join(HOOKED_TOOLS["mcp_session"] + HOOKED_TOOLS["mcp_shell"]))


_MCP_SESSION = re.compile(r"mcp__.*(%s).*" % "|".join(HOOKED_TOOLS["mcp_session"]))


def is_shell_tool(name):
    """A tool whose string command the guard inspects as a command line: every hooked tool (the shell tools of every host and the
    worktree-creating tools) and every MCP tool."""
    return name in SHELL_TOOLS + HOOKED_TOOLS["isolation"] + HOOKED_TOOLS["strict"] or name.startswith("mcp__")


def shell_text(payload):
    return shell_command(payload)[0]


def shell_command(payload):
    """-> (command line or None, its shell dialect).  Codex passes argv: the script of a shell's -c / -Command / -EncodedCommand / /c element
    (_child_script: the words after a PowerShell or cmd option are joined into the text it runs) is read in that shell's dialect; the
    elements of any other argv are quoted back into a line (each holding a space, a quote, a backslash or a shell character) read as bash.
    A string command is read in the tool's shell (Monitor and MCP tools take a string only)."""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    c, sh = ti.get("command"), _TOOL_SHELL.get(tool)
    if isinstance(c, list) and tool != "Monitor" and not tool.startswith("mcp__"):
        parts = [str(x) for x in c]
        exe = _exe(parts[0]) if parts else ""
        script = _child_script(exe, parts[1:], _OPAQUE) if exe in _SHELL_OF else None
        if script is not None:
            c, sh = script, _SHELL_OF[exe]
        else:
            c, sh = " ".join(shlex.quote(x) if re.search(r"[\s'\"\\$`;&|<>()]", x) else x for x in parts), "bash"
    return (c if is_shell_tool(tool) and isinstance(c, str) else None), sh


def _rooted(p):
    """An absolute spelling on any platform (a drive path counts everywhere, so a payload is read alike on every host)."""
    return p.startswith(("/", "\\")) or re.match(r"[A-Za-z]:[\\/]", p) is not None


def session_dir(payload):
    """tool_input.workdir, else tool_input.cwd, else the payload's cwd, else the process directory; a leading ~ or ~user is expanded and a
    Git Bash drive spelling mapped, and a relative tool directory is joined to the payload's cwd (else to the process directory)."""
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    base = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else None
    base = _norm_path(base) if base else None
    for d in (ti.get("workdir"), ti.get("cwd")):
        if d and isinstance(d, str):
            p = _norm_path(d)
            return p if _rooted(p) else os.path.normpath(os.path.join(base or os.getcwd(), p))
    return base or os.getcwd()


def extract(payload, aliases=None):
    """-> (creations, protected, default_cwd) for the tool names of all three hosts.  The command line of every hooked tool and every MCP tool
    whose tool_input.command is a string is judged, in addition to (never instead of) the judgement the tool's own name calls for."""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cwd = session_dir(payload)
    (c, sh), crs, why = shell_command(payload), [], None
    if c is not None:
        why = protected(c)
        crs = interpret(c, cwd, 0, aliases, sh=sh) if _gated(c) else []
    if tool in HOOKED_TOOLS["strict"] and not ti.get("path"):
        crs.append(_cr("EnterWorktree", ["worktree-%s" % ti["name"]] if ti.get("name") else [], cwd, not ti.get("name"), "worktree" if ti.get("name") else "auto", tool=True))
    elif tool in HOOKED_TOOLS["isolation"] and re.search(r"isolation\W+worktree", json.dumps(ti)):
        crs.append(_cr("%s isolation=worktree" % tool, [], cwd, True, "auto", tool=True))
    elif _MCP_SESSION.fullmatch(tool):
        name = ti.get("branch_name") or ti.get("branch") or ti.get("new_branch")
        wanted = any(ti.get(k) for k in ("use_worktree", "worktree", "isolation")) or (bool(name) and ti.get("use_worktree") is not False) or tool.endswith("hand_off_to_session")
        if wanted and ti.get("use_worktree") is not False:
            crs.append(_cr(tool, [name] if name else [], cwd, not name, "worktree" if name else "auto", tool=True))
    return crs, why, cwd


# ---------------------------------------------------------------- git adapter
_SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
          "GIT_PREFIX", "GIT_QUARANTINE_PATH", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_LITERAL_PATHSPECS", "GIT_ICASE_PATHSPECS",
          "GIT_REPLACE_REF_BASE", "GIT_NO_REPLACE_OBJECTS", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")
# Every git call: no fsmonitor program, no untracked cache written, every path that diff and log print named from the top of the work tree
# (diff.relative=false), whatever directory below it the call starts in: the hook's session directory or a --repo below the top, and
# diff.ignoreSubmodules=none, which git passes on to the status it runs inside each submodule checkout, so no setting hides a nested change.
_PIN = ["-c", "core.quotepath=false", "-c", "core.longpaths=true", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "diff.relative=false",
        "-c", "diff.ignoreSubmodules=none", "--no-optional-locks"]
# Every diff, log and status call carries --ignore-submodules=none right after its subcommand: a changed gitlink is a changed path, and a submodule
# checkout whose commit differs from its gitlink or that holds changes is an uncommitted change of that path, whatever diff.ignoreSubmodules,
# submodule.<name>.ignore or the ignore of .gitmodules says (the option on the command line overrides all three, a -c pin only the first).
# The only subcommands Git.run starts, none of which talks to a remote (in a partial clone, git itself fetches the objects a diff needs
# from the promisor remote).
LOCAL_GIT = frozenset(("--version", "branch", "check-ref-format", "config", "diff", "for-each-ref", "log", "merge-base", "rev-list", "rev-parse", "status", "worktree"))
_PIN_HINT = "ask the user to pin it in their own terminal: git config magos.target <branch>"


class GitFail(Exception):
    def __init__(self, code, text=""):
        super().__init__(text)
        self.code = code


class Uncertain(Exception):
    pass


_MEMO = None  # set for the duration of a hook call: the facts of a repository are collected once, whatever number of states lead to it


def _memo(key, fn):
    """fn() once per hook call and key (a GitFail or Uncertain it raises is kept as well); outside a hook call fn() every time."""
    if _MEMO is None:
        return fn()
    if key not in _MEMO:
        try:
            _MEMO[key] = (True, fn())
        except (GitFail, Uncertain) as err:
            _MEMO[key] = (False, err)
    ok, value = _MEMO[key]
    if not ok:
        raise value
    return value


class Git:
    def __init__(self, start, budget=BUDGET_S):
        end = time.monotonic() + budget
        self.start, self.deadline, self.common, self.top = start, min(end, HOOK_DEADLINE) if HOOK_DEADLINE else end, None, None

    def run(self, *args, cwd=None, inp=None, ok=(0,), full=False):
        """-> (exit code, stdout), or (exit code, stdout, stderr) with full=True.  An exit code outside `ok` raises GitFail (ok=None: any)."""
        sub = next((a for a in args if not a.startswith(("--git-dir=", "--work-tree="))), None)  # the first argument after the repository
        if sub not in LOCAL_GIT:
            raise GitFail("GIT_FAILED", "git %s is not a subcommand the guard runs" % (sub or "(none)"))
        e = {k: v for k, v in os.environ.items() if k not in _SCRUB and not k.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
        e.update(GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", LC_ALL="C", GIT_OPTIONAL_LOCKS="0")
        cmd = ["git"] + _PIN + (["-C", cwd] if cwd else []) + list(args)
        for attempt in range(3):
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise GitFail("BUDGET_EXCEEDED", "time budget exhausted")
            try:
                p = subprocess.run(cmd, input=inp, stdin=None if inp is not None else subprocess.DEVNULL, capture_output=True, timeout=min(left, 30),
                                   env=e, cwd=self.start, creationflags=0x08000000 if sys.platform == "win32" else 0)
                break
            except subprocess.TimeoutExpired:
                raise GitFail("BUDGET_EXCEEDED", "git timed out: %s" % " ".join(args[:3]))
            except FileNotFoundError:
                if not os.path.isdir(self.start):
                    raise GitFail("GIT_FAILED", "the working directory %s no longer exists" % self.start)
                raise GitFail("GIT_MISSING", "git is not installed or not on PATH")
            except OSError as err:  # e.g. WinError 1455 under memory pressure: retry, then fail closed
                if attempt == 2:
                    raise GitFail("GIT_FAILED", str(err))
                time.sleep(0.2 * (attempt + 1))
        if ok is not None and p.returncode not in ok:  # a failure without a message (a crash, an exit under memory pressure) still names its exit code
            why = p.stderr.decode("utf-8", "replace").strip()[-200:] or "exit code %d" % p.returncode
            raise GitFail("GIT_FAILED", "git %s: %s" % (" ".join(args[:3]), why))
        return (p.returncode, p.stdout, p.stderr) if full else (p.returncode, p.stdout)

    def text(self, *args, **kw):
        return self.run(*args, **kw)[1].decode("utf-8", "replace")


def open_repo(path):
    """-> Git or None (not a git repository); once per directory within a hook call."""
    return _memo(("open", pkey(path) if path else ""), lambda: _open_repo(path))


def _open_repo(path):
    if not path or not os.path.isdir(path):
        return None
    g = Git(path)
    try:
        rc, out = g.run("rev-parse", "--path-format=absolute", "--git-common-dir", ok=(0, 128))
        top = g.run("rev-parse", "--show-toplevel", ok=(0, 128)) if rc == 0 else (128, b"")
    except GitFail as err:
        if err.code in ("GIT_MISSING", "BUDGET_EXCEEDED"):  # neither means "not a repository"
            raise
        return None
    lines = out.decode("utf-8", "replace").splitlines()
    if rc != 0 or not lines:
        return None
    g.common = os.path.normpath(lines[0])
    g.top = os.path.normpath(top[1].decode("utf-8", "replace").strip()) if top[0] == 0 and top[1].strip() else None  # a bare repository has no work tree
    return g


def open_gitdir(path):
    """The repository a --git-dir / GIT_DIR value names, resolved as git resolves it (a git directory, a bare repository or a gitfile),
    or None when git does not take it as a repository."""
    if not path or not os.path.exists(path):
        return None
    start = path if os.path.isdir(path) else os.path.dirname(path)
    rc, out = Git(start).run("--git-dir=" + path, "rev-parse", "--path-format=absolute", "--git-common-dir", ok=(0, 128))
    lines = out.decode("utf-8", "replace").splitlines()
    return open_repo(lines[0].strip()) if rc == 0 and lines else None


def cfg(g, key):
    """Config value; magos.* keys come from the repository's own config only (git -c, GIT_CONFIG_* and global files cannot set them)."""
    rc, out = g.run("config", *(["--local"] if key.startswith("magos.") else []), "--get", key, ok=(0, 1))
    return out.decode("utf-8", "replace").strip() if rc == 0 else None


def pkey(p):
    return os.path.normcase(os.path.normpath(p))


def worktrees(g):
    return _memo(("worktrees", g.common), lambda: _worktrees(g))


def _worktrees(g):
    recs, cur = [], {}
    for tok in g.run("worktree", "list", "--porcelain", "-z")[1].split(b"\0") + [b""]:
        if tok:
            k, _, v = tok.decode("utf-8", "replace").partition(" ")
            cur[k] = v
        elif cur:
            recs.append(cur)
            cur = {}
    out = []
    for r in recs:
        path, br = os.path.normpath(r.get("worktree", "")), r.get("branch", "")
        if "bare" not in r and g.top and not os.path.exists(os.path.join(path, ".git")) and os.path.isfile(os.path.join(path, "HEAD")):
            path = g.top  # inside a submodule git lists the git directory as the worktree: the work tree is the repository's top
        out.append({"path": path, "head": r.get("HEAD", ""), "branch": br[11:] if br.startswith("refs/heads/") else None, "detached": "detached" in r,
                    "bare": "bare" in r, "prunable": "prunable" in r or not os.path.isdir(path), "locked": "locked" in r})
    return out


def list_refs(g):
    return _memo(("refs", g.common), lambda: _list_refs(g))


def _list_refs(g):
    heads, remotes, syms = {}, {}, {}
    for line in g.run("for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)", "refs/heads", "refs/remotes")[1].split(b"\n"):
        if line:
            ref, sha, sym = [x.decode("utf-8", "replace") for x in line.split(b"\0")]
            if ref.startswith("refs/heads/"):
                heads[ref[11:]] = sha
            elif ref.endswith("/HEAD"):
                syms[ref[13:-5]] = sym
            else:
                remotes[ref[13:]] = sha
    return heads, remotes, syms


def _is_anc(g, a, b):
    return g.run("merge-base", "--is-ancestor", a, b, ok=(0, 1))[0] == 0


def resolve_target(g, heads, remotes, syms, arg):
    """Integration target: --target, magos.target, origin/HEAD, init.defaultBranch, a single main/master/develop/trunk; else Uncertain."""
    def lookup(name):
        local, rem = heads.get(name), [s for r, s in remotes.items() if r.split("/", 1)[-1] == name]
        if local and rem and rem[0] != local:
            if _is_anc(g, local, rem[0]):
                return rem[0]
            if not _is_anc(g, rem[0], local):
                raise Uncertain("the local and remote copies of %s diverged" % name)
        return local or (rem[0] if rem else None)
    if arg and lookup(arg) is None:
        raise Uncertain("--target %s does not resolve to a branch" % arg)
    inferred = {"code": "TARGET_INFERRED", "text": "integration target inferred; " + _PIN_HINT}
    chain = [(arg, "high"), (cfg(g, "magos.target"), "high")] + [(s.split("/", 3)[-1], "high") for s in syms.values() if s] + [(cfg(g, "init.defaultBranch"), "medium")]
    for name, conf in chain:
        sha = lookup(name) if name else None
        if sha:
            return {"name": name, "sha": sha, "confidence": conf}, [inferred] * (conf != "high")
    cands = [n for n in ("main", "master", "develop", "trunk") if n in heads]
    if len(cands) == 1:
        return {"name": cands[0], "sha": heads[cands[0]], "confidence": "medium"}, [inferred]
    raise Uncertain("integration target is %s; %s" % ("ambiguous (%s)" % ", ".join(cands) if cands else "unknown", _PIN_HINT))


def _names_z(out):
    return {x.decode("utf-8", "replace") for x in out.split(b"\0") if x}


def committed_paths(g, target_sha, tip):
    """Paths the tip changed relative to the target over every merge base, minus content the target already holds (squash-merged work).
    None when there is no merge base."""
    rc, out = g.run("merge-base", "--all", target_sha, tip, ok=(0, 1))
    bases = out.decode().split()
    if rc != 0 or not bases:
        return None
    diff = ("diff", "--ignore-submodules=none", "--name-only", "-z", "--no-renames", "--no-ext-diff")
    paths = set().union(*(_names_z(g.run(*diff, b, tip, "--")[1]) for b in bases))
    return paths if target_sha in bases else paths & _names_z(g.run(*diff, target_sha, tip, "--")[1])


def parse_status(out):
    toks, paths, i = out.split(b"\0"), set(), 0
    while i < len(toks):
        t = toks[i].decode("utf-8", "replace")
        i += 1
        if t[:1] in ("1", "u"):
            paths.add(t.split(" ", 8 if t[0] == "1" else 10)[-1])
        elif t[:1] == "2":
            paths |= {t.split(" ", 9)[9], toks[i].decode("utf-8", "replace")}  # a rename claims old and new path
            i += 1
        elif t[:1] == "?":
            paths.add(t[2:])
    return paths


def dirty_paths(g, wt):
    return parse_status(g.run("status", "--ignore-submodules=none", "--porcelain=v2", "-z", "--untracked-files=all", "--ignored=no", cwd=wt)[1])


def operation(wt):
    """-> (notes, unreadable) for a worktree: running rebase / merge / cherry-pick / revert / sequencer, and git am or an unreadable git dir."""
    gd = os.path.join(wt, ".git")
    if not os.path.isdir(gd):
        try:
            with open(gd, encoding="utf-8") as fh:
                txt = fh.read().strip()
        except OSError:
            return [], True
        gd = txt[7:].strip() if txt.startswith("gitdir:") else ""
        gd = gd if os.path.isabs(gd) else os.path.normpath(os.path.join(wt, gd))
    notes = [lab for f, lab in (("rebase-merge", "rebase"), ("rebase-apply", "rebase/am"), ("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"),
                                ("REVERT_HEAD", "revert"), ("sequencer", "sequencer")) if os.path.exists(os.path.join(gd, f))]
    return notes, os.path.exists(os.path.join(gd, "rebase-apply", "applying"))


def _claimant(table, key, branch):
    return table.setdefault(key, {"key": key, "branch": branch, "worktrees": [], "declared": [], "paths": {"committed": set(), "uncommitted": set()}})


def gather(g, planned=None, target_arg=None, own_wt=""):
    """Snapshot of every claimant's committed / uncommitted evidence (git only; the planned branch's own lane is left out).  Raises Uncertain / GitFail.
    Once per repository and planned lane within a hook call (each caller gets its own copy of the top-level dict)."""
    return dict(_memo(("gather", g.common, fold(planned) if planned else None, target_arg, pkey(own_wt) if own_wt else ""),
                      lambda: _gather(g, planned, target_arg, own_wt)))


def _gather(g, planned=None, target_arg=None, own_wt=""):
    wts, (heads, remotes, syms) = worktrees(g), list_refs(g)
    target, warns = resolve_target(g, heads, remotes, syms, target_arg)
    own = lane_key(planned) if planned else None
    merged = set(g.text("for-each-ref", "--merged=" + target["sha"], "--format=%(refname)", "refs/heads", "refs/remotes").split("\n")) - {""}
    unknowns, table, jobs = [], {}, []
    tips = [(lane_key(n), n, s) for n, s in heads.items() if "refs/heads/" + n not in merged and lane_key(n) != own]
    if len(tips) > MAX_CLAIMANTS:
        unknowns.append({"code": "TOO_MANY_CLAIMANTS", "text": "%d unmerged local branches exceed the cap of %d" % (len(tips), MAX_CLAIMANTS)})
        tips = []
    far = []
    for r, s in sorted(remotes.items()):
        short = r.split("/", 1)[-1]
        if "refs/remotes/" + r in merged or short == target["name"]:
            continue
        if short not in heads or (heads[short] != s and not _is_anc(g, s, heads[short])):
            far.append(("rm:" + fold(r), r, s))
    if len(far) > MAX_REMOTES:
        warns.append({"code": "REMOTE_TRUNCATED", "text": "%d unmerged remote-tracking branches: only the first %d are analysed" % (len(far), MAX_REMOTES)})
    tips += far[:MAX_REMOTES]
    for key, name, sha in tips:
        _claimant(table, key, name)
        jobs.append(("c", key, name, sha))
    if remotes:
        warns.append({"code": "REMOTE_AS_OF_LAST_FETCH", "text": "remote-tracking branches are only as fresh as the last fetch (the guard never fetches)"})
    for w in wts:
        if w["bare"] or (w["branch"] and lane_key(w["branch"]) == own) or (own_wt and not w["branch"] and pkey(w["path"]) == pkey(own_wt)):
            continue
        if w["prunable"]:
            if w["locked"]:  # a locked worktree is kept for a reason (an offline drive): its work cannot be seen
                unknowns.append({"code": "WORKTREE_UNREADABLE", "text": "%s is locked and missing on disk" % w["path"]})
            else:
                warns.append({"code": "WORKTREE_PRUNABLE", "text": "%s is missing on disk" % w["path"]})
            continue
        notes, bad = operation(w["path"])
        if bad:
            unknowns.append({"code": "OP_METADATA_UNREADABLE", "text": "%s: a git am or a worktree whose metadata cannot be read" % w["path"]})
        if notes:
            warns.append({"code": "OP_IN_PROGRESS", "text": "%s: %s in progress" % (w["path"], "/".join(notes))})
        key = lane_key(w["branch"]) if w["branch"] else "wt:" + pkey(w["path"])
        _claimant(table, key, w["branch"])["worktrees"].append(w["path"])
        jobs.append(("u", key, w["path"], None))
        if not w["branch"] and w["head"].strip("0"):  # a detached worktree's commits are its own work
            jobs.append(("c", key, w["path"], w["head"]))

    def work(j):
        try:
            return j, (committed_paths(g, target["sha"], j[3]) if j[0] == "c" else dirty_paths(g, j[2])), None
        except GitFail as err:
            return j, None, err
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, jobs))
    for (kind, key, label, _sha), paths, err in results:
        if err:
            unknowns.append({"code": "STATUS_FAILED" if kind == "u" else err.code, "text": "%s: %s" % (label, err)})
        elif kind == "c" and paths is None:  # no common history: a merge would need --allow-unrelated-histories, so it cannot collide
            warns.append({"code": "UNRELATED_HISTORY", "text": "%s shares no history with %s and is ignored" % (label, target["name"])})
        else:
            table[key]["paths"]["committed" if kind == "c" else "uncommitted"] |= paths
    return {"target": target, "claimants": list(table.values()), "unknowns": unknowns, "warnings": warns, "heads": heads, "merged": merged,
            "wt_branches": {w["branch"] for w in wts if w["branch"]}, "deadline": g.deadline}


# ---------------------------------------------------------------- claim store: <git-common-dir>/magos (shared by all worktrees, never in a work tree)
def store(g):
    return os.path.join(g.common, "magos")


def claim_path(g, name):
    return os.path.join(store(g), "claims", *name.split("/")) + ".claim"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def who(g):
    try:
        login = getpass.getuser()
    except Exception:  # no username in the environment (a service account, a container)
        login = "unknown"
    return "%s <%s> (%s)" % (cfg(g, "user.name") or "?", cfg(g, "user.email") or "?", login)


class LockTimeout(Exception):
    pass


class Lock:
    """OS file lock on <store>/lock: the OS drops it when the holder dies, so there is no stale-lock rule."""

    def __init__(self, g):
        self.g, self.fh = g, None

    def __enter__(self):
        os.makedirs(store(self.g), exist_ok=True)
        self.fh = open(os.path.join(store(self.g), "lock"), "a+b")
        limit = time.monotonic() + float(os.environ.get("MAGOS_LOCK_TIMEOUT", LOCK_S))
        while True:
            try:
                self.fh.seek(0)
                if msvcrt:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() > limit:
                    self.fh.close()
                    raise LockTimeout()
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self.fh.seek(0)
            if msvcrt:
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()


def _read_retry(path):
    for attempt in range(5):
        try:
            with open(path, "rb") as fh:
                return fh.read().decode("utf-8-sig")
        except PermissionError:  # a writer's os.replace on Windows
            time.sleep(0.02)
    raise PermissionError(path)


CLAIM_KEYS = ("branch", "worktree", "target", "base", "created", "by", "override")  # the scalar keys of a claim, each at most once
_CTL = re.compile(r"[\x00-\x1f\x7f]")


class ClaimTooNew(Exception):
    """A claim written in a format newer than CLAIM_FORMAT: never read as if it were this format, never overwritten, never released.
    .v is the format number (an int; the digit text for a number too long for int())."""

    def __init__(self, v, branch):
        super().__init__("claim format v=%s is newer than this guard's v=%d" % (v, CLAIM_FORMAT))
        self.v, self.branch = v, branch


class ClaimRefused(ValueError):
    """write_claim refuses: a value with a control character, or a claim file that holds another branch's claim."""


class BadClaim(str):
    """An unusable claim file in read_claims' second list: the str is its path below claims/; .code is CLAIM_UNPARSEABLE or
    CLAIM_NEWER_FORMAT, and a newer-format claim carries .branch (None without a branch line) and .v."""

    def __new__(cls, rel, code="CLAIM_UNPARSEABLE", branch=None, v=None):
        s = str.__new__(cls, rel)
        s.code, s.branch, s.v = code, branch, v
        return s

    @property
    def text(self):
        if self.code == "CLAIM_NEWER_FORMAT":
            return newer_text(self.branch or "claims/" + self.replace(os.sep, "/"), self.v)
        return str(self)


def newer_text(name, v):
    return "%s was written by a newer MAGOS (v=%s); upgrade this guard" % (name, v)


_FORMAT_DIGITS = re.compile(r"[0-9]+")  # the value of the format line: ASCII digits only (int() alone would take '1_0', '+1', ' 1', other digits)


def format_number(value):
    """The claim format a line-2 value `v=<value>` names: one or more ASCII digits read as a decimal integer whatever its length and
    leading zeros.  -> int (the digit text, leading zeros removed, for a number too long for int()), or None when the spelling is not
    allowed."""
    if not _FORMAT_DIGITS.fullmatch(value):
        return None
    digits = value.lstrip("0") or "0"
    return int(digits) if len(digits) <= 4000 else digits  # int() refuses more than 4300 digits from Python 3.11 on


def parse_claim(text):
    """A claim file -> dict.  Line 1 is exactly `state=active` (the git layer reads only that line); line 2 `v=<n>` is the format (missing: 1;
    any value up to CLAIM_FORMAT, 0 included, is this guard's format).  The scalar keys appear at most once; `entry=` lines make the entry
    list; a `state=` or `v=` line elsewhere changes nothing; any other key is kept aside in 'extra' and written back unchanged.  Raises
    ValueError (unreadable) or ClaimTooNew."""
    lines = text.replace("\r", "").split("\n")
    if lines[0] != "state=active":
        raise ValueError("not a claim: line 1 is not state=active")
    v, rest = 1, lines[1:]
    if rest and rest[0].startswith("v="):
        n = format_number(rest[0][2:])
        if n is None:
            raise ValueError("the claim format line is not v=<digits>")
        if isinstance(n, str) or n > CLAIM_FORMAT:
            raise ClaimTooNew(n, next((ln[7:] for ln in rest[1:] if ln.startswith("branch=") and ln[7:]), None))
        v, rest = CLAIM_FORMAT, rest[1:]
    doc, extra = {"entries": [], "v": v}, []
    for line in rest:
        k, sep, val = line.partition("=")
        if not sep or not k or k in ("state", "v"):
            continue
        if k == "entry":
            doc["entries"].append(val)
        elif k in CLAIM_KEYS:
            if k in doc:
                raise ValueError("the key %s appears twice" % k)
            doc[k] = val
        else:
            extra.append((k, val))
    if not doc.get("branch") or not doc["entries"]:
        raise ValueError("not a claim")
    for k in CLAIM_KEYS:
        doc.setdefault(k, "")
    doc["extra"] = extra
    return doc


def read_claims(g):
    """-> ({folded branch: claim}, [BadClaim]): every unusable claim file is listed, a newer-format one with its branch and format.  Once per
    repository within a hook call."""
    return _memo(("claims", g.common), lambda: _read_claims(g))


def _read_claims(g):
    root, claims, bad = os.path.join(store(g), "claims"), {}, []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            if f.endswith(".claim"):
                p = os.path.join(d, f)
                rel = os.path.relpath(p, root)
                try:
                    doc = parse_claim(_read_retry(p))
                except ClaimTooNew as err:
                    bad.append(BadClaim(rel, "CLAIM_NEWER_FORMAT", err.branch, err.v))
                    continue
                except (OSError, ValueError):
                    bad.append(BadClaim(rel))
                    continue
                doc["file"] = p
                claims[fold(doc["branch"])] = doc
    return claims, bad


def newer_claim(bad, name):
    """The newer-format claim of branch `name` among read_claims' unusable files, or None."""
    return next((b for b in bad if b.code == "CLAIM_NEWER_FORMAT" and b.branch and fold(b.branch) == fold(name)), None)


def _replace(tmp, path, tries=40):
    """os.replace, retried while Windows reports the target busy (a reader holds it open)."""
    for attempt in range(tries):
        try:
            return os.replace(tmp, path)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05)


def _remove(path, tries=40):
    """os.remove, retried while Windows reports the file busy (a reader holds it open)."""
    for attempt in range(tries):
        try:
            return os.remove(path)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05)


def write_atomic(path, data, mode=None):
    """Write bytes to a temporary file beside `path` (with `mode` on POSIX when given), then move it into place: the file is replaced whole
    or not at all, and a failure leaves no temporary file behind."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        if mode is not None and os.name != "nt":
            os.chmod(tmp, mode)
        _replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def claim_bytes(g, name, doc):
    """-> (path, text) of the claim of `name` in format CLAIM_FORMAT.  Refuses (ClaimRefused) a value with a control character (each one in
    `by` becomes a space) and a claim file that holds another branch's claim or cannot be read; refuses (ClaimTooNew) to overwrite a
    newer-format claim.  Nothing is written: write_claim and the set commands put the text in place."""
    path = claim_path(g, name)
    vals = {k: str(doc.get(k) or "") for k in CLAIM_KEYS}
    vals["by"] = _CTL.sub(" ", vals["by"])
    extra = [(str(k), str(v)) for k, v in doc.get("extra") or [] if k not in CLAIM_KEYS + ("entry", "state", "v")]
    ctl = [k for k, v in vals.items() if _CTL.search(v)] + ["entry" for e in doc["entries"] if _CTL.search(e)] + \
        [k for k, v in extra if _CTL.search(k + v) or "=" in k]
    if ctl:
        raise ClaimRefused("a claim value contains a control character (%s)" % ", ".join(sorted(set(ctl))))
    if fold(vals["branch"]) != fold(name):
        raise ClaimRefused("the claim names %s, not %s" % (vals["branch"], name))
    if os.path.isdir(path):
        raise ClaimRefused("%s is a directory of other claims" % path)
    if os.path.lexists(path):
        try:
            other = parse_claim(_read_retry(path))
        except (OSError, ValueError):
            raise ClaimRefused("the claim file %s cannot be read; release it first" % path)
        if fold(other["branch"]) != fold(name):
            raise ClaimRefused("the claim file %s holds the claim of %s" % (path, other["branch"]))
    lines = ["state=active", "v=%d" % CLAIM_FORMAT] + ["%s=%s" % (k, vals[k]) for k in CLAIM_KEYS] + ["%s=%s" % kv for kv in extra]
    return path, ("\n".join(lines + ["entry=" + e for e in doc["entries"]]) + "\n").encode("utf-8")


def write_claim(g, name, doc):
    """Write the claim of `name` in format CLAIM_FORMAT (claim_bytes states what it refuses), whole or not at all."""
    path, data = claim_bytes(g, name, doc)
    write_atomic(path, data)


def audit_line(g, by=None, **rec):
    """One line of audit.log as UTF-8 bytes; a set command builds it before its write, so that no field of it can fail after that write."""
    return (json.dumps(dict(ts=now_iso(), by=who(g) if by is None else by, **rec), ensure_ascii=False) + "\n").encode("utf-8")


def append_audit(g, line):
    os.makedirs(store(g), exist_ok=True)
    with open(os.path.join(store(g), "audit.log"), "ab") as fh:
        fh.write(line)


def audit(g, **rec):
    append_audit(g, audit_line(g, **rec))


def audit_after(g, line, warns):
    """Append the audit line of a set write that is already made: a failure leaves the change in place and adds the warning AUDIT_NOT_WRITTEN."""
    try:
        append_audit(g, line)
    except OSError as err:
        warns.append({"code": "AUDIT_NOT_WRITTEN", "text": "the change is made, but audit.log could not be appended: %s" % err})


def read_override(g, fp):
    try:
        doc = json.loads(_read_retry(os.path.join(store(g), "override", fp + ".json")))
        return doc if doc.get("fp") == fp and doc.get("expires", "") > now_iso() else None
    except (OSError, ValueError):
        return None


def alias_problem(name):
    """-> the Windows alias rule's reason when a claim file under `name` would alias another branch's claim file, or None."""
    if any(c.endswith((".", " ")) or fold(c).endswith(".claim") for c in name.split("/")):
        return ("a path component ends in '.', a space or '.claim', so its claim file would alias another branch's on Windows "
                "(Windows alias rule: Windows drops trailing dots and spaces, and <x>.claim is the claim file of <x>)")
    return None


def name_problem(g, name, stored=False):
    """-> the intrinsic reason the branch name cannot be a lane (the rules that need no other branch), or None.  `stored`: the name of a
    claim an earlier guard stored, which keeps allowing the creation of its branch: only the Windows alias rule is not applied to it."""
    if name.startswith("-") or g.run("check-ref-format", "--branch", name, ok=(0, 1, 128))[0] != 0:
        return "not a valid git branch name"
    if len(name) > 100 or re.search(r'[<>|"]', name):
        return "longer than 100 characters or contains one of < > | \""
    if any(re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", c.lower()) for c in name.split("/")):
        return "a path component is a Windows reserved device name"
    return None if stored else alias_problem(name)


def name_clash(name, others):
    """-> the reason the branch name clashes with one of the branch names `others` (a ref cannot be both a file and a directory; a case or
    Unicode normalisation collision), or None."""
    f = fold(name)
    for other in others:
        o = fold(other)
        if o != f and (f.startswith(o + "/") or o.startswith(f + "/")):
            return "clashes with the existing branch or claim %s (a ref cannot be both a file and a directory)" % other
        if other != name and o == f:
            return "collides with %s once case and Unicode normalisation are ignored" % other
    return None


def check_name(g, name, claims, stored=False):
    """-> reason the branch name cannot be a lane, or None (name_problem, then name_clash against the branches and the `claims`)."""
    return name_problem(g, name, stored) or name_clash(name, list(list_refs(g)[0]) + [d["branch"] for d in claims.values()])


# ---------------------------------------------------------------- judge and commands
def real_branch(doc, heads):
    f = fold(doc["branch"])
    return next((n for n in heads if fold(n) == f), None)


def is_idle(doc, heads, merged, wt_branches, target_sha):
    """An integrated lane without a workspace: its branch is merged, nobody has it checked out, and it moved beyond the plan's base and the target tip."""
    b = real_branch(doc, heads)
    return b is not None and "refs/heads/" + b in merged and b not in wt_branches and heads[b] not in (target_sha, doc.get("base"))


def with_declared(claimants, claims, own, snap):
    table, bad, heads = {c["key"]: dict(c, declared=list(c["declared"])) for c in claimants}, [], snap["heads"]
    for fname, doc in claims.items():
        key = lane_key(doc["branch"])
        if is_integration_claim(doc):
            continue  # the integration branch of a set is the whole, assembled from the lanes: its claim claims no files, and is never parsed
        if key == own or is_idle(doc, heads, snap["merged"], snap["wt_branches"], snap["target"]["sha"]):
            continue  # the lane itself, or an integrated lane that no longer has a workspace (idle)
        try:
            ents = [parse_entry(r) for r in doc["entries"]]
        except ManifestError:
            bad.append(doc["branch"])
            continue
        planned = real_branch(doc, heads) is None and key not in table
        _claimant(table, key, doc["branch"])["declared"] = ents
        table[key]["planned"] = planned
    return list(table.values()), bad


def deny(code, **kw):
    return dict({"decision": "deny", "code": code, "conflicts": [], "unknowns": [], "warnings": [], "fingerprint": None}, **kw)


def judge(snap, claims, bad_claims, name, entries, override, declared=None):
    """`declared`: what with_declared returns for `name`, when the caller has computed it (set-plan computes it once for all its lanes)."""
    key = lane_key(name)
    cl, bad = declared if declared is not None else with_declared(snap["claimants"], claims, key, snap)
    conflicts = evaluate(entries, cl, snap.get("deadline"))
    unknowns = list(snap["unknowns"]) + [{"code": "CLAIM_UNPARSEABLE", "text": b} for b in bad] + \
        [{"code": getattr(b, "code", "CLAIM_UNPARSEABLE"), "text": getattr(b, "text", b)} for b in bad_claims]
    fp = fingerprint(key, conflicts, [u["code"] for u in unknowns], snap["target"]["sha"])
    v = {"decision": "allow", "code": "OK", "conflicts": conflicts, "unknowns": unknowns, "warnings": snap["warnings"], "target": snap["target"],
         "fingerprint": fp, "overridden": False}
    if conflicts or unknowns:
        v["code"] = "CONFLICT" if conflicts else "UNKNOWN"
        if fp == override:
            v["overridden"], v["code"] = True, "OVERRIDDEN"
        else:
            v["decision"] = "deny"
    return v


def backstop_warnings(g, lanes):
    """The warnings about the git backstop: NOT_ARMED when parallel lanes exist (`lanes`) and the backstop is not installed, HOOK_BYPASSED when it
    is installed and core.hooksPath keeps git from running it."""
    armed, found = os.path.exists(os.path.join(store(g), "ARMED")), []
    if not armed and lanes:
        found.append({"code": "NOT_ARMED", "text": "parallel lanes exist but the git backstop is not installed; the user can run `arm`"})
    if armed and g.run("config", "--get", "core.hooksPath", ok=(0, 1))[0] == 0:
        found.append({"code": "HOOK_BYPASSED", "text": "core.hooksPath is set: git no longer runs the backstop; tell the user (arm refuses while it is set)"})
    return found


def plan_core(g, name, entries, write, amend, lang, target_arg=None, worktree="", stored=False):
    """Judge `name` against every claimant; with write=True register the claim atomically.  Returns a verdict dict.  `stored`: `name` is the
    branch of a claim that exists (the host hook judging its creation), so a name an earlier guard stored is not refused by the alias rule."""
    claims, bad_claims = read_claims(g)
    if worktree and _CTL.search(worktree):
        return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [WORKTREE] %r: the worktree path contains a control character" % worktree))
    reason = check_name(g, name, {k: d for k, d in claims.items() if k != fold(name)}, stored)
    if reason:
        return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [BRANCH_NAME] %s: %s" % (name, reason)))
    own_wt = os.path.abspath(worktree) if worktree else (claims.get(fold(name)) or {}).get("worktree", "")
    try:
        snap = gather(g, name, target_arg, own_wt)
    except (Uncertain, GitFail) as err:
        return deny("UNKNOWN", unknowns=[{"code": getattr(err, "code", "TARGET_UNCERTAIN"), "text": str(err)}])
    snap["warnings"] = snap["warnings"] + backstop_warnings(g, bool(claims) or any(c["paths"]["committed"] or c["paths"]["uncommitted"] for c in snap["claimants"]))

    def judge_now(claims, bad_claims):
        old = claims.get(fold(name))
        same = bool(old) and {e.raw for e in entries} == set(old["entries"]) and (not worktree or pkey(old["worktree"] or ".") == pkey(os.path.abspath(worktree)))
        owner = branch_set(g, name, old) if write and not same and newer_claim(bad_claims, name) is None else None  # a newer-format claim is the claim gate's
        if owner:  # a branch of a set, its claim missing or set-less included: its claim is written only by set-plan
            return deny("LANE_EXISTS", message=T(lang, "lane_in_set", b=name, s=owner), target=snap["target"])
        if not old and name in snap["heads"]:
            return deny("BRANCH_EXISTS", message=T(lang, "branch_exists", b=name), target=snap["target"])
        if old and not same and not amend:
            return deny("LANE_EXISTS", message=T(lang, "lane_exists", b=name), target=snap["target"])
        shrink = bool(old) and amend and {e.raw for e in entries} <= set(old["entries"])
        v = judge(snap, claims, bad_claims, name, entries, None)
        if v["decision"] == "deny" and write:  # only plan reads (and consumes) an override record; the hook honours the claim's override field
            rec = read_override(g, v["fingerprint"])
            if rec:
                v = judge(snap, claims, bad_claims, name, entries, v["fingerprint"])
                v["override_reason"] = rec.get("reason")
        if shrink:
            v = dict(v, decision="allow", code="OK", conflicts=[], unknowns=[], overridden=False)
        v["unchanged"] = same
        v["worktree"] = old["worktree"] if same else os.path.abspath(worktree).replace("\\", "/") if worktree else (old["worktree"] if old else "")  # what the claim registers
        return v
    if not write:
        return judge_now(claims, bad_claims)
    try:
        with Lock(g):
            claims, bad_claims = read_claims(g)
            reason = check_name(g, name, {k: d for k, d in claims.items() if k != fold(name)})  # again: another planner may have registered meanwhile
            if reason:
                return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [BRANCH_NAME] %s: %s" % (name, reason)), target=snap["target"])
            v = judge_now(claims, bad_claims)
            if v["decision"] == "deny" or v["unchanged"] and not v["overridden"]:
                return v
            old = claims.get(fold(name))
            owner = branch_set(g, name, old) if old else None
            if owner:  # a branch of a set: plan never writes its claim, not even the re-plan of an override that judge_now found unchanged
                return deny("LANE_EXISTS", message=T(lang, "lane_in_set", b=name, s=owner), target=snap["target"])
            doc = {"branch": name, "worktree": v["worktree"], "target": snap["target"]["name"],
                   "base": snap["target"]["sha"], "created": now_iso(), "by": who(g), "override": v["fingerprint"] if v["overridden"] else "",
                   "entries": [e.raw for e in entries], "extra": old["extra"] if old and old.get("v") == CLAIM_FORMAT else []}
            try:
                write_claim(g, name, doc)
            except ClaimTooNew as err:
                return deny("UNKNOWN", unknowns=[{"code": "CLAIM_NEWER_FORMAT", "text": newer_text(name, err.v)}], target=snap["target"])
            except ClaimRefused as err:
                return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [BRANCH_NAME] %s: %s" % (name, err)), target=snap["target"])
            audit(g, op="amend" if name and claims.get(fold(name)) else "plan", branch=name, entries=doc["entries"], fingerprint=v["fingerprint"],
                  overridden=v["overridden"], reason=v.get("override_reason"), host="cli")
            if v["overridden"]:
                try:
                    os.remove(os.path.join(store(g), "override", v["fingerprint"] + ".json"))
                except OSError:
                    pass
            return v
    except LockTimeout:
        return deny("LOCK_TIMEOUT", message=T(lang, "lock", s=os.environ.get("MAGOS_LOCK_TIMEOUT", int(LOCK_S))), target=snap["target"])


def out_text(s):
    data = (s if s.endswith("\n") else s + "\n").encode("utf-8")
    if getattr(sys.stdout, "buffer", None):
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(data.decode("utf-8"))
    sys.stdout.flush()


def decode_manifest(raw):
    try:
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):  # PowerShell 5.1 `>` and Out-File write UTF-16
            return raw.decode("utf-16")
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ManifestError("ENCODING", "the manifest is not UTF-8 (ANSI file?): use --paths, stdin, or Out-File -Encoding utf8")


def read_manifest(g, args):
    lines = list(args.paths or [])
    if args.manifest:
        if args.manifest == "-":
            raw = sys.stdin.buffer.read()
        else:
            p = os.path.abspath(args.manifest)
            if any(pkey(p).startswith(pkey(w["path"]) + os.sep) for w in worktrees(g)):
                raise ManifestError("MANIFEST_IN_WORKTREE", "write the manifest outside every worktree (it would dirty it) or use --paths / stdin: %s" % p)
            with open(p, "rb") as fh:
                raw = fh.read()
        lines += decode_manifest(raw).replace("\r", "").split("\n")
    return parse_manifest(lines)


def finish(args, v, name):
    v["message"] = v.get("message") or render(args.lang, v, name)
    v["exit_code"] = EXIT.get(v["code"], 10)
    out_text(json.dumps(v, ensure_ascii=False, default=sorted) if args.json else v["message"])
    return v["exit_code"]


def cmd_plan(args, write):
    g = open_repo(args.repo)
    if g is None:
        sys.stderr.write("not a git repository: %s\n" % args.repo)
        return 2
    try:
        entries, errors = read_manifest(g, args)
    except ManifestError as err:
        entries, errors = [], [(err.code, str(err))]
    if errors:
        return finish(args, deny("INVALID_MANIFEST", message=T(args.lang, "invalid", errors="\n".join("  [%s] %s" % e for e in errors))), args.branch)
    v = plan_core(g, args.branch, entries, write, getattr(args, "amend", False), args.lang, getattr(args, "target", None), getattr(args, "worktree", ""))
    if write and v.get("decision") == "deny":  # the override dialog names the branches of this denial (check writes nothing)
        note_denial(g, args.branch, v)
    path = v.pop("worktree", "") or "<path>"  # the worktree the claim registers, no key of the --json verdict
    if v["decision"] == "allow" and "message" not in v:
        v["message"] = "\n".join([T(args.lang, "ok_plan", b=args.branch, n=len(entries), example='git worktree add "%s" -b %s %s' % (path, args.branch, v["target"]["name"]))
                                  if write else T(args.lang, "ok_check")] + ["(%s) %s" % (w["code"], w["text"]) for w in v["warnings"]])
    return finish(args, v, args.branch)


def merged_set(g):
    """-> (refs merged into the target, target sha); empty when the target cannot be resolved."""
    try:
        heads, remotes, syms = list_refs(g)
        target, _ = resolve_target(g, heads, remotes, syms, None)
        return {x for x in g.text("for-each-ref", "--merged=" + target["sha"], "--format=%(refname)", "refs/heads").split("\n") if x}, target["sha"]
    except (Uncertain, GitFail):
        return set(), None


def lane_state(doc, heads, merged, wts):
    """planned (no branch yet), active (unmerged work, a workspace, or a fresh branch) or idle (integrated, no workspace)."""
    refs, target_sha = merged
    b = real_branch(doc, heads)
    in_wt = [w["path"] for w in wts if (b and w["branch"] == b) or (doc["worktree"] and pkey(w["path"]) == pkey(doc["worktree"]))]
    if b is None:
        return ("active" if in_wt else "planned"), in_wt
    return ("idle" if is_idle(doc, heads, refs, {w["branch"] for w in wts if w["branch"]}, target_sha) else "active"), in_wt


def cmd_list(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    claims, bad = read_claims(g)
    heads, merged, wts, rows = list_refs(g)[0], merged_set(g), worktrees(g), []
    drift = {}
    if args.drift and claims:
        try:
            snap = gather(g)
            drift = {c["key"]: sorted(c["paths"]["committed"] | c["paths"]["uncommitted"]) for c in snap["claimants"]}
        except (Uncertain, GitFail):
            pass
    for doc in sorted(claims.values(), key=lambda d: d["created"]):
        st, in_wt = lane_state(doc, heads, merged, wts)
        row = {"branch": doc["branch"], "state": st, "entries": doc["entries"], "created": doc["created"], "by": doc["by"], "override": doc["override"] or None, "worktrees": in_wt}
        refused = alias_problem(doc["branch"])
        if refused:  # stored by an earlier guard: it still allows its branch, but plan refuses the name
            row["refused_name"] = refused
        owner = claim_set(doc)
        if owner is not None:  # a claim of a set: the set and its lane (the integration claim: role integration, no lane)
            row["set"] = owner
            if is_integration_claim(doc):
                row.update(lane=None, role="integration")
            elif claim_extra(doc, "lane"):
                row["lane"] = claim_extra(doc, "lane")[0]
        if args.drift:
            try:
                ents = [parse_entry(r) for r in doc["entries"]]
            except ManifestError:
                ents = None  # an unparseable claim is reported by doctor; its drift cannot be computed
            row["drift"] = [] if ents is None or row.get("role") else [p for p in drift.get(lane_key(doc["branch"]), []) if not any(path_hit(e, fpath(p)) for e in ents)]
        rows.append(row)

    def label(r):
        return " set %s" % r["set"] + ("/" + (r["lane"] or r["role"]) if r.get("lane") or r.get("role") else "") if "set" in r else ""
    lines = ["%-8s%s %s  [%s]%s%s" % (r["state"], label(r), r["branch"], ", ".join(r["entries"]), "  drift: " + _few(r["drift"]) if r.get("drift") else "",
                                    " (name refused by plan: %s)" % r["refused_name"] if r.get("refused_name") else "") for r in rows]
    for b in bad:  # claims the guard cannot use are shown too: they deny every creation, and this is where the user sees why
        path = b.replace(os.sep, "/")
        if b.code == "CLAIM_NEWER_FORMAT":
            rows.append({"branch": b.branch, "state": "newer-format", "v": b.v, "path": path})
            lines.append("newer-format %s (v=%s): upgrade this guard" % (b.branch or "claims/" + path, b.v))
        else:
            rows.append({"branch": None, "state": "unreadable", "path": path})
            lines.append("unreadable claims/%s" % path)
    out_text(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n".join(lines) or "(no claims)")
    return 0


def user_console():
    """True only for a real console / tty.  isatty() is TRUE for NUL on Windows (and in the PowerShell tool); GetConsoleMode is not."""
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            return bool(k.GetConsoleMode(k.GetStdHandle(-10), ctypes.byref(ctypes.c_uint32())) and sys.stdout.isatty())
        return os.isatty(0) and sys.stdout.isatty()
    except Exception:
        return False


def challenge(expected, lang):
    """User-only confirmation: refuses at once without a console (no read, so no hang); waits 120 s for typed input otherwise."""
    if not user_console():
        sys.stderr.write(T(lang, "need_tty") + "\n")
        return False
    sys.stderr.write("Type %s to confirm: " % expected)
    sys.stderr.flush()
    box = []
    t = threading.Thread(target=lambda: box.append(sys.stdin.readline().strip()), daemon=True)
    t.start()
    t.join(120)
    if not box:
        os._exit(EXIT["CONSOLE_REQUIRED"])  # the reader thread may still hold stdin
    return box[0] == expected


def _rename(src, dst, tries=40):
    """os.rename, retried while Windows reports a file busy (a reader holds it open).  It succeeds once: a second rename of `src` finds no file."""
    for attempt in range(tries):
        try:
            return os.rename(src, dst)
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05)


def _record_expiry(rec):
    """The `expires` of an approval or denial record as a finite number of seconds since the epoch (ValueError, TypeError or KeyError when it
    has none, or one too large for a float)."""
    try:
        v = float(rec["expires"])
    except OverflowError:  # an integer of hundreds of digits
        raise ValueError("expires is too large")
    if not math.isfinite(v):
        raise ValueError("expires is not a finite number")
    return v


def strip_approval(argv):
    """The argument list without its one approval option (--approval=<t>, or --approval and its value), or None when it holds none or more
    than one."""
    hits = [k for k, w in enumerate(argv or []) if w == "--approval" or w.startswith("--approval=")]
    if len(hits) != 1:
        return None
    k = hits[0]
    return argv[:k] + argv[k + (2 if argv[k] == "--approval" else 1):]


def consume_approval(args, root, where):
    """Verify and consume the --approval token of a user-only command (Approval, Verification in the command) -> (None, record), or (exit code,
    None) after its message on stderr.  <sha256>.json is renamed <sha256>.used first, so of two uses one wins and a failed check burns the
    token; the renamed record must then be of format 1 and unused, unexpired, and issued for this subcommand, this repository or default guard
    home (`where`) and exactly this argument list.  No message names the token."""
    def refuse(code, key, **kw):
        sys.stderr.write(T(args.lang, key, **kw) + "\n")
        return EXIT[code], None
    token = args.approval or ""
    if not _APPROVAL_TOKEN.fullmatch(token):
        return refuse("APPROVAL_UNKNOWN", "approval_unknown")
    h = hashlib.sha256(token.encode("ascii")).hexdigest()
    live, used = os.path.join(root, h + ".json"), os.path.join(root, h + ".used")
    try:
        _rename(live, used)
    except FileNotFoundError:
        return refuse("APPROVAL_USED", "approval_used") if os.path.isfile(used) else refuse("APPROVAL_UNKNOWN", "approval_unknown")
    except FileExistsError:  # Windows: a .used file of the same token beside a live record
        return refuse("APPROVAL_USED", "approval_used")
    try:
        rec = json.loads(_read_retry(used))
        if not (isinstance(rec, dict) and rec.get("v") == 1 and rec.get("used") is False and rec.get("via") in ("prompt", "auto-safe")):
            raise ValueError("not an approval record of format 1")
        expires = _record_expiry(rec)
    except (OSError, ValueError, TypeError, KeyError):
        return refuse("APPROVAL_UNKNOWN", "approval_unknown")
    if time.time() > expires:
        return refuse("APPROVAL_EXPIRED", "approval_expired")
    if rec.get("sub") != args.cmd:
        return refuse("APPROVAL_MISMATCH", "approval_mismatch", what=T(args.lang, "what_sub"))
    w = rec.get("where")
    if not isinstance(w, str) or not (pkey(w) == pkey(where) or same_file(w, where)):
        return refuse("APPROVAL_MISMATCH", "approval_mismatch", what=T(args.lang, "what_home" if args.cmd == "install" else "what_repo"))
    if rec.get("argv") != strip_approval(getattr(args, "argv", None)):
        return refuse("APPROVAL_MISMATCH", "approval_mismatch", what=T(args.lang, "what_args"))
    return None, rec


def user_gate(args, root, where, retype=None, dry=False):
    """The approval of a user-only command -> (exit code or None, via, record).  With --approval the token is verified and consumed
    (consume_approval) and neither the console nor the challenge is asked, also for a dry run; without it a dry run needs nothing, and every
    other run a real console and, with `retype`, the user typing it (challenge).  via: terminal, or the record's prompt or auto-safe."""
    if getattr(args, "approval", None) is not None:
        code, rec = consume_approval(args, root, where)
        return code, (rec or {}).get("via"), rec
    if dry:
        return None, None, None
    if retype is not None:
        return (None, "terminal", None) if challenge(retype, args.lang) else (EXIT["CONSOLE_REQUIRED"], None, None)
    if user_console():
        return None, "terminal", None
    sys.stderr.write(T(args.lang, "need_tty") + "\n")
    return EXIT["CONSOLE_REQUIRED"], None, None


def approval_fields(rec):
    """The audit fields of a run approved by a token: the tool_use_id of its record, and its route when the record names one of the two routes
    of version 1.0.8: `mcp` with the client that asked (Codex approval), or `hermes` (Hermes approval).  Any other value adds nothing, so the
    lines of Claude Code and of a real terminal stay those of 1.0.7."""
    if not rec:
        return {}
    fields = {"tool_use_id": rec.get("tool_use_id")}
    if rec.get("route") == "mcp":
        fields.update(route="mcp", client=rec.get("client"))
    elif rec.get("route") == "hermes":
        fields["route"] = "hermes"
    return fields


def ref_spelling(name):
    """A branch spelling read as a ref path: a backslash is a separator, empty and `.` segments are dropped, `..` is resolved."""
    parts = []
    for part in name.replace("\\", "/").split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    return "/".join(parts)


def cmd_release(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    branch = ref_spelling(args.branch) or args.branch
    try:
        with Lock(g):
            claims, bad = read_claims(g)
            root = os.path.join(store(g), "claims")
            spelled = in_store(root, claim_path(g, branch))  # the claim file this spelling names, when it lies inside the store

            def named(p):
                return spelled is not None and os.path.normcase(in_store(root, p) or "") == os.path.normcase(spelled)
            doc = claims.get(fold(branch)) or next((d for d in claims.values() if named(claim_path(g, d["branch"]))), None)
            newer = newer_claim(bad, branch) or next((b for b in bad if b.code == "CLAIM_NEWER_FORMAT" and named(os.path.join(root, b))), None)
            if newer is not None:  # a newer guard's claim is never released by this one: its rules for releasing cannot be known
                sys.stderr.write(T(args.lang, "blocked_newer", why=newer.text) + "\n")
                return EXIT["BLOCKED"]
            if not doc:
                if spelled and os.path.isfile(spelled) and any(b.code == "CLAIM_UNPARSEABLE" and named(os.path.join(root, b)) for b in bad):
                    if foreign_format(spelled):  # it may be a newer MAGOS's claim of a live lane: never released by a guard that cannot read it
                        sys.stderr.write(T(args.lang, "blocked_format", f=spelled.replace(os.sep, "/")) + "\n")
                        return EXIT["BLOCKED"]
                    os.remove(spelled)  # the claim file of this branch that nobody can parse blocks every creation: let it go
                    audit(g, op="release", branch=args.branch, reason="unreadable claim file removed", host="cli")
                    out_text(T(args.lang, "released", b=args.branch))
                    return 0
                out_text("no open claim for %s" % args.branch)
                return 0
            owner = claim_set_record(g, doc)
            if owner:  # a claim of a set that has a record (a lane or the integration claim): only set-release retires it
                sys.stderr.write(T(args.lang, "blocked_set", b=doc["branch"], s=owner) + "\n")
                return EXIT["BLOCKED"]
            heads, wts = list_refs(g)[0], worktrees(g)
            b = real_branch(doc, heads)
            unmerged = b is not None and "refs/heads/" + b not in merged_set(g)[0]
            try:
                dirty = any(dirty_paths(g, w["path"]) for w in wts if (b and w["branch"] == b) or (doc["worktree"] and pkey(w["path"]) == pkey(doc["worktree"])))
            except GitFail:
                dirty = True
            if unmerged or dirty:
                sys.stderr.write(T(args.lang, "blocked") + "\n")
                return EXIT["BLOCKED"]
            path = in_store(root, claim_path(g, doc["branch"]))  # only the file of the stored canonical branch name, inside the store
            if path is None or not os.path.isfile(path) or not os.path.samefile(path, doc["file"]):
                sys.stderr.write(T(args.lang, "blocked_alias", b=doc["branch"], f=doc["file"]) + "\n")
                return EXIT["BLOCKED"]
            os.remove(path)
            audit(g, op="release", branch=doc["branch"], reason=args.reason, host="cli")
    except LockTimeout:
        sys.stderr.write(T(args.lang, "lock", s=int(LOCK_S)) + "\n")
        return EXIT["LOCK_TIMEOUT"]
    out_text(T(args.lang, "released", b=doc["branch"]))
    return 0


def foreign_format(path):
    """True for a claim file whose line 1 is `state=active` and whose line 2 starts with `v=` in a spelling the format line does not allow:
    a format this guard cannot read, which may come from a newer MAGOS."""
    try:
        lines = _read_retry(path).replace("\r", "").split("\n")
    except (OSError, ValueError):
        return False
    return lines[0] == "state=active" and len(lines) > 1 and lines[1].startswith("v=") and format_number(lines[1][2:]) is None


def in_store(root, path):
    """The real path of `path` when it lies inside the directory `root` (the claim store), else None."""
    real, top = os.path.realpath(os.path.normpath(os.path.abspath(path))), os.path.realpath(root)
    return real if os.path.normcase(real).startswith(os.path.normcase(top).rstrip(os.sep) + os.sep) else None


def cmd_override(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    if not re.fullmatch(r"[0-9a-f]{12}", args.fingerprint):
        sys.stderr.write("the fingerprint is the 12 hex digits printed with a denial\n")
        return 2
    code, via, rec = user_gate(args, os.path.join(store(g), "approvals"), g.common, retype=args.fingerprint)
    if code:
        return code
    by = "user" if via == "terminal" else "agent"  # a reason typed in a terminal is the user's; one that came through the dialog the agent's
    now = time.time()
    doc = {"fp": args.fingerprint, "reason": args.reason, "by": who(g), "at": now_iso(), "expires": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 3600)),
           "via": via, "reason_by": by}
    os.makedirs(os.path.join(store(g), "override"), exist_ok=True)
    with open(os.path.join(store(g), "override", args.fingerprint + ".json"), "wb") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    audit(g, op="override", fingerprint=args.fingerprint, reason=args.reason, reason_by=by, via=via, host="cli", **approval_fields(rec))
    out_text(T(args.lang, "overridden", fp=args.fingerprint))
    return 0


# ---------------------------------------------------------------- sets (1.0.4): the set record, the integration claim, the spec of set-plan
SET_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")  # the slug: a set name and a lane id (a topic of one to three words)
SLUG_RULE = "[a-z0-9][a-z0-9-]{0,23}"  # the text of SET_NAME that the messages show (a literal brace cannot stand in an entry of M)
_GENERIC_ID = re.compile(r"(?:[0-9]+|[a-z]|(?:l|lane|task|agent|worker|wt|t|n|w|work|part|step|item)-?[0-9]+)")  # matched against the lower-cased id
REQ_ID = re.compile(r"[A-Za-z0-9_-]{1,8}")
_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])")
LANE_STATES = ("planned", "active", "ready", "integrated", "blocked")
SPEC_BYTES, SPEC_LANES, SPEC_SHARED, SPEC_NOTES, SPEC_DEPENDS, SPEC_ERRORS, SPEC_PAIRS = 4194304, 12, 64, 5, 11, 20, 20
SPEC_REQS, SPEC_SERVES, SPEC_SHEET = 12, 12, 8192
CHANGES_SUBJECTS, CHANGES_PATHS, CHANGES_SUBJECT_CHARS = 8, 12, 100  # the bounds of the changes summary of a lane
SPEC_TOP = ("v", "title", "requirements", "base", "sheet", "notes", "shared", "lanes")
SPEC_LANE = ("id", "title", "branch", "worktree", "paths", "depends_on", "serves", "outcome", "acceptance")
SPEC_LANE_OPTIONAL = ("acceptance",)  # every other key of the spec is required
RECORD_KEYS = ("v", "set", "target", "base", "revision", "created", "updated", "by", "title", "requirements", "sheet", "notes", "shared", "integration", "lanes")
RECORD_LANE_KEYS = ("id", "title", "branch", "worktree", "paths", "depends_on", "serves", "outcome", "acceptance", "state", "head", "ready_target", "changes", "note", "updated")
CHANGES_KEYS = ("commits", "subjects", "more", "files", "insertions", "deletions", "paths", "paths_more")
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_SHEET_CTL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # the sheet may hold a newline and a tab
_BASE = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


def set_name_problem(name, lang="en"):
    """-> why `name` is no set name, in `lang` (set_err_set_name, set_err_set_device), or None: [a-z0-9][a-z0-9-]{0,23} and no Windows device name
    (the record is the file sets/<name>.json, and a device name with any extension is a device on Windows)."""
    if not SET_NAME.fullmatch(name):
        return T(lang, "set_err_set_name", s=_shown(name), rule=SLUG_RULE)
    if _DEVICE.fullmatch(name):
        return T(lang, "set_err_set_device", s=_shown(name))
    return None


def integration_branch(set_name):
    return "agent/%s/integration" % set_name


def integration_entry(set_name):
    return ".magos/integration/%s/" % set_name


def claim_extra(doc, key):
    """The values of the extra lines `key=` of a claim, in file order."""
    return [v for k, v in doc.get("extra") or [] if k == key]


def claim_set(doc):
    """The name in the first `set=` line of a claim, or None."""
    vals = claim_extra(doc, "set")
    return vals[0] if vals else None


def is_integration_claim(doc):
    """Has the claim exactly the shape set-plan writes for the integration branch of a set: one `role=integration` line, one `set=<S>` line,
    the branch agent/<S>/integration and the single entry .magos/integration/<S>/ (the last three compared folded)?  Only such a claim is
    exempt from the overlap judgement; any other claim, one that carries role=integration included, is an ordinary claim."""
    sets = claim_extra(doc, "set")
    if claim_extra(doc, "role") != ["integration"] or len(sets) != 1:
        return False
    return fold(doc["branch"]) == fold(integration_branch(sets[0])) and len(doc["entries"]) == 1 and \
        fold(doc["entries"][0]) == fold(integration_entry(sets[0]))


def sets_dir(g):
    return os.path.join(store(g), "sets")


def set_path(g, name):
    return os.path.join(sets_dir(g), name + ".json")


class SetNewer(Exception):
    """A set record of a newer format: never interpreted, overwritten or removed.  .v is the format number (an int, or the digit text of one
    too long for int())."""

    def __init__(self, name, v):
        super().__init__("set %s: format v=%s is newer than this guard's v=%d" % (name, v, SET_FORMAT))
        self.name, self.v = name, v

    @property
    def shown(self):
        text = str(self.v)
        return text if len(text) <= 40 else text[:37] + "..."


class SetUnreadable(Exception):
    """A set record that is no JSON object of a format this guard knows: never overwritten or removed."""

    def __init__(self, name, path, why):
        super().__init__(why)
        self.name, self.path, self.why = name, path, why


class BadSet(str):
    """An unusable file in read_sets' second list: the str is its name below sets/; .code is SET_UNREADABLE or SET_NEWER_FORMAT, .name the
    set and .v the format of a newer record."""

    def __new__(cls, rel, code, name, v=None):
        s = str.__new__(cls, rel)
        s.code, s.name, s.v = code, name, v
        return s


class _Digits(str):
    """The JSON integer of more than 4,000 digits, kept as its text (int() refuses to read more than 4,300 digits from Python 3.11 on)."""


def _json_int(text):
    return int(text) if len(text.lstrip("-")) <= 4000 else _Digits(text)


class _Obj(dict):
    """A parsed JSON object that remembers the keys it repeated."""

    def __init__(self):
        super().__init__()
        self.dups = []


def _loads(text):
    """-> (value, number of repeated keys).  Parses with the hooks of the set formats: a repeated key is counted (the last value stays), NaN,
    the infinities and a number literal beyond the range of a float (1e400) are refused, an integer of more than 4,000 digits stays text
    (_Digits).  Raises ValueError and RecursionError."""
    seen = [0]

    def pairs(items):
        obj = _Obj()
        for k, v in items:
            if k in obj:
                obj.dups.append(k)
                seen[0] += 1
            obj[k] = v
        return obj

    def constant(name):
        raise ValueError("%s is not allowed" % name)

    def number(literal):
        f = float(literal)
        if math.isinf(f):
            raise ValueError("%s is not a finite number" % _shown(literal, 40))
        return f
    return json.loads(text, object_pairs_hook=pairs, parse_int=_json_int, parse_float=number, parse_constant=constant), seen[0]


def _kind(v):
    return "null" if v is None else "a boolean" if isinstance(v, bool) else "a number" if isinstance(v, (int, float, _Digits)) else "a string" if isinstance(v, str) \
        else "a list" if isinstance(v, list) else "an object"


def _is_text(v):
    return isinstance(v, str) and not isinstance(v, _Digits)


def _record_shape(rec, name):
    """-> why a record of format 1 is unusable, or None.  Keys this guard does not know are not looked at."""
    def texts(d, keys, where):
        for k in keys:
            if not _is_text(d.get(k)):
                return "%s%s is not a string" % (where, k)
        return None
    if rec.get("set") != name:
        return "the field set is not the file name"
    why = texts(rec, ("target", "base", "created", "updated", "by", "title", "sheet"), "")
    if not why and not _BASE.fullmatch(rec["base"]):  # the set commands pass it to git as a revision: never one shaped like an option
        why = "base is not a full object name"
    rev = rec.get("revision")
    if why or isinstance(rev, bool) or not isinstance(rev, int) or rev < 1:
        return why or "revision is not a positive integer"
    if not isinstance(rec.get("notes"), list) or not all(_is_text(n) for n in rec["notes"]):
        return "notes is not a list of strings"
    if not isinstance(rec.get("shared"), list) or not all(isinstance(s, dict) and _is_text(s.get("path")) and _is_text(s.get("owner")) for s in rec["shared"]):
        return "shared is not a list of {path, owner}"
    if rec.get("integration") is not None and not _is_text(rec["integration"]):
        return "integration is neither null nor a string"
    if not isinstance(rec.get("requirements"), list) or not all(isinstance(r, dict) and _is_text(r.get("id")) and _is_text(r.get("text")) for r in rec["requirements"]):
        return "requirements is not a list of {id, text}"
    if not isinstance(rec.get("lanes"), list):
        return "lanes is not a list"
    for i, ln in enumerate(rec["lanes"]):
        where = "lanes[%d]." % i
        if not isinstance(ln, dict):
            return "lanes[%d] is not an object" % i
        why = texts(ln, ("id", "title", "branch", "worktree", "outcome", "acceptance", "note", "updated"), where)
        if why:
            return why
        if not all(isinstance(ln.get(k), list) and all(_is_text(x) for x in ln[k]) for k in ("paths", "depends_on", "serves")):
            return "%spaths, depends_on and serves are not lists of strings" % where
        if ln.get("state") not in LANE_STATES or (ln.get("head") is not None and not (_is_text(ln["head"]) and _BASE.fullmatch(ln["head"]))):
            return "%sstate or head is not valid" % where
        if ln.get("ready_target") is not None and not (_is_text(ln["ready_target"]) and _BASE.fullmatch(ln["ready_target"])):
            return "%sready_target is neither null nor a full object name" % where
        if ln.get("changes") is not None and not _changes_shape(ln["changes"]):
            return "%schanges is neither null nor a summary of changes" % where
    return None


def _changes_shape(ch):
    """Is `ch` the summary of the changes of a lane (CHANGES_KEYS: six counts and two lists of strings; a key this guard does not know is allowed)?"""
    return isinstance(ch, dict) and all(isinstance(ch.get(k), int) and not isinstance(ch.get(k), bool) for k in ("commits", "more", "files", "insertions", "deletions", "paths_more")) \
        and all(isinstance(ch.get(k), list) and all(_is_text(x) for x in ch[k]) for k in ("subjects", "paths"))


def parse_set(name, path, text):
    """The record of set `name` from its text.  The format gate comes first: a record of a newer format raises SetNewer before any other field
    is read, whatever its shape; every other unusable record raises SetUnreadable."""
    try:
        rec, _ = _loads(text)
    except (ValueError, RecursionError, MemoryError) as err:
        raise SetUnreadable(name, path, "not valid JSON: %s" % str(err)[:120])
    if not isinstance(rec, dict):
        raise SetUnreadable(name, path, "the record is not a JSON object")
    v = rec.get("v")
    if isinstance(v, _Digits):
        if v.startswith("-"):
            raise SetUnreadable(name, path, "the format v is below 1")
        raise SetNewer(name, v)
    if isinstance(v, bool) or not isinstance(v, int):
        raise SetUnreadable(name, path, "the record has no integer format v")
    if v > SET_FORMAT:
        raise SetNewer(name, v)
    if v < 1:
        raise SetUnreadable(name, path, "the format v is below 1")
    todo = [rec]  # the parser keeps a number of more than 4,000 digits as text: a write would quote it; a lone surrogate has no UTF-8 form
    while todo:
        x = todo.pop()
        if isinstance(x, _Digits):
            raise SetUnreadable(name, path, "a number of more than 4,000 digits")
        if isinstance(x, str) and _SURROGATE.search(x):
            raise SetUnreadable(name, path, "holds a lone surrogate")
        todo.extend(list(x) + list(x.values()) if isinstance(x, dict) else x if isinstance(x, list) else ())
    why = _record_shape(rec, name)
    if why:
        raise SetUnreadable(name, path, why)
    return rec


def read_set(g, name):
    """-> the record of set `name`, or None when there is none.  Raises SetNewer and SetUnreadable (see parse_set)."""
    path = set_path(g, name)
    if not os.path.lexists(path):
        return None
    try:
        text = _read_retry(path)
    except (OSError, ValueError) as err:
        raise SetUnreadable(name, path, str(err)[:120])
    return parse_set(name, path, text)


def read_sets(g):
    """-> ({set name: record}, [BadSet]): every `*.json` file of sets/; an unusable one is listed with its code.  Once per repository within a
    hook call."""
    return _memo(("sets", g.common), lambda: _read_sets(g))


def _read_sets(g):
    recs, bad = {}, []
    try:
        names = sorted(os.listdir(sets_dir(g)))
    except OSError:
        return recs, bad
    for f in names:
        if not f.endswith(".json"):  # a temporary file (*.tmp) is never a record
            continue
        try:
            rec = read_set(g, f[:-5])
        except SetNewer as err:
            bad.append(BadSet(f, "SET_NEWER_FORMAT", f[:-5], err.v))
        except SetUnreadable:
            bad.append(BadSet(f, "SET_UNREADABLE", f[:-5]))
        else:
            if rec is not None:
                recs[f[:-5]] = rec
    return recs, bad


def claim_set_record(g, doc):
    """The name of the set the claim `doc` belongs to while that set has a record (a file sets/<set>.json, whatever its state), else None.  The
    name is validated before it is used as a path."""
    name = claim_set(doc)
    return name if name and set_name_problem(name) is None and os.path.lexists(set_path(g, name)) else None


def branch_set(g, name, doc):
    """The set whose branch `name` is, for the set gate of plan: the set of its claim `doc` while that set has a record (claim_set_record), else
    the set whose record names `name` (folded) as the branch of a lane or as its integration branch, whatever `doc` says (missing, without a
    set= line or naming a set without a record); of a record this guard cannot read only the integration branch is known.  None otherwise."""
    owner = claim_set_record(g, doc) if doc else None
    if owner:
        return owner
    recs, bad = read_sets(g)
    f = fold(name)
    for s, rec in sorted(recs.items()):
        if f in {fold(ln["branch"]) for ln in rec["lanes"]} | {fold(integration_branch(s))}:
            return s
    return next((b.name for b in bad if set_name_problem(b.name) is None and fold(integration_branch(b.name)) == f), None)


def _ordered(d, order):
    """`d` with the keys of `order` first, in that order, then every other key in its own order."""
    out = {k: d[k] for k in order if k in d}
    out.update({k: v for k, v in d.items() if k not in out})
    return out


class _Errors(list):
    """The errors of a spec, each (field, code, text)."""

    def add(self, field, code, text):
        self.append((field, code, text))


def _field(path, key):
    """The field path of the key `key` of the object at `path` (a key that is no plain word is shown in its repr)."""
    return "%s.%s" % (path, key) if path and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key) else key if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key) else \
        "%s[%s]" % (path, ascii(key)[:60])


def _keys(errs, obj, path, allowed, optional=()):
    """Duplicate, unknown and missing keys of the spec object `obj` at `path`; every key of `allowed` is required except those of `optional`."""
    for k in obj.dups:
        errs.add(_field(path, k), "DUPLICATE", "the key appears more than once")
    for k in obj:
        if k not in allowed:
            errs.add(_field(path, k), "UNKNOWN_KEY", "not a key of the spec")
    for k in allowed:
        if k not in obj and k not in optional:
            errs.add(_field(path, k), "MISSING", "required")


def _text(errs, field, v, lo, hi, multiline=False):
    """The string `v` when it holds lo to hi characters without a lone surrogate or a control character (the sheet may hold a newline and a
    tab), else None with the error recorded."""
    if not _is_text(v):
        errs.add(field, "TYPE", "must be a string, not %s" % _kind(v))
    elif not lo <= len(v) <= hi:
        errs.add(field, "RANGE", "must hold %d to %d characters, not %d" % (lo, hi, len(v)))
    elif _SURROGATE.search(v):
        errs.add(field, "ENCODING", "holds a lone surrogate")
    elif (_SHEET_CTL if multiline else _CTL).search(v):
        errs.add(field, "FORMAT", "holds a control character")
    else:
        return v
    return None


def lane_worktree(p):
    """-> (the stored spelling of an absolute worktree path, None) or (None, reason).  Classified here and never with os.path.isabs, whose
    Windows result for a rooted path without a drive differs from Python 3.13 on: a drive path (C:/x, C:\\x) or a UNC path on Windows, a
    path with a leading / elsewhere.  Git Bash drive spellings (/c/x) map to drive paths on Windows.  The spelling is os.path.normpath with
    / as the separator, as plan --worktree stores it; on POSIX the leading run of slashes is one (normpath keeps exactly two, which the
    kernel reads as one), and a Win32 namespace path (\\\\?\\, \\\\.\\), which pkey never folds to the drive it names, is refused; so are, on
    Windows, the spellings of the normpath form that Win32 path resolution reads as another directory than the one pkey compares: a segment
    that ends in '.' or a space, which it can drop (C:/x/repo./wt names C:/x/repo/wt), ~ followed by a digit, the form of an 8.3 short name
    (C:/x/REPOSI~1/wt can name C:/x/repository/wt), and a ':' after the drive, NTFS stream syntax (C:/x/repo::$INDEX_ALLOCATION/wt names
    C:/x/repo/wt)."""
    if len(p) > MAX_DIR:
        return None, "longer than %d characters" % MAX_DIR
    if _CTL.search(p):
        return None, "holds a control character"
    if p.startswith("~"):
        return None, "starts with ~: write the absolute path"
    q = _norm_path(p)
    if os.name == "nt":
        if re.match(r"[\\/]{2}[?.][\\/]", q):
            return None, "is a Win32 namespace path (\\\\?\\ or \\\\.\\), which is not a worktree path"
        absolute = re.match(r"[A-Za-z]:[\\/]", q) or re.match(r"[\\/]{2}[^\\/]", q)
    else:
        absolute = q.startswith("/") and "\\" not in q
        q = "/" + q.lstrip("/") if absolute else q
    if not absolute:
        return None, "is not an absolute path"
    if ".." in re.split(r"[\\/]" if os.name == "nt" else "/", q):
        return None, "holds a '..' segment"
    stored = os.path.normpath(q).replace("\\", "/")
    if os.name == "nt":
        if any(seg.endswith((".", " ")) for seg in stored.split("/")):
            return None, "holds a segment that ends in '.' or a space, which Windows can drop when it resolves the path"
        if re.search(r"~\d", stored):
            return None, "holds ~ followed by a digit, the form of an 8.3 short name, which Windows can resolve to the long name of another directory"
        if ":" in stored[2 if stored[1:2] == ":" else 0:]:
            return None, "holds a ':' after the drive, which NTFS reads as a stream (<dir>::$INDEX_ALLOCATION names <dir>)"
    return stored, None


def inside_path(path, root):
    """Is `path` the directory `root` or below it (pkey form: case and separators fold where the platform folds them)?"""
    p, r = pkey(path), pkey(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def merge_order(ids, deps):
    """The topological order of the lane ids: at every step the first lane of `ids` whose dependencies are all placed comes next, so it is
    deterministic.  A lane on or behind a cycle is left out."""
    placed, order = set(), []
    while len(order) < len(ids):
        nxt = next((i for i in ids if i not in placed and all(d in placed for d in deps.get(i, ()))), None)
        if nxt is None:
            break
        placed.add(nxt)
        order.append(nxt)
    return order


def _cycles(ids, deps):
    """The groups of lane ids that depend on each other in a cycle, each in `ids` order."""
    def reach(start):
        seen, todo = set(), list(deps.get(start, ()))
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo.extend(deps.get(x, ()))
        return seen
    reached, groups, covered = {i: reach(i) for i in ids}, [], set()
    for i in ids:
        if i in reached[i] and i not in covered:
            group = [j for j in ids if j in reached[i] and i in reached[j]]
            covered.update(group)
            groups.append(group)
    return groups


def _shown(text, limit=80):
    """A value of the spec as a message shows it: control characters as spaces, a lone surrogate as U+FFFD, cut to `limit` characters."""
    text = _SURROGATE.sub("\ufffd", _CTL.sub(" ", text))
    return text if len(text) <= limit else text[:limit - 1] + "…"


def slug_hint(lane_id):
    """The slug that lower-casing `lane_id` and replacing every _ by - gives, when it is a topic slug that is neither generic nor reserved, else None."""
    s = lane_id.lower().replace("_", "-")
    return s if SET_NAME.fullmatch(s) and not _GENERIC_ID.fullmatch(s) and s != "integration" and not _DEVICE.fullmatch(s) else None


def lane_id_problem(lang, value):
    """-> (code, text) for a lane id that is no topic slug, or None.  The tests run in this order and the first that fails gives the one error: generic
    (the lower-cased id is only digits, one letter or an ordinal such as l1, lane-2, task3), reserved (integration, a Windows device name), form (the
    id as written is not [a-z0-9][a-z0-9-]{0,23})."""
    low = value.lower()
    if _GENERIC_ID.fullmatch(low):
        return "GENERIC_ID", T(lang, "set_err_generic_id", id=_shown(value))
    if low == "integration" or _DEVICE.fullmatch(low):
        return "RESERVED", T(lang, "set_err_reserved_id", id=_shown(value))
    if not SET_NAME.fullmatch(value):
        slug = slug_hint(value)
        return "FORMAT", T(lang, "set_err_id_form", id=_shown(value), rule=SLUG_RULE, hint=" " + T(lang, "set_hint_slug", slug=slug) if slug else "")
    return None


def _dir_name(norm):
    """The directory name of a stored worktree path: its last component without a trailing separator ('' for the root of a drive)."""
    p = norm.rstrip("/")
    return "" if not p or re.fullmatch(r"[A-Za-z]:", p) else p.rsplit("/", 1)[-1]


class _Spec:
    """What the checks of one spec share: the language of the messages, the set and the target, the lane ids met so far, the requirement ids of the spec
    (None while they cannot be judged) and, on demand, the default worktree path of a lane."""

    def __init__(self, g, lang, set_name, target):
        self.g, self.lang, self.set, self.target = g, lang, set_name, target
        self.lanes, self.reqs, self._main = {}, None, None

    def default_worktree(self, lid):
        """<parent of the main worktree>/<repo dir name>-<set>-<id> with / separators (the main worktree is the first entry of git worktree list), an
        absolute path: below a root the parent is that root (/repo gives /repo-<set>-<id>); a main worktree at a root (of the filesystem, of a
        drive or, on Windows, of a UNC share) has no name and gives repo-<set>-<id> on that root (C:/ gives C:/repo-<set>-<id>, //server/share
        gives //server/share/repo-<set>-<id>, never the sibling share //server/share-<set>-<id>), which lies inside it."""
        if self._main is None:
            wts = worktrees(self.g)
            self._main = wts[0]["path"].replace("\\", "/").rstrip("/") if wts else ""
        parent, sep, name = self._main.rpartition("/")
        if not sep or not os.path.splitdrive(self._main)[1]:  # the root of a drive (C:), of a UNC share (//server/share) or of the filesystem (empty)
            parent, name = self._main, ""
        return "%s/%s-%s-%s" % (parent, name or "repo", self.set, lid)

    def worktree_name_error(self, lid, norm):
        """The error of the directory name of the lane `lid` at the stored path `norm`: it must end with -<set>-<id> after a non-empty prefix (WORKTREE_FORM,
        compared exactly, case included), and what stands before its first dot must be no Windows device name (WORKTREE); None when it holds."""
        name, suffix = _dir_name(norm), "-%s-%s" % (self.set, lid)
        if not name.endswith(suffix) or len(name) <= len(suffix):
            return "WORKTREE_FORM", T(self.lang, "set_err_worktree_form", l=lid, s=self.set, got=_shown(name), want=self.default_worktree(lid))
        first = name.split(".", 1)[0]
        if _DEVICE.fullmatch(fold(first)):
            return "WORKTREE", T(self.lang, "set_err_worktree_device", l=lid, got=_shown(name), dev=_shown(first), want=self.default_worktree(lid))
        return None


def _check_requirements(ctx, errs, spec):
    """The `requirements` of the spec -> (the valid {id, text} items in order, the rows (index, id, text) of the items the coverage judges, the number of
    repeated keys the items reported).  Sets ctx.reqs to {id: index} of the valid unique ids (None when there is none)."""
    reqs, rows, reported = [], [], 0
    if "requirements" not in spec:
        return reqs, rows, reported
    raw = spec["requirements"]
    if not isinstance(raw, list):
        errs.add("requirements", "TYPE", "must be a list, not %s" % _kind(raw))
        return reqs, rows, reported
    if not raw:
        errs.add("requirements", "RANGE", "a plan has 1 to %d requirements, not 0" % SPEC_REQS)
    elif len(raw) > SPEC_REQS:
        errs.add("requirements[%d]" % SPEC_REQS, "RANGE", "at most %d requirements, not %d" % (SPEC_REQS, len(raw)))
    seen, known = {}, {}
    for i, item in enumerate(raw[:SPEC_REQS]):
        where = "requirements[%d]" % i
        if not isinstance(item, dict):
            errs.add(where, "TYPE", "must be an object, not %s" % _kind(item))
            continue
        reported += len(item.dups)
        _keys(errs, item, where, ("id", "text"))
        rid = text = None
        if "id" in item:
            v = item["id"]
            if not _is_text(v):
                errs.add(where + ".id", "TYPE", "must be a string, not %s" % _kind(v))
            elif _SURROGATE.search(v):
                errs.add(where + ".id", "ENCODING", "holds a lone surrogate")
            elif not REQ_ID.fullmatch(v):
                errs.add(where + ".id", "FORMAT", "a requirement id is [A-Za-z0-9_-] of 1 to 8 characters, not %s" % _shown(v, 40))
            elif v.lower() in seen:
                errs.add(where + ".id", "DUPLICATE", "the id equals the id of requirements[%d] ignoring case" % seen[v.lower()])
            else:
                seen[v.lower()] = i
                known[v] = i
                rid = v
        if "text" in item:
            text = _text(errs, where + ".text", item["text"], 1, 200)
        if rid is not None and text is not None:
            reqs.append({"id": rid, "text": text})
            rows.append((i, rid, text))
    ctx.reqs = known or None
    return reqs, rows, reported


def _check_lane(ctx, errs, i, ln):
    """One lane of the spec at lanes[i] -> its model (the keys whose value is invalid are None; `raw_id` is the id as written when it is a string), the
    errors recorded in the order of the schema: id, title, branch, worktree, paths, depends_on, serves, outcome, acceptance."""
    path, lang = "lanes[%d]" % i, ctx.lang
    if not isinstance(ln, dict):
        errs.add(path, "TYPE", "must be an object, not %s" % _kind(ln))
        return None
    _keys(errs, ln, path, SPEC_LANE, SPEC_LANE_OPTIONAL)
    m = {"id": None, "raw_id": None, "title": None, "branch": None, "worktree": None, "paths": None, "entries": [], "depends_on": None, "serves": None,
         "outcome": None, "acceptance": ""}
    if "id" in ln:
        v = ln["id"]
        if not _is_text(v):
            errs.add(path + ".id", "TYPE", "must be a string, not %s" % _kind(v))
        elif _SURROGATE.search(v):
            errs.add(path + ".id", "ENCODING", "holds a lone surrogate")
        else:
            m["raw_id"] = v
            problem = lane_id_problem(lang, v)
            if problem:
                errs.add(path + ".id", *problem)
            elif v in ctx.lanes:  # a repeated id is an invalid id of this lane: its one error, and no rule derived from the id
                errs.add(path + ".id", "DUPLICATE", "the id equals the id of lanes[%d]" % ctx.lanes[v])
            else:
                ctx.lanes[v] = i
                m["id"] = v
    lid = m["id"]
    lname = lid or (_shown(m["raw_id"], 40) if m["raw_id"] is not None else "#%d" % i)
    if "title" in ln:
        m["title"] = _text(errs, path + ".title", ln["title"], 1, 80)
    if "branch" in ln:
        b = ln["branch"]
        if not _is_text(b):
            errs.add(path + ".branch", "TYPE", "must be a string, not %s" % _kind(b))
        elif _SURROGATE.search(b):
            errs.add(path + ".branch", "ENCODING", "holds a lone surrogate")
        elif lid is not None:  # a lane whose id is invalid has no branch rule: its one error is the id's
            want = "agent/%s/%s" % (ctx.set, lid)
            if b != want:
                errs.add(path + ".branch", "BRANCH_FORM", T(lang, "set_err_branch_form", l=lid, want=want, got=_shown(b)))
            elif fold(b) == fold(ctx.target):
                errs.add(path + ".branch", "BRANCH_NAME", "is the same branch as the target (case and Unicode normalisation ignored)")
            else:
                m["branch"] = b
    if "worktree" in ln:
        w = ln["worktree"]
        if not _is_text(w):
            errs.add(path + ".worktree", "TYPE", "must be a string, not %s" % _kind(w))
        elif _SURROGATE.search(w):
            errs.add(path + ".worktree", "ENCODING", "holds a lone surrogate")
        else:
            norm, reason = lane_worktree(w)
            if reason:
                errs.add(path + ".worktree", "WORKTREE", reason)
            else:
                m["worktree"] = norm
                problem = ctx.worktree_name_error(lid, norm) if lid is not None else None
                if problem:
                    errs.add(path + ".worktree", *problem)
    if "paths" in ln:
        raw = ln["paths"]
        if not isinstance(raw, list):
            errs.add(path + ".paths", "TYPE", "must be a list, not %s" % _kind(raw))
        elif not raw:
            errs.add(path + ".paths", "EMPTY", "a lane owns at least one manifest entry")
        else:
            if len(raw) > MAX_ENTRIES:
                errs.add(path + ".paths", "TOO_MANY", "more than %d entries" % MAX_ENTRIES)
            seen, m["paths"] = {}, []  # the normalised alternatives of each valid entry -> the index of its first spelling
            for j, p in enumerate(raw[:MAX_ENTRIES]):
                where = "%s.paths[%d]" % (path, j)
                if not _is_text(p):
                    errs.add(where, "TYPE", "must be a string, not %s" % _kind(p))
                elif _SURROGATE.search(p):
                    errs.add(where, "ENCODING", "holds a lone surrogate")
                elif _CTL.search(p):
                    errs.add(where, "EMPTY", "empty entry or control character")
                else:
                    try:
                        e = parse_entry(p)
                    except ManifestError as err:
                        errs.add(where, err.code, str(err))
                        continue
                    if e.alts in seen:  # equal after normalisation: every later spelling is refused on its own field
                        errs.add(where, "DUPLICATE", "the entry equals %s.paths[%d] after normalisation" % (path, seen[e.alts]))
                        continue
                    seen[e.alts] = j
                    m["entries"].append(e)
                    m["paths"].append(e.raw)
    if "depends_on" in ln:
        if not isinstance(ln["depends_on"], list):
            errs.add(path + ".depends_on", "TYPE", "must be a list, not %s" % _kind(ln["depends_on"]))
        else:
            if len(ln["depends_on"]) > SPEC_DEPENDS:
                errs.add(path + ".depends_on", "RANGE", "at most %d ids" % SPEC_DEPENDS)
            m["depends_on"] = list(ln["depends_on"][:SPEC_DEPENDS])
    if "serves" in ln:
        raw = ln["serves"]
        if not isinstance(raw, list):
            errs.add(path + ".serves", "TYPE", "must be a list, not %s" % _kind(raw))
        else:
            if not 1 <= len(raw) <= SPEC_SERVES:
                errs.add(path + ".serves", "RANGE", T(lang, "set_err_serves_count", l=lname, n=len(raw)))
            seen, m["serves"] = set(), []
            for j, r in enumerate(raw[:SPEC_SERVES]):
                where = "%s.serves[%d]" % (path, j)
                if _is_text(r) and _SURROGATE.search(r):
                    errs.add(where, "ENCODING", "holds a lone surrogate")
                elif ctx.reqs is not None and (not _is_text(r) or r not in ctx.reqs):
                    errs.add(where, "UNKNOWN_REQUIREMENT", T(lang, "set_err_serves_unknown", r=_shown(r if _is_text(r) else ascii(r), 40), ids=", ".join(ctx.reqs)))
                elif _is_text(r) and r in seen:
                    errs.add(where, "DUPLICATE", "%s is listed twice" % r)
                elif _is_text(r):
                    seen.add(r)
                    m["serves"].append(r)
    if "outcome" in ln:
        m["outcome"] = _text(errs, path + ".outcome", ln["outcome"], 1, 300)
    if "acceptance" in ln:
        a = _text(errs, path + ".acceptance", ln["acceptance"], 0, 300)
        m["acceptance"] = "" if a is None else a
    return m


def check_spec(g, spec, dupes, set_name, target, spec_path, lang="en"):
    """Validate a parsed spec: every field, then the rules across fields, all errors collected (the naming and coverage texts are in `lang`).  -> (errors,
    model); the model is None when there is an error.  Reads no claim, record or ref: only the worktree list (for the default worktree path of a message)
    and `git check-ref-format` run.  `spec_path`: the spec file (None for stdin), which must not lie inside a lane worktree."""
    errs = _Errors()
    if not isinstance(spec, dict):
        errs.add("spec", "TYPE", "the spec must be a JSON object, not %s" % _kind(spec))
        return errs, None
    _keys(errs, spec, "", SPEC_TOP)
    reported = len(spec.dups)
    ctx = _Spec(g, lang, set_name, target)
    if "v" in spec:
        v = spec["v"]
        if isinstance(v, bool) or isinstance(v, float) or (_is_text(v)) or v is None or isinstance(v, (list, dict)):
            errs.add("v", "TYPE", "must be the integer 1, not %s" % _kind(v))
        elif v != 1 or isinstance(v, _Digits):
            errs.add("v", "UNSUPPORTED_VERSION", "this guard reads spec version 1 only")
    title = _text(errs, "title", spec["title"], 1, 120) if "title" in spec else None
    requirements, req_rows, more = _check_requirements(ctx, errs, spec)
    reported += more
    base = None
    if "base" in spec:
        if not _is_text(spec["base"]):
            errs.add("base", "TYPE", "must be a string, not %s" % _kind(spec["base"]))
        elif not _BASE.fullmatch(spec["base"]):
            errs.add("base", "FORMAT", "must be the full object name of the target tip (40 or 64 hexadecimal digits)")
        else:
            base = spec["base"].lower()
    sheet = _text(errs, "sheet", spec["sheet"], 1, SPEC_SHEET, True) if "sheet" in spec else None
    notes = []
    if "notes" in spec:
        if not isinstance(spec["notes"], list):
            errs.add("notes", "TYPE", "must be a list, not %s" % _kind(spec["notes"]))
        else:
            if len(spec["notes"]) > SPEC_NOTES:
                errs.add("notes[%d]" % SPEC_NOTES, "RANGE", "at most %d notes" % SPEC_NOTES)
            for j, n in enumerate(spec["notes"][:SPEC_NOTES]):
                note = _text(errs, "notes[%d]" % j, n, 1, 200)
                if note is not None:
                    notes.append(note)
    lanes_raw, lanes = spec.get("lanes"), []
    if "lanes" in spec:
        if not isinstance(lanes_raw, list):
            errs.add("lanes", "TYPE", "must be a list, not %s" % _kind(lanes_raw))
        else:
            if not 1 <= len(lanes_raw) <= SPEC_LANES:
                errs.add("lanes", "RANGE", "a set has 1 to %d lanes, not %d" % (SPEC_LANES, len(lanes_raw)))
            for i, ln in enumerate(lanes_raw[:SPEC_LANES]):
                m = _check_lane(ctx, errs, i, ln)
                if isinstance(ln, dict):
                    reported += len(ln.dups)
                lanes.append(m)
    ids = dict(ctx.lanes)  # the lane ids that passed the id rules, each with the index of its first lane
    bad_ids = {m["raw_id"] for m in lanes if m and m["raw_id"] is not None and m["id"] is None}  # reported once, at the lane: no second error names them
    deps = {}
    for i, m in enumerate(lanes):  # depends_on: existing ids (spelled as the lane's id), no duplicate, no self, no cycle
        if not m or m["depends_on"] is None:
            continue
        seen = set()
        for j, d in enumerate(m["depends_on"]):
            where = "lanes[%d].depends_on[%d]" % (i, j)
            if not _is_text(d) or d not in ids:
                if not (_is_text(d) and d in bad_ids):
                    errs.add(where, "UNKNOWN_LANE", "%s is no lane id of the spec (ids are matched exactly)" % (ascii(d)[:40]))
            elif d in seen:
                errs.add(where, "DUPLICATE", "%s is listed twice" % d)
            elif d == m["id"]:
                errs.add(where, "CYCLE", "lane %s depends on itself" % d)
            else:
                seen.add(d)
        if m["id"] is not None:
            deps[m["id"]] = [d for d in m["depends_on"] if _is_text(d) and d in seen]
    order_ids = [m["id"] for m in lanes if m and m["id"] is not None]
    order = merge_order(order_ids, deps)
    if len(order) < len(order_ids):
        for group in _cycles(order_ids, deps):
            errs.add("lanes[%d].depends_on" % ids[group[0]], "CYCLE", "lanes %s depend on each other in a cycle" % ", ".join(group))
    shared, shared_seen = [], set()
    if "shared" in spec:
        if not isinstance(spec["shared"], list):
            errs.add("shared", "TYPE", "must be a list, not %s" % _kind(spec["shared"]))
        else:
            if len(spec["shared"]) > SPEC_SHARED:
                errs.add("shared", "RANGE", "at most %d shared paths" % SPEC_SHARED)
            for j, s in enumerate(spec["shared"][:SPEC_SHARED]):
                where = "shared[%d]" % j
                if not isinstance(s, dict):
                    errs.add(where, "TYPE", "must be an object, not %s" % _kind(s))
                    continue
                reported += len(s.dups)
                _keys(errs, s, where, ("path", "owner"))
                owner, entry = s.get("owner"), None
                if "path" in s:
                    p = _text(errs, where + ".path", s["path"], 1, 1024)
                    if p is not None:
                        try:
                            entry = parse_entry(p)
                        except ManifestError as err:
                            errs.add(where + ".path", err.code, str(err))
                        else:
                            if re.search(r"[*?]", p) or p.strip().replace("\\", "/").endswith("/"):
                                errs.add(where + ".path", "BAD_GLOB", "a shared path names one file: no * or ? and no trailing /")
                                entry = None
                            elif entry.alts[0][:-1] in shared_seen:
                                errs.add(where + ".path", "DUPLICATE", "the path is listed twice (after folding)")
                                entry = None
                            else:
                                shared_seen.add(entry.alts[0][:-1])
                if "owner" in s:
                    if not _is_text(owner) or owner not in ids:
                        if not (_is_text(owner) and owner in bad_ids):
                            errs.add(where + ".owner", "UNKNOWN_LANE", "%s is no lane id of the spec (ids are matched exactly)" % ascii(owner)[:40])
                    elif entry is not None:
                        manifest = lanes[ids[owner]]["entries"]
                        fp = entry.alts[0][:-1]  # the literal file: containment is the exact intersection, never the literal-directory rule
                        if not any(segs_overlap(alt, fp) for e in manifest for alt in e.alts):
                            errs.add(where + ".path", "NOT_IN_OWNER", "the path lies outside the manifest of its owner %s" % owner)
                if entry is not None and _is_text(owner):
                    shared.append({"path": entry.raw, "owner": owner})
    served = set()  # the requirements and the lanes cover each other: every requirement is served by a lane (every lane serves an existing one: its serves)
    for m in lanes:
        if m and m["serves"]:
            served.update(m["serves"])
    for i, rid, text in req_rows:
        if rid not in served:
            errs.add("requirements[%d]" % i, "UNSERVED", T(lang, "set_err_unserved", r=rid, t=text[:60]))
    for i, m in enumerate(lanes):  # worktrees: distinct, none inside another (a lane whose id is invalid has its one id error)
        if not m or m["worktree"] is None or m["id"] is None:
            continue
        for o in lanes[:i]:
            if o and o["worktree"] is not None and o["id"] is not None:
                if inside_path(m["worktree"], o["worktree"]) or inside_path(o["worktree"], m["worktree"]):
                    errs.add("lanes[%d].worktree" % i, "WORKTREE", "equals or lies inside the worktree of lane %s, or contains it" % o["id"])
    if spec_path and any(m and m["worktree"] is not None and inside_path(spec_path, m["worktree"]) for m in lanes):
        errs.add("--spec", "SPEC_IN_WORKTREE", "the spec file lies inside a lane worktree: write it elsewhere, or pass - and send it on stdin")
    if dupes > reported and not errs:
        errs.add("spec", "DUPLICATE", "a key appears more than once")
    if errs:
        return errs, None
    return errs, {"title": title, "requirements": requirements, "base": base, "sheet": sheet, "notes": notes, "shared": shared, "order": order, "lanes": lanes}


def read_spec(g, arg):
    """-> (the decoded spec text, the spec file's absolute path or None, errors).  The file must lie outside every worktree; it is read up to
    4,194,305 bytes, and `-` reads stdin."""
    errs, path = _Errors(), None
    try:
        if arg == "-":
            raw = sys.stdin.buffer.read(SPEC_BYTES + 1)
        else:
            path = os.path.abspath(arg)
            if any(inside_path(path, w["path"]) for w in worktrees(g)):
                errs.add("--spec", "SPEC_IN_WORKTREE", "the spec file lies inside a worktree (it would dirty it): write it elsewhere, or pass - and send it on stdin")
                return None, path, errs
            with open(path, "rb") as fh:
                raw = fh.read(SPEC_BYTES + 1)
    except (OSError, ValueError) as err:
        errs.add("--spec", "MISSING", "cannot read the spec: %s" % str(err)[:120])
        return None, path, errs
    if len(raw) > SPEC_BYTES:
        errs.add("spec", "TOO_LARGE", "the spec is larger than %d bytes" % SPEC_BYTES)
        return None, path, errs
    try:
        return decode_manifest(raw), path, errs
    except ManifestError:
        errs.add("spec", "ENCODING", "the spec is not UTF-8, or UTF-16 with a byte order mark")
        return None, path, errs


def parse_spec(text):
    """-> (value, number of repeated keys, errors): the JSON of a spec with the hooks of _loads."""
    errs = _Errors()
    try:
        value, dupes = _loads(text)
    except RecursionError:
        errs.add("spec", "JSON", "the JSON nests deeper than a parser can read")
    except (ValueError, MemoryError) as err:
        errs.add("spec", "JSON", "not valid JSON: %s" % str(err)[:160])
    else:
        return value, dupes, errs
    return None, 0, errs

# ---------------------------------------------------------------- set-plan
def set_emit(args, v):
    """Print the one result of a set command (the message, or with --json one object) and return its exit code, which `code` (an EXIT name) names."""
    v["exit_code"] = EXIT[v["code"]]
    out_text(json.dumps(v, ensure_ascii=False) if args.json else v["message"])
    return v["exit_code"]


def set_deny(lang, code, message, **extra):
    """A denial: decision, code, the keys of its exit, then the message (set_emit adds the exit code)."""
    v = {"decision": "deny", "code": code}
    v.update(extra)
    v["message"] = message
    return v


def error_lines(errors):
    """The `[CODE] field: text` lines of a list of (field, code, text): at most SPEC_ERRORS, then `... and N more`."""
    lines = ["  [%s] %s: %s" % (code, field, text) for field, code, text in errors[:SPEC_ERRORS]]
    return lines + (["  ... and %d more" % (len(errors) - SPEC_ERRORS)] if len(errors) > SPEC_ERRORS else [])


def invalid_set(lang, errors, code="INVALID_SPEC", frame="set_invalid"):
    """The denial of exit 24 (a spec or option value that is invalid in itself) or 12 (a name or worktree that clashes with the repository).  `frame`
    names what was refused: `set_invalid` (the set plan) for set-plan, `set_invalid_args` (invalid arguments) for set-show, set-update and set-release."""
    return set_deny(lang, code, T(lang, frame, errors="\n".join(error_lines(errors))),
                    errors=[{"field": f, "code": c, "text": t} for f, c, t in errors[:SPEC_ERRORS]])


def invalid_args(lang, errors):
    """The exit 24 of set-show, set-update and set-release, in the neutral frame `set_invalid_args`, which speaks of no plan."""
    return invalid_set(lang, errors, frame="set_invalid_args")


def unknown_set(lang, code, text):
    """The denial of exit 11 for an unknown of the call itself (TARGET_UNCERTAIN, SET_UNREADABLE, BUDGET_EXCEEDED, ...)."""
    return set_deny(lang, "UNKNOWN", "[%s] %s" % (code, text), unknowns=[{"code": code, "text": text}])


def record_denial(lang, name, err):
    """The denial for a record that cannot be used: exit 23 (SetNewer) or exit 11 (SetUnreadable)."""
    if isinstance(err, SetNewer):
        return set_deny(lang, "SET_NEWER_FORMAT", T(lang, "set_newer", s=name, v=err.shown))
    path = err.path.replace(os.sep, "/")
    return set_deny(lang, "UNKNOWN", T(lang, "set_unreadable", f=path), unknowns=[{"code": "SET_UNREADABLE", "text": "%s: %s" % (path, err.why)}])


def literal_prefix(alt):
    """The folded leading segments of an alternative up to the first one that holds * or ? or is ** (empty when it starts with one)."""
    return alt[:next((k for k, g in enumerate(alt) if g == GS or _WILD.search(g)), len(alt))]


def lane_overlaps(lanes, deadline):
    """The pairs of manifest entries of two lanes that can match a common path -> (the first SPEC_PAIRS as (lane id, entry, lane id, entry), the
    number of pairs).  A path matches an alternative only when its leading segments are the alternative's literal prefix, so two alternatives
    can match a common path only when the prefix of one is a prefix of the other's.  The entries are indexed by the prefix of each alternative
    (`at`) and by every prefix of that prefix (`under`), and an entry is compared (entries_overlap, the exact glob intersection) only with the
    entries of the later lanes whose prefix is a prefix of one of its own (`at`) or has one of its own as a prefix (`under`): an entry with an
    empty prefix meets every entry, and lanes that own distinct directories, also below one top directory, cost near-linear work.  Raises
    GitFail BUDGET_EXCEEDED when `deadline` passes: the proof is never partial."""
    def tick():
        if time.monotonic() > deadline:
            raise GitFail("BUDGET_EXCEEDED", "the proof that the lane manifests are disjoint ran out of time")
    at, under = {}, {}
    for li, lane in enumerate(lanes):
        for ei, e in enumerate(lane["entries"]):
            for alt in e.alts:
                p = literal_prefix(alt)
                at.setdefault(p, set()).add((li, ei))
                for k in range(len(p) + 1):
                    under.setdefault(p[:k], set()).add((li, ei))
    pairs, total, n = [], 0, 0
    for li, lane in enumerate(lanes):
        for ei, e in enumerate(lane["entries"]):
            tick()
            cand = set()
            for alt in e.alts:
                p = literal_prefix(alt)
                cand.update(under.get(p, ()))
                for k in range(len(p)):
                    cand.update(at.get(p[:k], ()))
            for lj, ej in sorted(c for c in cand if c[0] > li):
                n += 1
                if not n % 16:
                    tick()
                other = lanes[lj]["entries"][ej]
                if entries_overlap(e, other):
                    total += 1
                    if len(pairs) < SPEC_PAIRS:
                        pairs.append((lane["id"], e.raw, lanes[lj]["id"], other.raw))
    return pairs, total


def overlap_denial(lang, name, pairs, total):
    """The denial of exit 10 for lanes of the plan that overlap each other: both lane ids and both raw entries of every pair."""
    groups = []
    for a, ea, b, eb in pairs:
        if groups and (groups[-1]["a"], groups[-1]["b"]) == (a, b):
            groups[-1]["entries"].append([ea, eb])
        else:
            groups.append({"a": a, "b": b, "entries": [[ea, eb]]})
    lines = [T(lang, "set_conflict", s=name)] + [T(lang, "set_overlap", a=x["a"], b=x["b"], pairs="; ".join("%s <-> %s" % tuple(p) for p in x["entries"])) for x in groups]
    return set_deny(lang, "CONFLICT", "\n".join(lines + (["... and %d more" % (total - len(pairs))] if total > len(pairs) else [])), overlaps=groups)


def _claim_same(old, want):
    """Does the claim `old` hold what `want` says (entries, worktree, target, base, override and the set keys)?"""
    return old["entries"] == want["entries"] and old["worktree"] == want["worktree"] and old["target"] == want["target"] and old["base"] == want["base"] and \
        old["override"] == want["override"] and [claim_extra(old, k) for k in ("set", "lane", "role")] == [claim_extra(want, k) for k in ("set", "lane", "role")]


def _new_dirs(paths):
    """The directories above `paths` that do not exist yet (what a failed write must not leave behind)."""
    new = set()
    for p in paths:
        d = os.path.dirname(p)
        while d and not os.path.isdir(d) and d not in new:
            new.add(d)
            d = os.path.dirname(d)
    return new


def commit_store(writes, deletes):
    """Change the store as one: `writes` [(path, bytes, previous bytes or None)] go in with replace_files (the record is the last one), then
    `deletes` [(path, previous bytes)] are removed; when a deletion fails, every deletion and write already made is undone from the previous
    bytes (a file that had none is removed) and the error is raised, so the store never holds a mixture of two versions.  Every removal goes
    through _remove, retried while a reader holds the file open.  NotRestored when an undo fails as well."""
    new_dirs = _new_dirs([p for p, _d, _c in writes])

    def drop_dirs():
        for d in sorted(new_dirs, key=len, reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass
    try:
        replace_files([(p, d, c, None) for p, d, c in writes])  # puts its own files back when a move fails
    except BaseException:
        drop_dirs()
        raise
    gone = []
    try:
        for path, cur in deletes:
            _remove(path)
            gone.append((path, cur))
    except BaseException as err:
        lost = []
        for path, cur in reversed(gone):
            try:
                write_atomic(path, cur)
            except OSError:
                lost.append(path)
        for path, _data, cur in reversed(writes):
            try:
                if cur is None:
                    _remove(path)
                else:
                    write_atomic(path, cur)
            except OSError:
                lost.append(path)
        drop_dirs()
        if lost:
            raise NotRestored("%s; and %s could not be put back" % (err, ", ".join(lost)))
        raise


def _lane_checks(g, lang, mdl, rec, snap, members, heads, wts):
    """Step 10 of set-plan: the lanes of the record that were already started -> (errors for exit 24, the items of refuse16 for exit 16, removed ids)."""
    errs, blocked, removed = [], [], []
    by_id = {m["id"]: (i, m) for i, m in enumerate(mdl["lanes"])}
    for old in rec["lanes"]:
        detached = members.get("wt:" + pkey(old["worktree"]))  # the registered worktree on a detached HEAD: its commits and changes are the lane's
        evs = [ev for ev in (members.get(lane_key(old["branch"])), detached) if ev]
        uncommitted = set().union(*(ev["paths"]["uncommitted"] for ev in evs))
        changed = sorted(set().union(*(ev["paths"]["committed"] for ev in evs)) | uncommitted)
        branch = real_branch(old, heads)
        hit = by_id.get(old["id"])
        if hit is None:  # the lane is removed: refused while it holds work
            removed.append(old["id"])
            if branch is not None and "refs/heads/" + branch not in snap["merged"]:
                blocked.append((old["id"], "UNMERGED_WORK", T(lang, "set_why_unmerged", l=old["id"], b=old["branch"]), []))
            elif detached and detached["paths"]["committed"]:
                blocked.append((old["id"], "UNMERGED_WORK", T(lang, "set_why_unmerged", l=old["id"], b=old["branch"]), sorted(detached["paths"]["committed"])[:SPEC_ERRORS]))
            if uncommitted:
                blocked.append((old["id"], "DIRTY_WORKTREE", T(lang, "set_why_dirty", l=old["id"]), sorted(uncommitted)[:SPEC_ERRORS]))
            continue
        i, new = hit
        started = branch is not None or any(not w["bare"] and not w["prunable"] and (pkey(w["path"]) == pkey(old["worktree"]) or
                                                                                 (w["branch"] and fold(w["branch"]) == fold(old["branch"]))) for w in wts)
        if started and new["branch"] != old["branch"]:
            errs.append(("lanes[%d].branch" % i, "STATE", "lane %s has a branch or a worktree: its branch %s cannot change" % (old["id"], old["branch"])))
        if started and pkey(new["worktree"]) != pkey(old["worktree"]):
            errs.append(("lanes[%d].worktree" % i, "STATE", "lane %s has a branch or a worktree: its worktree %s cannot change" % (old["id"], old["worktree"])))
        outside = ManifestIndex(new["paths"], g.deadline).outside(changed)
        if outside:
            blocked.append((old["id"], "SHRINK", T(lang, "set_why_shrink", l=old["id"], files=_few(outside)), outside[:200]))
    return errs, blocked, removed


def plan_set(g, args, mdl):
    """Steps 5 to 13 of set-plan (Sets design): the record, the live base, the names against the repository, one snapshot, the lanes that were
    already started, the judgement against every other claimant, the new record and claims, and the write.  Runs inside the claim lock for a
    registration and without it for --dry-run.  -> the result dict."""
    lang, name, target, write = args.lang, args.set, args.target, not args.dry_run
    claims, bad_claims = read_claims(g)
    try:
        rec = read_set(g, name)
    except (SetNewer, SetUnreadable) as err:
        return record_denial(lang, name, err)
    if args.amend:
        if rec is None:
            return set_deny(lang, "SET_UNKNOWN", T(lang, "set_unknown", s=name))
        if fold(target) != fold(rec["target"]):
            return invalid_set(lang, [("--target", "STATE", "a target never changes: set %s lands on %s; release it and plan a new set" % (name, rec["target"]))])
        if args.expect_revision != rec["revision"]:
            return set_deny(lang, "STALE", T(lang, "set_stale_revision", s=name, cur=rec["revision"], exp=args.expect_revision),
                            kind="revision", expected=args.expect_revision, current=rec["revision"])
    elif rec is not None:
        return set_deny(lang, "SET_EXISTS", T(lang, "set_exists", s=name, rev=rec["revision"]), current=rec["revision"])
    heads, remotes, syms = list_refs(g)
    why = None
    if target not in heads:
        why = "the target %s is not a local branch: plan against a local branch" % _shown(target)
    else:
        try:
            tip, _ = resolve_target(g, heads, remotes, syms, target)
            if tip["sha"] != heads[target]:
                why = "the local branch %s is behind or diverged from its remote-tracking copy: lanes cut from it would not descend from the sha the plan names" % _shown(target)
        except Uncertain as err:
            why = str(err)
    if why:
        return unknown_set(lang, "TARGET_UNCERTAIN", why)
    live = heads[target]
    if live != mdl["base"]:
        return set_deny(lang, "STALE", T(lang, "set_stale_base", t=target, live=live, base=mdl["base"]), kind="base", expected=mdl["base"], current=live)
    ib = integration_branch(name)
    recorded = [ln["branch"] for ln in rec["lanes"]] + [ib] if rec is not None else []  # the branches of the record, spelled as it spells them
    registered = {fold(x) for x in recorded}  # a newer-format claim of one of these is the claim gate's (exit 11)
    own_claims = {k: d for k, d in claims.items() if rec is not None and (claim_set(d) == name or claim_set(d) is None and d["branch"] in recorded)}  # a fresh registration has none: a remnant is refused like any claim; an amend rewrites a set-less claim of a branch of the record spelled as the record spells it (another spelling is another claim file where case matters, and clashes, exit 12)
    others = {k: d for k, d in claims.items() if k not in own_claims}
    branches = [(m["id"], "lanes[%d].branch" % i, m["branch"]) for i, m in enumerate(mdl["lanes"])] + [("integration", "integration", ib)]
    pool = list(heads) + [d["branch"] for d in others.values()]
    clashes, foreign, existing = [], [], []
    for lid, field, b in branches:
        reason = name_clash(b, pool)
        if reason:
            clashes.append((field, "BRANCH_NAME", "lane %s: %s %s" % (lid, b, reason)))
        gated = fold(b) in registered and newer_claim(bad_claims, b) is not None
        if fold(b) in others or (newer_claim(bad_claims, b) is not None and not gated):
            foreign.append((field, "LANE_EXISTS", T(lang, "set_lane_exists", l=lid, b=b)))
        elif b in heads and fold(b) not in own_claims and fold(b) not in registered:  # an amend writes the missing claim of a branch of the record
            existing.append((field, "BRANCH_EXISTS", T(lang, "set_branch_exists", l=lid, b=b)))
    wts = worktrees(g)
    registered_wt = {ln["id"]: pkey(ln["worktree"]) for ln in rec["lanes"]} if rec is not None else {}
    for i, m in enumerate(mdl["lanes"]):
        for w in wts:
            at = pkey(w["path"]) == pkey(m["worktree"])  # the lane's own worktree: on its branch, or (an amend) detached at the path the record registers
            own = at and (w["branch"] and fold(w["branch"]) == fold(m["branch"]) or w["detached"] and registered_wt.get(m["id"]) == pkey(m["worktree"]))
            if not own and (inside_path(m["worktree"], w["path"]) or inside_path(w["path"], m["worktree"])):
                clashes.append(("lanes[%d].worktree" % i, "WORKTREE", "lane %s: %s is, lies inside or contains the worktree %s of the repository" % (m["id"], m["worktree"], w["path"])))
        if inside_path(m["worktree"], g.common):
            clashes.append(("lanes[%d].worktree" % i, "WORKTREE", "lane %s: %s lies inside the git directory" % (m["id"], m["worktree"])))
    if clashes:
        return invalid_set(lang, clashes, "INVALID_MANIFEST")
    for errors, code, key in ((foreign, "LANE_EXISTS", None), (existing, "BRANCH_EXISTS", None)):
        if errors:
            return set_deny(lang, code, "\n".join(t for _f, _c, t in errors), errors=[{"field": f, "code": c, "text": t} for f, c, t in errors])
    try:
        snap = gather(g, None, target)
    except Uncertain as err:
        return unknown_set(lang, "TARGET_UNCERTAIN", str(err))
    warns = list(snap["warnings"]) + backstop_warnings(g, True)  # the lanes of the set are parallel lanes
    member_keys = {lane_key(b) for _l, _f, b in branches} | {lane_key(ln["branch"]) for ln in (rec["lanes"] if rec else [])}
    member_keys |= {"wt:" + pkey(w) for w in [m["worktree"] for m in mdl["lanes"]] + [ln["worktree"] for ln in (rec["lanes"] if rec else [])]}
    members = {c["key"]: c for c in snap["claimants"] if c["key"] in member_keys}
    snap2 = dict(snap, claimants=[c for c in snap["claimants"] if c["key"] not in member_keys])
    removed = []
    if rec is not None:
        errs, blocked, removed = _lane_checks(g, lang, mdl, rec, snap, members, heads, wts)
        if errs:
            return invalid_set(lang, errs)
        if blocked:
            return refuse16(lang, "set-plan --amend", blocked)
    offending = []
    shared, unparsed = with_declared(snap2["claimants"], others, None, snap2)  # the claims outside the set are parsed once for every lane
    for m in mdl["lanes"]:
        # what with_declared gives for this lane alone, every claimant's files narrowed to those its manifest index matches (any other file is no evidence against the lane)
        key, index = lane_key(m["branch"]), ManifestIndex(m["paths"], g.deadline)
        cl = [dict(c, paths={k: {p for p in c["paths"][k] if index.hit(fpath(p))} for k in ("committed", "uncommitted")}) for c in shared if c["key"] != key]
        v = judge(snap2, others, bad_claims, m["branch"], m["entries"], None, declared=(cl, [b for b in unparsed if lane_key(b) != key]))
        if v["decision"] == "deny":
            offending.append((m, v))
    if offending:
        conflicts = any(v["conflicts"] for _m, v in offending)
        lines = [T(lang, "set_conflict", s=name)]
        for m, v in offending:
            lines.append(T(lang, "set_lane_item", l=m["id"], b=m["branch"]))
            lines += conflict_lines(lang, v)
        newer_only = not conflicts and all(u["code"] == "CLAIM_NEWER_FORMAT" for _m, v in offending for u in v["unknowns"])
        lines.append(T(lang, "newer_only") if newer_only else T(lang, "set_options", target=target))
        return set_deny(lang, "CONFLICT" if conflicts else "UNKNOWN", "\n".join(lines),
                        lanes=[{"id": m["id"], "branch": m["branch"], "code": v["code"], "conflicts": v["conflicts"], "unknowns": v["unknowns"]} for m, v in offending])
    now = now_iso()
    by = who(g) if write else ""
    old_lanes = {ln["id"]: ln for ln in rec["lanes"]} if rec else {}
    new_lanes = []
    for m in mdl["lanes"]:
        old = old_lanes.get(m["id"])
        lane = dict(old) if old else {}
        fresh = {"id": m["id"], "title": m["title"], "branch": m["branch"], "worktree": m["worktree"], "paths": list(m["paths"]),
                 "depends_on": list(m["depends_on"]), "serves": list(m["serves"]), "outcome": m["outcome"], "acceptance": m["acceptance"]}
        if old is None:
            lane.update(fresh, state="planned", head=None, ready_target=None, changes=None, note="", updated=now)
        else:
            if any(old.get(k) != fresh[k] for k in fresh):
                lane["updated"] = now
            lane.update(fresh)
            lane.setdefault("ready_target", None)
            lane.setdefault("changes", None)  # the state, the head, the ready_target, the changes and the note of a lane that survives stay
        new_lanes.append(_ordered(lane, RECORD_LANE_KEYS))
    new = dict(rec) if rec else {}
    new.update(v=SET_FORMAT, set=name, target=rec["target"] if rec else target, base=mdl["base"], created=rec["created"] if rec else now, title=mdl["title"],
               requirements=[dict(r) for r in mdl["requirements"]], sheet=mdl["sheet"], notes=list(mdl["notes"]), shared=mdl["shared"],
               integration=rec["integration"] if rec else None, lanes=new_lanes)

    def core(r):
        return {k: v for k, v in r.items() if k not in ("revision", "updated", "by")}
    wants = []
    for m in mdl["lanes"]:
        wants.append({"branch": m["branch"], "worktree": m["worktree"], "target": new["target"], "base": mdl["base"], "override": "", "entries": list(m["paths"]),
                      "extra": [("set", name), ("lane", m["id"])]})
    wants.append({"branch": ib, "worktree": "", "target": new["target"], "base": mdl["base"], "override": "", "entries": [integration_entry(name)],
                  "extra": [("set", name), ("role", "integration")]})
    file_writes, written = [], []
    for want in wants:
        old = claims.get(fold(want["branch"]))
        if old is not None and _claim_same(old, want):
            continue
        want["created"] = old["created"] if old else now
        want["by"] = by
        if old:  # the keys of the claim this guard does not know stay
            want["extra"] += [(k, v) for k, v in old.get("extra") or [] if k not in ("set", "lane", "role")]
        try:
            path, data = claim_bytes(g, want["branch"], want)
        except ClaimTooNew as err:
            return set_deny(lang, "UNKNOWN", "[CLAIM_NEWER_FORMAT] %s" % newer_text(want["branch"], err.v),
                            unknowns=[{"code": "CLAIM_NEWER_FORMAT", "text": newer_text(want["branch"], err.v)}])
        except ClaimRefused as err:
            return invalid_set(lang, [("lanes", "BRANCH_NAME", "%s: %s" % (want["branch"], err))], "INVALID_MANIFEST")
        file_writes.append((path, data, _file_bytes(path)))
        written.append(path)
    wanted = {fold(w["branch"]) for w in wants}
    deletes = []
    for key, doc in own_claims.items():
        if key not in wanted:
            real = in_store(os.path.join(store(g), "claims"), doc["file"])
            if real is None:
                warns.append({"code": "CLAIM_NOT_REMOVED", "text": "the claim file %s lies outside the claim store and was left alone" % doc["file"]})
            else:
                deletes.append((doc["file"], _file_bytes(doc["file"])))
    unchanged = rec is not None and core(new) == core(rec) and not file_writes and not deletes
    revision = rec["revision"] if unchanged else (rec["revision"] + 1 if rec else 1)
    if not unchanged:
        new.update(revision=revision, updated=now, by=by)
        rpath = set_path(g, name)
        file_writes.append((rpath, record_bytes(new), _file_bytes(rpath)))
        written.append(rpath)
        if write:
            lanes_audit = [{"id": ln["id"], "branch": ln["branch"], "worktree": ln["worktree"], "entries": ln["paths"], "serves": ln["serves"]} for ln in new_lanes]
            line = audit_line(g, by=by, op="set-amend" if rec else "set-plan", set=name, target=new["target"], base=mdl["base"], revision=revision,
                              requirements=[r["id"] for r in new["requirements"]], lanes=lanes_audit, integration=ib, host="cli",
                              **({"previous_revision": rec["revision"], "removed": removed} if rec else {}))
            commit_store(file_writes, deletes)
            audit_after(g, line, warns)
    lane_rows = [{"id": ln["id"], "title": ln["title"], "branch": ln["branch"], "worktree": ln["worktree"], "entries": ln["paths"], "depends_on": ln["depends_on"],
                  "serves": ln["serves"], "outcome": ln["outcome"], "acceptance": ln["acceptance"], "state": ln["state"],
                  "create": 'git worktree add "%s" -b %s %s' % (ln["worktree"], ln["branch"], new["target"])} for ln in new_lanes]
    req_rows = requirement_rows(new)
    first = lane_rows[0] if lane_rows else None  # the example of set_ok_plan cuts the first lane from the recorded base, every argument one quoted word
    example = "git worktree add %s -b %s %s" % (sh_quote(first["worktree"]), sh_quote(first["branch"]), sh_quote(mdl["base"])) if first else ""
    if args.dry_run:
        head = T(lang, "set_ok_check", s=name)
    elif unchanged:
        head = T(lang, "set_unchanged", s=name, rev=revision)
    elif rec is not None:
        head = T(lang, "set_ok_amend", s=name, old=rec["revision"], rev=revision, n=len(lane_rows))
    else:
        head = T(lang, "set_ok_plan", s=name, n=len(lane_rows), t=new["target"], base=mdl["base"], rev=revision, example=example)
    lines = [head] + [T(lang, "set_line", l=r["id"], b=r["branch"], w=r["worktree"], n=len(r["entries"])) for r in lane_rows] + [T(lang, "set_line_integration", b=ib)]
    lines += ["(%s) %s" % (w["code"], w["text"]) for w in warns]
    return {"decision": "allow", "code": "OK", "set": name, "target": {"name": new["target"], "sha": live}, "base": mdl["base"], "revision": revision,
            "dry_run": args.dry_run, "unchanged": unchanged, "integration_branch": ib, "order": mdl["order"], "requirements": req_rows, "lanes": lane_rows,
            "written": [] if args.dry_run or unchanged else [p.replace("\\", "/") for p in written], "warnings": warns, "message": "\n".join(lines)}


def requirement_rows(rec):
    """The requirements of a plan or a record as {id, text, lanes}, in their order: `lanes` are the ids of the lanes that serve the requirement, in lane
    order.  The coverage is derived from the `serves` of the lanes and never stored."""
    return [{"id": r["id"], "text": r["text"], "lanes": [ln["id"] for ln in rec["lanes"] if r["id"] in ln["serves"]]} for r in rec["requirements"]]


def _file_bytes(path):
    """The bytes of a file, or None when there is none."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def revision_arg(text):
    """argparse type of --expect-revision: 1 to 999,999,999 written without a sign or a leading zero."""
    if not re.fullmatch(r"[1-9][0-9]{0,8}", text):
        raise argparse.ArgumentTypeError("%r is not a revision (1 to 999999999)" % text)
    return int(text)


def cmd_set_plan(args):
    g = open_repo(args.repo)
    if g is None:
        sys.stderr.write("not a git repository: %s\n" % args.repo)
        return 2
    lang, name = args.lang, args.set
    why = set_name_problem(name, lang)
    if why:
        return set_emit(args, invalid_set(lang, [("--set", "FORMAT", why)]))
    text, spec_path, errs = read_spec(g, args.spec)
    spec, dupes = None, 0
    if text is not None:
        spec, dupes, errs = parse_spec(text)
    mdl = None
    if not errs:
        errs, mdl = check_spec(g, spec, dupes, name, args.target, spec_path, lang)
    if errs:
        return set_emit(args, invalid_set(lang, list(errs)))
    pairs, total = lane_overlaps(mdl["lanes"], g.deadline)
    if pairs:
        return set_emit(args, overlap_denial(lang, name, pairs, total))
    if args.dry_run:
        return set_emit(args, plan_set(g, args, mdl))
    try:
        with Lock(g):
            g.deadline = time.monotonic() + BUDGET_S  # the budget of the git calls starts when the lock is held
            v = plan_set(g, args, mdl)
    except LockTimeout:
        v = set_deny(lang, "LOCK_TIMEOUT", T(lang, "lock", s=os.environ.get("MAGOS_LOCK_TIMEOUT", int(LOCK_S))))
    return set_emit(args, v)


# ---------------------------------------------------------------- set-show, set-update, set-release
SET_TEXT_MAX = 200  # characters of --note and --reason, and the files an OUT_OF_LANE listing carries
_TRANSITIONS = {"planned": ("active", "blocked"), "active": ("active", "ready", "blocked"), "ready": ("active", "ready", "integrated", "blocked"),
                "integrated": ("integrated", "blocked"), "blocked": ("active", "blocked")}  # the states --state may name, by the state the lane is in


def record_bytes(rec):
    """The bytes of a set record as the guard writes it: the keys of RECORD_KEYS first, indented, LF, UTF-8 without a BOM; a non-finite number
    (which _loads never reads) raises ValueError.  Every write of a record (set-plan, set-update) goes through this one serialiser, so the
    change of one field leaves every other byte as it was."""
    return (json.dumps(_ordered(rec, RECORD_KEYS), ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _seg_glob(pat, name):
    """Does the segment glob `pat` (* and ?) match the plain name?  Greedy, with one point to fall back to: O(len(pat) * len(name))."""
    if not _WILD.search(pat):
        return pat == name
    p = i = 0
    star = mark = -1
    while i < len(name):
        if p < len(pat) and pat[p] == "*":
            star, mark, p = p, i, p + 1
        elif p < len(pat) and (pat[p] == "?" or pat[p] == name[i]):
            p += 1
            i += 1
        elif star >= 0:
            mark += 1
            i, p = mark, star + 1
        else:
            return False
    while p < len(pat) and pat[p] == "*":
        p += 1
    return p == len(pat)


def _path_glob(alt, path):
    """Does the path glob `alt` (segment globs; ** is any number of segments, also none) match the plain path?  The same greedy walk over segments."""
    p = i = 0
    star = mark = -1
    while i < len(path):
        if p < len(alt) and alt[p] == GS:
            star, mark, p = p, i, p + 1
        elif p < len(alt) and _seg_glob(alt[p], path[i]):
            p += 1
            i += 1
        elif star >= 0:
            mark += 1
            i, p = mark, star + 1
        else:
            return False
    while p < len(alt) and alt[p] == GS:
        p += 1
    return p == len(alt)


class ManifestIndex:
    """The entries of one manifest, indexed for testing many paths.  The prefixes of the literal files and directories an entry names are
    looked up in sets; every other entry is indexed by the folded literal first segment of each of its alternatives, and an alternative whose
    first segment holds * or ?, or is **, goes to a group that is tested for every path.  A path without a
    wildcard character is matched by a greedy glob walk, which takes time proportional to the size of the glob and the path; a path that
    holds * or ? is compared with the exact intersection.  hit(path) is exactly path_hit over the entries.  `deadline` (a monotonic time)
    ends a long test with GitFail BUDGET_EXCEEDED, never with a partial answer."""

    def __init__(self, raws, deadline=None):
        self.deadline, self.literal, self.proper, self.buckets, self.wild, self.entries, self.tests = deadline, set(), set(), {}, [], [], 0
        for raw in raws:
            try:
                e = parse_entry(raw)
            except ManifestError:  # a record is validated when it is written: an entry that cannot be read here matches nothing
                continue
            self.entries.append(e)
            for alt in e.alts:  # a file that an entry names as a directory: the path is a proper prefix of the entry's literal part
                lit = literal_prefix(alt)
                self.proper.update(lit[:k] for k in range(1, len(lit)))
            alt = e.alts[0]
            if len(e.alts) == 1 and alt[-1] == GS and not any(g == GS or _WILD.search(g) for g in alt[:-1]):
                self.literal.add(alt[:-1])
                continue
            placed = set()
            for a in e.alts:
                key = None if a[0] == GS or _WILD.search(a[0]) else a[0]
                if key not in placed:
                    placed.add(key)
                    (self.wild if key is None else self.buckets.setdefault(key, [])).append(e)

    def tick(self):
        self.tests += 1
        if self.deadline and not self.tests % 256 and time.monotonic() > self.deadline:
            raise GitFail("BUDGET_EXCEEDED", "the comparison of the files with the lane manifests ran out of time")

    def hit(self, path):
        """Does the folded path (fpath) fall under an entry of the manifest?"""
        if not path:
            return False
        if any(_WILD.search(g) for g in path):  # a file name with * or ? is a glob itself: only the exact intersection compares it
            for e in self.entries:
                self.tick()
                if path_hit(e, path):
                    return True
            return False
        if any(path[:k] in self.literal for k in range(1, len(path) + 1)) or path in self.proper:
            return True
        for e in self.buckets.get(path[0], []) + self.wild:
            self.tick()
            if any(_path_glob(a, path) for a in e.alts):
                return True
        return False

    def outside(self, files):
        """The files of `files` that no entry matches, sorted."""
        return sorted(p for p in files if not self.hit(fpath(p)))


def lane_worktrees(wts, lane, branch, missing=False):
    """The worktrees a lane has: at its registered path or on its branch (`branch` is the real branch of the lane, or None), not bare and, unless
    `missing`, not prunable (with `missing` also those whose directory is missing, which the callers that must not miss uncommitted work count
    as dirty); the one at the registered path first."""
    here = [w for w in wts if not w["bare"] and (missing or not w["prunable"]) and
            (pkey(w["path"]) == pkey(lane["worktree"]) or (branch is not None and w["branch"] == branch))]
    return sorted(here, key=lambda w: pkey(w["path"]) != pkey(lane["worktree"]))


def claim_status(name, lane, claims, bad):
    """`ok`, `missing` or `mismatch` for the claim of a lane of set `name`: it must carry `set=<name>` and `lane=<id>`, the record's entries
    in order, the record's worktree (compared with pkey; an empty one differs) and an empty override.  A claim of the branch that cannot be
    read, or comes from a newer MAGOS, is a mismatch (it cannot be rewritten as it is)."""
    doc = claims.get(fold(lane["branch"]))
    if doc is None:
        rel = os.path.normcase(os.path.join(*lane["branch"].split("/")) + ".claim")
        return "mismatch" if newer_claim(bad, lane["branch"]) or any(os.path.normcase(b) == rel for b in bad) else "missing"
    same_worktree = doc["worktree"] != "" and pkey(doc["worktree"]) == pkey(lane["worktree"])
    return "ok" if claim_extra(doc, "set") == [name] and claim_extra(doc, "lane") == [lane["id"]] and doc["entries"] == lane["paths"] and same_worktree \
        and doc["override"] == "" else "mismatch"


def is_ancestor(g, a, b):
    """Is commit `a` an ancestor of (or equal to) commit `b`?  An object that git does not know is no ancestor."""
    return g.run("merge-base", "--is-ancestor", a, b, ok=(0, 1, 128))[0] == 0


def set_lookup(g, args):
    """-> (the record of the set the command names, None), or (None, the denial): exit 21 (no record), 23 (a newer format) or 11 (unreadable)."""
    try:
        rec = read_set(g, args.set)
    except (SetNewer, SetUnreadable) as err:
        return None, record_denial(args.lang, args.set, err)
    if rec is None:
        return None, set_deny(args.lang, "SET_UNKNOWN", T(args.lang, "set_unknown", s=args.set))
    return rec, None


def target_paths(g, rec, heads, tip):
    """The target's own changes of the drift view -> the distinct files, sorted, of the target's commits since the plan's base that the set's own work
    does not hold: one `log` whose negative revisions are the base, the tip of the local integration branch when it exists and the recorded head of
    every `ready` or `integrated` lane, in the record's lane order.  A merge names only its own changes (dense-combined), a rename both paths, and a
    negative revision that no longer names an object excludes nothing (--ignore-missing).  Every revision is a full object name: the format gate
    refuses a record whose base or head is none (_record_shape), and the filter below keeps that true of every value passed."""
    neg = [rec["base"]]
    itip = heads.get(integration_branch(rec["set"]))
    if itip:
        neg.append(itip)
    neg += [ln["head"] for ln in rec["lanes"] if ln["state"] in ("ready", "integrated") and ln["head"]]
    out = g.run("log", "--ignore-submodules=none", "--no-show-signature", "-z", "--format=", "--name-only", "--no-renames", "--diff-merges=dense-combined",
                "--ignore-missing", tip, "--not", *[x for x in neg if _BASE.fullmatch(x)])[1]
    return sorted(_names_z(out))


def set_view(g, rec, drift):
    """The view of a set record derived from the repository (Sets, set-show) -> (view, warnings).  It only reads: refs, worktrees, claims and,
    with `drift`, the files each lane changed and the files of the target's commits that the set's own work does not hold (target_paths).  The
    target tip is the tip of the local branch of the record (never resolve_target, which a remote-tracking copy can make uncertain)."""
    name, base, wts = rec["set"], rec["base"], worktrees(g)
    heads = list_refs(g)[0]
    claims, bad = read_claims(g)
    tip = heads.get(rec["target"])
    view = {"target_tip": tip, "target_moved": None if tip is None else tip != base, "lanes": []}
    warns, changed, index = [], {}, {}
    for lane in rec["lanes"]:
        branch = real_branch(lane, heads)
        lane_tip = heads[branch] if branch else None
        here = lane_worktrees(wts, lane, branch)
        ops = []
        for w in here:  # every worktree of the lane, as set-update judges them: a second one may hold the uncommitted work
            notes, unreadable = operation(w["path"])
            ops += [x for x in notes + (["unreadable"] if unreadable else []) if x not in ops]
        clean = not any(worktree_dirty(g, w["path"]) for w in here) if here else None
        ahead = g.run("rev-list", "--count", "%s..%s" % (base, lane_tip), ok=(0, 128)) if lane_tip else None
        row = {"id": lane["id"], "branch_exists": branch is not None, "tip": lane_tip,
               "ahead": int(ahead[1].decode().strip()) if ahead and ahead[0] == 0 else None,
               "descends_from_base": is_ancestor(g, base, lane_tip) if lane_tip else None, "worktree_present": bool(here), "worktree_clean": clean,
               "operation": ops, "state": lane["state"], "head": lane["head"], "claim": claim_status(name, lane, claims, bad), "changes": lane.get("changes")}
        if drift:
            index[lane["id"]] = ManifestIndex(lane["paths"], g.deadline)
            files = None
            if lane_tip:
                paths = committed_paths(g, tip or base, lane_tip)
                if paths is None:  # no common history: a merge would need --allow-unrelated-histories
                    warns.append({"code": "UNRELATED_HISTORY", "text": "lane %s: %s shares no history with %s" % (lane["id"], branch, rec["target"])})
                else:
                    files = sorted(paths)
            changed[lane["id"]] = files
            row.update(changed=files, out_of_lane=index[lane["id"]].outside(files) if files else [],
                       moved_since_ready=None if lane_tip is None else lane["state"] == "ready" and lane_tip != lane["head"])
        view["lanes"].append(row)
    view["requirements"] = requirement_rows(rec)
    if drift:
        by_file = {}
        for lane in rec["lanes"]:
            for p in changed[lane["id"]] or ():
                by_file.setdefault(p, []).append(lane["id"])
        overlap = []
        if tip is not None and tip != base:
            for n, p in enumerate(target_paths(g, rec, heads, tip), 1):
                if not n % 256 and time.monotonic() > g.deadline:
                    raise GitFail("BUDGET_EXCEEDED", "the comparison of the files with the lane manifests ran out of time")
                ids = [ln["id"] for ln in rec["lanes"] if index[ln["id"]].hit(fpath(p))]
                if ids:
                    overlap.append({"path": p, "lanes": ids})
        view["drift"] = {"shared_changes": [{"path": p, "lanes": ids} for p, ids in sorted(by_file.items()) if len(ids) > 1], "target_overlap": overlap,
                         "stale": None if tip is None else bool(tip != base and overlap),
                         "merge_order": merge_order([ln["id"] for ln in rec["lanes"]], {ln["id"]: ln["depends_on"] for ln in rec["lanes"]})}
    return view, warns


def show_text(lang, rec, view):
    """The text view of set-show: the header, the stored sheet verbatim, one line per lane and, with --drift, the drift lines that are not empty."""
    def short(sha):
        return sha[:7] if sha else "-"
    lines = [T(lang, "show_head", s=rec["set"], t=rec["target"], base=short(rec["base"]), rev=rec["revision"], i=rec["integration"] or "-"), rec["sheet"].rstrip("\n")]
    for lane, row in zip(rec["lanes"], view["lanes"]):
        if "unreadable" in row["operation"]:
            wt = T(lang, "show_wt_unreadable")
        elif row["operation"]:
            wt = T(lang, "show_wt_op", op="/".join(row["operation"]))
        else:
            wt = T(lang, "show_wt_absent") if not row["worktree_present"] else T(lang, "show_wt_clean" if row["worktree_clean"] else "show_wt_dirty")
        lines.append(T(lang, "show_lane", box="[x]" if lane["state"] in ("ready", "integrated") else "[ ]", l=lane["id"], st=lane["state"], head=short(lane["head"]),
                       tip=short(row["tip"]), n="-" if row["ahead"] is None else row["ahead"], wt=wt, b=lane["branch"]))
        ch = lane.get("changes")
        if lane["state"] == "integrated" and ch:  # what the lane changed, stored when it was recorded integrated
            def listed(items, more):
                return "; ".join(items + ([T(lang, "show_more", n=more)] if more else [])) or "-"
            lines.append(T(lang, "show_changes", l=lane["id"], commits=ch["commits"], files=ch["files"], ins=ch["insertions"], paths=listed(ch["paths"], ch["paths_more"]),
                           subjects=listed(ch["subjects"], ch["more"]), **{"del": ch["deletions"]}))
    drift = view.get("drift")
    if drift:
        for row in view["lanes"]:
            if row["out_of_lane"]:
                lines.append(T(lang, "show_out", l=row["id"], files=_few(row["out_of_lane"])))
        if drift["shared_changes"]:
            lines.append(T(lang, "show_shared", files=_few(["%s [%s]" % (x["path"], ",".join(x["lanes"])) for x in drift["shared_changes"]])))
        if drift["target_overlap"]:
            lines.append(T(lang, "show_moved", base=short(rec["base"]), tip=short(view["target_tip"]),
                           files=_few(["%s [%s]" % (x["path"], ",".join(x["lanes"])) for x in drift["target_overlap"]])))
        moved = [row["id"] for row in view["lanes"] if row["moved_since_ready"]]
        if moved:
            lines.append(T(lang, "show_moved_ready", lanes=", ".join(moved)))
        if drift["merge_order"]:
            lines.append(T(lang, "show_order", order=" -> ".join(drift["merge_order"])))
    return "\n".join(lines)


def cmd_set_show(args):
    g = open_repo(args.repo)
    if g is None:
        sys.stderr.write("not a git repository: %s\n" % args.repo)
        return 2
    why = set_name_problem(args.set, args.lang)
    if why:
        return set_emit(args, invalid_args(args.lang, [("--set", "FORMAT", why)]))
    rec, denial = set_lookup(g, args)  # no lock, and nothing is created
    if denial:
        return set_emit(args, denial)
    view, warns = set_view(g, rec, args.drift)
    return set_emit(args, {"decision": "allow", "code": "OK", "record": rec, "view": view, "warnings": warns, "message": show_text(args.lang, rec, view)})


def refuse16(lang, op, items):
    """The denial of exit 16 for `op`, the one builder of exit 16 of set-plan --amend, set-update and set-release: items [(lane, reason, the text of
    the reason[, the files the reason names])]; every item of `blocked` carries lane, reason and files (a list, empty when the item names none)."""
    return set_deny(lang, "BLOCKED", T(lang, "set_blocked", op=op, why="; ".join(why for _l, _r, why, *_f in items)),
                    blocked=[{"lane": lane, "reason": reason, "files": list(files[0]) if files else []} for lane, reason, _w, *files in items])


def update_options(args):
    """The errors of the option values of set-update that need no repository (exit 24), each (field, code, text)."""
    errs, to = [], args.state
    why = set_name_problem(args.set, args.lang)
    if why:
        errs.append(("--set", "FORMAT", why))
    if args.head is not None and not _BASE.fullmatch(args.head):
        errs.append(("--head", "FORMAT", "a full object name: 40 or 64 hexadecimal digits"))
    elif args.head is not None and to not in ("ready", "integrated"):
        errs.append(("--head", "STATE", "--head goes with --state ready or integrated, not %s" % to))
    elif args.head is None and to in ("ready", "integrated"):
        errs.append(("--head", "MISSING", "--state %s needs --head <the tip of the lane branch>" % to))
    if args.note is not None:
        if len(args.note) > SET_TEXT_MAX:
            errs.append(("--note", "RANGE", "at most %d characters, not %d" % (SET_TEXT_MAX, len(args.note))))
        elif _SURROGATE.search(args.note):
            errs.append(("--note", "ENCODING", "holds a lone surrogate"))
        elif _CTL.search(args.note):
            errs.append(("--note", "FORMAT", "holds a control character"))
    if args.integration is not None:
        if to != "integrated":
            errs.append(("--integration", "STATE", "--integration goes with --state integrated, not %s" % to))
        elif args.integration != integration_branch(args.set):
            errs.append(("--integration", "FORMAT", "the integration branch of set %s is %s" % (args.set, integration_branch(args.set))))
    return errs


def update_checks(g, args, rec, lane, heads, wts):
    """The conditions of --state ready and of --state integrated that the repository decides -> (the denial (exit 16 or 22) or None, landed): `landed` is
    true when the head of an integrated lane is already an ancestor of the tip of the target (the ancestry test asks the target first and the integration
    branch second; the changes summary reuses the answer)."""
    lang, lid, head = args.lang, lane["id"], args.head.lower()
    branch = real_branch(lane, heads)
    if args.state == "ready":
        if branch is None:
            return refuse16(lang, "set-update", [(lid, "BRANCH_MISSING", T(lang, "set_why_missing", l=lid, b=lane["branch"]))]), False
        tip = heads[branch]
        if head != tip:
            return refuse16(lang, "set-update", [(lid, "HEAD_MISMATCH", T(lang, "set_why_head_tip", head=args.head, b=branch, tip=tip))]), False
        items = []
        for w in lane_worktrees(wts, lane, branch, missing=True):  # uncommitted work is not in the recorded head: a merge of it would leave that work behind
            if w["prunable"]:  # a worktree whose directory is missing (an unmounted drive) cannot be read: it is not known to be clean
                items.append((lid, "DIRTY_WORKTREE", T(lang, "set_why_wt_missing", l=lid, w=w["path"].replace("\\", "/"))))
                continue
            notes, unreadable = operation(w["path"])
            if notes or unreadable:
                items.append((lid, "OPERATION_IN_PROGRESS", T(lang, "set_why_operation", l=lid, op="/".join(notes + (["unreadable"] if unreadable else [])))))
            if dirty_paths(g, w["path"]):
                items.append((lid, "DIRTY_WORKTREE", T(lang, "set_why_dirty", l=lid)))
        if items:
            return refuse16(lang, "set-update", items), False
        paths = committed_paths(g, heads.get(rec["target"]) or rec["base"], tip)  # the plan's base stands in for a target that is gone
        if paths is None:
            return refuse16(lang, "set-update", [(lid, "NO_MERGE_BASE", T(lang, "set_why_base", l=lid))]), False
        outside = ManifestIndex(lane["paths"], g.deadline).outside(paths)
        if outside:
            return set_deny(lang, "OUT_OF_LANE", T(lang, "set_out_of_lane", l=lid, s=rec["set"], files=_few(outside, 20)), lane=lid, files=outside[:SET_TEXT_MAX],
                            truncated=len(outside) > SET_TEXT_MAX), False
        return None, False
    integration = integration_branch(rec["set"])
    if head != (lane["head"] or ""):
        return refuse16(lang, "set-update", [(lid, "HEAD_MISMATCH", T(lang, "set_why_head_recorded", head=args.head, l=lid, rec=lane["head"] or "-"))]), False
    if integration not in heads:
        return refuse16(lang, "set-update", [(lid, "BRANCH_MISSING", T(lang, "set_why_integration", b=integration))]), False
    landed = rec["target"] in heads and is_ancestor(g, head, heads[rec["target"]])
    if not landed and not is_ancestor(g, head, heads[integration]):
        return refuse16(lang, "set-update", [(lid, "NOT_MERGED", T(lang, "set_why_ancestor", head=args.head, t=rec["target"]))]), False
    return None, landed


def _subject(text):
    """A commit subject as the summary stores it: control characters become spaces, blanks at the ends go, an empty one reads `(no subject)` and one over
    CHANGES_SUBJECT_CHARS characters is cut to one character less followed by an ellipsis."""
    s = _CTL.sub(" ", text).strip()
    if not s:
        return "(no subject)"
    return s if len(s) <= CHANGES_SUBJECT_CHARS else s[:CHANGES_SUBJECT_CHARS - 1] + "…"


def changes_summary(g, ref, head):
    """What the lane at `head` changed against `ref` (full object names), from four read-only git commands -> the summary (CHANGES_KEYS, in that order), or
    None when the two share no history (merge-base exits 1; any other failure raises GitFail).  The commits are the non-merge commits of `ref..head` (a
    merge, such as the owner's merge of the target tip into the lane, is no lane commit); the files and lines are the net change from the merge base of the
    two (`ref...head`), merges included, so a lane that merged `ref` into itself is not charged with its files."""
    if g.run("merge-base", ref, head, ok=(0, 1))[0] != 0:
        return None
    rng = "%s..%s" % (ref, head)
    commits = int(g.text("rev-list", "--count", "--no-merges", rng).strip() or "0")
    subjects = []
    if commits:  # --no-merges filters first, --skip and --max-count apply before --reverse: the oldest CHANGES_SUBJECTS non-merge commits, oldest first
        out = g.text("log", "--ignore-submodules=none", "--no-show-signature", "--encoding=UTF-8", "--format=%s", "--reverse", "--no-merges",
                     "--skip=%d" % max(commits - CHANGES_SUBJECTS, 0), "--max-count=%d" % CHANGES_SUBJECTS, rng)
        lines = out.split("\n")  # one line per commit: an empty message is an empty line, which splitlines() would not tell from the end of the text
        if lines and lines[-1] == "":
            lines.pop()
        subjects = [_subject(x) for x in lines]
    toks = g.run("diff", "--ignore-submodules=none", "--numstat", "-z", "--find-renames", "--no-ext-diff", "--no-textconv", "%s...%s" % (ref, head),
                 "--")[1].split(b"\0")
    files = ins = dels = 0
    keys = {}  # the distinct keys of the changed files, in the order of the first file that has them
    i = 0
    while i < len(toks):
        tok, i = toks[i], i + 1
        cols = tok.split(b"\t", 2)
        if len(cols) < 3:
            continue
        added, removed, name = cols
        if name == b"":  # a rename or copy: the old and the new name follow as records of their own; it is one file, named by its new name
            names = toks[i:i + 2]
            name, i = (names[-1] if names else b""), i + 2
        files += 1
        ins += int(added) if added.isdigit() else 0  # a binary file shows - in both columns: one file, no line
        dels += int(removed) if removed.isdigit() else 0
        segs = _CTL.sub(" ", name.decode("utf-8", "replace")).split("/")
        keys.setdefault("/".join(segs[:2]), None)
    listed = list(keys)
    return {"commits": commits, "subjects": subjects, "more": commits - len(subjects), "files": files, "insertions": ins, "deletions": dels,
            "paths": listed[:CHANGES_PATHS], "paths_more": max(len(listed) - CHANGES_PATHS, 0)}


def lane_changes(g, rec, lane, heads, landed, lang):
    """The summary of the changes of the lane that `set-update --state integrated` records -> (denial, summary).  The compare tip is the tip of the local
    branch of the target, or, when the head is already in the target (`landed`), whose range against the tip would be empty, the lane's `ready_target`
    (the commit its ready was measured against; the plan's base when it is null).  Nothing is recorded when it cannot be measured: the missing target is
    exit 11 (TARGET_UNCERTAIN), no common history exit 16 (NO_MERGE_BASE)."""
    lid, target = lane["id"], rec["target"]
    if landed:
        ready = lane.get("ready_target")
        ref, shown = (ready, "the commit %s its ready was measured against" % ready) if ready else (rec["base"], "the plan's base %s" % rec["base"])
    elif target in heads:
        ref, shown = heads[target], target
    else:  # the message of this exit 11 is the text itself
        text = T(lang, "set_why_changes_target", t=target, l=lid)
        return set_deny(lang, "UNKNOWN", text, unknowns=[{"code": "TARGET_UNCERTAIN", "text": text}]), None
    summary = changes_summary(g, ref, lane["head"])
    if summary is None:
        return refuse16(lang, "set-update", [(lid, "NO_MERGE_BASE", T(lang, "set_why_changes_history", l=lid, ref=shown))]), None
    return None, summary


def update_set(g, args):
    """set-update inside the claim lock -> the result dict: the record is read, its revision compared, the lane and the transition checked, the
    conditions of the new state decided by the repository, and the record written whole (the one write)."""
    lang, name = args.lang, args.set
    rec, denial = set_lookup(g, args)
    if denial:
        return denial
    if args.expect_revision != rec["revision"]:
        return set_deny(lang, "STALE", T(lang, "set_stale_revision", s=name, cur=rec["revision"], exp=args.expect_revision), kind="revision",
                        expected=args.expect_revision, current=rec["revision"])
    lane = next((x for x in rec["lanes"] if x["id"] == args.lane), None)
    if lane is None:
        return invalid_args(lang, [("--lane", "UNKNOWN_LANE", "set %s has the lanes %s" % (name, ", ".join(x["id"] for x in rec["lanes"])))])
    to = args.state
    if to not in _TRANSITIONS[lane["state"]]:
        return invalid_args(lang, [("--state", "STATE", "lane %s is %s: it cannot become %s (from %s: %s)" % (lane["id"], lane["state"], to, lane["state"],
                                                                                                           ", ".join(_TRANSITIONS[lane["state"]])))])
    if to == "integrated":
        if rec["integration"] is None and args.integration is None:
            return invalid_args(lang, [("--integration", "MISSING", "the record names no integration branch yet: pass --integration %s" % integration_branch(name))])
        if rec["integration"] is not None and args.integration not in (None, rec["integration"]):
            return invalid_args(lang, [("--integration", "STATE", "the record names the integration branch %s" % rec["integration"])])
    changes = lane.get("changes") if to == "integrated" else None  # a lane that leaves integrated no longer states that it was merged
    ready_target = lane.get("ready_target")
    if to in ("ready", "integrated"):
        heads = list_refs(g)[0]
        denial, landed = update_checks(g, args, rec, lane, heads, worktrees(g))
        if denial:
            return denial
        if to == "ready":  # the commit the ready check measured the lane against: the target tip, or the plan's base for a target that is gone
            ready_target = heads.get(rec["target"]) or rec["base"]
        if to == "integrated" and lane["state"] == "ready":  # the first record of the merge: what the lane changed, measured now; a repeated update keeps it
            denial, changes = lane_changes(g, rec, lane, heads, landed, lang)
            if denial:
                return denial
    now = now_iso()
    new_lane = dict(lane, state=to, updated=now, note=lane["note"] if args.note is None else args.note,
                    head=args.head.lower() if to in ("ready", "integrated") else lane["head"], ready_target=ready_target, changes=changes)
    by = who(g)
    new = dict(rec, revision=rec["revision"] + 1, updated=now, by=by, integration=rec["integration"] if to != "integrated" else args.integration or rec["integration"],
               lanes=[_ordered(new_lane, RECORD_LANE_KEYS) if x is lane else x for x in rec["lanes"]])
    counts = {k: changes[k] for k in ("commits", "files", "insertions", "deletions")} if changes else None
    line = audit_line(g, by=by, op="set-update", set=name, lane=lane["id"], state=to, head=new_lane["head"], note=new_lane["note"], integration=new["integration"],
                      revision=new["revision"], changes=counts, host="cli")
    path = set_path(g, name)
    commit_store([(path, record_bytes(new), _file_bytes(path))], [])
    warns = []
    audit_after(g, line, warns)
    return {"decision": "allow", "code": "OK", "set": name, "lane": lane["id"], "state": to, "head": new_lane["head"], "changes": changes, "note": new_lane["note"],
            "integration": new["integration"], "revision": new["revision"], "warnings": warns,
            "message": "\n".join([T(lang, "set_ok_update", s=name, l=lane["id"], st=to, rev=new["revision"])] + ["(%s) %s" % (w["code"], w["text"]) for w in warns])}


def cmd_set_update(args):
    g = open_repo(args.repo)
    if g is None:
        sys.stderr.write("not a git repository: %s\n" % args.repo)
        return 2
    errs = update_options(args)  # before the lock, so that an invalid call creates nothing
    if errs:
        return set_emit(args, invalid_args(args.lang, errs))
    try:
        with Lock(g):
            g.deadline = time.monotonic() + BUDGET_S  # the budget of the git calls starts when the lock is held
            v = update_set(g, args)
    except LockTimeout:
        v = set_deny(args.lang, "LOCK_TIMEOUT", T(args.lang, "lock", s=os.environ.get("MAGOS_LOCK_TIMEOUT", int(LOCK_S))))
    return set_emit(args, v)


def worktree_dirty(g, wt):
    """Has the worktree uncommitted changes?  A status that git cannot produce counts as dirty; a git that cannot run at all raises."""
    rc, out = g.run("status", "--ignore-submodules=none", "--porcelain=v2", "-z", "--untracked-files=all", "--ignored=no", cwd=wt, ok=None)
    return rc != 0 or bool(parse_status(out))


def release_set(g, args):
    """set-release inside the claim lock -> the result dict.  The predicate is the one `release` uses for a claim, against the target of the
    record, for every lane and for the integration branch (`integration`): unmerged work (its branch exists and is not merged into the tip of the
    local target branch; no branch counts as merged when that branch is gone) and a dirty worktree; without --abandon every lane must also be
    integrated.  Nothing is written while anything blocks."""
    lang, name = args.lang, args.set
    rec, denial = set_lookup(g, args)
    if denial:
        return denial
    claims, bad = read_claims(g)
    heads, wts = list_refs(g)[0], worktrees(g)
    tip = heads.get(rec["target"])
    merged = {x for x in g.text("for-each-ref", "--merged=" + tip, "--format=%(refname)", "refs/heads").split("\n") if x} if tip else set()
    items, root = [], os.path.join(store(g), "claims")
    for lane in rec["lanes"]:
        lid, branch = lane["id"], real_branch(lane, heads)
        if not args.abandon and lane["state"] != "integrated":
            items.append((lid, "NOT_INTEGRATED", T(lang, "set_why_state", l=lid, st=lane["state"])))
        if branch is not None and "refs/heads/" + branch not in merged:
            items.append((lid, "UNMERGED_WORK", T(lang, "set_why_unmerged", l=lid, b=branch)))
        for w in lane_worktrees(wts, lane, branch, missing=True):  # the predicate of release: a worktree missing on disk is not known to be clean
            if w["prunable"] or worktree_dirty(g, w["path"]):
                items.append((lid, "DIRTY_WORKTREE", T(lang, "set_why_wt_missing" if w["prunable"] else "set_why_dirty", l=lid, w=w["path"].replace("\\", "/"))))
                break
    ib = real_branch({"branch": integration_branch(name)}, heads)  # the integration branch: the predicate of release, and no state
    if ib is not None and "refs/heads/" + ib not in merged:
        items.append(("integration", "UNMERGED_WORK", T(lang, "set_why_unmerged", l="integration", b=ib)))
    for w in [w for w in wts if ib is not None and not w["bare"] and w["branch"] == ib]:  # every worktree on it, a prunable one included
        if w["prunable"] or worktree_dirty(g, w["path"]):
            items.append(("integration", "DIRTY_WORKTREE", T(lang, "set_why_wt_missing" if w["prunable"] else "set_why_dirty", l="integration",
                                                             w=w["path"].replace("\\", "/"))))
            break
    for lid, branch in [(x["id"], x["branch"]) for x in rec["lanes"]] + [("integration", integration_branch(name))]:
        rel = os.path.normcase(os.path.join(*branch.split("/")) + ".claim")
        if newer_claim(bad, branch) or any(os.path.normcase(b) == rel for b in bad):  # it cannot be read, so it cannot be known to be the set's own
            items.append((lid, "CLAIM_UNUSABLE", T(lang, "set_why_claim", l=lid)))
    if items:
        return refuse16(lang, "set-release", items)
    warns, deletes, released = [], [], []
    for branch in [x["branch"] for x in rec["lanes"]] + [integration_branch(name)]:
        doc = claims.get(fold(branch))
        if doc is None:
            continue
        path = in_store(root, claim_path(g, doc["branch"]))
        if claim_set(doc) != name or fold(doc["branch"]) != fold(branch) or path is None or not os.path.isfile(path) or not os.path.samefile(path, doc["file"]):
            warns.append({"code": "CLAIM_NOT_REMOVED", "text": "the claim of %s does not belong to set %s (or does not lie at its own path) and was left in place" % (branch, name)})
            continue
        deletes.append((path, _file_bytes(path)))
        released.append(doc["branch"])
    record = set_path(g, name)
    line = audit_line(g, op="set-release", set=name, revision=rec["revision"], reason=args.reason, abandon=args.abandon, lanes=[x["id"] for x in rec["lanes"]],
                      claims=released, host="cli")
    commit_store([], deletes + [(record, _file_bytes(record))])  # the claims first, the record last: one transaction
    audit_after(g, line, warns)
    lines = [T(lang, "set_released", s=name, n=len(released))] + ["(%s) %s" % (w["code"], w["text"]) for w in warns]
    return {"decision": "allow", "code": "OK", "set": name, "abandoned": args.abandon, "released": released, "warnings": warns, "message": "\n".join(lines)}


def cmd_set_release(args):
    g = open_repo(args.repo)
    if g is None:
        sys.stderr.write("not a git repository: %s\n" % args.repo)
        return 2
    errs = [("--set", "FORMAT", why) for why in [set_name_problem(args.set, args.lang)] if why]
    if len(args.reason) > SET_TEXT_MAX:  # the rules of --note: the audit line must be writable once the claims are gone
        errs.append(("--reason", "RANGE", "at most %d characters, not %d" % (SET_TEXT_MAX, len(args.reason))))
    elif _SURROGATE.search(args.reason):
        errs.append(("--reason", "ENCODING", "holds a lone surrogate"))
    elif _CTL.search(args.reason):
        errs.append(("--reason", "FORMAT", "holds a control character"))
    if errs:
        return set_emit(args, invalid_args(args.lang, errs))
    try:
        with Lock(g):
            g.deadline = time.monotonic() + BUDGET_S  # the budget of the git calls starts when the lock is held
            v = release_set(g, args)
    except LockTimeout:
        v = set_deny(args.lang, "LOCK_TIMEOUT", T(args.lang, "lock", s=os.environ.get("MAGOS_LOCK_TIMEOUT", int(LOCK_S))))
    return set_emit(args, v)


# ---------------------------------------------------------------- host hooks (L1)
def host_off():
    """MAGOS_GUARD=off in the HOST hook process environment (an agent's tool environment cannot reach it) silences the host hooks."""
    return os.environ.get("MAGOS_GUARD", "").lower() in ("off", "0", "false")


def guard_mode(g, host=True):
    """armed | auto | off.  MAGOS_GUARD=off is read from the HOST hook process environment only (an agent's tool environment cannot reach it)."""
    if host and host_off():
        return "off"
    return _memo(("mode", g.common), lambda: "off" if (cfg(g, "magos.guard") or "").lower() == "off" else
                 "armed" if os.path.exists(os.path.join(store(g), "ARMED")) else "auto")


def parallel(g, cwd_top):
    """AUTO engagement for branch-only and auto-named creations: another lane exists (an open claim, an unmerged branch, another dirty worktree).
    A snapshot that hides lanes (more unmerged local branches than it analyses, or remote-tracking branches beyond the ones it analyses)
    counts as engaged.  -> (engaged, failure): failure is the error that kept the comparison from deciding, and engaged is then whether an
    open claim exists.  Once per repository and worktree within a hook call."""
    return _memo(("parallel", g.common, pkey(cwd_top or "")), lambda: _parallel(g, cwd_top))


def _parallel(g, cwd_top):
    claims, bad = read_claims(g)
    newer = any(b.code == "CLAIM_NEWER_FORMAT" for b in bad)  # a claim this guard cannot read is still an open claim
    try:
        snap = gather(g)
    except (Uncertain, GitFail) as err:
        return bool(claims) or newer, err
    if any(u["code"] == "TOO_MANY_CLAIMANTS" for u in snap["unknowns"]) or any(w["code"] == "REMOTE_TRUNCATED" for w in snap["warnings"]):
        return True, None  # the lanes the snapshot leaves out are other lanes
    if newer or any(not is_idle(d, snap["heads"], snap["merged"], snap["wt_branches"], snap["target"]["sha"]) for d in claims.values()):
        return True, None
    wts = {pkey(w["path"]): w for w in worktrees(g)}
    here = wts.get(pkey(cwd_top or ""))
    own = (lane_key(here["branch"]) if here and here["branch"] else "wt:" + pkey(cwd_top or ""))
    return any(c["key"] != own and (c["paths"]["committed"] or c["paths"]["uncommitted"]) for c in snap["claimants"]), None


def lane_signal(g, cwd_top):
    """A sign of another lane that needs no integration target: an open claim (also one of a newer format), a local branch other than the
    one checked out in the worktree the creation runs from, or a second worktree."""
    if holds_claims(g):
        return True
    wts = [w for w in worktrees(g) if not w["bare"]]
    if len(wts) > 1:
        return True
    here = next((w for w in wts if pkey(w["path"]) == pkey(cwd_top or "")), None)
    return any(b != (here or {}).get("branch") for b in list_refs(g)[0])


def check_creation(g, name, cr, lang, mode):
    """-> None (allow) or a deny verdict for creating branch `name`."""
    claims, bad = read_claims(g)
    doc, newer = claims.get(fold(name)), newer_claim(bad, name)
    if newer is not None:  # the lane's own claim is of a newer format: its manifest cannot be read, and plan cannot replace it
        return deny("UNKNOWN", unknowns=[{"code": "CLAIM_NEWER_FORMAT", "text": newer.text}])
    if not doc:
        return deny("NO_MANIFEST")
    if cr.get("path") and doc["worktree"] and pkey(cr["path"]) != pkey(doc["worktree"]):
        return deny("UNPLANNABLE", message=T(lang, "path_mismatch", b=name, want=doc["worktree"], got=cr["path"]))
    if is_integration_claim(doc):  # the whole of a set: judged for its claim and its name only, so no manifest, commit or unknown of the judgement denies it
        reason = check_name(g, name, {k: d for k, d in claims.items() if k != fold(name)}, True)
        return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [BRANCH_NAME] %s: %s" % (name, reason))) if reason else None
    try:
        entries = [parse_entry(r) for r in doc["entries"]]
    except ManifestError:
        return deny("UNKNOWN", unknowns=[{"code": "CLAIM_UNPARSEABLE", "text": name}])
    target = (doc["target"] or None) if claim_set(doc) else None  # a lane of a set is judged against the target set-plan proved it against
    v = plan_core(g, name, entries, False, False, lang, target_arg=target, stored=True)  # the claim exists: a name the alias rule refuses still allows its branch
    if v["code"] == "BRANCH_EXISTS":
        return None
    return v if v["decision"] == "deny" and v.get("fingerprint") != doc["override"] else None


def enforce(crs, default_cwd, lang):
    """-> None (allow) or (code, message) for the first creation that is denied.  Records of one creation that several states lead to are
    judged once per distinct repository."""
    seen = set()
    for cr in crs:
        res = judge_creation(cr, default_cwd, lang, seen)
        if res:
            return res
    return None


def _existing(path):
    """The nearest existing directory at or above `path` (where git looks for the repository of a directory that does not exist yet)."""
    while path and not os.path.isdir(path):
        up = os.path.dirname(path)
        if up == path:
            return None
        path = up
    return path


def judge_creation(cr, default_cwd, lang, seen=None):
    """One creation, judged in its own repository: the --git-dir / GIT_DIR / GIT_COMMON_DIR target when it has one, else the directory the
    shell is in at that point (the prior directory after a cd to a missing directory, then marked unresolved, unless an earlier element of
    the same && chain created that directory), else the session directory.  `seen` holds the (repository, creation) keys already judged."""
    cwd = cr["cwd"]
    follow = getattr(cwd, "follow", None)
    if follow and follow[0] == "new" and (not cr.get("redirect") or (cr.get("gitdir") and (pkey(cr["gitdir"]) + os.sep).startswith(pkey(str(cwd)) + os.sep))):
        return None  # a repository the same && chain created holds no lane (a redirect counts only when it names a git directory inside it)
    unresolved = isinstance(cwd, _Missing) and not follow
    if cr.get("anywhere"):  # the hook cannot tell which repository the command acts on: refused unless the session repository's guard is off
        if host_off():
            return None
        g = open_repo(default_cwd)
        return None if g is not None and guard_mode(g) == "off" else ("UNPARSEABLE", T(lang, "unparse_git", why=cr["why"]))
    if cr.get("redirect"):
        if host_off():
            return None
        g = open_gitdir(cr["gitdir"]) if cr["gitdir"] else None
        if g is None:  # git would act on a repository we cannot open: whatever the session repository's mode, refuse
            return "UNPARSEABLE", T(lang, "unparse_git", why=cr["why"]) if cr.get("why") else T(lang, "unparse_redirect")
    elif follow:  # the && chain entered a directory it made: git finds the repository of the worktree's repository / the nearest ancestor
        g = open_repo(follow[1] if follow[0] == "wt" else _existing(follow[1]))
    else:
        g = open_repo(cwd.prior if unresolved else (cwd or default_cwd))
    mode = guard_mode(g) if g else "off"
    if mode == "off":
        return None
    key = (pkey(g.common), pkey(g.top or ""), cr["redirect"], cr["verb"], tuple(cr["names"]), cr["kind"], pkey(cr["path"]) if isinstance(cr["path"], str) else None,
           cr["dynamic"], unresolved, cwd is None, cr.get("commit"))
    if seen is not None:
        if key in seen:
            return None
        seen.add(key)
    if cr["verb"] == "wt-detached" and cr["commit"]:  # `worktree add <path> <existing branch or remote-only name>` is not a detached lane
        heads, remotes, _ = list_refs(g)
        if cr["commit"] in heads or any(r.split("/", 1)[-1] == cr["commit"] for r in remotes):
            return None
    if cr["verb"] == "dwim":  # `switch <name>` / `worktree add <path> <name>` create a branch only for a remote-only name
        heads, remotes, _ = list_refs(g)
        cr = dict(cr, names=[n for n in cr["names"] if n not in heads and any(r.split("/", 1)[-1] == n for r in remotes)])
        if not cr["names"] or cr["dynamic"]:
            return None
    engaged = mode == "armed" or cr["kind"] == "worktree"
    if not engaged:
        engaged, failure = parallel(g, g.top)
        if failure is not None:  # the comparison could not decide: warn; an auto-named creation follows a lane signal that needs no target
            why = "%s: %s" % (getattr(failure, "code", "TARGET_UNCERTAIN"), failure)
            if cr["kind"] == "auto":
                try:
                    engaged = lane_signal(g, g.top)
                except (GitFail, Uncertain):
                    engaged = True
                then = "undecided_auto" if engaged else "undecided_auto_allow"
            else:
                then = "undecided_claims" if engaged else "undecided_allow"
            sys.stderr.write(T(lang, "undecided", why=why, then=T(lang, then)) + "\n")
            if cr["kind"] == "auto" and engaged:
                return "UNPLANNABLE", T(lang, "unplannable", why=cr["verb"]) + "\n[%s]" % why
    if not engaged:
        return None
    if cr["dynamic"] or unresolved or (cwd is None and not cr["tool"]):
        if cr["kind"] == "auto":
            return "UNPLANNABLE", T(lang, "unplannable", why=cr["verb"])
        why = cr.get("why") or ("the cd target %s does not exist, so the command would run in %s" % (cwd, cwd.prior) if unresolved else
                                "the cd / -C target or the branch name is dynamic")
        return "UNPARSEABLE", T(lang, "unparse_git", why=why)
    heads = list_refs(g)[0]
    for n in cr["names"]:
        if n in heads:  # an existing branch is switched to or reset, not created
            continue
        try:
            v = check_creation(g, n, cr, lang, mode)
        except GitFail as err:
            v = deny("UNKNOWN", unknowns=[{"code": err.code, "text": str(err)}]) if mode == "armed" or cr["kind"] == "worktree" else None
        if v:
            note_denial(g, n, v)  # the override dialog names the branches of this denial
            if v["code"] == "NO_MANIFEST" and (cr.get("redirect") or cr["verb"] == "push"):  # the creation is in another repository: the plan command names it
                v["message"] = T(lang, "nomanifest", b=n) + "\n" + T(lang, "how_plan", cmd='%s --repo "%s"' % (guard_cmd(), repo_dir(g)), b=n)
            return v["code"], v.get("message") or render(lang, v, n)
    if cr["kind"] == "auto" and not cr["names"]:
        return "UNPLANNABLE", T(lang, "unplannable", why=cr["verb"])
    return None


def repo_dir(g):
    """The directory to pass as --repo: the work tree, else the directory that holds a .git directory, else the git directory itself."""
    return (g.top or (os.path.dirname(g.common) if os.path.basename(g.common).lower() == ".git" else g.common)).replace("\\", "/")


def load_aliases(g):
    return {k[6:]: v for k, _, v in (ln.partition(" ") for ln in g.text("config", "--get-regexp", r"^alias\.", ok=(0, 1)).splitlines())}


def tamper_roots():
    """The absolute directories (pkey form) that hold the guard itself outside any repository: the guard home, and the Hermes plugin
    directory when it holds a launcher (the Hermes entry may run that launcher)."""
    roots = [pkey(guard_home())]
    plugin = os.path.join(hermes_home(), "plugins", "magos")
    if os.path.isfile(os.path.join(plugin, "hooks", "run-guard.cmd")):
        roots.append(pkey(os.path.abspath(plugin)))
    return roots


# ---------------------------------------------------------------- approval (1.0.7): the user's click in Claude Code's dialog for a user-only command
def approval_level(g):
    """-> (level, raw value): the repository's own magos.approval, read like magos.guard (git config --local; git's last value of a key that has
    several) and compared without regard to case and surrounding blanks.  Unset, and no repository, is prompt; any other value terminal.  A
    GitFail propagates: the hook then denies."""
    raw = cfg(g, "magos.approval") if g is not None else None
    if raw is None:
        return "prompt", None
    v = raw.strip().lower()
    return (v if v in APPROVAL_LEVELS else "terminal"), raw


def this_guard(path):
    """Is `path` this guard: the running file, or a file with the same bytes (such as the copy under the guard home)?"""
    me = os.path.abspath(__file__)
    if same_file(path, me):
        return True
    data = read_quiet(path) if os.path.isfile(path) else None
    return data is not None and data == read_quiet(me)


def _interpreter_problem(word, cwd):
    """The cause code when the first word of a direct invocation is no interpreter the hook may name, else None.  Accepted: a bare py, python,
    python3 or python3.<n>, optionally with .exe, which on Windows resolves (in the hook's PATH) to an .exe, not to a .bat or .cmd shim that
    would hand the quoted arguments to cmd.exe; or a path to the interpreter that runs the hook.  The guard or its launcher as the first word,
    a prefix assignment and a wrapper are no interpreter.  `cwd` None: the call names no directory (Hermes approval), so a relative path is
    APPROVAL_DIRECTORY."""
    if _guard_word(word):
        return "APPROVAL_SHAPE"
    if re.search(r"[\\/]", word) or word.startswith("~"):
        p = _norm_path(word)
        if not _rooted(p) and cwd is None:
            return "APPROVAL_DIRECTORY"
        return None if same_file(p if _rooted(p) else os.path.join(cwd, p), sys.executable) else "APPROVAL_INTERPRETER"
    if not _INTERPRETER.fullmatch(word):
        return "APPROVAL_SHAPE"
    if sys.platform == "win32" and not (shutil.which(word) or "").lower().endswith(".exe"):
        return "APPROVAL_INTERPRETER"
    return None


def approval_invocation(payload, cwd, tools=None):
    """-> (invocation, None) or (None, cause code): is the command of a Bash or PowerShell call exactly one direct invocation of this guard
    (Approval, Recognition 1 to 4)?  One command of the tool's dialect with nothing around it, no redirection and no dynamic word; an interpreter
    (_interpreter_problem) and only the interpreter options -3, -3.<n> (-32, -64), -B, -E, -I, -s, -u, -X utf8 and -Xutf8; then a word that
    names this guard (this_guard), joined to the session directory when it is relative.  The invocation: "sh" (the tool's shell), "words" (the
    interpreter, its options and the absolute script path, which the rewritten command quotes), "args" (the guard's arguments, none of them
    `--`) and "text" (the command as the payload holds it).  `tools` maps a tool to its dialect (default: Claude Code's Bash and PowerShell);
    `cwd` None means the call names no directory (Hermes approval): a relative script or interpreter path is then APPROVAL_DIRECTORY."""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    sh, c = (_APPROVAL_TOOLS if tools is None else tools).get(tool), ti.get("command")
    if sh is None or not isinstance(c, str):
        return None, "APPROVAL_TOOL"
    text = c.strip(" \t\r\n")
    if len(text) > MAX_TEXT or _CTL.search(text.replace("\t", " ")) or _SURROGATE.search(text):
        return None, "APPROVAL_SHAPE"
    ev = _lex(text, sh)
    if len(ev) != 1 or not isinstance(ev[0], _Seg) or ev[0].sub or any(isinstance(w, _Redir) for w, _d in ev[0]):
        return None, "APPROVAL_SHAPE"
    if any(d for _w, d in ev[0]):
        return None, "APPROVAL_DYNAMIC"
    ws = [w for w, _d in ev[0]]
    cause = _interpreter_problem(ws[0], cwd)
    if cause:
        return None, cause
    k = 1
    while k < len(ws) and ws[k].startswith("-"):
        if ws[k] == "-X" and ws[k + 1:k + 2] == ["utf8"]:
            k += 2
        elif _INTERP_OPT.fullmatch(ws[k]):
            k += 1
        else:
            return None, "APPROVAL_SHAPE"
    if k == len(ws) or _guard_word(ws[k]) != "script" or "--" in ws[k + 1:]:  # argparse reads a word after `--` otherwise from Python 3.13 on
        return None, "APPROVAL_SHAPE"
    p = _norm_path(ws[k])
    if not _rooted(p) and cwd is None:
        return None, "APPROVAL_DIRECTORY"
    path = p if _rooted(p) else os.path.normpath(os.path.join(cwd, p))
    if not this_guard(path):
        return None, "APPROVAL_SCRIPT"
    return {"sh": sh, "words": ws[:k] + [path.replace("\\", "/")], "args": ws[k + 1:], "text": c}, None


def approval_intact(lead, args, sh, win=None):
    """The cause code when a word cannot reach the guard unchanged through the tool's shell, else None.  `lead`: the interpreter, its options
    and the script; `args`: the guard's arguments.  Windows PowerShell 5.1 drops an empty word, splits or rejoins a word that holds '"' or ends
    with a backslash, and reads --% as its stop-parsing token; Git Bash on Windows rewrites an argument that starts with '/', holds '=/' or
    '@/' or starts with -<letter>/ as a Windows path, and one backslash of a pair away, when it starts a Windows program (the script word is
    a Windows path already)."""
    win = sys.platform == "win32" if win is None else win
    if sh == "ps":
        if any(w == "" or '"' in w or w.endswith("\\") or w == "--%" for w in list(lead) + list(args)):
            return "APPROVAL_POWERSHELL"
    elif win and any(w.startswith("/") or "=/" in w or "@/" in w or "\\\\" in w or re.match(r"-[A-Za-z]/", w) for w in args):
        return "APPROVAL_PATHCONV"
    return None


def approval_target(ns, row, cwd):
    """-> the cause code APPROVAL_REPO, or where the approval of a parsed invocation lives: {"g": the repository the command names (its --repo
    joined to the session directory, else the session directory; None outside one), "level": its magos.approval (approval_level), "root": the
    approval store, "where": the repository's common directory or the default guard home, "dest": the guard home install copies to}.  The
    command computes the same store from the same inputs: its --repo is read in the directory the tool's shell runs it in.  `cwd` None (a
    Hermes call without workdir, whose paths are absolute): the repository is the one --repo names, none without it."""
    if cwd is None:
        g = open_repo(ns.repo) if ns.repo is not None else None
    else:
        g = open_repo(cwd if ns.repo is None else os.path.join(cwd, ns.repo))
    if row.scope == "repo":
        if g is None:
            return "APPROVAL_REPO"
        root, where, dest = os.path.join(store(g), "approvals"), g.common, None
    else:  # install: the default guard home holds the store whatever --home says; --home names only where install copies
        root, where = os.path.join(guard_home(), "approvals"), guard_home()
        if cwd is None:
            dest = guard_home(ns.home)
        else:
            dest = os.path.normpath(os.path.join(cwd, os.path.expanduser(ns.home or os.environ.get("MAGOS_HOME") or "~/.magos"))).replace("\\", "/")
    return {"g": g, "level": approval_level(g)[0], "root": root, "where": where, "dest": dest}


def approval_command(sh, words, token):
    """The command the user approves: the words of the invocation, each quoted for the tool's shell, then --approval=<token> (one word, so a
    token that starts with '-' stays the option's value).  Bash: a word of letters, digits and _ @ % + = : , . / - stays bare, every other
    word is single-quoted; PowerShell: `& ` and every word single-quoted."""
    ws = list(words) + ["--approval=" + token]
    if sh == "ps":
        return "& " + " ".join(ps_quote(w) for w in ws)
    return " ".join(w if _BARE_SH.fullmatch(w) else sh_quote(w) for w in ws)


_QUOTE_LIKE = frozenset("＂＇«»‹›`´" + "".join(chr(c) for c in range(0x2018, 0x2020)))


def _dialog(text, limit):
    """An agent-controlled value as the dialog shows it: a JSON string of its NFKC form in which every control, format (the bidirectional
    controls among them), surrogate, line and paragraph separator character and every quotation mark but the ASCII '"' (categories Pi and Pf,
    U+2018 to U+201F, the fullwidth quotes, the guillemets, the backtick and the acute accent) is a space and a run of blanks is one, cut to
    `limit` characters.  The ASCII '"' is escaped as \\", so the value cannot end its quotes early or start a line of the guard."""
    s = unicodedata.normalize("NFKC", str(text))
    s = " ".join("".join(" " if ch in _QUOTE_LIKE or unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Zl", "Zp", "Pi", "Pf") else ch for ch in s).split())
    return json.dumps(s if len(s) <= limit else s[:limit - 1] + "…", ensure_ascii=False)


def approval_text(lang, row, ns, t, auto):
    """permissionDecisionReason: what the click approves (approval_what) and that the click is the approval."""
    return T(lang, "approval_auto" if auto else "approval_ask", sub=row.name, what=approval_what(lang, row, ns, t))


def approval_what(lang, row, ns, t):
    """What a click approves, the {what} of every route's question (Approval routes): every subcommand its dry run; arm, disarm and override
    the repository; install the host, the directory it copies from (that of this guard), the destination and an --allow-downgrade; override
    also the fingerprint, the lane and target and the conflicting branches of its denial record (at most six, then +<n> more) and the reason,
    marked as written by the agent.  `t`: {"g": the repository or None, "dest": the guard home install copies to}."""
    dry = T(lang, "approval_dry") if getattr(ns, "dry_run", False) else ""
    repo = _dialog(repo_dir(t["g"]), 200) if t["g"] is not None else ""
    if row.name == "override":
        rec = denial_record(t["g"], ns.fingerprint)
        if rec is None:
            denied = T(lang, "approval_no_record")
        else:
            b = rec["branches"]
            names = ", ".join(_dialog(x, 80) for x in b[:6]) + (" " + T(lang, "show_more", n=len(b) - 6) if len(b) > 6 else "")
            denied = T(lang, "approval_denied", lane=_dialog(rec["lane"], 80), target="-" if rec["target"] is None else _dialog(rec["target"], 80),
                       branches=names)
        what = T(lang, "approval_what_override", fp=_dialog(ns.fingerprint, 16), repo=repo, denied=denied, reason=_dialog(ns.reason, 160))
    elif row.name == "install":
        src = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")  # guard_files copies the script and the launcher from here
        what = T(lang, "approval_what_install", src=_dialog(src, 200), home=_dialog(t["dest"] + "/guard", 200), host=ns.host, dry=dry,
                 down=T(lang, "approval_downgrade") if getattr(ns, "allow_downgrade", False) else "")
    else:
        what = T(lang, "approval_what_" + row.name, repo=repo, dry=dry)
    return what


def _carries_approval(text):
    """Does the command name --approval anywhere, as written or with every escape character and quote removed?  The whole text is read, so a
    word after `--` (which argparse from Python 3.13 on reads as the end of the global options) counts as well."""
    return any(_APPROVAL_WORD.search(t) for t in (text, _bare(text)))


def _payload_id(v):
    return v[:200] if isinstance(v, str) and v else None


def approval_reentry(payload, cwd):
    """Is the command the hook's own rewritten command of this tool call, which the host runs through its hooks again?  -> "live" when its
    token's record (<sha256>.json, not yet consumed) names the payload's tool_use_id, holds the SHA-256 of exactly this command text and has not
    expired; "expired" for such a record whose expires has passed (the click came too late); None otherwise."""
    tid = payload.get("tool_use_id")
    if not isinstance(tid, str) or not tid:
        return None
    inv, _cause = approval_invocation(payload, cwd)
    last = inv["args"][-1] if inv and inv["args"] else ""
    token = last[len("--approval="):] if last.startswith("--approval=") else ""
    if not _APPROVAL_TOKEN.fullmatch(token):
        return None
    ns = parse_quiet(inv["args"])
    row = user_only_row(ns)
    t = approval_target(ns, row, cwd) if row is not None and ns.approval == token else None
    if not isinstance(t, dict):
        return None
    try:
        rec = json.loads(_read_retry(os.path.join(t["root"], hashlib.sha256(token.encode("ascii")).hexdigest() + ".json")))
        if not (isinstance(rec, dict) and rec.get("tool_use_id") == tid and
                rec.get("command_sha256") == hashlib.sha256(inv["text"].encode("utf-8")).hexdigest()):
            return None
        return "live" if _record_expiry(rec) >= time.time() else "expired"
    except (OSError, ValueError, TypeError, KeyError):
        return None


def approval_answer(payload, cwd, crs, lang):
    """The Claude Code hook's answer to a command in which the tamper filter found a user-only subcommand (Approval): an Approval (ask, or
    allow where magos.approval auto-safe allows the subcommand) that hands the host the command rebuilt with a one-time token, a deny
    (code, message) whose last line names the cause, or None for the hook's own rewritten command run through the hooks again."""
    why = _USER_MSG
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

    def shape(cause):
        return "PROTECTED", T(lang, "protected_shape", why=why, cmd=guard_cmd()) + "\n[%s]" % cause
    if _carries_approval(str(ti.get("command") or "")):  # an agent never supplies a token
        again = approval_reentry(payload, cwd)
        if again == "live":
            return None
        if again == "expired":  # the hook's own command, clicked too late: nothing runs, and the agent is not blamed
            return "PROTECTED", T(lang, "approval_expired")
        return "PROTECTED", T(lang, "approval_given", why=why)
    inv, cause = approval_invocation(payload, cwd)
    if inv is None:
        return shape(cause)
    if crs:
        return shape("APPROVAL_SHAPE")
    probe = "A" * 43  # the shape of a token: the guard's own parser must read the appended word as the approval option
    ns = parse_quiet(inv["args"] + ["--approval=" + probe])
    row = user_only_row(ns) if ns is not None and getattr(ns, "approval", None) == probe else None
    if row is None:
        return shape("APPROVAL_ARGS")
    if row.name == "install" and not same_file(inv["words"][-1], os.path.abspath(__file__)):
        return shape("APPROVAL_SCRIPT")  # install copies the launcher beside the script it runs as: only this very file names a trusted one
    cause = approval_intact(inv["words"], inv["args"], inv["sh"])
    if cause:
        return shape(cause)
    t = approval_target(ns, row, cwd)
    if not isinstance(t, dict):
        return shape(t)
    if t["level"] == "terminal":
        return "PROTECTED", T(lang, "protected_level", why=why)
    auto = t["level"] == "auto-safe" and row.auto_safe and \
        (row.scope != "home" or (pkey(t["dest"]) == pkey(guard_home()) and not getattr(ns, "allow_downgrade", False)))
    now, token = time.time(), secrets.token_urlsafe(32)
    command = approval_command(inv["sh"], inv["words"] + inv["args"], token)
    rec = {"v": 1, "sub": row.name, "argv": inv["args"], "where": t["where"], "via": "auto-safe" if auto else "prompt", "created": now,
           "expires": now + APPROVAL_S, "tool_use_id": _payload_id(payload.get("tool_use_id")), "session_id": _payload_id(payload.get("session_id")),
           "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(), "used": False}
    try:
        prune_approvals(t["root"], now)
        if row.scope == "repo":
            prune_denials(os.path.join(store(t["g"]), "denials"), now)
        write_atomic(os.path.join(t["root"], hashlib.sha256(token.encode("ascii")).hexdigest() + ".json"), json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    except OSError as err:
        return "PROTECTED", T(lang, "approval_unrecorded", why=why, err="%s: %s" % (type(err).__name__, err))
    updated = dict(ti, command=command, description=T(lang, "approval_desc", sub=row.name))
    if auto:  # an allow carries no sandbox escape the user never saw
        updated.pop("dangerouslyDisableSandbox", None)
    return Approval("allow" if auto else "ask", approval_text(lang, row, ns, t, auto), updated)


def _prune(root, now, pattern, grace, age, tmp):
    """Remove from the store `root` every file named by `pattern` whose expires passed more than `grace` seconds ago, one that cannot be read and
    is older than `age` seconds, and, with `tmp`, a temporary file older than `age`.  Files of other names stay; a file that a concurrent prune
    removed, or that cannot be removed, is no error."""
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        p = os.path.join(root, name)
        try:
            if tmp and name.endswith(".tmp"):
                stale = os.path.getmtime(p) + age < now
            elif pattern.fullmatch(name):
                try:
                    stale = _record_expiry(json.loads(_read_retry(p))) + grace < now
                except (OSError, ValueError, TypeError, KeyError):
                    stale = os.path.getmtime(p) + age < now
            else:
                continue
            if stale:
                _remove(p)
        except OSError:
            pass


def prune_approvals(root, now):
    """Every mint first prunes its approval store: a record expired more than APPROVAL_GRACE_S ago, and an unreadable record or temporary file
    older than that.  Until then an expired or used record names its cause."""
    _prune(root, now, _APPROVAL_FILE, APPROVAL_GRACE_S, APPROVAL_GRACE_S, True)


def prune_denials(root, now):
    """A mint in a repository store also removes the denial records whose expires has passed (an unreadable one older than DENIAL_S)."""
    _prune(root, now, _DENIAL_FILE, 0, DENIAL_S, False)


def note_denial(g, lane, v):
    """Keep the branches a conflict denial names in <store>/denials/<fingerprint>.json for the override dialog (plan in write mode, the host hook
    for a creation); best effort, so a failure changes no verdict and no message."""
    fp, conflicts = v.get("fingerprint"), v.get("conflicts")
    if v.get("decision") != "deny" or not fp or not conflicts:
        return
    now = time.time()
    try:
        rec = {"v": 1, "fp": fp, "lane": lane, "branches": [c["branch"] or "(detached) " + ", ".join(c["worktrees"]) for c in conflicts],
               "target": (v.get("target") or {}).get("name"), "at": now, "expires": now + DENIAL_S}
        write_atomic(os.path.join(store(g), "denials", fp + ".json"), json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass


def denial_record(g, fp):
    """What the live denial record of fingerprint `fp` names -> {"lane", "target" (None when it names none), "branches"}, or None (no
    repository, no such record, or one that has expired, cannot be read or names no lane)."""
    if g is None or not isinstance(fp, str) or not re.fullmatch(r"[0-9a-f]{12}", fp):
        return None
    try:
        rec = json.loads(_read_retry(os.path.join(store(g), "denials", fp + ".json")))
        if rec.get("fp") != fp or not isinstance(rec.get("branches"), list) or not isinstance(rec.get("lane"), str) or \
                _record_expiry(rec) <= time.time():
            return None
        target = rec.get("target")
        return {"lane": rec["lane"], "target": None if target is None else str(target), "branches": [str(b) for b in rec["branches"]]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


# ---------------------------------------------------------------- Codex approval (1.0.8): the MCP approval server and the Codex hook's route
MCP_TOOL_SPEC = {
    "name": MCP_TOOL,
    "title": "MAGOS approval",
    "description": "Ask the user, in the host's own approval dialog, to approve one MAGOS user-only guard command (override, arm, disarm or "
                   "install), and run it after the user ticks Approve and accepts. Call it with the arguments a MAGOS denial names. Nothing runs "
                   "without that: a decline, a cancel, an Accept without Approve or a dialog the host cannot show runs nothing.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "subcommand": {"type": "string", "enum": ["override", "arm", "disarm", "install"], "description": "The user-only guard subcommand."},
            "repo": {"type": "string", "description": "The absolute path of the repository. Required for override, arm and disarm; for install the "
                                                      "repository whose magos.approval applies (optional)."},
            "fingerprint": {"type": "string", "pattern": "^[0-9a-f]{12}$", "description": "override: the 12 hex digits the denial printed."},
            "reason": {"type": "string", "description": "override: the user's words; the dialog shows them as written by the agent."},
            "host": {"type": "string", "enum": ["claude", "codex", "hermes"], "description": "install: the host whose hook entry install prints."},
            "dry_run": {"type": "boolean", "description": "arm, disarm, install: only print what would be written; the user still approves it."},
        },
        "required": ["subcommand"],
        "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
}
_OVERSIZE = object()  # the reader's mark of a line longer than MCP_LINE


class _HostGone(Exception):
    """stdout of the MCP approval server cannot be written: the host is gone."""


def _abs_dir(p):
    """The absolute directory `p` names, normalised with / separators, or None: a drive or UNC path on Windows (a Git Bash /c/... spelling
    mapped), a /-rooted path elsewhere; never relative, drive-relative or ~, never longer than MAX_DIR, and existing.  Never os.path.isabs,
    whose Windows result changed in Python 3.13."""
    if not isinstance(p, str) or not p or p.startswith("~"):
        return None
    q = _norm_path(p)
    rooted = re.match(r"[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/][^\\/]", q) if os.name == "nt" else q.startswith("/")
    if not rooted or len(q) > MAX_DIR:
        return None
    q = os.path.normpath(q)
    return q.replace("\\", "/") if os.path.isdir(q) else None


def _client_name(info):
    """`clientInfo` as an audit field: name/version (the name alone without a version), control characters as spaces, at most 80 characters;
    None when it names no client."""
    if not isinstance(info, dict) or not isinstance(info.get("name"), str) or not info["name"]:
        return None
    v = info.get("version")
    return _shown(info["name"] + ("/" + v if isinstance(v, str) and v else ""), 80)


def mcp_validate(arguments, lang):
    """-> ({"row", "args", "argv", "repo", "g", "ns"}, None) or (None, [error lines]): the arguments of one magos_approve call checked as the guard
    checks a command (Codex approval, The tool call 1 and 2).  The command line is built from single-word --option=value forms and read back by
    the guard's own parser, which must give back the row, a probe approval word and every value."""
    if not isinstance(arguments, dict):
        return None, ["the arguments are not a JSON object"]
    errors = ["%s: not an argument of magos_approve" % _shown(str(k), 40) for k in arguments if k not in MCP_ARGS]
    sub = arguments.get("subcommand")
    row = next((u for u in USER_ONLY if u.name == sub), None) if isinstance(sub, str) else None
    if row is None:
        return None, errors + ["subcommand: override, arm, disarm or install"]
    takes = _MCP_TAKES[sub]
    errors += ["%s: %s takes no %s" % (k, sub, k) for k in MCP_ARGS[1:]
               if k in arguments and k not in takes and not (k == "dry_run" and arguments[k] is False)]
    for k in ("repo", "fingerprint", "reason", "host"):
        v = arguments.get(k)
        if k not in arguments or k not in takes:
            continue
        if not isinstance(v, str):
            errors.append("%s: not a string" % k)
        elif len(v) > MCP_FIELD:
            errors.append("%s: longer than %d characters" % (k, MCP_FIELD))
        elif _CTL.search(v.replace("\t", " ")) or _SURROGATE.search(v):
            errors.append("%s: holds a control character or a lone surrogate" % k)
    if "dry_run" in arguments and not isinstance(arguments["dry_run"], bool):
        errors.append("dry_run: true or false")
    path, g = None, None
    if "repo" in arguments:
        if isinstance(arguments["repo"], str) and not [e for e in errors if e.startswith("repo:")]:
            path = _abs_dir(arguments["repo"])
            if path is None:
                errors.append("repo: not the absolute path of an existing directory")
            else:
                try:
                    g = open_repo(path)
                except GitFail as err:
                    errors.append("repo: %s: %s" % (err.code, _shown(str(err), 200)))
                if g is None and row.scope == "repo" and not [e for e in errors if e.startswith("repo:")]:
                    errors.append("repo: not a git repository")
    elif row.scope == "repo":
        errors.append("repo: required for %s" % sub)
    fp, reason, host = arguments.get("fingerprint"), arguments.get("reason"), arguments.get("host")
    if sub == "override":
        if "fingerprint" not in arguments:
            errors.append("fingerprint: required for override")
        elif isinstance(fp, str) and not re.fullmatch(r"[0-9a-f]{12}", fp):
            errors.append("fingerprint: the 12 lowercase hex digits a denial prints")
        if "reason" not in arguments:
            errors.append("reason: required for override")
        elif isinstance(reason, str) and not reason.strip():
            errors.append("reason: empty")
    if sub == "install":
        if "host" not in arguments:
            errors.append("host: required for install")
        elif isinstance(host, str) and host not in HOSTS:
            errors.append("host: claude, codex or hermes")
    if errors:
        return None, errors
    dry = arguments.get("dry_run") is True
    argv = ([] if sub == "install" else ["--repo=" + path]) + ["--lang=" + lang, sub]  # install's repo names only the level
    if sub == "override":
        argv += ["--fingerprint=" + fp, "--reason=" + reason]
    elif sub == "install":
        argv += ["--host=" + host]
    argv += ["--dry-run"] if dry else []
    probe = "A" * 43
    ns = parse_quiet(argv + ["--approval=" + probe])
    back = ns is not None and user_only_row(ns) == row and getattr(ns, "approval", None) == probe and ns.lang == lang and \
        ns.repo == (None if sub == "install" else path) and \
        getattr(ns, "fingerprint", fp) == fp and getattr(ns, "reason", reason) == reason and getattr(ns, "host", host) == host and \
        getattr(ns, "dry_run", False) == dry
    if not back:
        return None, ["the guard's parser reads these arguments otherwise"]
    args = dict((k, v) for k, v in (("subcommand", sub), ("repo", path), ("fingerprint", fp if sub == "override" else None),
                                    ("reason", reason if sub == "override" else None), ("host", host if sub == "install" else None),
                                    ("dry_run", True if dry else None)) if v is not None)
    return {"row": row, "args": args, "argv": argv, "repo": path, "g": g, "ns": ns}, None


def ready_command(argv, lang="en"):
    """The guard command the user runs in a real terminal for the command line `argv` (Codex approval, The tool call 7): guard_cmd() and each
    word bare when the user's shell reads it as itself, else single-quoted for PowerShell on Windows and for sh elsewhere.  On Windows a word
    that holds '"', or a blank and a trailing backslash, would not reach the guard unchanged through Windows PowerShell 5.1, which wraps a
    word with a blank in double quotes without escaping it: such a word keeps its option name and shows the ready_own text in place of its
    value, which the user replaces with their own words."""
    win = sys.platform == "win32"
    bare, quote = (_BARE_PS, ps_quote) if win else (_BARE_SH, sh_quote)
    out = []
    for w in argv:
        if win and ('"' in w or (re.search(r"\s", w) and w.endswith("\\"))):
            w = (w.split("=", 1)[0] + "=" if w.startswith("--") and "=" in w else "") + T(lang, "ready_own")
        out.append(w if bare.fullmatch(w) else quote(w))
    return guard_cmd() + "".join(" " + w for w in out)


def _named_invocation(text, sh):
    """The guard's own reading (parse_quiet) of the words after the first guard script word that a user-only subcommand follows in a command of
    `text` (read in the dialect `sh`), or None: no such command, a dynamic word among its arguments, or words the parser refuses."""
    if not text or len(text) > MAX_TEXT:
        return None
    for ev in _lex(_heredocs(text)[0], sh):
        if not isinstance(ev, _Seg):
            continue
        words = [w for w, _d in ev]
        for i, w in enumerate(words):
            if _guard_word(w) == "script" and _guard_sub(words[i + 1:], False) in _USER_ONLY:
                if any(d for _w, d in ev[i + 1:]):
                    return None
                rest, k = [], i + 1
                while k < len(words):  # a redirection of the shell is no argument of the guard
                    if isinstance(words[k], _Redir):
                        k += words[k].take
                        continue
                    rest.append(words[k])
                    k += 1
                ns = parse_quiet(rest)
                return ns if ns is not None and user_only_row(ns) is not None else None
    return None


def mcp_arguments(ns, cwd):
    """The magos_approve arguments that run what a parsed user-only invocation names in the session directory `cwd` (Codex approval, The Codex
    hook), or None when it names what the tool does not take (install's --home or --allow-downgrade).  --lang, --json and an --approval value
    are dropped; a relative --repo is joined to `cwd`, and without --repo `cwd` is the repository (for install only when it lies in one)."""
    if getattr(ns, "home", None) or getattr(ns, "allow_downgrade", False):
        return None
    named = _join(cwd, ns.repo) if ns.repo is not None else cwd
    if not named:
        return None
    a = {"subcommand": ns.cmd}
    if ns.cmd != "install" or ns.repo is not None or open_repo(cwd) is not None:
        a["repo"] = os.path.normpath(named).replace("\\", "/")
    if ns.cmd == "override":
        a.update(fingerprint=ns.fingerprint, reason=ns.reason)
    if ns.cmd == "install":
        a["host"] = ns.host
    if getattr(ns, "dry_run", False):
        a["dry_run"] = True
    return a


def codex_denial(payload, cwd, lang):
    """The Codex hook's text for a user-only command (Codex approval, The Codex hook): protected_codex with the magos_approve arguments that run
    exactly what the command names and the ready command, protected_codex_form when its words do not map onto the tool, and under Codex's
    approval policy never (permission_mode bypassPermissions, where Codex declines the dialog by itself) protected_codex_never.  The deny itself
    never depends on the mapping."""
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    v = None
    try:
        text, sh = shell_command(payload)
        if os.name == "nt" and isinstance(ti.get("command"), str):  # Codex runs a string command through powershell.exe -Command on Windows
            sh = "ps"
        ns = _named_invocation(text, sh)
        a = mcp_arguments(ns, cwd) if ns is not None else None
        v = mcp_validate(a, lang)[0] if a is not None else None
    except Exception:  # the text falls back to the form the tool takes; the call is denied either way
        v = None
    if payload.get("permission_mode") == "bypassPermissions":
        ready = ready_command(v["argv"], lang) if v is not None else guard_cmd() + (" <子命令> <选项>" if lang == "zh" else " <subcommand> <options>")
        return T(lang, "protected_codex_never", why=_USER_MSG, ready=ready)
    if v is None:
        return T(lang, "protected_codex_form", why=_USER_MSG, cmd=guard_cmd())
    return T(lang, "protected_codex", why=_USER_MSG, call=json.dumps(v["args"], ensure_ascii=True), ready=ready_command(v["argv"], lang))


def mcp_plan(arguments, lang, session=None, client=None):
    """-> (plan, None) or (None, [error lines]): the snapshot of one magos_approve call (Codex approval, The tool call 3 to 5), taken once before
    the dialog and never read again after the click: the validated command line, the level, the approval store and `where`, the denial
    directory a mint prunes, the dialog text and the ready command."""
    v, errors = mcp_validate(arguments, lang)
    if errors:
        return None, errors
    row, g = v["row"], v["g"]
    try:
        level = approval_level(g)[0] if g is not None else "prompt"
    except GitFail as err:
        return None, ["repo: magos.approval cannot be read: %s: %s" % (err.code, _shown(str(err), 200))]
    if row.scope == "repo":
        root, where, denials = os.path.join(store(g), "approvals"), g.common, os.path.join(store(g), "denials")
        line = T(lang, "mcp_where_repo", repo=_dialog(os.path.realpath(repo_dir(g)).replace("\\", "/"), 200),
                 common=_dialog(os.path.realpath(g.common).replace("\\", "/"), 200))
    else:
        root, where, denials = os.path.join(guard_home(), "approvals"), guard_home(), None
        line = T(lang, "mcp_where_home", home=_dialog(guard_home(), 200))
    text = T(lang, "mcp_ask", sub=row.name, where=line, what=approval_what(lang, row, v["ns"], {"g": g, "dest": guard_home()}))
    return {"row": row, "argv": v["argv"], "level": "terminal" if level == "terminal" else "prompt", "root": root, "where": where,
            "denials": denials, "text": text, "ready": ready_command(v["argv"], lang), "session": session, "client": client}, None


def mcp_command(argv):
    """The runner of the MCP approval server (Codex approval, The tool call 6): this guard's command line `argv` run by main in this process, with
    an empty stdin and its stdout and stderr captured -> (exit code, text).  No program starts: the guard starts processes only in Git.run."""
    out, err = io.BytesIO(), io.BytesIO()
    held = sys.stdin, sys.stdout, sys.stderr
    fin = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    fout = io.TextIOWrapper(out, encoding="utf-8", errors="replace", write_through=True)
    ferr = io.TextIOWrapper(err, encoding="utf-8", errors="replace", write_through=True)
    sys.stdin, sys.stdout, sys.stderr = fin, fout, ferr
    try:
        code = main(list(argv))
    except SystemExit as stop:  # a usage error of the guard's parser
        code = stop.code if isinstance(stop.code, int) else 2
    finally:
        fout.flush()
        ferr.flush()
        sys.stdin, sys.stdout, sys.stderr = held
    text = (out.getvalue() + err.getvalue()).decode("utf-8", "replace")  # read while the wrappers live: a collected wrapper closes its buffer
    return code, text


def mcp_run(plan, runner):
    """On Accept only: mint the token, write its record into the store of the snapshot and run the snapshot's command line with it -> (output
    text, exit code), or (the error, None) when the record cannot be written.  The token is in no text."""
    token, now, sub = secrets.token_urlsafe(32), time.time(), plan["row"].name
    rec = {"v": 1, "sub": sub, "argv": plan["argv"], "where": plan["where"], "via": "prompt", "created": now, "expires": now + APPROVAL_S,
           "tool_use_id": None, "session_id": plan["session"], "command_sha256": None, "used": False, "route": "mcp", "client": plan["client"]}
    try:
        prune_approvals(plan["root"], now)
        if plan["denials"]:
            prune_denials(plan["denials"], now)
        write_atomic(os.path.join(plan["root"], hashlib.sha256(token.encode("ascii")).hexdigest() + ".json"),
                     json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    except OSError as err:
        return "the approval could not be recorded (%s: %s)" % (type(err).__name__, err), None
    code, out = runner(plan["argv"] + ["--approval=" + token])
    out = out.replace(token, "<redacted>")
    if len(out) > MCP_TEXT:
        out = out[:MCP_TEXT] + "\n... (%d more characters)" % (len(out) - MCP_TEXT)
    return out, code


def mcp_form(lang):
    """The requestedSchema of the dialog (Codex approval, The server): one required boolean `approve` without a default.  A form without a
    required field is accepted by Codex itself under the approval policy never with full disk access; this one it declines by itself."""
    return {"type": "object", "properties": {"approve": {"type": "boolean", "title": "Approve", "description": T(lang, "mcp_approve_field")}},
            "required": ["approve"]}


class McpServer:
    """The MCP approval server of one stdio session (Codex approval, The server): newline-delimited JSON-RPC 2.0 read from `rfile` and written
    to `wfile`, both binary.  A reader thread fills a queue; this thread answers in arrival order and keeps at most one dialog open.  `runner`
    runs an approved command line (mcp_command; tests pass their own)."""

    def __init__(self, rfile, wfile, lang, runner=None):
        self.rfile, self.wfile, self.lang, self.runner = rfile, wfile, lang, runner or mcp_command
        self.inbox, self.caps, self.client, self.pending, self.last = queue.Queue(), {}, None, None, 0

    def serve(self):
        """-> 0 at the end of input (an open dialog then runs nothing), 1 when stdout cannot be written."""
        threading.Thread(target=self._read, daemon=True).start()
        try:
            while True:
                if self.pending is not None and time.monotonic() >= self.pending["deadline"]:  # before every message: none extends the wait
                    self._late()
                wait = None if self.pending is None else max(0.0, self.pending["deadline"] - time.monotonic())
                try:
                    raw = self.inbox.get(timeout=wait)
                except queue.Empty:
                    continue
                if raw is None:
                    return 0
                if raw is _OVERSIZE:
                    self._error(None, -32600, "Invalid Request: the line is longer than %d bytes" % MCP_LINE)
                else:
                    self._handle(raw)
        except _HostGone:
            return 1

    def _read(self):
        try:
            while True:
                line = self.rfile.readline(MCP_LINE + 1)
                if not line:
                    break
                if len(line) > MCP_LINE and not line.endswith(b"\n"):  # skip the rest of a line over the limit
                    while line and not line.endswith(b"\n"):
                        line = self.rfile.readline(MCP_LINE + 1)
                    self.inbox.put(_OVERSIZE)
                    continue
                self.inbox.put(line)
        except (OSError, ValueError):
            pass
        self.inbox.put(None)

    def _send(self, msg):
        try:
            self.wfile.write((json.dumps(msg, ensure_ascii=True) + "\n").encode("ascii"))
            self.wfile.flush()
        except (OSError, ValueError):
            raise _HostGone()

    def _reply(self, ident, result):
        self._send({"jsonrpc": "2.0", "id": ident, "result": result})

    def _error(self, ident, code, text):
        self._send({"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": text}})

    def _result(self, ident, text, approved=False, code=None):
        self._reply(ident, {"content": [{"type": "text", "text": text}], "structuredContent": {"approved": approved, "exit_code": code, "text": text},
                            "isError": code is None or code != 0})

    def _handle(self, raw):
        body = raw.strip()
        if not body:
            return
        try:
            msg = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return self._error(None, -32700, "Parse error")
        ident = msg.get("id") if isinstance(msg, dict) else None
        good_id = isinstance(ident, (str, int)) and not isinstance(ident, bool)
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or ("id" in msg and not good_id and "method" in msg):
            return self._error(None, -32600, "Invalid Request")
        if "method" not in msg:
            return self._answered(msg)  # an answer to the server's own request
        method = msg["method"]
        if not isinstance(method, str):
            return self._error(None, -32600, "Invalid Request")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if "id" not in msg:
            if method == "notifications/cancelled":
                self._cancelled(params)
            return  # every other notification, notifications/initialized among them, needs no answer
        handler = {"initialize": self._initialize, "ping": self._ping, "tools/list": self._list, "tools/call": self._call}.get(method)
        if handler is None:
            return self._error(ident, -32601, "Method not found")
        try:
            handler(ident, params)
        except _HostGone:
            raise
        except Exception as err:  # the request fails, the session goes on; nothing ran
            self._error(ident, -32603, "Internal error: %s" % type(err).__name__)

    def _initialize(self, ident, params):
        caps = params.get("capabilities")
        self.caps, self.client = (caps if isinstance(caps, dict) else {}), _client_name(params.get("clientInfo"))
        v = params.get("protocolVersion")
        self._reply(ident, {"protocolVersion": v if isinstance(v, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v) else MCP_PROTOCOL,
                            "capabilities": {"tools": {}}, "serverInfo": {"name": MCP_SERVER, "version": GUARD_VERSION}})

    def _ping(self, ident, params):
        self._reply(ident, {})

    def _list(self, ident, params):
        self._reply(ident, {"tools": [MCP_TOOL_SPEC]})

    def _form(self):
        """Does the client declare the elicitation form (an elicitation capability that names form, or names neither form nor url)?"""
        e = self.caps.get("elicitation")
        return isinstance(e, dict) and ("form" in e or not any(k in e for k in ("form", "url")))

    def _call(self, ident, params):
        if params.get("name") != MCP_TOOL:
            return self._error(ident, -32602, "Unknown tool: %s" % _shown(str(params.get("name")), 80))
        if self.pending is not None:  # one dialog at a time, nothing queued: Codex does not cancel a call its own timeout ended
            return self._result(ident, T(self.lang, "mcp_busy"))
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        plan, errors = mcp_plan(params.get("arguments", {}), self.lang, _payload_id(meta.get("threadId")), self.client)
        if errors:
            return self._result(ident, T(self.lang, "mcp_invalid", errors="\n".join("  " + e for e in errors)))
        if plan["level"] == "terminal":
            return self._result(ident, T(self.lang, "mcp_terminal", sub=plan["row"].name, ready=plan["ready"]))
        if not self._form():
            return self._result(ident, T(self.lang, "mcp_no_form", ready=plan["ready"]))
        self.last += 1
        self.pending = {"id": ident, "elicit": self.last, "plan": plan, "deadline": time.monotonic() + MCP_CLICK_S}
        self._send({"jsonrpc": "2.0", "id": self.last, "method": "elicitation/create",
                    "params": {"mode": "form", "message": plan["text"], "requestedSchema": mcp_form(self.lang)}})

    def _withdraw(self, eid, why):
        self._send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": eid, "reason": why}})

    def _late(self):
        p, self.pending = self.pending, None
        self._withdraw(p["elicit"], "no answer within %s s" % MCP_CLICK_S)
        self._result(p["id"], T(self.lang, "mcp_late", sub=p["plan"]["row"].name, s=MCP_CLICK_S, ready=p["plan"]["ready"]))

    def _cancelled(self, params):
        p, rid = self.pending, params.get("requestId")
        if p is not None and rid == p["id"] and not isinstance(rid, bool):  # the cancelled call gets no answer
            self.pending = None
            self._withdraw(p["elicit"], "the tool call was cancelled")

    def _answered(self, msg):
        p, rid = self.pending, msg.get("id")
        if p is None or rid != p["elicit"] or isinstance(rid, bool):
            return  # an answer to no open dialog (withdrawn, cancelled or unknown): nothing runs
        self.pending = None
        sub, ready = p["plan"]["row"].name, p["plan"]["ready"]
        res = msg.get("result")
        if "error" in msg or not isinstance(res, dict):
            why = "the dialog ended with an error: %s" % _shown(json.dumps(msg.get("error"), ensure_ascii=True), 200)
            return self._result(p["id"], T(self.lang, "mcp_failed", sub=sub, err=why, ready=ready))
        action = res.get("action")
        if action != "accept":
            shown = _dialog(action, 20) if isinstance(action, str) else '"none"'
            return self._result(p["id"], T(self.lang, "mcp_refused", sub=sub, action=shown, ready=ready))
        content = res.get("content")
        if not (isinstance(content, dict) and content.get("approve") is True):  # Codex checks no answer against the form, and under never
            return self._result(p["id"], T(self.lang, "mcp_unticked", sub=sub, ready=ready))  # accepts an empty form by itself
        try:
            out, code = mcp_run(p["plan"], self.runner)
        except Exception as err:  # before the command ran: nothing ran
            out, code = "%s: %s" % (type(err).__name__, err), None
        if code is None:
            return self._result(p["id"], T(self.lang, "mcp_failed", sub=sub, err=out, ready=ready), approved=True)
        self._result(p["id"], T(self.lang, "mcp_ran", sub=sub, code=code, out=out), approved=True, code=code)


def cmd_mcp(args):
    """The MCP approval server (Codex approval): started by the host, never by a tool command (every host's hook denies that).  Only the
    protocol reaches stdout: for the session sys.stdout is stderr.  Exit 0 at the end of input, 1 when the host cannot be written or the
    server fails."""
    wfile = getattr(sys.stdout, "buffer", sys.stdout)
    held = sys.stdout
    sys.stdout = sys.stderr
    try:
        return McpServer(sys.stdin.buffer, wfile, args.lang).serve()
    except Exception as err:  # never main's fail(), which may write to stdout
        sys.stderr.write("MAGOS mcp server error: %s: %s\n" % (type(err).__name__, err))
        return 1
    finally:
        sys.stdout = held


def mcp_selftest():
    """-> (ok, why): this guard's approval server, in process, answers initialize and tools/list with magos_approve (doctor)."""
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": MCP_PROTOCOL, "capabilities": {}}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    out = io.BytesIO()
    try:
        code = McpServer(io.BytesIO(b"".join(json.dumps(m).encode("ascii") + b"\n" for m in lines)), out, "en").serve()
        got = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
        ok = code == 0 and [m.get("id") for m in got] == [1, 2] and got[0]["result"]["serverInfo"]["version"] == GUARD_VERSION and \
            [t.get("name") for t in got[1]["result"]["tools"]] == [MCP_TOOL]
        return ok, "" if ok else "unexpected answers (exit %s): %s" % (code, _shown(out.getvalue().decode("utf-8", "replace"), 200))
    except Exception as err:
        return False, "%s: %s" % (type(err).__name__, err)


# ---------------------------------------------------------------- Hermes approval (1.0.8): the hook that the MAGOS Hermes plugin runs, and the Hermes config
def _yaml_scalar(raw):
    """(text, quoted) of a one-line YAML scalar as the reader of the Hermes config takes it (Hermes approval, Reading the Hermes config), or None
    when it is no such scalar: an anchor, an alias, a tag, a block scalar, a flow collection, an unclosed quote, a double-quoted value with a
    backslash, or text after a closing quote that is no comment.  An unquoted value loses a trailing ` #` comment; in single quotes '' is '."""
    s = raw.strip()
    if not s or s.startswith("#"):
        return "", False
    if s[0] in "&*!|>[{@`%":
        return None
    if s[0] in "'\"":
        out, k = [], 1
        while k < len(s):
            ch = s[k]
            if ch == "\\" and s[0] == '"':
                return None
            if ch == s[0]:
                if s[0] == "'" and s[k + 1:k + 2] == "'":
                    out.append("'")
                    k += 2
                    continue
                rest = s[k + 1:].strip()
                return ("".join(out), True) if not rest or rest.startswith("#") else None
            out.append(ch)
            k += 1
        return None
    m = re.search(r"\s#", s)
    return (s[:m.start()].rstrip() if m else s), False


_YAML_TOP_BAD = re.compile(r"[{\[?&*!|>%@`<]|-(?:[ \t]|$)")  # a top-level flow collection, explicit key, node property, merge key or item


def _yaml_block(lines, key):
    """-> (the lines of the top-level `key:` block, error): ([], None) when the key is absent; an error for a key that occurs twice, a value on
    the key's own line (a flow mapping or a scalar), a tab in the indentation of the block, and a top-level line that is no `key:` line or
    bare document marker (a JSON-style file, an explicit `?` key, a top-level sequence or merge key, a document marker with content): the
    file is then read for certain or not at all."""
    block, found, inside = [], 0, False
    for line in lines:
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        if line[0] not in " \t":  # a top-level line ends the block
            inside = False
            if re.match(r"(?:---|\.\.\.)[ \t]*(?:#.*)?$", line):
                continue
            if _YAML_TOP_BAD.match(line) or line.startswith(("---", "...")) or not re.search(r":(?:[ \t]|$)", line):
                return [], "a top-level line that is no key: line: %s" % _shown(body, 40)
            if re.match(r"""(['"])%s\1[ \t]*:""" % re.escape(key), line):  # a quoted spelling of the key: read for certain or not at all
                return [], "a quoted %s: key" % key
            m = re.match(r"%s[ \t]*:(.*)$" % re.escape(key), line)
            if m:
                found += 1
                if found > 1:
                    return [], "more than one top-level %s: key" % key
                value = m.group(1).strip()
                if value and not value.startswith("#"):
                    return [], "%s: holds a value on its own line" % key
                inside = True
            continue
        if inside:
            if "\t" in line[:len(line) - len(line.lstrip(" \t"))]:
                return [], "a tab in the indentation of %s:" % key
            block.append(line)
    return block, None


def _yaml_children(block):
    """-> ({key: (raw value, [deeper lines])}, error) of a block: the lines indented as its first line are its keys; a deeper line, and a `-` item
    at that indentation (a block sequence), belongs to the key before it.  A repeated key and any other line are errors."""
    kids, indent, last = {}, None, None
    for line in block:
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        n = len(line) - len(line.lstrip(" "))
        indent = n if indent is None else indent
        if n > indent or (n == indent and last is not None and (body == "-" or body.startswith("- "))):
            if last is None:
                return {}, "a line before the first key"
            kids[last][1].append(line)
            continue
        m = re.match(r"([A-Za-z0-9_][A-Za-z0-9_.-]*)[ ]*:(?:[ ]+(.*))?$", body) if n == indent else None
        if m is None:
            return {}, "a line that is no key: %s" % _shown(body, 40)
        if m.group(1) in kids:
            return {}, "%s occurs twice" % m.group(1)
        last = m.group(1)
        kids[last] = (m.group(2) or "", [])
    return kids, None


def _hermes_config(home=None):
    """-> (path, the lines of <hermes home>/config.yaml or None when it is missing, error): UTF-8, a byte order mark and CR LF allowed."""
    path = os.path.join(home or hermes_home(), "config.yaml").replace("\\", "/")
    try:
        data = read_bytes(path)
        return path, (None if data is None else data.decode("utf-8-sig").splitlines()), None
    except (OSError, ValueError) as err:  # a directory, no permission, no UTF-8
        return path, None, "%s: %s" % (type(err).__name__, err)


def hermes_settings(home=None):
    """What the Hermes config says about Hermes's approval gate (Hermes approval, Reading the Hermes config) -> {"path", "error", "mode",
    "mode_quoted", "timeout"}.  A missing file is Hermes's defaults (mode and timeout None); a file that cannot be read, or an approvals: block
    this line reader cannot read for certain, sets "error" and leaves mode and timeout None."""
    path, lines, err = _hermes_config(home)
    s = {"path": path, "error": err, "mode": None, "mode_quoted": False, "timeout": None}
    if lines is None:
        return s
    block, err = _yaml_block(lines, "approvals")
    kids, err = _yaml_children(block) if err is None else ({}, err)
    got = {}
    for key in ("mode", "timeout"):
        if err is None and key in kids:
            raw, deeper = kids[key]
            got[key] = None if deeper else _yaml_scalar(raw)
            if got[key] is None:
                err = "approvals.%s is no plain one-line value" % key
    if err is not None:
        s["error"] = err
        return s
    if got.get("mode") and got["mode"][0]:
        s["mode"], s["mode_quoted"] = got["mode"]
    if "timeout" in got:
        s["timeout"] = hermes_timeout(*got["timeout"])
    return s


_YAML_NULL = ("", "~", "null", "Null", "NULL")
_YAML_BOOL = {w: v for v, words in ((True, "yes Yes YES true True TRUE on On ON"), (False, "no No NO false False FALSE off Off OFF"))
              for w in words.split()}
_YAML_INT = re.compile(r"[-+]?(?:0b[0-1_]+|0[0-7_]+|0|[1-9][0-9_]*|0x[0-9a-fA-F_]+|[1-9][0-9_]*(?::[0-5]?[0-9])+)")
_YAML_FLOAT = re.compile(r"[-+]?[0-9][0-9_]*\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9_]+(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*"
                         r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)")


def _yaml_number(text):
    """The YAML 1.1 value PyYAML constructs for an unquoted integer or float scalar (the resolver and constructor Hermes's config loader uses):
    underscores dropped, 0b binary, 0x hex, a leading 0 octal, base-60 parts with ':'; a float as float()."""
    v = text.replace("_", "")
    sign = -1 if v[:1] == "-" else 1
    v = v[1:] if v[:1] in "+-" else v
    if _YAML_INT.fullmatch(text):
        if ":" in v:
            n = 0
            for part in v.split(":"):
                n = n * 60 + int(part)
            return sign * n
        if v.startswith(("0b", "0x")):
            return sign * int(v[2:], 2 if v[1] == "b" else 16)
        return sign * (int(v, 8) if v != "0" and v.startswith("0") else int(v))
    v = v.lower()
    if v in (".inf", ".nan"):
        return sign * float(v[1:])
    if ":" in v:
        n = 0.0
        for part in v.split(":"):
            n = n * 60 + float(part)
        return sign * n
    return sign * float(v)


def hermes_timeout(text, quoted):
    """approvals.timeout as Hermes reads it (its _get_approval_timeout): int() of the value PyYAML gives the scalar, 300 where int() raises
    ValueError or TypeError.  Unquoted, YAML 1.1 resolves null (300), the booleans (1 and 0), integers in every base and floats (int()
    truncates; nan is 300); a quoted value and any other text is a string, which int() reads in decimal (blanks and single underscores
    allowed).  A value Hermes cannot take at all (an infinite float, a number YAML cannot construct) counts as the cap HERMES_LIFE_MAX_S."""
    try:
        if quoted:
            value = text
        elif text in _YAML_NULL:
            return HERMES_TIMEOUT_S
        elif text in _YAML_BOOL:
            value = _YAML_BOOL[text]
        elif _YAML_INT.fullmatch(text) or _YAML_FLOAT.fullmatch(text):
            value = _yaml_number(text)
        else:
            value = text
    except (ValueError, OverflowError):
        return HERMES_LIFE_MAX_S
    try:
        return int(value)
    except (ValueError, TypeError):
        return HERMES_TIMEOUT_S
    except OverflowError:
        return HERMES_LIFE_MAX_S


def hermes_mode_off(s):
    """Does approvals.mode read as off: `off` in any case and quoting, or unquoted false, no or n in any case?  Hermes reads the YAML 1.1
    booleans of PyYAML (false, False, FALSE, no, No, NO) as false, which it treats as off, and every other of these spellings (n, nO, fAlse)
    as a string, which it reads as manual: there the guard is stricter and refuses the click where Hermes would ask."""
    v = (s.get("mode") or "").strip().lower()
    return v == "off" or (not s.get("mode_quoted") and v in ("false", "no", "n"))


def hermes_lifetime(s):
    """The lifetime of a Hermes record that asks: min(max(T, 120), 900) + 30 s, T being approvals.timeout as Hermes reads it (300 when
    unset; hermes_timeout)."""
    t = s.get("timeout") if isinstance(s.get("timeout"), int) else HERMES_TIMEOUT_S
    return min(max(t, HERMES_LIFE_MIN_S), HERMES_LIFE_MAX_S) + HERMES_LIFE_MARGIN_S


def hermes_noask(gate, s):
    """-> (the key of the reason, its fields) when Hermes would not ask a human for this call, else None: the plugin's gate value (bypass,
    absent), HERMES_YOLO_MODE in the hook's environment, a Hermes config that cannot be read, approvals.mode off."""
    if gate == "bypass":
        return "hermes_how_session", {}
    if gate != "ask":
        return "hermes_how_gate", {}
    if os.environ.get("HERMES_YOLO_MODE", "").strip().lower() in _TRUTHY:
        return "hermes_how_env", {}
    if s["error"]:
        return "hermes_how_config", {"path": _dialog(s["path"], 200), "err": _dialog(s["error"], 200)}
    if hermes_mode_off(s):
        return "hermes_how_mode", {"path": _dialog(s["path"], 200), "value": _dialog(s["mode"], 40)}
    return None


def hermes_answer(payload, crs, lang, gate):
    """The Hermes hook's answer when the MAGOS Hermes plugin runs it (`--hermes-gate`) for a command in which the tamper filter found a
    user-only subcommand (Hermes approval): a HermesApproval that hands Hermes the command rebuilt with a one-time token (modify) and, except
    where auto-safe allows the subcommand, a guard-written question with a request-unique rule key (approve), or a deny (code, message) whose
    last line names the cause.  The directory comes from the call: its absolute workdir, else absolute paths only."""
    why = _USER_MSG
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}

    def shape(cause):
        return "PROTECTED", T(lang, "protected_shape_hermes", why=why, cmd=guard_cmd()) + "\n[%s]" % cause
    if _carries_approval(str(ti.get("command") or "")):  # Hermes runs its hooks once per call: no rewritten command comes back here
        return "PROTECTED", T(lang, "approval_given_hermes", why=why)
    if payload.get("tool_name") != "terminal" or any(ti.get(k) not in (None, False) for k in ("background", "pty")):
        return shape("APPROVAL_TOOL")
    wd, base = ti.get("workdir"), None
    if wd is not None:
        if not isinstance(wd, str) or not wd or wd.startswith("~") or not all(ch.isalnum() or ch in _HERMES_WORKDIR_CHARS for ch in wd):
            return shape("APPROVAL_DIRECTORY")
        p = _norm_path(wd)
        if not _rooted(p) or len(p) > MAX_DIR:
            return shape("APPROVAL_DIRECTORY")
        base = os.path.normpath(p)
    inv, cause = approval_invocation(payload, base, _HERMES_APPROVAL_TOOLS)
    if inv is None:
        return shape(cause)
    if crs:
        return shape("APPROVAL_SHAPE")
    probe = "A" * 43  # the shape of a token: the guard's own parser must read the appended word as the approval option
    ns = parse_quiet(inv["args"] + ["--approval=" + probe])
    row = user_only_row(ns) if ns is not None and getattr(ns, "approval", None) == probe else None
    if row is None:
        return shape("APPROVAL_ARGS")
    if row.name == "install" and not same_file(inv["words"][-1], os.path.abspath(__file__)):
        return shape("APPROVAL_SCRIPT")  # install copies the launcher beside the script it runs as: only this very file names a trusted one

    def relative(v):
        return v is not None and (v.startswith("~") or not _rooted(_norm_path(v)))
    if base is None and (relative(ns.repo) or (row.scope == "repo" and ns.repo is None) or (row.name == "install" and relative(ns.home))):
        return shape("APPROVAL_DIRECTORY")
    cause = approval_intact(inv["words"], inv["args"], "bash")
    if cause:
        return shape(cause)
    t = approval_target(ns, row, base)
    if not isinstance(t, dict):
        return shape(t)
    if t["level"] == "terminal":
        return "PROTECTED", T(lang, "protected_level", why=why)
    auto = t["level"] == "auto-safe" and row.auto_safe and \
        (row.scope != "home" or (pkey(t["dest"]) == pkey(guard_home()) and not getattr(ns, "allow_downgrade", False)))
    life = APPROVAL_S
    if not auto:
        settings = hermes_settings()
        no = hermes_noask(gate, settings)
        if no:
            return "PROTECTED", T(lang, "protected_hermes_noask", why=why, how=T(lang, no[0], **no[1]))
        life = hermes_lifetime(settings)
    now, token = time.time(), secrets.token_urlsafe(32)
    command = approval_command("bash", inv["words"] + inv["args"], token)
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    rec = {"v": 1, "sub": row.name, "argv": inv["args"], "where": t["where"], "via": "auto-safe" if auto else "prompt", "created": now,
           "expires": now + life, "tool_use_id": _payload_id(payload.get("tool_use_id")) or _payload_id(extra.get("tool_call_id")),
           "session_id": _payload_id(payload.get("session_id")), "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(), "used": False,
           "route": "hermes"}
    try:
        prune_approvals(t["root"], now)
        if row.scope == "repo":
            prune_denials(os.path.join(store(t["g"]), "denials"), now)
        write_atomic(os.path.join(t["root"], hashlib.sha256(token.encode("ascii")).hexdigest() + ".json"), json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    except OSError as err:
        return "PROTECTED", T(lang, "approval_unrecorded", why=why, err="%s: %s" % (type(err).__name__, err))
    if auto:
        return HermesApproval(command, None, None)
    return HermesApproval(command, T(lang, "approval_ask_hermes", sub=row.name, what=approval_what(lang, row, ns, t), secs=int(life)),
                          "magos:%s:%s" % (row.name, secrets.token_hex(16)))


def decide(payload, lang, host=None, gate=None):
    """-> None (allow), (code, message) (deny), an Approval (host claude: the ask or allow of a user-only command) or a HermesApproval (host
    hermes with the gate value of the MAGOS Hermes plugin: the modify and approve of a user-only command)."""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool.startswith("mcp__") and not isinstance(ti.get("command"), str) and not _MCP_SESSION.fullmatch(tool):
        return None  # an MCP tool that runs no command and starts no session: answered before any repository is opened or any git runs
    crs, prot, cwd = extract(payload)
    text, opened = shell_text(payload), []

    def repo():  # the session directory's repository, opened at most once
        if not opened:
            opened.append(open_repo(cwd))
        return opened[0]
    if text and any(s not in _BUILTINS for s in _git_subcommands(_bare(text))):  # a git alias may hide a creation anywhere (g''it, g\it)
        aliases = load_aliases(repo()) if repo() else {}
        crs = extract(payload, aliases)[0] if aliases else crs
    if not prot and text and len(text) <= MAX_TEXT and _WRITE_HINT.search(re.sub(r"[\\`^'\"]", "", text)):
        prot = protected(text, roots=tuple(tamper_roots()), lazy=lambda: [pkey(store(repo()))] if repo() else [])
    if prot:
        if prot[1] == _HOST_MSG:  # mcp: only the host starts the approval server, on every host (Codex approval)
            return "PROTECTED", T(lang, "protected_mcp")
        if prot[1] == _SLOT_MSG:  # a guard run whose subcommand is no plain word an agent may run, on every host (The subcommand of a guard run)
            return "PROTECTED", T(lang, "protected_slot", cmd=guard_cmd(), subs="|".join(AGENT_SUBS))
        if prot[1] == _LONG_MSG:  # a text too long to read that names MAGOS, on every host (The subcommand of a guard run)
            return "PROTECTED", T(lang, "protected_long", n=MAX_TEXT)
        if host == "hermes" and gate is not None and prot[1] == _USER_MSG:  # the MAGOS Hermes plugin: modify and approve (Hermes approval)
            return hermes_answer(payload, crs, lang, gate)
        if host == "claude" and prot[1] == _USER_MSG:  # Claude Code asks the user in its own dialog (Approval)
            return approval_answer(payload, cwd, crs, lang)
        if host == "codex" and prot[1] == _USER_MSG:  # Codex: the MCP tool magos_approve and Codex's own dialog (Codex approval)
            return "PROTECTED", codex_denial(payload, cwd, lang)
        g = repo()
        if prot[0] == "always" or (g and (guard_mode(g) == "armed" or holds_claims(g))):
            return "PROTECTED", T(lang, "protected", why=prot[1])
    return enforce(crs, cwd, lang) if crs else None


def holds_claims(g):
    """Does the repository hold an open claim (also one of a newer format that this guard cannot read)?"""
    claims, bad = read_claims(g)
    return bool(claims) or any(b.code == "CLAIM_NEWER_FORMAT" for b in bad)


def emit_deny(msg):
    """One deny shape for all three hosts, signalled as JSON at exit 0 (Claude/Codex hookSpecificOutput + legacy decision, Hermes decision).
    Exit 2 is deliberately not used: Python itself exits 2 for usage errors and a missing script, which must never read as a deny."""
    obj = {"decision": "block", "reason": msg, "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}}
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True) + "\n").encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


def emit_approval(a):
    """The ask or allow of a user-only command: one ASCII-escaped JSON object on stdout, exit 0, with hookSpecificOutput only (no legacy
    decision field: it has no ask, and its approve would skip the dialog)."""
    obj = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": a.decision, "permissionDecisionReason": a.reason,
                                  "updatedInput": a.updated}}
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True) + "\n").encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


def emit_hermes(a):
    """The Hermes hook's modify and approve for the MAGOS Hermes plugin (Hermes approval): one ASCII-escaped JSON object on stdout, exit 0.  No
    Hermes directive: a Hermes entry under hooks: that ran it would contribute nothing."""
    obj = {"hermesApproval": {"modify": {"command": a.command}}}
    if a.message is not None:
        obj["hermesApproval"]["approve"] = {"message": a.message, "rule_key": a.rule_key}
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True) + "\n").encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


_PREFILTER =re.compile(rb"git|worktree|isolation|start_session|EnterWorktree|magos|hookspath|gh|claude|eval|iex", re.I)


def cmd_hook(args):
    global HOOK_DEADLINE, _MEMO
    HOOK_DEADLINE, _MEMO = time.monotonic() + BUDGET_S, {}
    try:
        return _hook(args)
    finally:
        HOOK_DEADLINE, _MEMO = None, None


def _lane_text(payload):
    """Does the call look lane-related when the guard cannot recognise it?  The command text of tool_input, or for a tool without a command
    its tool_input serialised, is matched against the prefilter; path fields of the payload (cwd, transcript_path) never decide it.  A
    tool_input that cannot even be serialised counts as lane-related."""
    ti = payload.get("tool_input")
    c = ti.get("command") if isinstance(ti, dict) else None
    try:
        text = c if isinstance(c, str) else json.dumps(ti, ensure_ascii=False)
    except BaseException:  # nested beyond what the encoder can walk
        return True
    return _PREFILTER.search(text.encode("utf-8", "surrogatepass")) is not None


def _hook(args):
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        payload = payload if isinstance(payload, dict) else {}
    except BaseException as err:  # invalid JSON, or any exception while decoding (RecursionError and MemoryError included)
        if _PREFILTER.search(raw):
            return emit_deny("MAGOS guard: unparseable hook payload (%s)" % type(err).__name__)
        sys.stderr.write("MAGOS guard warning: unparseable hook payload (%s); the call shows no lane word and is allowed\n" % type(err).__name__)
        return (out_text("{}"), 0)[1]
    try:
        res = decide(payload, args.lang, args.host, getattr(args, "hermes_gate", None))
    except BaseException as err:  # fail closed only when the call looks lane-creating or protected
        try:
            looks = any(extract(payload)[:2])
        except BaseException:
            looks = _lane_text(payload)
        if looks:
            return emit_deny("MAGOS guard error (%s: %s); the lane-creating call is denied. Diagnose: %s doctor" % (type(err).__name__, err, guard_cmd()))
        sys.stderr.write("MAGOS guard warning: %s: %s\n" % (type(err).__name__, err))
        res = None
    if isinstance(res, HermesApproval):  # first: a HermesApproval and an Approval are tuples too
        return emit_hermes(res)
    if isinstance(res, Approval):
        return emit_approval(res)
    return emit_deny(res[1]) if res else (out_text("{}"), 0)[1]


# ---------------------------------------------------------------- git layer (L2): pure POSIX sh reference-transaction hook, no Python
HOOK_SH = r'''#!/bin/sh
# MAGOS lane guard, git layer: reference-transaction only. POSIX sh, LF endings, no Python, no environment switch.
Z=0000000000000000000000000000000000000000; in=
chain() { p=${0%/*}/reference-transaction.magos-prev; [ -f "$p" ] && [ -x "$p" ] || exit 0
  if [ -n "$in" ]; then printf '%s\n' "$in" | "$p" "$@"; else "$p" "$@"; fi; exit $?; }
[ "$1" = prepared ] || chain "$@"
if [ -n "$GIT_DIR" ]; then g=$GIT_DIR; elif [ -d .git ]; then g=.git; elif [ -f .git ]; then read -r l <.git; g=${l#gitdir: }; else g=.; fi
CD=$g; if [ -f "$g/commondir" ]; then read -r c <"$g/commondir"; case $c in /*|?:*) CD=$c;; *) CD=$g/$c;; esac; fi
M=$CD/magos
[ -f "$M/ARMED" ] || chain "$@"
L=zh; [ -f "$M/lang" ] && read -r L <"$M/lang"; G=magos_guard.py; [ -f "$M/guard" ] && read -r G <"$M/guard"
deny() { if [ "$L" = en ]; then printf 'MAGOS BLOCKED: %s\n' "$2" >&2; else printf 'MAGOS 拒绝: %s\n' "$1" >&2; fi; exit 1; }
claim() { [ -f "$M/claims/$1.claim" ] || return 1; read -r l <"$M/claims/$1.claim"; case $l in state=active|state=active?) return 0;; esac; return 1; }
need() { claim "$1" || deny "分支「$1」没有已登记的文件清单（$2）。先登记: $G plan --branch $1 --paths <路径...>。已有分支与工作树不受影响。若这是带起点的 switch/checkout -b 或 --orphan，检出可能已经发生：先看 git status。" "'$1' has no registered file manifest ($2). Register it first: $G plan --branch $1 --paths <paths>. Existing lanes are untouched. If this was switch/checkout -b <start> or --orphan, the checkout step may already have run: check git status."; }
exists() { [ -e "$CD/$1" ] || git rev-parse --verify -q "$1" >/dev/null; }
in=$(cat)
while read -r old new ref; do
  case $ref in
  @HEADS@*) [ "$new" = $Z ] && continue
    b=${ref#@HEADS@}; claim "$b" && continue
    if [ -f "$CD/$ref" ]; then read -r cur <"$CD/$ref"; else cur=$(git rev-parse --verify -q "$ref"); fi
    [ "$cur" = "$new" ] && continue
    [ -z "$cur" ] && need "$b" "creation / 新建分支";;
  HEAD) case $new in ref:@HEADS@*) b=${new#ref:@HEADS@}
      exists "refs/heads/$b" || need "$b" "unborn or orphan branch / 孤儿分支";; esac;;
  esac
done <<EOT
$in
EOT
chain "$@"
'''.replace("@HEADS@", _HEADS_CI)  # the arms match refs/heads/ in any case of both words, from the pattern the host hook reads


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def hooks_dir(g, wt=None):
    return os.path.normpath(g.text("rev-parse", "--path-format=absolute", "--git-path", "hooks", cwd=wt).strip())


def put_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))


PACK_KEYS = ("maintenance.pack-refs.enabled", "gc.packRefs")  # arm switches both off (background pack-refs would multiply hook calls)


def local_cfg(g, key):
    """The repository's own (--local) value of a config key, or None when it is unset there."""
    rc, out = g.run("config", "--local", "--get", key, ok=(0, 1))
    return out.decode("utf-8", "replace").strip() if rc == 0 else None


def backstop_cmd():
    """The guard command the backstop's deny message prints: the copy under the guard home when it declares this guard's GUARD_VERSION (a
    path that survives plugin upgrades), else the running script."""
    copy = os.path.join(guard_home(), "guard", "scripts", "magos_guard.py")
    return guard_cmd(copy if version_of(read_quiet(copy)) == GUARD_VERSION else None)


def cmd_arm(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    wts = [w for w in worktrees(g) if not w["bare"] and not w["prunable"]]
    dirs = {pkey(hooks_dir(g, w["path"])) for w in wts}
    hook = os.path.join(hooks_dir(g), "reference-transaction")
    mine_hook = os.path.exists(hook) and MARK in read_text(hook)
    why = ("core.hooksPath is set" if g.run("config", "--get", "core.hooksPath", ok=(0, 1))[0] == 0 else
           "the worktrees resolve to different hook directories (%d)" % len(dirs) if len(dirs) > 1 else
           "%s.magos-prev already exists" % hook if os.path.exists(hook + ".magos-prev") and not mine_hook else None)
    if why:
        sys.stderr.write("MAGOS arm refused: %s\n" % why)
        return EXIT["ARM_REFUSED"]
    s, dry = store(g), args.dry_run
    code, via, rec = user_gate(args, os.path.join(s, "approvals"), g.common, dry=dry)
    if code:
        return code
    record = os.path.join(s, "arm-config.json")
    keep = os.path.exists(record)  # an existing record holds the values from before the first arm: a re-run never records its own false
    steps = [("write", hook), ("write", os.path.join(s, "ARMED")), ("write", os.path.join(s, "lang")), ("write", os.path.join(s, "guard"))]
    steps += ([] if keep else [("write", record)]) + [("config", "%s=false" % k) for k in PACK_KEYS]
    if dry:
        for kind, target in steps:
            out_text("would %s %s" % (kind, target))
        return 0
    if not keep:
        write_atomic(record, (json.dumps({k: local_cfg(g, k) for k in PACK_KEYS}, indent=2) + "\n").encode("utf-8"))
    if os.path.exists(hook) and not mine_hook:
        os.replace(hook, hook + ".magos-prev")
    put_text(hook, HOOK_SH)
    os.chmod(hook, 0o755)
    put_text(os.path.join(s, "lang"), args.lang + "\n")
    put_text(os.path.join(s, "guard"), backstop_cmd() + "\n")
    put_text(os.path.join(s, "ARMED"), now_iso() + "\n")
    for k in PACK_KEYS:
        g.run("config", "--local", k, "false")
    audit(g, op="arm", lang=args.lang, via=via, **approval_fields(rec))
    for kind, target in steps:
        out_text("did %s %s" % (kind, target))
    return 0


def cmd_disarm(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    hook, s = os.path.join(hooks_dir(g), "reference-transaction"), store(g)
    code, via, rec = user_gate(args, os.path.join(s, "approvals"), g.common, dry=args.dry_run)
    if code:
        return code
    verb = "would" if args.dry_run else "did"
    mine = os.path.exists(hook) and MARK in read_text(hook)
    for target in [os.path.join(s, "ARMED")] + ([hook] if mine else []):
        out_text("%s remove %s" % (verb, target))
        if not args.dry_run and os.path.exists(target):
            os.remove(target)
    if mine and not args.dry_run and os.path.exists(hook + ".magos-prev"):
        os.replace(hook + ".magos-prev", hook)
    if not args.dry_run:
        audit(g, op="disarm", via=via, **approval_fields(rec))
    record = os.path.join(s, "arm-config.json")
    if os.path.exists(record):  # put back what arm found; without a record the settings stay as they are
        try:
            before = json.loads(read_text(record))
            before = before if isinstance(before, dict) else None
        except ValueError:
            before = None
        if before is None:
            out_text("%s is unreadable: gc.packRefs and maintenance.pack-refs.enabled stay as they are" % record)
            return 0
        for k in PACK_KEYS:
            if k not in before:
                continue
            out_text("%s %s" % (verb, "unset %s" % k if before[k] is None else "restore %s=%s" % (k, before[k])))
            if not args.dry_run:
                if before[k] is None:
                    g.run("config", "--local", "--unset", k, ok=(0, 5))
                else:
                    g.run("config", "--local", k, str(before[k]))
        out_text("%s remove %s" % (verb, record))
        if not args.dry_run:
            os.remove(record)
    elif any(local_cfg(g, k) == "false" for k in PACK_KEYS):  # armed before 1.0.2 (no record): the values from before that arm are unknown
        out_text("no %s: gc.packRefs and maintenance.pack-refs.enabled stay as they are; to return them to Git's defaults run "
                 "git config --local --unset gc.packRefs and git config --local --unset maintenance.pack-refs.enabled" % record)
    return 0


# ---------------------------------------------------------------- version, installer and doctor
HOSTS = ("claude", "codex", "hermes")
_VERSION_LINE = re.compile(rb"^GUARD_VERSION\s*=\s*[\"']([0-9]+(?:\.[0-9]+)*)[\"']", re.M)


def guard_home(arg=None):
    return os.path.abspath(os.path.expanduser(arg or os.environ.get("MAGOS_HOME") or "~/.magos")).replace("\\", "/")


def version_of(data):
    """The GUARD_VERSION a guard file's bytes declare, or None (guards before 1.0.2 declare none)."""
    m = _VERSION_LINE.search(data or b"")
    return m.group(1).decode("ascii") if m else None


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    """The bytes of a file, or None when it does not exist."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def read_quiet(path):
    """The bytes of a file, or None when it cannot be read (missing, a directory, no permission)."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (OSError, ValueError):
        return None


def newer(a, b):
    """Is GUARD_VERSION text `a` newer than `b`?  A guard that declares no version (None) is older than every guard that declares one."""
    return a is not None and (b is None or vtuple(a) > vtuple(b))


def guard_files(home):
    """(source, copy) for the guard script and its launcher: the source is this guard's own file, the copy is under <home>/guard."""
    here = os.path.dirname(os.path.abspath(__file__))
    return [(os.path.abspath(__file__), "%s/guard/scripts/magos_guard.py" % home),
            (os.path.normpath(os.path.join(here, "..", "hooks", "run-guard.cmd")), "%s/guard/hooks/run-guard.cmd" % home)]


def hermes_home():
    """HERMES_HOME, else %LOCALAPPDATA%/hermes on Windows, else ~/.hermes."""
    if os.environ.get("HERMES_HOME", "").strip():
        return os.environ["HERMES_HOME"].strip()
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA", "").strip():
        return os.path.join(os.environ["LOCALAPPDATA"].strip(), "hermes")
    return os.path.expanduser("~/.hermes")


_CMD_META = "&()^%;,="  # read by cmd.exe as operators, separators or expansions where it starts the launcher or runs the interpreter with call


def cmd_unsafe(path):
    """On Windows, the first character of `path` that cmd.exe reads as an operator, a separator or an expansion when it starts the launcher
    by that path and runs the interpreter through `call`; None when there is none, and always None elsewhere."""
    return next((c for c in path if c in _CMD_META), None) if sys.platform == "win32" else None


def hermes_plugin():
    """-> (launcher, note).  launcher: the Hermes plugin's own launcher when the Hermes entry may run it, i.e. the guard script beside it
    declares this guard's GUARD_VERSION and, on Windows, its path holds no character cmd_unsafe names; else None.  note: why an existing
    plugin launcher is not used, else None."""
    plugin = os.path.abspath(os.path.join(hermes_home(), "plugins", "magos")).replace("\\", "/")
    own = plugin + "/hooks/run-guard.cmd"
    if not os.path.isfile(own):
        return None, None
    v = version_of(read_quiet(plugin + "/scripts/magos_guard.py"))
    if v != GUARD_VERSION:
        return None, ("the Hermes plugin %s holds guard %s, not %s, so the Hermes entry runs the copy under the guard home. Update the Hermes "
                      "plugin (hermes plugins update magos; when its security scan asks for confirmation: hermes plugins install "
                      "UlyssesLeoLee/MAGOS --force --enable), then run install --host hermes again" % (plugin, v or "unversioned", GUARD_VERSION))
    bad = cmd_unsafe(own)
    if bad:
        return None, ("the Hermes plugin launcher %s contains %r, which cmd.exe reads as an operator, a separator or an expansion when it "
                      "starts the launcher, so the Hermes entry runs the copy under the guard home" % (own, bad))
    return own, None


def host_launcher(host, home):
    """The launcher a host entry runs: for Hermes the Hermes plugin's own launcher when it runs this guard version (it then follows
    `hermes plugins update`), otherwise the copied launcher under <home>/guard."""
    own = hermes_plugin()[0] if host == "hermes" else None
    return own or "%s/guard/hooks/run-guard.cmd" % home


def sh_quote(text):
    """`text` as one single-quoted word of a POSIX shell (bash, sh): each apostrophe closes the quote, is escaped and reopens it."""
    return "'%s'" % text.replace("'", "'\\''")


def ps_quote(text):
    """`text` as one single-quoted PowerShell string: each quote character PowerShell accepts there (', and the typographic single quotes)
    written twice."""
    return "'%s'" % re.sub("(['\u2018\u2019\u201a\u201b])", r"\1\1", text)


def host_snippet(host, home):
    launcher = host_launcher(host, home)
    win = sys.platform == "win32"
    if host == "codex":
        return json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash|mcp__.*(start_session|worktree|branch|hand_off_to_session)", "hooks": [{
            "type": "command", "command": "sh %s hook codex pre-tool" % sh_quote(launcher),
            "commandWindows": "& %s hook codex pre-tool; exit $LASTEXITCODE" % ps_quote(launcher), "timeout": 25,
            "statusMessage": "MAGOS lane guard"}]}]}}, indent=2)
    if host == "hermes":  # command is a YAML single-quoted scalar ('' stands for '), so the POSIX form and its quoted path stay valid YAML
        command = ('"%s"' % launcher if win else "sh " + sh_quote(launcher)) + " hook hermes pre-tool"
        return ('hooks:\n  pre_tool_call:\n    - matcher: "terminal"\n      command: \'%s\'\n      timeout: 25\n      fail_closed: true\n'
                % command.replace("'", "''"))
    return json.dumps({"hooks": {"PreToolUse": [  # run by bash: the single-quoted path keeps a $, a backtick or a ! literal
        {"matcher": claude_matcher(strict=True), "hooks": [{"type": "command", "command": "%s --strict hook claude pre-tool" % sh_quote(launcher),
                                                            "shell": "bash", "timeout": 25}]},
        {"matcher": claude_matcher(),
         "hooks": [{"type": "command", "command": "%s hook claude pre-tool" % sh_quote(launcher), "shell": "bash", "timeout": 25}]}]}}, indent=2)


def _toml_str(s):
    """`s` as a TOML basic string: " and \\ escaped, every control character but the tab (DEL included) as \\uXXXX, everything else literal."""
    return '"%s"' % "".join("\\\\" if c == "\\" else '\\"' if c == '"' else "\\u%04X" % ord(c) if (ord(c) < 0x20 and c != "\t") or c == "\x7f"
                            else c for c in s)


def codex_mcp_toml(home):
    """The [mcp_servers.magos] entry for Codex (Codex approval, install and doctor): the interpreter that runs install, isolated (-I) and without
    byte-code files (-B), runs the copy under the guard home; env_vars passes MAGOS_HOME and MAGOS_LANG through Codex's short environment."""
    args = ", ".join(_toml_str(a) for a in ("-I", "-B", "%s/guard/scripts/magos_guard.py" % home, "mcp"))
    return ('[mcp_servers.%s]\ncommand = %s\nargs = [%s]\nenv_vars = ["MAGOS_HOME", "MAGOS_LANG"]\nstartup_timeout_sec = 30\ntool_timeout_sec = 600\n'
            % (MCP_SERVER, _toml_str(sys.executable), args))


def codex_mcp_add(home):
    """The one-line alternative of codex_mcp_toml, each word quoted for the user's shell; it sets neither env_vars nor the timeouts."""
    win = sys.platform == "win32"
    bare, quote = (_BARE_PS, ps_quote) if win else (_BARE_SH, sh_quote)
    words = [sys.executable, "-I", "-B", "%s/guard/scripts/magos_guard.py" % home, "mcp"]
    return "codex mcp add %s -- %s" % (MCP_SERVER, " ".join(w if bare.fullmatch(w) else quote(w) for w in words))


def _hermes_list(raw, deeper):
    """The names of a plugins.enabled or plugins.disabled value: a flow list [a, b] of plain or quoted scalars on the key's line, or a block
    sequence of `- name` lines under it; None when it is neither."""
    raw = raw.strip()
    if raw and not raw.startswith("#"):
        m = re.fullmatch(r"\[(.*)\](?:\s+#.*)?", raw)
        if m is None or deeper:
            return None
        items = [x.strip() for x in m.group(1).split(",")] if m.group(1).strip() else []
        got = [_yaml_scalar(x) for x in items]
        return None if any(x is None or not x[0] for x in got) else [x[0] for x in got]
    names = []
    for line in deeper:
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        got = _yaml_scalar(body[1:]) if body == "-" or body.startswith("- ") else None
        if got is None or not got[0]:
            return None
        names.append(got[0])
    return names


def hermes_route(home=None):
    """What doctor and install --host hermes read about the route of the guard in Hermes (Hermes approval, doctor) -> {"dir": the MAGOS plugin
    directory, "plugin": it holds __init__.py and scripts/magos_guard.py, "version": that guard's GUARD_VERSION, "callbacks": its __init__.py
    registers the guard callbacks, "enabled": plugins.enabled names magos and plugins.disabled does not (None: no such list, or the config
    cannot be read), "entry": a line of the top-level hooks: block runs `hook hermes pre-tool` (None: unreadable), "consented":
    shell-hooks-allowlist.json lists that entry's exact command for pre_tool_call (None: no entry, or the file or the command cannot be read),
    "config": the config's path}."""
    hh = home or hermes_home()
    plugin = os.path.abspath(os.path.join(hh, "plugins", "magos")).replace("\\", "/")
    init = read_quiet(plugin + "/__init__.py")
    guard = read_quiet(plugin + "/scripts/magos_guard.py")
    path, lines, err = _hermes_config(hh)
    r = {"dir": plugin, "plugin": init is not None and guard is not None, "version": version_of(guard),
         "callbacks": b'register_hook("pre_tool_call"' in (init or b""), "enabled": None, "entry": False if lines is None and err is None else None,
         "consented": None, "config": path}
    if lines is None:
        return r
    block, err = _yaml_block(lines, "plugins")
    kids, err = _yaml_children(block) if err is None else ({}, err)
    if err is None and ("enabled" in kids or "disabled" in kids):
        on = _hermes_list(*kids["enabled"]) if "enabled" in kids else []
        off = _hermes_list(*kids["disabled"]) if "disabled" in kids else []
        r["enabled"] = None if on is None or off is None else ("magos" in on and "magos" not in off)
    hooks, err = _yaml_block(lines, "hooks")
    if err is not None:
        return r
    hits = [line for line in hooks if "hook hermes pre-tool" in line]
    r["entry"] = bool(hits)
    if not hits:
        return r
    body = hits[0].strip()
    body = body[2:].lstrip() if body.startswith("- ") else body
    got = _yaml_scalar(body[len("command:"):]) if body.startswith("command:") else None
    raw = read_quiet(os.path.join(hh, "shell-hooks-allowlist.json"))
    try:
        doc = {"approvals": []} if raw is None else json.loads(raw.decode("utf-8-sig"))
        listed = doc.get("approvals") if isinstance(doc, dict) else None
        if got is not None and isinstance(listed, list):
            r["consented"] = any(isinstance(a, dict) and a.get("event") == "pre_tool_call" and a.get("command") == got[0].strip() for a in listed)
    except ValueError:
        pass
    return r


def hermes_route_on(r):
    """Does the MAGOS Hermes plugin run the guard of this version and ask in Hermes's approval prompt (enabled, or plugins.enabled unread)?"""
    return r["plugin"] and r["version"] == GUARD_VERSION and r["callbacks"] and r["enabled"] is not False


def hermes_route_note(r):
    """The NOTE of install --host hermes on the route of the guard in Hermes (Hermes approval)."""
    if hermes_route_on(r):
        return ("the Hermes plugin %s (guard %s) runs the guard and asks for a user-only command in Hermes's approval prompt; with it, leave the entry "
                "below out of the Hermes config: a MAGOS entry under hooks: denies every user-only command before Hermes can ask" % (r["dir"], r["version"]))
    return ("the entry below runs the guard in Hermes once it is approved (hooks_auto_accept: true, or HERMES_ACCEPT_HOOKS=1 for hermes acp; an entry "
            "that is not approved is skipped without a word), and a user-only command then runs in the user's own terminal; the MAGOS Hermes plugin "
            "of this version (hermes plugins install UlyssesLeoLee/MAGOS --enable, or hermes plugins update magos, then a restart of Hermes) runs the "
            "guard without an entry and without that approval, and asks in Hermes's approval prompt")


def home_audit(home, **rec):
    """One JSON line (ts first) appended to <guard home>/audit.log."""
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "audit.log"), "ab") as fh:
        fh.write((json.dumps(dict(ts=now_iso(), **rec), ensure_ascii=False) + "\n").encode("utf-8"))


def cmd_version(args):
    """Read-only: the running guard's version, the sha256 of its file, its path and the Python that runs it."""
    me = os.path.abspath(__file__)
    info = {"version": GUARD_VERSION, "sha256": sha256_of(read_bytes(me) or b""), "path": me.replace("\\", "/"), "python": sys.version.split()[0]}
    out_text(json.dumps(info) if args.json else "magos_guard %(version)s\nsha256 %(sha256)s\npath %(path)s\npython %(python)s" % info)
    return 0


def version_record(source, data):
    return (json.dumps({"version": GUARD_VERSION, "sha256": sha256_of(data), "source": source.replace("\\", "/"), "installed_at": now_iso()},
                       indent=2) + "\n").encode("utf-8")


def read_record(home):
    """guard/VERSION.json under the guard home: a dict, None when the file is missing, {} when it cannot be read as a JSON object."""
    raw = read_quiet("%s/guard/VERSION.json" % home)
    if raw is None:
        return None
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def same_file(a, b):
    """Do the paths name one existing file?"""
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


class NotRestored(OSError):
    """replace_files failed and could not put back every file it had already replaced."""


def replace_files(items):
    """Replace several files as one: write every new content to a temporary file beside its destination (with its mode on POSIX), then
    move each into place.  When a move fails, every file already moved is put back from its previous bytes (removed when there was none),
    the temporary files are removed and the error is raised, so the files never mix two versions.  items: [(path, bytes, previous bytes or
    None, mode or None)]."""
    staged, done = [], []
    try:
        for path, data, _cur, mode in items:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = "%s.%d.tmp" % (path, os.getpid())
            staged.append(tmp)
            with open(tmp, "wb") as fh:
                fh.write(data)
            if mode is not None and os.name != "nt":
                os.chmod(tmp, mode)
        for (path, _data, cur, mode), tmp in zip(items, staged):
            _replace(tmp, path)
            done.append((path, cur, mode))
    except BaseException as err:
        lost = []
        for path, cur, mode in reversed(done):
            try:
                if cur is None:
                    _remove(path)
                else:
                    write_atomic(path, cur, mode)
            except OSError:
                lost.append(path)
        if lost:
            raise NotRestored("%s; and %s could not be put back" % (err, ", ".join(lost)))
        raise
    finally:
        for tmp in staged:
            if os.path.lexists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def cmd_install(args):
    """Copies the guard and its launcher to one canonical user-level directory and prints (and saves) the exact host snippet; never edits
    host config.  Version-aware and atomic: identical copies are left alone, a newer copy is not downgraded without --allow-downgrade, both
    files are replaced together or not at all (the launcher stays executable on POSIX), and guard/VERSION.json is rewritten by every install.
    On Windows a guard home whose launcher path holds a character cmd.exe would misread is refused.  User-only: needs a real console or an
    approval token that verifies (its store is under the default guard home, whatever --home says), except with --dry-run."""
    home, dry = guard_home(args.home), args.dry_run
    launcher = "%s/guard/hooks/run-guard.cmd" % home
    bad = cmd_unsafe(launcher)
    if bad:  # cmd.exe would split or expand the path where a host starts the launcher, so the guard would never run
        sys.stderr.write("MAGOS: the guard home %s cannot hold the launcher on Windows: its path %s contains %r, which cmd.exe reads as an "
                         "operator, a separator or an expansion when it starts the launcher; nothing was written. Choose a guard home whose "
                         "path holds none of & ( ) ^ %% ; , = (--home DIR or MAGOS_HOME).\n" % (home, launcher, bad))
        return 2
    code, via, rec = user_gate(args, os.path.join(guard_home(), "approvals"), guard_home(), dry=dry)
    if code:
        return code
    files =[(src, dst, read_bytes(src), read_bytes(dst)) for src, dst in guard_files(home)]
    missing = [src for src, _dst, data, _cur in files if data is None]
    if missing:
        raise FileNotFoundError("the guard sources are incomplete: %s" % ", ".join(missing))
    record = "%s/guard/VERSION.json" % home
    src0, data0, old = files[0][0], files[0][2], files[0][3]
    if all(data == cur for _src, _dst, data, cur in files):
        out_text("guard copy unchanged (%s)" % GUARD_VERSION)
    else:
        if newer(version_of(old), GUARD_VERSION) and not args.allow_downgrade:
            sys.stderr.write("MAGOS: the guard copy %s is version %s, newer than this guard %s; nothing was copied. Run install from the newer "
                             "MAGOS, or pass --allow-downgrade to replace it.\n" % (files[0][1], version_of(old), GUARD_VERSION))
            return EXIT["DOWNGRADE_REFUSED"]
        changed = [(src, dst, data, cur) for src, dst, data, cur in files if data != cur]
        if not dry:
            try:  # the launcher first: a failure on the script puts the launcher back
                replace_files([(dst, data, cur, 0o755 if dst.endswith(".cmd") else None) for _src, dst, data, cur in reversed(changed)])
            except OSError as err:
                kept = "the copy may now mix two versions" if isinstance(err, NotRestored) else "the previous copy is kept whole"
                text = "install failed (%s: %s); %s and VERSION.json is unchanged. Run doctor, then install again" % (type(err).__name__, err, kept)
                return fail(args, "INTERNAL_ERROR", text, "MAGOS guard: " + text)
        for src, dst, _data, _cur in changed:
            out_text("%s copy %s -> %s" % ("would" if dry else "did", src, dst))
        out_text("guard copy %s -> %s%s" % ("none" if old is None else version_of(old) or "unversioned", GUARD_VERSION,
                                             " (dry run: nothing written)" if dry else ""))
    if not dry:
        source = src0
        if same_file(src0, files[0][1]):  # install run from the copy itself: the copy still came from where VERSION.json says
            prev = (read_record(home) or {}).get("source")
            source = prev if isinstance(prev, str) and prev and not same_file(prev, src0) else src0
        write_atomic(record, version_record(source, data0))
    snippet = host_snippet(args.host, home)
    note = hermes_plugin()[1] if args.host == "hermes" else None
    if not dry:
        put_text("%s/guard/generated/%s.%s" % (home, args.host, "yaml" if args.host == "hermes" else "json"), snippet)
        if args.host == "codex":  # the entry of the MCP approval server (Codex approval)
            put_text("%s/guard/generated/codex-mcp.toml" % home, codex_mcp_toml(home))
        home_audit(home, op="install", host=args.host, to=GUARD_VERSION, source=src0.replace("\\", "/"), via=via, **approval_fields(rec),
                   **{"from": "none" if old is None else version_of(old) or "unversioned"})
    if note:
        out_text("NOTE: " + note + ".")
    if args.host == "hermes":
        out_text("NOTE: " + hermes_route_note(hermes_route()) + ".")
    extra = ("\n" + codex_mcp_toml(home) + "Or add the server with: %s (this sets neither env_vars nor the timeouts)\n" % codex_mcp_add(home)
             if args.host == "codex" else "")
    out_text(snippet + "\n" + extra + "Merge it into your own host configuration; the guard never edits it. Codex: trust the entry in /hooks. "
             "Hermes: with the MAGOS Hermes plugin no entry is needed; without it, approve the entry once (hooks_auto_accept: true, or "
             "HERMES_ACCEPT_HOOKS=1), or Hermes skips it without a word.")
    return 0


def git_version_text():
    """`git --version` as git prints it (a function of its own so that doctor's version check can be tested)."""
    return Git(os.getcwd()).text("--version").strip()


def git_too_old(text):
    """'X.Y' when the `git --version` text names a version below 2.36 (the lane guard needs worktree list -z), else None."""
    m = re.search(r"(\d+)\.(\d+)", text)
    return "%s.%s" % m.groups() if m and (int(m.group(1)), int(m.group(2))) < (2, 36) else None


def described(data):
    """'<GUARD_VERSION or unversioned> (<first 12 hex digits of the sha256>)' of a guard file's bytes."""
    return "%s (%s)" % (version_of(data) or "unversioned", sha256_of(data or b"")[:12])


def provenance(rec, cur):
    """The provenance line of the copy, read from its VERSION.json (information, never a problem)."""
    if rec is None:
        out_text("guard copy provenance: no VERSION.json")
    elif not rec:
        out_text("guard copy provenance: VERSION.json cannot be read")
    else:
        out_text("guard copy provenance: %s (%s) from %s, installed %s%s" % (
            rec.get("version") or "?", str(rec.get("sha256") or "?")[:12], rec.get("source") or "?", rec.get("installed_at") or "?",
            "" if rec.get("sha256") == sha256_of(cur) else ", which does not match the copy"))


def copy_report(home_arg=None):
    """Compare the copy under the guard home (run by the Codex and Hermes hooks) with the running guard and its launcher, or, when the
    running guard is that copy, with the guard VERSION.json names as its source; then the provenance line and the Hermes entry.
    -> True on a problem."""
    home = guard_home(home_arg)
    (src, dst, data, cur), (_lsrc, ldst, ldata, lcur) = [(s, d, read_quiet(s), read_quiet(d)) for s, d in guard_files(home)]
    if cur is None:
        out_text("guard copy: none under %s/guard" % home)
        return hermes_report(home, home_arg)
    rec, against, label = read_record(home), src, "this guard"
    if same_file(src, dst):  # doctor runs from the copy itself: compare it with the guard it was installed from
        source = (rec or {}).get("source")
        if not isinstance(source, str) or not source or not os.path.isfile(source) or same_file(source, dst):
            out_text("guard copy %s: %s; this guard is the copy, and VERSION.json names no source to compare it with" % (dst, described(cur)))
            provenance(rec, cur)
            return hermes_report(home, home_arg)
        against, label = source, "its source %s" % source.replace("\\", "/")
        data = read_quiet(source)
        ldata = read_quiet(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(source))), "hooks", "run-guard.cmd"))
        out_text("guard copy %s: this guard is the copy; it is compared with its source %s, which VERSION.json names" % (dst, against))
    problem = True
    if cur == data and (ldata is None or lcur == ldata):
        out_text("guard copy %s: %s, the same as %s" % (dst, described(cur), label))
        problem = False
    elif newer(version_of(cur), version_of(data)):  # install would refuse it (exit 18): name the newer MAGOS instead of an install command
        source = (rec or {}).get("source")
        out_text("guard copy %s: %s is NEWER than %s %s; run doctor from that MAGOS%s" % (
            dst, described(cur), label, described(data), " (VERSION.json names its source: %s)" % source if isinstance(source, str) and source else ""))
    else:
        hosts = [h for h in HOSTS if os.path.isfile("%s/guard/generated/%s.%s" % (home, h, "yaml" if h == "hermes" else "json"))] or list(HOSTS)
        refresh = "%s install --host %%s%s" % (guard_cmd(against), ' --home "%s"' % home if home_arg else "")
        out_text("guard copy %s: %s DIFFERS from %s %s; refresh it (%s):\n%s"
                 % (dst, described(cur), label, described(data), _USER_RUN, "\n".join("  " + refresh % h for h in hosts)))
        if ldata is not None and lcur != ldata:
            out_text("  the launcher %s (%s) differs as well" % (ldst, sha256_of(lcur or b"")[:12]))
    provenance(rec, cur)
    return hermes_report(home, home_arg) or problem


def hermes_entry_launcher(text):
    """The launcher path in the command of a Hermes entry install generated (a YAML single-quoted scalar), or None."""
    for line in text.splitlines():
        body = line.strip()
        if body.startswith("- "):
            body = body[2:].lstrip()
        if not body.startswith("command:"):
            continue
        raw = body[len("command:"):].strip()
        if len(raw) < 2 or raw[0] != "'" or raw[-1] != "'" or "'" in raw[1:-1].replace("''", ""):
            return None
        try:
            words = shlex.split(raw[1:-1].replace("''", "'"))
        except ValueError:
            return None
        words = words[1:] if words[:1] == ["sh"] else words
        return words[0] if words else None
    return None


def hermes_report(home, home_arg=None):
    """The Hermes entry install generated (guard/generated/hermes.yaml): its launcher must exist and run a guard of this version.
    -> True on a problem."""
    path = "%s/guard/generated/hermes.yaml" % home
    raw = read_quiet(path)
    if raw is None:
        return False
    launcher = hermes_entry_launcher(raw.decode("utf-8", "replace"))
    if not launcher:
        out_text("hermes entry %s: no launcher command found in it" % path)
        return False
    redo = "%s install --host hermes%s" % (guard_cmd(), ' --home "%s"' % home if home_arg else "")
    if not os.path.isfile(launcher):
        out_text("hermes entry %s: its launcher %s does NOT EXIST (the Hermes plugin was removed?), and fail_closed then blocks every Hermes "
                 "terminal call; run %s (%s) and merge the new entry, or remove the MAGOS entry from the Hermes config" % (path, launcher, redo, _USER_RUN))
        return True
    v = version_of(read_quiet(os.path.join(os.path.dirname(os.path.dirname(launcher)), "scripts", "magos_guard.py")))
    if v != GUARD_VERSION:
        out_text("hermes entry %s: its launcher %s runs guard %s, not this guard %s; update the Hermes plugin or run %s (%s) "
                 "and merge the new entry" % (path, launcher, v or "unversioned", GUARD_VERSION, redo, _USER_RUN))
        return True
    out_text("hermes entry: %s (guard %s)" % (launcher, v))
    return False


def codex_toml_entry(text):
    """(command, args) of the [mcp_servers.magos] entry install generated, read in the form codex_mcp_toml writes (one `command = "..."` and one
    `args = [...]` line, both JSON-compatible for what install writes); (None, []) when the text holds no such lines."""
    command, args = None, []
    for line in text.splitlines():
        key, _eq, value = line.partition(" = ")
        try:
            if key == "command":
                command = json.loads(value)
            elif key == "args":
                args = [a for a in json.loads(value) if isinstance(a, str)]
        except (ValueError, TypeError):
            continue
    return (command if isinstance(command, str) else None), args


def codex_report(home_arg=None):
    """doctor's Codex lines (Codex approval, install and doctor): the approval server answers in process; the entry install generated names an
    interpreter and a guard of this version; the sha256 of the plugin's root mcp.json beside the running guard; what only Codex shows.
    -> True on a problem."""
    ok, why = mcp_selftest()
    out_text("mcp server: " + ("answers initialize and tools/list (%s)" % MCP_TOOL if ok else "FAILED: " + why))
    problem = not ok
    home = guard_home(home_arg)
    path = "%s/guard/generated/codex-mcp.toml" % home
    raw = read_quiet(path)
    redo = "%s install --host codex%s" % (guard_cmd(), ' --home "%s"' % home if home_arg else "")
    if raw is None:
        out_text("codex mcp entry: none generated under %s/guard/generated (the MAGOS plugin for Codex starts the server from its mcp.json; "
                 "a Codex without the plugin takes the [mcp_servers.magos] entry that installing the guard for Codex prints)" % home)
    else:
        command, args = codex_toml_entry(raw.decode("utf-8", "replace"))
        script = next((a for a in args if a.endswith("magos_guard.py")), None)
        v = version_of(read_quiet(script)) if script else None
        if not command or not script:
            out_text("codex mcp entry %s: no command and guard script found in it; run %s (%s) and merge the new block" % (path, redo, _USER_RUN))
            problem = True
        elif not os.path.isfile(command) or not os.path.isfile(script):
            out_text("codex mcp entry %s: %s does NOT EXIST; run %s (%s) and merge the new block"
                     % (path, command if not os.path.isfile(command) else script, redo, _USER_RUN))
            problem = True
        elif newer(v, GUARD_VERSION):  # install would refuse it (exit 18): name the newer MAGOS instead of an install command
            out_text("codex mcp entry %s: its guard %s declares %s, NEWER than this guard %s; run doctor from that MAGOS" % (path, script, v, GUARD_VERSION))
            problem = True
        elif v != GUARD_VERSION:
            out_text("codex mcp entry %s: its guard %s declares %s, not this guard %s; run %s (%s) and merge the new block"
                     % (path, script, v or "no version", GUARD_VERSION, redo, _USER_RUN))
            problem = True
        else:
            out_text("codex mcp entry %s: %s %s (guard %s)" % (path, command, script, v))
    plugin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp.json")
    data = read_quiet(plugin)
    if data is not None:
        out_text("codex plugin file: mcp.json %s" % sha256_of(data)[:12])
    out_text("codex: only Codex shows whether it runs the server (/mcp) and trusts the MAGOS hooks (/hooks); its approval policy never "
             "declines every approval dialog, and the user then runs the command in a real terminal")
    return problem


def hermes_route_report():
    """doctor's Hermes route lines (Hermes approval, doctor), printed when the Hermes home is a directory: which route runs the guard in Hermes,
    a MAGOS entry under hooks: that Hermes skips or that stands beside the plugin, and whether Hermes asks.  -> True on a problem: the entry
    beside the plugin route (a double route), or an entry that is the only route and is not approved."""
    hh = hermes_home()
    if not os.path.isdir(hh):
        return False
    r = hermes_route()
    on = hermes_route_on(r)
    problem = False
    if on:
        out_text("hermes route: the plugin %s (guard %s) runs the guard and asks for a user-only command in Hermes's approval prompt" % (r["dir"], r["version"]))
    elif r["plugin"] and r["version"] != GUARD_VERSION:
        out_text("hermes route: the plugin %s holds guard %s, not %s; update it (hermes plugins update magos) and restart Hermes"
                 % (r["dir"], r["version"] or "unversioned", GUARD_VERSION))
    elif r["plugin"] and not r["callbacks"]:  # this guard's version, but an __init__.py that registers no guard callbacks
        out_text("hermes route: the plugin %s holds guard %s, but its __init__.py registers no guard callbacks; update it (hermes plugins update "
                 "magos) and restart Hermes" % (r["dir"], r["version"]))
    elif r["plugin"]:
        out_text("hermes route: magos is not in plugins.enabled of %s; Hermes loads no MAGOS callbacks" % r["config"])
    else:
        out_text("hermes route: no MAGOS plugin under %s/plugins; the entry under hooks: (install --host hermes) runs the guard, and user-only "
                 "commands run in the user's own terminal" % hh.replace("\\", "/"))
    if r["consented"] is False:
        out_text("hermes entry: %s holds the MAGOS entry under hooks:, but %s/shell-hooks-allowlist.json does not list its command, so Hermes skips "
                 "it without a word; approve it once (hooks_auto_accept: true, or HERMES_ACCEPT_HOOKS=1 for hermes acp)" % (r["config"], hh.replace("\\", "/")))
        problem = not on  # the guard then runs nowhere in Hermes
    if on and r["entry"] is True:
        out_text("hermes route: %s also holds a MAGOS entry under hooks:; it denies every user-only command before Hermes can ask and runs the guard "
                 "a second time on every terminal call; remove that entry from the Hermes config, the plugin runs the guard" % r["config"])
        problem = True
    s = hermes_settings(hh)
    if os.environ.get("HERMES_YOLO_MODE", "").strip().lower() in _TRUTHY:
        out_text("hermes approvals: HERMES_YOLO_MODE is set here: Hermes approves without asking, so the guard refuses the click and user-only "
                 "commands run in the user's own terminal")
    elif s["error"]:
        out_text("hermes approvals: %s cannot be read (%s): the guard refuses the click" % (s["path"], s["error"]))
    elif hermes_mode_off(s):
        out_text("hermes approvals: approvals.mode is %s in %s: Hermes approves without asking, so the guard refuses the click and user-only "
                 "commands run in the user's own terminal" % (s["mode"], s["path"]))
    else:
        out_text("hermes approvals: Hermes asks (%s), within %d s; a session /yolo is not visible here"
                 % ("approvals.mode " + s["mode"] if s["mode"] else "approvals.mode unset",
                    s["timeout"] if isinstance(s["timeout"], int) else HERMES_TIMEOUT_S))
    return problem


_VETO = re.compile(r"^MAGOS (?:BLOCKED|拒绝): ", re.M)  # the line the backstop's deny() writes; nothing else counts as its veto
SELFTEST_S = 30.0


def selftest_probe(g):
    """Try to create the unclaimed branch __magos_selftest on a Git budget of its own (not the time the rest of doctor used); a branch the
    backstop let through is deleted again.  -> (exit code, stderr text).  Raises GitFail."""
    probe = Git(g.start, budget=SELFTEST_S)
    rc, _out, err = probe.run("branch", "__magos_selftest", ok=None, full=True)
    if rc == 0:
        probe.run("branch", "-D", "__magos_selftest", ok=(0, 1))
    return rc, err.decode("utf-8", "replace").strip()


def set_report(g, claims, bad_claims, heads):
    """The sets part of doctor: the `sets:` line (printed when sets/ holds a file or a claim carries set=) and one line per problem -> whether
    there was a problem: a lane claim that is missing or differs from the record, an active or ready lane whose branch is gone, a target branch
    that is gone, claims of a set that has no record file (an interrupted registration), and a record that is newer or unreadable."""
    recs, bad = read_sets(g)
    try:
        listed = [f for f in os.listdir(sets_dir(g)) if os.path.isfile(os.path.join(sets_dir(g), f))]
    except OSError:
        listed = []
    carriers = [d for d in claims.values() if claim_set(d) is not None]
    if not listed and not carriers:
        return False
    too_new = [b for b in bad if b.code == "SET_NEWER_FORMAT"]
    out_text("sets: %d, unreadable: %d, newer-format: %d" % (len(recs), len(bad) - len(too_new), len(too_new)))
    lines = []
    for name, rec in sorted(recs.items()):
        for lane in rec["lanes"]:
            status = claim_status(name, lane, claims, bad_claims)
            if status != "ok":
                lines.append("set %s lane %s: claim %s" % (name, lane["id"], "missing" if status == "missing" else "differs"))
            if lane["state"] in ("active", "ready") and real_branch(lane, heads) is None:
                lines.append("set %s lane %s: branch vanished" % (name, lane["id"]))
        if rec["target"] not in heads:
            lines.append("set %s: the target branch %s no longer exists" % (name, rec["target"]))
    ghosts = {}
    for d in carriers:
        if claim_set_record(g, d) is None:  # no record file: a record that exists but cannot be read has its own line below
            ghosts.setdefault(claim_set(d), []).append(d["branch"])
    for name, branches in sorted(ghosts.items()):
        lines.append("claims of set %s without a record: %s" % (name, ", ".join(sorted(branches))))
    for b in too_new:
        lines.append("set record sets/%s was written by a newer MAGOS (v=%s): upgrade this guard (doctor shows its version, install refreshes the copy)" % (_shown(b, 255), b.v))
    lines += ["unreadable set record sets/%s" % _shown(b, 255) for b in bad if b.code == "SET_UNREADABLE"]  # a file name has at most 255 characters: never cut
    for line in lines:
        out_text("  " + line)
    return bool(lines)


_APPROVAL_SAYS = {"terminal": "every user-only command runs in the user's own terminal",
                  "prompt": "Claude Code asks in its own dialog for a user-only command, Codex in its own dialog through the MCP tool magos_approve, "
                            "and Hermes in its approval prompt through the MAGOS Hermes plugin",
                  "auto-safe": "Claude Code and Hermes (through the MAGOS Hermes plugin) run arm, and install to the default guard home without "
                               "--allow-downgrade, without a click and ask for every other user-only command; Codex asks for every user-only "
                               "command through the MCP tool magos_approve"}


def approval_report(g):
    """doctor's approval line: the level magos.approval sets in this repository -> True on a problem (a value that is no level, or one that
    cannot be read: the guard then fails closed to terminal)."""
    try:
        level, raw = approval_level(g)
    except GitFail as err:
        out_text("approval: terminal (magos.approval cannot be read: %s)" % err)
        return True
    if raw is not None and raw.strip().lower() not in APPROVAL_LEVELS:
        out_text("approval: terminal (magos.approval is %s, which is not terminal, prompt or auto-safe, so the guard fails closed; set it in "
                 "your own terminal: git config --local magos.approval prompt)" % json.dumps(_shown(raw, 80), ensure_ascii=False))
        return True
    out_text("approval: %s (%s): %s" % (level, "magos.approval unset" if raw is None else "magos.approval " + raw, _APPROVAL_SAYS[level]))
    return False


def cmd_doctor(args):
    me = os.path.abspath(__file__)
    out_text("guard %s (%s) at %s" % (GUARD_VERSION, sha256_of(read_bytes(me) or b"")[:12], me.replace("\\", "/")))
    ok = sys.version_info >= (3, 9)
    out_text("python %s %s" % (sys.version.split()[0], "ok" if ok else "TOO OLD (need 3.9+)"))
    problems = not ok
    try:
        ver = git_version_text()
        out_text("git %s" % ver)
        old = git_too_old(ver)
        if old:
            out_text("git %s TOO OLD for the lane guard (need 2.36+)" % old)
            problems = True
    except GitFail as err:
        out_text("git: %s" % err)
        ver = None
    problems = copy_report(args.home) or problems  # before the repository: the copy matters wherever the Codex and Hermes hooks run
    problems = codex_report(args.home) or problems
    problems = hermes_route_report() or problems
    if ver is None:
        return 1
    g = open_repo(args.repo)
    if g is None:
        out_text("repository: none at %s (guard is inert here)" % args.repo)
        out_text("approval: prompt (no repository): install asks in Claude Code's dialog, in Codex's (magos_approve) and in Hermes's approval prompt "
                 "(MAGOS Hermes plugin)")
        return 1 if problems else 0
    claims, bad = read_claims(g)
    heads = list_refs(g)[0]
    mode = guard_mode(g)
    too_new = [b for b in bad if b.code == "CLAIM_NEWER_FORMAT"]
    out_text("repository: %s (mode %s); claims: %d, unreadable: %d, newer-format: %d" % (g.common, mode, len(claims), len(bad) - len(too_new), len(too_new)))
    for b in bad:
        out_text("  %s" % (b.text if b.code == "CLAIM_NEWER_FORMAT" else "unreadable claims/%s" % b.replace(os.sep, "/")))
    approval_problem = approval_report(g)
    set_problems = set_report(g, claims, bad, heads)
    orphans = [d["branch"] for d in claims.values() if d["branch"] not in heads and not d["worktree"] and not (is_integration_claim(d) and claim_set_record(g, d))]
    out_text("claims without a branch or planned worktree: %s" % (", ".join(orphans) or "none"))
    refused = [d["branch"] for d in claims.values() if alias_problem(d["branch"])]
    if refused:  # they keep allowing their branches; plan refuses the names, so the lanes can only be released and planned again
        out_text("claims under a name plan refuses (Windows alias rule): %s; release them and plan the lanes under another name" % ", ".join(refused))
    wts = [w for w in worktrees(g) if not w["bare"] and not w["prunable"]]
    dirs = {pkey(hooks_dir(g, w["path"])) for w in wts}
    hook = os.path.join(hooks_dir(g), "reference-transaction")
    mine = os.path.exists(hook) and MARK in read_text(hook)
    same = mine and read_text(hook).replace("\r\n", "\n") == HOOK_SH
    rearm = "re-arm (%s): %s arm" % (_USER_RUN, guard_cmd())
    layer = "installed" if same else "installed but different from this version; " + rearm if mine else "not installed"
    out_text("git layer: %s; hook directories: %d" % (layer, len(dirs)))
    bypassed = mode == "armed" and g.run("config", "--get", "core.hooksPath", ok=(0, 1))[0] == 0
    if bypassed:
        out_text("core.hooksPath is set: git no longer runs the backstop")
    problems = problems or bool(bad) or set_problems or approval_problem or len(dirs) > 1 or (mode == "armed" and not same) or bypassed
    recorded = os.path.join(store(g), "guard")
    if os.path.exists(os.path.join(store(g), "ARMED")) and os.path.isfile(recorded):
        cmd = read_text(recorded).strip()
        m = re.search(r'"([^"]+)"', cmd)
        script = m.group(1) if m else (cmd.split() or [""])[-1]
        if not script or not os.path.isfile(script):
            out_text("backstop guard command %s: the script is MISSING, so a denial names a command that cannot run; %s" % (cmd, rearm))
            problems = True
        else:
            v = version_of(read_quiet(script))
            if v != GUARD_VERSION and not newer(v, GUARD_VERSION):  # older, or no version at all (before 1.0.2)
                out_text("backstop guard command %s: its script declares %s, older than this guard %s, so a denial sends agents to an older guard; "
                         "refresh that copy with install when it is the copy, then %s" % (cmd, v or "no version", GUARD_VERSION, rearm))
                problems = True
            else:
                out_text("backstop guard command: %s" % cmd)
    if mode == "armed" and same:
        lock = os.path.join(g.common, "refs", "heads", "__magos_selftest.lock")
        why = ("the branch __magos_selftest already exists" if "__magos_selftest" in heads else
               "a claim for __magos_selftest exists" if fold("__magos_selftest") in claims or newer_claim(bad, "__magos_selftest") else
               "%s exists (a ref lock an earlier git command left behind; remove it when no git command runs)" % lock.replace("\\", "/")
               if os.path.exists(lock) else None)
        rc, err = None, ""
        if not why:
            try:
                rc, err = selftest_probe(g)
            except GitFail as fail_:
                why = "the probe failed: %s: %s" % (fail_.code, fail_)
        if rc == 0:
            out_text("self-test FAILED: the backstop did not veto an unclaimed branch")
            problems = True
        elif rc is not None and _VETO.search(err):
            out_text("self-test ok: an unclaimed branch is vetoed")
        else:
            out_text("self-test inconclusive: %s" % (why or "git exited %d without a MAGOS veto: %s" % (rc, err[-300:] or "(no message)")))
            problems = True
    return 1 if problems else 0


class Parser(argparse.ArgumentParser):
    """Options are never abbreviated: `--rep` is a usage error, not `--repo` (the host hook matches the spellings argparse takes)."""

    def __init__(self, *args, **kw):
        kw["allow_abbrev"] = False
        super().__init__(*args, **kw)
        self.hidden = set()  # the values of --approval it parsed; build_parser gives the subcommand parsers the main parser's set

    def parse_known_args(self, args=None, namespace=None):
        words = [str(w) for w in (sys.argv[1:] if args is None else args)]
        for k, w in enumerate(words):
            if w.startswith("--approval="):
                self.hidden.add(w[len("--approval="):])
            elif w == "--approval" and k + 1 < len(words):
                self.hidden.add(words[k + 1])
        return super().parse_known_args(args, namespace)

    def error(self, message):
        """A usage error never shows an approval token: every value of --approval (--approval=<x>, or the word after --approval) that was
        parsed is shown as <redacted>, wherever the message names it; every other word is shown as written."""
        for v in sorted((v for v in self.hidden if v), key=len, reverse=True):
            message = re.sub(r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])" % re.escape(v), "<redacted>", message)
        super().error(message)


def build_parser(repo_default=None):
    """The guard's argument parser: main() uses it with repo_default os.getcwd(), and the Claude Code hook reads a direct invocation with it
    (repo_default None: --repo unset).  Every user-only subcommand (USER_ONLY) takes the option --approval, hidden from its help."""
    lang0 = os.environ.get("MAGOS_LANG") if os.environ.get("MAGOS_LANG") in ("zh", "en") else "zh"
    common = Parser(add_help=False)  # the same options work before or after the subcommand
    ap = Parser(prog="magos_guard", description=__doc__.splitlines()[0])  # subcommand parsers are built with the same class
    for parser, dflt in ((ap, None), (common, argparse.SUPPRESS)):
        parser.add_argument("--repo", default=repo_default if dflt is None else dflt)
        parser.add_argument("--lang", choices=("zh", "en"), default=lang0 if dflt is None else dflt)
        parser.add_argument("--json", action="store_true", default=False if dflt is None else dflt)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "check"):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("--branch", required=True)
        p.add_argument("--paths", nargs="*")
        p.add_argument("--manifest")
        if name == "plan":
            p.add_argument("--worktree", default="")
            p.add_argument("--amend", action="store_true")
        else:
            p.add_argument("--target")
    sub.add_parser("list", parents=[common]).add_argument("--drift", action="store_true")
    p = sub.add_parser("release", parents=[common])
    p.add_argument("--branch", required=True)
    p.add_argument("--reason", default="")
    p = sub.add_parser("override", parents=[common])
    p.add_argument("--fingerprint", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("hook", parents=[common])
    p.add_argument("host", choices=("claude", "codex", "hermes"))
    p.add_argument("event", choices=("pre-tool",))
    p.add_argument("--hermes-gate", choices=HERMES_GATES, help=argparse.SUPPRESS)  # set by the MAGOS Hermes plugin only (Hermes approval)
    p = sub.add_parser("arm", parents=[common])
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("disarm", parents=[common]).add_argument("--dry-run", action="store_true")
    p = sub.add_parser("install", parents=[common])
    p.add_argument("--host", required=True, choices=("claude", "codex", "hermes"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--home")
    p.add_argument("--allow-downgrade", action="store_true")
    sub.add_parser("doctor", parents=[common]).add_argument("--home")
    sub.add_parser("version", parents=[common])
    p = sub.add_parser("set-plan", parents=[common])
    p.add_argument("--set", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--amend", action="store_true")
    p.add_argument("--expect-revision", type=revision_arg)
    p = sub.add_parser("set-show", parents=[common])
    p.add_argument("--set", required=True)
    p.add_argument("--drift", action="store_true")
    p = sub.add_parser("set-update", parents=[common])
    p.add_argument("--set", required=True)
    p.add_argument("--expect-revision", type=revision_arg, required=True)
    p.add_argument("--lane", required=True)
    p.add_argument("--state", required=True, choices=("active", "ready", "integrated", "blocked"))
    p.add_argument("--head")
    p.add_argument("--note")
    p.add_argument("--integration")
    p = sub.add_parser("set-release", parents=[common])
    p.add_argument("--set", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--abandon", action="store_true")
    sub.add_parser("mcp", parents=[common])  # the MCP approval server, which only the host starts (Codex approval)
    for u in USER_ONLY:
        sub.choices[u.name].add_argument("--approval", help=argparse.SUPPRESS)
    for p in sub.choices.values():  # a usage error of a subcommand also hides a value the main parser saw (Parser.error)
        p.hidden = ap.hidden
    sub.metavar = "{%s}" % ",".join(n for n in sub.choices if n not in HOST_ONLY)  # mcp is hidden (help=SUPPRESS would print ==SUPPRESS==)
    return ap


def parse_quiet(words):
    """The guard's own reading of `words` with --repo unset, or None when its parser refuses them (or they ask for help); prints nothing."""
    ap = build_parser(None)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return ap.parse_args(list(words))
    except SystemExit:
        return None


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser(os.getcwd())
    try:
        args = ap.parse_args(argv)
        if args.cmd == "set-plan" and args.amend != (args.expect_revision is not None):
            ap.error("set-plan: --amend and --expect-revision go together")
        if args.cmd == "hook" and args.hermes_gate is not None and args.host != "hermes":
            ap.error("--hermes-gate goes with hook hermes")
    except SystemExit as err:
        if any(a == "hook" for a in (sys.argv[1:] if argv is None else argv)) and err.code:
            return 1  # a usage error is a failure (the launcher maps it), never a deny
        raise
    args.argv = list(sys.argv[1:] if argv is None else argv)  # the argument list an --approval token was issued for
    try:
        if args.cmd in ("plan", "check"):
            return cmd_plan(args, args.cmd == "plan")
        return {"list": cmd_list, "release": cmd_release, "override": cmd_override, "hook": cmd_hook, "arm": cmd_arm, "disarm": cmd_disarm,
                "install": cmd_install, "doctor": cmd_doctor, "version": cmd_version, "set-plan": cmd_set_plan, "set-show": cmd_set_show,
                "set-update": cmd_set_update, "set-release": cmd_set_release, "mcp": cmd_mcp}[args.cmd](args)
    except GitFail as err:
        return fail(args, err.code, str(err), "MAGOS guard: %s: %s" % (err.code, err))
    except BaseException as err:  # never exit 1 silently: every failure is a deny-class exit
        if args.cmd == "hook":
            raise
        text = "%s: %s" % (type(err).__name__, err)
        return fail(args, "INTERNAL_ERROR", text, "MAGOS guard internal error: " + text)


def fail(args, code, text, line):
    """A Git failure or an internal error of a command: the line on stderr and, with --json, a deny object on stdout.  Exit 11."""
    sys.stderr.write(line + "\n")
    if args.json and args.cmd != "hook":
        out_text(json.dumps({"decision": "deny", "code": "UNKNOWN", "unknowns": [{"code": code, "text": text}], "message": line,
                             "exit_code": EXIT["UNKNOWN"]}, ensure_ascii=False))
    return EXIT["UNKNOWN"]


if __name__ == "__main__":
    sys.exit(main())
