---
description: Executa o .claude/SPEC.md etapa por etapa pelos agentes (implementer, coder, tester, writer), sem trocar o modelo da sessão
argument-hint: [etapa N | instrução extra] [--commit]
allowed-tools: Read, Grep, Glob, Agent, Edit(.claude/SPEC.md), Bash(hc:*), Bash(vera:*), Bash(lumine:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*)
---

Pedido: $ARGUMENTS

Estado do git (já coletado): !`git status --short`

O plano já existe em `.claude/SPEC.md`: não replaneje. Leia-o uma vez e siga o protocolo abaixo a partir da seção 3 (laço), como se tivesse recebido `--resume`. Se o pedido cita uma etapa, execute só ela. Você não edita código: toda etapa vai para o agente indicado nela (sem indicação, `implementer`).

Se o protocolo não aparecer logo abaixo desta linha, leia `~/.claude/protocols/plan-recursive.md` com Read antes de qualquer outra coisa.

@~/.claude/protocols/plan-recursive.md
