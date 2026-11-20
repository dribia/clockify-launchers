# Releasing Clockify Launchers

Clockify Launchers is distributed through the public [Dribia Stable Launchpad
PPA](https://launchpad.net/~dribia/+archive/ubuntu/stable) (`ppa:dribia/stable`).
Launchpad builds and signs the user-installable Debian packages from signed
source uploads. We publish **Ubuntu 24.04 (noble)** and **26.04 (resolute)**
individually; check the [PPA package list](https://launchpad.net/~dribia/+archive/ubuntu/stable/+packages)
for their live publication status.

## Release process

1. Run the GitHub Actions **bump** workflow with `patch`, `minor` or `major`.
   Review and merge the generated version-bump PR after CI passes.
2. The existing `release.yml` workflow creates a **draft GitHub Release**
   at the corresponding `vX.Y.Z` tag. Review its notes and the tag.
3. **Publish** the GitHub Release when ready. This starts the
   `publish-ppa.yml` workflow, which uses the protected `ppa-production`
   GitHub Actions environment. Approve the environment deployment as required.
4. The workflow builds two source uploads, signs them with a Launchpad-authorized
   OpenPGP key, and uploads them to `ppa:dribia/stable` with `dput`.
5. Verify **Accepted**, **Successfully built**, and **Published** on Launchpad
   for each target series. A green GitHub Actions run alone proves only that
   the uploads were sent, **not** that Launchpad built or published the packages.
6. Test on clean Ubuntu 24.04 and Ubuntu 26.04 desktop installations; check
   `apt-cache policy dribia-clockify-launchers`, install the package, and
   launch the GUI. Future upgrades are delivered by APT.

The source versions for a release like `v0.5.2` are deliberately different:
`0.5.2-1~ppa1~ubuntu24.04.1` (noble) and
`0.5.2-1~ppa1~ubuntu26.04.1` (resolute). Launchpad requires version
uniqueness across series. These packages are built from identical upstream
source tarballs.

**Do not publish the existing `v0.5.1` draft to test automation.**
That version has already been uploaded manually. Use a new patch release
(`v0.5.2` or later) for the first end-to-end CI/CD test.

## Set up the signing environment (one-time repository administration)

The GitHub repository owner must create **Settings → Environments →
`ppa-production`**, enable **required reviewers**, and protect release tags
from rewriting or deletion. Review the deployment branch/tag restriction:
the release workflow runs from a `vX.Y.Z` tag, not from a push to `main`.

Configure the following entries **in the environment**, not as repository
plaintext variables or files:

| Name | Kind | Content |
| --- | --- | --- |
| `PPA_GPG_PRIVATE_KEY` | Secret | The ASCII-armored private key whose public key is registered on the Launchpad upload account |
| `PPA_GPG_PASSPHRASE` | Secret | The private key passphrase |
| `PPA_GPG_FINGERPRINT` | Variable | The full public OpenPGP fingerprint (40 hexadecimal characters) |

The authorized personal Launchpad account must be a member of the `dribia`
team with permission to upload to its PPA. **Never commit or paste the
private key or passphrase in issues, PRs, logs, or chat.** The PPA's
repository signing key is generated and managed by Launchpad and is
independent of the upload key.

To set the private-key secret without printing it or writing it to a file,
use the GitHub CLI from the machine where your private key resides:

```sh
# Replace the fingerprint with your own Launchpad-registered key:
FPR=YOUR_40_CHARACTER_FINGERPRINT
gh auth login
gpg --armor --export-secret-keys "$FPR" | \
  gh secret set PPA_GPG_PRIVATE_KEY --env ppa-production \
    --repo dribia/clockify-launchers
```

Set the passphrase as an **environment secret** and the fingerprint as an
**environment variable** in GitHub's web UI. If you prefer, you can paste the
ASCII-armored key directly into the GitHub secret editor, but not into the
repository. Configure these values before publishing a new Release.

## Packaging and validation

`debian/changelog` records the base Debian version (e.g. `0.5.2-1`).
`scripts/build-source.sh` produces clean, unsigned source uploads from the
**committed Git tree**:

```sh
make source                      # base changelog version, for manual builds
PPA_SERIES=noble make source      # PPA version targeting Ubuntu 24.04
PPA_SERIES=resolute make source   # PPA version targeting Ubuntu 26.04
```

All files are written to `dist/source/`: `.orig.tar.xz`,
`.debian.tar.xz`, `.dsc`, `_source.buildinfo`, and `_source.changes`.
CI checks that both series have correct versions and distributions, include
the buildinfo file required by `debsign`, and have byte-identical upstream
source archives.

Run `make verify`, `make lintian`, and `make smoke-install` locally as
appropriate; pull-request CI covers lint, types, unit/contract/integration
tests, UI tests, Debian binary builds and source packaging.

If an upload is rejected, read the rejection email and Launchpad logs.
**Never reuse an already accepted Debian source version**, even after
deleting it; fix the release and increment the appropriate package version.

## Installation and upgrading

```sh
sudo apt update
sudo apt install software-properties-common  # only needed if add-apt-repository is absent
sudo add-apt-repository ppa:dribia/stable
sudo apt update
sudo apt install dribia-clockify-launchers
```

Subsequent updates arrive through the normal `apt upgrade`.
Ubuntu 22.04 and 20.04 are not supported by the current application:
it requires Python 3.12+ and modern libadwaita APIs. Supporting older
Ubuntu releases would require a separate compatibility project.
