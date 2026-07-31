# ADR 0004: Automatic signature excludes descriptions

Status: Accepted

## Context

Automatic launcher identity must group time entries without exploding on
free-text descriptions.

## Decision

Signature is `(workspace_id, project_id, task_id, sorted(tag_ids))`.
Descriptions are available only on manually created launchers.

## Consequences

One candidate per meaningful target; no launcher-per-description noise;
manual launchers can still pin a fixed description.
