#!/usr/bin/env python3
"""MAGOS lane guard: a lane's files are planned before the lane exists; creating a lane that overlaps another lane is denied.

One stdlib-only file (Python >= 3.9): CLI, PreToolUse hook entry for Claude Code / Codex / Hermes, and the sh body of the git
reference-transaction backstop. check / list / hook never write; plan / release / override / arm / disarm / install write only the
claim store under <git-common-dir>/magos and the files they print.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import shlex
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

GUARD_VERSION = "1.0.2"  # the one version constant of the guard; equals the package version (plugin.json, plugin.yaml, SKILL.md)
CLAIM_FORMAT = 1  # the claim file format this guard reads and writes (line `v=`); a claim of a newer format is never misread
GS = "**"
BUDGET_S, MAX_CLAIMANTS, MAX_REMOTES, MAX_ENTRIES, LOCK_S, MAX_TEXT = 18.0, 120, 300, 200, 30.0, 200000
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
        "DOWNGRADE_REFUSED": 18}
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
                "④ 仅在用户明确同意后，由用户本人在自己的终端运行：{cmd} override --fingerprint {fp} --reason \"<用户原话>\"；覆盖只通过 plan 生效，之后必须重新 plan（re-plan）。",
                "Options: (1) shrink or split the manifest; (2) wait until they are merged into {target}; (3) if the other lane is merged or abandoned, release its claim with "
                "{cmd} release --branch <their branch> (unmerged work is never released); (4) only with the user's explicit consent, "
                "the USER runs in their own terminal: {cmd} override --fingerprint {fp} --reason \"<user's words>\"; the override takes effect only through plan, "
                "so a re-plan is required."),
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
    "need_tty": ("MAGOS：这条命令只能由用户在真实终端里执行（当前标准输入不是控制台）。", "MAGOS: only the user may run this, in a real terminal (stdin is not a console)."),
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


def render(lang, v, name):
    """Human message of a verdict, naming every conflicting branch / worktree / evidence kind / files."""
    if v["code"] == "NO_MANIFEST":
        return T(lang, "nomanifest", b=name) + "\n" + T(lang, "how_plan", cmd=guard_cmd(), b=name)
    L = []
    if v.get("conflicts"):
        L.append(T(lang, "conflict", b=name))
    elif v.get("unknowns"):
        L.append(T(lang, "unknown", b=name))
    for i, c in enumerate(v.get("conflicts", []), 1):
        L.append(T(lang, "item", i=i, b=c["branch"] or "(detached)", w=", ".join(c["worktrees"]) or "-", p=T(lang, "planned") if c.get("planned") else ""))
        for e in c["evidence"]:
            k = T(lang, "k_" + e["kind"])
            L.append(T(lang, "ev_decl", k=k, t=_few(e["theirs"]), m=_few(e["matched"])) if e["kind"] == "declared"
                     else T(lang, "ev", k=k, n=len(e["files"]), f=_few(e["files"]), m=_few(e["matched"])))
    L += ["[%s] %s" % (u["code"], u["text"]) for u in v.get("unknowns", [])]
    if v["decision"] == "deny" and v.get("unknowns") and all(u["code"] == "CLAIM_NEWER_FORMAT" for u in v["unknowns"]):
        L.append(T(lang, "newer_only"))  # no shrink, wait, release or override: only a guard that reads that format can act on the claim
    elif v["decision"] == "deny" and v.get("fingerprint"):
        L.append(T(lang, "options", target=v.get("target", {}).get("name", "?"), cmd=guard_cmd(), fp=v["fingerprint"]))
    return "\n".join(L + ["(%s) %s" % (w["code"], w["text"]) for w in v.get("warnings", [])])


# ---------------------------------------------------------------- pure: command parsing (a UX layer: the git hook is the hard stop)
_BAD_NAME = re.compile(r"[\s~^:?*\[\\\x00-\x1f]|\.\.|^-|^/|/$|\.lock$")


_OPENERS = ("if", "while", "until", "for", "select", "case")  # POSIX-shell words that open a compound command: what runs inside may not run
_CLOSERS = ("fi", "done", "esac")
_CONT = re.compile(r"(?:\\|`)\r?\n[ \t]*")  # a line continuation


class _Seg(list):
    """One command of a line: a list of (word, dynamic); `at` is the offset of its first word in the text the lexer read, `sub` tells that
    it starts inside a word's $( .. ), <( .. ) or PowerShell ( .. ) (text substituted into another command)."""
    at, sub = 0, False


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
    only before $, a backtick, '"', a backslash and a newline; in cmd a caret outside double quotes does the same; PowerShell and a shell
    the hook cannot name keep their backslashes (path separators there)."""
    segs, cur, parens, close, cases, at = [], [], [], [False], [], [0, False]  # at: offset of the segment's first word, and whether it is substituted
    st = {"w": [], "dyn": False, "has": False, "open": False, "q": False, "b": 0, "kw": True, "inword": 0}  # kw: cur holds reserved words only
    kw, ps, posix = sh not in ("ps", "cmd"), sh == "ps", sh == "bash"
    escape = "\\" if posix else "^" if sh == "cmd" else None  # the character that quotes the next one outside quotes

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
        st.update(w=[], dyn=False, has=False, open=False, q=False, b=0)
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
        cur.append((w, dyn))
        st["kw"] = st["kw"] and w in _KEYWORDS

    def seg_end(mark=None):
        word_end()
        flush()
        if close[0]:
            segs.append(")")
            close[0] = False
        if mark:
            segs.append(mark)
    cmd = _CONT.sub(" ", cmd)
    i, n = 0, len(cmd)
    while i < n:
        c, mode = cmd[i], cases[-1] if cases else None
        nxt, prev = cmd[i + 1:i + 2], cmd[i - 1:i]
        if c == escape and nxt:  # an escaped character: literal, part of the word, never special (an escaped word is no reserved word)
            if not st["has"] and not cur:
                at[:] = [i, st["inword"] > 0]
            st["w"].append(nxt)
            st["has"], st["q"] = True, True
            i += 2
            continue
        if mode == "pat" and c in ")|" and st["w"] == list("esac") and not st["q"]:  # `esac)` / `esac|`: the case ends before the ')' or '|'
            word_end()
            mode = cases[-1] if cases else None
        if c in " \t\r" or (c == "\n" and mode == "pat"):
            word_end()
        elif mode == "pat" and c == "(" and not st["has"]:
            pass  # the optional '(' before a pattern
        elif mode == "pat" and c == "|":
            word_end()
        elif mode == "pat" and c == ")" and not st["open"]:
            seg_end()
            cases[-1] = "body"
        elif c in ";\n&|" or (c in "()" and not st["has"] and not cur) or (c == ")" and not st["open"]) or \
                (c == "{" and (not st["has"] or (ps and prev not in "$@"))) or (c == "}" and (not st["has"] or (ps and not st["b"]))):
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
        elif c in "'\"":
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
            i = j
        else:
            if not st["has"] and not cur:
                at[:] = [i, st["inword"] > 0]
            st["w"].append(c)
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
_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--attr-source", "--super-prefix", "--list-cmds"}
# The words that decide whether a command line is walked at all, read on the text with every escape character removed (g\it is git).
_GATE = re.compile(r"git|gh|gt|claude|eval|iex|invoke-expression|\.sh|\.ps1|source|-enc|base64", re.I)


def _gated(text):
    return _GATE.search(re.sub(r"[\\`^]", "", text)) is not None


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
    ancestor)."""
    follow = None


def _missing(target, prior, follow=None):
    m = _Missing(target)
    m.prior, m.follow = prior, follow
    return m


def _join(base, p):
    """`p` resolved against the directory `base` (None: unknown); None when it names no directory we may judge.  Absolute spellings are
    classified here and never with os.path.isabs, whose Windows result for a rooted path without a drive differs from Python 3.13 on.
    A relative path after a failed cd keeps the _Missing directory (the shell is still in its prior directory)."""
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
    return base if isinstance(base, _Missing) else os.path.normpath(os.path.join(base, p))


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
    return _join(getattr(here, "prior", here), value)


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
    A name is dropped when git would refuse it anyway (spaces, '..', a leading dash, a backslash that quoting kept ...).
    redirect: True when the record is judged in the git directory `gitdir` (--git-dir / GIT_DIR; None: it cannot be resolved)."""
    names = [n for n in names if _BAD_NAME.search(n) is None or re.search(r"[$`%()]", n)]
    return {"verb": verb, "names": names, "cwd": cwd, "dynamic": dynamic or any(re.search(r"[$`%()]", n) for n in names), "kind": kind, "path": path, "tool": tool,
            "commit": commit, "redirect": False, "gitdir": None}


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
        if len(key) >= 3 and any(name.startswith(key) for name in longs):
            return tok.split("=", 1)[1] if "=" in tok else ""
        return None
    return _short_value(tok, shorts)


def _branch_moves(args):
    """Does `git branch` rename or copy?  A short-option word holding m, M, c or C before a letter that takes a value (-u), or a long option
    of at least three letters that is a prefix of exactly one of --move and --copy."""
    for t in args:
        if t.startswith("--"):
            key = t[2:].split("=", 1)[0]
            if len(key) >= 3 and sum(full.startswith(key) for full in ("move", "copy")) == 1:
                return True
        elif t.startswith("-"):
            for ch in t[1:]:
                if ch in "mMcC":
                    return True
                if ch == "u":
                    break
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


_GLOB_WHY = "a glob refspec creates branches whose names the hook cannot list"
_PUSH_WHY = "the repository a push writes to is dynamic"


def _requote(words, dyn):
    """Words back into a command line: a literal word that holds a space or a shell character is quoted; a dynamic word stays as written."""
    return " ".join(shlex.quote(w) if not d and re.search(r"[\s'\"$`;&|<>()\\]", w) else w for w, d in zip(words, dyn))


def _rebase_exec(args):
    """The command texts `git rebase` runs: the value of -x / --exec / --exec= (also bundled, -qx <cmd>, and attached, -x<cmd>)."""
    out, k = [], 0
    while k < len(args):
        t = args[k]
        if t == "--exec" and k + 1 < len(args):
            out.append(args[k + 1])
            k += 1
        elif t.startswith("--exec="):
            out.append(t[7:])
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
            return interpret(val[1:] + " " + " ".join(a), here, depth + 1, gitdir=rd, sh="bash", work=work)
        vw = [w for seg in split_command(val) for w in seg]
        return parse_git(["git"] + [w for w, _ in vw] + a, [False] * (len(vw) + 1) + list(ad), here, defs, depth + 1, rd, work, sh)

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
        if any(t in ("-d", "-D", "--delete", "-l", "--list", "--show-current", "-u", "-r", "-a", "--contains", "--merged", "--no-merged", "--unset-upstream",
                     "--points-at", "--sort", "--format", "--edit-description") or t.startswith(("--set-upstream-to", "--list")) for t in a):
            return []
        pos = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-")]
        move = _branch_moves(a)  # rename / copy: the last name is the new branch
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
    if sub == "symbolic-ref":
        pos = [t for t in a if not t.startswith("-")]
        return [C(sub, [pos[1][11:]], here, False)] if len(pos) >= 2 and pos[0] == "HEAD" and pos[1].startswith("refs/heads/") else \
            [C(sub, [pos[0][11:]], here, False)] if pos and pos[0].startswith("refs/heads/") else []
    if sub == "update-ref":
        if "-d" in a:
            return []
        if "--stdin" in a:  # the instructions arrive on stdin: interpret() reads them from the command text
            return [dict(C(sub, [], here, False), stdin=True)]
        names = [t[11:] for t in a if t.startswith("refs/heads/")]
        return [C(sub, names, here, False)] if names else []
    if sub in ("fetch", "pull", "push"):
        pk = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-")]
        names, glob = [], False
        for t, _d in pk[1:]:  # the destinations of the refspecs, under refs/heads/ or bare
            m = re.fullmatch(r"\+?[^:]*:(?:refs/heads/)?([^:]+)", t)
            if m and not m.group(1).startswith("refs/"):
                glob = glob or "*" in m.group(1)
                names += [] if "*" in m.group(1) else [m.group(1)]
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


def _heredocs(cmd):
    """-> (command text without heredoc bodies, [bodies fed to a shell]).  A body fed to cat or a file is data, not a command."""
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
            if re.search(r"(?:^|[|;&\s])(?:sudo\s+)?(?:(?:ba|z|da|k)?sh|powershell|pwsh|source|iex|invoke-expression)\b", line, re.I):
                bodies.append("\n".join(body))
    return "\n".join(out), bodies


def _git_subcommands(text):
    """The subcommand after every `git` word (its first non-option word): one right-to-left pass, linear in the text."""
    toks, nxt, subs = text.split(), None, []
    for k in range(len(toks) - 1, -1, -1):
        if nxt is not None and re.search(r"(?:^|\W)git$", toks[k]):
            m = re.match(r"[A-Za-z][\w-]*", toks[nxt])
            subs += [m.group(0)] if m else []
        if not toks[k].startswith("-"):
            nxt = k
    return subs


_PS_ENV = re.compile(r"\$\{?env:([A-Za-z_][A-Za-z0-9_]*)\}?(\+?=)?(.*)$", re.I | re.S)
_ENV_PATH = re.compile(r"env:[\\/]?([A-Za-z_][A-Za-z0-9_]*)", re.I)
_SET_ENV = re.compile(r"setenvironmentvariable\(([^)]*)", re.I)
_TOOL_SHELL = {"Bash": "bash", "Monitor": "bash", "PowerShell": "ps"}  # the shell a hooked tool runs its command in (other tools: not known)
_SHELL_OF = dict([(s, "bash") for s in _SHELLS] + [("powershell", "ps"), ("pwsh", "ps"), ("cmd", "cmd")])


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
    out, early, env, galias, whole, over = [], [], {}, {}, cmd, []
    states = [[cwd, _GitDirs(gitdir, sh), list(dirs)]]
    contexts, bash = [], sh == "bash"

    def note(here, cands):
        if len(contexts) <= MAX_CONTEXTS and (here, cands) not in contexts:
            contexts.append((here, cands))
    note(cwd, states[0][1].cands())
    cmd, bodies = _heredocs(cmd)
    cmd = _CONT.sub(" ", cmd)  # the offsets of the substituted texts below are the lexer's
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
                words[k], dyn[k] = nw, bool(re.search(r"[$`%()]", nw)) if nw != w else dyn[k]
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
        while i < len(words) and (_ASSIGN.match(words[i]) or words[i].lower() in _WRAP + _KEYWORDS or words[i] == "&" or (i == 0 and words[i].endswith(")"))):
            wrapped, vals = words[i].lower() in _WRAP, _SU_VALUE if words[i].lower() in ("sudo", "doas") else _ENV_VALUE if words[i].lower() == "env" else ()
            i += 1
            if wrapped:  # the wrapped program is the next known one; the value of a wrapper option (-u git) is never the program
                i = next((k for k in range(i, len(words)) if _exe(words[k]) in _KNOWN and words[k - 1] not in vals), len(words))
        if i >= len(words):
            return False, []
        exe, rest = _exe(galias.get(words[i], words[i])), words[i + 1:]
        script = re.search(r"\.(sh|ps1|bash)$", words[i], re.I) is not None
        if not i and exe not in _STATEFUL and not script:  # neither depends on nor changes the state
            return False, []
        isolated = not _ALONE.isdisjoint(low[:i])  # a builtin behind a program wrapper runs in no shell: env cd x changes nothing
        chdir = _wrapped_dir(words, dyn, i)  # env -C <dir> and the privilege wrapper -D <dir>: the wrapped program runs in <dir>
        kept = [False] * (i + 1)  # kept[k]: a -E / --preserve-env stands after word k (the wrapper keeps the environment)
        for k in range(i - 2, -1, -1):
            kept[k] = kept[k + 1] or words[k + 1] == "-E" or words[k + 1].startswith("--preserve-env")
        work[0] -= STEP_COST * (len(states) - 1)
        finals = []
        for st in states:
            here, gds, dirs = st
            run = here if chdir is None else None if chdir[1] else _join(here, chdir[0])  # where the invocation runs (None: unknown)
            inv = gds.copy()  # GIT_DIR of this invocation: prefix and env assignments set it, env -u / -i remove it
            after_env = after_exec = False  # an env / exec word stands before word k
            for k in range(i):
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
                k = [w.lower() for w in rest].index("-argumentlist") + 1 if "-argumentlist" in [w.lower() for w in rest] else len(rest)
                args = rest[k] if k < len(rest) else ""
                prog = next((w for w in rest if _exe(w) == "git"), None)
                out.extend(interpret("git " + args.replace(",", " "), run, depth + 1, aliases, cands, "ps", work=work) if prog else [])
            elif exe == "find" and depth < 3 and any(w in ("-exec", "-execdir") for w in rest):
                k = next(k for k, w in enumerate(rest) if w in ("-exec", "-execdir"))
                out.extend(interpret(" ".join(rest[k + 1:]).replace("\\;", " "), run, depth + 1, aliases, cands, work=work))
            elif exe in _SHELLS + ("powershell", "pwsh", "cmd") and depth < 3:
                handled = False
                for k, w in enumerate(rest):
                    if re.fullmatch(r"-(enc|encodedcommand)", w.lower()) and k + 1 < len(rest):
                        try:
                            text = base64.b64decode(rest[k + 1]).decode("utf-16-le")
                        except ValueError:
                            text = "git branch $opaque"  # an undecodable encoded command counts as a dynamic creation
                        out.extend(interpret(text, run, depth + 1, aliases, cands, _SHELL_OF[exe], work=work))
                        handled = True
                        break
                    if re.fullmatch(r"-[a-z]*c|-command|/c|/k|//c", w.lower()) and k + 1 < len(rest):
                        out.extend(interpret(rest[k + 1] if exe in _SHELLS else " ".join(rest[k + 1:]), run, depth + 1, aliases, cands, _SHELL_OF[exe],
                                             work=work))
                        handled = True
                        break
                files = [w for k, w in enumerate(rest) if not w.startswith("-") and (k == 0 or rest[k - 1].lower() != "-command")]  # option values come first
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
            continue
        if ev == "|":
            continue
        if isinstance(ev, str) and ev in closing:
            if not any(f["kind"] == closing[ev] for f in frames[1:]):
                continue
            while True:
                f = frames.pop()
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
            changed, finals = segment([w for w, _ in ev], [d for _, d in ev])
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
    if any(cr.get("stdin") for cr in out):  # update-ref --stdin: the instructions are in the text that feeds it, or nowhere the hook can see
        named = _cr("update-ref", re.findall(r"(?:create|update)\s+refs/heads/([^\s\"']+)", whole), None, False)
        shown = bool(named["names"]) or re.search(r"\b(?:create|update|delete|verify|option|start|prepare|commit|abort)\s", whole) is not None
        out = [dict(cr, names=named["names"], dynamic=named["dynamic"] or not shown) if cr.pop("stdin", False) else cr for cr in out]
    elif depth < 3 and not any(cr["verb"] == "update-ref" for cr in out) and \
            any("--stdin" in s.partition("update-ref")[2] for s in re.split(r"[\n|;&]", whole) if "update-ref" in s):  # fed to a git the walk did not see
        names = re.findall(r"(?:create|update)\s+refs/heads/([^\s\"']+)", whole)
        early += [_with_rds(_cr("update-ref", names, h, False), h, c) for h, c in contexts[:MAX_CONTEXTS]] if names else []
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
                        "unlink truncate shred rmdir rd ln mklink rename-item rni ri mi".split())
_COPIES = ("cp", "copy-item")  # tested on their destination only, unless they copy as a link
_WRITE_HINT = re.compile(r">|\b(?:%s|sed|find)\b" % "|".join(re.escape(w) for w in sorted(_WRITE_CMDS, key=len, reverse=True)), re.I)
_USER_ONLY = ("override", "arm", "disarm", "install")
_READ_FLAGS = ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope")
_ENV_WRITE = re.compile(r"^(?:GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\d+|VALUE_\d+)=|\$env:GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\d+|VALUE_\d+)$)", re.I)
_USER_MSG = "override / arm / disarm / install are user-only"
_STATE_MSG = "the hooks, refs and claim store under .git and the guard home are the guard's state"
_CHILD_FLAG = re.compile(r"-[a-z]*c|-command|/c|/k|//c")


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


def _user_only(rest, launcher):
    """Is the subcommand in `rest` (the words after a guard word) user-only?  The launcher's leading --strict, the global options in any
    spelling argparse ever took, and a `--` (from Python 3.13 on argparse takes the word after it as the subcommand) are skipped."""
    k = 1 if launcher and rest[:1] and _bare(rest[0]) == "--strict" else 0
    while k < len(rest) and _bare(rest[k]).startswith("--"):
        t = _bare(rest[k])
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
    return k < len(rest) and (rest[k] in _USER_ONLY or _bare(rest[k]) in _USER_ONLY)


def _child_text(words):
    """The text the first child shell among `words` runs: bash / sh / zsh / dash / ksh -c, cmd /c and /k, powershell and pwsh -Command, -c
    or -EncodedCommand."""
    for i, w in enumerate(words):
        exe = _exe(_bare(w))
        if exe not in _SHELLS + ("powershell", "pwsh", "cmd"):
            continue
        rest = words[i + 1:]
        for k, r in enumerate(rest[:-1]):
            flag = _bare(r).lower()
            if re.fullmatch(r"-(enc|encodedcommand)", flag):
                try:
                    return base64.b64decode(rest[k + 1]).decode("utf-16-le")
                except ValueError:
                    return None
            if _CHILD_FLAG.fullmatch(flag):
                return rest[k + 1] if exe in _SHELLS else " ".join(rest[k + 1:])
        return None
    return None


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
    """The destination of a plain cp / Copy-Item (-t / --target-directory, -Destination, else the last positional argument), or None when cp
    copies as a link (-l, --link, -s, --symbolic-link): a link to a guard file lets a later write change the guard."""
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
        return [a for a in args if not a.startswith("-")][-1:]
    pos, k = [], 0
    while k < len(args):
        a = args[k]
        name = a[1:].rstrip(":").lower() if a.startswith("-") and len(a) > 1 else None
        if name and len(name) >= 3 and "destination".startswith(name):
            return args[k + 1:k + 2]
        if name and any(full.startswith(name) for full in ("path", "literalpath", "filter", "include", "exclude", "credential", "tosession", "fromsession")):
            k += 2
            continue
        pos += [] if name else [a]
        k += 1
    return pos[-1:]


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


def protected(text, depth=0, roots=(), lazy=None):
    """-> (scope, reason) or None.  scope 'always': user-only subcommands and magos.* config; 'guarded': edits of the guard's own state that
    matter once claims or the hook exist.  Words are inspected, never the whole text, so a commit message or a grep for these names passes;
    every keyword and path test reads each word as written and with its escape characters removed.  The text of a child shell (bash -c,
    cmd /c, powershell -Command ...) and a quoted word that names the guard script or its launcher are read with every check, to depth 3.
    `roots`: the absolute guard-home and Hermes-plugin directories (pkey form) whose absolute spellings count as the guard's state; `lazy`
    gives the store's root (see _state_word)."""
    if len(text) > MAX_TEXT:
        return "guarded", "the command is too long to inspect"
    for seg in split_command(_heredocs(text)[0]):
        found = _protected_words([w for w, _ in seg], depth, roots, lazy)
        if found:
            return found
    return None


def _protected_words(words, depth, roots, lazy):
    lows = [w.lower() for w in words]
    bares = [_bare(w).lower() for w in words]
    seen = set(lows) | set(bares)

    def any_word(pred):
        return any(pred(x) for x in lows) or any(pred(x) for x in bares)
    for i, w in enumerate(words):
        kind = _guard_word(w)
        if kind and _user_only(words[i + 1:], kind == "launcher"):  # also behind start, cmd /c start or Start-Process: the word is found anywhere
            return "always", _USER_MSG
        if depth < 3 and re.search(r"\s", w) and re.search(r"magos_guard|run-guard", w, re.I):  # Start-Process ... -ArgumentList '<guard> disarm'
            found = protected(w, depth + 1, roots, lazy)
            if found:
                return found
    child = _child_text(words) if depth < 3 else None
    found = protected(child, depth + 1, roots, lazy) if child else None
    if found:
        return found
    reads = any(f in seen for f in _READ_FLAGS)
    magos = any_word(lambda x: x.startswith("magos."))
    if magos and not reads and ("config" in seen or _aliased_git(bares)):
        return "always", "magos.* git config switches"
    if ("config" in seen and "core.hookspath" in seen and not reads) or any_word(lambda x: x.startswith("core.hookspath=")) or \
            ("config" in seen and "--worktree" in seen) or any(_ENV_WRITE.match(w) or _ENV_WRITE.match(_bare(w)) for w in words):
        return "guarded", "core.hooksPath / GIT_CONFIG_* / worktree config can switch the git layer off"
    e = next((k for k, w in enumerate(words) if not _ASSIGN.match(w) and bares[k] not in _WRAP), None)
    exe = _exe(bares[e]) if e is not None else ""
    if exe in _WRITE_CMDS or (exe == "sed" and "-i" in words) or (exe == "find" and "-delete" in seen):
        targets = _copy_destination(exe, words[e + 1:]) if exe in _COPIES else None
        if any(_state_word(w, roots, lazy) for w in (words[e + 1:] if targets is None else targets)):
            return "guarded", _STATE_MSG
    for k, w in enumerate(words):  # a redirect into the guard's state
        m = re.match(r"(?:\d|&)?>>?\|?(.*)$", w)
        target = (m.group(1) or (words[k + 1] if k + 1 < len(words) else "")) if m else ""
        if target and _state_word(target, roots, lazy):
            return "guarded", _STATE_MSG
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
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    c = ti.get("command")
    if isinstance(c, list) and tool != "Monitor" and not tool.startswith("mcp__"):  # Codex passes argv: a shell -c script is one element,
        parts = [str(x) for x in c]  # other elements are quoted back into a line (Monitor and MCP tools take a string only)
        k = next((j for j in range(1, len(parts) - 1) if re.fullmatch(r"-[a-z]*c|-command|/c", parts[j].lower())), None)
        c = parts[k + 1] if k is not None and _exe(parts[0]) in _SHELLS + ("powershell", "pwsh", "cmd") else \
            " ".join(shlex.quote(x) if re.search(r"[\s'\"$`;&|<>()]", x) else x for x in parts)
    return c if is_shell_tool(tool) and isinstance(c, str) else None


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
    crs, why, c = [], None, shell_text(payload)
    if c is not None:
        why = protected(c)
        crs = interpret(c, cwd, 0, aliases, sh=_TOOL_SHELL.get(tool)) if _gated(c) else []
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
_PIN = ["-c", "core.quotepath=false", "-c", "core.longpaths=true", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "--no-optional-locks"]
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
    diff = ("diff", "--name-only", "-z", "--no-renames", "--no-ext-diff")
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
    return parse_status(g.run("status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignored=no", cwd=wt)[1])


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


def write_claim(g, name, doc):
    """Write the claim of `name` in format CLAIM_FORMAT.  Refuses (ClaimRefused) a value with a control character (each one in `by` becomes a
    space) and a claim file that holds another branch's claim or cannot be read; refuses (ClaimTooNew) to overwrite a newer-format claim."""
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
    write_atomic(path, ("\n".join(lines + ["entry=" + e for e in doc["entries"]]) + "\n").encode("utf-8"))


def audit(g, **rec):
    os.makedirs(store(g), exist_ok=True)
    with open(os.path.join(store(g), "audit.log"), "ab") as fh:
        fh.write((json.dumps(dict(ts=now_iso(), by=who(g), **rec), ensure_ascii=False) + "\n").encode("utf-8"))


def read_override(g, fp):
    try:
        doc = json.loads(_read_retry(os.path.join(store(g), "override", fp + ".json")))
        return doc if doc.get("fp") == fp and doc.get("expires", "") > now_iso() else None
    except (OSError, ValueError):
        return None


def check_name(g, name, claims):
    """-> reason the branch name cannot be a lane, or None."""
    if name.startswith("-") or g.run("check-ref-format", "--branch", name, ok=(0, 1, 128))[0] != 0:
        return "not a valid git branch name"
    if len(name) > 100 or re.search(r'[<>|"]', name):
        return "longer than 100 characters or contains one of < > | \""
    if any(re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", c.lower()) for c in name.split("/")):
        return "a path component is a Windows reserved device name"
    if any(c.endswith((".", " ")) or fold(c).endswith(".claim") for c in name.split("/")):
        return ("a path component ends in '.', a space or '.claim', so its claim file would alias another branch's on Windows "
                "(Windows alias rule: Windows drops trailing dots and spaces, and <x>.claim is the claim file of <x>)")
    f = fold(name)
    for other in list(list_refs(g)[0]) + [d["branch"] for d in claims.values()]:
        o = fold(other)
        if o != f and (f.startswith(o + "/") or o.startswith(f + "/")):
            return "clashes with the existing branch or claim %s (a ref cannot be both a file and a directory)" % other
        if other != name and o == f:
            return "collides with %s once case and Unicode normalisation are ignored" % other
    return None


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


def judge(snap, claims, bad_claims, name, entries, override):
    key = lane_key(name)
    cl, bad = with_declared(snap["claimants"], claims, key, snap)
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


def plan_core(g, name, entries, write, amend, lang, target_arg=None, worktree=""):
    """Judge `name` against every claimant; with write=True register the claim atomically.  Returns a verdict dict."""
    claims, bad_claims = read_claims(g)
    if worktree and _CTL.search(worktree):
        return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [WORKTREE] %r: the worktree path contains a control character" % worktree))
    reason = check_name(g, name, {k: d for k, d in claims.items() if k != fold(name)})
    if reason:
        return deny("INVALID_MANIFEST", message=T(lang, "invalid", errors="  [BRANCH_NAME] %s: %s" % (name, reason)))
    own_wt = os.path.abspath(worktree) if worktree else (claims.get(fold(name)) or {}).get("worktree", "")
    try:
        snap = gather(g, name, target_arg, own_wt)
    except (Uncertain, GitFail) as err:
        return deny("UNKNOWN", unknowns=[{"code": getattr(err, "code", "TARGET_UNCERTAIN"), "text": str(err)}])
    if not os.path.exists(os.path.join(store(g), "ARMED")) and (claims or any(c["paths"]["committed"] or c["paths"]["uncommitted"] for c in snap["claimants"])):
        snap["warnings"] = snap["warnings"] + [{"code": "NOT_ARMED", "text": "parallel lanes exist but the git backstop is not installed; the user can run `arm`"}]
    if os.path.exists(os.path.join(store(g), "ARMED")) and g.run("config", "--get", "core.hooksPath", ok=(0, 1))[0] == 0:
        snap["warnings"] = snap["warnings"] + [{"code": "HOOK_BYPASSED", "text": "core.hooksPath is set: git no longer runs the backstop; tell the user (arm refuses while it is set)"}]

    def judge_now(claims, bad_claims):
        old = claims.get(fold(name))
        if not old and name in snap["heads"]:
            return deny("BRANCH_EXISTS", message=T(lang, "branch_exists", b=name), target=snap["target"])
        same = bool(old) and {e.raw for e in entries} == set(old["entries"]) and (not worktree or pkey(old["worktree"] or ".") == pkey(os.path.abspath(worktree)))
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
            doc = {"branch": name, "worktree": os.path.abspath(worktree).replace("\\", "/") if worktree else "", "target": snap["target"]["name"],
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
    if v["decision"] == "allow" and "message" not in v:
        path = getattr(args, "worktree", "") or "<path>"
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
        if args.drift:
            try:
                ents = [parse_entry(r) for r in doc["entries"]]
            except ManifestError:
                ents = None  # an unparseable claim is reported by doctor; its drift cannot be computed
            row["drift"] = [] if ents is None else [p for p in drift.get(lane_key(doc["branch"]), []) if not any(path_hit(e, fpath(p)) for e in ents)]
        rows.append(row)
    lines = ["%-8s %s  [%s]%s" % (r["state"], r["branch"], ", ".join(r["entries"]), "  drift: " + _few(r["drift"]) if r.get("drift") else "") for r in rows]
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
    if not challenge(args.fingerprint, args.lang):
        return EXIT["CONSOLE_REQUIRED"]
    now = time.time()
    doc = {"fp": args.fingerprint, "reason": args.reason, "by": who(g), "at": now_iso(), "expires": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 3600))}
    os.makedirs(os.path.join(store(g), "override"), exist_ok=True)
    with open(os.path.join(store(g), "override", args.fingerprint + ".json"), "wb") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    audit(g, op="override", fingerprint=args.fingerprint, reason=args.reason, host="cli")
    out_text(T(args.lang, "overridden", fp=args.fingerprint))
    return 0


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
    try:
        entries = [parse_entry(r) for r in doc["entries"]]
    except ManifestError:
        return deny("UNKNOWN", unknowns=[{"code": "CLAIM_UNPARSEABLE", "text": name}])
    v = plan_core(g, name, entries, False, False, lang)
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
    if follow and follow[0] == "new":  # a repository the same && chain created: it holds no lane
        return None
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
           cr["dynamic"], unresolved, cwd is None)
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


def decide(payload, lang):
    """-> None (allow) or (code, message)."""
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
    if text and any(s not in _BUILTINS for s in _git_subcommands(re.sub(r"[\\`^]", "", text))):  # a git alias may hide a creation anywhere
        aliases = load_aliases(repo()) if repo() else {}
        crs = extract(payload, aliases)[0] if aliases else crs
    if not prot and text and len(text) <= MAX_TEXT and _WRITE_HINT.search(re.sub(r"[\\`^'\"]", "", text)):
        prot = protected(text, roots=tuple(tamper_roots()), lazy=lambda: [pkey(store(repo()))] if repo() else [])
    if prot:
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


_PREFILTER = re.compile(rb"git|worktree|isolation|start_session|EnterWorktree|magos|hookspath|gh|claude|eval|iex", re.I)


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
        res = decide(payload, args.lang)
    except BaseException as err:  # fail closed only when the call looks lane-creating or protected
        try:
            looks = any(extract(payload)[:2])
        except BaseException:
            looks = _lane_text(payload)
        if looks:
            return emit_deny("MAGOS guard error (%s: %s); the lane-creating call is denied. Diagnose: %s doctor" % (type(err).__name__, err, guard_cmd()))
        sys.stderr.write("MAGOS guard warning: %s: %s\n" % (type(err).__name__, err))
        res = None
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
  refs/heads/*) [ "$new" = $Z ] && continue
    b=${ref#refs/heads/}; claim "$b" && continue
    if [ -f "$CD/$ref" ]; then read -r cur <"$CD/$ref"; else cur=$(git rev-parse --verify -q "$ref"); fi
    [ "$cur" = "$new" ] && continue
    [ -z "$cur" ] && need "$b" "creation / 新建分支";;
  HEAD) case $new in ref:refs/heads/*) b=${new#ref:refs/heads/}
      exists "refs/heads/$b" || need "$b" "unborn or orphan branch / 孤儿分支";; esac;;
  esac
done <<EOT
$in
EOT
chain "$@"
'''


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
    if not dry and not user_console():
        sys.stderr.write(T(args.lang, "need_tty") + "\n")
        return EXIT["CONSOLE_REQUIRED"]
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
    audit(g, op="arm", lang=args.lang)
    for kind, target in steps:
        out_text("did %s %s" % (kind, target))
    return 0


def cmd_disarm(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    hook, s = os.path.join(hooks_dir(g), "reference-transaction"), store(g)
    if not args.dry_run and not user_console():
        sys.stderr.write(T(args.lang, "need_tty") + "\n")
        return EXIT["CONSOLE_REQUIRED"]
    verb = "would" if args.dry_run else "did"
    mine = os.path.exists(hook) and MARK in read_text(hook)
    for target in [os.path.join(s, "ARMED")] + ([hook] if mine else []):
        out_text("%s remove %s" % (verb, target))
        if not args.dry_run and os.path.exists(target):
            os.remove(target)
    if mine and not args.dry_run and os.path.exists(hook + ".magos-prev"):
        os.replace(hook + ".magos-prev", hook)
    if not args.dry_run:
        audit(g, op="disarm")
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
                    os.remove(path)
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
    On Windows a guard home whose launcher path holds a character cmd.exe would misread is refused.  User-only: needs a real console
    except with --dry-run."""
    home, dry = guard_home(args.home), args.dry_run
    launcher = "%s/guard/hooks/run-guard.cmd" % home
    bad = cmd_unsafe(launcher)
    if bad:  # cmd.exe would split or expand the path where a host starts the launcher, so the guard would never run
        sys.stderr.write("MAGOS: the guard home %s cannot hold the launcher on Windows: its path %s contains %r, which cmd.exe reads as an "
                         "operator, a separator or an expansion when it starts the launcher; nothing was written. Choose a guard home whose "
                         "path holds none of & ( ) ^ %% ; , = (--home DIR or MAGOS_HOME).\n" % (home, launcher, bad))
        return 2
    if not dry and not user_console():
        sys.stderr.write(T(args.lang, "need_tty") + "\n")
        return EXIT["CONSOLE_REQUIRED"]
    files = [(src, dst, read_bytes(src), read_bytes(dst)) for src, dst in guard_files(home)]
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
        home_audit(home, op="install", host=args.host, to=GUARD_VERSION, source=src0.replace("\\", "/"),
                   **{"from": "none" if old is None else version_of(old) or "unversioned"})
    if note:
        out_text("NOTE: " + note + ".")
    out_text(snippet + "\nMerge it into your own host configuration; the guard never edits it. Codex: trust the entry in /hooks. Hermes: approve it on first use.")
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
        out_text("guard copy %s: %s DIFFERS from %s %s; refresh it in your own terminal:\n%s"
                 % (dst, described(cur), label, described(data), "\n".join("  " + refresh % h for h in hosts)))
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
                 "terminal call; in your own terminal run %s and merge the new entry, or remove the MAGOS entry from the Hermes config" % (path, launcher, redo))
        return True
    v = version_of(read_quiet(os.path.join(os.path.dirname(os.path.dirname(launcher)), "scripts", "magos_guard.py")))
    if v != GUARD_VERSION:
        out_text("hermes entry %s: its launcher %s runs guard %s, not this guard %s; update the Hermes plugin or, in your own terminal, run %s "
                 "and merge the new entry" % (path, launcher, v or "unversioned", GUARD_VERSION, redo))
        return True
    out_text("hermes entry: %s (guard %s)" % (launcher, v))
    return False


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
    if ver is None:
        return 1
    g = open_repo(args.repo)
    if g is None:
        out_text("repository: none at %s (guard is inert here)" % args.repo)
        return 1 if problems else 0
    claims, bad = read_claims(g)
    heads = list_refs(g)[0]
    mode = guard_mode(g)
    too_new = [b for b in bad if b.code == "CLAIM_NEWER_FORMAT"]
    out_text("repository: %s (mode %s); claims: %d, unreadable: %d, newer-format: %d" % (g.common, mode, len(claims), len(bad) - len(too_new), len(too_new)))
    for b in bad:
        out_text("  %s" % (b.text if b.code == "CLAIM_NEWER_FORMAT" else "unreadable claims/%s" % b.replace(os.sep, "/")))
    orphans = [d["branch"] for d in claims.values() if d["branch"] not in heads and not d["worktree"]]
    out_text("claims without a branch or planned worktree: %s" % (", ".join(orphans) or "none"))
    wts = [w for w in worktrees(g) if not w["bare"] and not w["prunable"]]
    dirs = {pkey(hooks_dir(g, w["path"])) for w in wts}
    hook = os.path.join(hooks_dir(g), "reference-transaction")
    mine = os.path.exists(hook) and MARK in read_text(hook)
    same = mine and read_text(hook).replace("\r\n", "\n") == HOOK_SH
    rearm = "re-arm in your own terminal: %s arm" % guard_cmd()
    layer = "installed" if same else "installed but different from this version; " + rearm if mine else "not installed"
    out_text("git layer: %s; hook directories: %d" % (layer, len(dirs)))
    bypassed = mode == "armed" and g.run("config", "--get", "core.hooksPath", ok=(0, 1))[0] == 0
    if bypassed:
        out_text("core.hooksPath is set: git no longer runs the backstop")
    problems = problems or bool(bad) or len(dirs) > 1 or (mode == "armed" and not same) or bypassed
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


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    lang0 = os.environ.get("MAGOS_LANG") if os.environ.get("MAGOS_LANG") in ("zh", "en") else "zh"
    common = Parser(add_help=False)  # the same options work before or after the subcommand
    ap = Parser(prog="magos_guard", description=__doc__.splitlines()[0])  # subcommand parsers are built with the same class
    for parser, dflt in ((ap, None), (common, argparse.SUPPRESS)):
        parser.add_argument("--repo", default=os.getcwd() if dflt is None else dflt)
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
    try:
        args = ap.parse_args(argv)
    except SystemExit as err:
        if any(a == "hook" for a in (sys.argv[1:] if argv is None else argv)) and err.code:
            return 1  # a usage error is a failure (the launcher maps it), never a deny
        raise
    try:
        if args.cmd in ("plan", "check"):
            return cmd_plan(args, args.cmd == "plan")
        return {"list": cmd_list, "release": cmd_release, "override": cmd_override, "hook": cmd_hook, "arm": cmd_arm, "disarm": cmd_disarm,
                "install": cmd_install, "doctor": cmd_doctor, "version": cmd_version}[args.cmd](args)
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
