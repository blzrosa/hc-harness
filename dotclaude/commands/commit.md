---
description: Propõe a mensagem de commit pelo agente committer (Haiku); não executa git commit
argument-hint: [o que commitar ou o motivo da mudança]
allowed-tools: Agent
---

Chame o agente `committer` (Agent com `subagent_type: "committer"`) com este prompt: `Proponha a mensagem de commit para as mudanças atuais.` mais, em uma ou duas frases, o PORQUÊ das mudanças se você souber por esta conversa, e o pedido da Nini se houver: $ARGUMENTS

Não rode git você mesmo e não leia diffs: o agente faz isso fora do seu contexto.

Saída: a resposta do agente como veio, num bloco de código, e uma linha lembrando que quem commita é a Nini (ou que `/safe-commit` executa o commit por ela).
