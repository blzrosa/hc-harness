"""Linha de comando do hc: despacha cada subcomando importando só o módulo de que precisa."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

KNOWN_FLAGS: Final[frozenset[str]] = frozenset({
    "--all", "--no-cache", "--no-fix", "--force", "--list", "-v", "--verbose", "-h", "--help", "--version",
})  # fmt: skip
VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {"--page", "--limit", "--prefix", "--sym"}
)


def split_args(args: list[str]) -> tuple[set[str], dict[str, str], list[str]]:
    """Separa flags booleanas, opções `--nome=valor` e posicionais. Opção de valor sem `=` vira flag inválida."""
    flags: set[str] = set()
    opts: dict[str, str] = {}
    positional: list[str] = []
    for a in args:
        name, eq, value = a.partition("=")
        if eq and name in VALUE_FLAGS:
            opts[name] = value
        elif a in VALUE_FLAGS:
            flags.add(f"{a} (needs a value: {a}=...)")
        elif a.startswith("-"):
            flags.add(a)
        else:
            positional.append(a)
    return flags, opts, positional


def print_help() -> None:
    help_text = """hc - Polyglot AST Harness & Token Compressor
Usage:
  hc                     Incremental check (ruff + pyright/ty + AST-affected pytest/ctest from git diff)
  hc --all               Force full project typecheck & full test suite
  hc <file1> [file2...]  Simulate changes on specific files and run their affected tests
  hc map [path]          Extract AST skeleton (classes, signatures, line numbers), alphabetical, paged
  hc impact [file...]    Show AST reverse dependency graph & affected tests
  hc find <symbol>       Definitions (file:lines + signature) and uses of a symbol (capped)
  hc show <file>:<sym>   Print only that symbol's body; also <file>:L10-40, or just <symbol>
  hc edit <file> [--all] Edit by SEARCH/REPLACE blocks read from stdin (CRLF/BOM safe, all-or-nothing)
  hc write <file>        Create a file from stdin (refuses to overwrite without --force)
  hc guard               PreToolUse hook: reads JSON on stdin; blocks git commit/push, token-heavy
                         reads (sed -n / cat on source, lockfiles) and file writes through the shell

Options:
  --no-cache             Ignore the "last OK" cache and run everything
  --no-fix               Do not auto-fix / format (ruff check only)
  --all                  With `edit`: replace every match of each SEARCH block (default: must be unique)
  --force                With `write`: overwrite an existing file
  --list                 With `map`: one line per file (path + top-level symbol count)
  --prefix=P             With `map`: only files whose path (relative to root) starts with P
  --sym=S                With `map`: only top-level symbols whose name starts with S
  --limit=N --page=K     With `map`: page size in lines (default 150) and page number (default 1)
  -v, --verbose          Print per-stage timings to stderr
  --version              Print version

hc edit format (whole lines; several blocks per call):
  hc edit src/x.py <<'EOF'
  <<<<<<< SEARCH
  old lines
  =======
  new lines (empty = delete the old lines)
  >>>>>>> REPLACE
  EOF
  If the text has a line `=======`, use longer markers (8+ `<`, same number of `=` and `>`).

Env:
  HC_TYPECHECKER=ty|pyright   Force a type checker (default: pyright, fallback ty)
  HC_PLAIN=1                  Disable the live progress line even in a terminal
  HC_GUARD_BLOCK=commit,push  Git subcommands `hc guard` blocks (default: commit,push)
  HC_GUARD_RULES=write,read,lockfile   Extra `hc guard` rule groups that are on (default: all; git is always on)

Live progress goes to stderr and only appears in an interactive terminal,
so agents (no TTY) only ever see the final "OK in ..." line or the failures.
"""
    sys.stdout.write(help_text)


def main() -> None:
    args = sys.argv[1:]
    flags, opts, positional = split_args(args)
    cmd = positional[0] if positional else ""

    # Caminho rápido: o hook roda a cada chamada de Bash, então só carrega o módulo do guard.
    if (
        cmd == "guard"
        and not (flags - KNOWN_FLAGS)
        and not (flags & {"-h", "--help", "--version"})
    ):
        from .guard import run_guard

        sys.exit(run_guard())

    from .ui import setup_stdio

    setup_stdio()

    unknown = flags - KNOWN_FLAGS
    if unknown:
        sys.stderr.write(f"hc: unknown option(s): {', '.join(sorted(unknown))}\n")
        print_help()
        sys.exit(2)

    if flags & {"-h", "--help"}:
        print_help()
        sys.exit(0)

    if "--version" in flags:
        try:
            from importlib.metadata import version

            sys.stdout.write(f"hc {version('hc-harness')}\n")
        except Exception:  # noqa: BLE001 - metadata ausente em execução "solta"
            sys.stdout.write("hc (unknown version)\n")
        sys.exit(0)

    from .gitutil import find_root, resolve_paths

    cwd = Path.cwd()
    root = find_root(cwd).resolve()

    if cmd == "map":
        from .mapview import cmd_map, parse_map_options

        try:
            map_options = parse_map_options(opts, "--list" in flags)
        except ValueError as exc:
            sys.stderr.write(f"hc: {exc}\n")
            sys.exit(2)
        sys.exit(cmd_map(root, cwd, positional[1:], map_options))

    if cmd == "impact":
        from .index import cmd_impact

        sys.exit(cmd_impact(root, cwd, positional[1:]))

    if cmd == "find":
        from .navigate import cmd_find

        sys.exit(cmd_find(root, positional[1:]))

    if cmd == "show":
        from .navigate import cmd_show

        sys.exit(cmd_show(root, cwd, positional[1:]))

    if cmd == "edit":
        from .edit import cmd_edit

        sys.exit(cmd_edit(root, cwd, positional[1:], replace_all="--all" in flags))

    if cmd == "write":
        from .edit import cmd_write

        sys.exit(cmd_write(root, cwd, positional[1:], force="--force" in flags))

    from .pipeline import run_pipeline

    file_args = resolve_paths(cwd, positional)
    try:
        code = run_pipeline(
            root,
            force_all="--all" in flags,
            explicit_files=file_args or None,
            use_cache="--no-cache" not in flags,
            fix="--no-fix" not in flags,
            verbose=bool(flags & {"-v", "--verbose"}),
        )
    except KeyboardInterrupt:
        sys.stderr.write("\nhc: interrupted\n")
        code = 130
    sys.exit(code)
