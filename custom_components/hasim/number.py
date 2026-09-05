"""Number entities exposing HASIM settings."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, NAME
from .coordinator import HasimConfigEntry
from .settings import NUMBER_SETTINGS, NumberSetting, async_update_option

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HasimConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""
    async_add_entities(HasimNumber(entry, setting) for setting in NUMBER_SETTINGS)


class HasimNumber(RestoreNumber, NumberEntity):
    """A setting as number entity (value lives in the config entry options)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, entry: HasimConfigEntry, setting: NumberSetting) -> None:
        self._entry = entry
        self._setting = setting
        self._attr_unique_id = f"{entry.entry_id}_{setting.key}"
        self._attr_translation_key = setting.key
        self._attr_native_min_value = setting.min
        self._attr_native_max_value = setting.max
        self._attr_native_step = setting.step
        unit = setting.unit
        currency = entry.runtime_data.currency
        if unit and "€" in unit and currency != "EUR":
            unit = unit.replace("€", currency)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="HASIM",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        value = self._entry.options.get(self._setting.key)
        if value is None:
            return self._setting.default
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        async_update_option(self.hass, self._entry, self._setting.key, value)
        self.async_write_ha_state()
