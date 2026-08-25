# Clockify Launchers

Native Ubuntu (GTK4/libadwaita) desktop application that creates and maintains
per-user application launchers which start [Clockify](https://clockify.me)
timers. Configure your API key once; each generated launcher appears in the
GNOME application grid and starts or switches the matching timer when clicked.

Key features:

- Onboarding with API key validation (stored only in GNOME Keyring via libsecret)
- Manual launcher creation from Clockify projects, tasks, and tags
- Import of legacy `clockify-cli in ...` launchers (safe, read-only parse)
- Manual, Assisted, and Autopilot management modes with conservative automation
- Background reconciliation via a systemd user timer
- Deterministic demo mode and automated UI screenshots

## Install

### From the Dribia APT repository (recommended)

Packages are published to a private Google Artifact Registry repository.
You need a Google account with read access to the `dribia-apt` repository in
the `dribia-operation` project (the `tothom@dribia.com` group has it) and
the `gcloud` CLI installed.

**1. Install Google's Artifact Registry apt transport** (one time):

```sh
curl -fsSL https://us-apt.pkg.dev/doc/repo-signing-key.gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/ar-transport.gpg
echo "deb [signed-by=/usr/share/keyrings/ar-transport.gpg] https://packages.cloud.google.com/apt apt-transport-artifact-registry-stable main" | \
  sudo tee /etc/apt/sources.list.d/ar-transport.list
sudo apt update
sudo apt install -y apt-transport-artifact-registry
```

**2. Add the Dribia repository and its signing key.** Artifact Registry
repositories are signed with Google's generic signing key; the `ar+https`
scheme routes the download through the authenticated transport from step 1:

```sh
curl -fsSL https://us-apt.pkg.dev/doc/repo-signing-key.gpg | \
  sudo gpg --dearmor -o /usr/share/keyrings/dribia-apt.gpg
echo "deb [signed-by=/usr/share/keyrings/dribia-apt.gpg] ar+https://europe-west1-apt.pkg.dev/projects/dribia-operation dribia-apt main" | \
  sudo tee /etc/apt/sources.list.d/dribia.list
```

**3. Provide Google credentials for root.** The apt transport runs under
`sudo`, so the [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
must exist for the root user (a plain `gcloud auth application-default login`
stores them under your own user, where apt cannot see them):

```sh
sudo gcloud auth application-default login
```

Log in with your Dribia Google account in the browser window that opens.
This is needed once; the credential refreshes itself afterwards.

**4. Install and stay updated:**

```sh
sudo apt update
sudo apt install dribia-clockify-launchers
```

New releases arrive through regular `apt upgrade`.

Troubleshooting:

- `failed to obtain default creds` during `apt update`: step 3 was skipped
  or run without `sudo`; the credentials must belong to root.
- `does not have a Release file` on the Dribia repository: the transport
  could not authenticate or is not authorized, and apt reports the failed
  download generically. Check, in order: step 3 was done with `sudo`
  (root ADC), you logged in with your `@dribia.com` Google account, and
  that account can read Artifact Registry in `dribia-operation`
  (`roles/artifactregistry.reader` is granted to the `tothom@dribia.com`
  group via Terraform in `dribia-operation-terraform`).
- `401`/`403` on the Dribia repository: same causes as above; your Google
  account lacks read access to Artifact Registry in `dribia-operation`.
- `NO_PUBKEY C0BA5CE6DC6315A3` / `repository is not signed`: the signing key
  from step 2 is missing, or the sources line lacks the `signed-by` option.
  As a fallback the key can be fetched from a keyserver:
  `sudo gpg --no-default-keyring --keyring /usr/share/keyrings/dribia-apt.gpg --keyserver keyserver.ubuntu.com --recv-keys C0BA5CE6DC6315A3`
- `E: The method driver /usr/lib/apt/methods/ar+https could not be found`:
  step 1 (the transport package) is missing.

### From a local build

```sh
make deb
sudo apt install ./dist/deb/dribia-clockify-launchers_*.deb
```

Runtime dependencies (installed by the package): `python3-gi`,
`gir1.2-gtk-4.0`, `gir1.2-adw-1`, `gir1.2-secret-1`, `python3-httpx`.
Targets Ubuntu 24.04 LTS and 26.04 LTS.

### Development setup

```sh
make bootstrap   # creates a uv venv (.venv) with --system-site-packages
```

PyGObject/GTK come from the system; `make bootstrap` prints the required
`apt-get install` list (GTK, Xvfb, dogtail, packaging tools, etc.).

## Usage

```text
clockify-launchers                         # open or focus the GUI
clockify-launchers gui                     # explicit GUI command
clockify-launchers start --launcher UUID   # start/switch timer for a launcher
clockify-launchers stop                    # stop the current running timer
clockify-launchers sync                    # reconcile launchers now
clockify-launchers sync --background       # quiet systemd mode
clockify-launchers doctor [--network]      # read-only diagnostics
clockify-launchers reset [--remove-launchers] [--yes]
clockify-launchers demo --state STATE      # deterministic UI fixture state
clockify-launchers --version
```

Exit codes: `0` success/no-op, `2` configuration, `3` authentication,
`4` API, `5` target, `6` desktop-file, `7` partial switch (old timer stopped,
new start failed), `8` locked, `64` usage.

## Development

```text
make run           # run against isolated dev XDG data (scripts/dev-env.sh)
make demo          # populated deterministic demo state
make test          # unit + contract + integration tests
make lint          # ruff check + format verification
make format        # apply formatting
make typecheck     # ty check src
make ui-capture    # capture all deterministic UI states to artifacts/ui/
make ui-review     # contact sheet + review checklist
make ui-test       # AT-SPI tests under Xvfb
make validate-data # desktop-file-validate + AppStream validation
make deb           # build the Debian package
make lintian       # run lintian
make smoke-install # install/test/remove in isolated environment
make test-apt-repo # locally signed test APT repository
make verify        # full non-live verification suite
```

## Demo mode

Run the UI with deterministic fixtures and no network, keyring, or real
user data:

```sh
CLOCKIFY_LAUNCHERS_DEMO=1 clockify-launchers gui
clockify-launchers demo --state launchers-populated
```

States include `onboarding-*`, `launchers-populated`, `launchers-empty`,
`launcher-editor`, `suggestions-add`, `suggestions-remove`, `preferences`,
`offline`, `auth-error`, and `externally-modified`.

## Testing

Default tests never contact Clockify. Live read-only tests are opt-in:

```sh
CLOCKIFY_LIVE_TESTS=1 CLOCKIFY_API_KEY=... make test
```

Never commit an API key; supply it from outside the repository.

## License

MIT. See [LICENSE](LICENSE).
