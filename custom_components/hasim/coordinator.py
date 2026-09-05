"""Data update coordinator for HASIM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
    CONF_CURRENCY,
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
    CONF_PRICE_AREA,
    CONF_VAT,
    DEFAULT_BAT_EFFICIENCY,
    DEFAULT_BAT_LIFETIME,
    DEFAULT_BAT_MIN_SOC,
    DEFAULT_CURRENCY,
    DEFAULT_DAYS,
    DEFAULT_ENERGY_TAX,
    DEFAULT_MARKUP_IMPORT,
    DEFAULT_PRICE_AREA,
    DEFAULT_VAT,
    DOMAIN,
    MAX_DAYS,
    UPDATE_INTERVAL_MINUTES,
)
from .energy_dashboard import (
    EnergyDashboardConfig,
    EnergyDashboardNotConfigured,
    async_read_energy_dashboard,
    resolve_price,
)
from .prices import PricePoint, PriceProvider
from .simulation import (
    BatteryConfig,
    DynamicContract,
    FixedContract,
    GridSeries,
    SimulationInput,
    SimulationResult,
    run_simulation,
)

_LOGGER = logging.getLogger(__name__)

type HasimConfigEntry = ConfigEntry[HasimCoordinator]


@dataclass(slots=True)
class PriceSlot:
    """One published price slot."""

    start: datetime
    end: datetime
    spot: float
    price: float  # all-in import price
    export_price: float

    def as_dict(self) -> dict[str, Any]:
        """Compact representation (kept small: 192 slots must fit in 16 kB)."""
        return {
            "start": self.start.isoformat(timespec="minutes"),
            "price": round(self.price, 4),
            "spot": round(self.spot, 4),
        }


@dataclass(slots=True)
class HasimData:
    """Everything the entities need."""

    result: SimulationResult
    dashboard: EnergyDashboardConfig
    fixed: FixedContract
    dynamic: DynamicContract
    battery: BatteryConfig | None
    period_start: datetime
    period_end: datetime
    hours_without_price: int
    hours_without_data: int
    today: list[PriceSlot] = field(default_factory=list)
    tomorrow: list[PriceSlot] = field(default_factory=list)

    def current_slot(self, now: datetime) -> PriceSlot | None:
        for slot in (*self.today, *self.tomorrow):
            if slot.start <= now < slot.end:
                return slot
        return None

    def next_slot(self, now: datetime) -> PriceSlot | None:
        for slot in (*self.today, *self.tomorrow):
            if slot.start > now:
                return slot
        return None


def _f(opts: dict[str, Any], key: str, default: float) -> float:
    value = opts.get(key)
    return float(value) if value is not None else default


def _opt_f(opts: dict[str, Any], key: str) -> float | None:
    value = opts.get(key)
    return float(value) if value not in (None, "") else None


def build_contracts(
    opts: dict[str, Any],
) -> tuple[FixedContract, DynamicContract, BatteryConfig | None]:
    """Build contract/battery objects from config entry options."""
    vat = _f(opts, CONF_VAT, DEFAULT_VAT) / 100
    fixed = FixedContract(
        import_price=_opt_f(opts, CONF_FIXED_IMPORT_PRICE),
        export_price=_opt_f(opts, CONF_FIXED_EXPORT_PRICE),
        net_metering=bool(opts.get(CONF_FIXED_NET_METERING, True)),
        standing_charge_month=_f(opts, CONF_FIXED_STANDING_CHARGE, 0.0),
        feed_in_fee_month=_f(opts, CONF_FIXED_FEED_IN_FEE, 0.0),
    )
    dynamic = DynamicContract(
        markup_import=_f(opts, CONF_DYN_MARKUP_IMPORT, DEFAULT_MARKUP_IMPORT),
        markup_export=_f(opts, CONF_DYN_MARKUP_EXPORT, 0.0),
        energy_tax=_f(opts, CONF_DYN_ENERGY_TAX, DEFAULT_ENERGY_TAX),
        vat=vat,
        net_metering=bool(opts.get(CONF_DYN_NET_METERING, True)),
        standing_charge_month=_f(opts, CONF_DYN_STANDING_CHARGE, 0.0),
        feed_in_fee_month=_f(opts, CONF_DYN_FEED_IN_FEE, 0.0),
    )
    battery: BatteryConfig | None = None
    if opts.get(CONF_BAT_ENABLED) and _f(opts, CONF_BAT_CAPACITY, 0.0) > 0:
        battery = BatteryConfig(
            capacity_kwh=_f(opts, CONF_BAT_CAPACITY, 0.0),
            max_charge_kw=_f(opts, CONF_BAT_CHARGE_POWER, 0.0),
            max_discharge_kw=_f(opts, CONF_BAT_DISCHARGE_POWER, 0.0),
            roundtrip_efficiency=_f(opts, CONF_BAT_EFFICIENCY, DEFAULT_BAT_EFFICIENCY) / 100,
            min_soc=_f(opts, CONF_BAT_MIN_SOC, DEFAULT_BAT_MIN_SOC) / 100,
            investment=_f(opts, CONF_BAT_INVESTMENT, 0.0),
            lifetime_years=_f(opts, CONF_BAT_LIFETIME, DEFAULT_BAT_LIFETIME),
            grid_charging=bool(opts.get(CONF_BAT_GRID_CHARGING, True)),
        )
    return fixed, dynamic, battery


def _row_start(row: dict[str, Any]) -> float:
    start = row["start"]
    if isinstance(start, datetime):
        return start.timestamp()
    return float(start)


def _hourly_changes(
    rows: dict[str, list[dict[str, Any]]], stat_ids: list[str], hour_index: dict[float, int], n: int
) -> tuple[list[float], bool]:
    """Sum hourly 'change' values of several statistics into one array."""
    values = [0.0] * n
    found = False
    for stat_id in stat_ids:
        for row in rows.get(stat_id, []):
            idx = hour_index.get(_row_start(row))
            if idx is None:
                continue
            change = row.get("change")
            if change is None:
                continue
            found = True
            values[idx] += max(0.0, float(change))
    return values, found


class HasimCoordinator(DataUpdateCoordinator[HasimData]):
    """Fetch prices and statistics, run the simulation."""

    config_entry: HasimConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HasimConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
            config_entry=entry,
        )
        opts = entry.options
        self.area: str = opts.get(CONF_PRICE_AREA, DEFAULT_PRICE_AREA)
        self.currency: str = opts.get(CONF_CURRENCY, DEFAULT_CURRENCY)
        self.provider = PriceProvider(hass, async_get_clientsession(hass), self.area, self.currency)
        self.days_override: int | None = None

    @property
    def days(self) -> int:
        days = self.days_override or int(self.config_entry.options.get(CONF_DAYS, DEFAULT_DAYS))
        return max(1, min(MAX_DAYS, days))

    async def _async_update_data(self) -> HasimData:
        opts = dict(self.config_entry.options)
        fixed, dynamic, battery = build_contracts(opts)

        try:
            dashboard = await async_read_energy_dashboard(self.hass)
        except EnergyDashboardNotConfigured as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.now()
        today = now.date()
        end_local = dt_util.start_of_local_day(now)
        start_local = end_local - timedelta(days=self.days)
        start_utc = dt_util.as_utc(start_local)
        end_utc = dt_util.as_utc(end_local)

        # --- prices -------------------------------------------------------
        self.provider.forget_future(today)
        points = await self.provider.async_get_range(
            start_local.date(), today + timedelta(days=1), today=today
        )
        if not points:
            raise UpdateFailed(f"No day-ahead prices available for area {self.area}")

        # --- statistics ---------------------------------------------------
        stat_ids = dashboard.all_stat_ids
        try:
            rows = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                start_utc,
                end_utc,
                stat_ids,
                "hour",
                None,
                {"change"},
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Error reading statistics: {err}") from err

        n = int((end_utc - start_utc).total_seconds() // 3600)
        hours = [start_utc + timedelta(hours=i) for i in range(n)]
        hour_index = {h.timestamp(): i for i, h in enumerate(hours)}

        grids: list[GridSeries] = []
        any_data = False
        for grid in dashboard.grids:
            from_ids = [grid.stat_from] if grid.stat_from else []
            to_ids = [grid.stat_to] if grid.stat_to else []
            imp, f1 = _hourly_changes(rows, from_ids, hour_index, n)
            exp, f2 = _hourly_changes(rows, to_ids, hour_index, n)
            any_data = any_data or f1 or f2
            grids.append(
                GridSeries(
                    key=grid.key,
                    name=grid.name,
                    import_kwh=imp,
                    export_kwh=exp,
                    import_price=resolve_price(
                        self.hass, grid.import_price, grid.import_price_entity
                    ),
                    export_price=resolve_price(
                        self.hass, grid.export_price, grid.export_price_entity
                    ),
                )
            )
        solar, _ = _hourly_changes(rows, dashboard.solar_stats, hour_index, n)

        # Hourly spot price = mean of the slots inside that hour.
        sums = [0.0] * n
        counts = [0] * n
        for start, price in points:
            hour_ts = start.replace(minute=0, second=0, microsecond=0).timestamp()
            idx = hour_index.get(hour_ts)
            if idx is None:
                continue
            sums[idx] += price
            counts[idx] += 1

        keep = [i for i in range(n) if counts[i] > 0]
        hours_without_price = n - len(keep)
        hours_without_data = sum(
            1
            for i in keep
            if all(g.import_kwh[i] == 0 and g.export_kwh[i] == 0 for g in grids) and solar[i] == 0
        )
        inp = SimulationInput(
            hours=[hours[i] for i in keep],
            grids=[
                GridSeries(
                    g.key,
                    g.name,
                    [g.import_kwh[i] for i in keep],
                    [g.export_kwh[i] for i in keep],
                    g.import_price,
                    g.export_price,
                )
                for g in grids
            ],
            solar_kwh=[solar[i] for i in keep],
            spot_price=[sums[i] / counts[i] for i in keep],
        )
        if not any_data:
            _LOGGER.warning(
                "No energy statistics found for %s in the last %d day(s)",
                ", ".join(sorted(stat_ids)),
                self.days,
            )

        result: SimulationResult = await self.hass.async_add_executor_job(
            run_simulation, inp, fixed, dynamic, battery
        )

        # --- today / tomorrow slots for the price entities -----------------
        today_slots, tomorrow_slots = self._build_slots(points, dynamic, now)

        return HasimData(
            result=result,
            dashboard=dashboard,
            fixed=fixed,
            dynamic=dynamic,
            battery=battery,
            period_start=start_local,
            period_end=end_local,
            hours_without_price=hours_without_price,
            hours_without_data=hours_without_data,
            today=today_slots,
            tomorrow=tomorrow_slots,
        )

    @staticmethod
    def _build_slots(
        points: list[PricePoint], dynamic: DynamicContract, now: datetime
    ) -> tuple[list[PriceSlot], list[PriceSlot]]:
        today_start = dt_util.start_of_local_day(now)
        tomorrow_start = today_start + timedelta(days=1)
        day_after = tomorrow_start + timedelta(days=1)
        relevant = [p for p in points if p[0] >= today_start]
        today: list[PriceSlot] = []
        tomorrow: list[PriceSlot] = []
        for i, (start, spot) in enumerate(relevant):
            if i + 1 < len(relevant):
                end = relevant[i + 1][0]
            else:
                end = start + (
                    (relevant[i][0] - relevant[i - 1][0]) if i > 0 else timedelta(hours=1)
                )
            slot = PriceSlot(
                start=dt_util.as_local(start),
                end=dt_util.as_local(end),
                spot=spot,
                price=dynamic.import_price(spot),
                export_price=dynamic.export_price(spot),
            )
            if start < tomorrow_start:
                today.append(slot)
            elif start < day_after:
                tomorrow.append(slot)
        return today, tomorrow
