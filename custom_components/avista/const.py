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

# Avista answers a usage request in about 4 seconds, and hourly data costs one
# request per day, so a long hourly backfill cannot finish inside Home
# Assistant's config entry setup timeout. Older data comes from daily reads
# instead, which cover 32 days per request, and only the recent window is
# fetched hourly.
HOURLY_DAYS = 14
DAILY_BACKFILL_DAYS = 3 * 365

# Days of daily data one request returns, so how far to step the window.
DAILY_STRIDE = 32

# Re-read recent days every cycle; utilities revise readings after the fact.
REFETCH_DAYS = 30

# Avista documents no rate limit, so keep the backfill burst polite.
MAX_CONCURRENT_REQUESTS = 4
