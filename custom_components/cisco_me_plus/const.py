"""Constants for the Cisco Mobility Express Plus integration."""

from __future__ import annotations

DOMAIN = "cisco_me_plus"

CONF_COMMUNITY = "community"
CONF_CONSIDER_HOME = "consider_home"

DEFAULT_PORT = 161
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
DEFAULT_CONSIDER_HOME = 180

# The controller refreshes client byte counters about every 90 s; after this long without a change
# the client is considered idle.
RATE_STALE_SECONDS = 200
APP_SCAN_INTERVAL = 120
TOP_LIST_SIZE = 10
