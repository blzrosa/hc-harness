"""Git e descoberta de arquivos-fonte."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from .config import IGNORE_DIRS, VALID_EXTS


def is_ignored(rel_path: Path) -> bool:
    """Recebe caminho RELATIVO à raiz (o prefixo absoluto pode conter pastas com '.')."""
    return any(part.startswith(".") or part in IGNORE_DIRS for part in rel_path.parts)


def find_root(start: Path) -> Path:
    """Raiz = primeiro ancestral com .git (dir ou arquivo, p/ worktrees); senão pyproject.toml."""
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    for d in (start, *start.parents):
        if (d / "pyproject.toml").exists():
            return d
    return start


LAST_GIT_ERROR: list[str] = []


def _git(root: Path, *args: str) -> bytes | None:
    LAST_GIT_ERROR.clear()
    try:
        res = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        LAST_GIT_ERROR.append(f"git not runnable: {exc}")
        return None
    if res.returncode != 0:
        LAST_GIT_ERROR.append(res.stderr.decode("utf-8", "replace").strip())
        return None
    return res.stdout


def _walk(root: Path) -> Iterator[Path]:
    """Fallback fora do git: os.walk PODANDO diretórios ignorados (rglob entraria no .venv)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            yield Path(dirpath) / name


def list_source_files(root: Path) -> list[Path]:
    """Lista arquivos-fonte via `git ls-files` (rápido, respeita .gitignore) com fallback p/ os.walk."""
    excludes = [
        f":(exclude,glob)**/{d}/**" for d in sorted(IGNORE_DIRS)
    ]  # poda no git mesmo sem .gitignore
    out = _git(
        root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        ".",
        *excludes,
    )
    if out is not None:
        rels = [
            r
            for r in out.decode("utf-8", "replace").split("\0")
            if r and os.path.splitext(r)[1].lower() in VALID_EXTS
        ]
        return [root / r for r in rels if not is_ignored(Path(r))]
    return [
        p
        for p in _walk(root)
        if p.suffix.lower() in VALID_EXTS and not is_ignored(p.relative_to(root))
    ]


def get_git_changed_files(root: Path) -> list[Path] | None:
    """Arquivos modificados/novos (qualquer extensão). None => não é um repositório git."""
    excludes = [f":(exclude,glob)**/{d}/**" for d in sorted(IGNORE_DIRS)]
    out = _git(root, "status", "--porcelain=v1", "-z", "-uall", "--", ".", *excludes)
    if out is None:
        return None
    entries = out.decode("utf-8", "replace").split("\0")
    changed: list[Path] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, rel = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            i += 1  # com -z, o caminho de origem vem como entrada extra
        p = (root / rel).resolve()
        if p.exists():
            changed.append(p)
    return changed


def resolve_paths(cwd: Path, names: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for name in names:
        p = (cwd / name).resolve()
        if p.exists():
            resolved.append(p)
        else:
            sys.stderr.write(f"hc: ignoring missing path: {name}\n")
    return resolved
