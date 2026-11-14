"""Auditoria de tokens das sessões do Claude Code: para onde foi o dinheiro e por quê.

Uso:
    python tools/token_audit.py <pasta | arquivo.jsonl> [...] [--top=N] [--secoes=a,b,...]
    python tools/token_audit.py <pasta> --exemplos=<prefixo de categoria>   (ex.: "hc (ver", "shell:for")

Uma pasta é lida recursivamente (inclui `<sessão>/subagents/agent-*.jsonl`), então serve tanto
`~/.claude/projects/<projeto>` quanto `~/.claude/projects` inteiro.

Seções (todas por padrão): custo, origem, ferramentas, tempo, adocao, agentes, base.

Como o custo é atribuído
- Preço: a linha `cost-state` dá o custo exato por modelo. Assumindo as razões usuais
  (leitura de cache 0,1x, escrita 5 min 1,25x, escrita 1 h 2x, saída 5x o preço de entrada),
  sobra uma incógnita por modelo, ajustada pelos totais. A dispersão entre sessões é impressa.
- "Carrego": um resultado de ferramenta não custa só quando chega. Ele é escrito no cache uma
  vez e relido em TODAS as requisições seguintes da mesma conversa. O custo de carrego de uma
  chamada é tokens x (escrita + leitura x requisições restantes).
Só biblioteca padrão.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

R_READ, R_W5, R_W1H, R_OUT = 0.1, 1.25, 2.0, 5.0
DEFAULT_CPT = 3.7  # caracteres por token quando a calibração não é confiável
DIRECT_TOOLS = ("pytest", "ruff", "pyright", "ty", "ctest", "mypy")
RAW_READERS = (
    "cat",
    "sed",
    "head",
    "tail",
    "awk",
    "less",
    "more",
    "type",
    "Get-Content",
)
HC_SUBS = ("map", "find", "show", "impact", "edit", "guard")
SECTIONS = (
    "custo",
    "origem",
    "papeis",
    "cache",
    "ferramentas",
    "tempo",
    "adocao",
    "agentes",
    "base",
)


@dataclass
class Req:
    ts: datetime | None
    model: str
    inp: int = 0
    read: int = 0
    w5: int = 0
    w1h: int = 0
    out: int = 0
    think: int = 0
    skill: str = ""

    @property
    def context(self) -> int:
        return self.inp + self.read + self.w5 + self.w1h

    def units(self) -> float:
        """Custo em 'tokens de entrada equivalentes'."""
        return (
            self.inp
            + R_READ * self.read
            + R_W5 * self.w5
            + R_W1H * self.w1h
            + R_OUT * self.out
        )


@dataclass
class Call:
    tool: str
    cat: str
    in_chars: int
    req: int  # índice da requisição que emitiu a chamada
    t0: datetime | None
    command: str = ""
    whole_file: bool = False
    out_chars: int = 0
    t1: datetime | None = None
    err: bool = False
    blocked: bool = False
    answered: bool = False


@dataclass
class Thread:
    """Uma conversa: a sessão principal ou a transcrição de um subagente."""

    path: Path
    kind: str  # "principal" ou "agente:<tipo>"
    project: str
    session: str
    reqs: list[Req] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    text_chars: int = 0  # texto de usuário + assistente (não ferramenta)
    hook_ms: list[int] = field(default_factory=list)
    hook_chars: int = 0
    diag_chars: int = 0
    diag_n: int = 0
    cost_state: dict[str, dict[str, float]] = field(default_factory=dict)
    cost_total: float | None = None
    shape_tools: dict[str, int] = field(default_factory=dict)
    shape_system: int = 0
    att_chars: Counter[str] = field(default_factory=Counter)


def parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def text_len(x: Any) -> int:
    if isinstance(x, str):
        return len(x)
    if isinstance(x, list):
        return sum(text_len(i.get("text", "") if isinstance(i, dict) else i) for i in x)
    return 0


def text_of(x: Any) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "".join(
            str(i.get("text", "")) if isinstance(i, dict) else str(i) for i in x
        )
    return ""


def shell_category(cmd: str) -> str:
    """Classifica um comando de shell pelo que ele realmente roda."""
    s = cmd.strip()
    s = re.sub(r"^(\w+=\S+\s+)+", "", s)
    s = re.sub(r"^cd\s+(\"[^\"]*\"|\S+)\s*(&&|;)\s*", "", s)
    w = s.split()
    if not w:
        return "shell:?"
    head = w[0].rsplit("/", 1)[-1]
    rest = w[1:]
    if head == "uv" and rest[:1] == ["run"]:
        rest = [x for x in rest[1:] if not x.startswith("-")]
        if rest[:2] == ["python", "-m"]:
            rest = rest[2:]
        if not rest:
            return "shell:uv"
        head, rest = rest[0].rsplit("/", 1)[-1], rest[1:]
    if head in ("python", "python3", "py") and rest[:1] == ["-m"] and len(rest) > 1:
        head, rest = rest[1], rest[2:]
    if head == "hc":
        sub = next((x for x in rest if not x.startswith("-")), "")
        return f"hc {sub}" if sub in HC_SUBS else "hc (verificar)"
    if head in DIRECT_TOOLS:
        return f"direto:{head}"
    if head in RAW_READERS:
        return f"leitura crua:{head}"
    if head == "git":
        return f"git {rest[0]}" if rest else "git"
    if head in ("python", "python3", "py"):
        return "shell:python"
    return f"shell:{head}"


def categorize(name: str, inp: dict[str, Any]) -> str:
    if name in ("Bash", "PowerShell"):
        return shell_category(str(inp.get("command", "")))
    if name.startswith("mcp__"):
        parts = name.split("__")
        tool = parts[2] if len(parts) > 2 else ""
        return f"mcp:{parts[1]} {tool.removeprefix(parts[1] + '_')}".strip()
    if name in ("Agent", "Task"):
        return f"Agent:{inp.get('subagent_type', '?')}"
    return name


def read_thread(path: Path) -> Thread:
    sub = path.parent.name == "subagents"
    kind = "principal"
    if sub:
        meta = path.with_suffix(".meta.json")
        try:
            kind = "agente:" + str(
                json.loads(meta.read_text(encoding="utf-8")).get("agentType", "?")
            )
        except (OSError, ValueError):
            kind = "agente:?"
    session_dir = path.parent.parent if sub else path
    th = Thread(
        path=path,
        kind=kind,
        project=session_dir.parent.name,
        session=session_dir.stem[:8],
    )
    by_msg: dict[str, int] = {}
    by_call: dict[str, Call] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        typ = d.get("type")
        ts = parse_ts(d.get("timestamp"))
        if typ == "cost-state":
            th.cost_total = d.get("totalCostUSD", th.cost_total)
            mu = d.get("modelUsage")
            if isinstance(mu, dict):
                th.cost_state = {m: v for m, v in mu.items() if isinstance(v, dict)}
            continue
        if typ == "api-request-shape" and not th.shape_tools:
            shape = d.get("shape") or {}
            th.shape_system = sum(
                len(str(x.get("text", ""))) for x in shape.get("system") or []
            )
            for t in shape.get("tools") or []:
                th.shape_tools[str(t.get("name"))] = len(
                    json.dumps(t, ensure_ascii=False)
                )
            continue
        if typ == "attachment":
            a = d.get("attachment") or {}
            at = str(a.get("type"))
            size = len(json.dumps(a, ensure_ascii=False))
            th.att_chars[at] += size
            if at == "hook_success":
                th.hook_chars += len(str(a.get("content", "")))
                try:
                    th.hook_ms.append(int(a.get("durationMs", 0)))
                except (TypeError, ValueError):
                    pass
            elif at == "diagnostics":
                th.diag_chars += size
                th.diag_n += 1
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        usage = m.get("usage")
        if typ == "assistant" and isinstance(usage, dict) and mid:
            if mid not in by_msg:
                by_msg[mid] = len(th.reqs)
                th.reqs.append(Req(ts, str(m.get("model", "?"))))
            r = th.reqs[by_msg[mid]]
            cc = usage.get("cache_creation") or {}
            w1h = cc.get("ephemeral_1h_input_tokens") or 0
            total_w = usage.get("cache_creation_input_tokens") or 0
            r.inp = usage.get("input_tokens") or 0
            r.read = usage.get("cache_read_input_tokens") or 0
            r.w1h, r.w5 = w1h, max(0, total_w - w1h)
            r.out = max(r.out, usage.get("output_tokens") or 0)
            r.think = (usage.get("output_tokens_details") or {}).get(
                "thinking_tokens"
            ) or 0
            r.skill = str(d.get("attributionSkill") or "")
        content = m.get("content")
        if isinstance(content, str):
            th.text_chars += len(content)
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                th.text_chars += len(str(b.get("text", "")))
            elif bt == "tool_use" and b.get("id") not in by_call:
                raw = b.get("input")
                inp: dict[str, Any] = raw if isinstance(raw, dict) else {}
                name = str(b.get("name", "?"))
                c = Call(
                    tool=name,
                    cat=categorize(name, inp),
                    in_chars=len(json.dumps(inp, ensure_ascii=False)),
                    req=by_msg.get(str(mid), max(0, len(th.reqs) - 1)),
                    t0=ts,
                    command=str(inp.get("command", "")),
                    whole_file=name == "Read"
                    and "offset" not in inp
                    and "limit" not in inp,
                )
                by_call[str(b["id"])] = c
                th.calls.append(c)
            elif bt == "tool_result":
                c2 = by_call.get(str(b.get("tool_use_id")))
                if c2 is None or c2.answered:
                    continue
                c2.answered = True
                body = text_of(b.get("content"))
                c2.out_chars = len(body)
                c2.t1 = ts
                c2.err = bool(b.get("is_error"))
                c2.blocked = c2.err and "hc guard" in body
    return th


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for a in paths:
        p = Path(a).expanduser()
        if p.is_dir():
            files += sorted(p.rglob("*.jsonl"))
        elif p.is_file():
            files.append(p)
    return files


# ---------- preços ----------


def fit_prices(threads: list[Thread]) -> tuple[dict[str, float], dict[str, str]]:
    """US$ por token de entrada, por modelo, a partir das linhas cost-state."""
    cost: dict[str, float] = defaultdict(float)
    units: dict[str, float] = defaultdict(float)
    per_session: dict[str, list[float]] = defaultdict(list)
    for th in threads:
        for model, v in th.cost_state.items():
            w1h = float(v.get("cacheCreationEphemeral1hInputTokens", 0) or 0)
            w5 = float(v.get("cacheCreationEphemeral5mInputTokens", 0) or 0)
            u = (
                float(v.get("inputTokens", 0) or 0)
                + R_READ * float(v.get("cacheReadInputTokens", 0) or 0)
                + R_W5 * w5
                + R_W1H * w1h
                + R_OUT * float(v.get("outputTokens", 0) or 0)
            )
            c = float(v.get("costUSD", 0) or 0)
            if u > 0 and c > 0:
                cost[model] += c
                units[model] += u
                per_session[model].append(c / u)
    price = {m: cost[m] / units[m] for m in cost}
    spread = {
        m: f"{min(v) * 1e6:.2f}..{max(v) * 1e6:.2f}" for m, v in per_session.items()
    }
    return price, spread


def price_of(price: dict[str, float], model: str) -> float:
    if model in price:
        return price[model]
    for m, p in price.items():
        if m.split("-")[1:2] == model.split("-")[1:2]:
            return p
    return 0.0


def calibrate_cpt(threads: list[Thread]) -> float:
    """Caracteres por token: texto acrescentado / crescimento do contexto."""
    chars = grown = 0
    for th in threads:
        if len(th.reqs) < 5:
            continue
        ctx = [r.context for r in th.reqs]
        if min(ctx[1:]) < ctx[0] * 0.8:  # houve compactação: não serve
            continue
        grown += ctx[-1] - ctx[0]
        last = len(th.reqs) - 1
        chars += th.text_chars + sum(
            c.in_chars + c.out_chars for c in th.calls if c.req < last
        )
    cpt = chars / grown if grown else 0.0
    return cpt if 2.5 <= cpt <= 5.0 else DEFAULT_CPT


# ---------- relatório ----------


def usd(x: float) -> str:
    return f"{x:8.2f}"


def k(n: float) -> str:
    return f"{n / 1000:.0f}k" if abs(n) >= 1000 else f"{n:.0f}"


def pct(a: float, b: float) -> str:
    return f"{100 * a / b:.0f}%" if b else "-"


def secs(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


class Report:
    def __init__(self, threads: list[Thread], top: int) -> None:
        self.threads = threads
        self.top = top
        self.price, self.spread = fit_prices(threads)
        self.cpt = calibrate_cpt(threads)
        self.out: list[str] = []
        self._long = 0
        self._switch = 0

    def p(self, s: str = "") -> None:
        self.out.append(s)

    def req_cost(self, r: Req) -> float:
        return price_of(self.price, r.model) * r.units()

    def thread_cost(self, th: Thread) -> float:
        return sum(self.req_cost(r) for r in th.reqs)

    def carry(self, th: Thread, c: Call) -> tuple[float, float]:
        """(tokens, US$) que a chamada custa por ficar no contexto até o fim da conversa."""
        tok = (c.in_chars + c.out_chars) / self.cpt
        after = th.reqs[c.req + 1 :]
        if not after:
            return tok, 0.0
        usd_ = tok * price_of(self.price, after[0].model) * R_W1H
        usd_ += sum(tok * price_of(self.price, r.model) * R_READ for r in after[1:])
        return tok, usd_

    # --- custo: exato x reconstruído, e por componente ---
    def custo(self) -> None:
        mains = [t for t in self.threads if t.kind == "principal"]
        exact = sum(t.cost_total or 0 for t in mains)
        rebuilt = sum(self.thread_cost(t) for t in self.threads)
        self.p("== CUSTO ==")
        self.p(
            f"{len(mains)} sessões, {len(self.threads) - len(mains)} transcrições de subagente, "
            f"{sum(len(t.reqs) for t in self.threads)} requisições"
        )
        self.p(
            f"custo exato (cost-state): US$ {exact:.2f} | reconstruído das transcrições: "
            f"US$ {rebuilt:.2f} ({pct(rebuilt, exact)})"
        )
        self.p(f"calibração: {self.cpt:.2f} caracteres por token")
        self.p("preço de entrada ajustado (US$/MTok) e dispersão entre sessões:")
        for m, pr in sorted(self.price.items(), key=lambda kv: -kv[1]):
            self.p(f"  {m:22} {pr * 1e6:6.2f}   [{self.spread.get(m, '')}]")
        comp: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for th in self.threads:
            for r in th.reqs:
                if r.model.startswith("<"):
                    continue
                pr = price_of(self.price, r.model)
                c = comp[r.model]
                c["leitura de cache"] += pr * R_READ * r.read
                c["escrita de cache"] += pr * (R_W5 * r.w5 + R_W1H * r.w1h)
                c["saída"] += pr * R_OUT * r.out
                c["  (da saída: raciocínio)"] += pr * R_OUT * r.think
                c["entrada sem cache"] += pr * r.inp
                c["_req"] += 1
                c["_w5"] += r.w5
                c["_w1h"] += r.w1h
        keys = [
            "leitura de cache",
            "escrita de cache",
            "saída",
            "  (da saída: raciocínio)",
            "entrada sem cache",
        ]
        self.p(
            f"\n{'componente':26}"
            + "".join(f"{m.replace('claude-', '')[:15]:>16}" for m in comp)
        )
        for key in keys:
            row = f"{key:26}"
            for m in comp:
                tot = sum(comp[m][x] for x in keys if not x.startswith("  "))
                row += f"{comp[m][key]:>9.2f} {pct(comp[m][key], tot):>5} "
            self.p(row)
        self.p(
            f"{'requisições':26}" + "".join(f"{comp[m]['_req']:>16.0f}" for m in comp)
        )
        self.p(
            f"{'escrita 5 min / 1 h (tok)':26}"
            + "".join(
                f"{k(comp[m]['_w5']) + ' / ' + k(comp[m]['_w1h']):>16}" for m in comp
            )
        )

    # --- origem: quem gastou (thread, skill, projeto) ---
    def origem(self) -> None:
        self.p("\n== QUEM GASTOU ==")
        rows: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        for th in self.threads:
            for r in th.reqs:
                who = th.kind
                if th.kind == "principal":
                    who = f"principal /{r.skill}" if r.skill else "principal (conversa)"
                key = f"{who} [{r.model.replace('claude-', '')}]"
                x = rows[key]
                x[0] += self.req_cost(r)
                x[1] += 1
                x[2] += r.context
                x[3] += r.out
        total = sum(v[0] for v in rows.values())
        self.p(
            f"{'origem':46}{'US$':>8}{'%':>5}{'req':>6}{'ctx médio':>10}{'saída/req':>10}"
        )
        for key, v in sorted(rows.items(), key=lambda kv: -kv[1][0])[: self.top]:
            self.p(
                f"{key[:45]:46}{usd(v[0])}{pct(v[0], total):>5}{v[1]:>6.0f}"
                f"{k(v[2] / v[1]):>10}{v[3] / v[1]:>10.0f}"
            )
        projects: dict[str, float] = defaultdict(float)
        for th in self.threads:
            projects[th.project] += self.thread_cost(th)
        if len(projects) > 1:
            self.p("\npor projeto:")
            for name, c in sorted(projects.items(), key=lambda kv: -kv[1])[: self.top]:
                self.p(f"  {usd(c)}  {name[-40:]}")
        # decomposição: base x ferramentas x saída
        base = tools = outc = 0.0
        for th in self.threads:
            if not th.reqs:
                continue
            first = th.reqs[0].context
            for i, r in enumerate(th.reqs):
                pr = price_of(self.price, r.model)
                base += first * pr * (R_W1H if i == 0 else R_READ)
                outc += r.out * pr * R_OUT
            tools += sum(self.carry(th, c)[1] for c in th.calls)
        rest = total - base - tools - outc
        self.p("\ndecomposição do total (estimativa):")
        for name, v in (
            ("contexto fixo (prompt, ferramentas, CLAUDE.md) relido a cada req", base),
            ("carrego de entradas e resultados de ferramenta", tools),
            ("geração de saída (texto, raciocínio, argumentos de ferramenta)", outc),
            ("resto (mensagens, anexos, reescritas de cache)", rest),
        ):
            self.p(f"  {usd(v)} {pct(v, total):>5}  {name}")

    # --- ferramentas: volume e carrego ---
    def ferramentas(self) -> None:
        self.p("\n== FERRAMENTAS (volume e custo de carrego) ==")
        rows: dict[str, list[float]] = defaultdict(lambda: [0.0] * 6)
        for th in self.threads:
            for c in th.calls:
                x = rows[c.cat]
                _, cost = self.carry(th, c)
                x[0] += 1
                x[1] += c.in_chars / self.cpt
                x[2] += c.out_chars / self.cpt
                x[3] += cost
                x[4] += c.err
                # argumentos são tokens de SAÍDA: pagos 5x na emissão
                if c.req < len(th.reqs):
                    x[5] += (
                        c.in_chars
                        / self.cpt
                        * R_OUT
                        * price_of(self.price, th.reqs[c.req].model)
                    )
        self.p(
            f"{'categoria':26}{'n':>6}{'escrito':>9}{'devolv.':>9}{'dev/n':>7}"
            f"{'carrego$':>9}{'emissão$':>9}{'erros':>6}"
        )
        order = sorted(rows.items(), key=lambda kv: -(kv[1][3] + kv[1][5]))
        for cat, v in order[: self.top]:
            self.p(
                f"{cat[:25]:26}{v[0]:>6.0f}{k(v[1]):>9}{k(v[2]):>9}{v[2] / v[0]:>7.0f}"
                f"{v[3]:>9.2f}{v[5]:>9.2f}{v[4]:>6.0f}"
            )
        if len(order) > self.top:
            tail = order[self.top :]
            self.p(
                f"{'(outras ' + str(len(tail)) + ')':26}{sum(v[0] for _, v in tail):>6.0f}"
                f"{k(sum(v[1] for _, v in tail)):>9}{k(sum(v[2] for _, v in tail)):>9}{'':>7}"
                f"{sum(v[3] for _, v in tail):>9.2f}{sum(v[5] for _, v in tail):>9.2f}"
            )
        big = sorted(
            ((self.carry(th, c)[1], c, th) for th in self.threads for c in th.calls),
            key=lambda x: -x[0],
        )[:8]
        self.p("\nchamadas individuais mais caras (carrego):")
        for cost, c, th in big:
            what = c.command.strip().replace("\n", " ")[:60] or c.cat
            self.p(
                f"  US$ {cost:5.2f}  {k(c.out_chars / self.cpt):>5} tok  "
                f"{th.session} {th.kind[:14]:14} {what}"
            )

    # --- tempo ---
    def tempo(self) -> None:
        self.p("\n== TEMPO DE EXECUÇÃO (do pedido ao resultado, em s) ==")
        self.p(
            "inclui espera por permissão; Agent em segundo plano aparece na seção de agentes"
        )
        t: dict[str, list[float]] = defaultdict(list)
        for th in self.threads:
            for c in th.calls:
                s = secs(c.t0, c.t1)
                if s is not None and s >= 0 and not c.cat.startswith("Agent:"):
                    t[c.cat].append(s)
        self.p(
            f"{'categoria':26}{'n':>6}{'mediana':>9}{'p90':>8}{'máx':>8}{'total':>9}"
        )
        for cat, v in sorted(t.items(), key=lambda kv: -sum(kv[1]))[: self.top]:
            v.sort()
            p90 = v[min(len(v) - 1, int(len(v) * 0.9))]
            self.p(
                f"{cat[:25]:26}{len(v):>6}{statistics.median(v):>9.1f}{p90:>8.1f}"
                f"{v[-1]:>8.0f}{sum(v):>9.0f}"
            )
        hooks = [ms for th in self.threads for ms in th.hook_ms]
        if hooks:
            self.p(
                f"hook SessionStart (lumi): {len(hooks)}x, mediana {statistics.median(hooks):.0f} ms, "
                f"máx {max(hooks)} ms"
            )

    # --- papéis: o que cada origem faz com as suas requisições ---
    def papeis(self) -> None:
        self.p("\n== O QUE CADA ORIGEM FAZ (chamadas de ferramenta por origem) ==")
        acts: dict[str, Counter[str]] = defaultdict(Counter)
        reqs: Counter[str] = Counter()
        silent: Counter[str] = Counter()
        for th in self.threads:
            used = {c.req for c in th.calls}
            for i, r in enumerate(th.reqs):
                reqs[self.origin(th, r)] += 1
                silent[self.origin(th, r)] += i not in used
            for c in th.calls:
                if c.req < len(th.reqs):
                    group = (
                        "hc navegação"
                        if c.cat in ("hc map", "hc find", "hc show", "hc impact")
                        else "shell (outros)"
                        if c.cat.startswith(("shell:", "leitura crua:", "git"))
                        else c.cat
                    )
                    acts[self.origin(th, th.reqs[c.req])][group] += 1
        for who, n in reqs.most_common(self.top):
            if n < 10:
                continue
            mix = ", ".join(f"{a} {b}" for a, b in acts[who].most_common(9))
            self.p(f"{who} — {n} req, {silent[who]} sem ferramenta")
            self.p(f"    {mix}")

    def origin(self, th: Thread, r: Req) -> str:
        who = th.kind
        if th.kind == "principal":
            who = f"principal /{r.skill}" if r.skill else "principal (conversa)"
        return f"{who} [{r.model.replace('claude-', '')}]"

    # --- cache: carga inicial e reescritas ---
    def cache(self) -> None:
        self.p("\n== CACHE: carga inicial e reescritas ==")
        self.p(
            f"{'conversa':22}{'n':>4}{'carga inicial':>15}{'US$':>8}{'reescritas':>11}"
            f"{'tok':>8}{'US$':>8}{'após >5min':>11}{'após >1h':>9}{'TTL 5m/1h':>14}"
        )
        g: dict[str, list[float]] = defaultdict(lambda: [0.0] * 9)
        for th in self.threads:
            if not th.reqs:
                continue
            x = g[th.kind]
            first = th.reqs[0]
            pr0 = price_of(self.price, first.model)
            x[0] += 1
            x[1] += first.w5 + first.w1h
            x[2] += pr0 * (R_W5 * first.w5 + R_W1H * first.w1h)
            for prev, r in zip(th.reqs, th.reqs[1:]):
                x[7] += r.w5
                x[8] += r.w1h
                if prev.context < 20_000 or r.read >= prev.context * 0.5:
                    continue
                pr = price_of(self.price, r.model)
                gap = (secs(prev.ts, r.ts) or 0) / 60
                x[3] += 1
                x[4] += r.w5 + r.w1h
                # o que a reescrita custou a mais do que uma leitura normal custaria
                x[5] += pr * ((R_W5 - R_READ) * r.w5 + (R_W1H - R_READ) * r.w1h)
                x[6] += gap > 5
                if prev.model != r.model:
                    self._switch += 1
                if gap > 60:
                    self._long += 1
        for kind, x in sorted(g.items()):
            self.p(
                f"{kind[:21]:22}{x[0]:>4.0f}{k(x[1]):>15}{x[2]:>8.2f}{x[3]:>11.0f}"
                f"{k(x[4]):>8}{x[5]:>8.2f}{x[6]:>11.0f}{self._long:>9}"
                f"{k(x[7]) + '/' + k(x[8]):>14}"
            )
            self._long = 0
        self.p(
            f"reescritas logo após troca de modelo no meio da conversa: {self._switch} "
            "(o cache é por modelo: /comando com `model:` diferente reescreve o contexto inteiro)"
        )
        self._switch = 0

    # --- exemplos de uma categoria (--exemplos=<prefixo>) ---
    def exemplos(self, prefix: str) -> None:
        self.p(f"\n== EXEMPLOS: {prefix} (as mais demoradas) ==")
        rows = [
            (secs(c.t0, c.t1) or 0.0, c, th)
            for th in self.threads
            for c in th.calls
            if c.cat.startswith(prefix) or (prefix == "bloqueado" and c.blocked)
        ]
        rows.sort(key=lambda x: -x[0])
        for s, c, th in rows[: self.top]:
            what = (c.command or c.cat).strip().replace("\n", " ⏎ ")[:150]
            flag = "BLOQUEADO " if c.blocked else "ERRO " if c.err else ""
            self.p(
                f"{s:7.0f}s {k(c.out_chars / self.cpt):>5} tok  {th.session} "
                f"{th.kind[:12]:12} {flag}{what}"
            )

    # --- adoção de hc / lumi ---
    def adocao(self) -> None:
        self.p("\n== ADOÇÃO: hc e lumi estão sendo usados? ==")
        n: Counter[str] = Counter()
        tok: Counter[str] = Counter()
        sess_lumi: set[str] = set()
        sess_hc: set[str] = set()
        sessions: set[str] = set()
        blocked: Counter[str] = Counter()
        for th in self.threads:
            sessions.add(th.session)
            for c in th.calls:
                g = (
                    "hc navegação"
                    if c.cat in ("hc map", "hc find", "hc show", "hc impact")
                    else "hc verificação"
                    if c.cat == "hc (verificar)"
                    else "ferramenta direta (pytest/ruff/pyright)"
                    if c.cat.startswith("direto:")
                    else "leitura crua no shell (cat/sed/head)"
                    if c.cat.startswith("leitura crua:")
                    else "lumi"
                    if c.cat.startswith("mcp:lumi")
                    else "Read arquivo inteiro"
                    if c.tool == "Read" and c.whole_file
                    else "Read com offset/limit"
                    if c.tool == "Read"
                    else c.tool
                    if c.tool in ("Grep", "Glob")
                    else ""
                )
                if c.blocked:
                    blocked[c.cat] += 1
                if not g:
                    continue
                n[g] += 1
                tok[g] += int(c.out_chars / self.cpt)
                if g == "lumi":
                    sess_lumi.add(th.session)
                if g.startswith("hc"):
                    sess_hc.add(th.session)
        self.p(f"{'grupo':42}{'n':>6}{'devolvido':>11}{'tok/chamada':>13}")
        for g, v in n.most_common():
            self.p(f"{g:42}{v:>6}{k(tok[g]):>11}{tok[g] / v:>13.0f}")
        self.p(
            f"sessões com hc: {len(sess_hc)}/{len(sessions)} | com lumi (MCP): "
            f"{len(sess_lumi)}/{len(sessions)}"
        )
        lumi = Counter(
            c.cat for th in self.threads for c in th.calls if c.cat.startswith("mcp:")
        )
        if lumi:
            self.p(
                "chamadas MCP: " + ", ".join(f"{a} {b}" for a, b in lumi.most_common())
            )
        if blocked:
            self.p(
                f"bloqueios do hc guard: {sum(blocked.values())} — "
                + ", ".join(f"{a} {b}" for a, b in blocked.most_common(6))
            )
        diag = sum(t.diag_chars for t in self.threads)
        self.p(
            f"diagnósticos do LSP injetados: {sum(t.diag_n for t in self.threads)} anexos, "
            f"~{k(diag / self.cpt)} tok | hook lumi no início: ~"
            f"{k(sum(t.hook_chars for t in self.threads) / self.cpt)} tok"
        )

    # --- subagentes ---
    def agentes(self) -> None:
        self.p("\n== SUBAGENTES ==")
        g: dict[str, list[Thread]] = defaultdict(list)
        for th in self.threads:
            if th.kind != "principal" and th.reqs:
                g[th.kind] += [th]
        if not g:
            self.p("nenhuma transcrição de subagente")
            return
        self.p(
            f"{'tipo':20}{'n':>4}{'modelo':>12}{'req/exec':>9}{'ctx 1º':>8}{'ctx máx':>9}"
            f"{'US$/exec':>9}{'US$':>8}{'min/exec':>9}"
        )
        for kind, ths in sorted(g.items()):
            costs = [self.thread_cost(t) for t in ths]
            durs = [
                (secs(t.reqs[0].ts, t.reqs[-1].ts) or 0) / 60 for t in ths if t.reqs
            ]
            model = Counter(r.model for t in ths for r in t.reqs).most_common(1)[0][0]
            self.p(
                f"{kind[7:26]:20}{len(ths):>4}{model.replace('claude-', '')[:11]:>12}"
                f"{statistics.mean(len(t.reqs) for t in ths):>9.0f}"
                f"{k(statistics.median(t.reqs[0].context for t in ths)):>8}"
                f"{k(max(r.context for t in ths for r in t.reqs)):>9}"
                f"{statistics.mean(costs):>9.2f}{sum(costs):>8.2f}{statistics.mean(durs):>9.1f}"
            )
        ret: dict[str, list[int]] = defaultdict(list)
        for th in self.threads:
            for c in th.calls:
                if c.cat.startswith("Agent:"):
                    ret[c.cat].append(c.in_chars)
        for cat, v in ret.items():
            self.p(
                f"  {cat}: {len(v)} despachos, prompt médio ~{statistics.mean(v) / self.cpt:.0f} tok"
            )

    # --- contexto fixo ---
    def base(self) -> None:
        self.p("\n== CONTEXTO FIXO (o que já vem carregado antes da 1ª mensagem) ==")
        by_kind: dict[str, list[int]] = defaultdict(list)
        for th in self.threads:
            if th.reqs:
                by_kind[th.kind].append(th.reqs[0].context)
        for kind, v in sorted(by_kind.items()):
            self.p(
                f"  1ª requisição, {kind:20} mediana {k(statistics.median(v)):>5} tok "
                f"(mín {k(min(v))}, máx {k(max(v))}, n={len(v)})"
            )
        shaped = [t for t in self.threads if t.shape_tools and t.kind == "principal"]
        if not shaped:
            return
        th = max(shaped, key=lambda t: t.path.stat().st_mtime)
        total = sum(th.shape_tools.values())
        self.p(
            f"definições de ferramenta na sessão {th.session}: ~{k(total / self.cpt)} tok "
            f"em {len(th.shape_tools)} ferramentas; prompt de sistema ~{k(th.shape_system / self.cpt)} tok"
        )
        for name, size in sorted(th.shape_tools.items(), key=lambda kv: -kv[1])[:10]:
            self.p(f"  {size / self.cpt:>7.0f} tok  {name}")
        n_main = len([t for t in self.threads if t.kind == "principal" and t.reqs])
        att: Counter[str] = Counter()
        for t in self.threads:
            if t.kind == "principal":
                att += t.att_chars
        self.p("anexos de contexto, média por sessão (tok):")
        for name in (
            "skill_listing",
            "instructions",
            "agent_listing_delta",
            "deferred_tools_delta",
            "mcp_instructions_delta",
            "environment",
            "session_context",
            "hook_success",
        ):
            if att[name]:
                self.p(f"  {att[name] / self.cpt / max(n_main, 1):>7.0f}  {name}")


def main(argv: list[str]) -> int:
    top = 22
    sections = list(SECTIONS)
    paths: list[str] = []
    examples: list[str] = []
    for a in argv:
        if a.startswith("--top="):
            top = int(a.split("=", 1)[1])
        elif a.startswith("--secoes="):
            sections = [s for s in a.split("=", 1)[1].split(",") if s in SECTIONS]
        elif a.startswith("--exemplos="):
            examples.append(a.split("=", 1)[1])
        elif not a.startswith("--"):
            paths.append(a)
    files = collect(paths)
    if not files:
        sys.stderr.write(__doc__ or "")
        return 2
    rep = Report([read_thread(f) for f in files], top)
    for s in [] if examples else sections:
        getattr(rep, s)()
    for e in examples:
        rep.exemplos(e)
    sys.stdout.write("\n".join(rep.out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
