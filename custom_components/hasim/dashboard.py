"""Generated HASIM dashboard (Lovelace panel) and frontend cards."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace import LOVELACE_DATA
from homeassistant.components.lovelace.const import (
    CONF_ICON,
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    MODE_STORAGE,
    MODE_YAML,
)
from homeassistant.components.lovelace.dashboard import LovelaceConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.json import json_bytes, json_fragment

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
    DASHBOARD_ICON,
    DASHBOARD_URL_PATH,
    DOMAIN,
    FRONTEND_SCRIPT,
    FRONTEND_URL_BASE,
    NAME,
    SERVICE_SIMULATE,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "overview": "Overview",
        "settings": "Settings",
        "advice": "Advice",
        "advice_md": (
            "**Best scenario:** {{ state_translated('%BEST%') }}\n\n"
            "Simulated period: {{ state_attr('%BEST%', 'days') }} days "
            "({{ state_attr('%BEST%', 'hours') }} hours"
            "{% if state_attr('%BEST%', 'hours_without_price') %}, "
            "{{ state_attr('%BEST%', 'hours_without_price') }} hours without price{% endif %}).\n\n"
            "Dynamic vs. fixed: **{{ states('%SAV_DYN%') }} €/year** "
            "(positive = dynamic is cheaper)."
            "{% if states('%SAV_BAT%') not in ['unknown', 'unavailable'] %}\n\n"
            "Battery: **{{ states('%SAV_BAT%') }} €/year** saving, payback "
            "**{{ states('%PAYBACK%') }}** years.{% endif %}"
        ),
        "prices": "Day-ahead prices",
        "costs": "Costs over the simulated period",
        "cost_history": "Cost trend",
        "energy": "Energy in the period",
        "general": "General",
        "fixed": "Fixed contract",
        "dynamic": "Dynamic contract",
        "battery": "Home battery",
        "run": "Run simulation now",
    },
    "nl": {
        "overview": "Overzicht",
        "settings": "Instellingen",
        "advice": "Advies",
        "advice_md": (
            "**Beste scenario:** {{ state_translated('%BEST%') }}\n\n"
            "Gesimuleerde periode: {{ state_attr('%BEST%', 'days') }} dagen "
            "({{ state_attr('%BEST%', 'hours') }} uur"
            "{% if state_attr('%BEST%', 'hours_without_price') %}, "
            "{{ state_attr('%BEST%', 'hours_without_price') }} uur zonder prijs{% endif %}).\n\n"
            "Dynamisch t.o.v. vast: **{{ states('%SAV_DYN%') }} €/jaar** "
            "(positief = dynamisch is goedkoper)."
            "{% if states('%SAV_BAT%') not in ['unknown', 'unavailable'] %}\n\n"
            "Batterij: **{{ states('%SAV_BAT%') }} €/jaar** besparing, terugverdientijd "
            "**{{ states('%PAYBACK%') }}** jaar.{% endif %}"
        ),
        "prices": "Day-ahead prijzen",
        "costs": "Kosten over de gesimuleerde periode",
        "cost_history": "Kostenverloop",
        "energy": "Energie in de periode",
        "general": "Algemeen",
        "fixed": "Vast contract",
        "dynamic": "Dynamisch contract",
        "battery": "Thuisbatterij",
        "run": "Simulatie nu uitvoeren",
    },
}


def _entity_map(hass: HomeAssistant, entry_id: str) -> dict[str, str]:
    """Map unique-id suffix -> entity_id for all entities of the entry."""
    registry = er.async_get(hass)
    prefix = f"{entry_id}_"
    result: dict[str, str] = {}
    for entity in er.async_entries_for_config_entry(registry, entry_id):
        if entity.unique_id.startswith(prefix):
            result[entity.unique_id[len(prefix) :]] = entity.entity_id
    return result


def _tile(entity: str | None, **extra: Any) -> dict[str, Any] | None:
    if not entity:
        return None
    return {"type": "tile", "entity": entity, **extra}


def _entities_card(title: str, ids: list[str | None]) -> dict[str, Any] | None:
    entities = [i for i in ids if i]
    if not entities:
        return None
    return {"type": "entities", "title": title, "entities": entities}


def _section(heading: str, cards: list[dict[str, Any] | None]) -> dict[str, Any]:
    real = [c for c in cards if c]
    return {
        "type": "grid",
        "cards": [{"type": "heading", "heading": heading}, *real],
    }


def build_dashboard_config(
    entities: dict[str, str], language: str, currency: str = "EUR"
) -> dict[str, Any]:
    """Build the Lovelace config from the entry's entity ids."""
    t = TEXTS["nl"] if language.startswith("nl") else TEXTS["en"]
    e = entities.get
    symbol = "€" if currency == "EUR" else currency

    advice_md = (
        t["advice_md"]
        .replace("%BEST%", e("best_scenario", ""))
        .replace("%SAV_DYN%", e("savings_dynamic", ""))
        .replace("%SAV_BAT%", e("savings_battery", ""))
        .replace("%PAYBACK%", e("battery_payback", ""))
    )

    overview_sections = [
        _section(
            t["advice"],
            [
                {"type": "markdown", "content": advice_md},
                {
                    "type": "custom:hasim-scenario-card",
                    "entity": e("best_scenario"),
                    "currency": symbol,
                },
            ],
        ),
        _section(
            t["prices"],
            [
                {
                    "type": "custom:hasim-price-card",
                    "today": e("price_today_average"),
                    "tomorrow": e("price_tomorrow_average"),
                    "current": e("current_price"),
                },
                _tile(e("current_price")),
                _tile(e("price_today_average")),
                _tile(e("price_today_min")),
                _tile(e("price_today_max")),
                _tile(e("price_tomorrow_average")),
            ],
        ),
        _section(
            t["costs"],
            [
                _entities_card(
                    t["costs"],
                    [
                        e("cost_fixed"),
                        e("cost_dynamic"),
                        e("cost_fixed_battery"),
                        e("cost_dynamic_battery"),
                        e("savings_dynamic"),
                        e("savings_battery"),
                        e("battery_payback"),
                    ],
                ),
                {
                    "type": "history-graph",
                    "title": t["cost_history"],
                    "hours_to_show": 24 * 30,
                    "entities": [
                        {"entity": i}
                        for i in (
                            e("cost_fixed"),
                            e("cost_dynamic"),
                            e("cost_fixed_battery"),
                            e("cost_dynamic_battery"),
                        )
                        if i
                    ],
                },
            ],
        ),
        _section(
            t["energy"],
            [
                _tile(e("period_import")),
                _tile(e("period_export")),
                _tile(e("period_solar")),
                _tile(e("period_consumption")),
            ],
        ),
    ]

    run_button = {
        "type": "button",
        "name": t["run"],
        "icon": "mdi:play-circle",
        "show_state": False,
        "tap_action": {
            "action": "perform-action",
            "perform_action": f"{DOMAIN}.{SERVICE_SIMULATE}",
        },
    }
    settings_sections = [
        _section(
            t["general"],
            [_entities_card(t["general"], [e(CONF_DAYS), e(CONF_VAT)]), run_button],
        ),
        _section(
            t["fixed"],
            [
                _entities_card(
                    t["fixed"],
                    [
                        e(CONF_FIXED_IMPORT_PRICE),
                        e(CONF_FIXED_EXPORT_PRICE),
                        e(CONF_FIXED_NET_METERING),
                        e(CONF_FIXED_STANDING_CHARGE),
                        e(CONF_FIXED_FEED_IN_FEE),
                    ],
                )
            ],
        ),
        _section(
            t["dynamic"],
            [
                _entities_card(
                    t["dynamic"],
                    [
                        e(CONF_DYN_MARKUP_IMPORT),
                        e(CONF_DYN_MARKUP_EXPORT),
                        e(CONF_DYN_ENERGY_TAX),
                        e(CONF_DYN_NET_METERING),
                        e(CONF_DYN_STANDING_CHARGE),
                        e(CONF_DYN_FEED_IN_FEE),
                    ],
                )
            ],
        ),
        _section(
            t["battery"],
            [
                _entities_card(
                    t["battery"],
                    [
                        e(CONF_BAT_ENABLED),
                        e(CONF_BAT_CAPACITY),
                        e(CONF_BAT_CHARGE_POWER),
                        e(CONF_BAT_DISCHARGE_POWER),
                        e(CONF_BAT_EFFICIENCY),
                        e(CONF_BAT_MIN_SOC),
                        e(CONF_BAT_INVESTMENT),
                        e(CONF_BAT_LIFETIME),
                        e(CONF_BAT_GRID_CHARGING),
                    ],
                )
            ],
        ),
    ]

    return {
        "title": NAME,
        "views": [
            {
                "title": t["overview"],
                "path": "overview",
                "icon": "mdi:view-dashboard",
                "type": "sections",
                "max_columns": 3,
                "sections": overview_sections,
            },
            {
                "title": t["settings"],
                "path": "settings",
                "icon": "mdi:cog",
                "type": "sections",
                "max_columns": 2,
                "sections": settings_sections,
            },
        ],
    }


class HasimDashboard(LovelaceConfig):
    """Read-only, always up-to-date dashboard generated from the entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        super().__init__(
            hass,
            DASHBOARD_URL_PATH,
            {
                CONF_TITLE: NAME,
                CONF_ICON: DASHBOARD_ICON,
                CONF_REQUIRE_ADMIN: False,
                CONF_SHOW_IN_SIDEBAR: True,
            },
        )
        self._entry_id = entry_id

    @property
    def mode(self) -> str:
        return MODE_YAML

    def _build(self) -> dict[str, Any]:
        entities = _entity_map(self.hass, self._entry_id)
        from .coordinator import HasimCoordinator  # noqa: PLC0415

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        currency = "EUR"
        if entry is not None and isinstance(getattr(entry, "runtime_data", None), HasimCoordinator):
            currency = entry.runtime_data.currency
        return build_dashboard_config(entities, self.hass.config.language, currency)

    async def async_get_info(self) -> dict[str, Any]:
        config = self._build()
        return {"mode": self.mode, "views": len(config["views"])}

    async def async_load(self, force: bool) -> dict[str, Any]:
        return self._build()

    async def async_json(self, force: bool) -> json_fragment:
        return json_fragment(json_bytes(self._build()))

    @callback
    def async_notify_updated(self) -> None:
        """Tell open frontends to reload the dashboard."""
        self._config_updated()


@callback
def async_register_dashboard(hass: HomeAssistant, entry_id: str) -> HasimDashboard:
    """Register the generated dashboard as a sidebar panel."""
    dashboard = HasimDashboard(hass, entry_id)
    hass.data[LOVELACE_DATA].dashboards[DASHBOARD_URL_PATH] = dashboard
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=NAME,
        sidebar_icon=DASHBOARD_ICON,
        frontend_url_path=DASHBOARD_URL_PATH,
        config={"mode": MODE_YAML},
        require_admin=False,
        update=True,
    )
    return dashboard


@callback
def async_unregister_dashboard(hass: HomeAssistant) -> None:
    """Remove the generated dashboard."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is not None:
        lovelace.dashboards.pop(DASHBOARD_URL_PATH, None)
    frontend.async_remove_panel(hass, DASHBOARD_URL_PATH, warn_if_unknown=False)


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the custom cards and register them as a Lovelace resource."""
    if hass.data.get(f"{DOMAIN}_frontend_registered"):
        return
    hass.data[f"{DOMAIN}_frontend_registered"] = True
    path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(path), cache_headers=False)]
    )
    url = f"{FRONTEND_URL_BASE}/{FRONTEND_SCRIPT}?v={VERSION}"
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE:
        _LOGGER.warning(
            "Lovelace resources are in YAML mode; add %s as a 'module' resource "
            "to use the HASIM cards",
            url,
        )
        return
    resources = lovelace.resources
    if not resources.loaded:
        await resources.async_load()
    for item in resources.async_items():
        if str(item.get("url", "")).startswith(f"{FRONTEND_URL_BASE}/{FRONTEND_SCRIPT}"):
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})
    _LOGGER.info("Registered HASIM frontend cards as Lovelace resource %s", url)


async def async_create_storage_dashboard(
    hass: HomeAssistant, entry_id: str, url_path: str, title: str
) -> None:
    """Create an editable (storage mode) copy of the generated dashboard."""
    handler_entry = hass.data.get(websocket_api.DOMAIN, {}).get("lovelace/dashboards/create")
    handler = handler_entry[0] if handler_entry else None
    collection = getattr(getattr(handler, "__self__", None), "storage_collection", None)
    if collection is None:
        raise HomeAssistantError(
            "Cannot access the Lovelace dashboards collection in this Home Assistant "
            "version; create a dashboard manually and paste the YAML from the "
            "HASIM README"
        )
    if "-" not in url_path:
        raise HomeAssistantError("The dashboard URL must contain a hyphen (-)")
    lovelace = hass.data[LOVELACE_DATA]
    if url_path not in lovelace.dashboards:
        await collection.async_create_item(
            {
                CONF_URL_PATH: url_path,
                CONF_TITLE: title,
                CONF_ICON: DASHBOARD_ICON,
                CONF_REQUIRE_ADMIN: False,
                CONF_SHOW_IN_SIDEBAR: True,
            }
        )
    target = lovelace.dashboards.get(url_path)
    if target is None or target.mode != MODE_STORAGE:
        raise HomeAssistantError(f"Dashboard {url_path} exists but is not a storage dashboard")
    entities = _entity_map(hass, entry_id)
    config = build_dashboard_config(entities, hass.config.language)
    await target.async_save(config)
