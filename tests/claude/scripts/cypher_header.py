# ```cypher
# CREATE
#   (file:File {name: "cypher_header.py", type: "file", language: "python"}),
#   (v_SCRIPTS:Variable {name: "SCRIPTS", type: "variable"}),
#   (v_CONTRACTS:Variable {name: "CONTRACTS", type: "variable"}),
#   (v_EXTRA:Variable {name: "EXTRA", type: "variable"}),
#   (v_SCOPES:Variable {name: "SCOPES", type: "variable"}),
#   (f_identifier:Function {name: "identifier", type: "function", signature: "identifier(prefix: str, name: str) -> str"}),
#   (f_own_nodes:Function {name: "own_nodes", type: "function", signature: "own_nodes(body)"}),
#   (f_signature:Function {name: "signature", type: "function", signature: "signature(name: str, node) -> str"}),
#   (f_collect:Function {name: "collect", type: "function", signature: "collect(tree: ast.Module) -> tuple[dict, dict]"}),
#   (f_collect_scan:Function {name: "collect.scan", type: "function", signature: "scan(body, parent: str | None) -> None"}),
#   (f_collect_register:Function {name: "collect.register", type: "function", signature: "register(node, parent: str | None, label: str) -> str"}),
#   (f_render:Function {name: "render", type: "function", signature: "render(path: Path, display_name: str) -> str"}),
#   (f_render_resolve:Function {name: "render.resolve", type: "function", signature: "resolve(name: str, scope: str | None) -> str | None"}),
#   (f_split_header:Function {name: "split_header", type: "function", signature: "split_header(text: str) -> tuple[str, str]"}),
#   (f_main:Function {name: "main", type: "function", signature: "main() -> int"}),
#   (file)-[:CONTAINS]->(v_SCRIPTS),
#   (file)-[:CONTAINS]->(v_CONTRACTS),
#   (file)-[:CONTAINS]->(v_EXTRA),
#   (file)-[:CONTAINS]->(v_SCOPES),
#   (file)-[:CONTAINS]->(f_identifier),
#   (file)-[:CONTAINS]->(f_own_nodes),
#   (file)-[:CONTAINS]->(f_signature),
#   (file)-[:CONTAINS]->(f_collect),
#   (f_collect)-[:CONTAINS]->(f_collect_scan),
#   (f_collect)-[:CONTAINS]->(f_collect_register),
#   (file)-[:CONTAINS]->(f_render),
#   (f_render)-[:CONTAINS]->(f_render_resolve),
#   (file)-[:CONTAINS]->(f_split_header),
#   (file)-[:CONTAINS]->(f_main),
#   (f_collect)-[:CALLS]->(f_collect_register),
#   (f_collect)-[:CALLS]->(f_collect_scan),
#   (f_collect_register)-[:CALLS]->(f_collect_scan),
#   (f_collect_scan)-[:CALLS]->(f_collect_register),
#   (f_collect_scan)-[:CALLS]->(f_own_nodes),
#   (f_main)-[:CALLS]->(f_render),
#   (f_main)-[:CALLS]->(f_split_header),
#   (f_main)-[:USES]->(v_EXTRA),
#   (f_main)-[:USES]->(v_SCRIPTS),
#   (f_own_nodes)-[:USES]->(v_SCOPES),
#   (f_render)-[:CALLS]->(f_collect),
#   (f_render)-[:CALLS]->(f_identifier),
#   (f_render)-[:CALLS]->(f_own_nodes),
#   (f_render)-[:CALLS]->(f_render_resolve),
#   (f_render)-[:CALLS]->(f_signature),
#   (file)-[:CALLS]->(f_main);
# ```
"""Generate or verify the Cypher structure header at the top of every Python file under tests/claude/scripts,
and of the Agent Plugins check modules in tests/codex/contracts (EXTRA).

The header is derived from the file's own AST (functions, nested functions, lambdas, module-level variables, calls
between functions defined in the same file, variable reads), so it cannot drift from the code.
Run: python -X utf8 tests/claude/scripts/cypher_header.py [--check]
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re

SCRIPTS = Path(__file__).resolve().parent
CONTRACTS = SCRIPTS.parents[1] / "codex" / "contracts"
EXTRA = [CONTRACTS / name for name in ("agent_plugin.py", "skill_frontmatter.py", "test_agent_plugin.py")]
FENCE_OPEN, FENCE_CLOSE = "# ```cypher", "# ```"
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def identifier(prefix: str, name: str) -> str:
    """Cypher variable name for a node."""
    return prefix + re.sub(r"\W", "_", name)


def own_nodes(body):
    """Walk a statement list (or one expression); nested functions, classes, and lambdas are yielded but not entered."""
    stack = list(body) if isinstance(body, list) else [body]
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def signature(name: str, node) -> str:
    """Compact `name(args) -> returns` text for a function or lambda node."""
    returns = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) else ""
    return f"{name}({ast.unparse(node.args)}){returns}".replace('"', "'")


def collect(tree: ast.Module) -> tuple[dict, dict]:
    """Return (functions, variables): qualified name -> {'node', 'parent', 'label'} and module-level variable names."""
    functions: dict[str, dict] = {}
    variables: dict[str, ast.AST] = {}

    def register(node, parent: str | None, label: str) -> str:
        qualified = f"{parent}.{label}" if parent else label
        functions[qualified] = {"node": node, "parent": parent, "label": label}
        scan(node.body, qualified)
        return qualified

    def scan(body, parent: str | None) -> None:
        for inner in own_nodes(body):
            if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                register(inner, parent, inner.name)
            elif isinstance(inner, ast.Lambda):
                register(inner, parent, f"lambda_{inner.lineno}_{inner.col_offset}")

    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            register(statement, None, statement.name)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    variables[target.id] = statement
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scan([statement], None)
    return functions, variables


def render(path: Path, display_name: str) -> str:
    """The header text (comment lines, trailing newline) for one source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions, variables = collect(tree)
    top_functions = {name for name, info in functions.items() if info["parent"] is None}
    lines = [f'(file:File {{name: "{display_name}", type: "file", language: "python"}})']
    lines += [f'({identifier("v_", name)}:Variable {{name: "{name}", type: "variable"}})' for name in variables]
    for qualified, info in functions.items():
        lines.append(f'({identifier("f_", qualified)}:Function {{name: "{qualified}", type: "function", '
                     f'signature: "{signature(info["label"], info["node"])}"}})')
    lines += [f'(file)-[:CONTAINS]->({identifier("v_", name)})' for name in variables]
    for qualified, info in functions.items():
        owner = "file" if info["parent"] is None else identifier("f_", info["parent"])
        lines.append(f'({owner})-[:CONTAINS]->({identifier("f_", qualified)})')

    def resolve(name: str, scope: str | None) -> str | None:
        """A called name resolves to a function nested in the current scope chain, then to a top-level function."""
        while scope:
            if f"{scope}.{name}" in functions:
                return f"{scope}.{name}"
            scope = functions[scope]["parent"]
        return name if name in top_functions else None

    edges = set()
    for qualified, info in functions.items():
        for inner in own_nodes(info["node"].body):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                target = resolve(inner.func.id, qualified)
                if target and target != qualified:
                    edges.add((identifier("f_", qualified), "CALLS", identifier("f_", target)))
            if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load) and inner.id in variables:
                edges.add((identifier("f_", qualified), "USES", identifier("v_", inner.id)))
    module_level = [s for s in tree.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    decorators = [d for info in functions.values() if info["parent"] is None and hasattr(info["node"], "decorator_list")
                  for d in info["node"].decorator_list]
    for statement in [*module_level, *decorators]:
        for inner in own_nodes([statement]):
            callee = inner.func if isinstance(inner, ast.Call) else None
            while isinstance(callee, ast.Call):  # `@oracle("x")(function)`: the factory is the inner call
                callee = callee.func
            if isinstance(callee, ast.Name) and callee.id in top_functions:
                edges.add(("file", "CALLS", identifier("f_", callee.id)))
    lines += [f"({a})-[:{rel}]->({b})" for a, rel, b in sorted(edges)]
    body = ",\n".join(f"  {line}" for line in lines) + ";"
    return "\n".join([FENCE_OPEN, "# CREATE", *(f"# {row}" for row in body.splitlines()), FENCE_CLOSE]) + "\n"


def split_header(text: str) -> tuple[str, str]:
    """Separate an existing generated header from the rest of the file."""
    if not text.startswith(FENCE_OPEN):
        return "", text
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == FENCE_CLOSE:
            return "".join(lines[: index + 1]), "".join(lines[index + 1:])
    return "", text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only verify; exit 1 when a header is missing or stale")
    options = parser.parse_args()
    stale = []
    for path in [*sorted(SCRIPTS.glob("*.py")), *EXTRA]:
        old, body = split_header(path.read_text(encoding="utf-8"))
        scratch = path.with_suffix(".tmp.py")
        scratch.write_text(body, encoding="utf-8", newline="\n")
        try:
            header = render(scratch, path.name)
        finally:
            scratch.unlink()
        if old != header:
            stale.append(path.name)
            if not options.check:
                path.write_text(header + body, encoding="utf-8", newline="\n")
    print(("stale: " if options.check else "updated: ") + (", ".join(stale) or "none"))
    return 1 if stale and options.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
