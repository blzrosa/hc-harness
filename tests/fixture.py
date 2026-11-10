"""Projeto de exemplo determinístico + casos de caracterização do hc.

Os arquivos `golden/*.txt` foram gerados pelo `hc.py` monolítico (antes da divisão em módulos).
Se o comportamento mudar DE PROPÓSITO, regenere com `tests/make_golden.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

FILES: dict[str, str] = {
    "src/demo/__init__.py": '''"""Pacote de exemplo."""

from .core import Engine, slugify_title

__all__ = ["Engine", "slugify_title"]
''',
    "src/demo/util.py": '''"""Funções auxiliares."""

from __future__ import annotations

import re

SEPARATOR = "-"


def slugify(text: str) -> str:
    """Converte texto em slug."""
    return re.sub(r"[^a-z0-9]+", SEPARATOR, text.lower()).strip(SEPARATOR)


def clamp(value: int, low: int = 0, high: int = 10) -> int:
    return max(low, min(value, high))
''',
    "src/demo/core.py": '''"""Núcleo de exemplo."""

from __future__ import annotations

from dataclasses import dataclass

from .util import clamp, slugify

DEFAULT_LIMIT: int = 5


class Base:
    name: str = "base"

    def describe(self) -> str:
        return f"<{self.name}>"


@dataclass
class Engine(Base):
    limit: int = DEFAULT_LIMIT

    def run(self, steps: int) -> list[int]:
        """Roda `steps` passos limitados."""
        return [clamp(i, 0, self.limit) for i in range(steps)]

    @staticmethod
    def label(text: str) -> str:
        return slugify(text)


async def fetch(url: str, *, retries: int = 3) -> str:
    return url * retries


def slugify_title(title: str) -> str:
    return slugify(title)
''',
    "tests/conftest.py": """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
""",
    "tests/test_core.py": """from demo.core import Engine, slugify_title


def test_run():
    assert Engine(limit=2).run(4) == [0, 1, 2, 2]


def test_label():
    assert Engine.label("Hello World") == "hello-world"


def test_title():
    assert slugify_title("A B") == "a-b"
""",
    "tests/test_util.py": """from demo.util import clamp, slugify


def test_clamp():
    assert clamp(20) == 10


def test_slugify():
    assert slugify("X  y") == "x-y"
""",
}

UNCOMMITTED_APPEND = """

def shout(text: str) -> str:
    return slugify(text).upper()
"""

# nome -> argumentos do hc
CASES: dict[str, list[str]] = {
    "map_dir": ["map", "src"],
    "map_file": ["map", "src/demo/core.py"],
    "map_missing": ["map", "nope"],
    "find_class": ["find", "Engine"],
    "find_method": ["find", "Engine.run"],
    "find_func_uses": ["find", "slugify"],
    "find_none": ["find", "zzz_missing"],
    "find_usage": ["find"],
    "show_symbol": ["show", "src/demo/core.py:Engine.run"],
    "show_range": ["show", "src/demo/core.py:L1-12"],
    "show_list": ["show", "src/demo/core.py"],
    "show_global": ["show", "clamp"],
    "show_missing": ["show", "src/demo/core.py:nope"],
    "show_usage": ["show"],
    "impact_git": ["impact"],
    "impact_file": ["impact", "src/demo/core.py"],
    "help": ["--help"],
    "bad_flag": ["--zzz"],
}

# comandos testados no guard (o esperado vem do golden/guard_cases.json)
GUARD_COMMANDS: list[str] = [
    "git commit -m x",
    "git push",
    "git push origin main",
    "cd x && git commit -m y",
    "git status && git commit -am z",
    "git -C /tmp commit -m x",
    "git -c user.name=a commit -m x",
    "/usr/bin/git commit -m x",
    "bash -c 'git commit -m x'",
    "sh -c \"bash -c 'git push'\"",
    'pwsh -Command "git push"',
    "echo hi | git push",
    "(git commit -m x)",
    "echo $(git push)",
    "GIT commit -m x",
    "echo git commit",
    "git status",
    "git diff --stat",
    "git log -5 --format=%s",
    "git add -A",
    "grep -n commit file.py",
    "hc",
    "hc --all",
    "uv run python x.py",
    "ls -la",
    "",
]


def git(root: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=hc-test",
            "-c",
            "user.email=hc@test",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def build_project(root: Path) -> None:
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))  # bytes: LF em qualquer SO
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    util = root / "src/demo/util.py"
    util.write_bytes(util.read_bytes() + UNCOMMITTED_APPEND.encode("utf-8"))


def hc_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(HOME=str(home), USERPROFILE=str(home), HC_PLAIN="1", PYTHONUTF8="1")
    env.pop("CI", None)
    if extra:
        env.update(extra)
    return env


def run_hc(
    prefix: list[str],
    args: list[str],
    cwd: Path,
    home: Path,
    stdin: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*prefix, *args],
        cwd=cwd,
        env=hc_env(home, extra_env),
        input=stdin if stdin is not None else "",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def render(cp: subprocess.CompletedProcess[str], root: Path) -> str:
    """Saída normalizada: sem tempos, sem caminho absoluto, sem barra invertida."""

    def norm(s: str) -> str:
        for variant in {
            str(root),
            str(root.resolve()),
            root.as_posix(),
            root.resolve().as_posix(),
        }:
            s = s.replace(variant, "<root>")
        # repr de lista no Windows escapa a barra ('src\\\\demo'): colapsa as duplas antes das simples
        s = s.replace("\\\\", "/").replace("\\", "/")
        s = re.sub(r"Computed in .*", "Computed in <t>", s)
        return s

    return f"exit={cp.returncode}\n--stdout--\n{norm(cp.stdout)}--stderr--\n{norm(cp.stderr)}"


def default_prefix() -> list[str]:
    return [sys.executable, "-m", "hc_harness"]


def default_env_with_src(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PYTHONPATH": str(SRC_DIR)}
    if extra:
        env.update(extra)
    return env
