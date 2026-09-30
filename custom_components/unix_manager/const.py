"""Constants for Unix Device Manager."""

DOMAIN = "unix_manager"

CONF_KEY_FILE = "key_file"
CONF_HOST_KEY = "host_key"  # pinned server host key, OpenSSH format
CONF_INTERVAL = "check_interval"  # minutes
DEFAULT_INTERVAL = 60
MAX_LISTED_PACKAGES = 50  # keep state attributes small
