# ADR 0013: UI built programmatically in Python instead of GtkBuilder/GResource templates

Status: Accepted

## Context

AGENTS.md § 6.2 suggests GtkBuilder `.ui` templates compiled into a
GResource, while § 7 allows small deviations that simplify implementation.

## Decision

Build all widgets programmatically in Python (`ui/*.py`). CSS is embedded in
`application.py`. `make resources` is a no-op.

## Consequences

Simpler iteration (no compile step, no template/handler indirection) with
identical resulting widgets and accessibility properties. Layer separation
is preserved; a future move to templates would be mechanical. The
`resources/` package-data hooks remain in `pyproject.toml` if that happens.
