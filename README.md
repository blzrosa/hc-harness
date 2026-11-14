# hc-harness

Harness poliglota (Python/C/C++) baseada em AST e compressor de tokens para o
[Claude Code](https://claude.com/claude-code). Expõe quatro comandos:
`lumine` (navegar e editar), `vera` (verificar), `selene` (guardar) e `clara`
(auditar custo de tokens). O comando antigo `hc` continua funcionando com todos
os subcomandos, como alias.

## O que faz

- **Verificação incremental:** lê as mudanças do `git status`, calcula os
  arquivos e testes dependentes (grafo de imports reverso, baseado em AST) e
  executa só o necessário.
- **Pipeline:** `uv sync` (se `pyproject.toml`/`uv.lock` mudaram), `ruff check --fix`
  e `ruff format`, type check (pyright, com fallback para ty) e pytest em paralelo.
  Para C/C++: clang-format, build com cmake e ctest.
- **Saída enxuta:** `OK in 1.2 s` quando tudo passa; senão, só os blocos das
  ferramentas que falharam.
- **Navegação de código barata (`lumine`):** `map`, `find` e `show` devolvem
  esqueletos e trechos em vez de arquivos inteiros.
- **Guarda (`selene`):** hook `PreToolUse` que bloqueia `git commit`/`git push`,
  leituras caras de código via shell, escrita de arquivos por shell e leitura de lockfiles.
- **Auditoria (`clara`):** mede o custo de tokens das sessões do Claude Code.

## Requisitos

- Python 3.11 ou superior
- [uv](https://docs.astral.sh/uv/)
- Opcionais, usadas se estiverem instaladas: `ruff`, `pyright` ou `ty`,
  `pytest`, `clang-format`, `cmake`, `ctest`

Dependências de runtime: `tree-sitter`, `tree-sitter-c`, `tree-sitter-cpp`.
O extra `headroom` (`headroom-ai`) é opcional.

## Instalação

```bash
git clone https://github.com/blzrosa/hc-harness.git
cd hc-harness
uv sync
uv tool install .          # disponibiliza lumine, vera, selene, clara e hc globalmente
```

Depois de atualizar o código, reinstale com `uv tool install --reinstall .`.
Para desenvolvimento, use `uv run vera` ou `uv run python -m hc_harness`.

## Uso

| Comando novo | Equivale a | Descrição |
|---|---|---|
| `vera` | `hc` | Verificação incremental das mudanças atuais do git |
| `vera --all` | `hc --all` | Projeto inteiro: type check completo e toda a suíte de testes |
| `vera <arquivo> [...]` | `hc <arquivo> [...]` | Trata os arquivos como alterados |
| `lumine impact [arquivo ...]` | `hc impact` | Mostra quais testes uma mudança afeta, sem executar |
| `lumine map [caminho]` | `hc map` | Esqueleto AST (classes, assinaturas, linhas), paginado |
| `lumine find <símbolo>` | `hc find` | Definições e usos de um símbolo (máx. 25 usos) |
| `lumine show <arquivo>:<símbolo>` | `hc show` | Imprime só o corpo do símbolo (também `:L10-40`) |
| `lumine edit <arquivo> [--all]` | `hc edit` | Aplica blocos SEARCH/REPLACE lidos do stdin |
| `lumine write <arquivo>` | `hc write` | Cria arquivo a partir do stdin (`--force` para sobrescrever) |
| `selene` | `hc guard` | Hook `PreToolUse`: lê JSON no stdin e bloqueia comandos perigosos |
| `clara [caminho]` | (novo) | Auditoria de tokens das sessões |

Opções do `vera`: `--no-cache`, `--no-fix`, `-v`/`--verbose`, `--version` e
`--timeout=S` (orçamento total em segundos; padrão 540; também `VERA_TIMEOUT`).
Em `lumine map`: `--list`, `--prefix=P`, `--sym=S`, `--limit=N`, `--page=K`.

### clara

Sem caminho, `clara` lê as sessões em `~/.claude/projects`. Opções:
`--secoes=`, `--exemplos=`, `--top=`, `--desde=AAAA-MM-DD` e `--ate=AAAA-MM-DD`.

```bash
clara --desde=2026-11-01 --top=10
```

### Resultado

- Código de saída `0` = passou, `1` = falhas, `2` = erro de uso ou de git.
- `OK in 1.2 s (clean tree)`: sem mudanças, nada rodou.
- `OK ... (cached)`: arquivos idênticos à última execução que passou.
- `OK ... (skipped: ruff, pytest)`: essas ferramentas não estão instaladas.

### Formato do `lumine edit`

```text
lumine edit src/x.py <<'EOF'
<<<<<<< SEARCH
linhas antigas
=======
linhas novas (vazio = remove as linhas antigas)
>>>>>>> REPLACE
EOF
```

Se o texto contiver uma linha `=======`, use marcadores mais longos (8 ou mais `<`,
o mesmo número de `=` e `>`).

### Variáveis de ambiente

| Variável | Efeito |
|---|---|
| `HC_TYPECHECKER=ty\|pyright` | Força o type checker (padrão: pyright, com fallback para ty) |
| `HC_PLAIN=1` | Desativa a linha de progresso ao vivo |
| `VERA_TIMEOUT=S` | Orçamento total do `vera`, em segundos (padrão 540) |
| `HC_GUARD_BLOCK=commit,push` | Subcomandos git bloqueados pelo `selene` |
| `HC_GUARD_RULES=write,read,lockfile` | Grupos de regras extras do `selene` |

## Integração com o Claude Code

Registre o guard como hook `PreToolUse` para a ferramenta `Bash` em
`~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "selene" }]
      }
    ]
  }
}
```

Depois, oriente o agente no `CLAUDE.md` a rodar `vera` após cada edição, em vez de
chamar ruff, pyright ou pytest diretamente.

## Estrutura do projeto

```text
src/hc_harness/
  cli.py        ponto de entrada e despacho dos comandos
  pipeline.py   orquestração das etapas de verificação
  runner.py     execução das ferramentas externas
  index.py      índice de símbolos e grafo de imports
  symbols.py    extração de símbolos (AST / tree-sitter)
  mapview.py    comando `map`
  navigate.py   comandos `find` e `show`
  edit.py       comandos `edit` e `write`
  guard.py      hook `selene` (`hc guard`)
  compress.py   compressão da saída
  gitutil.py    integração com o git
  config.py     configuração
  ui.py         progresso no terminal
tests/          testes (inclui golden files)
tools/          utilitários: bash_audit.py, session_cost.py
```

## Testes

```bash
uv run vera --all
```

Os golden files em `tests/golden` são gerados por `tests/make_golden.py`.

## Licença

Defina a licença do projeto antes de publicar.
