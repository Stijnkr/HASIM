"""Tests for the HASIM simulation engine (no Home Assistant needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "hasim_simulation",
    Path(__file__).resolve().parent.parent / "custom_components" / "hasim" / "simulation.py",
)
sim = importlib.util.module_from_spec(_SPEC)
sys.modules["hasim_simulation"] = sim
_SPEC.loader.exec_module(sim)


def _hours(n: int) -> list[datetime]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [start + timedelta(hours=i) for i in range(n)]


def _inp(imp, exp, spot, solar=None, price=0.25, export_price=0.10):
    n = len(imp)
    grid = sim.GridSeries(
        "grid", "Net", list(imp), list(exp), import_price=price, export_price=export_price
    )
    return sim.SimulationInput(
        hours=_hours(n),
        grids=[grid],
        solar_kwh=list(solar) if solar else [0.0] * n,
        spot_price=list(spot),
    )


def test_fixed_without_net_metering():
    inp = _inp([1, 2, 0, 0], [0, 0, 3, 0], [0.1] * 4)
    res = sim.fixed_contract_cost(inp, sim.FixedContract(net_metering=False))
    assert res.cost == pytest.approx(3 * 0.25 - 3 * 0.10)


def test_fixed_with_net_metering_import_surplus():
    inp = _inp([4, 2, 0, 0], [0, 0, 3, 0], [0.1] * 4)
    res = sim.fixed_contract_cost(inp, sim.FixedContract(net_metering=True))
    assert res.cost == pytest.approx((6 - 3) * 0.25)


def test_fixed_with_net_metering_export_surplus():
    inp = _inp([1, 0, 0, 0], [0, 0, 3, 0], [0.1] * 4)
    res = sim.fixed_contract_cost(inp, sim.FixedContract(net_metering=True))
    assert res.cost == pytest.approx(-(3 - 1) * 0.10)


def test_fixed_standing_charges_scale_with_days():
    n = 24 * 30
    inp = _inp([0] * n, [0] * n, [0.1] * n)
    res = sim.fixed_contract_cost(
        inp, sim.FixedContract(standing_charge_month=6.0, feed_in_fee_month=2.0)
    )
    assert res.fixed_cost == pytest.approx(8.0 * 30 / sim.DAYS_PER_MONTH)


def test_fixed_uses_per_grid_prices():
    n = 2
    g1 = sim.GridSeries("t1", "T1", [1, 0], [0, 0], import_price=0.20)
    g2 = sim.GridSeries("t2", "T2", [0, 1], [0, 0], import_price=0.30)
    inp = sim.SimulationInput(_hours(n), [g1, g2], [0.0] * n, [0.1] * n)
    res = sim.fixed_contract_cost(inp, sim.FixedContract())
    assert res.cost == pytest.approx(0.50)
    assert res.breakdown["t1"] == pytest.approx(0.20)


def test_dynamic_without_net_metering():
    inp = _inp([1, 0], [0, 1], [0.10, 0.20])
    c = sim.DynamicContract(
        markup_import=0.02,
        markup_export=0.01,
        energy_tax=0.10,
        vat=0.21,
        net_metering=False,
    )
    res = sim.dynamic_contract_cost(inp, c)
    expected = (0.10 + 0.02 + 0.10) * 1.21 - (0.20 - 0.01) * 1.21
    assert res.cost == pytest.approx(expected)


def test_dynamic_net_metering_only_nets_tax():
    inp = _inp([1, 0], [0, 1], [0.10, 0.20])
    c = sim.DynamicContract(
        markup_import=0.0,
        markup_export=0.0,
        energy_tax=0.10,
        vat=0.0,
        net_metering=True,
    )
    res = sim.dynamic_contract_cost(inp, c)
    # tax fully netted; spot cost 0.10 - export income 0.20
    assert res.cost == pytest.approx(-0.10)
    assert res.breakdown["energy_tax"] == pytest.approx(0.0)


def test_battery_self_consumption_shifts_solar_export():
    # Hour 0: 4 kWh export (solar), hour 1: 4 kWh import.
    bat = sim.BatteryConfig(
        capacity_kwh=10,
        max_charge_kw=5,
        max_discharge_kw=5,
        roundtrip_efficiency=1.0,
        min_soc=0.0,
        grid_charging=False,
    )
    flows = sim.optimise_battery([0, 4], [4, 0], [0.30, 0.30], [0.05, 0.05], bat)
    assert flows.total_charge == pytest.approx(4.0)
    assert flows.total_discharge == pytest.approx(4.0)
    assert sum(flows.import_kwh) == pytest.approx(0.0)
    assert sum(flows.export_kwh) == pytest.approx(0.0)


def test_battery_does_nothing_when_prices_flat_and_netting():
    bat = sim.BatteryConfig(
        capacity_kwh=10,
        max_charge_kw=5,
        max_discharge_kw=5,
        roundtrip_efficiency=0.9,
        min_soc=0.0,
    )
    flows = sim.optimise_battery([0, 4], [4, 0], [0.25, 0.25], [0.25, 0.25], bat)
    assert flows.total_charge == pytest.approx(0.0)


def test_battery_arbitrage_charges_cheap_discharges_expensive():
    bat = sim.BatteryConfig(
        capacity_kwh=5,
        max_charge_kw=5,
        max_discharge_kw=5,
        roundtrip_efficiency=1.0,
        min_soc=0.0,
        grid_charging=True,
    )
    p_imp = [0.05, 0.40]
    p_exp = [0.04, 0.39]
    flows = sim.optimise_battery([1, 1], [0, 0], p_imp, p_exp, bat)
    # Charge fully at the cheap hour, cover own load and export the rest.
    assert flows.import_kwh[0] == pytest.approx(6.0)
    assert flows.export_kwh[1] == pytest.approx(4.0)


def test_battery_respects_power_limit():
    bat = sim.BatteryConfig(
        capacity_kwh=10,
        max_charge_kw=2,
        max_discharge_kw=2,
        roundtrip_efficiency=1.0,
        min_soc=0.0,
    )
    flows = sim.optimise_battery([0, 0], [0, 0], [0.05, 0.50], [0.04, 0.49], bat)
    assert flows.charge_kwh[0] <= 2.0 + 1e-9
    assert flows.discharge_kwh[1] <= 2.0 + 1e-9


def test_run_simulation_all_scenarios_and_best():
    n = 48
    imp = [1.0 if h % 24 >= 17 else 0.2 for h in range(n)]
    exp = [2.0 if 10 <= h % 24 <= 15 else 0.0 for h in range(n)]
    solar = [2.5 if 9 <= h % 24 <= 16 else 0.0 for h in range(n)]
    spot = [0.25 if h % 24 >= 17 else 0.02 for h in range(n)]
    inp = _inp(imp, exp, spot, solar)
    bat = sim.BatteryConfig(10, 5, 5, 0.9, investment=5000, min_soc=0.0)
    res = sim.run_simulation(
        inp,
        sim.FixedContract(net_metering=False),
        sim.DynamicContract(net_metering=False),
        bat,
    )
    assert set(res.scenarios) == set(sim.SCENARIOS)
    assert res.best in sim.SCENARIOS
    assert res.scenarios["dynamic_battery"].cost <= res.scenarios["dynamic"].cost + 1e-9
    assert res.scenarios["fixed_battery"].cost <= res.scenarios["fixed"].cost + 1e-9
    assert res.consumption_kwh == pytest.approx(sum(imp) + sum(solar) - sum(exp))
    payback = res.battery_payback_years()
    assert payback is None or payback > 0


def test_split_flows_keeps_totals():
    n = 3
    g1 = sim.GridSeries("t1", "T1", [1, 0, 0], [0, 0, 0], 0.2)
    g2 = sim.GridSeries("t2", "T2", [0, 2, 0], [0, 0, 1], 0.3)
    inp = sim.SimulationInput(_hours(n), [g1, g2], [0.0] * n, [0.1] * n)
    imports, exports = sim._split_flows(inp, [1.5, 1.0, 0.5], [0.0, 0.5, 0.0])
    for h in range(n):
        assert imports[0][h] + imports[1][h] == pytest.approx([1.5, 1.0, 0.5][h])
        assert exports[0][h] + exports[1][h] == pytest.approx([0.0, 0.5, 0.0][h])
    assert imports[1][1] == pytest.approx(1.0)
    assert imports[1][2] == pytest.approx(0.5)  # hour with only export on t2
