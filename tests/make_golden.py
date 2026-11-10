"""Gera os arquivos golden a partir de uma implementação de referência do hc.

Uso (a partir da raiz do repo):
    python tests/make_golden.py -- python caminho/para/hc.py
    python tests/make_golden.py -- python -m hc_harness        # (com PYTHONPATH=src)

Só rode isto quando quiser MUDAR o comportamento de propósito.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture import CASES, GUARD_COMMANDS, build_project, render, run_hc

GOLD = Path(__file__).resolve().parent / "golden"


def main() -> None:
    if "--" not in sys.argv:
        sys.exit(__doc__)
    prefix = sys.argv[sys.argv.index("--") + 1 :]
    GOLD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp, "proj")
        home = Path(tmp, "home")
        root.mkdir()
        home.mkdir()
        build_project(root)
        for name, args in CASES.items():
            cp = run_hc(prefix, args, root, home)
            (GOLD / f"{name}.txt").write_text(
                render(cp, root), encoding="utf-8", newline="\n"
            )
        guard: dict[str, int] = {}
        for cmd in GUARD_COMMANDS:
            cp = run_hc(
                prefix,
                ["guard"],
                root,
                home,
                stdin=json.dumps({"tool_input": {"command": cmd}}),
            )
            guard[cmd] = cp.returncode
        (GOLD / "guard_cases.json").write_text(
            json.dumps(guard, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(
        f"golden gravado em {GOLD} ({len(CASES)} casos + {len(GUARD_COMMANDS)} comandos de guard)"
    )


if __name__ == "__main__":
    main()
