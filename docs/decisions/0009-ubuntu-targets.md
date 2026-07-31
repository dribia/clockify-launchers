# ADR 0009: Target Ubuntu 24.04 LTS and 26.04 LTS

Status: Accepted

## Context

The app depends on GTK 4, libadwaita, PyGObject, and libsecret from the
distribution.

## Decision

Ubuntu 24.04 LTS is the minimum supported platform; 26.04 LTS is also
tested. libadwaita usage is limited to APIs available in 1.5.

## Consequences

No newer GTK/libadwaita APIs without a 1.5-compatible fallback; packaging is
verified against both releases.
