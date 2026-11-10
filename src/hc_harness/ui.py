"""Saída para humanos: formatação de tempo, stdio UTF-8 e a linha de progresso (stderr, só em TTY)."""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final


def format_duration(ns: int) -> str:
    """Formata nanossegundos automaticamente para us, ms, s ou min."""
    us = ns / 1_000
    if us < 1_000:
        return f"{us:.1f} us"
    ms = us / 1_000
    if ms < 1_000:
        return f"{ms:.1f} ms"
    sec = ms / 1_000
    if sec < 60:
        return f"{sec:.2f} s"
    minutes = int(sec // 60)
    rem_sec = sec % 60
    return f"{minutes}m {rem_sec:.1f}s"


def setup_stdio() -> None:
    """UTF-8 no stdout/stderr (Windows usa cp1252 por padrão) e ANSI habilitado no console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-12)  # STD_ERROR_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(
                    handle, mode.value | 0x0004
                )  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except (OSError, AttributeError):
            pass


def is_interactive() -> bool:
    return (
        sys.stderr.isatty()
        and os.environ.get("TERM") != "dumb"
        and not os.environ.get("HC_PLAIN")
        and not os.environ.get("CI")
    )


class Progress:
    """Mostra a(s) etapa(s) em execução numa única linha transitória (estilo `uv sync`)."""

    _FRAMES: Final[str] = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._active: dict[str, float] = {}
        self._timings: list[tuple[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = False
        if enabled:
            atexit.register(self.stop)

    def _start_thread(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        sys.stderr.write("\x1b[?25l")  # esconde cursor
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        i = 0
        while not self._stop.wait(0.08):
            with self._lock:
                if self._paused or not self._active:
                    continue
                width = shutil.get_terminal_size((100, 20)).columns
                earliest = min(self._active.values())
                names = " + ".join(self._active)
                frame = self._FRAMES[i % len(self._FRAMES)]
                line = f"{frame} {names}… {time.perf_counter() - earliest:.1f}s"
                sys.stderr.write(f"\r\x1b[2K{line[: width - 1]}")
                sys.stderr.flush()
            i += 1

    @contextmanager
    def stage(self, label: str) -> Iterator[None]:
        start = time.perf_counter()
        with self._lock:
            self._active[label] = start
        self._start_thread()
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(label, None)
                self._timings.append((label, time.perf_counter() - start))
                if self.enabled and not self._active:
                    sys.stderr.write("\r\x1b[2K")
                    sys.stderr.flush()

    @contextmanager
    def pause(self) -> Iterator[None]:
        """Suspende o spinner (ex.: para deixar o `uv sync` desenhar o próprio progresso)."""
        with self._lock:
            self._paused = True
            if self.enabled:
                sys.stderr.write("\r\x1b[2K\x1b[?25h")
                sys.stderr.flush()
        try:
            yield
        finally:
            with self._lock:
                self._paused = False
                if self.enabled:
                    sys.stderr.write("\x1b[?25l")

    def stop(self) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1)
            self._thread = None
        if self.enabled:
            sys.stderr.write("\r\x1b[2K\x1b[?25h")
            sys.stderr.flush()

    def summary(self) -> str:
        return " · ".join(
            f"{name} {dur * 1000:.0f} ms" if dur < 1 else f"{name} {dur:.2f} s"
            for name, dur in self._timings
        )
