"""Central identifiers and constants for Clockify Launchers.

Every identifier that would need to change on a product rename lives here
or in packaging metadata; no other source file may hard-code them.
"""

from __future__ import annotations

APP_NAME = "Clockify Launchers"
APP_ID = "com.dribia.ClockifyLaunchers"
EXECUTABLE = "clockify-launchers"
PACKAGE_NAME = "dribia-clockify-launchers"
PYTHON_DIST = "clockify-launchers"
VERSION = "0.5.1"

DESKTOP_FILE_PREFIX = f"{APP_ID}."
DESKTOP_FILE_SUFFIX = ".desktop"
MAIN_DESKTOP_FILE = f"{APP_ID}.desktop"

MANAGED_KEY = "X-Clockify-Launchers-Managed"
LAUNCHER_ID_KEY = "X-Clockify-Launchers-Id"

SYSTEMD_SERVICE = "clockify-launchers-sync.service"
SYSTEMD_TIMER = "clockify-launchers-sync.timer"

# Timer re-arm anchors (ADR 0018). data/systemd/clockify-launchers-sync.timer
# ships the same values; tests cross-check the two so they cannot drift.
# The interval drop-in must re-declare them because an empty ``On*Sec=``
# assignment resets systemd's shared timer-spec list (see ADR 0019).
TIMER_ON_STARTUP_MINUTES = 2
TIMER_ACCURACY_SECONDS = 60
TIMER_RANDOMIZED_DELAY_SECONDS = 30

CONFIG_DIR_NAME = "clockify-launchers"
DATA_DIR_NAME = "clockify-launchers"

DEFAULT_API_BASE_URL = "https://api.clockify.me/api"
# Where users generate their personal API key (Profile settings -> Advanced).
API_KEY_SETTINGS_URL = "https://app.clockify.me/user/preferences#advanced"
KNOWN_REGION_PREFIXES = ("euc1", "use2", "euw2", "apse2")

SECRET_SCHEMA_NAME = "com.dribia.ClockifyLaunchers.ApiKey"  # noqa: S105 - attribute name, not a secret
SECRET_ATTR_APPLICATION = "application"  # noqa: S105 - attribute name, not a secret
SECRET_ATTR_ACCOUNT_ID = "account_id"  # noqa: S105 - attribute name, not a secret
SECRET_ATTR_API_ORIGIN = "api_origin"  # noqa: S105 - attribute name, not a secret

USER_AGENT = f"{EXECUTABLE}/{VERSION}"

DEMO_ENV_VAR = "CLOCKIFY_LAUNCHERS_DEMO"
DEMO_STATE_ENV_VAR = "CLOCKIFY_LAUNCHERS_DEMO_STATE"

# Exit codes (documented CLI contract)
EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_AUTH_ERROR = 3
EXIT_API_ERROR = 4
EXIT_TARGET_ERROR = 5
EXIT_DESKTOP_FILE_ERROR = 6
EXIT_PARTIAL_SWITCH = 7
EXIT_LOCKED = 8
EXIT_USAGE = 64
