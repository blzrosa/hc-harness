"""Índice incremental de imports/includes e grafo reverso de impacto (quais testes rodar)."""

from __future__ import annotations

import ast
import json
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import (
    ALL_C_CPP_EXTS,
    INCLUDE_RE,
    INDEX_VERSION,
    PYBIND_RE,
    VALID_EXTS,
    get_proj_id,
    state_file,
)
from .gitutil import get_git_changed_files, list_source_files, resolve_paths
from .ui import format_duration


@dataclass(frozen=True, slots=True)
class ImpactReport:
    py_affected: list[Path]
    py_tests: list[str]
    cpp_tests: list[str]
    needs_cpp_build: bool


def path_to_module(py_file: Path, root: Path) -> str:
    rel = py_file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[0] in ("src", "app", "python", "tests", "benchmarks"):
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _extract_file_imports(p: Path, mod_name: str) -> list[str]:
    try:
        source = p.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(p))
    except (OSError, SyntaxError):
        return []

    mod_parts = mod_name.split(".") if mod_name else []
    pkg_parts = mod_parts if p.name == "__init__.py" else mod_parts[:-1]
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base_mod = node.module or ""
            if node.level > 0:
                up = max(0, len(pkg_parts) - (node.level - 1))
                prefix = ".".join(pkg_parts[:up])
                full_mod = f"{prefix}.{base_mod}".strip(".") if prefix else base_mod
            else:
                full_mod = base_mod

            if full_mod:
                imports.add(full_mod)
            for alias in node.names:
                target = f"{full_mod}.{alias.name}".strip(".")
                if target:
                    imports.add(target)

    return sorted(imports)


def _parse_file(p: Path, root: Path, mtime: int, size: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"m": mtime, "s": size, "i": [], "c": [], "b": []}
    if p.suffix.lower() == ".py":
        entry["i"] = _extract_file_imports(p, path_to_module(p, root))
        return entry
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return entry
    entry["c"] = sorted({Path(inc).name for inc in INCLUDE_RE.findall(text)})
    entry["b"] = sorted({m1 or m2 for m1, m2 in PYBIND_RE.findall(text)})
    return entry


def build_index(root: Path) -> dict[Path, dict[str, Any]]:
    """Índice {arquivo -> imports/includes/pybind} com cache por (mtime_ns, size). Só re-parseia o que mudou."""
    files = list_source_files(root)
    cache_path = state_file(f"index_{get_proj_id(root)}.json")
    cached: dict[str, dict[str, Any]] = {}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if raw.get("v") == INDEX_VERSION:
            cached = raw.get("files", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    fresh: dict[str, dict[str, Any]] = {}
    index: dict[Path, dict[str, Any]] = {}
    dirty = False
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue  # arquivo removido mas ainda no índice do git
        rel = p.relative_to(root).as_posix()
        entry = cached.get(rel)
        if not (
            entry and entry.get("m") == st.st_mtime_ns and entry.get("s") == st.st_size
        ):
            entry = _parse_file(p, root, st.st_mtime_ns, st.st_size)
            dirty = True
        fresh[rel] = entry
        index[p] = entry

    if dirty or len(fresh) != len(cached):
        tmp = cache_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"v": INDEX_VERSION, "files": fresh}), encoding="utf-8"
            )
            tmp.replace(cache_path)
        except OSError:
            pass
    return index


def _is_test_file(p: Path) -> bool:
    return p.name.startswith("test_") or p.name.endswith("_test.py")


def _resolve_import(imp: str, mod_index: dict[str, list[Path]]) -> list[Path]:
    """Resolve `a.b.Symbol` para o módulo conhecido de MAIOR prefixo (`a.b`)."""
    parts = imp.split(".")
    for i in range(len(parts), 0, -1):
        hit = mod_index.get(".".join(parts[:i]))
        if hit:
            return hit
    return []


def get_affected_targets(
    root: Path, changed_files: list[Path], index: dict[Path, dict[str, Any]]
) -> ImpactReport:
    if not changed_files:
        return ImpactReport(
            py_affected=[], py_tests=[], cpp_tests=[], needs_cpp_build=False
        )

    py_files = [p for p in index if p.suffix.lower() == ".py"]
    cpp_files = [p for p in index if p.suffix.lower() in ALL_C_CPP_EXTS]

    # ---- C/C++: grafo reverso de #include + módulos expostos via pybind ----
    cpp_by_name: dict[str, list[Path]] = {}
    for p in cpp_files:
        cpp_by_name.setdefault(p.name, []).append(p)

    reverse_cpp: dict[Path, set[Path]] = {}
    exported_py_mods: dict[Path, set[str]] = {}
    for p in cpp_files:
        for inc_name in index[p]["c"]:
            for target in cpp_by_name.get(inc_name, ()):
                reverse_cpp.setdefault(target, set()).add(p)
        if index[p]["b"]:
            exported_py_mods[p] = set(index[p]["b"])

    cpp_changed = [p for p in changed_files if p.suffix.lower() in ALL_C_CPP_EXTS]
    cpp_queue: deque[Path] = deque(cpp_changed)
    cpp_visited: set[Path] = set(cpp_changed)
    affected_cpp_tests: set[str] = set()
    bridged_py_modules: set[str] = set()

    while cpp_queue:
        curr = cpp_queue.popleft()
        if "test" in curr.stem.lower():
            affected_cpp_tests.add(curr.stem)
        if curr in exported_py_mods:
            bridged_py_modules.update(exported_py_mods[curr])
        for dependent in reverse_cpp.get(curr, set()):
            if dependent not in cpp_visited:
                cpp_visited.add(dependent)
                cpp_queue.append(dependent)

    # ---- Python: resolve imports -> arquivos UMA vez e faz BFS no grafo reverso ----
    mod_index: dict[str, list[Path]] = {}
    for p in py_files:
        mod = path_to_module(p, root)
        if not mod:
            continue
        mod_index.setdefault(mod, []).append(p)
        if "." in mod:  # alias curto (layouts onde a 1ª pasta não faz parte do import)
            mod_index.setdefault(mod.split(".", maxsplit=1)[1], []).append(p)

    importers: dict[Path, set[Path]] = {}
    for p in py_files:
        for imp in index[p]["i"]:
            for target in _resolve_import(imp, mod_index):
                if target != p:
                    importers.setdefault(target, set()).add(p)

    py_changed = [p for p in changed_files if p.suffix.lower() == ".py"]
    py_queue: deque[Path] = deque(py_changed)
    py_visited: set[Path] = set(py_changed)

    if bridged_py_modules:
        for p in py_files:
            for imp in index[p]["i"]:
                if any(
                    imp == m or imp.endswith(f".{m}") or imp.startswith(f"{m}.")
                    for m in bridged_py_modules
                ):
                    if p not in py_visited:
                        py_visited.add(p)
                        py_queue.append(p)
                    break

    while py_queue:
        curr = py_queue.popleft()
        for imp in importers.get(curr, ()):
            if imp not in py_visited:
                py_visited.add(imp)
                py_queue.append(imp)

    affected_py_tests = {
        str(p.relative_to(root)) for p in py_visited if _is_test_file(p)
    }

    # conftest.py alterado afeta todos os testes sob a pasta dele
    for c in (p for p in changed_files if p.name == "conftest.py"):
        affected_py_tests.update(
            str(t.relative_to(root))
            for t in py_files
            if _is_test_file(t) and c.parent in t.parents
        )

    return ImpactReport(
        py_affected=sorted(py_visited),
        py_tests=sorted(affected_py_tests),
        cpp_tests=sorted(affected_cpp_tests),
        needs_cpp_build=bool(cpp_visited),
    )


def cmd_impact(root: Path, cwd: Path, names: list[str]) -> int:
    t0 = time.perf_counter_ns()
    explicit = resolve_paths(cwd, names)
    changed = explicit or [
        p for p in (get_git_changed_files(root) or []) if p.suffix.lower() in VALID_EXTS
    ]
    impact = get_affected_targets(root, changed, build_index(root))
    elapsed = format_duration(time.perf_counter_ns() - t0)
    sys.stdout.write(f"Target files: {[str(p.relative_to(root)) for p in changed]}\n")
    sys.stdout.write(f"Needs C/C++ Build: {impact.needs_cpp_build}\n")
    sys.stdout.write(f"Affected CTest: {impact.cpp_tests}\n")
    sys.stdout.write(f"Affected Pytest ({len(impact.py_tests)}): {impact.py_tests}\n")
    sys.stdout.write(f"Computed in {elapsed}\n")
    return 0
