"""Caracterização do `hc guard`: o que é bloqueado (exit 2) e o que passa (exit 0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixture import default_env_with_src, default_prefix, run_hc

from hc_harness.guard import GUARD_DEFAULT_BLOCK, find_blocked_git

GOLD = json.loads(
    (Path(__file__).resolve().parent / "golden" / "guard_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize(("command", "code"), sorted(GOLD.items()))
def test_find_blocked_git(command: str, code: int) -> None:
    assert (find_blocked_git(command, GUARD_DEFAULT_BLOCK) is not None) == (code == 2)


@pytest.mark.parametrize(
    "command", ["git commit -m x", "bash -c 'git commit -m x'", "git status"]
)
def test_guard_cli(command: str, tmp_path: Path) -> None:
    cp = run_hc(
        default_prefix(),
        ["guard"],
        tmp_path,
        tmp_path,
        stdin=json.dumps({"tool_input": {"command": command}}),
        extra_env=default_env_with_src(),
    )
    assert cp.returncode == GOLD[command]
    if cp.returncode == 2:
        assert "hc guard" in cp.stderr
    assert cp.stdout == ""


def test_guard_ignores_malformed_input(tmp_path: Path) -> None:
    cp = run_hc(
        default_prefix(),
        ["guard"],
        tmp_path,
        tmp_path,
        stdin="isto nao e json",
        extra_env=default_env_with_src(),
    )
    assert cp.returncode == 0


def test_guard_env_override(tmp_path: Path) -> None:
    env = default_env_with_src({"HC_GUARD_BLOCK": "reset"})
    payload = lambda c: json.dumps({"tool_input": {"command": c}})
    blocked = run_hc(
        default_prefix(),
        ["guard"],
        tmp_path,
        tmp_path,
        stdin=payload("git reset --hard"),
        extra_env=env,
    )
    allowed = run_hc(
        default_prefix(),
        ["guard"],
        tmp_path,
        tmp_path,
        stdin=payload("git commit -m x"),
        extra_env=env,
    )
    assert (blocked.returncode, allowed.returncode) == (2, 0)
