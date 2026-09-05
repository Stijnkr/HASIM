"""Sensors for HASIM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NAME
from .coordinator import HasimConfigEntry, HasimCoordinator, HasimData
from .simulation import (
    SCENARIO_DYNAMIC,
    SCENARIO_DYNAMIC_BATTERY,
    SCENARIO_FIXED,
    SCENARIO_FIXED_BATTERY,
    SCENARIOS,
    ScenarioResult,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HasimSensorDescription(SensorEntityDescription):
    """Describes a HASIM sensor."""

    value_fn: Callable[[HasimData], Any]
    attr_fn: Callable[[HasimData], dict[str, Any]] | None = None
    requires_battery: bool = False


def _scenario(data: HasimData, key: str) -> ScenarioResult | None:
    return data.result.scenarios.get(key)


def _scenario_value(key: str) -> Callable[[HasimData], float | None]:
    def _fn(data: HasimData) -> float | None:
        s = _scenario(data, key)
        return round(s.cost, 2) if s else None

    return _fn


def _scenario_attrs(key: str) -> Callable[[HasimData], dict[str, Any]]:
    def _fn(data: HasimData) -> dict[str, Any]:
        s = _scenario(data, key)
        if not s:
            return {}
        return {
            "annual_cost": round(s.annual_cost, 2),
            "energy_cost": round(s.energy_cost, 2),
            "standing_costs": round(s.fixed_cost, 2),
            "import_kwh": round(s.import_kwh, 1),
            "export_kwh": round(s.export_kwh, 1),
            "battery_charge_kwh": round(s.battery_charge_kwh, 1),
            "battery_discharge_kwh": round(s.battery_discharge_kwh, 1),
            "battery_cycles": round(s.battery_cycles, 1),
            "breakdown": {k: round(v, 2) for k, v in s.breakdown.items()},
            "days": round(s.days, 1),
        }

    return _fn


def _slot_stats(slots: list) -> dict[str, Any]:
    if not slots:
        return {"available": False}
    prices = [s.price for s in slots]
    cheapest = min(slots, key=lambda s: s.price)
    priciest = max(slots, key=lambda s: s.price)
    return {
        "available": True,
        "average": round(sum(prices) / len(prices), 5),
        "min": round(cheapest.price, 5),
        "min_start": cheapest.start.isoformat(),
        "max": round(priciest.price, 5),
        "max_start": priciest.start.isoformat(),
    }


def _day_prices(which: str) -> Callable[[HasimData], dict[str, Any]]:
    def _fn(data: HasimData) -> dict[str, Any]:
        slots = getattr(data, which)
        attrs = _slot_stats(slots)
        attrs["prices"] = [s.as_dict() for s in slots]
        return attrs

    return _fn


def _current_price(data: HasimData) -> float | None:
    slot = data.current_slot(dt_util.now())
    return round(slot.price, 5) if slot else None


def _current_price_attrs(data: HasimData) -> dict[str, Any]:
    now = dt_util.now()
    slot = data.current_slot(now)
    nxt = data.next_slot(now)
    return {
        "spot": round(slot.spot, 5) if slot else None,
        "export_price": round(slot.export_price, 5) if slot else None,
        "next_price": round(nxt.price, 5) if nxt else None,
        "next_start": nxt.start.isoformat() if nxt else None,
        "markup": data.dynamic.markup_import,
        "energy_tax": data.dynamic.energy_tax,
        "vat": data.dynamic.vat,
        "today": _slot_stats(data.today),
        "tomorrow": _slot_stats(data.tomorrow),
    }


def _day_value(which: str, stat: str) -> Callable[[HasimData], float | None]:
    def _fn(data: HasimData) -> float | None:
        slots = getattr(data, which)
        if not slots:
            return None
        prices = [s.price for s in slots]
        if stat == "avg":
            return round(sum(prices) / len(prices), 5)
        if stat == "min":
            return round(min(prices), 5)
        return round(max(prices), 5)

    return _fn


def _savings_dynamic(data: HasimData) -> float | None:
    r = data.result
    if SCENARIO_DYNAMIC not in r.scenarios:
        return None
    return round(r.annual_saving(SCENARIO_DYNAMIC, SCENARIO_FIXED), 2)


def _best_battery_key(data: HasimData) -> str | None:
    cands = [
        s
        for k, s in data.result.scenarios.items()
        if k in (SCENARIO_FIXED_BATTERY, SCENARIO_DYNAMIC_BATTERY)
    ]
    if not cands:
        return None
    return min(cands, key=lambda s: s.cost).key


def _savings_battery(data: HasimData) -> float | None:
    key = _best_battery_key(data)
    if key is None:
        return None
    return round(data.result.annual_saving(key, data.result.best_without_battery), 2)


def _savings_battery_attrs(data: HasimData) -> dict[str, Any]:
    r = data.result
    key = _best_battery_key(data)
    if key is None:
        return {}
    payback = r.battery_payback_years()
    return {
        "best_battery_scenario": key,
        "baseline_scenario": r.best_without_battery,
        "saving_vs_fixed": round(r.annual_saving(SCENARIO_FIXED_BATTERY, SCENARIO_FIXED), 2)
        if SCENARIO_FIXED_BATTERY in r.scenarios
        else None,
        "saving_vs_dynamic": round(r.annual_saving(SCENARIO_DYNAMIC_BATTERY, SCENARIO_DYNAMIC), 2)
        if SCENARIO_DYNAMIC_BATTERY in r.scenarios
        else None,
        "payback_years": round(payback, 1) if payback else None,
        "investment": r.battery.investment if r.battery else None,
        "lifetime_years": r.battery.lifetime_years if r.battery else None,
        "pays_back_within_lifetime": (
            payback is not None and r.battery is not None and payback <= r.battery.lifetime_years
        ),
    }


def _payback(data: HasimData) -> float | None:
    payback = data.result.battery_payback_years()
    return round(payback, 1) if payback is not None else None


def _best_attrs(data: HasimData) -> dict[str, Any]:
    r = data.result
    ranking = sorted(r.scenarios.values(), key=lambda s: s.cost)
    return {
        "period_start": data.period_start.isoformat(),
        "period_end": data.period_end.isoformat(),
        "days": round(r.days, 1),
        "hours": r.hours,
        "hours_without_price": data.hours_without_price,
        "hours_without_data": data.hours_without_data,
        "ranking": [s.key for s in ranking],
        "annual_costs": {s.key: round(s.annual_cost, 2) for s in ranking},
        "period_costs": {s.key: round(s.cost, 2) for s in ranking},
        "grid_connections": [g.name for g in data.dashboard.grids],
        "solar_statistics": data.dashboard.solar_stats,
        "existing_battery": bool(
            data.dashboard.battery_from_stats or data.dashboard.battery_to_stats
        ),
    }


DESCRIPTIONS: tuple[HasimSensorDescription, ...] = (
    HasimSensorDescription(
        key="current_price",
        translation_key="current_price",
        native_unit_of_measurement="€/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        value_fn=_current_price,
        attr_fn=_current_price_attrs,
    ),
    HasimSensorDescription(
        key="price_today_average",
        translation_key="price_today_average",
        native_unit_of_measurement="€/kWh",
        suggested_display_precision=4,
        value_fn=_day_value("today", "avg"),
        attr_fn=_day_prices("today"),
    ),
    HasimSensorDescription(
        key="price_today_min",
        translation_key="price_today_min",
        native_unit_of_measurement="€/kWh",
        suggested_display_precision=4,
        value_fn=_day_value("today", "min"),
    ),
    HasimSensorDescription(
        key="price_today_max",
        translation_key="price_today_max",
        native_unit_of_measurement="€/kWh",
        suggested_display_precision=4,
        value_fn=_day_value("today", "max"),
    ),
    HasimSensorDescription(
        key="price_tomorrow_average",
        translation_key="price_tomorrow_average",
        native_unit_of_measurement="€/kWh",
        suggested_display_precision=4,
        value_fn=_day_value("tomorrow", "avg"),
        attr_fn=_day_prices("tomorrow"),
    ),
    HasimSensorDescription(
        key="cost_fixed",
        translation_key="cost_fixed",
        native_unit_of_measurement="€",
        suggested_display_precision=2,
        value_fn=_scenario_value(SCENARIO_FIXED),
        attr_fn=_scenario_attrs(SCENARIO_FIXED),
    ),
    HasimSensorDescription(
        key="cost_dynamic",
        translation_key="cost_dynamic",
        native_unit_of_measurement="€",
        suggested_display_precision=2,
        value_fn=_scenario_value(SCENARIO_DYNAMIC),
        attr_fn=_scenario_attrs(SCENARIO_DYNAMIC),
    ),
    HasimSensorDescription(
        key="cost_fixed_battery",
        translation_key="cost_fixed_battery",
        native_unit_of_measurement="€",
        suggested_display_precision=2,
        value_fn=_scenario_value(SCENARIO_FIXED_BATTERY),
        attr_fn=_scenario_attrs(SCENARIO_FIXED_BATTERY),
        requires_battery=True,
    ),
    HasimSensorDescription(
        key="cost_dynamic_battery",
        translation_key="cost_dynamic_battery",
        native_unit_of_measurement="€",
        suggested_display_precision=2,
        value_fn=_scenario_value(SCENARIO_DYNAMIC_BATTERY),
        attr_fn=_scenario_attrs(SCENARIO_DYNAMIC_BATTERY),
        requires_battery=True,
    ),
    HasimSensorDescription(
        key="savings_dynamic",
        translation_key="savings_dynamic",
        native_unit_of_measurement="€/yr",
        suggested_display_precision=0,
        value_fn=_savings_dynamic,
    ),
    HasimSensorDescription(
        key="savings_battery",
        translation_key="savings_battery",
        native_unit_of_measurement="€/yr",
        suggested_display_precision=0,
        value_fn=_savings_battery,
        attr_fn=_savings_battery_attrs,
        requires_battery=True,
    ),
    HasimSensorDescription(
        key="battery_payback",
        translation_key="battery_payback",
        native_unit_of_measurement="yr",
        suggested_display_precision=1,
        value_fn=_payback,
        requires_battery=True,
    ),
    HasimSensorDescription(
        key="best_scenario",
        translation_key="best_scenario",
        device_class=SensorDeviceClass.ENUM,
        options=list(SCENARIOS),
        value_fn=lambda d: d.result.best,
        attr_fn=_best_attrs,
    ),
    HasimSensorDescription(
        key="period_import",
        translation_key="period_import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: round(d.result.import_kwh, 2),
    ),
    HasimSensorDescription(
        key="period_export",
        translation_key="period_export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: round(d.result.export_kwh, 2),
    ),
    HasimSensorDescription(
        key="period_solar",
        translation_key="period_solar",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: round(d.result.solar_kwh, 2),
    ),
    HasimSensorDescription(
        key="period_consumption",
        translation_key="period_consumption",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda d: round(d.result.consumption_kwh, 2),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HasimConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    has_battery = coordinator.data.battery is not None
    async_add_entities(
        HasimSensor(coordinator, description)
        for description in DESCRIPTIONS
        if has_battery or not description.requires_battery
    )


class HasimSensor(CoordinatorEntity[HasimCoordinator], SensorEntity):
    """A HASIM sensor."""

    entity_description: HasimSensorDescription
    _attr_has_entity_name = True
    # Price lists are for live cards (e.g. ApexCharts), not for history.
    _unrecorded_attributes = frozenset({"prices"})

    def __init__(self, coordinator: HasimCoordinator, description: HasimSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=NAME,
            manufacturer="HASIM",
            model=f"Day-ahead {coordinator.area}",
            entry_type=DeviceEntryType.SERVICE,
        )
        currency = coordinator.currency
        unit = description.native_unit_of_measurement
        if unit and "€" in unit and currency != "EUR":
            self._attr_native_unit_of_measurement = unit.replace("€", currency)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data)
