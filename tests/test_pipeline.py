"""Fumaça do pipeline (`hc` sem argumentos) num projeto pequeno. Precisa de ruff e pytest no PATH."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fixture import build_project, default_env_with_src, default_prefix, run_hc

pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None or shutil.which("pytest") is None,
    reason="ruff e pytest precisam estar instalados",
)

# ty ausente/forçado: não depende de rede nem de pyright
ENV = default_env_with_src({"HC_TYPECHECKER": "ty"})


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    build_project(root)
    return root, home


def test_ok_then_cached(project: tuple[Path, Path]) -> None:
    root, home = project
    first = run_hc(default_prefix(), [], root, home, extra_env=ENV)
    assert first.returncode == 0, first.stdout
    assert first.stdout.startswith("OK in ")
    second = run_hc(default_prefix(), [], root, home, extra_env=ENV)
    assert second.returncode == 0
    assert "cached" in second.stdout


def test_failing_test_is_reported(project: tuple[Path, Path]) -> None:
    root, home = project
    t = root / "tests/test_util.py"
    t.write_bytes(t.read_bytes().replace(b"== 10", b"== 11"))
    cp = run_hc(default_prefix(), [], root, home, extra_env=ENV)
    assert cp.returncode == 1
    assert "=== PYTEST" in cp.stdout


def test_clean_tree(project: tuple[Path, Path]) -> None:
    root, home = project
    from fixture import git

    git(root, "add", "-A")
    git(root, "commit", "-qm", "all")
    cp = run_hc(default_prefix(), [], root, home, extra_env=ENV)
    assert cp.returncode == 0
    assert "clean tree" in cp.stdout
