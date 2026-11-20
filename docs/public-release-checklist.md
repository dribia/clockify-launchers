# Public repository maintenance checklist

[Clockify Launchers](https://github.com/dribia/clockify-launchers) is public.
Keep these checks in mind when changing release automation or accepting
contributions. Do not confuse passing CI with a complete security audit.

## For every pull request

- [ ] Check changes to GitHub Actions, build and installation scripts for
  untrusted input, excessive permissions or secret exposure.
- [ ] Keep API keys, signing material and passphrases out of source files,
  screenshots, test fixtures, logs and workflow artifacts.
- [ ] Review bundled assets and third-party dependencies for compatible
  licenses and attribution.
- [ ] Ensure the automated test suite and Debian source-package verification
  pass before merging.

## Before every public release

- [ ] Make sure the tag points to the intended code on `main` and release
  notes accurately describe the changes.
- [ ] Require approval of the protected `ppa-production` environment before
  signing and uploading packages to the public PPA.
- [ ] Confirm Launchpad **builds and publishes** each target series. A
  successful `dput` upload is not the same as a published Debian package.
- [ ] Install and smoke-test from a clean supported Ubuntu desktop on each
  advertised series.
- [ ] Update documentation if installation instructions, supported versions
  or minimum dependencies change.

## Historical secrets / confidentiality

Moving or deleting a sensitive file from the latest commit does not remove
it from public Git history, tags or previous pull requests. If credentials
are discovered, **revoke or rotate them first**, investigate where they were
exposed, and coordinate history remediation with the maintainers. Do not
assume a history rewrite alone makes leaked secrets safe.

The production OpenPGP private key is stored only in an approved maintainer's
keyring and the protected GitHub deployment environment. Launchpad signs
the published APT repository with a separate key managed by Launchpad.
