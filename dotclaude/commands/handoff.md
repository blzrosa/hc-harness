---
description: Grava o estado da sessão em .claude/HANDOFF.md para retomar após /clear
allowed-tools: Write(.claude/HANDOFF.md), Edit(.claude/HANDOFF.md)
---

Arquivos alterados (já coletado): !`git status --short`

Grave `.claude/HANDOFF.md` com **uma única chamada Write** (sobrescreve; não leia o arquivo antes, não rode comandos, não revise depois). É um resumo para uma sessão nova continuar sem esta conversa. No máximo 25 linhas, só fatos desta sessão:

- **Objetivo**: o que se está tentando fazer.
- **Feito**: o que já funciona.
- **Falta**: o que resta, em ordem.
- **Decisões**: escolhas feitas e o porquê (inclui o que foi descartado).
- **Arquivos-chave**: `caminho:Lx-y` e por que importam.
- **Estado dos testes**: resultado da última `vera` e, se falhou, onde.
- **Próximo passo**: UMA ação concreta para começar.

Não cole código, logs nem saídas de comandos.

Ao terminar, responda só: "Salvo. Para retomar: /clear e depois `leia .claude/HANDOFF.md e continue`."
