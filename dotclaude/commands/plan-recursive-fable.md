---
description: Igual ao /plan-recursive, mas orquestrado pelo Fable em vez do Opus
argument-hint: <descrição da tarefa> [--commit] | --resume
allowed-tools: Read, Grep, Glob, Agent, Edit(.claude/SPEC.md), Bash(hc:*), Bash(vera:*), Bash(lumine:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*)
model: claude-fable-5-2
---

Tarefa: $ARGUMENTS

Estado do git (já coletado): !`git status --short`

Siga o protocolo abaixo do início ao fim. Se ele não aparecer logo abaixo desta linha, leia `~/.claude/protocols/plan-recursive.md` com Read antes de qualquer outra coisa.

@~/.claude/protocols/plan-recursive.md
