"""Constants for the Avista integration."""

from datetime import timedelta

DOMAIN = "avista"

# The utility name understood by bidgely's _select_utility.
UTILITY = "Avista"

CONF_FUELS = "fuels"

ELECTRIC = "ELECTRIC"
GAS = "GAS"

# Avista publishes usage about a day late, so polling faster gains nothing.
UPDATE_INTERVAL = timedelta(hours=12)

# Hourly data costs one request per day, so cap what the first run pulls.
BACKFILL_DAYS = 365

# Re-read recent days every cycle; utilities revise readings after the fact.
REFETCH_DAYS = 30

# Avista documents no rate limit, so keep the backfill burst polite.
MAX_CONCURRENT_REQUESTS = 4
