# dotclaude: as customizações do Claude Code e o guia de máquina nova

Esta pasta guarda o que antes só existia em `~/.claude` e `~/.local/bin`, para que uma máquina
nova (Linux ou Windows) fique igual à anterior com um clone e um script.

## Repositórios

| Repositório | URL | O que traz |
|---|---|---|
| hc-harness | <https://github.com/blzrosa/hc-harness> | `vera`, `lumine`, `selene`, `clara`, `hc` e esta pasta |
| lumi-librarian | <https://github.com/blzrosa/lumi-librarian> | `sofia` (MCP e CLI do vault), `aurora` (hooks de sessão) e o plugin `aurora@sofia` |

Os dois são públicos. O vault `~/.brain` **não** está em nenhum deles e não deve ir para um
repositório público (veja o passo 6).

## O que há aqui

| Caminho | Vai para | Conteúdo |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | Instruções globais (harness, delegação, regras, Sofia) |
| `agents/` | `~/.claude/agents/` | `coder`, `committer`, `explorer`, `implementer`, `reviewer`, `tester`, `verifier`, `writer` |
| `commands/` | `~/.claude/commands/` | `/commit`, `/handoff`, `/implement`, `/plan`, `/plan-recursive`, `/plan-recursive-fable`, `/safe-commit` |
| `protocols/` | `~/.claude/protocols/` | Protocolo do `/plan-recursive` |
| `settings.json` | `~/.claude/settings.json` | Permissões, hook `selene`, plugins; o caminho do marketplace é preenchido na instalação |
| `bin/safe-commit` | `~/.local/bin/safe-commit` | Único caminho de commit liberado para o agente |
| `install.sh` | (roda no lugar) | Copia tudo acima, com backup do que for sobrescrito |

Fica de fora, de propósito: credenciais (`.credentials.json`), histórico, sessões, cache de
plugins e o `~/.claude.json`, que é estado da máquina. Os servidores MCP que moram nele são
recriados por comando no passo 7.

## Máquina nova, em ordem

A ordem importa: o `settings.json` registra o hook `selene` para todo comando de shell, então a
harness precisa estar no PATH antes de ele ser instalado.

### 1. Base

- `git`
- [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [Claude Code](https://code.claude.com/docs): `curl -fsSL https://claude.ai/install.sh | bash`
- `~/.local/bin` no PATH: `uv tool update-shell` e abrir um terminal novo

### 2. Clonar os dois repositórios lado a lado

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/blzrosa/hc-harness.git
git clone https://github.com/blzrosa/lumi-librarian.git
```

O `install.sh` procura o `lumi-librarian` na pasta irmã do `hc-harness`. Se ele estiver em outro
lugar, passe `LUMI_DIR=/caminho/lumi-librarian`.

### 3. Instalar a harness

```bash
cd ~/projects/hc-harness
uv sync
uv tool install .
```

### 4. Instalar a Sofia e a Aurora

```bash
cd ~/projects/lumi-librarian
uv sync
uv tool install --editable .
```

### 5. Ferramentas opcionais

O `vera` usa as que encontrar e avisa `(skipped: …)` para as que faltam.

```bash
uv tool install ruff
uv tool install pyright
uv tool install ty
uv tool install pytest
uv tool install headroom-ai     # MCP de compressão (headroom)
```

Para C/C++: `clang-format`, `cmake` e `ctest` pelo gerenciador de pacotes do sistema.

### 6. Trazer o vault

Copie a pasta `~/.brain` inteira da máquina antiga para `~/.brain` (rsync, pendrive ou um
repositório git **privado**). A pasta `.sofia/` é o índice; se ela não vier junto, `sofia index`
a reconstrói.

Para outro local, defina `SOFIA_VAULT` ou use `~/.config/sofia/config.toml`.

### 7. Instalar as customizações e registrar MCPs e plugins

```bash
cd ~/projects/hc-harness
sh dotclaude/install.sh
```

Depois, entrar no Claude Code uma vez para fazer o login (`claude`, depois `/login`) e registrar:

```bash
claude mcp add --scope user sofia -e SOFIA_VAULT=$HOME/.brain -- \
  uv run --directory ~/projects/lumi-librarian sofia mcp
claude mcp add --scope user headroom -- headroom mcp serve

claude plugin marketplace add ~/projects/lumi-librarian
claude plugin install aurora@sofia
claude plugin install frontend-design@claude-plugins-official
```

O Serena é registrado por projeto, dentro da pasta de cada um que o usa:

```bash
claude mcp add serena -- uvx --python 3.13 --from serena-agent serena start-mcp-server \
  --project-from-cwd --context claude-code --open-web-dashboard False
```

### 8. Conferir

```bash
cd ~/projects/hc-harness
vera --all                 # a suíte da harness passando no sistema novo
claude mcp list            # sofia e headroom conectados
sofia search harness       # o vault responde
```

Numa sessão nova do Claude Code: a linha da Aurora aparece no início, um comando de shell passa
pelo `selene` sem erro de hook, e `/commit` devolve uma proposta de mensagem.

Se **todo** comando de shell falhar com erro de hook, o `selene` não está no PATH do processo do
Claude Code: confira o passo 1 e reabra o terminal.

## Manter em dia

O `install.sh` copia, não cria links. Depois de mudar algo em `~/.claude` que deva valer em todas
as máquinas, copie o arquivo de volta para `dotclaude/` e commite; na outra máquina, `git pull` e
`sh dotclaude/install.sh` de novo. Ele só toca nos arquivos que mudaram e guarda a versão anterior
em `~/.claude/backups/dotclaude-<data>/`.

No `settings.json` daqui, o caminho do marketplace é o marcador `__LUMI_LIBRARIAN_DIR__`: ao
copiar de volta o seu `~/.claude/settings.json`, restaure o marcador antes de commitar.
