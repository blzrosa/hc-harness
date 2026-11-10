"""Regras novas do `hc guard`: escrita pelo shell, leitura cara, lockfiles. E o que NÃO deve ser barrado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixture import default_env_with_src, default_prefix, run_hc

from hc_harness.guard import GUARD_RULE_GROUPS, find_rule_violation, strip_hc_payloads

BLOCKED_WRITE = [
    "sed -i 's/a/b/' src/a.py",
    "sed -i.bak 's/a/b/' src/a.py",
    "sed --in-place 's/a/b/' a.py",
    "cd x && sed -ni 's/a/b/p' src/a.py",
    "cat > src/a.py <<'EOF'\nx = 1\nEOF",
    "cat >> notes.md <<EOF\nhi\nEOF",
    "cat <<'EOF' > src/a.py\nx = 1\nEOF",
    "echo 'x' > setup.cfg",
    "printf 'a' >> src/a.py",
    "tee src/a.py <<EOF\nhi\nEOF",
    "python - <<'EOF'\np='CHANGELOG.md'\ns=open(p).read()\nopen(p,'w').write(s)\nEOF",
    "python3 - <<EOF\nfrom pathlib import Path\nPath('src/a.py').write_text('x')\nEOF",
    "uv run python - <<'EOF'\nopen('README.md', 'w').write('x')\nEOF",
    "Set-Content -Path src/a.py -Value x",
    "bash -c \"sed -i 's/a/b/' src/a.py\"",
]
BLOCKED_READ = [
    "sed -n 250,256p README.md",
    "sed -n '1,10p' src/a.py",
    "cd x && sed -n 5p pyproject.toml",
    "cat tools/bench_hash.py",
    "cat README.md CHANGELOG.md",
    "cat -n src/a.py",
    "type src\\a.py",
    "Get-Content src/a.py",
]
BLOCKED_LOCK = [
    "cat uv.lock",
    "head -50 uv.lock",
    "grep -n foo uv.lock",
    "git diff uv.lock",
    "git diff pyproject.toml && git diff uv.lock | head -80",
    "git show HEAD:uv.lock",
    "git diff -- poetry.lock",
]
ALLOWED = [
    "sed -n 1,5p",
    "sed 's/a/b/' src/a.py",
    "git diff --stat uv.lock",
    "git diff --stat -- uv.lock",
    "git add uv.lock",
    "git status",
    "uv lock",
    "uv sync",
    "grep -rn foo src/",
    "head -5 src/a.py",
    "tail -20 build.log",
    "cat >/dev/null <<'EOF'\nhello\nEOF",
    "cat <<'EOF'\nhello\nEOF",
    "python x.py > out.txt",
    "python x.py > result.json",
    "uv run python bench.py 2>&1 | tail -5",
    "pytest -q 2>&1",
    "ruff check src",
    "hc",
    "hc --all",
    "hc show src/a.py:Foo",
    "hc map src",
    "python - <<'EOF'\nimport json\njson.dump({}, open('out.json', 'w'))\nEOF",
    "python - <<'EOF'\nprint(open('src/a.py').read()[:10])\nEOF",
    "git log -5 --format=%s",
    "ls -la",
    # o conteúdo de hc edit/write é DADO: não pode ser barrado por parecer comando
    "hc edit src/a.py <<'EOF'\n<<<<<<< SEARCH\ncat > x.py\nsed -i s/a/b/ y.py\n=======\ngit push\n>>>>>>> REPLACE\nEOF",
    "hc write notes.md <<'EOF'\ngit commit -m x\nsed -n 1p a.py\ncat uv.lock\nEOF",
    "@'\ngit commit -m x\nsed -n 1p a.py\n'@ | hc write notes.md",
]


@pytest.mark.parametrize("command", BLOCKED_WRITE + BLOCKED_READ + BLOCKED_LOCK)
def test_blocked(command: str) -> None:
    assert (
        find_rule_violation(strip_hc_payloads(command), GUARD_RULE_GROUPS) is not None
    ), command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed(command: str) -> None:
    assert find_rule_violation(strip_hc_payloads(command), GUARD_RULE_GROUPS) is None, (
        command
    )


def test_messages_point_to_the_alternative() -> None:
    w = find_rule_violation("sed -i s/a/b/ a.py", GUARD_RULE_GROUPS)
    r = find_rule_violation("sed -n 1,5p a.py", GUARD_RULE_GROUPS)
    k = find_rule_violation("cat uv.lock", GUARD_RULE_GROUPS)
    assert w is not None and "hc edit" in w and "Edit" in w
    assert r is not None and "hc show" in r and "Read" in r
    assert k is not None and "git diff --stat" in k


def test_groups_can_be_disabled_individually() -> None:
    cmd_read, cmd_write, cmd_lock = (
        "sed -n 1,5p a.py",
        "sed -i s/a/b/ a.py",
        "cat uv.lock",
    )
    assert find_rule_violation(cmd_read, frozenset({"write", "lockfile"})) is None
    assert find_rule_violation(cmd_write, frozenset({"read", "lockfile"})) is None
    assert find_rule_violation(cmd_lock, frozenset({"read", "write"})) is None
    assert find_rule_violation(cmd_lock, frozenset()) is None


def _guard(cmd: str, tmp_path: Path, env: dict[str, str] | None = None):
    return run_hc(
        default_prefix(),
        ["guard"],
        tmp_path,
        tmp_path,
        stdin=json.dumps({"tool_input": {"command": cmd}}),
        extra_env=default_env_with_src(env),
    )


def test_cli_blocks_with_message_and_exit_2(tmp_path: Path) -> None:
    cp = _guard("sed -n 1,5p src/a.py", tmp_path)
    assert cp.returncode == 2
    assert "hc show" in cp.stderr
    assert cp.stdout == ""


def test_cli_hc_payload_with_git_commit_text_is_allowed(tmp_path: Path) -> None:
    assert (
        _guard("hc write notes.md <<'EOF'\ngit commit -m x\nEOF", tmp_path).returncode
        == 0
    )


def test_cli_git_commit_after_a_payload_is_still_blocked(tmp_path: Path) -> None:
    cp = _guard("hc write notes.md <<'EOF'\nok\nEOF\ngit commit -m x", tmp_path)
    assert cp.returncode == 2
    assert "git commit" in cp.stderr


def test_cli_env_switches_rule_groups_but_never_git(tmp_path: Path) -> None:
    assert (
        _guard(
            "sed -n 1,5p a.py", tmp_path, {"HC_GUARD_RULES": "write,lockfile"}
        ).returncode
        == 0
    )
    assert _guard("sed -n 1,5p a.py", tmp_path, {"HC_GUARD_RULES": ""}).returncode == 0
    assert _guard("git commit -m x", tmp_path, {"HC_GUARD_RULES": ""}).returncode == 2
