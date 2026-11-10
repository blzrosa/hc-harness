"""Constantes e helpers compartilhados do hc."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Final

STATE_DIR: Final[Path] = Path.home() / ".ai-harness" / "state"


def state_file(name: str) -> Path:
    """Caminho dentro de STATE_DIR. Cria a pasta só quando alguém precisa (importar o hc não toca o disco)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / name


C_EXTS: Final[frozenset[str]] = frozenset({".c", ".h"})
CPP_EXTS: Final[frozenset[str]] = frozenset(
    {".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx"}
)
ALL_C_CPP_EXTS: Final[frozenset[str]] = C_EXTS | CPP_EXTS
VALID_EXTS: Final[frozenset[str]] = ALL_C_CPP_EXTS | {".py"}

IGNORE_DIRS: Final[frozenset[str]] = frozenset(
    {
        "venv",
        ".venv",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        ".git",
        "cmake-build-debug",
        "cmake-build-release",
    }
)

# Arquivos que invalidam o cache de "último OK" e/ou exigem uv sync.
CONFIG_FILES: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "ruff.toml",
        ".ruff.toml",
        "pytest.ini",
        "pyrightconfig.json",
        "ty.toml",
    }
)

INDEX_VERSION: Final[int] = 2
MAX_ARG_CHARS: Final[int] = (
    20_000  # limite seguro p/ linha de comando no Windows (~32k)
)
MAX_OUT_CHARS: Final[int] = 12_000  # teto de saída por etapa (proteção de tokens)
PYTEST_OK_CODES: Final[tuple[int, ...]] = (0, 5)  # 5 = nenhum teste coletado

INCLUDE_RE: Final[re.Pattern[str]] = re.compile(
    r'^\s*#\s*include\s*["<]([^">]+)[">]', re.MULTILINE
)
PYBIND_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:PYBIND11_MODULE|NB_MODULE)\s*\(\s*([a-zA-Z0-9_]+)|PyInit_([a-zA-Z0-9_]+)"
)
SESSION_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^=+ test session starts =+$")
ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


LINE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"\r\n|\r|\n")


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("FORCE_COLOR", None)
    env.update(
        {
            "NO_COLOR": "1",
            "PY_COLORS": "0",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


CHILD_ENV: Final[dict[str, str]] = _child_env()


def get_proj_id(root: Path) -> str:
    return hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
