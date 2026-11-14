"""Pontos de entrada lumine, vera, selene e o alias hc."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hc_harness import cli

SRC = Path(cli.__file__).resolve().parents[1]
TARGET = str(Path(cli.__file__).resolve())


def test_lumine_rejects_check(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main_lumine([])
    assert exc.value.code == 2
    assert "lumine map" in capsys.readouterr().out


def test_vera_rejects_map() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main_vera(["map"])
    assert exc.value.code == 2


def _run(fn, args: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as exc:
        fn(args)
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_hc_still_dispatches_map(capsys: pytest.CaptureFixture[str]) -> None:
    hc_out = _run(cli.main, ["map", TARGET], capsys)
    lumine_out = _run(cli.main_lumine, ["map", TARGET], capsys)
    assert hc_out
    assert hc_out == lumine_out


def test_selene_fast_path() -> None:
    code = (
        "import sys\n"
        "from hc_harness.cli import main_selene\n"
        "try:\n"
        "    main_selene([])\n"
        "except SystemExit:\n"
        "    pass\n"
        "bad = [m for m in ('hc_harness.pipeline', 'tree_sitter') if m in sys.modules]\n"
        "print('BAD:' + ','.join(bad))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        input="",
        capture_output=True,
        text=True,
        check=False,
        cwd=str(SRC),
        env={**__import__("os").environ, "PYTHONPATH": str(SRC)},
    )
    assert "BAD:" in proc.stdout, proc.stderr
    assert proc.stdout.strip().endswith("BAD:")
