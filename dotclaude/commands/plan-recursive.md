---
description: Planeja no Opus e executa etapa por etapa chamando o agente implementer (Sonnet) até concluir o plano
argument-hint: <descrição da tarefa> [--commit] | --resume
allowed-tools: Read, Grep, Glob, Agent, Edit(.claude/SPEC.md), Bash(hc:*), Bash(vera:*), Bash(lumine:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*)
model: opus
---

Tarefa: $ARGUMENTS

Estado do git (já coletado): !`git status --short`

Siga o protocolo abaixo do início ao fim. Se ele não aparecer logo abaixo desta linha, leia `~/.claude/protocols/plan-recursive.md` com Read antes de qualquer outra coisa.

@~/.claude/protocols/plan-recursive.md
