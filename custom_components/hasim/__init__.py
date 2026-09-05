"""HASIM - Home Assistant energy contract & battery simulator."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    ATTR_DAYS,
    ATTR_TITLE,
    ATTR_URL_PATH,
    CONF_CURRENCY,
    CONF_PRICE_AREA,
    DOMAIN,
    MAX_DAYS,
    NAME,
    SERVICE_CREATE_DASHBOARD,
    SERVICE_SIMULATE,
)
from .coordinator import HasimConfigEntry, HasimCoordinator
from .dashboard import (
    async_create_storage_dashboard,
    async_register_dashboard,
    async_register_frontend,
    async_unregister_dashboard,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SIMULATE_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_DAYS))}
)
SERVICE_CREATE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_URL_PATH, default="hasim-dashboard"): cv.string,
        vol.Optional(ATTR_TITLE, default=f"{NAME} (editable)"): cv.string,
    }
)


def _loaded_entries(hass: HomeAssistant) -> list[HasimConfigEntry]:
    return hass.config_entries.async_loaded_entries(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services."""

    async def _handle_simulate(call: ServiceCall) -> None:
        days = call.data.get(ATTR_DAYS)
        for entry in _loaded_entries(hass):
            coordinator: HasimCoordinator = entry.runtime_data
            coordinator.days_override = days
            await coordinator.async_request_refresh()

    async def _handle_create_dashboard(call: ServiceCall) -> None:
        entries = _loaded_entries(hass)
        if not entries:
            raise HomeAssistantError("HASIM is not set up")
        await async_create_storage_dashboard(
            hass, entries[0].entry_id, call.data[ATTR_URL_PATH], call.data[ATTR_TITLE]
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SIMULATE, _handle_simulate, schema=SERVICE_SIMULATE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_DASHBOARD,
        _handle_create_dashboard,
        schema=SERVICE_CREATE_DASHBOARD_SCHEMA,
    )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: HasimConfigEntry) -> None:
    """Options changed: reload when the price source changed, else re-simulate."""
    coordinator: HasimCoordinator = entry.runtime_data
    if (
        entry.options.get(CONF_PRICE_AREA, coordinator.area) != coordinator.area
        or entry.options.get(CONF_CURRENCY, coordinator.currency) != coordinator.currency
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    coordinator.days_override = None
    await coordinator.async_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: HasimConfigEntry) -> bool:
    """Set up HASIM from a config entry."""
    coordinator = HasimCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    try:
        await async_register_frontend(hass)
        dashboard = async_register_dashboard(hass, entry.entry_id)
        dashboard.async_notify_updated()
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not register the HASIM dashboard")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HasimConfigEntry) -> bool:
    """Unload a config entry."""
    async_unregister_dashboard(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
