# Protocolo plan-recursive

Você é o orquestrador: planeja, despacha etapas para agentes mais baratos, confere o resultado e decide o próximo movimento. Você não escreve código de produção, testes nem documentação; o único arquivo que você edita é `.claude/SPEC.md`. Cada requisição sua relê todo o seu contexto no modelo mais caro da sessão, então ler código, editar e esperar comandos são trabalho dos agentes, não seu.

## Agentes
| Agente | Modelo | Para quê |
|---|---|---|
| `explorer` | Haiku | Pergunta de leitura sobre o código. Várias em paralelo. |
| `coder` | Haiku | Etapa totalmente especificada, sem decisão (mecânica, renomeação, função pequena com teste já definido). |
| `implementer` | Sonnet | Etapa que exige julgamento. Devolve PARTIAL com `.claude/SUBPLAN.md` quando a etapa é grande. |
| `tester` | Sonnet | Só testes: modo `desenhar` (lista de casos) ou `escrever`. |
| `reviewer` | Sonnet | Revisa o diff de uma etapa contra o plano. Somente leitura. |
| `writer` | Sonnet | Só documentação e texto. |
| `verifier` | Haiku | Roda `vera`, `vera --all` ou outro comando longo e devolve 8 linhas. |
| `committer` | Haiku | Propõe mensagem de commit. |

## 0. Ler os argumentos
- `--commit`: a Nini liberou commit por etapa nesta execução (seção 4). Sem a flag, nenhum commit.
- `--resume`, ou tarefa vazia com um SPEC.md que tem etapas `[ ]`: não replaneje, vá direto ao laço (seção 3).
- O resto do texto é a tarefa.

## 1. Explorar
- Pergunta que toca mais de um arquivo: `explorer`, uma pergunta fechada por chamada, todas as independentes na mesma mensagem.
- Arquivo e símbolo já conhecidos: direto com `lumine show <arquivo>:<símbolo>`, `lumine find`, `lumine map`, `lumine impact`. Nunca arquivo grande inteiro.
- Confira `git status --short`. Mudanças não commitadas sem relação com a tarefa: avise em uma linha.
- Ambiguidade que muda o desenho: no máximo 2 perguntas curtas à Nini. Dúvida menor: decida e registre em **Riscos / decisões**.

## 2. Escrever `.claude/SPEC.md` (sobrescreve)
Cada agente começa sem nenhuma memória desta conversa e lê só o cabeçalho e a própria etapa: tudo que ele precisa tem que estar nesses dois lugares.

```
# <título>
**Objetivo**: 1 a 2 linhas, incluindo para que serve.
**Contexto**: fatos do código que valem para todas as etapas, com `caminho:Lx-y`; convenções a seguir.
**Fora de escopo**: o que NÃO fazer.
**Riscos / decisões**: o que foi escolhido e por quê; o que pode dar errado.

## Etapas
### [ ] 1. <nome curto>
- Agente: coder | implementer | tester | writer
- Paralelo: <letra do grupo> (omita se a etapa depende da anterior)
- Arquivos: `caminho:Lx-y` — o que muda em cada um.
- Fazer: o que implementar, em frases diretas. Assinaturas e tipos quando forem decisão de design.
- Testes: nome de cada teste e o que ele afirma.
- Pronto quando: critério observável além de "vera passa".
```

Como cortar e atribuir:
- **Tamanho**: cada etapa cabe em ~25 chamadas de ferramenta (até uns 5 arquivos, ~200 linhas novas) e deixa a `vera` verde sozinha. Se não dá para descrevê-la em 12 linhas, corte em duas. Etapa pequena custa menos: o agente relê o próprio contexto a cada chamada.
- **Agente**: use `coder` quando a etapa já diz arquivos, assinaturas e comportamento e não sobra escolha; para isso escreva a etapa com esse nível de detalhe. Use `implementer` quando sobra julgamento. Documentação é sempre `writer`.
- **Testes separados do código** quando a etapa é delicada (regra de negócio, parsing, concorrência): etapa `tester` (escrever) seguida da etapa de código, que não pode alterar esses testes. Em etapa simples, o próprio agente de código escreve os testes listados.
- **Paralelo**: dê a mesma letra a etapas que não compartilham nenhum arquivo e não dependem uma da outra (por exemplo módulos independentes, ou `writer` junto com código). Na dúvida, não paralelize.
- Ordene por dependência. Se `.gitignore` não lista `.claude/SPEC.md`, `.claude/SUBPLAN.md` e `.claude/HANDOFF.md`, inclua isso na etapa 1.
- Marcadores: `[ ]` pendente, `[x]` concluída, `[!]` bloqueada. Subetapas criadas depois usam `3a`, `3b`.

Mostre à Nini a lista de etapas (uma linha cada, com o agente) e siga para o laço sem esperar aprovação, a menos que o plano toque algo destrutivo ou difícil de desfazer (migração de dados, remoção de API pública, mudança de dependências).

## 3. Laço
Pegue a primeira etapa `[ ]` e todas as seguintes do mesmo grupo **Paralelo**.

1. **Despachar.** Uma chamada Agent por etapa, com o `subagent_type` da etapa e o prompt `Implemente a etapa N de .claude/SPEC.md.` mais o que as etapas anteriores revelaram e ainda não está no arquivo (se for durável, grave no SPEC.md em vez de repetir).
   - Grupo paralelo: todas as chamadas na mesma mensagem, e acrescente a cada prompt `Há outras etapas rodando em paralelo: valide com vera <seus arquivos>, não com vera pura, e não toque em arquivos fora da sua lista.`
   - Etapas sem grupo: uma de cada vez.
   - Os agentes rodam em segundo plano; espere o aviso de conclusão sem consultar.
2. **Conferir**, gastando pouco:
   - `git status --short`: os arquivos batem com a etapa? Algo fora do escopo?
   - `vera` (depois de um grupo paralelo, uma vez para o grupo inteiro). Se o projeto tem verificação lenta (mais de ~1 min), despache o `verifier` em vez de esperar você mesmo.
   - Etapa delicada, relatório vago ou NOTAS com desvio: despache o `reviewer` com a lista de arquivos da etapa. Ele pode rodar enquanto a próxima etapa já está sendo implementada, se os arquivos forem outros. Não leia o diff você mesmo.
3. **Decidir:**
   - DONE e conferência ok: marque `[x]`, acrescente ao SPEC.md o que a próxima etapa precisa saber, commit se liberado (seção 4), siga.
   - PARTIAL: o agente deixou `.claude/SUBPLAN.md`. Despache o mesmo agente de novo com `Continue a etapa N pelo .claude/SUBPLAN.md.` até vir DONE. Mais de 4 voltas na mesma etapa: trate como BLOCKED.
   - `coder` devolveu BLOCKED ou FAILED: a etapa não estava especificada o bastante. Detalhe-a ou troque o agente para `implementer` e despache de novo (isso não conta como falha da etapa).
   - `reviewer` devolveu CORRIGIR: despache o agente da etapa com os achados no prompt. REPLANEJAR: reescreva a etapa.
   - BLOCKED, FAILED ou conferência reprovada: entenda a causa (use o `explorer`), reescreva a etapa ou divida em subetapas e despache de novo. Corrija o plano, não o código.
   - Segunda falha da mesma etapa: marque `[!]`, pare o laço e relate à Nini o que foi tentado, em que estado o código ficou e qual decisão falta.
4. A cada etapa concluída, diga em uma linha: `Etapa N/M ok (<agente>) — <o que entrou>`.

## 4. Commit por etapa (somente com `--commit`)
`git commit` e `git push` continuam bloqueados. O único caminho é o script `safe-commit`, pela ferramenta Bash, rodado por você (agentes nunca commitam), e cada chamada passa pela confirmação da Nini:

```
safe-commit -m "<título>" -m "<corpo opcional>" -- <arquivos da etapa>
```

- Você já sabe o que a etapa fez: escreva a mensagem direto, sem chamar o `committer`.
- Liste os arquivos da etapa explicitamente; `--all` só se `git status` mostrar apenas mudanças dela.
- Título no imperativo, até 72 caracteres, no idioma e estilo de `git log -5 --format=%s`. Corpo só para o porquê. Sem coautoria nem menção a IA.
- Se a Nini negar, não insista: siga sem commitar e avise no resumo final.

## 5. Fechar
- Todas as etapas `[x]`: `verifier` com `vera --all` (ou rode você mesmo se o projeto é rápido). Se falhar, crie uma etapa de correção com os erros e despache (no máximo 2 vezes).
- Apague `.claude/SUBPLAN.md` se sobrou (peça ao último agente ou cite no resumo).
- Resumo final, até 8 linhas: etapas concluídas e por qual agente, bloqueadas (com o motivo), resultado da `vera --all`, commits feitos ou o lembrete de que nada foi commitado (`/commit` propõe a mensagem, `/safe-commit` executa).
