"""Navegação compacta no código: `hc map`, `hc find`, `hc show` (poucos tokens)."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

from .config import LINE_SPLIT_RE
from .gitutil import list_source_files
from .symbols import Symbol, file_symbols

NAME_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[.:]+")
RANGE_RE: Final[re.Pattern[str]] = re.compile(r"^L?(\d+)(?:-L?(\d+))?$")
FIND_MAX_USES: Final[int] = 25
SHOW_MAX_LINES: Final[int] = 250
SHOW_MAX_CANDIDATES: Final[int] = 3


def _name_parts(name: str) -> list[str]:
    return [p for p in NAME_SPLIT_RE.split(name) if p]


def _matches(sym: Symbol, query_parts: list[str]) -> bool:
    """`bar` casa Foo.bar e ns::Foo.bar; `Foo.bar` só casa com esse sufixo."""
    parts = _name_parts(sym.name)
    return bool(query_parts) and parts[-len(query_parts) :] == query_parts


def cmd_find(root: Path, args: list[str]) -> int:
    """Definições (AST) + usos (busca por palavra) de um símbolo, em poucas linhas."""
    if not args:
        sys.stderr.write(
            "usage: hc find <symbol>   (e.g. run_stage, Outcome, Class.method)\n"
        )
        return 2
    query = args[0]
    qparts = _name_parts(query)
    if not qparts:
        sys.stderr.write(f"hc: invalid symbol: {query}\n")
        return 2
    word = re.compile(rf"(?<!\w){re.escape(qparts[-1])}(?!\w)")
    defs: list[str] = []
    uses: list[str] = []
    n_uses = 0
    for p in sorted(list_source_files(root)):
        rel = _rel(p, root)
        def_lines: set[int] = set()
        for s in file_symbols(p):
            if _matches(s, qparts):
                defs.append(f"def  {rel}:L{s.start}-{s.end}  {s.sig}")
                def_lines.add(s.name_line)
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(LINE_SPLIT_RE.split(content), 1):
            if i in def_lines or not word.search(line):
                continue
            n_uses += 1
            if n_uses <= FIND_MAX_USES:
                uses.append(f"use  {rel}:L{i}  {line.strip()[:110]}")
    if not defs and not uses:
        sys.stdout.write(f"no match for '{query}'\n")
        return 1
    out = [*defs, *uses]
    if n_uses > FIND_MAX_USES:
        out.append(
            f"... [{n_uses - FIND_MAX_USES} more uses omitted; narrow with Class.method or use hc show]"
        )
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def _parse_show_target(cwd: Path, raw: str) -> tuple[Path | None, str]:
    """`arquivo`, `arquivo:selector` (aceita `C:\\x\\f.py:sym` no Windows) ou só `simbolo`."""
    whole = cwd / raw
    if whole.is_file():
        return whole.resolve(), ""
    if ":" in raw:
        left, right = raw.rsplit(":", 1)
        lp = cwd / left
        if lp.is_file():
            return lp.resolve(), right
    return None, raw


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _emit_blocks(root: Path, blocks: list[tuple[Path, int, int]]) -> int:
    budget = SHOW_MAX_LINES
    out: list[str] = []
    for path, a, b in blocks:
        try:
            lines = LINE_SPLIT_RE.split(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            continue
        a = max(1, a)
        b = min(b, len(lines))
        if a > b:
            out.append(f"# {_rel(path, root)}: range outside file ({len(lines)} lines)")
            continue
        take = min(b - a + 1, max(budget, 0))
        out.append(f"# {_rel(path, root)}:L{a}-{b}")
        width = len(str(b))
        out.extend(f"{n:>{width}}: {lines[n - 1]}" for n in range(a, a + take))
        budget -= take
        if take < b - a + 1:
            rest_from = a + take
            out.append(
                f"... [{b - a + 1 - take} lines omitted; hc show {_rel(path, root)}:L{rest_from}-{b}]"
            )
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def cmd_show(root: Path, cwd: Path, args: list[str]) -> int:
    """Imprime só o corpo de um símbolo (ou faixa de linhas), com números de linha."""
    if not args:
        sys.stderr.write(
            "usage: hc show <file>:<symbol> | <file>:L<a>-<b> | <symbol>\n"
            "       hc show <file>   (lists its symbols)\n"
        )
        return 2
    path, sel = _parse_show_target(cwd, args[0])

    if path is None:  # só o símbolo: procura no projeto inteiro
        qparts = _name_parts(sel)
        hits = [
            (p, s)
            for p in sorted(list_source_files(root))
            for s in file_symbols(p)
            if _matches(s, qparts)
        ]
        if not hits:
            sys.stderr.write(f"hc: no symbol or file '{sel}'\n")
            return 1
        if len(hits) > SHOW_MAX_CANDIDATES:
            lines = [f"{len(hits)} matches, use hc show <file>:<symbol>:"]
            lines += [
                f"  {_rel(p, root)}:L{s.start}-{s.end}  {s.name}" for p, s in hits[:15]
            ]
            sys.stdout.write("\n".join(lines) + "\n")
            return 1
        return _emit_blocks(root, [(p, s.start, s.end) for p, s in hits])

    rel = _rel(path, root)
    if not sel:
        syms = file_symbols(path)
        if not syms:
            sys.stdout.write(f"{rel}: no symbols found\n")
            return 1
        sys.stdout.write(
            "\n".join(f"L{s.start}-{s.end}  {s.name}" for s in syms) + "\n"
        )
        return 0

    m = RANGE_RE.match(sel)
    if m:
        a = int(m.group(1))
        b = int(m.group(2) or a)
        return _emit_blocks(root, [(path, a, b)])

    qparts = _name_parts(sel)
    found = [s for s in file_symbols(path) if _matches(s, qparts)]
    if not found:
        names = ", ".join(s.name for s in file_symbols(path)[:30])
        sys.stderr.write(f"hc: no symbol '{sel}' in {rel}. Available: {names}\n")
        return 1
    return _emit_blocks(root, [(path, s.start, s.end) for s in found])
