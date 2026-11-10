"""`hc map`: esqueleto de código (classes, assinaturas, linhas), paginado, em ordem alfabética e filtrável.

    hc map <pasta|arquivo> [--page=N] [--limit=LINHAS] [--prefix=CAMINHO] [--sym=NOME] [--list]

* Pasta: arquivos em ordem alfabética (sem diferenciar maiúsculas) pelo caminho relativo à raiz.
  `--prefix` fica só com os arquivos cujo caminho começa assim (relativo à raiz, como aparece na saída).
* `--sym` fica só com os símbolos de topo cujo nome começa assim (em pasta ou arquivo).
* `--list` mostra uma linha por arquivo (caminho e nº de símbolos de topo): o jeito barato de escolher o que abrir.
* Paginação por linhas (`--limit`, padrão 150) sem partir um arquivo no meio: se coube numa página só,
  a saída é exatamente a de antes; se não, o rodapé diz qual comando mostra a próxima página.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .gitutil import list_source_files
from .symbols import extract_skeleton

DEFAULT_LIMIT: Final[int] = 150
HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^L\d+(?:-\d+)?: (.*)$")


@dataclass(frozen=True, slots=True)
class MapOptions:
    page: int = 1
    limit: int = DEFAULT_LIMIT
    prefix: str = ""
    sym: str = ""
    list_only: bool = False


def _positive(opts: dict[str, str], name: str, default: int) -> int:
    raw = opts.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError(f"{name} must be a positive integer (got {raw!r})")
    return value


def parse_map_options(opts: dict[str, str], list_only: bool) -> MapOptions:
    return MapOptions(
        page=_positive(opts, "--page", 1),
        limit=_positive(opts, "--limit", DEFAULT_LIMIT),
        prefix=opts.get("--prefix", ""),
        sym=opts.get("--sym", ""),
        list_only=list_only,
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _blocks(skeleton: str) -> list[list[str]]:
    """Um bloco por símbolo de topo: a linha dele + as linhas indentadas (membros) que vêm depois."""
    blocks: list[list[str]] = []
    for line in skeleton.split("\n"):
        if blocks and line.startswith(" "):
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return blocks


def _block_name(block: list[str]) -> str | None:
    m = HEADER_RE.match(block[0])
    if m is None:
        return None
    head = m.group(1).split("(", 1)[0].rstrip(": \t").split()
    return head[-1] if head else None


def _sym_matches(block: list[str], sym: str) -> bool:
    name = _block_name(block)
    return name is not None and (
        name.startswith(sym) or name.split("::")[-1].startswith(sym)
    )


def _pack(units: list[list[str]], limit: int) -> list[list[list[str]]]:
    """Agrupa unidades (arquivo ou símbolo) em páginas de até `limit` linhas; nunca parte uma unidade."""
    pages: list[list[list[str]]] = []
    current: list[list[str]] = []
    used = 0
    for unit in units:
        if current and used + len(unit) > limit:
            pages.append(current)
            current, used = [], 0
        current.append(unit)
        used += len(unit)
    if current:
        pages.append(current)
    return pages


def _next_command(arg: str, o: MapOptions, page: int) -> str:
    parts = ["hc map", f'"{arg}"' if " " in arg else arg]
    if o.prefix:
        parts.append(f"--prefix={o.prefix}")
    if o.sym:
        parts.append(f"--sym={o.sym}")
    if o.list_only:
        parts.append("--list")
    if o.limit != DEFAULT_LIMIT:
        parts.append(f"--limit={o.limit}")
    parts.append(f"--page={page}")
    return " ".join(parts)


def _emit(units: list[list[str]], o: MapOptions, noun: str, arg: str) -> int:
    pages = _pack(units, o.limit)
    if o.page > len(pages):
        sys.stderr.write(f"hc: page {o.page} out of range (1-{len(pages)})\n")
        return 1
    shown = pages[o.page - 1]
    lines = [line for unit in shown for line in unit]
    if len(pages) > 1:
        first = sum(len(p) for p in pages[: o.page - 1]) + 1
        footer = f"[page {o.page}/{len(pages)} · {noun} {first}-{first + len(shown) - 1} of {len(units)}"
        if o.page < len(pages):
            footer += f" · next: {_next_command(arg, o, o.page + 1)}"
        lines.append(footer + "]")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def _dir_units(root: Path, target: Path, o: MapOptions) -> list[list[str]]:
    prefix = o.prefix.replace("\\", "/").removeprefix("./").lower()
    entries = sorted(
        (
            (_rel(p, root), p)
            for p in list_source_files(root)
            if p.resolve().is_relative_to(target)
        ),
        key=lambda e: (e[0].lower(), e[0]),
    )
    units: list[list[str]] = []
    for rel, path in entries:
        if prefix and not rel.lower().startswith(prefix):
            continue
        blocks = _blocks(extract_skeleton(path))
        if o.sym:
            blocks = [b for b in blocks if _sym_matches(b, o.sym)]
            if not blocks:
                continue
        if o.list_only:
            units.append([f"{rel}  {sum(1 for b in blocks if _block_name(b))}"])
        else:
            units.append([f"--- {rel} ---", *(line for b in blocks for line in b)])
    return units


def cmd_map(
    root: Path, cwd: Path, names: list[str], options: MapOptions | None = None
) -> int:
    o = options or MapOptions()
    arg = names[0] if names else "."
    target = (cwd / arg).resolve()
    if target.is_file():
        blocks = _blocks(extract_skeleton(target))
        if o.sym:
            blocks = [b for b in blocks if _sym_matches(b, o.sym)]
            if not blocks:
                sys.stdout.write(
                    f"no symbols starting with '{o.sym}' in {_rel(target, root)}\n"
                )
                return 1
        return _emit(blocks, o, "symbols", arg)
    if target.is_dir():
        units = _dir_units(root, target, o)
        if not units and (o.prefix or o.sym):
            what = " and ".join(
                part
                for part in (
                    f"path prefix '{o.prefix}'" if o.prefix else "",
                    f"symbol prefix '{o.sym}'" if o.sym else "",
                )
                if part
            )
            sys.stdout.write(f"no files match {what} under {arg}\n")
            return 1
        return _emit(units, o, "files", arg) if units else 0
    sys.stderr.write(f"hc: no such path: {target}\n")
    return 2
