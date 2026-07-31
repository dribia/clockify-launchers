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

```bash
PROJECT_ID=dribia-infra          # adjust
LOCATION=europe-southwest1       # adjust
REPO=clockify-launchers-apt
GITHUB_REPO=dribia/clockify-launchers

# 1. APT repository (Artifact Registry signs Release files itself).
gcloud artifacts repositories create "$REPO" \
  --project="$PROJECT_ID" --location="$LOCATION" \
  --repository-format=apt --description="Clockify Launchers APT repo"

# 2. Publisher service account.
gcloud iam service-accounts create apt-publisher --project="$PROJECT_ID"
gcloud artifacts repositories add-iam-policy-binding "$REPO" \
  --project="$PROJECT_ID" --location="$LOCATION" \
  --member="serviceAccount:apt-publisher@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

# 3. Workload Identity Federation for GitHub Actions (no stored keys).
gcloud iam workload-identity-pools create github --project="$PROJECT_ID" \
  --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --project="$PROJECT_ID" --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$GITHUB_REPO'"
POOL_NAME=$(gcloud iam workload-identity-pools describe github \
  --project="$PROJECT_ID" --location=global --format='value(name)')
gcloud iam service-accounts add-iam-policy-binding \
  "apt-publisher@$PROJECT_ID.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/$POOL_NAME/attribute.repository/$GITHUB_REPO"
echo "GCP_WIF_PROVIDER=$POOL_NAME/providers/github-oidc"
```

Then set GitHub Actions configuration:

- Variables: `GCP_PROJECT_ID`, `GAR_LOCATION`, `GAR_APT_REPOSITORY`.
- Secrets: `GCP_WIF_PROVIDER` (printed above), `GCP_SERVICE_ACCOUNT`
  (`apt-publisher@$PROJECT_ID.iam.gserviceaccount.com`).
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
echo "deb ar+https://LOCATION-apt.pkg.dev/projects/PROJECT_ID REPO main" | \
  sudo tee /etc/apt/sources.list.d/clockify-launchers.list
sudo apt-get update
sudo apt-get install dribia-clockify-launchers
```

Replace `LOCATION`, `PROJECT_ID`, and `REPO`. The
`apt-transport-artifact-registry` package (from Google's
`apt.pkg.dev` bootstrap repo, see
https://cloud.google.com/artifact-registry/docs/os-packages/debian/configure)
authenticates apt with the machine's gcloud or service-account credentials.
If the repository is made public instead, the standard `deb
https://LOCATION-apt.pkg.dev/projects/PROJECT_ID REPO main` line works with
the signing key from
`https://LOCATION-apt.pkg.dev/projects/PROJECT_ID/repos/REPO/gpg`.
