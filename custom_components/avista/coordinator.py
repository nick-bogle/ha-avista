"""Coordinator to handle Avista connections."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from bidgely import AggregateType, Bidgely, CannotConnect, CostRead, InvalidAuth
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import (
    BACKFILL_DAYS,
    CONF_FUELS,
    DOMAIN,
    ELECTRIC,
    MAX_CONCURRENT_REQUESTS,
    REFETCH_DAYS,
    UPDATE_INTERVAL,
    UTILITY,
)

_LOGGER = logging.getLogger(__name__)

type AvistaConfigEntry = ConfigEntry[AvistaCoordinator]


def statistic_id_prefix(user_id: str, measurement: str) -> str:
    """Build the statistic id prefix for a fuel.

    The Bidgely user id is the only stable identifier available: Avista's
    getBidgelyWidgetData returns whichever account the session has active, so
    the account number the user typed is never sent anywhere.
    """
    return f"{user_id}_{measurement}".replace("-", "_").lower()


class AvistaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch Avista usage and insert it as long term statistics."""

    config_entry: AvistaConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: AvistaConfigEntry) -> None:
        """Initialize the data handler."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Avista",
            update_interval=UPDATE_INTERVAL,
        )
        self.api = Bidgely(
            async_create_clientsession(hass),
            UTILITY,
            config_entry.data[CONF_USERNAME],
            config_entry.data[CONF_PASSWORD],
            config_entry.data.get("account_id", ""),
        )
        self.fuels: list[str] = list(config_entry.data[CONF_FUELS])

        @callback
        def _dummy_listener() -> None:
            pass

        # This integration only writes statistics, so it adds no entities and
        # nothing would otherwise listen to the coordinator -- without a
        # listener it never refreshes on its own.
        self.async_add_listener(_dummy_listener)

    async def _async_update_data(self) -> dict[str, Any]:
        """Log in and refresh statistics for every enabled fuel."""
        try:
            # The token is short lived and refreshing is cheap, so just
            # re-login on each cycle rather than track expiry.
            await self.api.async_login()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            raise UpdateFailed(f"Error during login: {err}") from err

        for measurement in self.fuels:
            await self._insert_statistics(measurement)
        return {}

    async def _insert_statistics(self, measurement: str) -> None:
        """Insert statistics for one fuel."""
        assert self.api.user_id is not None
        prefix = statistic_id_prefix(self.api.user_id, measurement)
        cost_statistic_id = f"{DOMAIN}:{prefix}_energy_cost"
        consumption_statistic_id = f"{DOMAIN}:{prefix}_energy_consumption"

        name_prefix = f"Avista {measurement.lower()}"
        is_electric = measurement == ELECTRIC
        cost_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{name_prefix} cost",
            source=DOMAIN,
            statistic_id=cost_statistic_id,
            unit_class=None,
            unit_of_measurement=None,
        )
        consumption_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{name_prefix} consumption",
            source=DOMAIN,
            statistic_id=consumption_statistic_id,
            # Avista meters gas in therms, which Home Assistant has no unit for.
            # The therm values are passed through unconverted and labelled CCF:
            # converting would need the gas heat content, which the API never
            # returns, so a guessed factor would corrupt the numbers. This keeps
            # them matching the bill exactly and mislabels only the unit.
            unit_class=EnergyConverter.UNIT_CLASS
            if is_electric
            else VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR
            if is_electric
            else UnitOfVolume.CENTUM_CUBIC_FEET,
        )

        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, consumption_statistic_id, True, set()
        )
        if not last_stat:
            _LOGGER.debug("Updating %s statistics for the first time", measurement)
            reads = await self._async_get_reads(measurement, None)
            cost_sum = 0.0
            consumption_sum = 0.0
            last_stats_time = None
        else:
            reads = await self._async_get_reads(
                measurement, last_stat[consumption_statistic_id][0]["start"]
            )
            if not reads:
                _LOGGER.debug("No recent %s data. Skipping update", measurement)
                return
            start = reads[0].start_time
            # Usually a statistic already exists at start; if not, fall back to
            # scanning from there so the running sum still resumes correctly.
            stats: dict[str, list[Any]] = {}
            for end in (start + timedelta(seconds=1), None):
                stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    start,
                    end,
                    {cost_statistic_id, consumption_statistic_id},
                    "hour",
                    None,
                    {"sum"},
                )
                if stats:
                    break

            if not stats.get(consumption_statistic_id):
                # A previous statistic exists but its sum is unreadable, so
                # there is nothing to continue from. Writing this window would
                # restart the sum at zero underneath the existing series and
                # corrupt it, so leave the data alone and retry next cycle.
                _LOGGER.warning(
                    "Found no prior sum for %s at %s; skipping this update to"
                    " avoid rewriting existing statistics",
                    consumption_statistic_id,
                    start,
                )
                return

            def _safe_get_sum(records: list[Any]) -> float:
                if records and "sum" in records[0]:
                    return float(records[0]["sum"])
                return 0.0

            cost_sum = _safe_get_sum(stats.get(cost_statistic_id, []))
            consumption_sum = _safe_get_sum(stats.get(consumption_statistic_id, []))
            last_stats_time = stats[consumption_statistic_id][0]["start"]

        cost_statistics: list[StatisticData] = []
        consumption_statistics: list[StatisticData] = []
        for read in reads:
            start = read.start_time
            if last_stats_time is not None and start.timestamp() <= last_stats_time:
                continue
            cost_state = max(0.0, read.cost or 0.0)
            consumption_state = max(0.0, read.consumption or 0.0)
            cost_sum += cost_state
            consumption_sum += consumption_state
            cost_statistics.append(
                StatisticData(start=start, state=cost_state, sum=cost_sum)
            )
            consumption_statistics.append(
                StatisticData(start=start, state=consumption_state, sum=consumption_sum)
            )

        _LOGGER.debug(
            "Adding %s statistics for %s", len(consumption_statistics), prefix
        )
        async_add_external_statistics(self.hass, cost_metadata, cost_statistics)
        async_add_external_statistics(
            self.hass, consumption_metadata, consumption_statistics
        )

    async def _async_get_reads(
        self, measurement: str, start_time: float | None
    ) -> list[CostRead]:
        """Get hourly reads, localized and ready for statistics.

        On the first run this backfills BACKFILL_DAYS; afterwards it re-reads
        from REFETCH_DAYS before the last statistic, since utilities revise
        readings after the fact.
        """
        tz = await dt_util.async_get_time_zone(self.api.utility.timezone())
        end = dt_util.now(tz)
        if start_time is None:
            start = end - timedelta(days=BACKFILL_DAYS)
        else:
            start = datetime.fromtimestamp(start_time, tz=tz) - timedelta(
                days=REFETCH_DAYS
            )
        return await self._async_fetch_hourly(measurement, start, end, tz)

    async def _async_fetch_hourly(
        self, measurement: str, start: datetime, end: datetime, tz: Any
    ) -> list[CostRead]:
        """Fetch hourly reads a day at a time, with bounded concurrency.

        Avista returns 24 hourly reads per request, selected by the request's
        end timestamp. bidgely's async_get_usage_data would gather every day at
        once -- a year of backfill in one burst -- so drive async_fetch directly
        behind a semaphore instead.
        """
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def fetch_day(day: datetime) -> list[CostRead]:
            async with semaphore:
                return await self.api.async_fetch(
                    measurement, AggregateType.HOUR, day - timedelta(days=1), day
                )

        # Noon local time unambiguously identifies the day being asked for,
        # even across daylight saving transitions.
        day = start.astimezone(tz).replace(hour=12, minute=0, second=0, microsecond=0)
        days: list[datetime] = []
        while day <= end:
            days.append(day)
            day += timedelta(days=1)

        results = await asyncio.gather(*(fetch_day(d) for d in days))

        reads: list[CostRead] = []
        for day_reads in results:
            for read in day_reads:
                # The most recent hours exist but carry no consumption yet;
                # Avista publishes about a day late. Zeroing them would write
                # false troughs into the statistics.
                if read.consumption is None:
                    continue
                # The API returns naive local wall clock times. Statistics need
                # timezone aware starts on exact hour boundaries.
                reads.append(
                    CostRead(
                        start_time=read.start_time.replace(tzinfo=tz),
                        end_time=read.end_time.replace(tzinfo=tz),
                        consumption=read.consumption,
                        cost=read.cost,
                        temperature=read.temperature,
                        itemization=read.itemization,
                    )
                )
        reads.sort()
        return reads
