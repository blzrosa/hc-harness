# hc-harness

Harness poliglota (Python/C/C++) baseada em AST e compressor de tokens para o
[Claude Code](https://claude.com/claude-code). Expõe o comando `hc`, que roda
só as verificações afetadas pela sua mudança e devolve uma saída compacta.

## O que faz

- **Verificação incremental:** lê as mudanças do `git status`, calcula os
  arquivos e testes dependentes (grafo de imports reverso, baseado em AST) e
  executa só o necessário.
- **Pipeline:** `uv sync` (se `pyproject.toml`/`uv.lock` mudaram), `ruff check --fix`
  e `ruff format`, type check (pyright, com fallback para ty) e pytest em paralelo.
  Para C/C++: clang-format, build com cmake e ctest.
- **Saída enxuta:** `OK in 1.2 s` quando tudo passa; senão, só os blocos das
  ferramentas que falharam.
- **Navegação de código barata:** `map`, `find` e `show` devolvem esqueletos e
  trechos em vez de arquivos inteiros.
- **Guarda (`hc guard`):** hook `PreToolUse` que bloqueia `git commit`/`git push`,
  leituras caras de código via shell, escrita de arquivos por shell e leitura de lockfiles.

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
uv tool install .          # disponibiliza o comando `hc` globalmente
```

Para desenvolvimento, use `uv run hc` ou `uv run python -m hc_harness`.

## Uso

| Comando | Descrição |
|---|---|
| `hc` | Verificação incremental das mudanças atuais do git |
| `hc --all` | Projeto inteiro: type check completo e toda a suíte de testes |
| `hc <arquivo> [...]` | Trata os arquivos como alterados |
| `hc impact [arquivo ...]` | Mostra quais testes uma mudança afeta, sem executar |
| `hc map [caminho]` | Esqueleto AST (classes, assinaturas, linhas), paginado |
| `hc find <símbolo>` | Definições e usos de um símbolo (máx. 25 usos) |
| `hc show <arquivo>:<símbolo>` | Imprime só o corpo do símbolo (também `:L10-40`) |
| `hc edit <arquivo> [--all]` | Aplica blocos SEARCH/REPLACE lidos do stdin |
| `hc write <arquivo>` | Cria arquivo a partir do stdin (`--force` para sobrescrever) |
| `hc guard` | Hook `PreToolUse`: lê JSON no stdin e bloqueia comandos perigosos |

Opções: `--no-cache`, `--no-fix`, `-v`/`--verbose`, `--version`.
Em `map`: `--list`, `--prefix=P`, `--sym=S`, `--limit=N`, `--page=K`.

### Resultado

- Código de saída `0` = passou, `1` = falhas, `2` = erro de uso ou de git.
- `OK in 1.2 s (clean tree)`: sem mudanças, nada rodou.
- `OK ... (cached)`: arquivos idênticos à última execução que passou.
- `OK ... (skipped: ruff, pytest)`: essas ferramentas não estão instaladas.

### Formato do `hc edit`

```text
hc edit src/x.py <<'EOF'
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
| `HC_GUARD_BLOCK=commit,push` | Subcomandos git bloqueados pelo `hc guard` |
| `HC_GUARD_RULES=write,read,lockfile` | Grupos de regras extras do `hc guard` |

## Integração com o Claude Code

Registre o guard como hook `PreToolUse` para a ferramenta `Bash` em
`~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "hc guard" }]
      }
    ]
  }
}
```

Depois, oriente o agente no `CLAUDE.md` a rodar `hc` após cada edição, em vez de
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
  guard.py      hook `hc guard`
  compress.py   compressão da saída
  gitutil.py    integração com o git
  config.py     configuração
  ui.py         progresso no terminal
tests/          testes (inclui golden files)
tools/          utilitários: bash_audit.py, session_cost.py
```

## Testes

```bash
uv run hc --all
```

Os golden files em `tests/golden` são gerados por `tests/make_golden.py`.

## Licença

Defina a licença do projeto antes de publicar.
