# Public repository readiness checklist

The repository stays **private** until all blocking checks below are
complete. The four Phase 1 PRs must be merged, reviewed and pass CI
before the visibility change.

## Automated and reviewed checks

- [x] The current tree has an MIT license and Debian copyright metadata.
- [x] GitHub release-workflow command interpolation is addressed in its
  dedicated security PR (merge and CI confirmation still required).
- [x] Non-native Debian source packaging is addressed in a dedicated PR
  (full CI source-build confirmation still required).
- [x] The private Artifact Registry deployment path is removed in the
  distribution documentation PR (merge required).
- [x] Tracked generated egg-info and debhelper fragments are removed by
  the hygiene PR, with a CI check against regression (merge required).
- [x] Initial static scan of the 50 commits reachable from `main` for
  common private-key delimiters and recognizable token prefixes
  (`ghp_`, `github_pat_`, `AIza`, `AKIA`) found no obvious matches in
  returned commit patches. This is **not** a complete secrets audit.

## Blocking checks before switching GitHub visibility

- [ ] Merge all four Phase 1 PRs and verify the combined result and CI.
- [ ] Run a dedicated secret scanner (for example, Gitleaks) over **all Git
  refs and history**, including non-main branches and tags, and manually
  inspect results. The targeted patch-pattern scan above is insufficient
  to certify the repository secret-free.
- [ ] Review historic commits for internal infrastructure details,
  credential material and confidential business context. Removing files
  from the current tree does **not** remove them from Git history.
  Decide whether the historical internal APT setup is approved for public
  disclosure, or sanitize the history / publish a clean public mirror
  before enabling visibility. Never assume a history rewrite revokes
  credentials: rotate any exposed secrets first.
- [ ] Check GitHub repository visibility consequences, including historical
  pull requests, issues, releases, attachments, branches, tags, and Actions
  logs/artifacts for information not intended for publication.
- [ ] Confirm Dribia approval for public licensing, the Clockify name and
  logo/trademark usage, bundled icons, and third-party notices.
- [ ] Confirm all contributors and maintainers know the repository will
  become public and that external contributions are permitted.
- [ ] Verify PPA instructions are still clearly marked pending until
  packages are published; do not represent Phase 2 CI publishing as live.
- [ ] Change GitHub visibility to public **manually**, after signoff.

## Notes

Dribia continues to own the application identifiers, Debian package
namespace and Launchpad team PPA. Open-sourcing the source repository does
not require renaming the application or the Debian package.

Production GPG keys, passphrases and other publishing credentials must stay
outside the repository. They will be provisioned separately in a protected
GitHub Actions environment for Phase 2.
