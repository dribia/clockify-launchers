PYTHON := .venv/bin/python
UV := uv
STATES := onboarding-welcome onboarding-key onboarding-workspace onboarding-mode \
	launchers-populated launchers-empty launcher-editor suggestions-add \
	suggestions-remove preferences offline auth-error externally-modified

.PHONY: bootstrap resources run demo test lint format typecheck ui-test ui-capture \
	ui-review validate-data deb lintian smoke-install test-apt-repo verify clean

bootstrap:
	$(UV) venv --python /usr/bin/python3.12 --system-site-packages .venv
	$(UV) pip install -e ".[dev]"
	# GTK/libadwaita type stubs; --no-deps avoids building pycairo from source.
	$(UV) pip install --no-deps pygobject-stubs
	@echo "System packages needed (install with sudo apt-get install):"
	@echo "  python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1"
	@echo "  xvfb dbus-x11 xdotool imagemagick python3-dogtail at-spi2-core"
	@echo "  desktop-file-utils appstream lintian debhelper dh-python"
	@echo "  pybuild-plugin-pyproject libglib2.0-bin devscripts reprepro"

resources:
	@echo "UI is built programmatically; no GResource compilation required."

run:
	scripts/dev-env.sh $(PYTHON) -m clockify_launchers gui

demo:
	CLOCKIFY_LAUNCHERS_DEMO=1 CLOCKIFY_LAUNCHERS_DEMO_STATE=launchers-populated \
		$(PYTHON) -m clockify_launchers gui

test:
	$(PYTHON) -m pytest tests/unit tests/contract tests/integration

lint:
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts

format:
	$(PYTHON) -m ruff format src tests scripts
	$(PYTHON) -m ruff check --fix src tests scripts

typecheck:
	$(UV) run --with ty ty check src

ui-test:
	scripts/ui-headless.sh $(PYTHON) -m pytest tests/ui -m ui

ui-capture:
	scripts/ui-capture.sh $(STATES)

ui-review: ui-capture
	$(PYTHON) scripts/ui-review.py artifacts/ui

validate-data:
	desktop-file-validate data/com.dribia.ClockifyLaunchers.desktop
	appstreamcli validate --no-net data/com.dribia.ClockifyLaunchers.metainfo.xml || \
		appstream-util validate-relax data/com.dribia.ClockifyLaunchers.metainfo.xml

deb:
	scripts/build-deb.sh

lintian:
	lintian --fail-on error dist/deb/*.deb

smoke-install:
	scripts/smoke-install.sh

test-apt-repo:
	scripts/build-test-apt-repo.sh

verify: lint typecheck test validate-data ui-capture ui-test deb
	@echo "verify: all checks passed"

clean:
	rm -rf artifacts dist build .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true

bump:
	@test -n "$(VERSION)" || { echo "usage: make bump VERSION={major|minor|patch|X.Y.Z}"; exit 2; }
	python3 scripts/bump-version.py $(VERSION)
