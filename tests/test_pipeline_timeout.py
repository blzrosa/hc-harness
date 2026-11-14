"""Orçamento de tempo do vera e tempos por estágio na linha OK."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fixture import build_project, default_env_with_src, default_prefix, run_hc

from hc_harness.pipeline import format_ok_line

needs_tools = pytest.mark.skipif(
    shutil.which("ruff") is None or shutil.which("pytest") is None,
    reason="ruff e pytest precisam estar instalados",
)

ENV = default_env_with_src({"HC_TYPECHECKER": "ty"})


@needs_tools
def test_timeout_reports_stage(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    build_project(root)
    t = root / "tests/test_util.py"
    t.write_text(
        "import time\n\n\ndef test_sleeps() -> None:\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    cp = run_hc(default_prefix(), ["--timeout=1"], root, home, extra_env=ENV)
    assert cp.returncode == 1, cp.stdout
    assert "=== TIMEOUT ===" in cp.stdout
    assert "pytest" in cp.stdout
    # nunca grava last_ok: a segunda execução também estoura, em vez de dizer "cached"
    again = run_hc(default_prefix(), ["--timeout=1"], root, home, extra_env=ENV)
    assert "=== TIMEOUT ===" in again.stdout
    assert "cached" not in again.stdout


def test_slow_ok_lists_stage_times() -> None:
    timings = [
        ("pytest (3 files)", 88.0),
        ("pyright (2 files)", 6.0),
        ("ruff fix", 0.4),
    ]
    line = format_ok_line(95.0, timings, "", "1m 35.0s")
    assert line == "OK in 95 s (pytest 88 s, pyright 6 s)\n"


def test_fast_ok_line_unchanged() -> None:
    line = format_ok_line(2.0, [("pytest (1 file)", 1.5)], "", "2.00 s")
    assert line == "OK in 2.00 s\n"
