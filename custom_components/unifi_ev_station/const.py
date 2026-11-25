DOMAIN = "unifi_ev_station"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number"]

CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_CURRENT = "max_current"
CONF_MIN_INCREASE_INTERVAL = "min_increase_interval"
CONF_REASSERT_INTERVAL = "reassert_interval"

DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 30
# 0 means "no extra limit": use the breaker table, or 32 A when unknown.
DEFAULT_MAX_CURRENT = 0
DEFAULT_MIN_INCREASE_INTERVAL = 30
DEFAULT_REASSERT_INTERVAL = 300

# Give up on a single HTTP request after this many seconds. Load management
# needs to know quickly that a command failed rather than wait minutes.
REQUEST_TIMEOUT = 10
WEBSOCKET_CONNECT_TIMEOUT = 15

# Without EV_POWER_STATS frames for this long, a charger is treated as idle.
TELEMETRY_IDLE_SECONDS = 90

CONNECT_BASE = "/proxy/connect/api/v2"
