## Harness — `vera`, `lumine`, `selene`, `clara` (`hc` still works as an alias)

- `vera` — verification. Run it after editing code, instead of ruff / pyright / ty / pytest / ctest / `uv sync`.
  `vera` checks the current git changes, `vera <files>` treats those files as changed, `vera --all` checks the whole
  project (once before declaring a task done). It auto-fixes and formats your files: don't hand-fix imports or
  formatting. Run it alone, no `| tail` / `| grep`.
- `lumine` — read and edit code: `lumine find <symbol>`, `lumine show <file>:<symbol>` (or `:L10-40`),
  `lumine map <path>`, `lumine impact <file>`, `lumine edit <file>` when `Edit` fails on CRLF. Use these or `Read`
  with offset/limit; never `cat`, `sed -n`, `head` or `tail` on source files.
- `selene` — the guard that runs before every shell command. When it blocks, the message names the offending part
  and its replacement: change that part, don't work around it.
- `clara` — token cost audit of past sessions. Only when asked about cost.

### Reading `vera`
- `OK in 1.2 s` → passed. Stop. `(clean tree)` / `(cached)` → nothing changed since the last pass and nothing ran:
  don't re-run without changing code. `(skipped: …)` → that tool isn't installed: tell the user, don't install it.
- Otherwise only failures are printed, one `=== TOOL ===` block each. Fix the first errors, then re-run.
- `=== TIMEOUT ===` → the time budget ran out; the block names the stage and the time of each one. Don't re-run the
  same command: narrow it with `vera <files>` or hand it to the `verifier` agent.
- Exit code: 0 = pass, 1 = failures or timeout, 2 = usage / git error.

### Delegation (I explicitly authorize and request this)
- **Investigation → `explorer` agent**: any question touching more than one file ("where is X used", "how does Y
  work"), with the question as the prompt. Don't substitute `Explore` or `general-purpose`. Read directly only when
  you already know the exact file and range.
- **Written plan → agents**, when I ask or when running `/implement` / `/plan-recursive`: `coder`, `implementer`,
  `tester`, `writer`, `reviewer`. One step of `.claude/SPEC.md` per call; in parallel only within the same `Paralelo`
  group. Check each report against `git status --short` and `vera`.
- **Long commands → `verifier` agent**; **commit messages → `committer` agent**. Never wait with `sleep` / `until` /
  `for` loops.

### Hard rules
- **Never run `git commit` or `git push`** (any form, including `git -C`, aliases or `bash -c`). They are blocked.
  When work is ready, show the proposed commit message and let the user commit.
- **`safe-commit` is the only way to commit, and only when the user released it**: they ran `/safe-commit`, passed
  `--commit` to `/plan-recursive`, or said so in this conversation for the changes at hand. A release covers that
  work only, never later changes. Run it through the Bash tool: `safe-commit -m "<title>" [-m "<body>"] -- <files>`
  (`--all` only when every change belongs to the commit). No co-author or AI lines in the message. If the
  confirmation prompt is denied, stop: don't retry or look for another route. Subagents never commit. Never push.
- Edit with `Edit`, create files with `Write`. Never modify or create files through Bash (`sed -i`, `tee`,
  `cat > file`, `python - <<EOF`). Never read or edit lockfiles.
- Don't edit `~/.ai-harness/state/` (harness caches and dataset).
- Always add `.claude/SPEC.md`, `.claude/SUBPLAN.md` and `.claude/HANDOFF.md` to the `.gitignore` in projects.

## Sofia — Nini's second brain (Obsidian vault in `~/.brain`)

The MCP server `sofia` indexes the vault (text search + link graph, no LLM, compact results). In any folder, when a
question may involve Nini's notes, projects, decisions or past sessions, query Sofia before reading files:
- `sofia_search` first; `sofia_get` for one specific note; `sofia_neighbors` / `sofia_path` for the link graph;
  `sofia_tags` / `sofia_recent` to browse.
- Never rewrite or delete Nini's notes. Write only via `sofia_capture` (`00-inbox/`) and `sofia_log_session`
  (`70-sessions/`); never edit `.sofia/`.
- Refer to the user as "a Nini" (third person, feminine) in anything written to the vault.
