"""Símbolos e esqueletos de código: Python via `ast`, C/C++ via tree-sitter (import preguiçoso)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

from .config import ALL_C_CPP_EXTS, CPP_EXTS, LINE_SPLIT_RE

if TYPE_CHECKING:
    from tree_sitter import Language, Node


_CPP_NAME_NODES: Final[frozenset[str]] = frozenset(
    {
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
        "type_identifier",
    }
)
_CPP_CONTAINER_NODES: Final[frozenset[str]] = frozenset(
    {
        "template_declaration",
        "linkage_specification",
        "declaration_list",
        "field_declaration_list",
    }
)


@lru_cache(maxsize=2)
def _ts_language(is_cpp: bool) -> Language:
    # Import preguiçoso: tree-sitter só custa tempo de startup quando `hc map` precisa dele.
    from tree_sitter import Language

    if is_cpp:
        import tree_sitter_cpp as tscpp

        return Language(tscpp.language())
    import tree_sitter_c as tsc

    return Language(tsc.language())


def extract_skeleton(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    if ext == ".py":
        return _extract_py_skeleton(file_path)
    if ext in ALL_C_CPP_EXTS:
        return _extract_cpp_skeleton(file_path, is_cpp=(ext in CPP_EXTS or ext == ".h"))
    return f"# Unsupported file extension: {ext}"


def _extract_py_skeleton(file_path: Path) -> str:
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return f"ParseError in {file_path}: {exc}"

    lines: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append(_format_py_func(node, indent=0))
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            base_str = f"({', '.join(bases)})" if bases else ""
            end_l = node.end_lineno or node.lineno
            lines.append(f"L{node.lineno}-{end_l}: class {node.name}{base_str}:")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(_format_py_func(item, indent=4))
                elif isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    ann = ast.unparse(item.annotation)
                    lines.append(f"    L{item.lineno}: {item.target.id}: {ann}")
    return "\n".join(lines) if lines else "# No top-level classes or functions"


def _format_py_func(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: int) -> str:
    prefix = " " * indent
    async_kw = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    end_l = node.end_lineno or node.lineno
    return f"{prefix}L{node.lineno}-{end_l}: {async_kw}def {node.name}({args}){ret}"


def _extract_cpp_skeleton(file_path: Path, *, is_cpp: bool = True) -> str:
    try:
        source_bytes = file_path.read_bytes()
    except OSError as exc:
        return f"ReadError in {file_path}: {exc}"

    from tree_sitter import Parser

    parser = Parser(_ts_language(is_cpp))
    tree = parser.parse(source_bytes)
    lines: list[str] = []

    def walk_node(node: Node, indent: int = 0) -> None:
        prefix = " " * indent
        start_l = node.start_point[0] + 1
        end_l = node.end_point[0] + 1

        if node.type in ("function_definition", "declaration", "field_declaration"):
            body = node.child_by_field_name("body")
            end_byte = body.start_byte if body is not None else node.end_byte
            sig_bytes = source_bytes[node.start_byte : end_byte].strip()
            sig_text = " ".join(sig_bytes.decode("utf-8", errors="ignore").split())
            if "(" in sig_text or node.type == "function_definition":
                lines.append(f"{prefix}L{start_l}-{end_l}: {sig_text}")
            return

        if node.type == "template_declaration":
            for child in node.children:
                if child.type in (
                    "function_definition",
                    "class_specifier",
                    "struct_specifier",
                    "declaration",
                ):
                    walk_node(child, indent)
            return

        if node.type in ("class_specifier", "struct_specifier", "namespace_definition"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = source_bytes[name_node.start_byte : name_node.end_byte].decode(
                    "utf-8", errors="ignore"
                )
            else:
                name = "<anon>"
            kind = node.type.split("_", maxsplit=1)[0]
            lines.append(f"{prefix}L{start_l}-{end_l}: {kind} {name}:")
            body = node.child_by_field_name("body")
            if body is not None:
                for child in body.children:
                    walk_node(child, indent + 4)
            return

        for child in node.children:
            walk_node(child, indent)

    walk_node(tree.root_node, 0)
    return "\n".join(lines) if lines else "# No top-level C/C++ symbols found"


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str  # qualificado: Classe.metodo (Python) ou ns::Classe.metodo (C++)
    start: int  # primeira linha (inclui decorators)
    end: int
    name_line: int  # linha onde o nome é definido (p/ não contar como "uso")
    sig: str


def _py_symbols(path: Path) -> list[Symbol]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    lines = LINE_SPLIT_RE.split(source)
    out: list[Symbol] = []

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                end = node.end_lineno or node.lineno
                qual = f"{prefix}{node.name}"
                if isinstance(node, ast.ClassDef):
                    bases = ", ".join(ast.unparse(b) for b in node.bases)
                    sig = (
                        f"class {node.name}({bases})" if bases else f"class {node.name}"
                    )
                    out.append(Symbol(qual, start, end, node.lineno, sig))
                    visit(node.body, f"{qual}.")
                else:
                    sig = _format_py_func(node, 0).split(": ", 1)[1]
                    out.append(Symbol(qual, start, end, node.lineno, sig))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Name):
                        text = (
                            lines[node.lineno - 1].strip()
                            if node.lineno <= len(lines)
                            else t.id
                        )
                        out.append(
                            Symbol(
                                f"{prefix}{t.id}",
                                node.lineno,
                                node.end_lineno or node.lineno,
                                node.lineno,
                                text[:100],
                            )
                        )

    visit(tree.body, "")
    return out


def _cpp_symbols(path: Path) -> list[Symbol]:
    ext = path.suffix.lower()
    try:
        source = path.read_bytes()
        from tree_sitter import Parser

        parser = Parser(_ts_language(ext in CPP_EXTS or ext == ".h"))
    except (OSError, ImportError):
        return []
    tree = parser.parse(source)
    out: list[Symbol] = []

    def text(n: Node) -> str:
        return source[n.start_byte : n.end_byte].decode("utf-8", errors="ignore")

    def declarator_name(node: Node | None) -> str | None:
        cur = node
        while cur is not None:
            if cur.type in _CPP_NAME_NODES:
                return text(cur)
            nxt = cur.child_by_field_name("declarator")
            if nxt is None:
                return next(
                    (text(c) for c in cur.children if c.type in _CPP_NAME_NODES), None
                )
            cur = nxt
        return None

    def visit(node: Node, prefix: str) -> None:
        for child in node.children:
            t = child.type
            start = child.start_point[0] + 1
            end = child.end_point[0] + 1
            if t == "function_definition":
                name = declarator_name(child.child_by_field_name("declarator"))
                body = child.child_by_field_name("body")
                end_byte = body.start_byte if body is not None else child.end_byte
                sig = " ".join(
                    source[child.start_byte : end_byte]
                    .decode("utf-8", "ignore")
                    .split()
                )
                if name:
                    out.append(Symbol(f"{prefix}{name}", start, end, start, sig))
            elif t in ("declaration", "field_declaration"):
                decl = child.child_by_field_name("declarator")
                if decl is not None and decl.type == "function_declarator":
                    name = declarator_name(decl)
                    if name:
                        sig = " ".join(text(child).split())
                        out.append(Symbol(f"{prefix}{name}", start, end, start, sig))
            elif t in ("class_specifier", "struct_specifier", "namespace_definition"):
                name_node = child.child_by_field_name("name")
                body = child.child_by_field_name("body")
                if name_node is not None:
                    name = text(name_node)
                    kind = t.split("_", maxsplit=1)[0]
                    out.append(
                        Symbol(f"{prefix}{name}", start, end, start, f"{kind} {name}")
                    )
                    if body is not None:
                        visit(body, f"{prefix}{name}.")
                elif body is not None:
                    visit(body, prefix)
            elif t in _CPP_CONTAINER_NODES:
                visit(child, prefix)

    visit(tree.root_node, "")
    return out


def file_symbols(path: Path) -> list[Symbol]:
    ext = path.suffix.lower()
    if ext == ".py":
        return _py_symbols(path)
    if ext in ALL_C_CPP_EXTS:
        return _cpp_symbols(path)
    return []
