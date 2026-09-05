"""Shared definitions for the settings entities (number / switch)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging

from homeassistant.core import HomeAssistant

from .const import (
    CONF_BAT_CAPACITY,
    CONF_BAT_CHARGE_POWER,
    CONF_BAT_DISCHARGE_POWER,
    CONF_BAT_EFFICIENCY,
    CONF_BAT_ENABLED,
    CONF_BAT_GRID_CHARGING,
    CONF_BAT_INVESTMENT,
    CONF_BAT_LIFETIME,
    CONF_BAT_MIN_SOC,
    CONF_DAYS,
    CONF_DYN_ENERGY_TAX,
    CONF_DYN_FEED_IN_FEE,
    CONF_DYN_MARKUP_EXPORT,
    CONF_DYN_MARKUP_IMPORT,
    CONF_DYN_NET_METERING,
    CONF_DYN_STANDING_CHARGE,
    CONF_FIXED_EXPORT_PRICE,
    CONF_FIXED_FEED_IN_FEE,
    CONF_FIXED_IMPORT_PRICE,
    CONF_FIXED_NET_METERING,
    CONF_FIXED_STANDING_CHARGE,
    CONF_VAT,
    DEFAULT_BAT_EFFICIENCY,
    DEFAULT_BAT_LIFETIME,
    DEFAULT_BAT_MIN_SOC,
    DEFAULT_DAYS,
    DEFAULT_ENERGY_TAX,
    DEFAULT_MARKUP_IMPORT,
    DEFAULT_VAT,
    MAX_DAYS,
)
from .coordinator import HasimConfigEntry

_LOGGER = logging.getLogger(__name__)

PER_KWH = "€/kWh"
PER_MONTH = "€/month"


@dataclass(frozen=True, kw_only=True)
class NumberSetting:
    """A numeric option exposed as a number entity."""

    key: str
    default: float | None
    min: float
    max: float
    step: float
    unit: str | None
    group: str  # general / fixed / dynamic / battery
    optional: bool = False  # None allowed (= use energy dashboard price)


@dataclass(frozen=True, kw_only=True)
class SwitchSetting:
    """A boolean option exposed as a switch entity."""

    key: str
    default: bool
    group: str


NUMBER_SETTINGS: tuple[NumberSetting, ...] = (
    NumberSetting(
        key=CONF_DAYS, default=DEFAULT_DAYS, min=1, max=MAX_DAYS, step=1, unit="d", group="general"
    ),
    NumberSetting(
        key=CONF_VAT, default=DEFAULT_VAT, min=0, max=100, step=0.1, unit="%", group="general"
    ),
    NumberSetting(
        key=CONF_FIXED_IMPORT_PRICE,
        default=None,
        min=0,
        max=5,
        step=0.0001,
        unit=PER_KWH,
        group="fixed",
        optional=True,
    ),
    NumberSetting(
        key=CONF_FIXED_EXPORT_PRICE,
        default=None,
        min=-1,
        max=5,
        step=0.0001,
        unit=PER_KWH,
        group="fixed",
        optional=True,
    ),
    NumberSetting(
        key=CONF_FIXED_STANDING_CHARGE,
        default=0.0,
        min=0,
        max=500,
        step=0.01,
        unit=PER_MONTH,
        group="fixed",
    ),
    NumberSetting(
        key=CONF_FIXED_FEED_IN_FEE,
        default=0.0,
        min=0,
        max=500,
        step=0.01,
        unit=PER_MONTH,
        group="fixed",
    ),
    NumberSetting(
        key=CONF_DYN_MARKUP_IMPORT,
        default=DEFAULT_MARKUP_IMPORT,
        min=-1,
        max=5,
        step=0.0001,
        unit=PER_KWH,
        group="dynamic",
    ),
    NumberSetting(
        key=CONF_DYN_MARKUP_EXPORT,
        default=0.0,
        min=-1,
        max=5,
        step=0.0001,
        unit=PER_KWH,
        group="dynamic",
    ),
    NumberSetting(
        key=CONF_DYN_ENERGY_TAX,
        default=DEFAULT_ENERGY_TAX,
        min=0,
        max=5,
        step=0.0001,
        unit=PER_KWH,
        group="dynamic",
    ),
    NumberSetting(
        key=CONF_DYN_STANDING_CHARGE,
        default=0.0,
        min=0,
        max=500,
        step=0.01,
        unit=PER_MONTH,
        group="dynamic",
    ),
    NumberSetting(
        key=CONF_DYN_FEED_IN_FEE,
        default=0.0,
        min=0,
        max=500,
        step=0.01,
        unit=PER_MONTH,
        group="dynamic",
    ),
    NumberSetting(
        key=CONF_BAT_CAPACITY, default=10.0, min=0, max=1000, step=0.1, unit="kWh", group="battery"
    ),
    NumberSetting(
        key=CONF_BAT_CHARGE_POWER,
        default=5.0,
        min=0,
        max=1000,
        step=0.1,
        unit="kW",
        group="battery",
    ),
    NumberSetting(
        key=CONF_BAT_DISCHARGE_POWER,
        default=5.0,
        min=0,
        max=1000,
        step=0.1,
        unit="kW",
        group="battery",
    ),
    NumberSetting(
        key=CONF_BAT_EFFICIENCY,
        default=DEFAULT_BAT_EFFICIENCY,
        min=50,
        max=100,
        step=0.5,
        unit="%",
        group="battery",
    ),
    NumberSetting(
        key=CONF_BAT_MIN_SOC,
        default=DEFAULT_BAT_MIN_SOC,
        min=0,
        max=90,
        step=1,
        unit="%",
        group="battery",
    ),
    NumberSetting(
        key=CONF_BAT_INVESTMENT,
        default=0.0,
        min=0,
        max=1_000_000,
        step=1,
        unit="€",
        group="battery",
    ),
    NumberSetting(
        key=CONF_BAT_LIFETIME,
        default=DEFAULT_BAT_LIFETIME,
        min=1,
        max=30,
        step=1,
        unit="yr",
        group="battery",
    ),
)

SWITCH_SETTINGS: tuple[SwitchSetting, ...] = (
    SwitchSetting(key=CONF_FIXED_NET_METERING, default=True, group="fixed"),
    SwitchSetting(key=CONF_DYN_NET_METERING, default=True, group="dynamic"),
    SwitchSetting(key=CONF_BAT_ENABLED, default=False, group="battery"),
    SwitchSetting(key=CONF_BAT_GRID_CHARGING, default=True, group="battery"),
)


def async_update_option(hass: HomeAssistant, entry: HasimConfigEntry, key: str, value) -> None:
    """Persist one option; the entry's update listener triggers a new simulation."""
    options = dict(entry.options)
    if value is None:
        options.pop(key, None)
    else:
        options[key] = value
    hass.config_entries.async_update_entry(entry, options=options)


UpdateFn = Callable[[str, object], Awaitable[None] | None]
