"""Supply-chain and network contracts of the repository: every workflow is pinned, read-only and installs only hash-pinned wheels;
Dependabot keeps the pins current after a cooldown; no tracked file holds a credential; the hook code imports no network module, starts
only git, and runs no git subcommand that talks to a remote."""
from __future__ import annotations

import ast
import itertools
import re
import subprocess
from pathlib import Path

import pytest

from conftest import G, ROOT

WORKFLOWS = ROOT / ".github" / "workflows"
FLOWS = sorted(p for p in WORKFLOWS.iterdir() if p.is_file())  # GitHub runs .yml and .yaml alike: every file here is checked
# .github/requirements serves Python 3.14 and Dependabot updates it; the 3.9 set is frozen at the last releases that support 3.9.
REQ_FILES = sorted([*(ROOT / ".github" / "requirements").glob("*.txt"), *(ROOT / ".github" / "requirements-py39").glob("*.txt")], key=lambda p: p.as_posix())
SHA_PIN = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")
PIN_LINE = re.compile(r"^\s*(?:- )?uses: ([\w.-]+/[\w./-]+)@([0-9a-f]{40}) # v\d+(?:\.\d+)*\s*$")
INSTALL = re.compile(r"^python -m pip install --require-hashes --only-binary :all:(?: -r (\"\$\w+\"|\.github/requirements(?:-py39)?/[\w.-]+\.txt))+$")
# Programs that fetch or install code other than through the hash-pinned pip line.
FETCHERS = re.compile(r"\b(?:curl|wget|uvx?|pipx|conda|mamba|npm|npx|pnpm|yarn|gem|go\s+install|cargo\s+install|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|"
                      r"Start-BitsTransfer|bitsadmin|certutil|apt(?:-get)?|choco|winget|brew|easy_install)\b|\|\s*(?:ba|z|da)?sh\b", re.I)
SECRETS = re.compile(r"\bsecrets\b|\btojson\s*\(", re.I)
TOKEN = re.compile(r"\bgithub\s*(?:\.\s*token\b|\[\s*['\"]token['\"]\s*\])", re.I)
# The only write a workflow token may hold: CodeQL uploads its results.
WRITE_GRANTS = {("codeql.yml", "analyze", "security-events")}
# The only step that names the job token: zizmor's online audits. (checkout and setup-python receive it through their default inputs.)
TOKEN_STEPS = {("security.yml", "workflows", "Audit the workflows and Dependabot with zizmor")}


def _yaml():
    try:
        import yaml
    except ImportError:  # a silent skip would report the supply-chain contract as green
        pytest.fail("PyYAML is required for the supply-chain contract (pip install -r .github/requirements/tests-py314.txt)")
    return yaml


def flow(path):
    return _yaml().safe_load(path.read_text(encoding="utf-8"))


def triggers(doc):
    return doc.get("on", doc.get(True))  # YAML 1.1 reads the bare key `on` as true


def test_workflows_are_pinned_read_only_and_timed():
    names = [p.name for p in FLOWS]
    assert names == ["codeql.yml", "security.yml", "test.yml"], names
    for path in FLOWS:
        text = path.read_text(encoding="utf-8")
        doc = flow(path)
        assert not {"pull_request_target", "workflow_run"} & set(triggers(doc)), path.name
        assert not SECRETS.search(text), path.name  # no repository secret, in any spelling (`secrets.X`, `secrets['X']`, toJSON)
        top = doc.get("permissions")
        assert isinstance(top, dict) and set(top.values()) <= {"read", "none"}, (path.name, top)
        assert "concurrency" in doc, path.name
        for line in text.splitlines():
            if re.match(r"^\s*(?:- )?uses:", line):
                assert PIN_LINE.match(line), (path.name, line)  # a full commit SHA, with its tag in the comment
        token_steps = 0
        for job_id, job in doc["jobs"].items():
            assert isinstance(job.get("timeout-minutes"), int), (path.name, job_id)
            for scope, level in (job.get("permissions") or {}).items():
                assert level in ("read", "none") or (path.name, job_id, scope) in WRITE_GRANTS, (path.name, job_id, scope, level)
            for step in job["steps"]:
                if "uses" in step:
                    assert SHA_PIN.fullmatch(step["uses"]), (path.name, job_id, step)
                    if step["uses"].startswith("actions/checkout@"):
                        assert step["with"]["persist-credentials"] is False, (path.name, job_id)
                    if step["uses"].startswith("actions/setup-python@"):
                        assert "cache" not in step.get("with", {}), (path.name, job_id)  # no cache a pull request could poison
                assert "${{" not in step.get("run", ""), (path.name, job_id, step.get("name"))  # expressions reach a script only through env
                named = bool(TOKEN.search(str(step.get("env", ""))) or TOKEN.search(str(step.get("with", ""))))
                assert named == ((path.name, job_id, step.get("name")) in TOKEN_STEPS), (path.name, job_id, step.get("name"))
                token_steps += named
        assert len(TOKEN.findall(text)) == token_steps == sum(1 for t in TOKEN_STEPS if t[0] == path.name), path.name


def _combinations(job):
    """The matrix combinations GitHub runs: the product of the axes, each extended by the `include` rows that match it."""
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    combos = [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else [{}]
    for row in matrix.get("include", []):
        hits = [c for c in combos if all(c.get(k, v) == v for k, v in row.items() if k in axes)]
        for c in hits:
            c.update({k: v for k, v in row.items() if k not in axes})
        if not hits:
            combos.append(dict(row))
    return combos


def _resolve(value, combo):
    def one(m):
        assert m.group(1) in combo, (value, combo)  # every combination defines what the expression reads
        return str(combo[m.group(1)])
    return re.sub(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", one, value)


def test_every_install_is_hash_pinned_binary_only():
    used = set()
    for path in FLOWS:
        doc = flow(path)
        for job_id, job in doc["jobs"].items():
            for step in job["steps"]:
                run = step.get("run", "")
                assert not FETCHERS.search(run), (path.name, job_id, run)  # nothing is fetched or installed but by the pinned pip line
                if not re.search(r"\bpip\b", run):
                    continue
                lines = [line.strip() for line in run.strip().splitlines()]
                assert len(lines) == 1 and INSTALL.match(lines[0]), (path.name, job_id, run)
                env = dict(doc.get("env") or {}, **(job.get("env") or {}), **(step.get("env") or {}))
                for combo in _combinations(job):
                    for ref in re.findall(r"-r (\S+)", lines[0]):
                        f = _resolve(env[ref[2:-1]], combo) if ref.startswith('"$') else ref
                        assert (ROOT / f).is_file(), (path.name, job_id, combo, f)
                        used.add(f)
    assert used == {p.relative_to(ROOT).as_posix() for p in REQ_FILES}, used  # every requirement file is installed somewhere, and only those exist


def test_the_matrix_expansion_follows_github():
    job = {"strategy": {"matrix": {"os": ["w", "u"], "python": ["3.9", "3.14"],
                                   "include": [{"python": "3.9", "req": "a"}, {"python": "3.14", "req": "b"}, {"os": "m", "python": "3.13"}]}}}
    combos = _combinations(job)
    assert sorted((c["os"], c["python"], c.get("req")) for c in combos) == [("m", "3.13", None), ("u", "3.14", "b"), ("u", "3.9", "a"),
                                                                           ("w", "3.14", "b"), ("w", "3.9", "a")]
    with pytest.raises(AssertionError):
        [_resolve("${{ matrix.req }}", c) for c in combos]  # the 3.13 leg would install `.github/` and fail


def _requirements(path):
    """(name, version, marker, [hashes], [other options]) per logical line of a requirements file."""
    out = []
    for logical in re.sub(r"\\\n", " ", path.read_text(encoding="utf-8")).splitlines():
        logical = logical.split(" #")[0].strip()
        if not logical or logical.startswith("#"):
            continue
        words = logical.split()
        hashes = [w for w in words if w.startswith("--hash=")]
        head = logical.split(" --")[0].strip()
        others = [w for w in words if w.startswith("-") and not w.startswith("--hash=")]
        m = re.fullmatch(r"([A-Za-z0-9][\w.-]*)==([\w.]+)(?: ; ([\w\s.=<>!'\"]+))?", head)
        assert m, (path.name, head)
        out.append((m.group(1), m.group(2), m.group(3), hashes, others))
    return out


def test_requirement_files_pin_every_package_by_version_and_hash():
    files = {p.relative_to(ROOT).as_posix(): p for p in REQ_FILES}
    assert sorted(files) == [".github/requirements-py39/tests-py39.txt", ".github/requirements/coverage.txt", ".github/requirements/tests-py314.txt",
                             ".github/requirements/zizmor.txt"]
    pins = {}
    for rel, path in files.items():
        rows = _requirements(path)
        assert rows, rel
        for name, version, _marker, hashes, others in rows:
            assert hashes and all(re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", h) for h in hashes), (rel, name)
            assert not others, (rel, name, others)  # no index, find-links, trusted host, editable or URL requirement
        pins[rel] = {name.lower(): version for name, version, _m, _h, _o in rows}
    major = lambda v: int(v.split(".")[0])  # noqa: E731
    assert {"pytest", "pyyaml"} <= set(pins[".github/requirements/tests-py314.txt"]) and major(pins[".github/requirements/tests-py314.txt"]["pytest"]) >= 9
    assert {"pytest", "pyyaml"} <= set(pins[".github/requirements-py39/tests-py39.txt"]) and major(pins[".github/requirements-py39/tests-py39.txt"]["pytest"]) < 9
    assert set(pins[".github/requirements/coverage.txt"]) == {"coverage"} and set(pins[".github/requirements/zizmor.txt"]) == {"zizmor"}


def test_dependabot_updates_the_action_and_package_pins_after_a_cooldown():
    updates = _yaml().safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))["updates"]
    assert [(u["package-ecosystem"], u["directory"]) for u in updates] == [("github-actions", "/"), ("pip", "/.github/requirements")]
    for u in updates:
        assert u["schedule"]["interval"] == "weekly" and u["cooldown"]["default-days"] >= 7, u


def _tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT), capture_output=True, stdin=subprocess.DEVNULL, check=True).stdout
    return [ROOT / name for name in out.decode("utf-8").split("\0") if name]


# Each pattern names one credential format by its fixed prefix; the prefixes are split so this file matches none of them.
CREDENTIALS = [re.compile(p) for p in (
    "-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?" + "PRIVATE" + " KEY(?: BLOCK)?-----",
    r"\b(?:AK" + r"IA|AS" + r"IA)[0-9A-Z]{16}\b",
    r"\bgh[pousr]" + r"_[A-Za-z0-9]{36,}\b",
    r"\bgithub" + r"_pat_[A-Za-z0-9_]{22,}",
    r"\bglpat" + r"-[A-Za-z0-9_-]{20,}",
    r"\bxox[abposr]" + r"-[A-Za-z0-9-]{10,}",
    r"hooks\.slack\.com/" + r"services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+",
    r"\bsk-" + r"(?:ant|proj|svcacct)-[A-Za-z0-9_-]{20,}",
    r"\bsk-" + r"[A-Za-z0-9]{48}\b",
    r"\bhf" + r"_[A-Za-z0-9]{34,}\b",
    r"\bAI" + r"za[0-9A-Za-z_-]{35}(?![\w-])",
    r"\bnpm" + r"_[A-Za-z0-9]{36}\b",
    r"\bpypi" + r"-AgE[A-Za-z0-9_-]{50,}",
    r"\b[sr]k" + r"_live_[0-9A-Za-z]{24,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ" + r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"<>]+:[^/\s@'\"<>]{3,}" + "@[\\w.-]+",
)]


def test_no_tracked_file_holds_a_credential():
    files = _tracked()
    assert len(files) > 100, len(files)
    found = []
    for path in files:
        text = path.read_bytes().decode("utf-8", "replace")
        for pattern in CREDENTIALS:
            found += ["%s: %s" % (path.relative_to(ROOT).as_posix(), m.group(0)[:12]) for m in pattern.finditer(text)]
    assert not found, found


def test_the_credential_patterns_find_their_formats():
    samples = ["-----BEGIN " + "PGP PRIVATE" + " KEY BLOCK-----", "AK" + "IA" + "ABCDEFGHIJKLMNOP", "gh" + "p_" + "a" * 36, "github" + "_pat_" + "a" * 30,
               "gl" + "pat-" + "b" * 20, "xo" + "xb-" + "1234567890-abc", "https://hooks.slack.com/" + "services/T0123/B0456/abcdef", "sk-" + "ant-" + "a" * 30,
               "sk-" + "c" * 48, "hf" + "_" + "d" * 34, 'key = "AI' + 'za' + "b" * 34 + '-"', "np" + "m_" + "c" * 36, "py" + "pi-AgE" + "d" * 60,
               "sk" + "_live_" + "e" * 30, "ey" + "J" + "f" * 12 + ".ey" + "J" + "g" * 12 + "." + "h" * 12, "https://" + "user:" + "hunter2@example.com"]
    assert len(samples) == len(CREDENTIALS)
    for pattern, sample in zip(CREDENTIALS, samples):
        assert pattern.search(sample), (pattern.pattern, sample)
    assert CREDENTIALS[0].search("-----BEGIN " + "OPENSSH PRIVATE" + " KEY-----")
    for clean in ("--hash=sha256:" + "0" * 64, "git@github.com:owner/repo.git", "https://github.com/owner/repo", "ghp_short", "sk-learn"):
        assert not any(p.search(clean) for p in CREDENTIALS), clean


NETWORK_MODULES = {"socket", "ssl", "http", "urllib.request", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "asyncio",
                   "socketserver", "webbrowser", "multiprocessing", "logging.handlers", "wsgiref", "requests", "httpx", "urllib3", "aiohttp"}
# The git subcommands the guard may run; none of them talks to a remote. A new one is a deliberate change to this list.
LOCAL_GIT = {"--version", "branch", "check-ref-format", "config", "diff", "for-each-ref", "merge-base", "rev-parse", "status", "worktree"}
NETWORK_GIT = {"fetch", "pull", "push", "clone", "ls-remote", "remote", "submodule", "fetch-pack", "send-pack", "http-fetch", "http-push",
               "upload-pack", "receive-pack", "upload-archive", "archive", "daemon", "request-pull", "send-email", "imap-send", "svn", "p4"}
NETWORK_WORDS = re.compile(r"\b(?:curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|Start-BitsTransfer|bitsadmin|certutil|nc|ncat|socat|telnet|ftp|"
                           r"ssh|scp|sftp|rsync)\b|/dev/(?:tcp|udp)|://", re.I)


def _imports(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names |= {node.module} | {"%s.%s" % (node.module, a.name) for a in node.names}
    return names


def _parents(tree):
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node
    return tree


def _enclosing(node, kind):
    while node is not None and not isinstance(node, kind):
        node = getattr(node, "parent", None)
    return node


def _git_subcommands(tree):
    """The subcommand of every `.run(...)` / `.text(...)` call on a Git object: global options before it are skipped, a starred tuple is
    resolved from its assignment; Git.text forwarding its own *args is the one call without a subcommand of its own."""
    tuples = {t.id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple) for t in n.targets
              if isinstance(t, ast.Name)}
    subs, unresolved = set(), []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("run", "text")):
            continue
        if isinstance(call.func.value, ast.Name) and call.func.value.id == "subprocess":
            continue  # the one process launch, checked below
        fn = _enclosing(call, ast.FunctionDef)
        cls = _enclosing(fn, ast.ClassDef)
        args = list(call.args)
        if fn is not None and fn.name == "text" and cls is not None and cls.name == "Git" and isinstance(args[0], ast.Starred):
            continue
        if args and isinstance(args[0], ast.Starred) and isinstance(args[0].value, ast.Name) and args[0].value.id in tuples:
            args = list(tuples[args[0].value.id].elts) + args[1:]
        while args and (isinstance(args[0], ast.BinOp) and isinstance(args[0].left, ast.Constant) and str(args[0].left.value).startswith("--")
                        or isinstance(args[0], ast.Constant) and str(args[0].value).startswith("--") and str(args[0].value) != "--version"):
            args = args[1:]  # a global option such as --git-dir=<path>
        if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            subs.add(args[0].value)
        else:
            unresolved.append(call.lineno)
    return subs, unresolved


def test_the_hook_code_opens_no_network_connection():
    for rel in ("scripts/magos_guard.py", "scripts/sync_hosts.py", "__init__.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        bad = {n for n in _imports(tree) if n in NETWORK_MODULES or n.split(".")[0] in NETWORK_MODULES - {"http"} or n.startswith("http.")}
        assert not bad, (rel, bad)
        dynamic = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("__import__", "import_module")]
        assert not dynamic, rel
        os_calls = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "os"
                    and re.fullmatch(r"system|popen|startfile|exec\w*|spawn\w*|posix_spawn\w*|fork\w*", n.attr)]
        assert not os_calls, (rel, os_calls)
        from_os = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module in ("os", "subprocess", "ctypes") for a in n.names}
        assert not from_os, (rel, from_os)
    assert "subprocess" not in _imports(ast.parse((ROOT / "scripts" / "sync_hosts.py").read_text(encoding="utf-8")))

    # The guard starts processes at one place, Git.run, whose argv starts with git.
    source = (ROOT / "scripts" / "magos_guard.py").read_text(encoding="utf-8")
    tree = _parents(ast.parse(source))
    aliases = [a for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names if a.name in ("subprocess", "ctypes") and a.asname]
    assert not aliases
    used = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "subprocess"]
    assert {n.attr for n in used} == {"run", "DEVNULL", "TimeoutExpired"}, {n.attr for n in used}
    launches = [n for n in used if n.attr == "run"]
    assert len(launches) == 1 and _enclosing(launches[0], ast.FunctionDef).name == "run" and _enclosing(launches[0], ast.ClassDef).name == "Git"
    run = _enclosing(launches[0], ast.FunctionDef)
    assert 'cmd = ["git"] + _PIN' in ast.get_source_segment(source, run) and launches[0].parent.args[0].id == "cmd"

    # Every git subcommand it runs is local.
    subs, unresolved = _git_subcommands(tree)
    assert not unresolved, unresolved  # a call whose subcommand the check cannot read
    assert subs <= LOCAL_GIT and not subs & NETWORK_GIT, sorted(subs)
    assert {"diff", "rev-parse", "worktree", "--version"} <= subs, sorted(subs)

    # ctypes reads the console mode on Windows, nothing else.
    windll = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "windll"]
    assert [n.attr for n in windll] == ["kernel32"]
    k = _enclosing(windll[0], ast.Assign).targets[0].id
    console = _enclosing(windll[0], ast.FunctionDef)
    assert {n.attr for n in ast.walk(console) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == k} == {"GetConsoleMode", "GetStdHandle"}
    assert {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "ctypes"} == {"windll", "byref", "c_uint32"}

    # The launcher only finds an interpreter and runs the guard; the git-layer hook `arm` installs runs git rev-parse and the chained hook.
    launcher = (ROOT / "hooks" / "run-guard.cmd").read_text(encoding="utf-8")
    assert not NETWORK_WORDS.search(launcher), NETWORK_WORDS.findall(launcher)
    assert not NETWORK_WORDS.search(G.HOOK_SH), NETWORK_WORDS.findall(G.HOOK_SH)
    commands = re.sub(r"(?m)^#.*$", "", G.HOOK_SH)
    assert set(re.findall(r"(?m)(?:^|[;&|(])\s*git\s+([a-z][\w-]*)", commands)) == {"rev-parse"}  # in command position; messages name `git status`

def test_the_network_check_sees_every_call_shape():
    """The subcommand reader resolves the guard's real call shapes, and a remote subcommand behind any of them is found."""
    def subs_of(code):
        return _git_subcommands(_parents(ast.parse(code)))
    assert subs_of("g.text('fetch', 'origin')") == ({"fetch"}, [])
    assert subs_of("diff = ('ls-remote', 'origin')\ng.run(*diff, 'x')") == ({"ls-remote"}, [])
    assert subs_of("Git(s).run('--git-dir=' + p, 'push', 'x')") == ({"push"}, [])
    assert subs_of("args = make()\ng.run(*args)")[1] == [2]
    assert subs_of("g.run(name)")[1] == [1]
