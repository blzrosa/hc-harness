"""`hc edit` / `hc write`: casamento tolerante a CRLF, preservação byte a byte, tudo-ou-nada, limites."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixture import default_env_with_src, default_prefix, run_hc

from hc_harness.edit import EditError, parse_blocks


def block(search: str, replace: str, marker: int = 7) -> str:
    lt, eq, gt = "<" * marker, "=" * marker, ">" * marker
    return f"{lt} SEARCH\n{search}{eq}\n{replace}{gt} REPLACE\n"


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()  # find_root reconhece a raiz
    (tmp_path / "home").mkdir()
    return root


def hc(proj: Path, args: list[str], stdin: str = "", env: dict[str, str] | None = None):
    return run_hc(
        default_prefix(),
        args,
        proj,
        proj.parent / "home",
        stdin=stdin,
        extra_env=default_env_with_src(env),
    )


def put(proj: Path, name: str, data: bytes) -> Path:
    p = proj / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# ---------------------------------------------------------------- edit: caminho feliz


def test_replace_unique_block_lf(proj: Path) -> None:
    f = put(proj, "a.py", b"x = 1\ny = 2\nz = 3\n")
    cp = hc(proj, ["edit", "a.py"], block("y = 2\n", "y = 20\nw = 4\n"))
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout == "OK a.py: L2 (-1 +2)\n"
    assert f.read_bytes() == b"x = 1\ny = 20\nw = 4\nz = 3\n"


def test_crlf_file_edited_with_lf_search_stays_crlf(proj: Path) -> None:
    f = put(proj, "a.py", b"x = 1\r\ny = 2\r\nz = 3\r\n")
    cp = hc(proj, ["edit", "a.py"], block("x = 1\ny = 2\n", "x = 10\ny = 20\nq = 5\n"))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"x = 10\r\ny = 20\r\nq = 5\r\nz = 3\r\n"


def test_mixed_eol_untouched_lines_keep_their_bytes(proj: Path) -> None:
    f = put(proj, "a.txt", b"a\r\nb\nc\r\nd\n")
    cp = hc(proj, ["edit", "a.txt"], block("b\n", "B\n"))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"a\r\nB\nc\r\nd\n"


def test_bom_is_preserved(proj: Path) -> None:
    f = put(proj, "a.py", b"\xef\xbb\xbfx = 1\ny = 2\n")
    cp = hc(proj, ["edit", "a.py"], block("y = 2\n", "y = 3\n"))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"\xef\xbb\xbfx = 1\ny = 3\n"


def test_missing_final_newline_is_preserved(proj: Path) -> None:
    f = put(proj, "a.py", b"x = 1\ny = 2")
    cp = hc(proj, ["edit", "a.py"], block("y = 2\n", "y = 3\n"))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"x = 1\ny = 3"


def test_trailing_whitespace_in_file_is_tolerated(proj: Path) -> None:
    f = put(proj, "a.py", b"x = 1   \ny = 2\t\nz = 3\n")
    cp = hc(proj, ["edit", "a.py"], block("x = 1\ny = 2\n", "x = 9\n"))
    assert cp.returncode == 0, cp.stderr
    assert "trailing whitespace ignored" in cp.stdout
    assert f.read_bytes() == b"x = 9\nz = 3\n"


def test_empty_replace_deletes_the_lines(proj: Path) -> None:
    f = put(proj, "a.py", b"a\nb\nc\n")
    cp = hc(proj, ["edit", "a.py"], block("b\n", ""))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"a\nc\n"


def test_utf8_roundtrip(proj: Path) -> None:
    f = put(proj, "a.md", "# Título\nação simples\n".encode())
    cp = hc(proj, ["edit", "a.md"], block("ação simples\n", "ação composta — ✓\n"))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == "# Título\nação composta — ✓\n".encode()


def test_line_matches_whole_lines_only(proj: Path) -> None:
    """`x = 1` não pode casar no meio de `xx = 1`: o casamento é por linha inteira."""
    f = put(proj, "a.py", b"xx = 1\nx = 1\n")
    cp = hc(proj, ["edit", "a.py"], block("x = 1\n", "x = 2\n"))
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"xx = 1\nx = 2\n"


def test_longer_markers_allow_equals_line_in_text(proj: Path) -> None:
    f = put(proj, "a.rst", b"Title\n=======\nbody\n")
    cp = hc(
        proj, ["edit", "a.rst"], block("Title\n=======\n", "Novo\n=====\n", marker=8)
    )
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"Novo\n=====\nbody\n"


def test_multiple_blocks_in_one_call(proj: Path) -> None:
    f = put(proj, "a.py", b"a\nb\nc\nd\n")
    cp = hc(proj, ["edit", "a.py"], block("a\n", "A\n") + "\n" + block("d\n", "D\nE\n"))
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.startswith("OK a.py: 2 blocks: 1: L1 (-1 +1); 2: L4 (-1 +2)")
    assert f.read_bytes() == b"A\nb\nc\nD\nE\n"


# ---------------------------------------------------------------- edit: falhas não gravam nada


def test_not_found_reports_closest_and_writes_nothing(proj: Path) -> None:
    original = b"def f(a, b):\n    return a + b\n"
    f = put(proj, "a.py", original)
    cp = hc(proj, ["edit", "a.py"], block("def f(a, b):\n    return a - b\n", "pass\n"))
    assert cp.returncode == 1
    assert "not found" in cp.stderr
    assert "Closest at L1-2" in cp.stderr
    assert "nothing was written" in cp.stderr
    assert f.read_bytes() == original


def test_ambiguous_match_lists_lines_and_all_replaces_every_one(proj: Path) -> None:
    f = put(proj, "a.py", b"x = 1\nfoo\nx = 1\n")
    cp = hc(proj, ["edit", "a.py"], block("x = 1\n", "x = 2\n"))
    assert cp.returncode == 1
    assert "matches 2 places (L1, L3)" in cp.stderr
    assert f.read_bytes() == b"x = 1\nfoo\nx = 1\n"
    cp = hc(proj, ["edit", "a.py", "--all"], block("x = 1\n", "x = 2\n"))
    assert cp.returncode == 0, cp.stderr
    assert "x2" in cp.stdout
    assert f.read_bytes() == b"x = 2\nfoo\nx = 2\n"


def test_second_block_failing_leaves_file_untouched(proj: Path) -> None:
    original = b"a\nb\n"
    f = put(proj, "a.py", original)
    cp = hc(proj, ["edit", "a.py"], block("a\n", "A\n") + block("zzz\n", "Z\n"))
    assert cp.returncode == 1
    assert "block 2" in cp.stderr
    assert f.read_bytes() == original


def test_noop_is_rejected(proj: Path) -> None:
    f = put(proj, "a.py", b"a\n")
    cp = hc(proj, ["edit", "a.py"], block("a\n", "a\n"))
    assert cp.returncode == 1
    assert "identical" in cp.stderr
    assert f.read_bytes() == b"a\n"


def test_missing_file_points_to_write(proj: Path) -> None:
    cp = hc(proj, ["edit", "nope.py"], block("a\n", "b\n"))
    assert cp.returncode == 1
    assert "hc write" in cp.stderr


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "texto solto\n",
        "<<<<<<< SEARCH\na\n=======\nb\n",
        "<<<<<<< SEARCH\na\nb\n>>>>>>> REPLACE\n",
    ],
)
def test_malformed_stdin(proj: Path, stdin: str) -> None:
    f = put(proj, "a.py", b"a\n")
    cp = hc(proj, ["edit", "a.py"], stdin)
    assert cp.returncode == 1
    assert f.read_bytes() == b"a\n"


def test_empty_search_is_rejected(proj: Path) -> None:
    put(proj, "a.py", b"a\n")
    cp = hc(proj, ["edit", "a.py"], block("", "x\n"))
    assert cp.returncode == 1
    assert "empty SEARCH" in cp.stderr


def test_binary_and_non_utf8_are_refused(proj: Path) -> None:
    put(proj, "b.bin", b"\x00\x01\x02")
    put(proj, "l.txt", b"caf\xe9\n")
    assert hc(proj, ["edit", "b.bin"], block("a\n", "b\n")).returncode == 1
    assert hc(proj, ["edit", "l.txt"], block("a\n", "b\n")).returncode == 1


def test_usage_errors_exit_2(proj: Path) -> None:
    assert hc(proj, ["edit"]).returncode == 2
    assert hc(proj, ["write"]).returncode == 2


# ---------------------------------------------------------------- limites de segurança


@pytest.mark.parametrize(
    "target", ["../outside.py", ".claude/settings.json", ".git/config", "../../etc/x"]
)
def test_off_limits_paths_are_refused(proj: Path, target: str) -> None:
    (proj / ".claude").mkdir(exist_ok=True)
    (proj / ".claude/settings.json").write_text("{}")
    (proj / ".git/config").write_text("[core]\n")
    (proj.parent / "outside.py").write_text("a\n")
    cp = hc(proj, ["edit", target], block("a\n", "b\n"))
    assert cp.returncode == 1
    assert "outside the project root" in cp.stderr or "off limits" in cp.stderr
    assert (proj.parent / "outside.py").read_text() == "a\n"
    cp = hc(proj, ["write", target, "--force"], "x\n")
    assert cp.returncode == 1


# ---------------------------------------------------------------- write


def test_stdin_with_doubled_cr_is_normalized() -> None:
    """Windows pode entregar `\\r\\r\\n` (dupla tradução de fim de linha): vira um LF só."""
    import io
    import sys

    from hc_harness.edit import read_stdin

    class FakeStdin:
        buffer = io.BytesIO(b"a\r\r\nb\r\nc\n")

        def isatty(self) -> bool:
            return False

    real = sys.stdin
    sys.stdin = FakeStdin()  # type: ignore[assignment]
    try:
        assert read_stdin() == "a\nb\nc\n"
    finally:
        sys.stdin = real


def test_write_creates_file_and_parents_with_lf_and_final_newline(proj: Path) -> None:
    cp = hc(proj, ["write", "pkg/sub/new.py"], "x = 1\r\ny = 2")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout == "OK wrote pkg/sub/new.py (2 lines)\n"
    assert (proj / "pkg/sub/new.py").read_bytes() == b"x = 1\ny = 2\n"


def test_write_refuses_to_overwrite_without_force(proj: Path) -> None:
    f = put(proj, "a.py", b"keep\n")
    cp = hc(proj, ["write", "a.py"], "new\n")
    assert cp.returncode == 1
    assert "already exists" in cp.stderr
    assert f.read_bytes() == b"keep\n"


def test_write_force_keeps_crlf_and_bom_of_existing_file(proj: Path) -> None:
    f = put(proj, "a.py", b"\xef\xbb\xbfold\r\nlines\r\n")
    cp = hc(proj, ["write", "a.py", "--force"], "new\nfile\n")
    assert cp.returncode == 0, cp.stderr
    assert f.read_bytes() == b"\xef\xbb\xbfnew\r\nfile\r\n"


def test_write_refuses_empty_content(proj: Path) -> None:
    cp = hc(proj, ["write", "a.py"], "  \n")
    assert cp.returncode == 1
    assert not (proj / "a.py").exists()


# ---------------------------------------------------------------- parser (unidade)


def test_parse_blocks_unit() -> None:
    assert parse_blocks(block("a\nb\n", "c\n")) == [("a\nb\n", "c\n")]
    assert parse_blocks(block("a\n", "") + "\n\n" + block("b\n", "c\n")) == [
        ("a\n", ""),
        ("b\n", "c\n"),
    ]
    with pytest.raises(EditError):
        parse_blocks("")
    with pytest.raises(EditError):
        parse_blocks("lixo\n" + block("a\n", "b\n"))
