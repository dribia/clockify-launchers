#!/bin/bash
# Prove APT distributability: build a locally signed test repository with an
# ephemeral GPG key, add it to an isolated apt configuration, and install the
# package by name. All key material is destroyed afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."
DEB=$(ls dist/deb/dribia-clockify-launchers_*.deb 2>/dev/null | head -1)
[ -n "$DEB" ] || { echo "Build the package first: make deb"; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export GNUPGHOME="$WORK/gnupg"
mkdir -p "$GNUPGHOME"; chmod 700 "$GNUPGHOME"

echo "Generating ephemeral signing key..."
gpg --batch --pinentry-mode loopback --passphrase '' --quick-gen-key \
  "Clockify Launchers Test <test@example.invalid>" default default never

REPO="$WORK/repo"
mkdir -p "$REPO/conf"
cat > "$REPO/conf/distributions" <<EOF
Origin: clockify-launchers-test
Label: clockify-launchers-test
Codename: noble
Architectures: amd64
Components: main
Description: Ephemeral test repository
SignWith: default
EOF
reprepro -b "$REPO" includedeb noble "$DEB"

# Isolated apt configuration (no root needed for update/policy checks).
APT_ROOT="$WORK/apt"
mkdir -p "$APT_ROOT/etc/apt/sources.list.d" "$APT_ROOT/etc/apt/trusted.gpg.d" \
         "$APT_ROOT/var/lib/apt/lists/partial" "$APT_ROOT/var/cache/apt/archives/partial" \
         "$APT_ROOT/var/lib/dpkg"
touch "$APT_ROOT/var/lib/dpkg/status"
gpg --export > "$APT_ROOT/etc/apt/trusted.gpg.d/test.gpg"
echo "deb [arch=all,amd64] copy://$REPO noble main" \
  > "$APT_ROOT/etc/apt/sources.list.d/test.list"

APT_OPTS=(-o Dir="$APT_ROOT" -o Dir::State::status="$APT_ROOT/var/lib/dpkg/status" \
          -o Dir::Etc::sourcelist="$APT_ROOT/etc/apt/sources.list.d/test.list" \
          -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0)

apt-get "${APT_OPTS[@]}" update
apt-cache "${APT_OPTS[@]}" policy dribia-clockify-launchers | grep -q Candidate
(cd "$WORK" && apt-get "${APT_OPTS[@]}" download dribia-clockify-launchers)
ls "$WORK"/dribia-clockify-launchers_*.deb

echo "test-apt-repo: package resolvable and downloadable by name from a signed repo"
