"""Constants for Unix Device Manager."""

DOMAIN = "unix_manager"

CONF_KEY_FILE = "key_file"
CONF_HOST_KEY = "host_key"  # pinned server host key, OpenSSH format
CONF_INTERVAL = "check_interval"  # minutes
DEFAULT_INTERVAL = 60
MAX_LISTED_PACKAGES = 50  # keep state attributes small

# Long-running operations, also the button keys.
OP_REFRESH = "refresh_repositories"
OP_UPGRADE = "upgrade_os"
OP_NAMES = {OP_REFRESH: "Update repositories", OP_UPGRADE: "Update OS"}
