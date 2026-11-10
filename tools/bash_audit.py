"""Uso: python bash_audit.py <arquivo.jsonl | pasta> ...
Audita as chamadas Bash: o que roda, o que falha, o que repete, o que escreve arquivo por heredoc."""

import collections
import json
import pathlib
import re
import sys


def txt(x):
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "".join(i.get("text", "") if isinstance(i, dict) else str(i) for i in x)
    return ""


def head(cmd):
    s = cmd.strip()
    s = re.sub(r"^(\w+=\S+\s+)+", "", s)  # tira VAR=valor do começo
    s = re.sub(r"^cd\s+\S+\s*(&&|;)\s*", "", s)  # tira "cd x &&"
    w = s.split()
    if not w:
        return "?"
    return (
        f"{w[0]} {w[1]}"
        if w[0] in ("hc", "git", "uv", "python", "python3") and len(w) > 1
        else w[0]
    )


files = []
for a in sys.argv[1:]:
    p = pathlib.Path(a)
    files += sorted(p.glob("*.jsonl")) if p.is_dir() else [p]

calls = {}  # tool_use_id -> dados
for f in files:
    for line in f.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        c = (d.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") in ("Bash", "PowerShell"):
                cmd = (b.get("input") or {}).get("command", "")
                calls.setdefault(
                    b["id"], {"cmd": cmd, "out": 0, "err": False, "sess": f.stem}
                )  # dedupe
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                r = calls[b["tool_use_id"]]
                r["out"] = len(txt(b.get("content")))
                r["err"] = bool(b.get("is_error"))

n = len(calls)
errs = [c for c in calls.values() if c["err"]]
heredoc = [
    c for c in calls.values() if "<<" in c["cmd"] or re.search(r"\bcat\s*>", c["cmd"])
]
print(
    f"{n} chamadas | com erro: {len(errs)} ({100 * len(errs) // max(n, 1)}%) | "
    f"heredoc/cat>: {len(heredoc)} (~{sum(len(c['cmd']) for c in heredoc) // 4} tok escritos)"
)

g = collections.defaultdict(lambda: [0, 0, 0, 0])
for c in calls.values():
    x = g[head(c["cmd"])]
    x[0] += 1
    x[1] += len(c["cmd"]) // 4
    x[2] += c["out"] // 4
    x[3] += c["err"]
print(f"\n{'comando':22}{'n':>5}{'escrito':>9}{'devolv.':>9}{'erros':>6}")
for k, v in sorted(g.items(), key=lambda kv: -(kv[1][1] + kv[1][2]))[:15]:
    print(f"{k[:21]:22}{v[0]:>5}{v[1]:>9}{v[2]:>9}{v[3]:>6}")

print("\nSaídas maiores (~tok):")
for c in sorted(calls.values(), key=lambda c: -c["out"])[:5]:
    print(f"{c['out'] // 4:>7}  {c['cmd'].strip()[:90]!r}")

rep = collections.Counter(re.sub(r"\s+", " ", c["cmd"].strip()) for c in calls.values())
rep = [(k, v) for k, v in rep.items() if v > 1]
print(
    f"\nComandos idênticos repetidos: {len(rep)} (total extra: {sum(v - 1 for _, v in rep)})"
)
for k, v in sorted(rep, key=lambda kv: -kv[1])[:5]:
    print(f"{v:>4}x  {k[:90]!r}")
if errs:
    print("\nErros mais comuns (início do comando):")
    for k, v in collections.Counter(head(c["cmd"]) for c in errs).most_common(5):
        print(f"{v:>4}  {k}")
