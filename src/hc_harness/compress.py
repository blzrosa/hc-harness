"""Compressão determinística da saída das ferramentas (+ Headroom opcional) e log do dataset."""

from __future__ import annotations

import importlib
import json
import time

from .config import ANSI_ESCAPE_RE, MAX_OUT_CHARS, SESSION_HEADER_RE, state_file


def _apply_headroom_sdk(text: str) -> str:
    try:
        headroom = importlib.import_module("headroom")
    except ImportError:
        return text

    compress_fn = getattr(headroom, "compress_text", None) or getattr(
        headroom, "compress", None
    )
    if callable(compress_fn):
        try:
            res = compress_fn(text)
            if isinstance(res, str) and res.strip():
                return res.strip()
            text_attr = getattr(res, "text", None)
            if isinstance(text_attr, str) and text_attr.strip():
                return text_attr.strip()
        except (ValueError, RuntimeError, TypeError):
            return text
    return text


def _cap_output(text: str, max_chars: int = MAX_OUT_CHARS) -> str:
    """Teto de tokens: mantém começo e fim (onde ficam causa e resumo) e omite o miolo."""
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    head: list[str] = []
    tail: list[str] = []
    used = 0
    lo, hi = 0, len(lines) - 1
    while lo <= hi and used < max_chars:
        head.append(lines[lo])
        used += len(lines[lo]) + 1
        lo += 1
        if lo <= hi and used < max_chars:
            tail.append(lines[hi])
            used += len(lines[hi]) + 1
            hi -= 1
    omitted = max(0, hi - lo + 1)
    return "\n".join(
        [*head, f"... [{omitted} lines omitted by hc] ...", *reversed(tail)]
    )


def compress_and_log(stage: str, raw_output: str) -> str:
    clean_raw = ANSI_ESCAPE_RE.sub("", raw_output).strip()
    if not clean_raw:
        return ""

    filtered_lines: list[str] = []
    seen_lines: set[str] = set()

    for line in clean_raw.splitlines():
        if line.startswith(
            (
                "platform ",
                "rootdir:",
                "configfile:",
                "plugins:",
                "collected ",
                "testpaths:",
            )
        ):
            continue
        if SESSION_HEADER_RE.match(line):
            continue
        if "In instantiation of" in line or "required from here" in line:
            continue
        stripped = line.strip()
        if stripped.startswith(("note:", "info:", "help:")) and stripped in seen_lines:
            continue
        if stripped:
            seen_lines.add(stripped)
        filtered_lines.append(line)

    pre_filtered = "\n".join(filtered_lines)
    compressed = _cap_output(_apply_headroom_sdk(pre_filtered))

    record = {
        "ts": int(time.time()),
        "task": f"compress_{stage}",
        "raw_chars": len(clean_raw),
        "compressed_chars": len(compressed),
        "raw": clean_raw,
        "compressed": compressed,
    }
    try:
        with state_file("laya_dataset.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    return compressed
