"""Execução de ferramentas externas: subprocessos, achar executáveis, `uv sync` e etapas com progresso."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from .compress import compress_and_log
from .config import CHILD_ENV, MAX_ARG_CHARS, get_proj_id, state_file
from .ui import Progress


def run_cmd(
    cmd: list[str], cwd: Path | None = None, timeout: float | None = None
) -> tuple[int, str]:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=cwd,
            env=CHILD_ENV,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired as exc:
        partial = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        return (
            124,
            f"{partial}\n[hc] timeout after {timeout:.0f}s: {' '.join(cmd[:3])}".strip(),
        )
    return res.returncode, f"{res.stdout}\n{res.stderr}".strip()


def venv_bin_dir(root: Path) -> Path | None:
    for name in ("Scripts", "bin"):
        d = root / ".venv" / name
        if d.is_dir():
            return d
    return None


def find_tool(name: str, root: Path) -> str | None:
    """Prefere o executável do .venv do projeto (versão pinada); senão o do PATH."""
    bin_dir = venv_bin_dir(root)
    if bin_dir is not None:
        for cand in (f"{name}.exe", name):
            if (bin_dir / cand).is_file():
                return str(bin_dir / cand)
    return shutil.which(name)


def fit_args(targets: list[str], fallback: list[str]) -> list[str]:
    """Evita estourar o limite de linha de comando (Windows ~32k) com muitos arquivos."""
    return targets if sum(len(t) + 1 for t in targets) <= MAX_ARG_CHARS else fallback


def check_uv_sync(
    root: Path, progress: Progress, *, force_rebuild: bool = False
) -> str | None:
    existing = [t for t in (root / "pyproject.toml", root / "uv.lock") if t.exists()]
    if not existing or shutil.which("uv") is None:
        return None

    def config_hash() -> str:
        hasher = hashlib.sha256()
        for t in existing:
            hasher.update(t.read_bytes())
        return hasher.hexdigest()

    cache_file = state_file(f"uv_{get_proj_id(root)}.hash")
    current_hash = config_hash()
    up_to_date = (
        not force_rebuild
        and (root / ".venv").exists()
        and cache_file.exists()
        and cache_file.read_text(encoding="utf-8").strip() == current_hash
    )
    if up_to_date:
        return None

    if progress.enabled:
        # Terminal interativo: deixa o uv desenhar o próprio progresso (resolve/download/install).
        with progress.pause():
            sys.stderr.write("hc: uv sync\n")
            code = subprocess.run(
                ["uv", "sync"], cwd=root, stdin=subprocess.DEVNULL, check=False
            ).returncode
        if code != 0:
            return f"[uv sync failed] exit code {code} (uv output shown above)"
    else:
        code, out = run_cmd(["uv", "sync", "--quiet"], cwd=root)
        if code != 0:
            return f"[uv sync failed]\n{compress_and_log('uv', out)}"

    # Recalcula DEPOIS do sync: o uv pode reescrever o uv.lock.
    try:
        cache_file.write_text(config_hash(), encoding="utf-8")
    except OSError:
        pass
    return None


def run_stage(
    progress: Progress,
    label: str,
    cmd: list[str],
    root: Path,
    *,
    title: str,
    log_key: str,
    ok_codes: tuple[int, ...] = (0,),
) -> str | None:
    """Roda uma ferramenta mostrando `label` no spinner. Retorna o bloco de erro comprimido ou None."""
    with progress.stage(label):
        code, out = run_cmd(cmd, root)
    if code in ok_codes:
        return None
    with progress.stage("comprimindo saída"):
        body = compress_and_log(log_key, out)
    return f"=== {title} ===\n{body}"
