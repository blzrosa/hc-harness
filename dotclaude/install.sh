#!/bin/sh
# Instala as customizações do Claude Code versionadas em dotclaude/.
#
# Uso:  sh dotclaude/install.sh
#
# Copia CLAUDE.md, agents/, commands/, protocols/ e settings.json para ~/.claude
# e o safe-commit para ~/.local/bin. Tudo que seria sobrescrito vai antes para
# ~/.claude/backups/dotclaude-<data>/. Não mexe em credenciais, sessões nem em
# ~/.claude.json (os servidores MCP são registrados à parte; veja o README.md).
#
# Variáveis:
#   CLAUDE_CONFIG_DIR  pasta de configuração (padrão: ~/.claude)
#   LUMI_DIR           clone do lumi-librarian (padrão: pasta irmã deste repositório)
#   BIN_DIR            destino do safe-commit (padrão: ~/.local/bin)
set -eu

src=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$src")
dest=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
bin=${BIN_DIR:-$HOME/.local/bin}
lumi=${LUMI_DIR:-$(dirname "$repo")/lumi-librarian}
backup="$dest/backups/dotclaude-$(date +%Y-%m-%d-%H%M%S)"

say() { printf '%s\n' "$*"; }
warn() { printf 'AVISO: %s\n' "$*" >&2; }

# Copia um arquivo, guardando antes o que existir no destino (se for diferente).
put() {
  from=$1
  to=$2
  rel=$3
  if [ -f "$to" ]; then
    if cmp -s "$from" "$to"; then
      return 0
    fi
    mkdir -p "$(dirname "$backup/$rel")"
    cp "$to" "$backup/$rel"
  fi
  mkdir -p "$(dirname "$to")"
  cp "$from" "$to"
  say "  $rel"
}

say "Instalando em $dest"
put "$src/CLAUDE.md" "$dest/CLAUDE.md" "CLAUDE.md"
for dir in agents commands protocols; do
  for f in "$src/$dir"/*.md; do
    name=$(basename "$f")
    put "$f" "$dest/$dir/$name" "$dir/$name"
  done
done

# settings.json: troca o marcador pelo caminho do clone do lumi-librarian.
if [ -d "$lumi" ]; then
  lumi=$(cd "$lumi" && pwd)
else
  warn "lumi-librarian não encontrado em $lumi (clone-o ou defina LUMI_DIR e rode de novo)"
fi
if command -v cygpath >/dev/null 2>&1; then
  lumi=$(cygpath -m "$lumi")
fi
tmp=$(mktemp)
sed "s|__LUMI_LIBRARIAN_DIR__|$lumi|" "$src/settings.json" >"$tmp"
put "$tmp" "$dest/settings.json" "settings.json"
rm -f "$tmp"

say "Instalando em $bin"
mkdir -p "$bin"
cp "$src/bin/safe-commit" "$bin/safe-commit"
chmod +x "$bin/safe-commit"
say "  safe-commit"

if [ -d "$backup" ]; then
  say "Arquivos anteriores guardados em $backup"
fi

case ":$PATH:" in
  *":$bin:"*) ;;
  *) warn "$bin não está no PATH; adicione-o no ~/.profile (ou rode 'uv tool update-shell')" ;;
esac
for cmd in selene vera lumine clara; do
  command -v "$cmd" >/dev/null 2>&1 || warn "'$cmd' não está no PATH: rode 'uv tool install .' na raiz do hc-harness"
done
for cmd in sofia aurora; do
  command -v "$cmd" >/dev/null 2>&1 || warn "'$cmd' não está no PATH: rode 'uv tool install .' na raiz do lumi-librarian"
done

say "Pronto. Faltam os servidores MCP e os plugins: veja dotclaude/README.md."
