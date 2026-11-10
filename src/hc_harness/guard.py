"""Hook PreToolUse do Claude Code (`hc guard`). Só stdlib: roda a cada chamada de Bash/PowerShell."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Final

GUARD_DEFAULT_BLOCK: Final[frozenset[str]] = frozenset({"commit", "push"})
_GIT_VALUE_OPTS: Final[frozenset[str]] = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env",
})  # fmt: skip
_SEP_RE: Final[re.Pattern[str]] = re.compile(r"&&|\|\||\|&|\$\(|[;|&\n\r`()]")
_SHELLS: Final[frozenset[str]] = frozenset(
    {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"}
)
_SHELL_CMD_FLAGS: Final[frozenset[str]] = frozenset(
    {"-c", "-lc", "-command", "-c:", "/c"}
)


def _tokens(fragment: str) -> list[str]:
    lex = shlex.shlex(fragment, posix=True)
    lex.whitespace_split = True
    lex.escape = ""  # backslash é separador de caminho no Windows, não escape
    lex.commenters = ""
    try:
        return list(lex)
    except (
        ValueError
    ):  # aspas desbalanceadas (separador caiu dentro de uma string): seja conservador
        return fragment.split()


def _prog(token: str) -> str:
    return re.split(r"[\\/]", token.strip())[-1].lower().removesuffix(".exe")


def _git_subcommand(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in _GIT_VALUE_OPTS:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg.lower()
    return None


def find_blocked_git(
    command: str, blocked: frozenset[str], depth: int = 0
) -> str | None:
    """Acha `git <subcomando bloqueado>` em qualquer posição: após &&, ;, |, $(...), wrappers, caminho
    completo, opções globais (-C/-c) e shells aninhados (bash -c '...', pwsh -Command '...')."""
    if depth > 3:
        return None
    for fragment in _SEP_RE.split(command):
        toks = _tokens(fragment.strip())
        for i, tok in enumerate(toks):
            prog = _prog(tok)
            if prog == "git":
                sub = _git_subcommand(toks[i + 1 :])
                if sub in blocked:
                    return f"git {sub}"
            elif prog in _SHELLS:
                for j in range(i + 1, len(toks)):
                    if toks[j].lower() in _SHELL_CMD_FLAGS and j + 1 < len(toks):
                        nested = (
                            " ".join(toks[j + 1 :]) if prog == "cmd" else toks[j + 1]
                        )
                        hit = find_blocked_git(nested, blocked, depth + 1)
                        if hit:
                            return hit
                        break
    return None


# ---------------------------------------------------------------- regras de tokens e de escrita
# Ensinam o modelo a usar a ferramenta certa: bloqueiam e dizem qual é a alternativa.
# (O `git commit`/`git push` acima é regra dura e sempre vale; estes grupos podem ser desligados.)

GUARD_RULE_GROUPS: Final[frozenset[str]] = frozenset({"write", "read", "lockfile"})

_CODE_EXTS: Final[frozenset[str]] = frozenset({
    ".py", ".pyi", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx",
    ".md", ".rst", ".toml", ".cfg", ".ini", ".yaml", ".yml", ".js", ".ts", ".sh",
})  # fmt: skip
_READ_EXTS: Final[frozenset[str]] = _CODE_EXTS | {".json", ".txt"}
_LOCK_NAMES: Final[frozenset[str]] = frozenset({
    "uv.lock", "poetry.lock", "pdm.lock", "pipfile.lock", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "cargo.lock",
})  # fmt: skip
_WHOLE_READERS: Final[frozenset[str]] = frozenset(
    {"cat", "type", "get-content", "gc", "bat", "more", "less"}
)
_LOCK_READERS: Final[frozenset[str]] = _WHOLE_READERS | {
    "head", "tail", "sed", "grep", "egrep", "fgrep", "rg", "awk", "jq", "select-string", "sls",
}  # fmt: skip
_PS_WRITERS: Final[frozenset[str]] = frozenset(
    {"set-content", "add-content", "out-file", "sc", "ac"}
)
_GIT_SUMMARY_FLAGS: Final[frozenset[str]] = frozenset({
    "--stat", "--numstat", "--shortstat", "--name-only", "--name-status", "--summary", "--dirstat",
})  # fmt: skip

_REDIRECT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9&<>])>{1,2}\s*[\"']?([^\s\"'|;&<>()]+)"
)
_HEREDOC_RE: Final[re.Pattern[str]] = re.compile(
    r"((?<!<)<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\2)([^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)",
    re.DOTALL,
)
_HC_PAYLOAD_RE: Final[re.Pattern[str]] = re.compile(
    r"(\bhc(?:\.exe)?[ \t]+(?:edit|write)\b[^\n]*?)((?<!<)<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\3)([^\n]*)\n.*?\n[ \t]*\4[ \t]*(?=\n|$)",
    re.DOTALL,
)
_PS_HERE_RE: Final[re.Pattern[str]] = re.compile(
    r"@(['\"])[ \t]*\r?\n.*?\r?\n\1@[ \t]*\|[ \t]*hc(?:\.exe)?[ \t]+(?:edit|write)\b",
    re.DOTALL,
)
_PY_HEREDOC_RE: Final[re.Pattern[str]] = re.compile(
    r"\bpython[\w.]*[ \t]+(?:-[A-Za-z]+[ \t]+)*-[ \t]*(?:(?<!<)<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1)[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)",
    re.DOTALL,
)
_PY_WRITE_RE: Final[re.Pattern[str]] = re.compile(
    r"\.write_text\(|\.write_bytes\(|\bopen\([^)\n]*,\s*(?:mode\s*=\s*)?[\"'][wax][bt+]*[\"']"
)
_PY_PATH_RE: Final[re.Pattern[str]] = re.compile(
    "[\"'][^\"'\\n]*(?:" + "|".join(re.escape(e) for e in sorted(_CODE_EXTS)) + ")[\"']"
)

_MSG_WRITE: Final[str] = (
    "hc guard: writing files through the shell ({what}) is blocked. Use `Edit`/`Write`; if `Edit` fails "
    "(CRLF/whitespace) use `hc edit <file>` (SEARCH/REPLACE blocks on stdin, see `hc --help`), or "
    "`hc write <file>` for new files.\n"
)
_MSG_READ: Final[str] = (
    "hc guard: `{what}` on a source/text file is blocked (token-heavy). Use `hc show <file>:<symbol>` or "
    "`hc show <file>:L10-40`, `hc map <file>`, or `Read` with offset/limit.\n"
)
_MSG_LOCK: Final[str] = (
    "hc guard: reading lockfiles is blocked. Use `git diff --stat -- <lockfile>`; `uv` regenerates them.\n"
)


def strip_hc_payloads(command: str) -> str:
    """Tira o corpo de `hc edit/write <<EOF ... EOF` (e do here-string do PowerShell): é dado, não comando.
    Sem isso, um texto com `git commit` ou `sed -n` dentro do conteúdo seria barrado."""
    command = _HC_PAYLOAD_RE.sub(r"\1\2\5", command)
    return _PS_HERE_RE.sub(
        lambda m: "@@ | " + m.group(0).rsplit("|", 1)[1].strip(), command
    )


def _ext(token: str) -> str:
    return os.path.splitext(token.rstrip("/\\"))[1].lower()


def _strip_env(toks: list[str]) -> list[str]:
    i = 0
    while i < len(toks) and re.match(r"[A-Za-z_]\w*=", toks[i]):
        i += 1
    return toks[i:]


def _check_fragment(toks: list[str], enabled: frozenset[str]) -> str | None:
    if not toks:
        return None
    prog, args = _prog(toks[0]), toks[1:]
    flags = [a for a in args if a.startswith("-")]
    operands = [a for a in args if not a.startswith("-")]

    if "lockfile" in enabled and any(
        o.lower().endswith(tuple(_LOCK_NAMES)) for o in operands
    ):
        if prog in _LOCK_READERS:
            return _MSG_LOCK
        is_git_dump = prog == "git" and _git_subcommand(args) in {"diff", "show", "log"}
        if is_git_dump and not any(f in _GIT_SUMMARY_FLAGS for f in flags):
            return _MSG_LOCK

    if prog == "sed":
        short = [f for f in flags if not f.startswith("--")]
        if "write" in enabled and (
            any("i" in f[1:] for f in short)
            or any(f.startswith("--in-place") for f in flags)
        ):
            return _MSG_WRITE.format(what="sed -i")
        if (
            "read" in enabled
            and any("n" in f[1:] for f in short)
            and any(_ext(o) in _READ_EXTS for o in operands)
        ):
            return _MSG_READ.format(what="sed -n")
    elif (
        "read" in enabled
        and prog in _WHOLE_READERS
        and any(_ext(o) in _READ_EXTS for o in operands)
    ):
        return _MSG_READ.format(what=prog)
    elif (
        "write" in enabled
        and (prog == "tee" or prog in _PS_WRITERS)
        and any(_ext(o) in _CODE_EXTS for o in operands)
    ):
        return _MSG_WRITE.format(what=prog)
    return None


def _python_heredoc_write(command: str) -> str | None:
    for m in _PY_HEREDOC_RE.finditer(command):
        body = m.group(3)
        if _PY_WRITE_RE.search(body) and _PY_PATH_RE.search(body):
            return _MSG_WRITE.format(
                what="python heredoc that writes a source/doc file"
            )
    return None


def find_rule_violation(
    command: str, enabled: frozenset[str], depth: int = 0
) -> str | None:
    """Mensagem de bloqueio se o comando quebra alguma regra de escrita/leitura/lockfile, senão None.
    Espera o comando já sem payloads de `hc edit/write` (ver `strip_hc_payloads`)."""
    if depth > 3:
        return None
    outside = _HEREDOC_RE.sub(r"\1\4", command)  # corpos de heredoc não são comandos
    if "write" in enabled:
        for m in _REDIRECT_RE.finditer(outside):
            if _ext(m.group(1)) in _CODE_EXTS:
                return _MSG_WRITE.format(what=f"redirect to {m.group(1)}")
        if depth == 0 and (hit := _python_heredoc_write(command)):
            return hit
    for fragment in _SEP_RE.split(outside):
        toks = _strip_env(_tokens(fragment.strip()))
        if hit := _check_fragment(toks, enabled):
            return hit
        if toks and _prog(toks[0]) in _SHELLS:
            for j in range(1, len(toks)):
                if toks[j].lower() in _SHELL_CMD_FLAGS and j + 1 < len(toks):
                    nested = (
                        " ".join(toks[j + 1 :])
                        if _prog(toks[0]) == "cmd"
                        else toks[j + 1]
                    )
                    if hit := find_rule_violation(nested, enabled, depth + 1):
                        return hit
                    break
    return None


def _enabled_rules() -> frozenset[str]:
    raw = os.environ.get("HC_GUARD_RULES")
    if raw is None:
        return GUARD_RULE_GROUPS
    return (
        frozenset(x.strip().lower() for x in raw.split(",") if x.strip())
        & GUARD_RULE_GROUPS
    )


def run_guard() -> int:
    """Lê o JSON do hook PreToolUse no stdin. Exit 2 = bloqueia (stderr volta para o Claude); 0 = libera."""
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (json.JSONDecodeError, OSError):
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    env_list = {
        x.strip().lower()
        for x in os.environ.get("HC_GUARD_BLOCK", "").split(",")
        if x.strip()
    }
    clean = strip_hc_payloads(
        command
    )  # o texto de `hc edit/write <<EOF` é dado, não comando
    hit = find_blocked_git(clean, frozenset(env_list) or GUARD_DEFAULT_BLOCK)
    if hit is not None:
        sys.stderr.write(
            f"hc guard: `{hit}` is blocked in this environment. Do not run it or work around it. "
            "Show the user the proposed commit message / command instead and let them run it.\n"
        )
        return 2
    enabled = _enabled_rules()
    message = find_rule_violation(clean, enabled) if enabled else None
    if message is None:
        return 0
    sys.stderr.write(message)
    return 2
