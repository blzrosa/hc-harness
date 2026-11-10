"""Onde foram os tokens das sessões do Claude Code (~/.claude/projects/**/*.jsonl).

Uso:
    python tools/session_cost.py <arquivo.jsonl | pasta> [...]   (pasta = só *.jsonl dela)
    python tools/session_cost.py <pasta> --tools                  (acrescenta tabela por ferramenta)

Mostra, por sessão: turnos, contexto (1º / médio / máx, em tokens), quantos "cache miss" houve
(contexto reescrito do zero depois de uma pausa) e quantos tokens isso custou, pausas longas,
custo exato (linha `cost-state`) e chamadas de subagente (Agent/Task). Só biblioteca padrão.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

SUBAGENT_TOOLS = frozenset({"Agent", "Task"})
MIN_MISS_CONTEXT = (
    20_000  # abaixo disso o "miss" é só a primeira carga / não vale a pena contar
)
PAUSE_MIN = 5.0  # TTL padrão do cache de prompt (minutos)
LONG_PAUSE_MIN = 60.0


@dataclass
class Turn:
    ts: datetime | None
    context: int  # input + cache_read + cache_creation
    cache_read: int
    cache_write: int
    output: int
    model: str


@dataclass
class Session:
    name: str
    turns: list[Turn] = field(default_factory=list)
    cost: float | None = None
    models: dict[str, float] = field(default_factory=dict)
    tool_calls: Counter[str] = field(default_factory=Counter)
    tool_in: Counter[str] = field(default_factory=Counter)  # caracteres escritos
    tool_out: Counter[str] = field(default_factory=Counter)  # caracteres devolvidos
    subagents: Counter[str] = field(default_factory=Counter)  # por subagent_type
    sidechain_lines: int = 0
    misses: int = 0
    miss_tokens: int = 0
    pauses: int = 0
    long_pauses: int = 0


def text_len(x: Any) -> int:
    if isinstance(x, str):
        return len(x)
    if isinstance(x, list):
        return sum(text_len(i.get("text", "") if isinstance(i, dict) else i) for i in x)
    return 0


def parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _turn(usage: dict[str, Any], ts: datetime | None, model: str) -> Turn:
    read = usage.get("cache_read_input_tokens") or 0
    write = usage.get("cache_creation_input_tokens") or 0
    fresh = usage.get("input_tokens") or 0
    return Turn(
        ts, fresh + read + write, read, write, usage.get("output_tokens") or 0, model
    )


def analyze_turns(s: Session) -> None:
    prev: Turn | None = None
    for t in s.turns:
        if prev is not None and prev.ts and t.ts:
            gap = (t.ts - prev.ts).total_seconds() / 60
            s.pauses += gap > PAUSE_MIN
            s.long_pauses += gap > LONG_PAUSE_MIN
        if (
            prev is not None
            and prev.context >= MIN_MISS_CONTEXT
            and t.cache_read < prev.context * 0.5
        ):
            s.misses += 1
            s.miss_tokens += t.cache_write
        prev = t


def scan(path: Path) -> Session:
    s = Session(name=path.stem[:8])
    seen_tools: dict[str, str] = {}
    seen_msgs: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("isSidechain"):
            s.sidechain_lines += 1
        if d.get("type") == "cost-state":
            s.cost = d.get("totalCostUSD", s.cost)
            usage = d.get("modelUsage")
            if isinstance(usage, dict):
                s.models = {
                    m: float(v.get("costUSD", 0) or 0)
                    for m, v in usage.items()
                    if isinstance(v, dict)
                }
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if (
            d.get("type") == "assistant"
            and m.get("usage")
            and mid
            and mid not in seen_msgs
        ):
            seen_msgs.add(mid)  # a mesma msg aparece 1x por bloco de conteúdo
            s.turns.append(
                _turn(
                    m["usage"], parse_ts(d.get("timestamp")), str(m.get("model", "?"))
                )
            )
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("id") not in seen_tools:
                name = str(b.get("name", "?"))
                seen_tools[b["id"]] = name
                s.tool_calls[name] += 1
                s.tool_in[name] += len(
                    json.dumps(b.get("input", {}), ensure_ascii=False)
                )
                if name in SUBAGENT_TOOLS:
                    inp = b.get("input") or {}
                    s.subagents[
                        str(inp.get("subagent_type", "?"))
                        if isinstance(inp, dict)
                        else "?"
                    ] += 1
            elif b.get("type") == "tool_result":
                s.tool_out[seen_tools.get(str(b.get("tool_use_id")), "?")] += text_len(
                    b.get("content")
                )
    analyze_turns(s)
    return s


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for a in paths:
        p = Path(a)
        if p.is_dir():
            files += sorted(p.glob("*.jsonl"))
        elif p.is_file():
            files.append(p)
    return files


def k(n: float) -> str:
    return f"{n / 1000:.0f}k"


def render(sessions: list[Session], with_tools: bool = False) -> str:
    out: list[str] = []
    head = f"{'sessão':9}{'US$':>7}{'turnos':>7}{'ctx 1º':>8}{'médio':>7}{'máx':>7}{'miss':>5}{'reescrito':>10}{'pausas>5m':>10}{'>1h':>5}{'agentes':>8}"
    out.append(head)
    for s in sorted(sessions, key=lambda x: -(x.cost or 0)):
        n = len(s.turns)
        ctx = [t.context for t in s.turns] or [0]
        cost = f"{s.cost:.2f}" if s.cost is not None else "?"
        out.append(
            f"{s.name:9}{cost:>7}{n:>7}{k(ctx[0]):>8}{k(sum(ctx) / len(ctx)):>7}{k(max(ctx)):>7}"
            f"{s.misses:>5}{k(s.miss_tokens):>10}{s.pauses:>10}{s.long_pauses:>5}{sum(s.subagents.values()):>8}"
        )
    total = sum(s.cost or 0 for s in sessions)
    lost = sum(s.miss_tokens for s in sessions)
    out.append(
        f"\n{len(sessions)} sessão(ões), US$ {total:.2f}; cache miss reescreveu ~{k(lost)} tokens no total"
    )
    models: Counter[str] = Counter()
    for s in sessions:
        for name, c in s.models.items():
            models[name] += c  # type: ignore[assignment]
    if models:
        out.append(
            "custo por modelo: "
            + ", ".join(f"{m} US$ {c:.2f}" for m, c in models.most_common())
        )
    agents: Counter[str] = Counter()
    sidechain = 0
    for s in sessions:
        agents += s.subagents
        sidechain += s.sidechain_lines
    if agents or sidechain:
        out.append(f"subagentes: {dict(agents)}; linhas de sidechain: {sidechain}")
    else:
        out.append(
            "subagentes: NENHUMA chamada (sem tool_use Agent/Task e sem linhas isSidechain) nas sessões lidas"
        )
    if with_tools:
        calls: Counter[str] = Counter()
        tin: Counter[str] = Counter()
        tout: Counter[str] = Counter()
        for s in sessions:
            calls += s.tool_calls
            tin += s.tool_in
            tout += s.tool_out
        out.append(
            f"\n{'ferramenta':14}{'chamadas':>9}{'escrito ~tok':>14}{'devolvido ~tok':>16}"
        )
        for name in sorted(calls, key=lambda x: -(tin[x] + tout[x])):
            out.append(
                f"{name:14}{calls[name]:>9}{tin[name] // 4:>14}{tout[name] // 4:>16}"
            )  # ~4 chars/token
    return "\n".join(out)


def main(argv: list[str]) -> int:
    with_tools = "--tools" in argv
    paths = [a for a in argv if not a.startswith("--")]
    files = collect(paths)
    if not files:
        sys.stderr.write(__doc__ or "")
        return 2
    sys.stdout.write(render([scan(f) for f in files], with_tools) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
