# ADR 0014: ty for type checking; uv venv with system site packages

Status: Accepted

## Context

AGENTS.md specifies mypy, but the repository owner chose ty. PyGObject
cannot be pip-installed cleanly and is provided by the distribution.

## Decision

- Use `ty` (`make typecheck` runs `uv run --with ty ty check src`) instead
  of mypy, per owner decision.
- `make bootstrap` creates a uv-managed venv with `--system-site-packages`
  so the system `python3-gi`/GTK stack is visible while pip dependencies
  (`httpx`, dev tools) stay isolated.

## Consequences

Fast type checking and reproducible dev environments; the venv depends on
system GI packages being installed (bootstrap prints the apt list).
