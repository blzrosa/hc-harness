"""`hc map`: ordem alfabética, paginação por linhas, filtros --prefix/--sym e --list."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fixture import default_env_with_src, default_prefix, run_hc

N_MODULES = 12


def module_text(i: int) -> str:
    return (
        f"def alpha_{i:02d}(x: int) -> int:\n    return x\n\n\n"
        f"class Box{i:02d}:\n    def run(self) -> None:\n        pass\n\n"
        f"def zeta_{i:02d}() -> None:\n    pass\n"
    )


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    for i in range(N_MODULES):
        p = root / "src" / "gen" / f"mod_{i:02d}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(module_text(i), encoding="utf-8")
    (root / "src" / "B.py").write_text(
        "def bee() -> None:\n    pass\n", encoding="utf-8"
    )
    (root / "src" / "a.py").write_text(
        "def ay() -> None:\n    pass\n", encoding="utf-8"
    )
    return root


def hc(proj: Path, *args: str):
    return run_hc(
        default_prefix(),
        ["map", *args],
        proj,
        proj.parent / "home",
        extra_env=default_env_with_src(None),
    )


def headers(out: str) -> list[str]:
    return re.findall(r"^--- (.+) ---$", out, flags=re.MULTILINE)


def test_unpaged_output_has_no_footer_and_is_sorted_case_insensitive(
    proj: Path,
) -> None:
    cp = hc(proj, "src", "--limit=100000")
    assert cp.returncode == 0, cp.stderr
    assert "[page" not in cp.stdout
    hs = headers(cp.stdout)
    assert hs == sorted(hs, key=lambda s: (s.lower(), s))
    assert hs[0] == "src/a.py" and hs[1] == "src/B.py"


def test_pages_concatenate_to_full_output(proj: Path) -> None:
    full = hc(proj, "src", "--limit=100000").stdout
    first = hc(proj, "src", "--limit=12")
    m = re.search(r"\[page 1/(\d+) ", first.stdout)
    assert m, first.stdout
    total = int(m.group(1))
    assert total > 1
    chunks = []
    for page in range(1, total + 1):
        cp = hc(proj, "src", "--limit=12", f"--page={page}")
        assert cp.returncode == 0, cp.stderr
        body, _, footer = cp.stdout.rstrip("\n").rpartition("\n[page")
        assert footer.startswith(f" {page}/{total} ")
        assert ("next:" in footer) == (page < total)
        chunks.append(body)
    assert "\n".join(chunks) + "\n" == full


def test_footer_next_command_keeps_filters(proj: Path) -> None:
    cp = hc(proj, "src", "--prefix=src/gen", "--limit=12")
    assert "next: hc map src --prefix=src/gen --limit=12 --page=2]" in cp.stdout


def test_page_out_of_range(proj: Path) -> None:
    cp = hc(proj, "src", "--limit=12", "--page=99")
    assert cp.returncode == 1
    assert "page 99 out of range" in cp.stderr
    assert cp.stdout == ""


def test_prefix_filters_by_relative_path(proj: Path) -> None:
    cp = hc(proj, "src", "--prefix=src/gen/mod_0", "--limit=100000")
    hs = headers(cp.stdout)
    assert hs == [f"src/gen/mod_0{i}.py" for i in range(10)]
    cp2 = hc(proj, "--prefix=SRC/B")  # sem diferenciar maiúsculas
    assert headers(cp2.stdout) == ["src/B.py"]


def test_sym_filters_top_level_symbols(proj: Path) -> None:
    cp = hc(proj, "src", "--sym=Box03", "--limit=100000")
    assert headers(cp.stdout) == ["src/gen/mod_03.py"]
    assert "Box03" in cp.stdout and "alpha_03" not in cp.stdout
    assert "run(" in cp.stdout  # os membros acompanham a classe


def test_no_match_exits_1(proj: Path) -> None:
    cp = hc(proj, "src", "--prefix=nope")
    assert cp.returncode == 1
    assert "no files match" in cp.stdout


def test_list_is_one_line_per_file(proj: Path) -> None:
    cp = hc(proj, "src", "--list", "--limit=100000")
    lines = cp.stdout.strip().split("\n")
    assert lines[0] == "src/a.py  1"
    assert "src/gen/mod_00.py  3" in lines
    assert len(lines) == N_MODULES + 2


def test_file_mode_sym_and_paging(proj: Path) -> None:
    f = "src/gen/mod_05.py"
    cp = hc(proj, f, "--sym=zeta")
    assert "zeta_05" in cp.stdout and "alpha_05" not in cp.stdout
    paged = hc(proj, f, "--limit=3")
    assert "[page 1/" in paged.stdout and "symbols 1-" in paged.stdout
    miss = hc(proj, f, "--sym=qqq")
    assert miss.returncode == 1 and "no symbols starting with" in miss.stdout


@pytest.mark.parametrize("arg", ["--page=0", "--page=x", "--limit=-1"])
def test_bad_numbers_exit_2(proj: Path, arg: str) -> None:
    cp = hc(proj, "src", arg)
    assert cp.returncode == 2
    assert "positive integer" in cp.stderr


def test_value_option_without_equals_is_rejected(proj: Path) -> None:
    cp = hc(proj, "src", "--page")
    assert cp.returncode == 2
    assert "needs a value" in cp.stderr
