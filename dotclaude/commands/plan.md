---
description: Planeja a tarefa no Opus e grava .claude/SPEC.md (não implementa)
argument-hint: <descrição da tarefa>
allowed-tools: Read, Grep, Glob, Agent, Edit(.claude/SPEC.md), Bash(lumine map:*), Bash(lumine find:*), Bash(lumine show:*), Bash(lumine impact:*), Bash(git status:*)
model: opus
---

Tarefa: $ARGUMENTS

Você só PLANEJA. Não edite código, não rode testes. Quem implementa depois é o Sonnet, lendo apenas o `.claude/SPEC.md` e sem nenhuma memória desta conversa, então o plano precisa ser autossuficiente.

## Como explorar (gastando pouco)
1. Pergunta que passa por mais de um arquivo ("onde X é usado", "como Y funciona"): agente `explorer`, uma pergunta fechada por chamada, em paralelo quando forem independentes.
2. Arquivo e símbolo já conhecidos: `lumine find <símbolo>`, `lumine map <pasta ou arquivo>`, `lumine show <arquivo>:<símbolo>` ou `Read` com offset/limit. Nunca arquivos inteiros grandes.
3. `lumine impact <arquivo>` para saber quais testes são afetados.
4. Se uma ambiguidade muda o desenho, faça no máximo 2 perguntas curtas antes de escrever o plano. Dúvida menor: decida e registre em **Riscos / decisões**.

## Formato do `.claude/SPEC.md` (sobrescreva; no máximo 80 linhas)
```
# <título>
**Objetivo**: 1 a 2 linhas, incluindo para que serve.
**Contexto**: fatos do código que valem para todas as etapas, com `caminho:Lx-y`; convenções a seguir.
**Fora de escopo**: o que NÃO fazer.
**Riscos / decisões**: o que foi escolhido e por quê; o que pode dar errado.

## Etapas
### [ ] 1. <nome curto>
- Arquivos: `caminho:Lx-y` — o que muda em cada um.
- Agente: coder | implementer | tester | writer
- Paralelo: <letra do grupo> (omita se a etapa depende da anterior)
- Fazer: o que implementar, em frases diretas.
- Testes: nome de cada teste e o que ele afirma (escritos antes do código).
- Pronto quando: critério observável além de "vera passa".
```
- Cada etapa deixa o projeto passando na `vera` sozinha e cabe em ~25 chamadas de ferramenta (até uns 5 arquivos, ~200 linhas novas). Ordene por dependência.
- **Agente**: `coder` (Haiku) quando a etapa já diz arquivos, assinaturas e comportamento e não sobra escolha, e escreva a etapa com esse nível de detalhe sempre que der; `implementer` (Sonnet) quando sobra julgamento; `tester` para etapa só de testes (use em parte delicada, antes da etapa de código); `writer` para documentação.
- **Paralelo**: mesma letra para etapas que não compartilham arquivo nem dependem uma da outra. Na dúvida, omita.
- Cada agente lê só o cabeçalho e a própria etapa: não espalhe informação necessária por outras etapas.
- Sem código no plano, exceto assinaturas e tipos quando forem decisão de design.
- Se o `.gitignore` não lista `.claude/SPEC.md` e `.claude/HANDOFF.md`, inclua isso na etapa 1.

## Ao terminar
Responda em 3 linhas: onde o plano foi salvo, a decisão mais importante e o próximo passo: `/clear` e depois `/implement` (executa etapa por etapa pelos agentes, no modelo da sessão).
