# ADR 0012: Production APT hosting and signing are external release decisions

Status: Superseded for production distribution (2026-11-19)

## Context

The package must be APT-distributable, but repository hosting and production
signing keys must not live in the source repository.

## Decision

The repository proves distributability with `make test-apt-repo`
(`scripts/build-test-apt-repo.sh`), which uses an ephemeral signing key in an
isolated environment. Production infrastructure is chosen at deployment time.

## Consequences

No private keys or credentials are ever committed. The repository still
uses ephemeral signing keys for local verification.

## Subsequent decision (2026-11-19)

Dribia selected a public Launchpad PPA at `ppa:dribia/stable` as the official
Ubuntu distribution channel, replacing its previous private Artifact Registry
APT repository. Launchpad builds packages from signed Debian source uploads.
Production signing keys remain outside the source tree, with a protected CI
publisher planned for the next phase.

