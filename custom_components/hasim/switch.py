"""Switch entities exposing HASIM boolean settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, NAME
from .coordinator import HasimConfigEntry
from .settings import SWITCH_SETTINGS, SwitchSetting, async_update_option

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HasimConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities."""
    async_add_entities(HasimSwitch(entry, setting) for setting in SWITCH_SETTINGS)


class HasimSwitch(SwitchEntity):
    """A boolean setting as switch entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry: HasimConfigEntry, setting: SwitchSetting) -> None:
        self._entry = entry
        self._setting = setting
        self._attr_unique_id = f"{entry.entry_id}_{setting.key}"
        self._attr_translation_key = setting.key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="HASIM",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(self._setting.key, self._setting.default))

    async def async_turn_on(self, **kwargs: Any) -> None:
        async_update_option(self.hass, self._entry, self._setting.key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        async_update_option(self.hass, self._entry, self._setting.key, False)
        self.async_write_ha_state()
