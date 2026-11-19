# Releasing Clockify Launchers

## Current distribution status

The public distribution target is the [Dribia Stable Launchpad PPA](https://launchpad.net/~dribia/+archive/ubuntu/stable), `ppa:dribia/stable`.
The previous private Google Artifact Registry APT publisher has been retired
from this repository. **Launchpad publishing is not yet automated or live.**
Do not announce PPA installation until a source upload has built successfully
for the advertised Ubuntu release.

GitHub releases remain useful for changelogs and release tags. The
`release.yml` workflow creates a draft GitHub release after a version-bump
PR is merged; publishing that draft no longer uploads an APT package until
the Launchpad workflow is added.

## Version bump

Keep these version locations consistent:

1. `src/clockify_launchers/constants.py` — `VERSION`
2. `pyproject.toml` — `[project] version`
3. `debian/changelog` — a new versioned entry
4. `data/com.dribia.ClockifyLaunchers.metainfo.xml` — `<releases>`
5. `CHANGELOG.md` — move unreleased notes under the new version

Use `make bump VERSION=patch` (or `minor` / `major`) locally, or run
the GitHub Actions **bump** workflow to open a version-bump PR.

## Verification

On a clean checkout, run:

```sh
make verify         # lint, types, tests, desktop metadata, UI and .deb build
make lintian        # check the binary .deb
make smoke-install  # installs and removes a built .deb (requires sudo)
make test-apt-repo # local ephemeral-key APT repository test
```

Once the Debian source-package migration PR is merged, also run:

```sh
make source         # unsigned Debian source package in dist/source/
```

The source package will use Debian source format `3.0 (quilt)` and an
upstream `.orig.tar.xz`; Launchpad requires a signed **source** upload rather
than our prebuilt `.deb`.

Verify packaging on Ubuntu 24.04 (noble) and Ubuntu 26.04 (resolute).
The supported release must be reflected in `debian/changelog` for each
upload, and each release needs a Debian version that upgrades cleanly from
previously installed versions.

Review the UI screenshots with `make ui-review` and record the assessment
in `docs/ui-review.md` before tagging.

## GitHub release flow

1. Trigger the **bump** workflow (or make a version-bump PR).
2. Review `CHANGELOG.md`, the PR, tests and package build.
3. Merge the PR; the **release** workflow creates a draft GitHub release.
4. Review the draft and publish it when ready.

**Publishing the GitHub release currently does not deploy packages to the
PPA.** Do not treat the release as installed/distributed until Launchpad has
finished its separate builds.

## Planned PPA publishing (Phase 2)

The first package upload should be verified manually before enabling the
GitHub Actions release publisher:

1. Create or reuse an OpenPGP key, register its *public* fingerprint with
   the personal Launchpad account authorized for the `dribia` team.
2. Build a clean source package and sign its `.dsc` and `_source.changes`
   files using the corresponding private key.
3. Upload it with `dput ppa:dribia/stable <signed_source.changes>`.
4. Wait for Launchpad to build and publish it. Test installation on a clean
   supported Ubuntu system.
5. Automate the same signed source-upload flow in a **protected** GitHub
   Actions environment, with signing material in encrypted environment secrets.

Never commit private keys, passphrases, API keys or production APT credentials
to the repository. Launchpad signs the published repository independently
of the personal OpenPGP key that authenticates source uploads.

Once PPA builds are available, installation is:

```sh
sudo add-apt-repository ppa:dribia/stable
sudo apt update
sudo apt install dribia-clockify-launchers
```

Normal `apt upgrade` then provides package updates.
