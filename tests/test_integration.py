"""Integration tests: config flow, setup and entities (needs HA test harness)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hasim.const import (
    CONF_BAT_CAPACITY,
    CONF_BAT_CHARGE_POWER,
    CONF_BAT_DISCHARGE_POWER,
    CONF_BAT_ENABLED,
    CONF_BAT_INVESTMENT,
    CONF_DAYS,
    CONF_DYN_NET_METERING,
    CONF_FIXED_NET_METERING,
    CONF_PRICE_AREA,
    DOMAIN,
)
from custom_components.hasim.energy_dashboard import (
    EnergyDashboardConfig,
    GridConnection,
)

DASHBOARD = EnergyDashboardConfig(
    grids=[
        GridConnection("grid_0", "Tariff 1", "sensor.imp1", "sensor.exp1", 0.22, None, None, None),
        GridConnection("grid_1", "Tariff 2", "sensor.imp2", "sensor.exp2", 0.24, None, None, None),
    ],
    solar_stats=["sensor.solar"],
)

OPTIONS = {
    CONF_PRICE_AREA: "NL",
    CONF_DAYS: 2,
    CONF_FIXED_NET_METERING: False,
    CONF_DYN_NET_METERING: False,
    CONF_BAT_ENABLED: True,
    CONF_BAT_CAPACITY: 10.0,
    CONF_BAT_CHARGE_POWER: 5.0,
    CONF_BAT_DISCHARGE_POWER: 5.0,
    CONF_BAT_INVESTMENT: 4000.0,
}


def _fake_statistics(hass, start, end, stat_ids, period, units, types):
    rows: dict[str, list[dict]] = {}
    n = int((end - start).total_seconds() // 3600)
    for stat in stat_ids:
        rows[stat] = []
        for i in range(n):
            ts = (start + timedelta(hours=i)).timestamp()
            hour = i % 24
            if stat.startswith("sensor.imp"):
                change = 1.2 if hour >= 17 else 0.3
            elif stat.startswith("sensor.exp"):
                change = 1.5 if 10 <= hour <= 15 else 0.0
            else:
                change = 2.5 if 9 <= hour <= 16 else 0.0
            rows[stat].append({"start": ts, "end": ts + 3600, "change": change})
    return rows


async def _fake_fetch_day(self, day):
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=2)
    return [(start + timedelta(minutes=15 * i), 0.02 + 0.25 * ((i // 4) >= 17)) for i in range(96)]


@pytest.fixture
def _patches():
    with (
        patch(
            "custom_components.hasim.coordinator.async_read_energy_dashboard",
            return_value=DASHBOARD,
        ),
        patch(
            "custom_components.hasim.config_flow.async_read_energy_dashboard",
            return_value=DASHBOARD,
        ),
        patch(
            "custom_components.hasim.coordinator.statistics_during_period",
            side_effect=_fake_statistics,
        ),
        patch("custom_components.hasim.prices.NordPoolClient.fetch_day", _fake_fetch_day),
    ):
        yield


@pytest.mark.usefixtures("_patches")
async def test_setup_creates_entities(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options=OPTIONS, title="HASIM")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    best = hass.states.get("sensor.hasim_best_scenario")
    assert best is not None
    assert best.state in ("fixed", "dynamic", "fixed_battery", "dynamic_battery")
    assert best.attributes["days"] == 2
    assert best.attributes["hours_without_price"] == 0

    fixed = hass.states.get("sensor.hasim_cost_fixed_contract")
    dynamic = hass.states.get("sensor.hasim_cost_dynamic_contract")
    assert fixed is not None and dynamic is not None
    assert float(fixed.state) > 0
    assert "annual_cost" in fixed.attributes

    bat = hass.states.get("sensor.hasim_cost_dynamic_contract_with_battery")
    assert bat is not None
    assert float(bat.state) <= float(dynamic.state) + 1e-6

    price = hass.states.get("sensor.hasim_current_dynamic_price")
    assert price is not None
    assert price.state not in ("unknown", "unavailable")
    assert price.attributes["today"]["available"] is True
    today = hass.states.get("sensor.hasim_average_price_today")
    assert len(today.attributes["prices"]) == 96
    assert set(today.attributes["prices"][0]) == {"start", "price", "spot"}

    imp = hass.states.get("sensor.hasim_grid_import_in_period")
    assert float(imp.state) == pytest.approx(2 * 2 * (7 * 1.2 + 17 * 0.3), rel=1e-3)

    # settings entities reflect the options and changing one re-simulates
    days = hass.states.get("number.hasim_simulation_period")
    assert days is not None and float(days.state) == 2
    assert hass.states.get("switch.hasim_fixed_net_metering").state == "off"
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.hasim_fixed_net_metering"}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_FIXED_NET_METERING] is True
    assert hass.states.get("switch.hasim_fixed_net_metering").state == "on"
    fixed_netted = hass.states.get("sensor.hasim_cost_fixed_contract")
    assert float(fixed_netted.state) < float(fixed.state)  # netting lowers the cost

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.hasim_simulation_period", "value": 1},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_DAYS] == 1
    assert hass.states.get("sensor.hasim_best_scenario").attributes["days"] == 1

    # generated dashboard is registered as a panel
    from homeassistant.components.lovelace import LOVELACE_DATA

    dashboard = hass.data[LOVELACE_DATA].dashboards["hasim-energy"]
    cfg = await dashboard.async_load(False)
    assert cfg["views"][0]["sections"][1]["cards"][1]["today"] == "sensor.hasim_average_price_today"

    # service re-runs with another period
    await hass.services.async_call(DOMAIN, "simulate", {"days": 2}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.hasim_best_scenario").attributes["days"] == 2

    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.usefixtures("_patches")
async def test_config_flow(recorder_mock, hass: HomeAssistant, enable_custom_integrations) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRICE_AREA: "NL", "currency": "EUR", CONF_DAYS: 7, "vat": 21}
    )
    assert result["step_id"] == "fixed"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "fixed_export_price": 0.05,
            CONF_FIXED_NET_METERING: True,
            "fixed_standing_charge": 5,
            "fixed_feed_in_fee": 0,
        },
    )
    assert result["step_id"] == "dynamic"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "dynamic_markup_import": 0.02,
            "dynamic_markup_export": 0.0,
            "dynamic_energy_tax": 0.10154,
            CONF_DYN_NET_METERING: True,
            "dynamic_standing_charge": 6,
            "dynamic_feed_in_fee": 0,
        },
    )
    assert result["step_id"] == "battery"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BAT_ENABLED: False,
            CONF_BAT_CAPACITY: 10,
            CONF_BAT_CHARGE_POWER: 5,
            CONF_BAT_DISCHARGE_POWER: 5,
            "battery_efficiency": 90,
            "battery_min_soc": 10,
            CONF_BAT_INVESTMENT: 0,
            "battery_lifetime": 10,
            "battery_grid_charging": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_DAYS] == 7
    await hass.async_block_till_done()

    # No battery configured -> battery entities exist but are unavailable
    assert hass.states.get("sensor.hasim_best_scenario") is not None
    assert hass.states.get("sensor.hasim_cost_dynamic_contract_with_battery").state == "unavailable"
