"""Config flow for the Avista integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from bidgely import AggregateType, Bidgely, CannotConnect, InvalidAuth
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .const import CONF_FUELS, DOMAIN, ELECTRIC, GAS, UTILITY

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class AvistaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Avista."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = Bidgely(
                async_create_clientsession(self.hass),
                UTILITY,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                "",
            )
            try:
                await api.async_login()
                fuels = await _async_probe_fuels(api)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error setting up Avista")
                errors["base"] = "unknown"
            else:
                if not fuels:
                    errors["base"] = "no_fuels"
                else:
                    assert api.user_id is not None
                    await self.async_set_unique_id(api.user_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Avista ({user_input[CONF_USERNAME]})",
                        data={**user_input, CONF_FUELS: fuels},
                    )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


async def _async_probe_fuels(api: Bidgely) -> list[str]:
    """Return the fuels this account actually has service for.

    A monthly read covers all history in a single request. An account with no
    gas service returns nothing, which is what distinguishes it from an account
    that has gas but burned none -- summer gas legitimately reads 0.0, so an
    all-zero series must still count as service.
    """
    fuels: list[str] = []
    end = dt_util.utcnow()
    start = end - timedelta(days=400)
    for measurement in (ELECTRIC, GAS):
        try:
            reads = await api.async_fetch(measurement, AggregateType.MONTH, start, end)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("No %s service detected", measurement, exc_info=True)
            continue
        if reads:
            fuels.append(measurement)
    return fuels
