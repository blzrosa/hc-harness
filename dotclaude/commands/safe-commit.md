---
description: Commita as mudanças com safe-commit (sem coautoria de IA); rodar este comando é a liberação da Nini
argument-hint: [o que commitar ou dica para a mensagem]
allowed-tools: Agent, Bash(git status:*)
---

Arquivos alterados (já coletado, não rode de novo): !`git status --short`

Pedido da Nini: $ARGUMENTS

A Nini rodou `/safe-commit`, então o commit está liberado para as mudanças acima, e só para elas. `git commit` e `git push` continuam bloqueados; use apenas o script, pela ferramenta Bash:

```
safe-commit -m "<título>" -m "<corpo opcional>" -- <arquivo> <arquivo> ...
```

1. **Mensagem.** Se esta conversa já deixa claro o que mudou e por quê, escreva a mensagem você mesmo, sem ler diffs. Senão, chame o agente `committer` (`subagent_type: "committer"`) passando o pedido da Nini; ele devolve título, corpo e arquivos de cada commit.
2. **O que entra.** Se o pedido delimita ("só os testes", "só src/x.py"), respeite. Mudanças sem relação entre si: um commit por grupo. Liste os arquivos depois de `--`; `--all` só quando tudo que o `git status` mostra pertence ao mesmo commit. Deixe de fora o que parece segredo ou lixo (`.env`, chaves, dumps, temporários) e avise.
3. **Formato.** Título no imperativo, até 72 caracteres, no idioma e estilo do projeto. Corpo de 1 a 3 linhas só para o PORQUÊ. Nenhuma linha de coautoria ou menção a IA.

Cada chamada pede confirmação à Nini. Se ela negar, pare: não tente de novo nem procure outro caminho. O agente nunca commita; quem roda o `safe-commit` é você.

Saída: a linha `hash título` de cada commit feito e, se sobrou algo fora, uma linha dizendo o quê e por quê. Não faça push.
