# ```cypher
# CREATE
#   (file:File {name: "test_agent_plugin.py", type: "file", language: "python"}),
#   (v_HERE:Variable {name: "HERE", type: "variable"}),
#   (v_REPO:Variable {name: "REPO", type: "variable"}),
#   (v_PACKAGE:Variable {name: "PACKAGE", type: "variable"}),
#   (v_MANIFEST:Variable {name: "MANIFEST", type: "variable"}),
#   (v_VERSION:Variable {name: "VERSION", type: "variable"}),
#   (v_DISCOVERY:Variable {name: "DISCOVERY", type: "variable"}),
#   (v_SKILLS:Variable {name: "SKILLS", type: "variable"}),
#   (v_ROOT:Variable {name: "ROOT", type: "variable"}),
#   (v_CONTAINMENT:Variable {name: "CONTAINMENT", type: "variable"}),
#   (v_MCP:Variable {name: "MCP", type: "variable"}),
#   (v_CLONE:Variable {name: "CLONE", type: "variable"}),
#   (v_HOST_MANIFEST:Variable {name: "HOST_MANIFEST", type: "variable"}),
#   (v_INSTALL_YAML:Variable {name: "INSTALL_YAML", type: "variable"}),
#   (v_RECON:Variable {name: "RECON", type: "variable"}),
#   (v_RECON_DESCRIPTION:Variable {name: "RECON_DESCRIPTION", type: "variable"}),
#   (v_SHORT:Variable {name: "SHORT", type: "variable"}),
#   (v_ROOT_DESCRIPTION:Variable {name: "ROOT_DESCRIPTION", type: "variable"}),
#   (v_ROOT_COMPATIBILITY:Variable {name: "ROOT_COMPATIBILITY", type: "variable"}),
#   (v_ROOT_PAD:Variable {name: "ROOT_PAD", type: "variable"}),
#   (v_MUTATIONS:Variable {name: "MUTATIONS", type: "variable"}),
#   (f_edit:Function {name: "edit", type: "function", signature: "edit(relative: str, old: str, new: str)"}),
#   (f_edit_apply:Function {name: "edit.apply", type: "function", signature: "apply(root: Path) -> None"}),
#   (f_manifest:Function {name: "manifest", type: "function", signature: "manifest(change)"}),
#   (f_manifest_apply:Function {name: "manifest.apply", type: "function", signature: "apply(root: Path) -> None"}),
#   (f_write:Function {name: "write", type: "function", signature: "write(relative: str, content: str)"}),
#   (f_write_apply:Function {name: "write.apply", type: "function", signature: "apply(root: Path) -> None"}),
#   (f_add_seventh_skill:Function {name: "add_seventh_skill", type: "function", signature: "add_seventh_skill(root: Path) -> None"}),
#   (f_long_named_adapter:Function {name: "long_named_adapter", type: "function", signature: "long_named_adapter(root: Path) -> None"}),
#   (f_add_symlink:Function {name: "add_symlink", type: "function", signature: "add_symlink(root: Path) -> None"}),
#   (f_rename_skill_md:Function {name: "rename_skill_md", type: "function", signature: "rename_skill_md(root: Path) -> None"}),
#   (f_link_directory:Function {name: "link_directory", type: "function", signature: "link_directory(target: Path, link: Path) -> None"}),
#   (f_add_empty_outside_link:Function {name: "add_empty_outside_link", type: "function", signature: "add_empty_outside_link(root: Path) -> None"}),
#   (f_add_directory_link:Function {name: "add_directory_link", type: "function", signature: "add_directory_link(root: Path) -> None"}),
#   (f_lambda_168_5:Function {name: "lambda_168_5", type: "function", signature: "lambda_168_5(root)"}),
#   (f_lambda_141_46:Function {name: "lambda_141_46", type: "function", signature: "lambda_141_46(data)"}),
#   (f_lambda_140_55:Function {name: "lambda_140_55", type: "function", signature: "lambda_140_55(data)"}),
#   (f_lambda_135_5:Function {name: "lambda_135_5", type: "function", signature: "lambda_135_5(root)"}),
#   (f_lambda_131_14:Function {name: "lambda_131_14", type: "function", signature: "lambda_131_14(data)"}),
#   (f_lambda_129_50:Function {name: "lambda_129_50", type: "function", signature: "lambda_129_50(data)"}),
#   (f_lambda_128_45:Function {name: "lambda_128_45", type: "function", signature: "lambda_128_45(data)"}),
#   (f_lambda_127_58:Function {name: "lambda_127_58", type: "function", signature: "lambda_127_58(data)"}),
#   (f_lambda_126_42:Function {name: "lambda_126_42", type: "function", signature: "lambda_126_42(data)"}),
#   (f_lambda_125_39:Function {name: "lambda_125_39", type: "function", signature: "lambda_125_39(data)"}),
#   (f_lambda_123_43:Function {name: "lambda_123_43", type: "function", signature: "lambda_123_43(data, name=name)"}),
#   (f_lambda_122_45:Function {name: "lambda_122_45", type: "function", signature: "lambda_122_45(data)"}),
#   (f_lambda_121_25:Function {name: "lambda_121_25", type: "function", signature: "lambda_121_25(root)"}),
#   (f_rows:Function {name: "rows", type: "function", signature: "rows(root: Path) -> dict"}),
#   (f_install_rows:Function {name: "install_rows", type: "function", signature: "install_rows(root: Path) -> dict"}),
#   (f_pick:Function {name: "pick", type: "function", signature: "pick(result: dict, fragment: str) -> list[dict]"}),
#   (f_remove_tree:Function {name: "remove_tree", type: "function", signature: "remove_tree(path: Path) -> None"}),
#   (f_remove_tree_make_writable:Function {name: "remove_tree.make_writable", type: "function", signature: "make_writable(function, target, *_)"}),
#   (file)-[:CONTAINS]->(v_HERE),
#   (file)-[:CONTAINS]->(v_REPO),
#   (file)-[:CONTAINS]->(v_PACKAGE),
#   (file)-[:CONTAINS]->(v_MANIFEST),
#   (file)-[:CONTAINS]->(v_VERSION),
#   (file)-[:CONTAINS]->(v_DISCOVERY),
#   (file)-[:CONTAINS]->(v_SKILLS),
#   (file)-[:CONTAINS]->(v_ROOT),
#   (file)-[:CONTAINS]->(v_CONTAINMENT),
#   (file)-[:CONTAINS]->(v_MCP),
#   (file)-[:CONTAINS]->(v_CLONE),
#   (file)-[:CONTAINS]->(v_HOST_MANIFEST),
#   (file)-[:CONTAINS]->(v_INSTALL_YAML),
#   (file)-[:CONTAINS]->(v_RECON),
#   (file)-[:CONTAINS]->(v_RECON_DESCRIPTION),
#   (file)-[:CONTAINS]->(v_SHORT),
#   (file)-[:CONTAINS]->(v_ROOT_DESCRIPTION),
#   (file)-[:CONTAINS]->(v_ROOT_COMPATIBILITY),
#   (file)-[:CONTAINS]->(v_ROOT_PAD),
#   (file)-[:CONTAINS]->(v_MUTATIONS),
#   (file)-[:CONTAINS]->(f_edit),
#   (f_edit)-[:CONTAINS]->(f_edit_apply),
#   (file)-[:CONTAINS]->(f_manifest),
#   (f_manifest)-[:CONTAINS]->(f_manifest_apply),
#   (file)-[:CONTAINS]->(f_write),
#   (f_write)-[:CONTAINS]->(f_write_apply),
#   (file)-[:CONTAINS]->(f_add_seventh_skill),
#   (file)-[:CONTAINS]->(f_long_named_adapter),
#   (file)-[:CONTAINS]->(f_add_symlink),
#   (file)-[:CONTAINS]->(f_rename_skill_md),
#   (file)-[:CONTAINS]->(f_link_directory),
#   (file)-[:CONTAINS]->(f_add_empty_outside_link),
#   (file)-[:CONTAINS]->(f_add_directory_link),
#   (file)-[:CONTAINS]->(f_lambda_168_5),
#   (file)-[:CONTAINS]->(f_lambda_141_46),
#   (file)-[:CONTAINS]->(f_lambda_140_55),
#   (file)-[:CONTAINS]->(f_lambda_135_5),
#   (file)-[:CONTAINS]->(f_lambda_131_14),
#   (file)-[:CONTAINS]->(f_lambda_129_50),
#   (file)-[:CONTAINS]->(f_lambda_128_45),
#   (file)-[:CONTAINS]->(f_lambda_127_58),
#   (file)-[:CONTAINS]->(f_lambda_126_42),
#   (file)-[:CONTAINS]->(f_lambda_125_39),
#   (file)-[:CONTAINS]->(f_lambda_123_43),
#   (file)-[:CONTAINS]->(f_lambda_122_45),
#   (file)-[:CONTAINS]->(f_lambda_121_25),
#   (file)-[:CONTAINS]->(f_rows),
#   (file)-[:CONTAINS]->(f_install_rows),
#   (file)-[:CONTAINS]->(f_pick),
#   (file)-[:CONTAINS]->(f_remove_tree),
#   (f_remove_tree)-[:CONTAINS]->(f_remove_tree_make_writable),
#   (f_add_directory_link)-[:CALLS]->(f_link_directory),
#   (f_add_empty_outside_link)-[:CALLS]->(f_link_directory),
#   (f_add_seventh_skill)-[:CALLS]->(f_edit),
#   (f_lambda_168_5)-[:CALLS]->(f_edit),
#   (f_lambda_168_5)-[:USES]->(v_ROOT_DESCRIPTION),
#   (f_long_named_adapter)-[:CALLS]->(f_edit),
#   (file)-[:CALLS]->(f_edit),
#   (file)-[:CALLS]->(f_manifest),
#   (file)-[:CALLS]->(f_write);
# ```
"""Mutation tests for the Agent Plugins and git-clone layout checks (standard library only).

Each case copies the package into a temporary directory, applies one defect, and asserts that the named check row
turns red while the unmodified copy stays green. A setup error fails the case; only a missing symlink privilege
skips it (the skip count is part of unittest's last line). Run: python -X utf8 tests/codex/contracts/test_agent_plugin.py
"""

import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import agent_plugin  # noqa: E402
import install_layout  # noqa: E402
import skill_frontmatter  # noqa: E402

REPO = HERE.parents[2]
PACKAGE = ["plugin.json", "SKILL.md", "LICENSE", "references", "skills", "scripts"]

MANIFEST = "plugin.json is a valid"
VERSION = "manifest version matches"
DISCOVERY = "skills/ discovery"
SKILLS = "every discovered skill meets"
ROOT = "root SKILL.md"
CONTAINMENT = "package paths stay inside"
MCP = "mcp.json is absent or valid"
CLONE = "git-clone checkout, the Codex"
HOST_MANIFEST = "git-clone checkout has no"
INSTALL_YAML = "every installed SKILL.md is strict YAML"

RECON = "skills/git-recon/SKILL.md"
RECON_DESCRIPTION = 'description: "查看仓库状态（只读）；/git-recon [--remote] [--help]."'
SHORT = 'short-description: "查看仓库状态；$git-recon [--remote] [--help]."'
ROOT_DESCRIPTION = 'description: "Automatically use for'
ROOT_COMPATIBILITY = ("Requires Git 2.30+ or harness-native workspace isolation; "
                      "intended for Agent Skills-compatible coding agents.")
# Characters that bring the root description to exactly 1024, computed so that rewording SKILL.md keeps the
# boundary cases on the boundary.
ROOT_PAD = 1024 - len(skill_frontmatter.parse((REPO / "SKILL.md").read_text(encoding="utf-8"))[0]["description"])


def edit(relative: str, old: str, new: str):
    def apply(root: Path) -> None:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        assert old in text, (relative, old)
        path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
    return apply


def manifest(change):
    def apply(root: Path) -> None:
        data = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
        change(data)
        (root / "plugin.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return apply


def write(relative: str, content: str):
    def apply(root: Path) -> None:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(content, encoding="utf-8")
    return apply


def add_seventh_skill(root: Path) -> None:
    shutil.copytree(root / "skills" / "git-recon", root / "skills" / "magos")
    edit("skills/magos/SKILL.md", "name: git-recon", "name: magos")(root)


def long_named_adapter(root: Path) -> None:
    """A skill whose name equals its directory but has 65 characters: only the length rule can reject it."""
    long_name = "git-" + "x" * 61
    (root / "skills" / "git-recon").rename(root / "skills" / long_name)
    edit(f"skills/{long_name}/SKILL.md", "name: git-recon", f"name: {long_name}")(root)


def add_symlink(root: Path) -> None:
    try:
        os.symlink(root / "SKILL.md", root / "skills" / "git-recon" / "linked.md")
    except OSError as error:
        if getattr(error, "winerror", None) == 1314 or error.errno == errno.EPERM:
            raise unittest.SkipTest(f"creating a symbolic link needs a privilege here ({error})") from None
        raise


def rename_skill_md(root: Path) -> None:
    os.rename(root / "skills" / "git-recon" / "SKILL.md", root / "skills" / "git-recon" / "skill.md")


def link_directory(target: Path, link: Path) -> None:
    """A junction on Windows (no privilege needed), a directory symlink elsewhere."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def add_empty_outside_link(root: Path) -> None:
    """A link to an empty directory outside the root: it holds no files, so a file listing never shows it."""
    outside = root.parent / "outside-empty"
    outside.mkdir()
    link_directory(outside, root / "skills" / "git-recon" / "ext")


def add_directory_link(root: Path) -> None:
    link_directory(root / "references", root / "skills" / "git-recon" / "linked")


MUTATIONS = [
    ("manifest missing", lambda root: (root / "plugin.json").unlink(), [MANIFEST, VERSION]),
    ("manifest name not lowercase", manifest(lambda data: data.update(name="MAGOS")), [MANIFEST]),
    *[(f"manifest name {name!r}", manifest(lambda data, name=name: data.update(name=name)), [MANIFEST])
      for name in ("a--b", "-a", "a.", "a..b", "a b", "a" * 65, "")],
    ("manifest without name", manifest(lambda data: data.pop("name")), [MANIFEST]),
    ("manifest without $schema", manifest(lambda data: data.pop("$schema")), [MANIFEST]),
    ("manifest field outside the closed schema", manifest(lambda data: data.update(commands="./commands")), [MANIFEST]),
    ("manifest author is a string", manifest(lambda data: data.update(author="someone")), [MANIFEST]),
    ("manifest keyword is not a string", manifest(lambda data: data.update(keywords=["git", 1])), [MANIFEST]),
    ("manifest $schema targets another version",
     manifest(lambda data: data.update({"$schema": "https://agent-plugins.org/schemas/1.1.0/plugin.schema.json"})),
     [MANIFEST]),
    ("manifest duplicate key", edit("plugin.json", '"name": "magos",', '"name": "magos",\n  "name": "magos",'), [MANIFEST]),
    ("manifest has a byte-order mark",
     lambda root: (root / "plugin.json").write_bytes(b"\xef\xbb\xbf" + (root / "plugin.json").read_bytes()), [MANIFEST]),
    ("manifest holds NaN, which is not JSON",
     edit("plugin.json", '"license": "Apache-2.0",',
          '"license": "Apache-2.0",\n  "extensions": {"com.example.client": {"x": NaN}},'),
     [MANIFEST]),
    ("manifest version drifts from SKILL.md", manifest(lambda data: data.update(version="3.5.0")), [VERSION]),
    ("manifest version is a number", manifest(lambda data: data.update(version=3)), [MANIFEST, VERSION]),
    ("commands.md states another version",
     edit("references/commands.md", "`multi-agent-git-orchestrator` v3.4.", "`multi-agent-git-orchestrator` v3.3."),
     [VERSION]),
    ("adapter flow-style list", edit(RECON, SHORT, SHORT + "\n  tags: [git, worktree]"), [SKILLS, CLONE]),
    ("adapter nested metadata.hermes", edit(RECON, SHORT, SHORT + '\n  hermes:\n    tags: "git"'), [SKILLS, CLONE]),
    ("adapter metadata.hermes as a string", edit(RECON, SHORT, SHORT + '\n  hermes: "git, worktree"'), [SKILLS]),
    ("adapter plain metadata value", edit(RECON, SHORT, "short-description: plain text"), [SKILLS]),
    ("adapter top-level field outside Agent Skills", edit(RECON, "license: Apache-2.0", 'license: Apache-2.0\ntags: "git"'),
     [SKILLS]),
    ("adapter duplicate top-level key", edit(RECON, "license: Apache-2.0", "license: Apache-2.0\nlicense: Apache-2.0"),
     [SKILLS, CLONE]),
    ("adapter description holds '---'", edit(RECON, RECON_DESCRIPTION, 'description: "read --- only"'), [SKILLS, CLONE]),
    ("adapter name differs from its directory", edit(RECON, "name: git-recon", "name: git-recon-x"), [SKILLS, CLONE]),
    ("adapter name has 65 characters", long_named_adapter, [SKILLS]),
    ("adapter description has an unquoted ': '", edit(RECON, RECON_DESCRIPTION, "description: Recon: read only"),
     [SKILLS, CLONE]),
    ("adapter description is blank", edit(RECON, RECON_DESCRIPTION, 'description: " "'), [SKILLS]),
    ("adapter description has 1025 characters", edit(RECON, RECON_DESCRIPTION, 'description: "' + "x" * 1025 + '"'),
     [SKILLS]),
    ("adapter line ends with a Unicode space", edit(RECON, SHORT, SHORT + chr(0x3000)), [SKILLS, CLONE]),
    ("adapter file is named skill.md", rename_skill_md, [DISCOVERY]),
    ("adapter reference is missing", edit(RECON, "`../../references/reconnaissance.md`", "`../../references/missing.md`"),
     [CONTAINMENT]),
    ("adapter reference escapes the root", edit(RECON, "`../../references/reconnaissance.md`", "`../../../outside.md`"),
     [CONTAINMENT]),
    ("root description has an unquoted ': '",
     lambda root: edit("SKILL.md", ROOT_DESCRIPTION, "description: Automatically use for")(root)
     or edit("SKILL.md", 'single-branch Git questions unless topology, coordination, or shared-history safety matters."',
             "single-branch Git questions unless topology, coordination, or shared-history safety matters.")(root),
     [ROOT, CLONE]),
    ("root description over 1024 characters", edit("SKILL.md", ROOT_DESCRIPTION, ROOT_DESCRIPTION + "x" * (ROOT_PAD + 10)),
     [ROOT]),
    ("root description has 1025 characters", edit("SKILL.md", ROOT_DESCRIPTION, ROOT_DESCRIPTION + "x" * (ROOT_PAD + 1)),
     [ROOT]),
    ("root compatibility has 501 characters", edit("SKILL.md", ROOT_COMPATIBILITY, "x" * 501), [ROOT]),
    ("a seventh skill under skills/", add_seventh_skill, [DISCOVERY, CLONE]),
    *[(f"a host plugin manifest in {directory}/", write(f"{directory}/plugin.json", '{"name": "magos"}\n'), [HOST_MANIFEST])
      for directory in (".claude-plugin", ".codex-plugin", ".cursor-plugin")],
    ("mcp.json without $schema", write("mcp.json", '{"mcpServers": {}}\n'), [MCP]),
    ("a symbolic link in the package", add_symlink, [CONTAINMENT]),
    ("a directory junction or link in the package", add_directory_link, [CONTAINMENT]),
    ("an empty directory link pointing outside the root", add_empty_outside_link, [CONTAINMENT]),
]


def rows(root: Path) -> dict:
    return {row["file"]: row for row in agent_plugin.check(root) + install_layout.check_checkout(root)}


def install_rows(root: Path) -> dict:
    """The installed-package rows of install_layout, run on the copy as if it were a Codex install."""
    return {row["file"]: row for row in
            install_layout.check_package("codex", root, root.parent, install_layout.codex_discovery)}


def pick(result: dict, fragment: str) -> list[dict]:
    matching = [row for label, row in result.items() if fragment in label]
    assert matching, f"no row matches {fragment!r}"
    return matching


def remove_tree(path: Path) -> None:
    """rmtree that also removes read-only files: git writes its loose objects read-only, which Windows refuses to unlink."""
    def make_writable(function, target, *_):
        os.chmod(target, stat.S_IWRITE)
        function(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable)
    else:
        shutil.rmtree(path, onerror=make_writable)


class PackageCopy(unittest.TestCase):
    def copy(self) -> Path:
        temporary = Path(tempfile.mkdtemp(prefix="magos-plugin-"))
        self.addCleanup(remove_tree, temporary)
        root = temporary / "MAGOS"
        root.mkdir()
        for name in PACKAGE:
            source = REPO / name
            (shutil.copytree if source.is_dir() else shutil.copy2)(source, root / name)
        return root


class AgentPluginChecks(PackageCopy):
    def test_unmodified_package_passes(self):
        root = self.copy()
        failed = {label: row["missing"] for label, row in {**rows(root), **install_rows(root)}.items()
                  if not row["passed"]}
        self.assertEqual(failed, {})

    def test_each_mutation_turns_its_row_red(self):
        for title, mutate, expected in MUTATIONS:
            with self.subTest(title):
                root = self.copy()
                mutate(root)
                result = rows(root)
                for fragment in expected:
                    self.assertFalse(all(row["passed"] for row in pick(result, fragment)),
                                     f"{title}: {fragment!r} stayed green")

    def test_limits_are_inclusive(self):
        root = self.copy()
        edit(RECON, RECON_DESCRIPTION, 'description: "' + "x" * 1024 + '"')(root)
        edit("SKILL.md", ROOT_DESCRIPTION, ROOT_DESCRIPTION + "x" * ROOT_PAD)(root)
        edit("SKILL.md", ROOT_COMPATIBILITY, "x" * 500)(root)
        result = rows(root)
        for fragment in (SKILLS, ROOT):
            self.assertTrue(all(row["passed"] for row in pick(result, fragment)), pick(result, fragment))

    def test_an_unreadable_file_is_a_red_row_not_a_crash(self):
        root = self.copy()
        (root / "references" / "commands.md").write_bytes("版本".encode("utf-16"))
        result = rows(root)
        self.assertFalse(all(row["passed"] for row in pick(result, VERSION)))
        self.assertTrue(any("could not run" in problem for row in pick(result, VERSION) for problem in row["missing"]))

    def test_nested_repositories_are_not_package_files_outside_git(self):
        """A worktree or clone below the package (e.g. .claude/worktrees/<name>) is not walked, as git would not."""
        root = self.copy()
        nested = root / ".claude" / "worktrees" / "lane"
        shutil.copytree(root / "skills", nested / "skills")
        write(".claude/worktrees/lane/.git", "gitdir: elsewhere\n")(root)
        paths = {relative for _, relative in agent_plugin.tracked_files(root)}
        self.assertFalse(any(path.startswith(".claude/worktrees/lane/") for path in paths), sorted(paths)[:5])
        self.assertTrue(all(row["passed"] for row in pick(rows(root), CLONE)))

    def test_a_flow_style_adapter_turns_the_installed_yaml_row_red(self):
        root = self.copy()
        edit(RECON, SHORT, SHORT + "\n  tags: [git, worktree]")(root)
        self.assertFalse(all(row["passed"] for row in pick(install_rows(root), INSTALL_YAML)))


class GitCheckout(PackageCopy):
    """In a git work tree the checks read the index and the untracked, non-ignored files, once each."""

    def git(self, root: Path, *arguments: str, text: str | None = None) -> str:
        """Run git on bytes: text-mode stdin would turn the newlines of --index-info input into CRLF on Windows."""
        completed = subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True,
                                   input=None if text is None else text.encode("utf-8"))
        return completed.stdout.decode("utf-8")

    def staged_copy(self) -> Path:
        root = self.copy()
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        self.git(root, "add", "-A")
        return root

    def stage_link_entry(self, root: Path, relative: str) -> None:
        """Index entry with mode 120000 while a plain file sits on disk: what a clone looks like with core.symlinks=false."""
        blob = self.git(root, "hash-object", "-w", "--stdin", text="SKILL.md").strip()
        write(relative, "SKILL.md")(root)
        self.git(root, "update-index", "--add", "--cacheinfo", f"120000,{blob},{relative}")

    def test_untracked_files_are_checked_before_git_add(self):
        root = self.staged_copy()
        write(".claude-plugin/plugin.json", '{"name": "magos"}\n')(root)
        add_seventh_skill(root)
        result = rows(root)
        for fragment in (HOST_MANIFEST, CLONE, DISCOVERY):
            self.assertFalse(all(row["passed"] for row in pick(result, fragment)), f"{fragment!r} stayed green")

    def test_ignored_files_are_not_package_files(self):
        """Only git mode honors .gitignore (the directory walk would list the file), so this pins git mode."""
        root = self.staged_copy()
        write(".gitignore", ".claude-plugin/\n")(root)
        write(".claude-plugin/plugin.json", '{"name": "magos"}\n')(root)
        paths = {relative for _, relative in agent_plugin.tracked_files(root)}
        self.assertNotIn(".claude-plugin/plugin.json", paths)
        self.assertTrue(all(row["passed"] for row in pick(rows(root), HOST_MANIFEST)))

    def test_links_inside_ignored_directories_are_not_package_links(self):
        """An ignored .venv holding a link (POSIX venvs have lib64 -> lib) is not part of the package."""
        root = self.staged_copy()
        write(".gitignore", ".venv/\n")(root)
        (root / ".venv").mkdir()
        link_directory(root / "references", root / ".venv" / "lib64")
        self.assertNotIn(".venv/lib64", {relative for _, relative in agent_plugin.tracked_files(root)})
        self.assertTrue(all(row["passed"] for row in pick(rows(root), CONTAINMENT)))

    def test_an_index_only_link_entry_is_flagged(self):
        root = self.staged_copy()
        self.stage_link_entry(root, "skills/git-recon/linked.md")
        self.assertFalse((root / "skills" / "git-recon" / "linked.md").is_symlink())
        self.assertFalse(all(row["passed"] for row in pick(rows(root), CONTAINMENT)))

    def test_an_untracked_empty_directory_link_is_found(self):
        root = self.staged_copy()
        add_empty_outside_link(root)
        self.assertFalse(all(row["passed"] for row in pick(rows(root), CONTAINMENT)))

    def test_deleted_tracked_files_are_dropped_and_the_row_goes_red(self):
        root = self.staged_copy()
        shutil.rmtree(root / "skills" / "git-converge")
        paths = {relative for _, relative in agent_plugin.tracked_files(root)}
        self.assertNotIn("skills/git-converge/SKILL.md", paths)
        self.assertIn("skills/git-recon/SKILL.md", paths)
        self.assertFalse(all(row["passed"] for row in pick(rows(root), CLONE)))

    def test_an_unmerged_path_counts_once(self):
        root = self.staged_copy()
        relative = RECON
        original = (root / relative).read_text(encoding="utf-8")
        shas = [self.git(root, "hash-object", "-w", "--stdin", text=original + f"\n<!-- {side} -->\n").strip()
                for side in ("base", "ours", "theirs")]
        self.git(root, "rm", "--cached", "-q", "--", relative)
        self.git(root, "update-index", "--index-info",
                 text="".join(f"100644 {sha} {stage}\t{relative}\n" for stage, sha in enumerate(shas, start=1)))
        stages = [line.split()[2] for line in self.git(root, "ls-files", "-s", "--", relative).splitlines()]
        self.assertEqual(stages, ["1", "2", "3"], "the setup must produce an unmerged index entry")
        listed = [path for _, path in agent_plugin.tracked_files(root)]
        self.assertEqual(listed.count(relative), 1)
        self.assertTrue(all(row["passed"] for row in pick(rows(root), CLONE)))


class StrictFrontmatter(unittest.TestCase):
    """The reader must reject what loaders read differently, and accept the escapes it advertises."""

    @staticmethod
    def page(line: str) -> str:
        return f"---\nname: x\n{line}\n---\nbody\n"

    def test_escaped_backslashes_are_accepted(self):
        backslash = chr(92)
        for raw, expected in [(f'"C:{backslash * 2}new and C:{backslash * 2}Users"', f"C:{backslash}new and C:{backslash}Users"),
                              (f'"only {backslash * 2} here"', f"only {backslash} here"),
                              (f'"say {backslash}"hi{backslash}" now"', 'say "hi" now')]:
            with self.subTest(raw):
                fields, _ = skill_frontmatter.parse(self.page(f"description: {raw}"))
                self.assertEqual(fields["description"], expected)

    def test_other_escapes_and_trailing_text_are_rejected(self):
        backslash = chr(92)
        for raw in [f'"tab{backslash}there"', f'"a{backslash}u0041b"', '"closed" # comment', '"unclosed']:
            with self.subTest(raw), self.assertRaises(skill_frontmatter.FrontmatterError):
                skill_frontmatter.parse(self.page(f"description: {raw}"))

    def test_control_and_line_break_characters_are_rejected(self):
        for label, char in [("lone CR", "\r"), ("NEL", "\x85"), ("DEL", "\x7f"), ("C1 control", "\x9b"),
                            ("U+FFFE", chr(0xFFFE)), ("line separator", chr(0x2028)), ("vertical tab", "\x0b")]:
            for quoted in (f'"a{char}b"', f"plain{char}value"):
                with self.subTest(label=label, value=quoted), self.assertRaises(skill_frontmatter.FrontmatterError):
                    skill_frontmatter.parse(self.page(f"description: {quoted}"))

    def test_the_error_names_the_line(self):
        with self.assertRaisesRegex(skill_frontmatter.FrontmatterError, r"line 3: character U\+007F"):
            skill_frontmatter.parse(self.page('description: "a\x7fb"'))

    def test_only_the_ascii_space_is_whitespace(self):
        nbsp, ideographic = chr(0xA0), chr(0x3000)
        for label, text in [("U+3000 after a closing quote", self.page(f'description: "x"{ideographic}')),
                            ("NBSP before a key", self.page(f"{nbsp}description: x")),
                            ("NBSP-only line", self.page(nbsp))]:
            with self.subTest(label), self.assertRaises(skill_frontmatter.FrontmatterError):
                skill_frontmatter.parse(text)
        fields, _ = skill_frontmatter.parse(self.page(f"description: x{nbsp}"))
        self.assertEqual(fields["description"], f"x{nbsp}")

    def test_values_and_keys_that_yaml_1_1_reads_as_non_strings_are_rejected(self):
        rejected = ["description: +.inf", "description: -.INF", "description: .nan", "description: on", "description: Null",
                    "description: 0x1f", "description: 1:20", "description: 2026-10-03", "description: ~",
                    'metadata:\n  on: "x"', 'metadata:\n  yes: "x"', 'metadata:\n  null: "x"', 'metadata:\n  1: "x"',
                    'metadata:\n  1_5: "x"', 'metadata:\n  -x: "x"']
        for line in rejected:
            with self.subTest(line), self.assertRaises(skill_frontmatter.FrontmatterError):
                skill_frontmatter.parse(self.page(line))

    def test_the_reader_agrees_with_pyyaml_on_what_it_accepts(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed, so there is nothing to compare with")
        accepted = ['description: "a b"', "description: plain text", "description: 'it''s'",
                    'license: Apache-2.0\nmetadata:\n  version: "3.4"\n  short-description: "x; $y [z]"',
                    'description: "查看仓库状态（只读）；/git-recon [--remote] [--help]."',
                    f"description: x{chr(0xA0)}"]
        for line in accepted:
            with self.subTest(line):
                text = self.page(line)
                fields, _ = skill_frontmatter.parse(text)
                self.assertEqual(fields, yaml.safe_load(skill_frontmatter.split(text)))
                self.assertIsNone(skill_frontmatter.cross_check(text, fields))

    def test_cross_check_reports_a_disagreement(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML is not installed")
        text = self.page("description: x")
        self.assertIsNotNone(skill_frontmatter.cross_check(text, {"name": "x", "description": "something else"}))
        self.assertIsNotNone(skill_frontmatter.cross_check("---\nname: [broken\n---\n", {}))

    def test_a_closing_fence_at_the_end_of_the_file_is_accepted(self):
        fields, _ = skill_frontmatter.parse('---\nname: x\ndescription: "y"\n---')
        self.assertEqual(fields, {"name": "x", "description": "y"})

    def test_chinese_text_is_accepted(self):
        fields, _ = skill_frontmatter.parse(self.page('description: "查看仓库状态（只读）；/git-recon [--remote] [--help]."'))
        self.assertTrue(fields["description"].startswith("查看仓库状态"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
