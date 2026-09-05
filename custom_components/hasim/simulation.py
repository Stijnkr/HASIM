"""Pure-Python simulation engine for HASIM.

No Home Assistant imports here so the engine can be unit-tested standalone.

All energy values are kWh per hour, all prices are EUR/kWh (or the configured
currency). Spot prices are the raw day-ahead prices *excluding* VAT, energy
tax and supplier markup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math

DAYS_PER_MONTH = 365.25 / 12

SCENARIO_FIXED = "fixed"
SCENARIO_DYNAMIC = "dynamic"
SCENARIO_FIXED_BATTERY = "fixed_battery"
SCENARIO_DYNAMIC_BATTERY = "dynamic_battery"
SCENARIOS = (
    SCENARIO_FIXED,
    SCENARIO_DYNAMIC,
    SCENARIO_FIXED_BATTERY,
    SCENARIO_DYNAMIC_BATTERY,
)


@dataclass(slots=True)
class GridSeries:
    """Hourly import/export of one grid connection from the energy dashboard."""

    key: str
    name: str
    import_kwh: list[float]
    export_kwh: list[float]
    # Fixed prices as configured in the energy dashboard (incl. tax/VAT).
    import_price: float | None = None
    export_price: float | None = None


@dataclass(slots=True)
class SimulationInput:
    """Aligned hourly series for the simulation period."""

    hours: list[datetime]
    grids: list[GridSeries]
    solar_kwh: list[float]
    spot_price: list[float]  # EUR/kWh excl. VAT / tax / markup

    @property
    def n(self) -> int:
        """Number of hours."""
        return len(self.hours)

    @property
    def days(self) -> float:
        """Length of the period in days."""
        return self.n / 24

    def total_import(self) -> list[float]:
        """Sum of import across grid connections."""
        return [sum(g.import_kwh[i] for g in self.grids) for i in range(self.n)]

    def total_export(self) -> list[float]:
        """Sum of export across grid connections."""
        return [sum(g.export_kwh[i] for g in self.grids) for i in range(self.n)]

    def consumption(self) -> list[float]:
        """House consumption = import + solar - export (clipped at 0)."""
        imp = self.total_import()
        exp = self.total_export()
        return [max(0.0, imp[i] + self.solar_kwh[i] - exp[i]) for i in range(self.n)]


@dataclass(slots=True)
class FixedContract:
    """Fixed-price contract."""

    # Override for all grid connections; None = use energy dashboard prices.
    import_price: float | None = None
    # Feed-in compensation for (net) exported kWh; None = dashboard export price.
    export_price: float | None = None
    net_metering: bool = True
    standing_charge_month: float = 0.0
    feed_in_fee_month: float = 0.0


@dataclass(slots=True)
class DynamicContract:
    """Dynamic (day-ahead) contract."""

    markup_import: float = 0.02  # supplier markup EUR/kWh excl. VAT
    markup_export: float = 0.0  # supplier fee on exported kWh excl. VAT
    energy_tax: float = 0.10154  # EUR/kWh excl. VAT
    vat: float = 0.21
    net_metering: bool = True
    standing_charge_month: float = 0.0
    feed_in_fee_month: float = 0.0

    def import_price(self, spot: float, *, include_tax: bool = True) -> float:
        """All-in import price for a spot price."""
        tax = self.energy_tax if include_tax else 0.0
        return (spot + self.markup_import + tax) * (1 + self.vat)

    def export_price(self, spot: float) -> float:
        """Export price for a spot price."""
        return (spot - self.markup_export) * (1 + self.vat)


@dataclass(slots=True)
class BatteryConfig:
    """Hypothetical home battery."""

    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    roundtrip_efficiency: float = 0.90
    min_soc: float = 0.10
    max_soc: float = 1.0
    investment: float = 0.0
    lifetime_years: float = 10.0
    grid_charging: bool = True
    degradation_cost_kwh: float = 0.0

    @property
    def usable_kwh(self) -> float:
        """Usable capacity."""
        return max(0.0, self.capacity_kwh * (self.max_soc - self.min_soc))

    @property
    def one_way_efficiency(self) -> float:
        """Efficiency for one direction (charge or discharge)."""
        return math.sqrt(max(0.01, min(1.0, self.roundtrip_efficiency)))


@dataclass(slots=True)
class BatteryFlows:
    """Result of a battery dispatch."""

    import_kwh: list[float]
    export_kwh: list[float]
    charge_kwh: list[float]  # AC energy into the battery
    discharge_kwh: list[float]  # AC energy out of the battery
    soc_kwh: list[float]

    @property
    def total_charge(self) -> float:
        return sum(self.charge_kwh)

    @property
    def total_discharge(self) -> float:
        return sum(self.discharge_kwh)


@dataclass(slots=True)
class ScenarioResult:
    """Cost result of one scenario."""

    key: str
    cost: float
    energy_cost: float
    fixed_cost: float
    import_kwh: float
    export_kwh: float
    days: float
    battery_charge_kwh: float = 0.0
    battery_discharge_kwh: float = 0.0
    battery_cycles: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def annual_cost(self) -> float:
        """Cost extrapolated to a full year."""
        if self.days <= 0:
            return 0.0
        return self.cost * 365 / self.days

    def as_dict(self) -> dict:
        """Serialisable representation."""
        return {
            "key": self.key,
            "cost": round(self.cost, 2),
            "energy_cost": round(self.energy_cost, 2),
            "fixed_cost": round(self.fixed_cost, 2),
            "annual_cost": round(self.annual_cost, 2),
            "import_kwh": round(self.import_kwh, 2),
            "export_kwh": round(self.export_kwh, 2),
            "battery_charge_kwh": round(self.battery_charge_kwh, 2),
            "battery_discharge_kwh": round(self.battery_discharge_kwh, 2),
            "battery_cycles": round(self.battery_cycles, 1),
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
        }


@dataclass(slots=True)
class SimulationResult:
    """Full simulation result."""

    days: float
    hours: int
    scenarios: dict[str, ScenarioResult]
    import_kwh: float
    export_kwh: float
    solar_kwh: float
    consumption_kwh: float
    battery: BatteryConfig | None = None

    @property
    def best(self) -> str:
        """Key of the cheapest scenario."""
        return min(self.scenarios.values(), key=lambda s: s.cost).key

    @property
    def best_without_battery(self) -> str:
        """Cheapest scenario without a battery."""
        return min(
            (s for s in self.scenarios.values() if s.key in (SCENARIO_FIXED, SCENARIO_DYNAMIC)),
            key=lambda s: s.cost,
        ).key

    def annual_saving(self, scenario: str, baseline: str) -> float:
        """Annual saving of `scenario` compared to `baseline` (positive = cheaper)."""
        return self.scenarios[baseline].annual_cost - self.scenarios[scenario].annual_cost

    def battery_payback_years(self) -> float | None:
        """Payback time of the battery, using the best battery scenario."""
        if self.battery is None or self.battery.investment <= 0:
            return None
        base = self.best_without_battery
        best_bat = min(
            (
                s
                for s in self.scenarios.values()
                if s.key in (SCENARIO_FIXED_BATTERY, SCENARIO_DYNAMIC_BATTERY)
            ),
            key=lambda s: s.cost,
            default=None,
        )
        if best_bat is None:
            return None
        saving = self.annual_saving(best_bat.key, base)
        if saving <= 0:
            return None
        return self.battery.investment / saving


# ---------------------------------------------------------------------------
# Cost functions
# ---------------------------------------------------------------------------


def _months(days: float) -> float:
    return days / DAYS_PER_MONTH


def fixed_contract_cost(
    inp: SimulationInput,
    contract: FixedContract,
    imports: list[list[float]] | None = None,
    exports: list[list[float]] | None = None,
) -> ScenarioResult:
    """Cost for a fixed contract, per grid connection."""
    imports = imports if imports is not None else [g.import_kwh for g in inp.grids]
    exports = exports if exports is not None else [g.export_kwh for g in inp.grids]
    energy = 0.0
    breakdown: dict[str, float] = {}
    tot_imp = 0.0
    tot_exp = 0.0
    for grid, imp, exp in zip(inp.grids, imports, exports, strict=True):
        price = (
            contract.import_price
            if contract.import_price is not None
            else (grid.import_price or 0.0)
        )
        exp_price = (
            contract.export_price
            if contract.export_price is not None
            else (grid.export_price or 0.0)
        )
        s_imp = sum(imp)
        s_exp = sum(exp)
        tot_imp += s_imp
        tot_exp += s_exp
        if contract.net_metering:
            net = s_imp - s_exp
            cost = price * max(net, 0.0) - exp_price * max(-net, 0.0)
        else:
            cost = price * s_imp - exp_price * s_exp
        breakdown[grid.key] = cost
        energy += cost
    months = _months(inp.days)
    fixed = months * (contract.standing_charge_month + contract.feed_in_fee_month)
    breakdown["standing_charges"] = months * contract.standing_charge_month
    breakdown["feed_in_fees"] = months * contract.feed_in_fee_month
    return ScenarioResult(
        key=SCENARIO_FIXED,
        cost=energy + fixed,
        energy_cost=energy,
        fixed_cost=fixed,
        import_kwh=tot_imp,
        export_kwh=tot_exp,
        days=inp.days,
        breakdown=breakdown,
    )


def dynamic_contract_cost(
    inp: SimulationInput,
    contract: DynamicContract,
    total_import: list[float] | None = None,
    total_export: list[float] | None = None,
) -> ScenarioResult:
    """Cost for a dynamic contract."""
    imp = total_import if total_import is not None else inp.total_import()
    exp = total_export if total_export is not None else inp.total_export()
    vat = 1 + contract.vat
    spot_cost = 0.0
    markup_cost = 0.0
    export_income = 0.0
    for i, spot in enumerate(inp.spot_price):
        spot_cost += imp[i] * spot * vat
        markup_cost += imp[i] * contract.markup_import * vat
        export_income += exp[i] * (spot - contract.markup_export) * vat
    s_imp = sum(imp)
    s_exp = sum(exp)
    tax_base = max(0.0, s_imp - s_exp) if contract.net_metering else s_imp
    tax_cost = tax_base * contract.energy_tax * vat
    energy = spot_cost + markup_cost + tax_cost - export_income
    months = _months(inp.days)
    fixed = months * (contract.standing_charge_month + contract.feed_in_fee_month)
    return ScenarioResult(
        key=SCENARIO_DYNAMIC,
        cost=energy + fixed,
        energy_cost=energy,
        fixed_cost=fixed,
        import_kwh=s_imp,
        export_kwh=s_exp,
        days=inp.days,
        breakdown={
            "spot": spot_cost,
            "markup": markup_cost,
            "energy_tax": tax_cost,
            "export_income": -export_income,
            "standing_charges": months * contract.standing_charge_month,
            "feed_in_fees": months * contract.feed_in_fee_month,
        },
    )


# ---------------------------------------------------------------------------
# Battery dispatch (dynamic programming over discretised state of charge)
# ---------------------------------------------------------------------------


def optimise_battery(
    base_import: list[float],
    base_export: list[float],
    price_import: list[float],
    price_export: list[float],
    battery: BatteryConfig,
) -> BatteryFlows:
    """Find the cost-minimising hourly battery dispatch.

    Exact (for the SOC discretisation) dynamic programme with perfect
    foresight over the whole period. Real controllers only see day-ahead
    prices, so this is an upper bound on what a battery can achieve.
    """
    n = len(base_import)
    usable = battery.usable_kwh
    eff = battery.one_way_efficiency
    max_charge_stored = battery.max_charge_kw * eff  # kWh stored per hour
    max_discharge_stored = battery.max_discharge_kw / eff  # kWh drawn per hour
    if n == 0 or usable <= 0 or max_charge_stored <= 0 or max_discharge_stored <= 0:
        return BatteryFlows(list(base_import), list(base_export), [0.0] * n, [0.0] * n, [0.0] * n)

    min_pow = min(max_charge_stored, max_discharge_stored)
    levels = int(min(60, max(10, math.ceil(usable / min_pow) * 2)))
    step = usable / levels
    k_charge = max(1, int(max_charge_stored / step + 1e-9))
    k_discharge = max(1, int(max_discharge_stored / step + 1e-9))
    inf = float("inf")
    degr = battery.degradation_cost_kwh

    cost = [0.0] + [inf] * levels  # start empty
    choice: list[list[int]] = []
    for h in range(n):
        b_imp = base_import[h]
        b_exp = base_export[h]
        p_imp = price_import[h]
        p_exp = price_export[h]
        new_cost = [inf] * (levels + 1)
        new_choice = [0] * (levels + 1)
        for lvl in range(levels + 1):
            c0 = cost[lvl]
            if c0 == inf:
                continue
            lo = max(-k_discharge, -lvl)
            hi = min(k_charge, levels - lvl)
            for d in range(lo, hi + 1):
                stored = d * step
                if d > 0:
                    ac_in = stored / eff
                    ac_out = 0.0
                    if not battery.grid_charging and ac_in > b_exp + 1e-9:
                        continue
                elif d < 0:
                    ac_in = 0.0
                    ac_out = -stored * eff
                    if not battery.grid_charging and ac_out > b_imp + 1e-9:
                        continue
                else:
                    ac_in = ac_out = 0.0
                net = b_imp - b_exp + ac_in - ac_out
                hour_cost = (net * p_imp if net > 0 else net * p_exp) + abs(stored) * degr
                total = c0 + hour_cost
                nl = lvl + d
                if total < new_cost[nl]:
                    new_cost[nl] = total
                    new_choice[nl] = d
        cost = new_cost
        choice.append(new_choice)

    # Backtrack from the cheapest final state.
    lvl = min(range(levels + 1), key=lambda i: cost[i])
    deltas = [0] * n
    for h in range(n - 1, -1, -1):
        d = choice[h][lvl]
        deltas[h] = d
        lvl -= d

    imp = [0.0] * n
    exp = [0.0] * n
    charge = [0.0] * n
    discharge = [0.0] * n
    soc = [0.0] * n
    level = 0
    for h in range(n):
        d = deltas[h]
        level += d
        stored = d * step
        ac_in = stored / eff if d > 0 else 0.0
        ac_out = -stored * eff if d < 0 else 0.0
        net = base_import[h] - base_export[h] + ac_in - ac_out
        imp[h] = max(net, 0.0)
        exp[h] = max(-net, 0.0)
        charge[h] = ac_in
        discharge[h] = ac_out
        soc[h] = level * step + battery.capacity_kwh * battery.min_soc
    return BatteryFlows(imp, exp, charge, discharge, soc)


def _split_flows(
    inp: SimulationInput, total_import: list[float], total_export: list[float]
) -> tuple[list[list[float]], list[list[float]]]:
    """Split total flows back over the grid connections, proportionally."""
    n_grid = len(inp.grids)
    imports = [[0.0] * inp.n for _ in range(n_grid)]
    exports = [[0.0] * inp.n for _ in range(n_grid)]
    for h in range(inp.n):
        base_imp = [g.import_kwh[h] for g in inp.grids]
        base_exp = [g.export_kwh[h] for g in inp.grids]
        s_imp = sum(base_imp)
        s_exp = sum(base_exp)
        active = [i for i in range(n_grid) if base_imp[i] > 0 or base_exp[i] > 0]
        fallback = active[0] if active else 0
        for i in range(n_grid):
            if s_imp > 0:
                imports[i][h] = total_import[h] * base_imp[i] / s_imp
            elif i == fallback:
                imports[i][h] = total_import[h]
            if s_exp > 0:
                exports[i][h] = total_export[h] * base_exp[i] / s_exp
            elif i == fallback:
                exports[i][h] = total_export[h]
    return imports, exports


def _weighted_fixed_prices(
    inp: SimulationInput, contract: FixedContract
) -> tuple[list[float], list[float]]:
    """Per-hour effective import/export prices for a fixed contract."""
    p_imp: list[float] = []
    p_exp: list[float] = []
    for h in range(inp.n):
        num = 0.0
        den = 0.0
        exp_price = 0.0
        best_price = 0.0
        for g in inp.grids:
            price = (
                contract.import_price
                if contract.import_price is not None
                else (g.import_price or 0.0)
            )
            g_exp_price = (
                contract.export_price
                if contract.export_price is not None
                else (g.export_price or 0.0)
            )
            weight = g.import_kwh[h] + g.export_kwh[h]
            num += price * weight
            den += weight
            if weight > 0 or best_price == 0.0:
                best_price = price
                exp_price = g_exp_price
        price = num / den if den > 0 else best_price
        p_imp.append(price)
        # With net metering each exported kWh cancels an imported one.
        p_exp.append(price if contract.net_metering else exp_price)
    return p_imp, p_exp


def _with_battery(
    result: ScenarioResult, flows: BatteryFlows, key: str, battery: BatteryConfig
) -> ScenarioResult:
    result.key = key
    result.battery_charge_kwh = flows.total_charge
    result.battery_discharge_kwh = flows.total_discharge
    result.battery_cycles = (
        flows.total_discharge / battery.usable_kwh if battery.usable_kwh else 0.0
    )
    return result


def run_simulation(
    inp: SimulationInput,
    fixed: FixedContract,
    dynamic: DynamicContract,
    battery: BatteryConfig | None = None,
) -> SimulationResult:
    """Run all scenarios."""
    scenarios: dict[str, ScenarioResult] = {}
    scenarios[SCENARIO_FIXED] = fixed_contract_cost(inp, fixed)
    scenarios[SCENARIO_DYNAMIC] = dynamic_contract_cost(inp, dynamic)

    total_import = inp.total_import()
    total_export = inp.total_export()

    if battery is not None and battery.capacity_kwh > 0:
        # Fixed contract + battery
        p_imp, p_exp = _weighted_fixed_prices(inp, fixed)
        flows = optimise_battery(total_import, total_export, p_imp, p_exp, battery)
        imports, exports = _split_flows(inp, flows.import_kwh, flows.export_kwh)
        res = fixed_contract_cost(inp, fixed, imports, exports)
        scenarios[SCENARIO_FIXED_BATTERY] = _with_battery(
            res, flows, SCENARIO_FIXED_BATTERY, battery
        )

        # Dynamic contract + battery
        p_imp = [
            dynamic.import_price(s, include_tax=not dynamic.net_metering) for s in inp.spot_price
        ]
        p_exp = [dynamic.export_price(s) for s in inp.spot_price]
        flows = optimise_battery(total_import, total_export, p_imp, p_exp, battery)
        res = dynamic_contract_cost(inp, dynamic, flows.import_kwh, flows.export_kwh)
        scenarios[SCENARIO_DYNAMIC_BATTERY] = _with_battery(
            res, flows, SCENARIO_DYNAMIC_BATTERY, battery
        )

    return SimulationResult(
        days=inp.days,
        hours=inp.n,
        scenarios=scenarios,
        import_kwh=sum(total_import),
        export_kwh=sum(total_export),
        solar_kwh=sum(inp.solar_kwh),
        consumption_kwh=sum(inp.consumption()),
        battery=battery,
    )
