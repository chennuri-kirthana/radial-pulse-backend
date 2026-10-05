# CLAUDE.md

**Read [AGENTS.md](AGENTS.md) first — it is the single source of truth for AI agents in this
repo.** This file only adds Claude-specific notes and must never contradict AGENTS.md.

- Use `make <target>` (see `make help`); Python runs through `uv run`.
- When a task needs a decision listed as open in `docs/architecture/decisions.md`, stop and ask.
- Plan changes that touch migrations + API contract before editing: list the files first.
- Plain English in docs and messages: the team prefers simple words and short sentences.
