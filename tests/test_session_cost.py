"""tools/session_cost.py: dedupe por id, cache miss após pausa, custo exato e detecção de subagentes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

SPEC = importlib.util.spec_from_file_location(
    "session_cost", Path(__file__).resolve().parent.parent / "tools" / "session_cost.py"
)
assert SPEC and SPEC.loader
sc: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules["session_cost"] = sc  # dataclasses precisa achar o módulo
SPEC.loader.exec_module(sc)


def assistant(
    mid: str, ts: str, read: int, write: int, content: list[dict] | None = None
) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts,
            "message": {
                "id": mid,
                "model": "claude-sonnet-5-5",
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 10,
                    "cache_read_input_tokens": read,
                    "cache_creation_input_tokens": write,
                },
                "content": content or [{"type": "text", "text": "ok"}],
            },
        }
    )


def tool_use(tid: str, name: str, **inp: object) -> list[dict]:
    return [{"type": "tool_use", "id": tid, "name": name, "input": inp}]


def write_session(
    tmp_path: Path, lines: list[str], name: str = "abcdef1234.jsonl"
) -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_dedupes_messages_and_tool_use_by_id(tmp_path: Path) -> None:
    bash = tool_use("t1", "Bash", command="ls")
    p = write_session(
        tmp_path,
        [
            assistant("m1", "2026-01-01T10:00:00Z", 0, 40000, bash),
            assistant(
                "m1", "2026-01-01T10:00:00Z", 0, 40000, bash
            ),  # mesma msg, outro bloco
        ],
    )
    s = sc.scan(p)
    assert len(s.turns) == 1
    assert s.tool_calls["Bash"] == 1


def test_cache_miss_after_long_pause(tmp_path: Path) -> None:
    p = write_session(
        tmp_path,
        [
            assistant("m1", "2026-01-01T10:00:00Z", 0, 50000),
            assistant("m2", "2026-01-01T10:01:00Z", 50000, 1000),  # cache quente
            assistant(
                "m3", "2026-01-01T11:30:00Z", 0, 52000
            ),  # 89 min depois: reescreveu tudo
        ],
    )
    s = sc.scan(p)
    assert (s.misses, s.miss_tokens) == (1, 52000)
    assert (s.pauses, s.long_pauses) == (1, 1)


def test_small_context_is_not_a_miss(tmp_path: Path) -> None:
    p = write_session(
        tmp_path,
        [
            assistant("m1", "2026-01-01T10:00:00Z", 0, 5000),
            assistant("m2", "2026-01-01T12:00:00Z", 0, 5100),
        ],
    )
    assert sc.scan(p).misses == 0


def test_cost_state_uses_last_line(tmp_path: Path) -> None:
    cs = lambda total, cost: json.dumps(
        {
            "type": "cost-state",
            "totalCostUSD": total,
            "modelUsage": {"claude-sonnet-5-5": {"costUSD": cost}},
        }
    )
    s = sc.scan(write_session(tmp_path, [cs(1.0, 1.0), cs(2.5, 2.5)]))
    assert s.cost == 2.5
    assert s.models == {"claude-sonnet-5-5": 2.5}


def test_detects_subagent_calls_and_sidechain(tmp_path: Path) -> None:
    p = write_session(
        tmp_path,
        [
            assistant(
                "m1",
                "2026-01-01T10:00:00Z",
                0,
                1000,
                tool_use("a1", "Agent", subagent_type="explorer"),
            ),
            assistant(
                "m2",
                "2026-01-01T10:00:05Z",
                0,
                1000,
                tool_use("a2", "Task", subagent_type="explorer"),
            ),
            json.dumps(
                {"type": "user", "isSidechain": True, "message": {"content": "x"}}
            ),
        ],
    )
    s = sc.scan(p)
    assert dict(s.subagents) == {"explorer": 2}
    assert s.sidechain_lines == 1
    assert "explorer" in sc.render([s])


def test_render_reports_no_subagents_and_totals(tmp_path: Path) -> None:
    p = write_session(tmp_path, [assistant("m1", "2026-01-01T10:00:00Z", 0, 1000)])
    out = sc.render([sc.scan(p)], with_tools=True)
    assert "NENHUMA chamada" in out
    assert "1 sessão(ões)" in out


def test_main_exit_codes(tmp_path: Path, capsys) -> None:
    write_session(tmp_path, [assistant("m1", "2026-01-01T10:00:00Z", 0, 1000)])
    assert sc.main([str(tmp_path)]) == 0
    assert "abcdef12" in capsys.readouterr().out
    assert sc.main([str(tmp_path / "vazio")]) == 2
