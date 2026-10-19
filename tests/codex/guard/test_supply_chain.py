"""Supply-chain and network contracts of the repository: every workflow is pinned and read-only, runs only listed commands and installs
only hash-pinned wheels; Dependabot keeps the pins current after a cooldown; no tracked file holds a credential; the hook code imports no
network module, starts only git, and its git runs only local subcommands."""
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
INSTALL = re.compile(r"python -m pip install --require-hashes --only-binary :all:(?: -r (\"\$\w+\"|\.github/requirements(?:-py39)?/[\w.-]+\.txt))+")
# Every line a workflow may run. A new command is a deliberate change to this list: nothing else fetches, installs or starts a program.
RUN_LINES = [INSTALL] + [re.compile(p) for p in (
    re.escape("python -VV"), re.escape("git --version"), re.escape("command -v sh"),
    r"python -m pytest(?: (?:tests/[\w/.]+(?:::\w+)?|-q|-ra|-p no:cacheprovider|--basetemp=\"\$RUNNER_TEMP/\w+\"))+",
    r"python -X utf8 tests/(?:codex|claude)/[\w/]+\.py(?: --check)?",
    re.escape('changes="$(git status --porcelain --untracked-files=all)"'), re.escape('if [ -n "$changes" ]; then'),
    re.escape("printf '%s\\n' \"$changes\""), re.escape("exit 1"), re.escape("fi"),
    re.escape("version=\"$(sed -n 's/^version: *\\([^ ]*\\) *$/\\1/p' plugin.yaml)\""), re.escape('if [ "$TAG" != "v$version" ]; then'),
    re.escape("printf 'tag %s is not v%s\\n' \"$TAG\" \"$version\""),
    re.escape("zizmor --no-ignores --no-config --collect=all --strict-collection --format github --persona pedantic ."),
)]
# Every environment variable a workflow may set; pip reads PIP_* variables as options, so only the version check may be switched off.
ENV_KEYS = {"PYTHONDONTWRITEBYTECODE", "PYTHONUTF8", "PIP_DISABLE_PIP_VERSION_CHECK", "REQUIREMENTS", "TAG", "GH_TOKEN"}
SECRETS = re.compile(r"\bsecrets\b|\btojson\s*\(", re.I)
TOKEN = re.compile(r"\bgithub\s*(?:\.\s*token\b|\[\s*['\"]token['\"]\s*\])", re.I)
# Every action a workflow may use, with the inputs it may set (an input such as checkout's `repository` or setup-python's `pip-version`
# would fetch other code).
ACTION_INPUTS = {"actions/checkout": {"persist-credentials"}, "actions/setup-python": {"python-version"},
                 "github/codeql-action/init": {"languages", "build-mode"}, "github/codeql-action/analyze": {"category"}}
JOB_KEYS = {"name", "runs-on", "timeout-minutes", "permissions", "strategy", "defaults", "steps", "env"}  # no container, services or reusable workflow
RUNNERS = {"ubuntu-latest", "windows-latest"}
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


def trigger_names(doc):
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads the bare key `on` as true
    assert isinstance(on, (str, list, dict)), on
    return {on} if isinstance(on, str) else set(on)


def _envs(doc):
    yield "workflow", doc.get("env") or {}
    for job_id, job in doc["jobs"].items():
        yield job_id, job.get("env") or {}
        for step in job["steps"]:
            yield "%s/%s" % (job_id, step.get("name")), step.get("env") or {}


def test_workflows_are_pinned_read_only_and_timed():
    names = [p.name for p in FLOWS]
    assert names == ["codeql.yml", "security.yml", "test.yml"], names
    for path in FLOWS:
        text = path.read_text(encoding="utf-8")
        doc = flow(path)
        assert not {"pull_request_target", "workflow_run"} & trigger_names(doc), path.name
        assert not SECRETS.search(text), path.name  # no repository secret, in any spelling (`secrets.X`, `secrets['X']`, toJSON)
        assert not re.search(r"zizmor\s*:\s*ignore", text, re.I), path.name  # no inline ignore (the gate also runs --no-ignores)
        top = doc.get("permissions")
        assert isinstance(top, dict) and set(top.values()) <= {"read", "none"}, (path.name, top)
        assert "concurrency" in doc, path.name
        assert set(doc) <= {"name", "on", True, "permissions", "concurrency", "env", "jobs"}, (path.name, set(doc))  # no workflow-level defaults
        for where, env in _envs(doc):
            assert set(env) <= ENV_KEYS, (path.name, where, sorted(set(env) - ENV_KEYS))
        for line in text.splitlines():
            if re.match(r"^\s*(?:- )?uses:", line):
                assert PIN_LINE.match(line), (path.name, line)  # a full commit SHA, with its tag in the comment
        token_steps = 0
        for job_id, job in doc["jobs"].items():
            assert isinstance(job.get("timeout-minutes"), int), (path.name, job_id)
            assert set(job) <= JOB_KEYS, (path.name, job_id, sorted(set(job) - JOB_KEYS))
            oses = [c.get("os") for c in _combinations(job)] if job["runs-on"] == "${{ matrix.os }}" else [job["runs-on"]]
            assert oses and set(oses) <= RUNNERS, (path.name, job_id, oses)
            assert (job.get("defaults") or {"run": {"shell": "bash"}}) == {"run": {"shell": "bash"}}, (path.name, job_id)
            for scope, level in (job.get("permissions") or {}).items():
                assert level in ("read", "none") or (path.name, job_id, scope) in WRITE_GRANTS, (path.name, job_id, scope, level)
            for step in job["steps"]:
                assert "shell" not in step and "working-directory" not in step, (path.name, job_id, step.get("name"))
                if "uses" in step:
                    assert SHA_PIN.fullmatch(step["uses"]), (path.name, job_id, step)
                    action = step["uses"].split("@")[0]
                    assert action in ACTION_INPUTS and set(step.get("with") or {}) <= ACTION_INPUTS[action], (path.name, job_id, step)
                    if step["uses"].startswith("actions/checkout@"):
                        assert step["with"]["persist-credentials"] is False, (path.name, job_id)
                    if step["uses"].startswith("actions/setup-python@"):
                        assert "cache" not in step.get("with", {}), (path.name, job_id)  # no cache a pull request could poison
                assert "${{" not in step.get("run", ""), (path.name, job_id, step.get("name"))  # expressions reach a script only through env
                named = bool(TOKEN.search(str(step.get("env", ""))) or TOKEN.search(str(step.get("with", ""))))
                assert named == ((path.name, job_id, step.get("name")) in TOKEN_STEPS), (path.name, job_id, step.get("name"))
                token_steps += named
        assert len(TOKEN.findall(text)) == token_steps == sum(1 for t in TOKEN_STEPS if t[0] == path.name), path.name
    tracked = {p.relative_to(ROOT).as_posix() for p in _tracked()}
    assert not {n for n in tracked if re.search(r"(^|/)\.?zizmor\.ya?ml$", n)}  # no zizmor configuration (the gate also runs --no-config)


def test_trigger_names_read_every_spelling_of_on():
    assert trigger_names({"on": "pull_request_target"}) == {"pull_request_target"}
    assert trigger_names({True: ["push", "workflow_run"]}) == {"push", "workflow_run"}
    assert trigger_names({"on": {"push": None, "schedule": [{"cron": "1 1 * * 1"}]}}) == {"push", "schedule"}


def _combinations(job):
    """The matrix combinations GitHub runs: the product of the axes without the `exclude` matches; each `include` row extends every
    original combination whose axis values it does not contradict, and becomes a combination of its own when it extends none. A row
    never extends a combination another row added."""
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    originals = [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else []
    originals = [c for c in originals if not any(all(c.get(k) == v for k, v in ex.items()) for ex in matrix.get("exclude", []))]
    added = []
    for row in matrix.get("include", []):
        hits = [c for c in originals if all(c[k] == v for k, v in row.items() if k in axes)]
        for c in hits:
            c.update({k: v for k, v in row.items() if k not in axes})
        if not hits:
            added.append(dict(row))
    return (originals + added) or [{}]


def _resolve(value, combo):
    def one(m):
        assert m.group(1) in combo, (value, combo)  # every combination defines what the expression reads
        return str(combo[m.group(1)])
    return re.sub(r"\$\{\{\s*matrix\.([\w-]+)\s*\}\}", one, value)


def test_every_run_line_is_listed_and_every_install_is_hash_pinned():
    used = set()
    for path in FLOWS:
        doc = flow(path)
        for job_id, job in doc["jobs"].items():
            for step in job["steps"]:
                lines = [line.strip() for line in step.get("run", "").strip().splitlines()]
                for line in lines:
                    assert any(p.fullmatch(line) for p in RUN_LINES), (path.name, job_id, line)
                for line in (line for line in lines if INSTALL.fullmatch(line)):
                    env = dict(doc.get("env") or {}, **(job.get("env") or {}), **(step.get("env") or {}))
                    for combo in _combinations(job):
                        for ref in re.findall(r"-r (\S+)", line):
                            f = _resolve(env[ref[2:-1]], combo) if ref.startswith('"$') else ref
                            assert (ROOT / f).is_file(), (path.name, job_id, combo, f)
                            used.add(f)
    assert used == {p.relative_to(ROOT).as_posix() for p in REQ_FILES}, used  # every requirement file is installed somewhere, and only those exist


def test_the_run_allowlist_refuses_other_commands():
    for line in ("pip3 install requests", "python -mpip install requests", "python -m pip install requests", "pipenv install x", "poetry install",
                 "git clone https://example.com/x", "gh release download -R x/y", "curl -LsSf https://example.com/i.sh | sh",
                 'echo "PIP_INDEX_URL=https://example.com" >> "$GITHUB_ENV"', "python -c 'import urllib.request'",
                 "python -m pip install --require-hashes --only-binary :all: -r evil.txt", "python -m pytest tests/x.py; curl x",
                 "zizmor --strict-collection --format github --persona pedantic ."):
        assert not any(p.fullmatch(line) for p in RUN_LINES), line


def test_the_matrix_expansion_follows_github():
    # GitHub's documented example for expanding or adding matrix configurations.
    job = {"strategy": {"matrix": {"fruit": ["apple", "pear"], "animal": ["cat", "dog"],
                                   "include": [{"color": "green"}, {"color": "pink", "animal": "cat"}, {"fruit": "apple", "shape": "circle"},
                                               {"fruit": "banana"}, {"fruit": "banana", "animal": "cat"}]}}}
    key = lambda c: sorted(c.items())  # noqa: E731
    assert sorted(_combinations(job), key=key) == sorted([
        {"fruit": "apple", "animal": "cat", "color": "pink", "shape": "circle"}, {"fruit": "apple", "animal": "dog", "color": "green", "shape": "circle"},
        {"fruit": "pear", "animal": "cat", "color": "pink"}, {"fruit": "pear", "animal": "dog", "color": "green"},
        {"fruit": "banana"}, {"fruit": "banana", "animal": "cat"}], key=key)
    assert _combinations({"strategy": {"matrix": {"include": [{"site": "a", "dc": "x"}, {"site": "b", "dc": "y"}]}}}) == [
        {"site": "a", "dc": "x"}, {"site": "b", "dc": "y"}]
    assert _combinations({"strategy": {"matrix": {"python": ["3.9", "3.13", "3.14"], "exclude": [{"python": "3.13"}]}}}) == [
        {"python": "3.9"}, {"python": "3.14"}]
    legs = _combinations({"strategy": {"matrix": {"python": ["3.9", "3.14"], "include": [{"python": "3.9", "req": "a"}, {"python": "3.13"}]}}})
    with pytest.raises(AssertionError):
        [_resolve("${{ matrix.req }}", c) for c in legs]  # the 3.14 and 3.13 legs define no `req`


def _requirements(path):
    """(name, version, marker, [hashes], [other options]) per requirement, read the way pip reads the file: a line ending in a backslash
    continues on the next unless it is a comment, and a comment runs from `#` (at the start or after whitespace) to the end of the line."""
    raw = path.read_bytes()
    # pip decodes by a byte-order mark or a `coding:` line in the first two lines: ASCII without either reads the same for pip and here
    assert raw.isascii() and not re.search(rb"coding[:=]", b"\n".join(raw.splitlines()[:2])), path.name
    text = raw.decode("ascii").replace("\r\n", "\n")
    assert "${" not in text, path.name  # pip would expand an environment variable here
    logical, parts = [], []
    for line in text.splitlines():
        comment = re.match(r"(^|\s+)#.*$", line)
        if line.endswith("\\") and not comment:
            parts.append(line[:-1])
            continue
        logical.append("".join(parts) + (" " + line if comment else line))
        parts = []
    if parts:
        logical.append("".join(parts))
    out = []
    for item in logical:
        item = re.sub(r"(^|\s+)#.*$", "", item).strip()
        if not item:
            continue
        words = item.split()
        hashes = [w for w in words if w.startswith("--hash=")]
        others = [w for w in words if w.startswith("-") and not w.startswith("--hash=")]
        head = item.split(" --")[0].strip()
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
        for name, _version, _marker, hashes, others in rows:
            assert hashes and all(re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", h) for h in hashes), (rel, name)
            assert not others, (rel, name, others)  # no index, find-links, trusted host, editable, nested file or URL requirement
        pins[rel] = {name.lower(): version for name, version, _m, _h, _o in rows}
    major = lambda v: int(v.split(".")[0])  # noqa: E731
    assert {"pytest", "pyyaml"} <= set(pins[".github/requirements/tests-py314.txt"]) and major(pins[".github/requirements/tests-py314.txt"]["pytest"]) >= 9
    assert {"pytest", "pyyaml"} <= set(pins[".github/requirements-py39/tests-py39.txt"]) and major(pins[".github/requirements-py39/tests-py39.txt"]["pytest"]) < 9
    assert set(pins[".github/requirements/coverage.txt"]) == {"coverage"} and set(pins[".github/requirements/zizmor.txt"]) == {"zizmor"}


def test_the_requirement_reader_reads_like_pip(tmp_path):
    f = tmp_path / "r.txt"
    h = "--hash=sha256:" + "a" * 64
    f.write_text("# note \\\nx==1 \\\n    %s  # trailing\n" % h, encoding="utf-8")
    assert _requirements(f) == [("x", "1", None, [h], [])]
    f.write_text("# note \\\n--extra-index-url https://example.com/simple\nx==1 %s\n" % h, encoding="utf-8")
    with pytest.raises(AssertionError):
        _requirements(f)  # a comment does not continue: pip reads the option on the next line, and so does the reader
    f.write_text("# -*- coding: utf-7 -*-\nx==1 %s\n" % h, encoding="utf-8")
    with pytest.raises(AssertionError):
        _requirements(f)  # pip would decode the rest as UTF-7, which can spell lines this reader does not see
    f.write_bytes(b"\xef\xbb\xbfx==1 " + h.encode() + b"\n")
    with pytest.raises(AssertionError):
        _requirements(f)
    f.write_text("x==${V} %s\n" % h, encoding="utf-8")
    with pytest.raises(AssertionError):
        _requirements(f)


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
PROCESS_MODULES = {"pty", "posix", "nt", "_posixsubprocess", "_winapi", "multiprocessing"}
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


def _without_messages(body):
    """The shell words of the text, read left to right as the shell reads them: comments dropped; a quoted string that holds a space and
    no command substitution (a message or an argument, never a command) replaced by a space; any other quoted string unwrapped and a
    backslash escape outside quotes resolved, so `g""it`, `"git"` and `g\\it` read as `git`."""
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c == "#" and (i == 0 or body[i - 1].isspace()):  # a word that starts with # starts a comment
            while i < n and body[i] != "\n":
                i += 1
        elif c in "'\"":
            j = i + 1
            while j < n and body[j] != c:
                j += 2 if c == '"' and body[j] == "\\" else 1
            seg = body[i:j + 1]
            out.append(" " if re.search(r"\s", seg) and "$(" not in seg and "`" not in seg else seg[1:-1])
            i = j + 1
        elif c == "\\":
            out.append(body[i + 1:i + 2])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def hook_git_subcommands(text):
    """The subcommand of every `git` the shell text runs, by name or by path: comments and messages are data; global options before the
    subcommand (`-C <dir>`, `-c <k=v>`, `--x`) are skipped."""
    body = _without_messages(text)
    subs = []
    for m in re.finditer(r"(?<![\w.$-])(?:[\w.-]*/)*git(?![\w.-])", body):
        words = body[m.end():].split()
        i = 0
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] in ("-C", "-c") else 1
        subs.append(words[i].strip("\"';)`") if i < len(words) else "")
    return subs


def test_the_hook_code_opens_no_network_connection(monkeypatch, tmp_path):
    for rel in ("scripts/magos_guard.py", "scripts/sync_hosts.py", "__init__.py"):
        tree = _parents(ast.parse((ROOT / rel).read_text(encoding="utf-8")))
        names = _imports(tree)
        bad = {n for n in names if n in NETWORK_MODULES | PROCESS_MODULES or n.split(".")[0] in (NETWORK_MODULES | PROCESS_MODULES) - {"http"}
               or n.startswith("http.")}
        assert not bad, (rel, bad)
        dynamic = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("__import__", "import_module")]
        assert not dynamic, (rel, dynamic)
        os_calls = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "os"
                    and re.fullmatch(r"system|popen|startfile|exec\w*|spawn\w*|posix_spawn\w*|fork\w*", n.attr)]
        assert not os_calls, (rel, os_calls)
        process_pool = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "ProcessPoolExecutor"
                        or isinstance(n, ast.Name) and n.id == "ProcessPoolExecutor"
                        or isinstance(n, ast.ImportFrom) and any(a.name in ("ProcessPoolExecutor", "*") for a in n.names)]
        assert not process_pool, (rel, process_pool)
        # no code built at run time and no way around the import rules: exec, eval, compile, builtins, sys.modules
        hidden = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ("exec", "eval", "compile", "__import__", "globals", "vars")
                  or isinstance(n, ast.Name) and n.id in ("__builtins__", "builtins")
                  or isinstance(n, ast.Attribute) and n.attr == "modules" and getattr(n.value, "id", "") == "sys"]
        assert not hidden and "builtins" not in names and "importlib" not in names, (rel, hidden)
        from_mod = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module in ("os", "subprocess", "ctypes") for a in n.names}
        assert not from_mod, (rel, from_mod)
        aliased = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names if a.name in ("os", "subprocess", "ctypes") and a.asname]
        assert not aliased, (rel, aliased)
        # os, subprocess and ctypes are used only by attribute: never passed on, rebound or reached through getattr
        loose = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in ("os", "subprocess", "ctypes")
                 and not (isinstance(n.parent, ast.Attribute) and n.parent.value is n)]
        assert not loose, (rel, loose)
    assert "subprocess" not in _imports(ast.parse((ROOT / "scripts" / "sync_hosts.py").read_text(encoding="utf-8")))

    # The guard starts processes at one place, Git.run, whose argv is git, the pinned options and the arguments.
    source = (ROOT / "scripts" / "magos_guard.py").read_text(encoding="utf-8")
    tree = _parents(ast.parse(source))
    used = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "subprocess"]
    assert {n.attr for n in used} == {"run", "DEVNULL", "TimeoutExpired"}, {n.attr for n in used}
    launches = [n for n in used if n.attr == "run"]
    assert len(launches) == 1 and _enclosing(launches[0], ast.FunctionDef).name == "run" and _enclosing(launches[0], ast.ClassDef).name == "Git"
    run = _enclosing(launches[0], ast.FunctionDef)
    assert 'cmd = ["git"] + _PIN' in ast.get_source_segment(source, run) and launches[0].parent.args[0].id == "cmd"
    assert G._PIN == ["-c", "core.quotepath=false", "-c", "core.longpaths=true", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                      "--no-optional-locks"]  # the guard's git starts no fsmonitor program and writes no untracked cache

    # Git.run refuses every subcommand outside the local set before it starts git, whatever call shape reaches it.
    assert G.LOCAL_GIT and not G.LOCAL_GIT & NETWORK_GIT, sorted(G.LOCAL_GIT)
    started = []
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: started.append(a) or pytest.fail("git started"))
    g = G.Git(str(tmp_path))
    for args in (("fetch", "origin"), ("ls-remote",), ("--git-dir=x", "push"), ("--config-env=core.fsmonitor=X", "status"), ("-c", "a=b", "status"),
                 ("remote", "update"), ()):
        with pytest.raises(G.GitFail) as err:
            g.run(*args)
        refused = next((a for a in args if not a.startswith("--git-dir=")), "(none)")
        assert err.value.code == "GIT_FAILED" and "git %s is not a subcommand the guard runs" % refused in str(err.value), (args, str(err.value))
    with pytest.raises(G.GitFail):
        getattr(g, "text")("submodule", "update")
    assert started == []
    literal = {n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("run", "text") and n.args
               and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) and not n.args[0].value.startswith("--git-dir")}
    assert literal <= G.LOCAL_GIT, sorted(literal - G.LOCAL_GIT)  # every subcommand written as the first literal argument is in the set

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
    assert not re.search(r"\b(?:%s)\b" % "|".join(map(re.escape, sorted(NETWORK_GIT))), G.HOOK_SH)
    assert not re.search(r"\beval\b|\b(?:ba|z|da)?sh\s+-c\b", G.HOOK_SH)
    assert set(hook_git_subcommands(G.HOOK_SH)) == {"rev-parse"}


def test_the_hook_text_reader_finds_every_git():
    assert hook_git_subcommands('if git fetch -q origin; then :; fi') == ["fetch"]
    assert hook_git_subcommands('[ -d "$g" ] && git -C "$g" push -q origin HEAD') == ["push"]
    assert hook_git_subcommands('"git" ls-remote x; cur=$(git rev-parse --verify -q "$r")') == ["ls-remote", "rev-parse"]
    assert hook_git_subcommands('deny "check git status first" x; # git fetch\n[ -d .git ] && git --no-pager rev-parse') == ["rev-parse"]
    assert hook_git_subcommands('printf "%s" "x" git fetch "y"') == ["fetch"]  # quotes pair left to right
    assert hook_git_subcommands('v="$(git push -q origin)"; w="`git pull`"') == ["push", "pull"]  # a substitution in quotes runs
    assert hook_git_subcommands('/usr/bin/git fetch; g""it push; g\\it pull') == ["fetch", "push", "pull"]  # by path, split, escaped
    assert hook_git_subcommands('[ -d "$CD/.git" ] && read -r l <"$g/gitdir"') == []
