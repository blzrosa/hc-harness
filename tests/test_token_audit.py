"""tools/token_audit.py: categorias de shell, leitura de sessão + subagente, preço ajustado e carrego."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

SPEC = importlib.util.spec_from_file_location(
    "token_audit", Path(__file__).resolve().parent.parent / "tools" / "token_audit.py"
)
assert SPEC and SPEC.loader
ta: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules["token_audit"] = ta  # dataclasses precisa achar o módulo
SPEC.loader.exec_module(ta)

MODEL = "claude-sonnet-5-5"


def assistant(mid: str, ts: str, read: int, w1h: int, content: list[Any]) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "attributionSkill": "implement",
            "message": {
                "id": mid,
                "model": MODEL,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 100,
                    "cache_read_input_tokens": read,
                    "cache_creation_input_tokens": w1h,
                    "cache_creation": {"ephemeral_1h_input_tokens": w1h},
                },
                "content": content,
            },
        }
    )


def tool_use(tid: str, name: str, inp: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def result(tid: str, ts: str, body: str, error: bool = False) -> str:
    block = {
        "type": "tool_result",
        "tool_use_id": tid,
        "content": body,
        "is_error": error,
    }
    return json.dumps(
        {"type": "user", "timestamp": ts, "message": {"content": [block]}}
    )


def make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    sub = proj / "aaaaaaaa-1111" / "subagents"
    sub.mkdir(parents=True)
    usage = {
        "inputTokens": 0,
        "outputTokens": 300,
        "cacheReadInputTokens": 2000,
        "cacheCreationEphemeral5mInputTokens": 0,
        "cacheCreationEphemeral1hInputTokens": 1000,
        "costUSD": (0.1 * 2000 + 2 * 1000 + 5 * 300) * 2e-6,
    }
    lines = [
        assistant(
            "m1",
            "2026-11-01T10:00:00Z",
            0,
            1000,
            [tool_use("t1", "Bash", {"command": "hc show a.py:f"})],
        ),
        result("t1", "2026-11-01T10:00:02Z", "x" * 370),
        assistant(
            "m2",
            "2026-11-01T10:00:05Z",
            1000,
            0,
            [tool_use("t2", "Bash", {"command": "cat a.py"})],
        ),
        result("t2", "2026-11-01T10:00:06Z", "hc guard: `cat` blocked", error=True),
        assistant(
            "m3", "2026-11-01T10:00:09Z", 1000, 0, [{"type": "text", "text": "fim"}]
        ),
        json.dumps(
            {"type": "cost-state", "totalCostUSD": 1.0, "modelUsage": {MODEL: usage}}
        ),
    ]
    (proj / "aaaaaaaa-1111.jsonl").write_text("\n".join(lines), encoding="utf-8")
    (sub / "agent-x.jsonl").write_text(
        assistant(
            "s1",
            "2026-11-01T10:00:03Z",
            0,
            500,
            [tool_use("u1", "Read", {"file_path": "a.py"})],
        ),
        encoding="utf-8",
    )
    (sub / "agent-x.meta.json").write_text(
        json.dumps({"agentType": "explorer"}), encoding="utf-8"
    )
    return proj


def test_shell_category_classifies_what_actually_runs() -> None:
    cat = ta.shell_category
    assert cat("hc") == "hc (verificar)"
    assert cat("cd src && hc --all 2>&1 | tail -40") == "hc (verificar)"
    assert cat("hc show a.py:f") == "hc show"
    assert cat("hc map src --list") == "hc map"
    assert cat("uv run pytest -q") == "direto:pytest"
    assert cat("python -m pytest tests") == "direto:pytest"
    assert cat("sed -n 1,20p a.py") == "leitura crua:sed"
    assert cat("git status --short") == "git status"
    assert cat("FOO=1 ls") == "shell:ls"


def test_categorize_mcp_and_agent() -> None:
    assert ta.categorize("mcp__lumi__lumi_search", {}) == "mcp:lumi search"
    assert ta.categorize("Agent", {"subagent_type": "explorer"}) == "Agent:explorer"
    assert ta.categorize("Read", {}) == "Read"


def test_reads_main_thread_and_subagent(tmp_path: Path) -> None:
    threads = [ta.read_thread(f) for f in ta.collect([str(make_project(tmp_path))])]
    kinds = sorted(t.kind for t in threads)
    assert kinds == ["agente:explorer", "principal"]
    main = next(t for t in threads if t.kind == "principal")
    assert [r.context for r in main.reqs] == [1000, 1000, 1000]
    assert main.reqs[0].skill == "implement"
    assert [c.cat for c in main.calls] == ["hc show", "leitura crua:cat"]
    assert main.calls[1].blocked and not main.calls[0].blocked
    sub = next(t for t in threads if t.kind != "principal")
    assert sub.calls[0].whole_file


def test_price_fit_and_carry(tmp_path: Path) -> None:
    threads = [ta.read_thread(f) for f in ta.collect([str(make_project(tmp_path))])]
    rep = ta.Report(threads, top=10)
    assert abs(rep.price[MODEL] - 2e-6) < 1e-12
    main = next(t for t in threads if t.kind == "principal")
    tokens, cost = rep.carry(main, main.calls[0])
    # escrito uma vez (2x) na requisição seguinte e relido (0,1x) na última
    assert abs(cost - tokens * 2e-6 * (2.0 + 0.1)) < 1e-12
    # a última chamada não tem requisição depois dela na mesma conversa: custo zero
    assert rep.carry(threads[0], threads[0].calls[-1])[1] >= 0


def test_report_renders_every_section(tmp_path: Path, capsys: Any) -> None:
    assert ta.main([str(make_project(tmp_path))]) == 0
    out = capsys.readouterr().out
    for title in ("== CUSTO ==", "== QUEM GASTOU ==", "== CACHE", "== ADOÇÃO"):
        assert title in out
    assert "bloqueios do hc guard: 1" in out
    assert ta.main([]) == 2
