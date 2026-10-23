"""The READMEs in the three languages (README.md Chinese, README.en.md English, README.ja.md Japanese) offer the same choice of language, and the
Japanese one follows the Chinese one section for section: the same outline, tables and command blocks, diagrams of the same shape, and the same
files, flags and commands named in inline code.  A command block is written for its reader as well: only its commands must be the same."""
from __future__ import annotations

import re

import pytest

from conftest import ROOT

FILES = {"zh": "README.md", "en": "README.en.md", "ja": "README.ja.md"}
SWITCH = "[English](README.en.md) | [中文](README.md) | [日本語](README.ja.md)"
CODE_LANGS = ("bash", "powershell", "json", "yaml")  # fences whose commands are the same in every language (comments and placeholders aside)
DIAGRAM = "mermaid"  # a diagram is translated: its labels are in the language of the README, its nodes and edges are the same
LITERAL = re.compile(r"/|\\|--|\.md\b|\.py\b|\.json\b|\.ya?ml\b|\.cmd\b|\$|%|~")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8").splitlines()


def parse(rel):
    """(heading levels, [(fence language, body)], [(rows, columns)], inline-code spans outside headings and code) of one README."""
    lines = read(rel)
    heads, fences, tables, spans = [], [], [], set()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        fence = re.match(r"^(`{3,})(\w*)\s*$", line)
        if fence:
            j = i + 1
            while j < n and not lines[j].startswith(fence.group(1)):
                j += 1
            fences.append((fence.group(2), "\n".join(lines[i + 1:j])))
            i = j + 1
            continue
        head = re.match(r"^(#{1,6}) ", line)
        if head:
            heads.append(len(head.group(1)))
            i += 1
            continue
        if line.startswith("|") and i + 1 < n and re.match(r"^\|[-| :]+\|$", lines[i + 1]):
            j = i
            while j < n and lines[j].startswith("|"):
                j += 1
            tables.append((j - i - 2, line.count("|") - 1))
            for row in lines[i:j]:
                spans.update(re.findall(r"`([^`]+)`", row))
            i = j
            continue
        spans.update(re.findall(r"`([^`]+)`", line))
        i += 1
    return heads, fences, tables, {re.sub(r"<[^<>]*>", "<>", s) for s in spans}  # a placeholder is written in the language of the README


def without_comment(line):
    """The line up to its `# ` comment: a '#' that starts the line or follows whitespace, is followed by whitespace and sits outside quotes."""
    quote = ""
    for i, char in enumerate(line):
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (i == 0 or line[i - 1].isspace()) and line[i + 1:i + 2].isspace():
            return line[:i]
    return line


def commands(body):
    """A command block as every language must write it: no `# ` comment, and each <placeholder> read as one (both are written for the reader)."""
    return "\n".join(re.sub(r"<[^<>]*>", "<>", without_comment(line)).rstrip() for line in body.split("\n"))


def shape(body):
    """The nodes and edges of a mermaid diagram: its non-empty lines without the quoted labels of nodes and edges and without the `state "..." as`
    lines that only label a state."""
    lines = (re.sub(r'\[\s*"[^"]*"\s*\]|\{\s*"[^"]*"\s*\}|\|\s*"[^"]*"\s*\|', "", line).rstrip() for line in body.split("\n"))
    return [line for line in lines if line.strip() and not re.match(r'\s*state\s+"', line)]


def test_every_readme_opens_with_the_same_language_switcher():
    for rel in FILES.values():
        lines = read(rel)
        assert lines[0] == "# Multi-Agent Git Orchestrator Skills" and lines[2] == SWITCH, (rel, lines[:3])


def test_the_relative_links_of_every_readme_resolve():
    for rel in FILES.values():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if not re.match(r"[a-z][a-z0-9+.-]*:|#", target):
                assert (ROOT / target.split("#")[0]).exists(), (rel, target)


@pytest.fixture(scope="module")
def zh_ja():
    return parse(FILES["zh"]), parse(FILES["ja"])


def test_the_japanese_readme_has_the_outline_tables_and_command_blocks_of_the_chinese_one(zh_ja):
    zh, ja = zh_ja
    assert ja[0] == zh[0], "heading levels differ"
    assert [f[0] for f in ja[1]] == [f[0] for f in zh[1]], "code block languages differ"
    assert ja[2] == zh[2], "table dimensions differ"
    for k, (a, b) in enumerate(zip(zh[1], ja[1])):
        if a[0] in CODE_LANGS:
            assert commands(a[1]) == commands(b[1]), ("code block %d (%s) differs" % (k, a[0]), a[1][:80])
        elif a[0] == DIAGRAM:
            assert shape(a[1]) == shape(b[1]), ("diagram %d differs in its nodes or edges" % k, a[1][:80])


def test_the_japanese_readme_names_the_files_flags_and_commands_the_chinese_one_names(zh_ja):
    zh, ja = zh_ja
    literals = {s for s in zh[3] if s.isascii() and LITERAL.search(s)}
    assert literals <= ja[3], sorted(literals - ja[3])


# The Hermes plugin scanner rates a recursive delete aimed at the home directory as critical and refuses the plugin, so a README must not show one.
HOME_DELETE = re.compile(r"(?<![A-Za-z0-9])rm\s+(-[^\s]*)?r.*(?:\$HOME|~[/\s*]|~$)|(?<![A-Za-z0-9])rmdir\s+.*(?:\$HOME|~[/\s*]|~$)")


def test_no_readme_shows_a_recursive_delete_aimed_at_the_home_directory():
    for rel in FILES.values():
        for number, line in enumerate(read(rel), 1):
            assert not HOME_DELETE.search(line), (rel, number, line)
