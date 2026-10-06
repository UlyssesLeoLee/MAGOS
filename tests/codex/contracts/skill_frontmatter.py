# ```cypher
# CREATE
#   (file:File {name: "skill_frontmatter.py", type: "file", language: "python"}),
#   (v_KEY:Variable {name: "KEY", type: "variable"}),
#   (v_UNSAFE:Variable {name: "UNSAFE", type: "variable"}),
#   (v_DOUBLE_QUOTED:Variable {name: "DOUBLE_QUOTED", type: "variable"}),
#   (v_PLAIN_FIRST:Variable {name: "PLAIN_FIRST", type: "variable"}),
#   (v_YAML11_WORDS:Variable {name: "YAML11_WORDS", type: "variable"}),
#   (f_split:Function {name: "split", type: "function", signature: "split(text: str) -> str"}),
#   (f_scalar:Function {name: "scalar", type: "function", signature: "scalar(raw: str, line: int) -> tuple[str, str]"}),
#   (f_parse:Function {name: "parse", type: "function", signature: "parse(text: str) -> tuple[dict, dict]"}),
#   (f_cross_check:Function {name: "cross_check", type: "function", signature: "cross_check(text: str, fields: dict) -> str | None"}),
#   (file)-[:CONTAINS]->(v_KEY),
#   (file)-[:CONTAINS]->(v_UNSAFE),
#   (file)-[:CONTAINS]->(v_DOUBLE_QUOTED),
#   (file)-[:CONTAINS]->(v_PLAIN_FIRST),
#   (file)-[:CONTAINS]->(v_YAML11_WORDS),
#   (file)-[:CONTAINS]->(f_split),
#   (file)-[:CONTAINS]->(f_scalar),
#   (file)-[:CONTAINS]->(f_parse),
#   (file)-[:CONTAINS]->(f_cross_check),
#   (f_cross_check)-[:CALLS]->(f_split),
#   (f_parse)-[:CALLS]->(f_scalar),
#   (f_parse)-[:CALLS]->(f_split),
#   (f_parse)-[:USES]->(v_KEY),
#   (f_parse)-[:USES]->(v_YAML11_WORDS),
#   (f_scalar)-[:USES]->(v_DOUBLE_QUOTED),
#   (f_scalar)-[:USES]->(v_PLAIN_FIRST),
#   (f_scalar)-[:USES]->(v_YAML11_WORDS),
#   (f_split)-[:USES]->(v_UNSAFE);
# ```
"""Strict reader for the YAML subset that MAGOS uses in SKILL.md frontmatter (standard library only).

Accepted: column-0 `key: value` lines, and one nested map (`key:` followed by `  child: value` lines). A value is a
double-quoted string (JSON escapes, only \\" and \\\\), a single-quoted string ('' escapes a quote), or a plain scalar
that every YAML parser reads as the same string. Everything else is rejected instead of guessed: flow collections,
sequences, block scalars, anchors, aliases, tags, comments, tabs, duplicate keys, deeper nesting, and plain scalars
that YAML reads differently (": ", " #", a leading indicator, or a bool/null/number-like word).

Anything this reader accepts therefore parses to the same strings under PyYAML and under strictyaml, which the
Agent Skills reference validator (skills-ref) uses and which rejects flow style outright. When PyYAML is installed,
cross_check() confirms that. The regex reader it replaces could not see either defect.
"""

import json
import re

KEY = re.compile(r"([A-Za-z0-9_-]+):(?: (.*))?")
# Anything outside YAML's printable set, plus every character some loader reads as a line break (CR, NEL, LS, PS):
# loaders reject these or fold them into spaces, so a value holding one would not read the same everywhere.
UNSAFE = re.compile("[^\\n\\x20-\\x7e\\xa0-\\u2027\\u202a-\\ud7ff\\ue000-\\ufffd\\U00010000-\\U0010ffff]")
DOUBLE_QUOTED = re.compile(r'"(?:[^"\\]|\\["\\])*"')
PLAIN_FIRST = set("-?:,[]{}#&*!|>'\"%@`~")
YAML11_WORDS = {"y", "n", "yes", "no", "true", "false", "on", "off", "null"}


class FrontmatterError(ValueError):
    """The frontmatter is outside the accepted subset; the message names the line."""


def split(text: str) -> str:
    """Return the frontmatter block of a SKILL.md text (without the --- fences)."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise FrontmatterError("line 1: the file must start with '---'")
    end = text.find("\n---\n", 3)
    if end < 0 and text.endswith("\n---"):  # the closing fence is the last line, with no newline after it
        end = len(text) - 4
    if end < 0:
        raise FrontmatterError("no closing '---' line")
    block = text[4:end]
    if "---" in block:
        raise FrontmatterError("'---' inside the frontmatter ends it early for skills-ref (content.split('---', 2))")
    bad = UNSAFE.search(block)
    if bad:
        raise FrontmatterError(f"line {block.count(chr(10), 0, bad.start()) + 2}: character U+{ord(bad.group()):04X} is "
                               f"a control, line-break, or non-printable character that YAML loaders reject or fold")
    return block


def scalar(raw: str, line: int) -> tuple[str, str]:
    """Return (value, style) for one scalar; style is 'double', 'single', or 'plain'."""
    if raw.startswith('"'):
        if not DOUBLE_QUOTED.fullmatch(raw):
            raise FrontmatterError(f"line {line}: a double-quoted string takes only \\\" and \\\\ escapes, and nothing "
                                   f"may follow its closing quote")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise FrontmatterError(f"line {line}: invalid double-quoted string ({error.msg})") from None
        if not isinstance(value, str):
            raise FrontmatterError(f"line {line}: not a string")
        return value, "double"
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'") or "'" in raw[1:-1].replace("''", ""):
            raise FrontmatterError(f"line {line}: invalid single-quoted string")
        return raw[1:-1].replace("''", "'"), "single"
    if not raw or raw[0] in PLAIN_FIRST:
        raise FrontmatterError(f"line {line}: a plain value must not be empty or start with {raw[:1]!r}; quote it")
    if ": " in raw or raw.endswith(":") or " #" in raw:
        raise FrontmatterError(f"line {line}: a plain value must not contain ': ' or ' #' or end with ':'; quote it")
    if (raw.lower() in YAML11_WORDS or re.match(r"[-+.]?[0-9]", raw) or raw.startswith((".", "<<", "="))
            or re.fullmatch(r"[-+]\.(inf|nan)", raw, re.I)):
        raise FrontmatterError(f"line {line}: YAML may read {raw!r} as a non-string; quote it")
    return raw, "plain"


def parse(text: str) -> tuple[dict, dict]:
    """Return (fields, styles) for a SKILL.md text; styles maps 'key' or 'parent.key' to the scalar style."""
    fields: dict = {}
    styles: dict = {}
    parent = None
    for number, line in enumerate(split(text).split("\n"), start=2):
        if not line.strip(" "):
            continue
        if "\t" in line:
            raise FrontmatterError(f"line {number}: tab character")
        # Only the ASCII space is YAML whitespace here: NBSP, U+3000 and the like are content, so str.strip() would
        # silently drop characters that every loader keeps (or chokes on).
        indent = len(line) - len(line.lstrip(" "))
        match = KEY.fullmatch(line.strip(" "))
        if not match:
            raise FrontmatterError(f"line {number}: expected 'key: value' (no comments, sequences, or flow style)")
        key, raw = match.group(1), (match.group(2) or "").strip(" ")
        if key.lower() in YAML11_WORDS or key[0] in "0123456789-":
            raise FrontmatterError(f"line {number}: key {key!r} may be read as a non-string (bool, null, number); "
                                   f"rename it")
        if indent == 0:
            if key in fields:
                raise FrontmatterError(f"line {number}: duplicate key {key!r}")
            if raw:
                fields[key], styles[key] = scalar(raw, number)
                parent = None
            else:
                fields[key], parent = {}, key
        elif indent == 2 and parent is not None:
            if key in fields[parent]:
                raise FrontmatterError(f"line {number}: duplicate key {parent}.{key}")
            if not raw:
                raise FrontmatterError(f"line {number}: {parent}.{key} nests a map below a map; values must be strings")
            fields[parent][key], styles[f"{parent}.{key}"] = scalar(raw, number)
        else:
            raise FrontmatterError(f"line {number}: unexpected indentation")
    empty = [key for key, value in fields.items() if value == {}]
    if empty:
        raise FrontmatterError(f"{empty[0]!r} has no value (YAML reads it as null)")
    return fields, styles


def cross_check(text: str, fields: dict) -> str | None:
    """Compare with PyYAML when it is installed; return a problem, or None when it agrees or is unavailable."""
    try:
        import yaml
    except ImportError:
        return None
    try:
        loaded = yaml.safe_load(split(text))
    except yaml.YAMLError as error:
        return f"PyYAML rejects the frontmatter: {str(error).splitlines()[0]}"
    return None if loaded == fields else "PyYAML reads the frontmatter differently from the strict reader"
