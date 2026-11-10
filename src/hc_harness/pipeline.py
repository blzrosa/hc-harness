"""O `hc` sem subcomando: git diff -> impacto -> ruff -> (typecheck || pytest), com cache de "último OK"."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    ALL_C_CPP_EXTS,
    CONFIG_FILES,
    PYTEST_OK_CODES,
    VALID_EXTS,
    get_proj_id,
    state_file,
)
from .gitutil import LAST_GIT_ERROR, get_git_changed_files
from .index import build_index, get_affected_targets
from .runner import (
    check_uv_sync,
    find_tool,
    fit_args,
    run_cmd,
    run_stage,
    venv_bin_dir,
)
from .ui import Progress, format_duration, is_interactive


@dataclass(slots=True)
class Outcome:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    fatal: bool = False


def _count(n: int) -> str:
    return f"{n} arquivo" if n == 1 else f"{n} arquivos"


def _compute_state_hash(
    root: Path, files: list[Path], *, extra_tag: str = "", stat_only: bool = False
) -> str:
    """Hash de (config + arquivos). stat_only=True usa (mtime,size) — p/ varrer o projeto todo em --all."""
    hasher = hashlib.sha256(extra_tag.encode("utf-8"))
    for name in sorted(CONFIG_FILES):
        cfg = root / name
        if cfg.is_file():
            hasher.update(name.encode("utf-8"))
            hasher.update(cfg.read_bytes())

    for p in sorted(files):
        try:
            hasher.update(p.relative_to(root).as_posix().encode("utf-8"))
            if stat_only:
                st = p.stat()
                hasher.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
            else:
                hasher.update(p.read_bytes())
        except OSError:
            continue
    return hasher.hexdigest()


def run_cpp_pipeline(
    root: Path,
    changed_cpp: list[Path],
    cpp_test_targets: list[str],
    progress: Progress,
    skipped: list[str],
) -> list[str]:
    errors: list[str] = []

    if changed_cpp:
        if shutil.which("clang-format"):
            with progress.stage(f"clang-format ({_count(len(changed_cpp))})"):
                run_cmd(
                    [
                        "clang-format",
                        "-i",
                        *fit_args([str(p) for p in changed_cpp], []),
                    ],
                    root,
                )
        else:
            skipped.append("clang-format")

    build_dir = next(
        (
            root / d
            for d in ("build", "cmake-build-release", "cmake-build-debug")
            if (root / d / "CMakeCache.txt").exists()
        ),
        None,
    )
    if build_dir is None:
        return errors
    if not shutil.which("cmake"):
        skipped.append("cmake")
        return errors

    err = run_stage(
        progress, "cmake build", ["cmake", "--build", str(build_dir), "--parallel"], root,
        title="C/C++ BUILD", log_key="cpp_build",
    )  # fmt: skip
    if err:
        return [err]

    if cpp_test_targets:
        if shutil.which("ctest"):
            regex = "|".join(cpp_test_targets)
            err = run_stage(
                progress, f"ctest ({len(cpp_test_targets)})",
                ["ctest", "--test-dir", str(build_dir), "-R", regex, "--output-on-failure"], root,
                title=f"CTEST ({regex})", log_key="ctest",
            )  # fmt: skip
            if err:
                errors.append(err)
        else:
            skipped.append("ctest")

    return errors


def pick_typechecker(root: Path) -> tuple[str, list[str]] | None:
    """pyright por padrão; ty como fallback. Force com HC_TYPECHECKER=ty|pyright."""
    preferred = os.environ.get("HC_TYPECHECKER", "").lower()
    order = [preferred] if preferred in ("ty", "pyright") else ["pyright", "ty"]
    for name in order:
        exe = find_tool(name, root)
        if exe is None:
            continue
        if name == "ty":
            return name, [exe, "check", "--output-format", "concise"]
        cmd = [exe]
        bin_dir = venv_bin_dir(root)
        venv_py = next(
            (
                bin_dir / n
                for n in ("python.exe", "python")
                if bin_dir and (bin_dir / n).is_file()
            ),
            None,
        )
        if venv_py is not None:
            cmd += ["--pythonpath", str(venv_py)]
        return name, cmd
    return None


def run_pipeline(
    root: Path,
    *,
    force_all: bool = False,
    explicit_files: list[Path] | None = None,
    use_cache: bool = True,
    fix: bool = True,
    verbose: bool = False,
) -> int:
    t0 = time.perf_counter_ns()
    progress = Progress(is_interactive())
    try:
        outcome = _pipeline(
            root,
            progress,
            force_all=force_all,
            explicit_files=explicit_files,
            use_cache=use_cache,
            fix=fix,
        )
    finally:
        progress.stop()

    if (progress.enabled or verbose) and not outcome.fatal:
        timings = progress.summary()
        if timings:
            sys.stderr.write(f"  {timings}\n")

    if outcome.errors:
        sys.stdout.write("\n\n".join(outcome.errors) + "\n")
        return 2 if outcome.fatal else 1

    notes = list(outcome.notes)
    if outcome.skipped:
        notes.append(f"skipped: {', '.join(sorted(set(outcome.skipped)))}")
    suffix = f" ({', '.join(notes)})" if notes else ""
    sys.stdout.write(f"OK in {format_duration(time.perf_counter_ns() - t0)}{suffix}\n")
    return 0


def _pipeline(
    root: Path,
    progress: Progress,
    *,
    force_all: bool,
    explicit_files: list[Path] | None,
    use_cache: bool,
    fix: bool,
) -> Outcome:
    outcome = Outcome()

    with progress.stage("git status"):
        changed_all = (
            explicit_files
            if explicit_files is not None
            else get_git_changed_files(root)
        )
    if changed_all is None:
        if not force_all:
            reason = LAST_GIT_ERROR[0] if LAST_GIT_ERROR else "unknown error"
            outcome.errors.append(
                f"hc: could not read git status in {root}\n  git: {reason}\n"
                "  Run `git init` (or fix the error above), use `hc --all`, or pass files explicitly."
            )
            outcome.fatal = True
            return outcome
        changed_all = []  # --all sem git: varre o projeto inteiro (os.walk com poda)

    changed_files = [p for p in changed_all if p.suffix.lower() in VALID_EXTS]
    config_changed = any(p.name in CONFIG_FILES for p in changed_all)

    # Atalho 1: nada mudou -> não roda nada.
    if not force_all and not changed_files and not config_changed:
        outcome.notes.append("clean tree")
        return outcome

    with progress.stage("analisando impacto"):
        index = build_index(root)
        impact = get_affected_targets(root, changed_files, index)

    if force_all:
        touched = sorted(index)
    else:
        touched = sorted(set(changed_files) | set(impact.py_affected))
    tag = f"all={force_all}"

    # Atalho 2: mesmo conteúdo do último OK -> retorna sem rodar nada.
    run_cache_file = state_file(f"last_ok_{get_proj_id(root)}.hash")
    with progress.stage("verificando cache"):
        pre_hash = _compute_state_hash(
            root, touched, extra_tag=tag, stat_only=force_all
        )
    if (
        use_cache
        and run_cache_file.exists()
        and run_cache_file.read_text(encoding="utf-8").strip() == pre_hash
    ):
        outcome.notes.append("cached")
        return outcome

    changed_cpp = [p for p in changed_files if p.suffix.lower() in ALL_C_CPP_EXTS]
    if impact.needs_cpp_build:
        outcome.errors.extend(
            run_cpp_pipeline(
                root, changed_cpp, impact.cpp_tests, progress, outcome.skipped
            )
        )
        if outcome.errors:
            return outcome

    has_py = any(p.suffix.lower() == ".py" for p in changed_files)
    if (root / "pyproject.toml").exists() or has_py:
        uv_err = check_uv_sync(
            root,
            progress,
            force_rebuild=(impact.needs_cpp_build and not (root / "build").exists()),
        )
        if uv_err:
            outcome.errors.append(uv_err)
            return outcome

    py_changed = [p for p in changed_files if p.suffix.lower() == ".py"]

    # 1. Ruff (SEQUENCIAL: modifica arquivos, então precisa terminar antes de checar tipos/testes).
    if force_all or py_changed:
        ruff = find_tool("ruff", root)
        if ruff is None:
            outcome.skipped.append("ruff")
        else:
            targets = (
                ["."]
                if force_all
                else fit_args([str(p.relative_to(root)) for p in py_changed], ["."])
            )
            n = "projeto" if targets == ["."] else _count(len(targets))
            if fix:
                with progress.stage(f"ruff fix ({n})"):
                    r_code, _ = run_cmd(
                        [
                            ruff,
                            "check",
                            "--fix",
                            "--unsafe-fixes",
                            "--quiet",
                            "--output-format=concise",
                            *targets,
                        ],
                        root,
                    )
                with progress.stage(f"ruff format ({n})"):
                    run_cmd([ruff, "format", "--quiet", *targets], root)
                if (
                    r_code != 0
                ):  # re-checa só quando sobrou algo (o format pode ter resolvido)
                    err = run_stage(
                        progress, "ruff check", [ruff, "check", "--quiet", "--output-format=concise", *targets], root,
                        title="RUFF", log_key="ruff",
                    )  # fmt: skip
                    if err:
                        outcome.errors.append(err)
            else:
                err = run_stage(
                    progress, f"ruff check ({n})", [ruff, "check", "--quiet", "--output-format=concise", *targets],
                    root, title="RUFF", log_key="ruff",
                )  # fmt: skip
                if err:
                    outcome.errors.append(err)

    # 2. Typecheck e Pytest são somente-leitura e independentes -> rodam EM PARALELO.
    def typecheck_job() -> str | None:
        py_targets = [
            str(p.relative_to(root))
            for p in impact.py_affected
            if p.suffix.lower() == ".py"
        ]
        if not force_all and not py_targets:
            return None
        checker = pick_typechecker(root)
        if checker is None:
            outcome.skipped.append("typecheck")
            return None
        name, base = checker
        args = [] if force_all else fit_args(py_targets, [])
        n = "projeto" if not args else _count(len(args))
        return run_stage(
            progress,
            f"{name} ({n})",
            [*base, *args],
            root,
            title=name.upper(),
            log_key=name,
        )

    def pytest_job() -> str | None:
        test_targets = ["."] if force_all else impact.py_tests
        if not test_targets:
            return None
        pytest = find_tool("pytest", root)
        if pytest is None:
            outcome.skipped.append("pytest")
            return None
        args = fit_args(test_targets, ["."])
        n = "tudo" if args == ["."] else _count(len(args))
        # -rfE: resumo só de falhas/erros (o `-ra` antigo listava skips/xfails = tokens à toa)
        cmd = [pytest, "-q", "--tb=short", "-rfE", "--no-header", "--color=no", *args]
        return run_stage(
            progress, f"pytest ({n})", cmd, root, title=f"PYTEST ({', '.join(test_targets)})", log_key="pytest",
            ok_codes=PYTEST_OK_CODES,
        )  # fmt: skip

    jobs: list[Callable[[], str | None]] = [typecheck_job, pytest_job]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(job) for job in jobs]
        for fut in futures:  # ordem estável de saída: typecheck, depois pytest
            err = fut.result()
            if err:
                outcome.errors.append(err)

    if outcome.errors:
        return outcome

    # Recalcula pós-Ruff/clang-format (podem ter alterado bytes) e grava o cache de OK.
    try:
        run_cache_file.write_text(
            _compute_state_hash(root, touched, extra_tag=tag, stat_only=force_all),
            encoding="utf-8",
        )
    except OSError:
        pass
    return outcome
