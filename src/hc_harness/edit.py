"""`hc edit` e `hc write`: edição de arquivos pela entrada padrão, resiliente a CRLF, BOM e espaços finais.

Por que existe: o `Edit` nativo falha quando o arquivo tem CRLF e o modelo manda LF; aí o modelo cai para
`python - <<EOF` ou `sed -i`, que custam mais tokens e não checam nada. Aqui o casamento ignora o tipo de
fim de linha, preserva o que não foi tocado byte a byte e grava tudo-ou-nada.

Formato do `hc edit FILE` (blocos de LINHAS INTEIRAS; vários blocos por chamada):

    <<<<<<< SEARCH
    linhas a achar (devem ser únicas no arquivo; senão acrescente contexto ou use --all)
    =======
    linhas novas (vazio = apagar as linhas)
    >>>>>>> REPLACE

Se o texto contiver uma linha `=======`, use marcadores mais longos (`<<<<<<<<`, `========`, `>>>>>>>>`):
o divisor e o fecho precisam ter o mesmo comprimento do marcador de abertura.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

BOM: Final[bytes] = b"\xef\xbb\xbf"
OPEN_RE: Final[re.Pattern[str]] = re.compile(r"^(<{7,}) SEARCH[ \t]*$")
MAX_LISTED_MATCHES: Final[int] = 5
OFF_LIMITS: Final[frozenset[str]] = frozenset({".git", ".claude"})


class EditError(Exception):
    """Erro de uso ou de casamento: nada foi gravado."""


@dataclass(slots=True)
class LoadedFile:
    text: str  # decodificado, com os fins de linha originais e sem BOM
    bom: bool
    dominant_eol: str


# ---------------------------------------------------------------- entrada e alvo


def read_stdin() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        raise EditError(
            "reads its content from stdin (use a heredoc: hc edit FILE <<'EOF' ... EOF)"
        )
    data = sys.stdin.buffer.read()
    try:
        text = data.decode("utf-8-sig")  # tolera BOM no começo (PowerShell)
    except UnicodeDecodeError:
        raise EditError("stdin is not valid UTF-8") from None
    # `\r+\n`: além de CRLF, aceita `\r\r\n` (duas camadas de tradução de fim de linha, comum no Windows)
    return re.sub(r"\r+\n", "\n", text)


def resolve_target(root: Path, cwd: Path, raw: str) -> Path:
    """Só dentro do projeto e fora de .git/.claude: `Bash(hc *)` é liberado sem pedir permissão,
    então esta ferramenta não pode ser um jeito de escapar das regras do Edit/Write."""
    path = (cwd / raw).resolve()
    try:
        rel = path.relative_to(root.resolve())
    except ValueError:
        raise EditError(
            f"{raw}: outside the project root; use the Edit/Write tools"
        ) from None
    if rel.parts and rel.parts[0] in OFF_LIMITS:
        raise EditError(
            f"{raw}: `{rel.parts[0]}/` is off limits for hc edit/write (the Edit/Write tools have their own permission rules)"
        )
    return path


def rel_name(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_file(path: Path) -> LoadedFile:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise EditError(f"{path.name}: binary file")
    bom = raw.startswith(BOM)
    try:
        text = (raw[len(BOM) :] if bom else raw).decode("utf-8")
    except UnicodeDecodeError:
        raise EditError(f"{path.name}: not valid UTF-8") from None
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    return LoadedFile(text, bom, "\r\n" if crlf > lf_only else "\n")


def write_atomic(path: Path, data: bytes) -> None:
    """Grava num temporário ao lado e troca (os.replace): ou o arquivo novo inteiro, ou o antigo."""
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.hc-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- blocos SEARCH/REPLACE


def _join(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def parse_blocks(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        m = OPEN_RE.match(lines[i])
        if m is None:
            raise EditError(
                f"stdin line {i + 1}: expected '<<<<<<< SEARCH', got {lines[i][:40]!r}"
            )
        n = len(m.group(1))
        divider, closer = "=" * n, ">" * n + " REPLACE"
        j = i + 1
        search: list[str] = []
        while j < len(lines) and lines[j].rstrip() != divider:
            search.append(lines[j])
            j += 1
        if j >= len(lines):
            raise EditError(f"block {len(blocks) + 1}: missing '{divider}' divider")
        k = j + 1
        repl: list[str] = []
        while k < len(lines) and lines[k].rstrip() != closer:
            repl.append(lines[k])
            k += 1
        if k >= len(lines):
            raise EditError(f"block {len(blocks) + 1}: missing '{closer}' marker")
        blocks.append((_join(search), _join(repl)))
        i = k + 1
    if not blocks:
        raise EditError("no SEARCH/REPLACE block on stdin")
    return blocks


def _pattern(search: str, *, relaxed: bool) -> re.Pattern[str]:
    """Casa linhas inteiras, qualquer fim de linha (LF/CRLF); `relaxed` também ignora espaços no fim da linha."""
    parts = search.split("\n")[:-1]
    sep = r"[ \t]*\r?\n" if relaxed else r"\r?\n"
    body = sep.join(re.escape(p.rstrip() if relaxed else p) for p in parts) + sep
    return re.compile(r"(?<![^\n])" + body)


def _lineno(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _clip(s: str, n: int = 100) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _not_found(idx: int, work: str, search: str) -> str:
    want = search.rstrip("\n").split("\n")
    have = work.replace("\r\n", "\n").split("\n")
    n = len(want)
    first = want[0].strip()
    best_i, best_ratio = -1, 0.0
    for i in range(max(0, len(have) - n + 1)):
        if difflib.SequenceMatcher(None, have[i].strip(), first).quick_ratio() < 0.6:
            continue
        r = difflib.SequenceMatcher(
            None, "\n".join(have[i : i + n]), "\n".join(want)
        ).ratio()
        if r > best_ratio:
            best_i, best_ratio = i, r
    msg = f"block {idx}: SEARCH not found."
    if best_i < 0 or best_ratio < 0.5:
        return (
            msg + " No similar text in the file (check the file/path and re-read it)."
        )
    region = have[best_i : best_i + n]
    for k, (w, h) in enumerate(zip(want, region, strict=False)):
        if w != h:
            return (
                f"{msg} Closest at L{best_i + 1}-{best_i + n}; first difference at SEARCH line {k + 1}:\n"
                f"  SEARCH: {_clip(w)}\n  file:   {_clip(h)}"
            )
    return f"{msg} Closest at L{best_i + 1}-{best_i + n} (differs only in length)."


def apply_block(
    work: str, search: str, repl: str, *, replace_all: bool, idx: int
) -> tuple[str, list[int], bool]:
    """Devolve (texto novo, linhas onde casou, usou_tolerancia_de_espaco_final)."""
    if not search:
        raise EditError(f"block {idx}: empty SEARCH (use `hc write` for new files)")
    relaxed = False
    matches = list(_pattern(search, relaxed=False).finditer(work))
    if not matches:
        matches = list(_pattern(search, relaxed=True).finditer(work))
        relaxed = bool(matches)
    if not matches:
        raise EditError(_not_found(idx, work, search))
    if len(matches) > 1 and not replace_all:
        where = ", ".join(
            f"L{_lineno(work, m.start())}" for m in matches[:MAX_LISTED_MATCHES]
        )
        more = "…" if len(matches) > MAX_LISTED_MATCHES else ""
        raise EditError(
            f"block {idx}: SEARCH matches {len(matches)} places ({where}{more}). "
            "Add surrounding lines to make it unique, or pass --all."
        )
    out: list[str] = []
    pos = 0
    lines: list[int] = []
    for m in matches:
        out.append(work[pos : m.start()])
        eol = "\r\n" if "\r\n" in m.group(0) else "\n"
        out.append(repl.replace("\n", eol))
        pos = m.end()
        lines.append(_lineno(work, m.start()))
    out.append(work[pos:])
    return "".join(out), lines, relaxed


# ---------------------------------------------------------------- comandos


def cmd_edit(
    root: Path, cwd: Path, names: list[str], *, replace_all: bool = False
) -> int:
    if len(names) != 1:
        sys.stderr.write(
            "usage: hc edit <file> [--all]   (SEARCH/REPLACE blocks on stdin; see hc --help)\n"
        )
        return 2
    try:
        path = resolve_target(root, cwd, names[0])
        if not path.is_file():
            raise EditError(f"{names[0]}: no such file (use `hc write` for new files)")
        blocks = parse_blocks(read_stdin())
        loaded = load_file(path)
        tmp_eol = "\r\n" if "\r\n" in loaded.text else "\n"
        no_final_newline = bool(loaded.text) and not loaded.text.endswith("\n")
        work = loaded.text + tmp_eol if no_final_newline else loaded.text

        notes: list[str] = []
        for idx, (search, repl) in enumerate(blocks, 1):
            work, lines, relaxed = apply_block(
                work, search, repl, replace_all=replace_all, idx=idx
            )
            removed, added = search.count("\n"), repl.count("\n")
            where = ",".join(f"L{n}" for n in lines)
            tag = f" x{len(lines)}" if len(lines) > 1 else ""
            note = f"{where}{tag} (-{removed} +{added})"
            notes.append(f"{note} [trailing whitespace ignored]" if relaxed else note)

        if no_final_newline and work.endswith(tmp_eol):
            work = work[: -len(tmp_eol)]
        if work == loaded.text:
            raise EditError(
                "result is identical to the original (SEARCH == REPLACE?); nothing written"
            )
        write_atomic(path, (BOM if loaded.bom else b"") + work.encode("utf-8"))
    except EditError as exc:
        sys.stderr.write(f"hc edit: {exc}\n(nothing was written)\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"hc edit: {exc}\n")
        return 1
    summary = (
        notes[0]
        if len(notes) == 1
        else f"{len(notes)} blocks: "
        + "; ".join(f"{i}: {n}" for i, n in enumerate(notes, 1))
    )
    sys.stdout.write(f"OK {rel_name(path, root)}: {summary}\n")
    return 0


def cmd_write(root: Path, cwd: Path, names: list[str], *, force: bool = False) -> int:
    if len(names) != 1:
        sys.stderr.write("usage: hc write <file> [--force]   (content on stdin)\n")
        return 2
    try:
        path = resolve_target(root, cwd, names[0])
        exists = path.exists()
        if exists and not path.is_file():
            raise EditError(f"{names[0]}: not a regular file")
        if exists and not force:
            raise EditError(
                f"{names[0]} already exists: change it with Edit / `hc edit`, or pass --force to overwrite"
            )
        content = read_stdin()
        if not content.strip():
            raise EditError("empty content on stdin; refusing to write an empty file")
        if not content.endswith("\n"):
            content += "\n"
        bom, eol = False, "\n"
        if exists:  # sobrescrita mantém o estilo do arquivo existente
            old = load_file(path)
            bom, eol = old.bom, old.dominant_eol
        data = (BOM if bom else b"") + content.replace("\n", eol).encode("utf-8")
        if exists:
            write_atomic(path, data)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    except EditError as exc:
        sys.stderr.write(f"hc write: {exc}\n(nothing was written)\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"hc write: {exc}\n")
        return 1
    sys.stdout.write(
        f"OK wrote {rel_name(path, root)} ({content.count(chr(10))} lines)\n"
    )
    return 0
