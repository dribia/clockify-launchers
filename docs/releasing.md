# Releasing

## Version bump

Update the version in all of these places (keep them identical):

1. `src/clockify_launchers/constants.py` — `VERSION`
2. `pyproject.toml` — `[project] version`
3. `debian/changelog` — new entry at the top (`dch` or manual)
4. `data/com.dribia.ClockifyLaunchers.metainfo.xml` — `<releases>` entry
5. `CHANGELOG.md` — move Unreleased content under the new version

## Verification

From a clean checkout:

```sh
make verify        # lint + typecheck + test + validate-data + ui-capture + ui-test + deb
```

Then packaging checks:

```sh
make deb           # build the .deb (scripts/build-deb.sh)
make lintian       # lintian --fail-on error
make smoke-install # install/run/remove in an isolated environment
make test-apt-repo # build a locally signed test APT repo with an ephemeral key,
                   # apt update, install by package name, smoke test, clean up
```

Run the packaging pipeline on both Ubuntu 24.04 and 26.04.

Also review UI screenshots (`make ui-review`) and record the assessment in
`docs/ui-review.md` before tagging.

## Production distribution

Production APT repository hosting and signing are **external deployment
decisions**, deliberately outside this repository. The repository only
proves APT-distributability via the ephemeral-key test repo flow.

**Never commit private signing keys, production repository credentials, or
API keys.** The test APT repo script generates and destroys its own
ephemeral key material.
