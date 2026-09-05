"""HASIM - Home Assistant energy contract & battery simulator."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import ATTR_DAYS, DOMAIN, MAX_DAYS, SERVICE_SIMULATE
from .coordinator import HasimConfigEntry, HasimCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SIMULATE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_DAYS))}
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services."""

    async def _handle_simulate(call: ServiceCall) -> None:
        days = call.data.get(ATTR_DAYS)
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            coordinator: HasimCoordinator = entry.runtime_data
            coordinator.days_override = days
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_SIMULATE, _handle_simulate, schema=SERVICE_SIMULATE_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HasimConfigEntry) -> bool:
    """Set up HASIM from a config entry."""
    coordinator = HasimCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HasimConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
