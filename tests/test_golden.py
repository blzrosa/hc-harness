"""Caracterização: a saída de map/find/show/impact/help não pode mudar sem querer."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixture import (
    CASES,
    build_project,
    default_env_with_src,
    default_prefix,
    render,
    run_hc,
)

GOLD = Path(__file__).resolve().parent / "golden"


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("proj")
    home = tmp_path_factory.mktemp("home")
    build_project(root)
    return root, home


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden(name: str, project: tuple[Path, Path]) -> None:
    root, home = project
    cp = run_hc(
        default_prefix(), CASES[name], root, home, extra_env=default_env_with_src()
    )
    expected = (GOLD / f"{name}.txt").read_text(encoding="utf-8")
    assert render(cp, root) == expected
