"""Read the standard Home Assistant energy dashboard configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class GridConnection:
    """One import/export pair from the energy dashboard."""

    key: str
    name: str
    stat_from: str | None
    stat_to: str | None
    import_price: float | None
    import_price_entity: str | None
    export_price: float | None
    export_price_entity: str | None


@dataclass(slots=True)
class EnergyDashboardConfig:
    """Relevant parts of the energy dashboard."""

    grids: list[GridConnection] = field(default_factory=list)
    solar_stats: list[str] = field(default_factory=list)
    battery_from_stats: list[str] = field(default_factory=list)  # discharge
    battery_to_stats: list[str] = field(default_factory=list)  # charge

    @property
    def all_stat_ids(self) -> set[str]:
        ids: set[str] = set()
        for grid in self.grids:
            if grid.stat_from:
                ids.add(grid.stat_from)
            if grid.stat_to:
                ids.add(grid.stat_to)
        ids.update(self.solar_stats)
        ids.update(self.battery_from_stats)
        ids.update(self.battery_to_stats)
        return ids


class EnergyDashboardNotConfigured(HomeAssistantError):
    """Energy dashboard has no usable grid source."""


def _friendly(hass: HomeAssistant, stat_id: str | None, fallback: str) -> str:
    if stat_id and (state := hass.states.get(stat_id)) is not None:
        return state.name
    return fallback


def _parse_grid_source(
    hass: HomeAssistant, source: dict[str, Any], index: int
) -> list[GridConnection]:
    # New unified format (HA >= 2025.x)
    if "flow_from" not in source and "flow_to" not in source:
        stat_from = source.get("stat_energy_from")
        stat_to = source.get("stat_energy_to")
        if not stat_from and not stat_to:
            return []
        return [
            GridConnection(
                key=f"grid_{index}",
                name=source.get("name")
                or _friendly(hass, stat_from or stat_to, f"Grid {index + 1}"),
                stat_from=stat_from,
                stat_to=stat_to,
                import_price=source.get("number_energy_price"),
                import_price_entity=source.get("entity_energy_price"),
                export_price=source.get("number_energy_price_export"),
                export_price_entity=source.get("entity_energy_price_export"),
            )
        ]

    # Legacy format: lists of flow_from / flow_to, pair them by position.
    flows_from = list(source.get("flow_from") or [])
    flows_to = list(source.get("flow_to") or [])
    connections: list[GridConnection] = []
    for i in range(max(len(flows_from), len(flows_to))):
        f_from = flows_from[i] if i < len(flows_from) else {}
        f_to = flows_to[i] if i < len(flows_to) else {}
        stat_from = f_from.get("stat_energy_from")
        stat_to = f_to.get("stat_energy_to")
        if not stat_from and not stat_to:
            continue
        connections.append(
            GridConnection(
                key=f"grid_{index}_{i}",
                name=_friendly(hass, stat_from or stat_to, f"Grid {index + 1}.{i + 1}"),
                stat_from=stat_from,
                stat_to=stat_to,
                import_price=f_from.get("number_energy_price"),
                import_price_entity=f_from.get("entity_energy_price"),
                export_price=f_to.get("number_energy_price"),
                export_price_entity=f_to.get("entity_energy_price"),
            )
        )
    return connections


async def async_read_energy_dashboard(hass: HomeAssistant) -> EnergyDashboardConfig:
    """Read the energy dashboard preferences."""
    # Imported lazily so the integration also loads when 'energy' is missing.
    from homeassistant.components.energy.data import async_get_manager  # noqa: PLC0415

    manager = await async_get_manager(hass)
    prefs = manager.data
    if not prefs:
        raise EnergyDashboardNotConfigured("The energy dashboard is not configured")

    config = EnergyDashboardConfig()
    for index, source in enumerate(prefs.get("energy_sources") or []):
        s_type = source.get("type")
        if s_type == "grid":
            config.grids.extend(_parse_grid_source(hass, source, index))
        elif s_type == "solar":
            if stat := source.get("stat_energy_from"):
                config.solar_stats.append(stat)
        elif s_type == "battery":
            if stat := source.get("stat_energy_from"):
                config.battery_from_stats.append(stat)
            if stat := source.get("stat_energy_to"):
                config.battery_to_stats.append(stat)

    if not config.grids:
        raise EnergyDashboardNotConfigured("The energy dashboard has no grid consumption source")
    return config


def resolve_price(hass: HomeAssistant, fixed: float | None, entity: str | None) -> float | None:
    """Fixed price from the dashboard: number, or the current state of an entity."""
    if fixed is not None:
        return float(fixed)
    if entity and (state := hass.states.get(entity)) is not None:
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None
    return None
