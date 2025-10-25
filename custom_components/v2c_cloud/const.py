"""Constants for the Octopus Energy Italy integration."""

DOMAIN = "v2c_cloud"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Debug interval settings
UPDATE_INTERVAL = 1  # Update interval in minutes

# Token management
TOKEN_REFRESH_MARGIN = (
    300  # Refresh token if less than 300 seconds (5 minutes) remaining
)
TOKEN_AUTO_REFRESH_INTERVAL = 50 * 60  # Auto refresh token every 50 minutes

# Debug options
DEBUG_ENABLED = False
LOG_API_RESPONSES = False  # Set to True to log full API responses
LOG_TOKEN_RESPONSES = (
    False  # Set to True to log token-related responses (login, refresh)
)
