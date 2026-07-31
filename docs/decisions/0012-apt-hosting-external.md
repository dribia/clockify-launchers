# ADR 0012: Production APT hosting and signing are external release decisions

Status: Accepted

## Context

The package must be APT-distributable, but repository hosting and production
signing keys must not live in the source repository.

## Decision

The repository proves distributability with `make test-apt-repo`
(`scripts/build-test-apt-repo.sh`), which uses an ephemeral signing key in an
isolated environment. Production infrastructure is chosen at deployment time.

## Consequences

No private keys or credentials are ever committed; release documentation
covers the local verification flow only.
