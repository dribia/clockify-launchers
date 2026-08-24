---
name: release-drilaunchers
description: Use when the developer asks to release, publish, ship, or version-bump this repository (drilaunchers / dribia-clockify-launchers). Guides the whole release process end to end - preflight, landing pending work, CHANGELOG, bump workflow, bump PR merge, publishing the draft release, deploy monitoring - asking the developer for approval before every critical step.
---

# Release process for dribia-clockify-launchers

This skill guides an **assisted** release of this repository. The agent does
the work; the developer approves the critical gates. Never skip a gate, never
batch two gates into one question.

## Release pipeline (how this repo ships)

```
Actions "bump" workflow (workflow_dispatch: major|minor|patch)
  -> bot opens PR ":label: Version bump to vX.Y.Z" on branch release/vX.Y.Z-merge
  -> merge PR to main
  -> release.yml (push to main, commit message contains "Version bump to")
     creates a DRAFT GitHub release with tag vX.Y.Z
  -> developer/agent publishes (un-drafts) the release
  -> deploy.yml (release: published) builds the .deb, checks that the tag,
     pyproject.toml, debian/changelog, and constants.py versions all match,
     runs lintian, uploads to the dribia-apt Artifact Registry (APT), and
     attaches the .deb to the GitHub release
```

Version locations (must always agree; `scripts/bump-version.py` updates the
first four, **not** `CHANGELOG.md`):

1. `pyproject.toml` - `[project] version`
2. `src/clockify_launchers/constants.py` - `VERSION`
3. `debian/changelog` - top entry
4. `data/com.dribia.ClockifyLaunchers.metainfo.xml` - `<releases>`
5. `CHANGELOG.md` - manual (Keep a Changelog format)

## Approval gates

Ask with the `question` tool, one gate at a time, only when that gate is
actually reached. The gates, in order:

| # | Gate | What to ask |
| - | ---- | ----------- |
| G1 | Push pending work | "Commit and push these changes to main / open a PR?" (show `git status` summary first) |
| G2 | Bump kind | Offer major / minor / patch with a **recommendation** derived from the Unreleased CHANGELOG section (breaking -> major, features -> minor, fixes only -> patch). Developer decides. |
| G3 | Approve + merge bump PR | Show the PR diff summary and CI status first. |
| G4 | Publish (un-draft) the release | Make explicit that this deploys to the production APT repo for all users. |

Everything else (running checks, editing CHANGELOG dates, watching CI,
reporting) proceeds autonomously without asking.

## Step-by-step procedure

### 1. Preflight (autonomous)

```bash
git fetch --tags -q
gh release list --limit 3          # what is actually released (do NOT trust local tags alone)
git status --short                 # pending work?
git log --oneline origin/main..HEAD
gh run list --limit 3              # CI health on main
```

- Read `CHANGELOG.md`: confirm there is an `## [Unreleased]` section with
  content. If empty and there are no unreleased commits, tell the developer
  there is nothing to release and stop.
- Confirm the latest `gh release` matches the version in `pyproject.toml`.
  If they disagree, investigate before proceeding (releasing.md and past
  releases are the truth, not local files).

### 2. Land pending work (gate G1)

If the working tree is dirty or local commits are unpushed:

- Run the fast checks first: `make test`, `make lint` (run `make format` and
  re-check if lint fails on formatting), `make typecheck`.
- Make sure `CHANGELOG.md` `[Unreleased]` describes the pending work; add
  entries if missing.
- **G1**: ask before committing/pushing. Commit style: imperative subject,
  explanatory body (see `git log` for examples).
- After pushing, watch CI: `gh run list --limit 3`, then
  `gh run watch <id> --exit-status --interval 15`. Do not continue until CI
  is green on main.

### 3. Heavier verification (autonomous, report failures)

Per `docs/releasing.md`, from a clean tree run at minimum `make verify`.
`make smoke-install` needs sudo and `make test-apt-repo` is slow; run them if
the environment permits, otherwise tell the developer they were skipped and
why. Any failure stops the release until fixed.

### 4. Trigger the bump (gate G2)

- Derive a recommendation from `[Unreleased]`: breaking changes -> `major`,
  any `### Added` feature -> `minor`, otherwise `patch`.
- **G2**: ask which bump to run, presenting the recommendation first and the
  resulting version number for each option (current version comes from
  `pyproject.toml`).
- Run it and wait:

```bash
gh workflow run bump.yml -f version=<choice>
sleep 10 && gh run list --workflow=bump.yml --limit 1
gh run watch <run-id> --exit-status --interval 10
gh pr list --limit 3               # expect ":label: Version bump to vX.Y.Z"
```

### 5. Fix CHANGELOG on the bump branch (autonomous)

The bump script does not touch `CHANGELOG.md`. On the bump branch
(`release/vX.Y.Z-merge`):

```bash
git fetch origin release/vX.Y.Z-merge -q && git checkout release/vX.Y.Z-merge -q
```

- Retitle `## [Unreleased]` to `## [X.Y.Z] - <today YYYY-MM-DD>`.
- Commit ("CHANGELOG: X.Y.Z release date") and push to the same branch.
- Watch the PR's CI: `gh run watch <id>` / `gh pr checks <pr>` until the
  `verify` check passes. (Note: `gh pr checks --watch` has been flaky here;
  polling `gh run watch` on the run id is more reliable.)

### 6. Approve and merge the bump PR (gate G3)

- Show the developer: PR number/title, files changed, CI status.
- **G3**: ask for approval to approve + merge.

```bash
gh pr review <pr> --approve
gh pr merge <pr> --merge --delete-branch
git checkout main -q && git pull -q
```

- Wait for `release.yml` to create the draft:
  `gh release list --limit 3` should show `vX.Y.Z  Draft`. Also let the
  post-merge CI run on main finish.

### 7. Publish the release (gate G4)

- **G4**: ask for approval, stating explicitly: "Publishing deploys
  vX.Y.Z to the dribia-apt production APT repository for all users."

```bash
gh release edit vX.Y.Z --draft=false
sleep 15 && gh run list --workflow=deploy.yml --limit 1
gh run watch <run-id> --exit-status --interval 20
gh run view <run-id> --json conclusion,jobs -q '.conclusion, (.jobs[] | .name + ": " + .conclusion)'
gh release view vX.Y.Z --json isDraft,tagName,assets -q '.tagName, .isDraft, (.assets[].name)'
```

Success = deploy conclusion `success`, all jobs (`build`, `publish`,
`attach-artifact`) green, and the `.deb` asset attached.

### 8. Wrap up (autonomous)

Report to the developer:

- Release URL and attached `.deb` name.
- Upgrade command for their machine:
  `sudo apt update && sudo apt install --only-upgrade dribia-clockify-launchers`
- If `docs/STATUS.md` references an outdated version/state, offer to update it.

## Failure handling

- **Bump workflow fails**: read logs (`gh run view <id> --log-failed`), fix,
  re-run. No state to roll back (the PR is only created on success).
- **Bump PR CI fails**: fix on the bump branch, push, re-watch. Never merge red.
- **Deploy fails after publishing**: do NOT re-publish blindly. Read the
  failing job log. The version-match check failing means a version file
  disagrees with the tag - fix on main, then re-run the workflow from the
  release page / `gh run rerun <id>`.
- **Draft release never appears** after merging: check that the merge commit
  message contains "Version bump to vX.Y.Z" (release.yml greps for it) and
  that the `release` run on main didn't fail.
- Anything ambiguous: stop and ask the developer rather than improvising.

## Hard rules

- Never push tags manually; tags are created by release.yml.
- Never edit version numbers by hand outside `scripts/bump-version.py`.
- Never commit signing keys, APT credentials, or API keys (releasing.md).
- Never merge a bump PR or publish a release without the developer's explicit
  approval in this session.
- One release at a time: if a draft release or open bump PR already exists,
  surface it and ask how to proceed instead of creating another.
