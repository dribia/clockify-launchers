# ADR 0011: Custom-field editing stays outside the core MVP

Status: Accepted

## Context

Clockify can reject new time entries when required custom fields are
missing, but full custom-field editing is significant scope.

## Decision

Keep a schema field for optional custom-field values, detect and clearly
surface required-custom-field API errors, and mark affected launchers as
needing attention — but do not build a custom-field editor unless the target
workspace proves it necessary.

## Consequences

Errors are handled correctly and never cause retry loops or premature timer
stops; editing remains a later enhancement.
