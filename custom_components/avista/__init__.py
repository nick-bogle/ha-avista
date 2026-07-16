"""The Avista integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .coordinator import AvistaConfigEntry, AvistaCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: AvistaConfigEntry) -> bool:
    """Set up Avista from a config entry."""
    coordinator = AvistaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AvistaConfigEntry) -> bool:
    """Unload a config entry."""
    return True
