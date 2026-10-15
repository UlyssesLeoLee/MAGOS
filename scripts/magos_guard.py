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

GS = "**"
BUDGET_S, MAX_CLAIMANTS, MAX_REMOTES, MAX_ENTRIES, LOCK_S, MAX_TEXT = 18.0, 120, 300, 200, 30.0, 200000
SHELL_TOOLS = ("Bash", "PowerShell", "terminal", "shell", "local_shell")
EXIT = {"OK": 0, "OVERRIDDEN": 0, "CONFLICT": 10, "NO_MANIFEST": 10, "UNPLANNABLE": 10, "UNPARSEABLE": 10, "PROTECTED": 10, "UNKNOWN": 11,
        "INVALID_MANIFEST": 12, "LOCK_TIMEOUT": 13, "LANE_EXISTS": 14, "BRANCH_EXISTS": 15, "BLOCKED": 16, "CONSOLE_REQUIRED": 17, "ARM_REFUSED": 3}
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
    "unplannable": ("MAGOS 拒绝：{why} 由工具自己命名分支或工作树，无法事先登记。请先 plan 一个分支名，再用 EnterWorktree name=<已登记名>（分支为 worktree-<name>），或自己 git worktree add 后在其中工作；必须用这个工具时，请用户执行 git config --local magos.guard off。没有创建任何东西。",
                    "MAGOS DENIES: {why} names the branch or worktree itself, so it cannot be planned. Plan a branch name, then EnterWorktree name=<planned name> (branch worktree-<name>), or git worktree add yourself and work there; if this tool is required, ask the user to run git config --local magos.guard off. Nothing was created."),
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
                "④ 仅在用户明确同意后，由用户本人在自己的终端运行：{cmd} override --fingerprint {fp} --reason \"<用户原话>\"，随后重新 plan。",
                "Options: (1) shrink or split the manifest; (2) wait until they are merged into {target}; (3) if the other lane is merged or abandoned, release its claim with "
                "{cmd} release --branch <their branch> (unmerged work is never released); (4) only with the user's explicit consent, "
                "the USER runs in their own terminal: {cmd} override --fingerprint {fp} --reason \"<user's words>\", then re-plan."),
    "ok_plan": ("MAGOS：已登记「{b}」的 manifest（{n} 条）。现在可以创建，例如：{example}",
                "MAGOS: registered the manifest of '{b}' ({n} entries). You may now create it, e.g.: {example}"),
    "ok_check": ("MAGOS：预览通过，没有发现重叠（未登记）。", "MAGOS: preview passed, no overlap found (nothing registered)."),
    "lane_exists": ("MAGOS：「{b}」已有一份不同的有效登记。用 --amend 修改，或先 release。", "MAGOS: '{b}' already has a different open claim. Change it with --amend, or release it first."),
    "branch_exists": ("MAGOS：分支「{b}」已经存在且没有有效登记，不能事后补登记。请换一个新分支名。", "MAGOS: branch '{b}' already exists without a claim; it cannot be registered after the fact. Choose a new branch name."),
    "lock": ("MAGOS：{s} 秒内没有拿到清单锁，未登记也未创建。请稍后重试。", "MAGOS: could not take the claim lock within {s} s; nothing registered. Retry."),
    "invalid": ("MAGOS：manifest 无效，未登记：\n{errors}", "MAGOS: the manifest is invalid, nothing registered:\n{errors}"),
    "blocked": ("MAGOS：拒绝 release：分支仍有未合并的工作或正被工作树检出。", "MAGOS: release refused: the branch has unmerged work or is checked out in a worktree."),
    "released": ("MAGOS：已释放「{b}」的登记。", "MAGOS: released the claim of '{b}'."),
    "overridden": ("MAGOS：已记录用户覆盖（指纹 {fp}，1 小时内有效）。", "MAGOS: recorded the user's override (fingerprint {fp}, valid for 1 hour)."),
    "need_tty": ("MAGOS：这条命令只能由用户在真实终端里执行（当前标准输入不是控制台）。", "MAGOS: only the user may run this, in a real terminal (stdin is not a console)."),
    "git_deny": ("MAGOS 拒绝: 分支「{b}」没有已登记的文件清单（{why}）。先登记: {cmd} plan --branch {b} --paths <路径...>。已有分支与工作树不受影响。",
                 "MAGOS BLOCKED: '{b}' has no registered file manifest ({why}). Register it first: {cmd} plan --branch {b} --paths <paths>. Existing lanes are untouched."),
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


def guard_cmd():
    return '%s "%s"' % ("py -3" if sys.platform == "win32" else "python3", os.path.abspath(__file__).replace("\\", "/"))


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
    if v["decision"] == "deny" and v.get("fingerprint"):
        L.append(T(lang, "options", target=v.get("target", {}).get("name", "?"), cmd=guard_cmd(), fp=v["fingerprint"]))
    return "\n".join(L + ["(%s) %s" % (w["code"], w["text"]) for w in v.get("warnings", [])])


# ---------------------------------------------------------------- pure: command parsing (a UX layer: the git hook is the hard stop)
_BAD_NAME = re.compile(r"[\s~^:?*\[\\\x00-\x1f]|\.\.|^-|^/|/$|\.lock$")


def split_command(cmd):
    """Split a shell / PowerShell command line into segments of (word, dynamic); quotes honoured, backslashes kept.
    Parentheses and braces separate segments only where a command may start; elsewhere they belong to a (dynamic) word."""
    segs, cur, st = [], [], {"w": [], "dyn": False, "has": False, "open": False}

    def word_end():
        if st["has"]:
            cur.append(("".join(st["w"]), st["dyn"]))
        st.update(w=[], dyn=False, has=False, open=False)

    def seg_end():
        word_end()
        if cur:
            segs.append(list(cur))
            cur.clear()
    cmd = re.sub(r"(?:\\|`)\r?\n[ \t]*", " ", cmd)  # line continuations
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in " \t\r":
            word_end()
        elif c in ";\n&|" or (c in "(){}" and not st["has"] and (c in "{}" or not cur)) or (c == ")" and not st["open"]):
            seg_end()
        elif c in "'\"":
            j = i + 1
            while j < n and cmd[j] != c:
                j += 2 if (c == '"' and cmd[j] in "\\`" and j + 1 < n and cmd[j + 1] == '"') else 1
            body = cmd[i + 1:j]
            st["w"].append(body.replace('`"', '"').replace('\\"', '"') if c == '"' else body)
            st["has"], st["dyn"], st["open"] = True, st["dyn"] or (c == '"' and bool(re.search(r"[$`]", body))), st["open"] or "(" in body
            i = j
        else:
            st["w"].append(c)
            st["has"], st["dyn"], st["open"] = True, st["dyn"] or c in "$`%()", st["open"] or c == "("
        i += 1
    seg_end()
    return segs


_WRAP = ("env", "command", "sudo", "time", "nohup", "exec", "call", "builtin", "nice", "xargs", "timeout", "watch", "wsl", "uv", "npx", "stdbuf", "setsid")
_KEYWORDS = ("if", "then", "else", "elif", "do", "while", "until", "!", "time", "function")
_SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
_KNOWN = ("git", "gh", "gt", "claude", "cd", "pushd", "chdir", "set-location", "sl", "powershell", "pwsh", "cmd", "eval", "iex", "invoke-expression",
          "start-process", "set-alias", "sal", "find") + _SHELLS
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
_SINK = re.compile(r"<<<|<\(|\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b|\b(?:iex|invoke-expression)\b|\|\s*(?:powershell|pwsh)|-command\s+-", re.I)
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


def _join(base, p):
    if base is None:
        return None
    p = _norm_path(p)
    if os.name == "nt" and p.startswith("/") and not re.match(r"[A-Za-z]:", p):
        return None  # a POSIX-rooted spelling _norm_path could not map to a drive: no directory we may judge
    return p if (os.path.isabs(p) or re.match(r"[A-Za-z]:", p)) else os.path.normpath(os.path.join(base, p))


def _cr(verb, names, cwd, dynamic, kind="branch", path=None, tool=False, commit=None):
    """A creation record.  kind: worktree (named worktree), branch (branch only) or auto (the tool names the worktree itself).
    A name is dropped when git would refuse it anyway (spaces, '..', a leading dash ...)."""
    names = [n for n in names if _BAD_NAME.search(n) is None or re.search(r"[$`%()]", n)]
    return {"verb": verb, "names": names, "cwd": cwd, "dynamic": dynamic or any(re.search(r"[$`%()]", n) for n in names), "kind": kind, "path": path, "tool": tool,
            "commit": commit}


def _wt_branch_flag(tok):
    return tok in ("-b", "-B") or re.fullmatch(r"-[a-zA-Z]*[bB]", tok) is not None


def _create_flag(tok, sub):
    """Is `tok` an option of `git switch|checkout` that creates a branch?  Long options match by unique prefix (--crea), short ones may be bundled (-fc)."""
    longs, shorts = (("create", "force-create", "orphan"), "cC") if sub == "switch" else (("orphan",), "bB")
    if tok.startswith("--"):
        key = tok[2:].split("=", 1)[0]
        return len(key) >= 3 and any(name.startswith(key) for name in longs)
    return tok.startswith("-") and any(ch in tok[1:] for ch in shorts)


def parse_git(words, dyn, cwd, aliases=None, depth=0):
    """One `git ...` invocation -> list of creation records."""
    i, here, defs = 1, cwd, dict(aliases or {})
    while i < len(words) and words[i].startswith("-"):
        w = words[i]
        if w == "-C" and i + 1 < len(words):
            here = None if dyn[i + 1] else _join(here, words[i + 1])
        elif w in ("--git-dir", "--work-tree") and i + 1 < len(words) or w.startswith(("--git-dir=", "--work-tree=")):
            here = None  # the repository is not where the working directory is
        elif w == "-c" and i + 1 < len(words) and words[i + 1].lower().startswith("alias."):
            defs[words[i + 1][6:].partition("=")[0]] = words[i + 1].partition("=")[2]
        i += 2 if w in _VALUE_OPTS else 1
    if i >= len(words):
        return []
    sub, a, ad = words[i], words[i + 1:], dyn[i + 1:]
    if dyn[i]:  # git $CMD ...: the subcommand itself is dynamic, so nothing can be matched
        return [_cr("dynamic subcommand", [], here, True)]
    if sub in defs and depth < 3:  # an alias: expand it (a leading ! is a shell command)
        val = defs[sub]
        if val.startswith("!"):
            return interpret(val[1:] + " " + " ".join(a), here, depth + 1)
        vw = [w for seg in split_command(val) for w in seg]
        return parse_git(["git"] + [w for w, _ in vw] + a, [False] * (len(vw) + 1) + list(ad), here, defs, depth + 1)

    def take(**kw):
        for k, t in enumerate(a):
            if _create_flag(t, sub):
                if "=" in t:
                    return _cr(sub, [t.split("=", 1)[1]], here, False, **kw)
                return _cr(sub, [a[k + 1]] if k + 1 < len(a) else [], here, k + 1 >= len(a) or ad[k + 1], **kw)
        return None
    if sub == "worktree" and a[:1] == ["add"]:
        pos, k = [], 1
        while k < len(a):
            if _wt_branch_flag(a[k]) or a[k] == "--reason":
                k += 2
                continue
            if a[k] != "--" and not a[k].startswith("-"):
                pos.append((a[k], ad[k]))
            k += 1
        path = _join(here, pos[0][0]) if pos and not pos[0][1] else None
        flag = next((k for k, t in enumerate(a) if _wt_branch_flag(t)), None)
        if flag is not None:
            return [_cr("worktree add", [a[flag + 1]] if flag + 1 < len(a) else [], here, flag + 1 >= len(a) or ad[flag + 1] or any(d for _, d in pos), kind="worktree", path=path)]
        if len(pos) == 1 and "--detach" not in a:  # git names the branch after the directory (and creates it only when it is new)
            return [_cr("worktree add", [re.split(r"[\\/]", pos[0][0].rstrip("/\\"))[-1]], here, pos[0][1], kind="worktree", path=path)]
        detached = _cr("wt-detached", ["detached/" + re.split(r"[\\/]", pos[0][0].rstrip("/\\"))[-1]], here, bool(pos) and pos[0][1], kind="worktree", path=path,
                       commit=pos[1][0] if len(pos) > 1 else None) if pos else None
        if len(pos) == 2 and "--detach" not in a and "/" not in pos[1][0] and pos[1][0] not in ("HEAD", "@"):  # a remote-only branch name creates a branch
            return [_cr("dwim", [pos[1][0]], here, pos[1][1], kind="worktree", path=path), detached]
        return [detached] if detached else []
    if sub == "branch":
        if any(t in ("-d", "-D", "--delete", "-l", "--list", "--show-current", "-u", "-r", "-a", "--contains", "--merged", "--no-merged", "--unset-upstream",
                     "--points-at", "--sort", "--format", "--edit-description") or t.startswith(("--set-upstream-to", "--list")) for t in a):
            return []
        pos = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-")]
        move = any(t in ("-m", "-M", "-c", "-C", "--move", "--copy") for t in a)
        return [_cr(sub, [pos[-1 if move else 0][0]], here, pos[-1 if move else 0][1])] if pos else []
    if sub in ("switch", "checkout"):
        cr = take()
        if cr:
            return [cr]
        tracked = [t for t in a if t.startswith(("--track", "-t"))]
        pos = [(t, ad[k]) for k, t in enumerate(a) if not t.startswith("-") and t != "--"]
        if tracked and pos:  # --track origin/x creates a local branch x
            return [_cr(sub, [pos[0][0].split("/", 1)[-1]], here, pos[0][1])]
        if sub == "switch" and len(pos) == 1 or sub == "checkout" and len(pos) == 1 and "--" not in a[:1]:
            return [_cr("dwim", [pos[0][0]], here, pos[0][1])]  # a remote-only name creates a tracking branch; enforce checks that
        return []
    if sub == "stash" and a[:1] == ["branch"]:
        return [_cr("stash branch", a[1:2], here, len(a) < 2 or ad[1])]
    if sub == "symbolic-ref":
        pos = [t for t in a if not t.startswith("-")]
        return [_cr(sub, [pos[1][11:]], here, False)] if len(pos) >= 2 and pos[0] == "HEAD" and pos[1].startswith("refs/heads/") else \
            [_cr(sub, [pos[0][11:]], here, False)] if pos and pos[0].startswith("refs/heads/") else []
    if sub == "update-ref":
        if "-d" in a:
            return []
        names = [t[11:] for t in a if t.startswith("refs/heads/")]
        return [_cr(sub, names, here, False)] if names else []
    if sub in ("fetch", "pull", "push"):
        pos = [t for t in a if not t.startswith("-")]
        if sub == "push" and pos[:1] != ["."]:
            return []  # a push creates a remote branch, not a local one
        names = [m.group(1) for t in pos[1:] for m in [re.fullmatch(r"\+?[^:]*:(?:refs/heads/)?([^:]+)", t)] if m and not m.group(1).startswith("refs/")]
        return [_cr(sub, names, here, False)] if names else []
    if sub == "flow":
        return [_cr("git flow", [], here, True, kind="auto", tool=True)]
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


def interpret(cmd, cwd, depth=0, aliases=None):
    """Every lane-creating invocation inside a command line: recurses into bash -c / powershell -Command / cmd /c / -EncodedCommand / eval / $(..) /
    here-documents fed to a shell / quoted text fed to a shell, follows literal variables and aliases, and reads small script files."""
    if len(cmd) > MAX_TEXT:  # too long to inspect: whatever follows the padding must not pass unseen
        return [dict(_cr("long command", [], cwd, True), why="the command is longer than %d characters and is not inspected" % MAX_TEXT)]
    out, here, env, galias, whole = [], cwd, {}, {}, cmd
    cmd, bodies = _heredocs(cmd)
    for body in bodies:
        out += interpret(body, cwd, depth + 1, aliases) if depth < 3 else []
    if depth < 3:
        for m in _SUBST.finditer(cmd):
            out += interpret(m.group(1) or m.group(2), cwd, depth + 1, aliases)
        if any("--stdin" in s.partition("update-ref")[2] for s in re.split(r"[\n|;&]", whole) if "update-ref" in s):  # the ref names arrive on stdin: read them from the command text
            names = re.findall(r"(?:create|update)\s+refs/heads/([^\s\"']+)", whole)
            out += [_cr("update-ref", names, cwd, False)] if names else []
        pipe = re.match(r"\s*(?:echo|printf)\s(.*?)\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b", cmd, re.I | re.S)
        out += interpret(pipe.group(1).strip(), cwd, depth + 1, aliases) if pipe else []
        if _SINK.search(cmd):
            for m in _QUOTED.finditer(cmd):
                body = (m.group(1) or m.group(2) or "").replace("\\n", "\n")  # printf 'git branch x\n' | sh
                if re.search(r"\bgit\b", body):
                    out += interpret(body, cwd, depth + 1, aliases)
    for seg in split_command(cmd):
        words, dyn = [w for w, _ in seg], [d for _, d in seg]
        if env:  # literal variables: g=git; $g branch x   /   $g = 'git'; & $g branch x
            for k, w in enumerate(words):
                nw = re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: env.get(m.group(1), m.group(0)), w)
                words[k], dyn[k] = nw, bool(re.search(r"[$`%()]", nw)) if nw != w else dyn[k]
        if len(words) >= 3 and words[1] == "=" and words[0].startswith("$"):  # PowerShell $name = 'value'
            env[words[0][1:]] = words[2]
            continue
        if len(words) == 1 and _ASSIGN.match(words[0]):  # NAME=value
            env[words[0].split("=", 1)[0]] = words[0].split("=", 1)[1]
            continue
        i = 0
        while i < len(words) and (_ASSIGN.match(words[i]) or words[i].lower() in _WRAP + _KEYWORDS or words[i] == "&" or (i == 0 and words[i].endswith(")"))):
            wrapped = words[i].lower() in _WRAP
            i += 1
            if wrapped:
                i = next((k for k in range(i, len(words)) if _exe(words[k]) in _KNOWN), len(words))
        if i >= len(words):
            continue
        exe, rest = _exe(galias.get(words[i], words[i])), words[i + 1:]
        if words[i - 1:i] == ["xargs"] or (i and "xargs" in [w.lower() for w in words[:i]]):  # the names arrive on stdin
            if exe == "git":
                out += parse_git(words[i:] + ["$stdin"], dyn[i:] + [True], here, aliases, depth)
                continue
        if exe in ("cd", "pushd", "chdir", "set-location", "sl"):
            tgt = [(w, d) for w, d in zip(rest, dyn[i + 1:]) if not w.startswith("-")]
            here = None if (not tgt or tgt[0][1] or tgt[0][0] == "-") else _join(here, tgt[0][0])
        elif exe in ("set-alias", "sal"):
            pos = [w for w in rest if not w.startswith("-")]
            if len(pos) >= 2:
                galias[pos[0]] = pos[1]
        elif exe == "start-process" and depth < 3:
            k = [w.lower() for w in rest].index("-argumentlist") + 1 if "-argumentlist" in [w.lower() for w in rest] else len(rest)
            args = rest[k] if k < len(rest) else ""
            prog = next((w for w in rest if _exe(w) == "git"), None)
            out += interpret("git " + args.replace(",", " "), here, depth + 1, aliases) if prog else []
        elif exe == "find" and depth < 3 and any(w in ("-exec", "-execdir") for w in rest):
            k = next(k for k, w in enumerate(rest) if w in ("-exec", "-execdir"))
            out += interpret(" ".join(rest[k + 1:]).replace("\\;", " "), here, depth + 1, aliases)
        elif exe in _SHELLS + ("powershell", "pwsh", "cmd") and depth < 3:
            handled = False
            for k, w in enumerate(rest):
                if re.fullmatch(r"-(enc|encodedcommand)", w.lower()) and k + 1 < len(rest):
                    try:
                        script = base64.b64decode(rest[k + 1]).decode("utf-16-le")
                    except ValueError:
                        script = "git branch $opaque"  # an undecodable encoded command counts as a dynamic creation
                    out += interpret(script, here, depth + 1, aliases)
                    handled = True
                    break
                if re.fullmatch(r"-[a-z]*c|-command|/c|/k|//c", w.lower()) and k + 1 < len(rest):
                    out += interpret(rest[k + 1] if exe in _SHELLS else " ".join(rest[k + 1:]), here, depth + 1, aliases)
                    handled = True
                    break
            cands = [w for k, w in enumerate(rest) if not w.startswith("-") and (k == 0 or rest[k - 1].lower() != "-command")]  # option values come first
            text = None if handled else next((s for s in (_script(w, here) for w in cands[:4]) if s), None)
            out += interpret(text, here, depth + 1, aliases) if text else []
        elif exe in ("eval", "iex", "invoke-expression") and depth < 3:
            out += interpret(" ".join(rest), here, depth + 1, aliases)
        elif exe == "git":
            out += parse_git(words[i:], dyn[i:], here, aliases, depth)
        elif (exe == "gh" and rest[:2] == ["pr", "checkout"]) or (exe == "gt" and rest[:1] == ["create"]) or (exe == "claude" and any(w in ("-w", "--worktree") for w in rest)):
            out.append(_cr(exe + " " + " ".join(rest[:2]), [], here, True, kind="auto", tool=True))
        elif re.search(r"\.(sh|ps1|bash)$", words[i], re.I) and depth < 3 or exe in ("source", "."):
            text = _script(rest[0] if exe in ("source", ".") and rest else words[i], here)
            out += interpret(text, here, depth + 1, aliases) if text else []
    seen, result = set(), []
    for cr in out:  # a creation seen twice (a quoted body and the command that runs it) counts once; a flag without a usable name is no creation
        key = repr(sorted(cr.items(), key=str))
        if key not in seen and (cr["names"] or cr["dynamic"] or cr["kind"] == "auto"):
            seen.add(key)
            result.append(cr)
    return result


_STATE_PATH = re.compile(r"(^|[\\/])\.git[\\/](hooks|refs|HEAD|magos|config)([\\/]|$)|(^|[\\/])packed-refs$|(^|[\\/])\.magos([\\/]|$)", re.I)
_WRITE_CMDS = frozenset("rm mv cp tee chmod del erase ren rename remove-item move-item copy-item set-content out-file add-content new-item clear-content".split())
_USER_ONLY = ("override", "arm", "disarm", "install")
_READ_FLAGS = ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "--show-scope")
_ENV_WRITE = re.compile(r"^(?:GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\d+|VALUE_\d+)=|\$env:GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\d+|VALUE_\d+)$)", re.I)
_USER_MSG = "override / arm / disarm / install are user-only"


def protected(text, depth=0):
    """-> (scope, reason) or None.  scope 'always': user-only subcommands and magos.* config; 'guarded': edits of the guard's own state that
    matter once claims or the hook exist.  Words are inspected, never the whole text, so a commit message or a grep for these names passes."""
    if len(text) > MAX_TEXT:
        return "guarded", "the command is too long to inspect"
    segs = split_command(_heredocs(text)[0])
    for seg in segs:
        words = [w for w, _ in seg]
        low = [w.lower() for w in words]
        for i, w in enumerate(words):
            if re.search(r"magos_guard(\.py)?$", w):
                rest, k = words[i + 1:], 0
                while k < len(rest) and rest[k] in ("--json", "--repo", "--lang"):
                    k += 2 if rest[k] != "--json" else 1
                if rest[k:k + 1] and rest[k] in _USER_ONLY:
                    return "always", _USER_MSG
            elif depth < 3 and " " in w and "magos_guard" in w and protected(w, depth + 1):  # bash -c '...', powershell -Command "..."
                return "always", _USER_MSG
        reads = any(f in low for f in _READ_FLAGS)
        if "config" in low and any(x.startswith("magos.") for x in low) and not reads:
            return "always", "magos.* git config switches"
        if ("config" in low and "core.hookspath" in low and not reads) or any(x.startswith("core.hookspath=") for x in low) or \
                ("config" in low and "--worktree" in low) or any(_ENV_WRITE.match(w) for w in words):
            return "guarded", "core.hooksPath / GIT_CONFIG_* / worktree config can switch the git layer off"
        exe = next((_exe(w) for w in words if not _ASSIGN.match(w) and w.lower() not in _WRAP), "")
        if exe in _WRITE_CMDS or (exe == "sed" and "-i" in words):
            if any(_STATE_PATH.search(w) for w in words[1:]):
                return "guarded", "the hooks, refs and claim store under .git are the guard's state"
        for k, w in enumerate(words):  # a redirect into the guard's state
            target = w.lstrip(">") if w.startswith(">") and w.lstrip(">") else (words[k + 1] if w in (">", ">>") and k + 1 < len(words) else "")
            if target and _STATE_PATH.search(target):
                return "guarded", "the hooks, refs and claim store under .git are the guard's state"
    return None


def shell_text(payload):
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    c = ti.get("command")
    if isinstance(c, list):  # Codex passes argv: a shell -c script is one element, other elements are quoted back into a line
        parts = [str(x) for x in c]
        k = next((j for j in range(1, len(parts) - 1) if re.fullmatch(r"-[a-z]*c|-command|/c", parts[j].lower())), None)
        c = parts[k + 1] if k is not None and _exe(parts[0]) in _SHELLS + ("powershell", "pwsh", "cmd") else \
            " ".join(shlex.quote(x) if re.search(r"[\s'\"$`;&|<>()]", x) else x for x in parts)
    return c if str(payload.get("tool_name") or "") in SHELL_TOOLS and isinstance(c, str) else None


def extract(payload, aliases=None):
    """-> (creations, protected, default_cwd) for the tool names of all three hosts."""
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cwd = ti.get("workdir") or payload.get("cwd") or os.getcwd()
    crs, why, c = [], None, shell_text(payload)
    if c is not None:
        why = protected(c)
        crs = interpret(c, cwd, 0, aliases) if re.search(r"git|gh|gt|claude|eval|iex|invoke-expression|\.sh|\.ps1|source|-enc|base64", c, re.I) else []
    elif tool == "EnterWorktree" and not ti.get("path"):
        crs.append(_cr("EnterWorktree", ["worktree-%s" % ti["name"]] if ti.get("name") else [], cwd, not ti.get("name"), "worktree" if ti.get("name") else "auto", tool=True))
    elif tool in ("Agent", "Task", "Workflow") and re.search(r"isolation\W+worktree", json.dumps(ti)):
        crs.append(_cr("%s isolation=worktree" % tool, [], cwd, True, "auto", tool=True))
    elif re.fullmatch(r"mcp__.*(start_session|worktree|branch|hand_off_to_session).*", tool):
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


class Git:
    def __init__(self, start, budget=BUDGET_S):
        end = time.monotonic() + budget
        self.start, self.deadline, self.common, self.top = start, min(end, HOOK_DEADLINE) if HOOK_DEADLINE else end, None, None

    def run(self, *args, cwd=None, inp=None, ok=(0,)):
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
        if p.returncode not in ok:
            raise GitFail("GIT_FAILED", "git %s: %s" % (" ".join(args[:3]), p.stderr.decode("utf-8", "replace").strip()[-200:]))
        return p.returncode, p.stdout

    def text(self, *args, **kw):
        return self.run(*args, **kw)[1].decode("utf-8", "replace")


def open_repo(path):
    """-> Git or None (not a git repository)."""
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


def cfg(g, key):
    """Config value; magos.* keys come from the repository's own config only (git -c, GIT_CONFIG_* and global files cannot set them)."""
    rc, out = g.run("config", *(["--local"] if key.startswith("magos.") else []), "--get", key, ok=(0, 1))
    return out.decode("utf-8", "replace").strip() if rc == 0 else None


def pkey(p):
    return os.path.normcase(os.path.normpath(p))


def worktrees(g):
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
    """Snapshot of every claimant's committed / uncommitted evidence (git only; the planned branch's own lane is left out).  Raises Uncertain / GitFail."""
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


def parse_claim(text):
    doc = {"entries": []}
    for line in text.replace("\r", "").split("\n"):
        k, sep, v = line.partition("=")
        if sep and k == "entry":
            doc["entries"].append(v)
        elif sep:
            doc[k] = v
    if doc.get("state") != "active" or not doc.get("branch") or not doc["entries"]:
        raise ValueError("not a claim")
    for k in ("worktree", "target", "base", "created", "by", "override"):
        doc.setdefault(k, "")
    return doc


def read_claims(g):
    """-> ({folded branch: claim}, [unreadable claim paths])."""
    root, claims, bad = os.path.join(store(g), "claims"), {}, []
    for d, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".claim"):
                p = os.path.join(d, f)
                try:
                    doc = parse_claim(_read_retry(p))
                    claims[fold(doc["branch"])] = doc
                except (OSError, ValueError):
                    bad.append(os.path.relpath(p, root))
    return claims, bad


def write_claim(g, name, doc):
    path = claim_path(g, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["state=active", "v=1"] + ["%s=%s" % (k, doc.get(k) or "") for k in ("branch", "worktree", "target", "base", "created", "by", "override")]
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "wb") as fh:
        fh.write(("\n".join(lines + ["entry=" + e for e in doc["entries"]]) + "\n").encode("utf-8"))
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, path)


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
    unknowns = list(snap["unknowns"]) + [{"code": "CLAIM_UNPARSEABLE", "text": b} for b in bad + bad_claims]
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
        if v["decision"] == "deny":
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
            v = judge_now(claims, bad_claims)
            if v["decision"] == "deny" or v["unchanged"] and not v["overridden"]:
                return v
            doc = {"branch": name, "worktree": os.path.abspath(worktree).replace("\\", "/") if worktree else "", "target": snap["target"]["name"],
                   "base": snap["target"]["sha"], "created": now_iso(), "by": who(g), "override": v["fingerprint"] if v["overridden"] else "",
                   "entries": [e.raw for e in entries]}
            write_claim(g, name, doc)
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
    claims, _bad = read_claims(g)
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
    out_text(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n".join(
        "%-8s %s  [%s]%s" % (r["state"], r["branch"], ", ".join(r["entries"]), "  drift: " + _few(r["drift"]) if r.get("drift") else "") for r in rows) or "(no claims)")
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


def cmd_release(args):
    g = open_repo(args.repo)
    if g is None:
        return 2
    try:
        with Lock(g):
            doc = read_claims(g)[0].get(fold(args.branch))
            if not doc:
                path = claim_path(g, args.branch)
                if os.path.isfile(path):  # a claim file nobody can parse blocks every creation: let it go
                    os.remove(path)
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
            os.remove(claim_path(g, doc["branch"]))
            audit(g, op="release", branch=doc["branch"], reason=args.reason, host="cli")
    except LockTimeout:
        sys.stderr.write(T(args.lang, "lock", s=int(LOCK_S)) + "\n")
        return EXIT["LOCK_TIMEOUT"]
    out_text(T(args.lang, "released", b=args.branch))
    return 0


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
def guard_mode(g, host=True):
    """armed | auto | off.  MAGOS_GUARD=off is read from the HOST hook process environment only (an agent's tool environment cannot reach it)."""
    if host and os.environ.get("MAGOS_GUARD", "").lower() in ("off", "0", "false"):
        return "off"
    if (cfg(g, "magos.guard") or "").lower() == "off":
        return "off"
    return "armed" if os.path.exists(os.path.join(store(g), "ARMED")) else "auto"


def parallel(g, cwd_top):
    """AUTO engagement for branch-only and auto-named creations: another lane exists (an open claim, an unmerged branch, another dirty worktree)."""
    claims = read_claims(g)[0]
    try:
        snap = gather(g)
    except (Uncertain, GitFail):
        return bool(claims)
    if any(not is_idle(d, snap["heads"], snap["merged"], snap["wt_branches"], snap["target"]["sha"]) for d in claims.values()):
        return True
    wts = {pkey(w["path"]): w for w in worktrees(g)}
    here = wts.get(pkey(cwd_top or ""))
    own = (lane_key(here["branch"]) if here and here["branch"] else "wt:" + pkey(cwd_top or ""))
    return any(c["key"] != own and (c["paths"]["committed"] or c["paths"]["uncommitted"]) for c in snap["claimants"])


def check_creation(g, name, cr, lang, mode):
    """-> None (allow) or a deny verdict for creating branch `name`."""
    doc = read_claims(g)[0].get(fold(name))
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
    for cr in crs:
        g, unresolved = open_repo(cr["cwd"] or default_cwd), False
        if g is None and cr["cwd"] and default_cwd and os.name == "nt" and cr["cwd"].startswith(("/", "\\", "~", "%", "$")) and not os.path.isdir(cr["cwd"]):
            # a Windows spelling we cannot map to a directory (an unusual Git Bash form): judge by the session's repository
            g, unresolved = open_repo(default_cwd), True
        mode = guard_mode(g) if g else "off"
        if mode == "off":
            continue
        if cr["verb"] == "wt-detached" and cr["commit"]:  # `worktree add <path> <existing branch or remote-only name>` is not a detached lane
            heads, remotes, _ = list_refs(g)
            if cr["commit"] in heads or any(r.split("/", 1)[-1] == cr["commit"] for r in remotes):
                continue
        if cr["verb"] == "dwim":  # `switch <name>` / `worktree add <path> <name>` create a branch only for a remote-only name
            heads, remotes, _ = list_refs(g)
            cr = dict(cr, names=[n for n in cr["names"] if n not in heads and any(r.split("/", 1)[-1] == n for r in remotes)])
            if not cr["names"] or cr["dynamic"]:
                continue
        engaged = mode == "armed" or cr["kind"] == "worktree" or parallel(g, g.top)
        if not engaged:
            continue
        if cr["dynamic"] or unresolved or (cr["cwd"] is None and not cr["tool"]):
            if cr["kind"] == "auto":
                return "UNPLANNABLE", T(lang, "unplannable", why=cr["verb"])
            return "UNPARSEABLE", T(lang, "unparse_git", why=cr.get("why") or "the cd / -C target or the branch name is dynamic")
        heads = list_refs(g)[0]
        for n in cr["names"]:
            if n in heads:  # an existing branch is switched to or reset, not created
                continue
            try:
                v = check_creation(g, n, cr, lang, mode)
            except GitFail as err:
                v = deny("UNKNOWN", unknowns=[{"code": err.code, "text": str(err)}]) if mode == "armed" or cr["kind"] == "worktree" else None
            if v:
                return v["code"], v.get("message") or render(lang, v, n)
        if cr["kind"] == "auto" and not cr["names"]:
            return "UNPLANNABLE", T(lang, "unplannable", why=cr["verb"])
    return None


def load_aliases(g):
    return {k[6:]: v for k, _, v in (ln.partition(" ") for ln in g.text("config", "--get-regexp", r"^alias\.", ok=(0, 1)).splitlines())}


def decide(payload, lang):
    """-> None (allow) or (code, message)."""
    crs, prot, cwd = extract(payload)
    if not crs and any(s not in _BUILTINS for s in _git_subcommands(shell_text(payload) or "")):  # a git alias may hide a creation
        g = open_repo(cwd)
        aliases = load_aliases(g) if g else {}
        crs = extract(payload, aliases)[0] if aliases else crs
    if prot:
        g = open_repo(cwd)
        if prot[0] == "always" or (g and (guard_mode(g) == "armed" or read_claims(g)[0])):
            return "PROTECTED", T(lang, "protected", why=prot[1])
    return enforce(crs, cwd, lang) if crs else None


def emit_deny(msg):
    """One deny shape for all three hosts, signalled as JSON at exit 0 (Claude/Codex hookSpecificOutput + legacy decision, Hermes decision).
    Exit 2 is deliberately not used: Python itself exits 2 for usage errors and a missing script, which must never read as a deny."""
    obj = {"decision": "block", "reason": msg, "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": msg}}
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True) + "\n").encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


_PREFILTER = re.compile(rb"git|worktree|isolation|start_session|EnterWorktree|magos|hookspath|gh|claude|eval|iex", re.I)


def cmd_hook(args):
    global HOOK_DEADLINE
    HOOK_DEADLINE = time.monotonic() + BUDGET_S
    try:
        return _hook(args)
    finally:
        HOOK_DEADLINE = None


def _hook(args):
    raw = sys.stdin.buffer.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
        payload = payload if isinstance(payload, dict) else {}
    except ValueError:
        payload = None
    if payload is None:
        return emit_deny("MAGOS guard: unparseable hook payload") if _PREFILTER.search(raw) else (out_text("{}"), 0)[1]
    try:
        res = decide(payload, args.lang)
    except BaseException as err:  # fail closed only when the call looked lane-creating
        try:
            looks = bool(_PREFILTER.search(raw)) and any(extract(payload)[:2])
        except BaseException:
            looks = True
        if looks:
            return emit_deny("MAGOS guard error (%s: %s); the lane-creating call is denied. Diagnose: %s doctor" % (type(err).__name__, err, guard_cmd()))
        sys.stderr.write("MAGOS guard warning: %s: %s\n" % (type(err).__name__, err))
        res = None
    return emit_deny(res[1]) if res else (out_text("{}"), 0)[1]


# ---------------------------------------------------------------- git layer (L2): pure POSIX sh reference-transaction hook, no Python
HOOK_SH = r'''#!/bin/sh
# MAGOS lane guard, git layer: reference-transaction only. POSIX sh, LF endings, no Python, no environment switch.
Z=0000000000000000000000000000000000000000; in=
chain() { p=${0%/*}/reference-transaction.magos-prev; [ -f "$p" ] || exit 0
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
    steps = [("write", hook), ("write", os.path.join(s, "ARMED")), ("write", os.path.join(s, "lang")), ("write", os.path.join(s, "guard"))]
    steps += [("config", "maintenance.pack-refs.enabled=false"), ("config", "gc.packRefs=false")]
    if dry:
        for kind, target in steps:
            out_text("would %s %s" % (kind, target))
        return 0
    if os.path.exists(hook) and not mine_hook:
        os.replace(hook, hook + ".magos-prev")
    put_text(hook, HOOK_SH)
    os.chmod(hook, 0o755)
    put_text(os.path.join(s, "lang"), args.lang + "\n")
    put_text(os.path.join(s, "guard"), guard_cmd() + "\n")
    put_text(os.path.join(s, "ARMED"), now_iso() + "\n")
    for kv in ("maintenance.pack-refs.enabled=false", "gc.packRefs=false"):  # no background pack-refs: it would multiply hook calls
        g.run("config", "--local", *kv.split("="))
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
    mine = os.path.exists(hook) and MARK in read_text(hook)
    for target in [os.path.join(s, "ARMED")] + ([hook] if mine else []):
        out_text("%s remove %s" % ("would" if args.dry_run else "did", target))
        if not args.dry_run and os.path.exists(target):
            os.remove(target)
    if mine and not args.dry_run and os.path.exists(hook + ".magos-prev"):
        os.replace(hook + ".magos-prev", hook)
    return 0


# ---------------------------------------------------------------- installer and doctor
def guard_home(arg=None):
    return os.path.abspath(os.path.expanduser(arg or os.environ.get("MAGOS_HOME") or "~/.magos")).replace("\\", "/")


def host_snippet(host, home):
    launcher = "%s/guard/hooks/run-guard.cmd" % home
    win = sys.platform == "win32"
    if host == "codex":
        return json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash|mcp__.*(start_session|worktree|branch|hand_off_to_session)", "hooks": [{
            "type": "command", "command": "sh '%s' hook codex pre-tool" % launcher,
            "commandWindows": "& '%s' hook codex pre-tool; exit $LASTEXITCODE" % launcher, "timeout": 25, "statusMessage": "MAGOS lane guard"}]}]}}, indent=2)
    if host == "hermes":
        return ('hooks:\n  pre_tool_call:\n    - matcher: "terminal"\n      command: \'%s hook hermes pre-tool\'\n      timeout: 25\n      fail_closed: true\n'
                % ('"%s"' % launcher if win else "sh '%s'" % launcher))
    return json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "^EnterWorktree$", "hooks": [{"type": "command", "command": '"%s" --strict hook claude pre-tool' % launcher, "shell": "bash", "timeout": 25}]},
        {"matcher": "^(Bash|PowerShell|Agent|Task|Workflow)$|^mcp__.*(start_session|worktree|branch|hand_off_to_session)",
         "hooks": [{"type": "command", "command": '"%s" hook claude pre-tool' % launcher, "shell": "bash", "timeout": 25}]}]}}, indent=2)


def cmd_install(args):
    """Copies the guard and its launcher to one canonical user-level directory and prints (and saves) the exact host snippet; never edits host config."""
    home, here = guard_home(args.home), os.path.dirname(os.path.abspath(__file__))
    copies = [(os.path.join(here, "magos_guard.py"), "%s/guard/scripts/magos_guard.py" % home), (os.path.join(here, "..", "hooks", "run-guard.cmd"), "%s/guard/hooks/run-guard.cmd" % home)]
    for src, dst in copies:
        out_text("%s copy %s -> %s" % ("would" if args.dry_run else "did", os.path.normpath(src), dst))
        if not args.dry_run and os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst)):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
    snippet = host_snippet(args.host, home)
    if not args.dry_run:
        put_text("%s/guard/generated/%s.%s" % (home, args.host, "yaml" if args.host == "hermes" else "json"), snippet)
    out_text(snippet + "\nMerge it into your own host configuration; the guard never edits it. Codex: trust the entry in /hooks. Hermes: approve it on first use.")
    return 0


def cmd_doctor(args):
    ok = sys.version_info >= (3, 9)
    out_text("python %s %s" % (sys.version.split()[0], "ok" if ok else "TOO OLD (need 3.9+)"))
    try:
        out_text("git %s" % Git(os.getcwd()).text("--version").strip())
    except GitFail as err:
        out_text("git: %s" % err)
        return 1
    g = open_repo(args.repo)
    if g is None:
        out_text("repository: none at %s (guard is inert here)" % args.repo)
        return 0 if ok else 1
    claims, bad = read_claims(g)
    heads = list_refs(g)[0]
    mode = guard_mode(g)
    out_text("repository: %s (mode %s); claims: %d, unreadable: %d" % (g.common, mode, len(claims), len(bad)))
    orphans = [d["branch"] for d in claims.values() if d["branch"] not in heads and not d["worktree"]]
    out_text("claims without a branch or planned worktree: %s" % (", ".join(orphans) or "none"))
    wts = [w for w in worktrees(g) if not w["bare"] and not w["prunable"]]
    dirs = {pkey(hooks_dir(g, w["path"])) for w in wts}
    hook = os.path.join(hooks_dir(g), "reference-transaction")
    mine = os.path.exists(hook) and MARK in read_text(hook)
    same = mine and read_text(hook).replace("\r\n", "\n") == HOOK_SH
    out_text("git layer: %s; hook directories: %d" % ("installed" if same else "installed but different from this version" if mine else "not installed", len(dirs)))
    bypassed = mode == "armed" and g.run("config", "--get", "core.hooksPath", ok=(0, 1))[0] == 0
    if bypassed:
        out_text("core.hooksPath is set: git no longer runs the backstop")
    problems = bad or len(dirs) > 1 or (mode == "armed" and not same) or bypassed
    if mode == "armed" and same:
        probe = g.run("branch", "__magos_selftest", ok=(0, 1, 128))
        if probe[0] == 0:
            g.run("branch", "-D", "__magos_selftest", ok=(0, 1))
            out_text("self-test FAILED: the backstop did not veto an unclaimed branch")
            problems = True
        else:
            out_text("self-test ok: an unclaimed branch is vetoed")
    return 0 if ok and not problems else 1


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    lang0 = os.environ.get("MAGOS_LANG") if os.environ.get("MAGOS_LANG") in ("zh", "en") else "zh"
    common = argparse.ArgumentParser(add_help=False)  # the same options work before or after the subcommand
    ap = argparse.ArgumentParser(prog="magos_guard", description=__doc__.splitlines()[0])
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
    sub.add_parser("doctor", parents=[common])
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
                "install": cmd_install, "doctor": cmd_doctor}[args.cmd](args)
    except GitFail as err:
        sys.stderr.write("MAGOS guard: %s: %s\n" % (err.code, err))
        return EXIT["UNKNOWN"]
    except BaseException as err:  # never exit 1 silently: every failure is a deny-class exit
        if args.cmd == "hook":
            raise
        sys.stderr.write("MAGOS guard internal error: %s: %s\n" % (type(err).__name__, err))
        return EXIT["UNKNOWN"]


if __name__ == "__main__":
    sys.exit(main())
