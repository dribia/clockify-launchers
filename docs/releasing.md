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

## Deployment: GCP Artifact Registry (APT)

Releases are published automatically by `.github/workflows/deploy.yml` when a
`v*` tag is pushed. The workflow builds the `.deb`, checks that the tag,
`pyproject.toml`, `debian/changelog`, and `constants.py` versions all match,
runs lintian, uploads to an Artifact Registry APT repository, and creates a
GitHub release.

### One-time GCP setup

The GCP resources are managed with Terraform in the
`dribia-tools-infrastructure` repository (project `dribia-tools`):

- `modules/google-artifact-registry`: APT repository `dribia-apt` in
  `europe-west1`.
- `modules/google-service-accounts`: `apt-publisher-sa` service account.
- `modules/google-iam`: `artifactregistry.writer` on the APT repo for the
  publisher, and a `workloadIdentityUser` binding on the existing GitHub
  Actions identity pool (owner-scoped to the `dribia` GitHub organization).

Run `terraform plan` / `terraform apply` there. The
`google_ci_identity_pool_provider_name` output matches the org-wide GitHub
variable `GCP_WORKLOAD_IDENTITY_PROVIDER`;
`apt-publisher-sa@dribia-tools.iam.gserviceaccount.com` is the value for the
`GCP_APT_PUBLISHER_SERVICE_ACCOUNT` variable.

Then set GitHub Actions configuration:

- Variables: `GCP_PROJECT_ID=dribia-tools`, `GAR_LOCATION=europe-west1`,
  `GAR_APT_REPOSITORY=dribia-apt`,
  `GCP_APT_PUBLISHER_SERVICE_ACCOUNT=apt-publisher-sa@dribia-tools.iam.gserviceaccount.com`,
  plus the org-wide `GCP_WORKLOAD_IDENTITY_PROVIDER`.
- No secrets are required; authentication uses OIDC.
- Optionally protect the `production` environment with required reviewers;
  the publish job runs in it.

### Releasing a version

1. Bump the version in `src/clockify_launchers/constants.py`,
   `pyproject.toml`, `data/com.dribia.ClockifyLaunchers.metainfo.xml`, and
   add a `debian/changelog` entry (`dch -v X.Y.Z-1`).
2. `make verify`, commit, and tag: `git tag vX.Y.Z && git push --tags`.
3. The Deploy workflow publishes the package and the GitHub release.

### Installing from the repository (user machines)

Private repositories need the Artifact Registry apt transport and
credentials; for machines with gcloud user credentials:

```bash
sudo apt-get install -y apt-transport-artifact-registry
echo "deb ar+https://europe-west1-apt.pkg.dev/projects/dribia-tools dribia-apt main" | \
  sudo tee /etc/apt/sources.list.d/clockify-launchers.list
sudo apt-get update
sudo apt-get install dribia-clockify-launchers
```

The `apt-transport-artifact-registry` package (from Google's
`apt.pkg.dev` bootstrap repo, see
https://cloud.google.com/artifact-registry/docs/os-packages/debian/configure)
authenticates apt with the machine's gcloud or service-account credentials.
If the repository is made public instead, the standard `deb
https://europe-west1-apt.pkg.dev/projects/dribia-tools dribia-apt main` line
works with the signing key from
`https://europe-west1-apt.pkg.dev/projects/dribia-tools/repos/dribia-apt/gpg`.
