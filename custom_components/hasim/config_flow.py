"""Config and options flow for HASIM."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowFormStep,
)
import voluptuous as vol

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
    CURRENCIES,
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
    NAME,
    PRICE_AREAS,
)
from .energy_dashboard import (
    EnergyDashboardNotConfigured,
    async_read_energy_dashboard,
    resolve_price,
)


def _money(
    step: float | str = "any", unit: str = "€/kWh", minimum: float = -1.0
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=100,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _number(
    minimum: float, maximum: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


STEP_GENERAL = vol.Schema(
    {
        vol.Required(CONF_PRICE_AREA, default=DEFAULT_PRICE_AREA): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=PRICE_AREAS, mode=selector.SelectSelectorMode.DROPDOWN
            )
        ),
        vol.Required(CONF_CURRENCY, default=DEFAULT_CURRENCY): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=CURRENCIES, mode=selector.SelectSelectorMode.DROPDOWN
            )
        ),
        vol.Required(CONF_DAYS, default=DEFAULT_DAYS): _number(1, MAX_DAYS, 1, "days"),
        vol.Required(CONF_VAT, default=DEFAULT_VAT): _number(0, 100, 0.1, "%"),
    }
)


async def _fixed_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Fixed contract step, pre-filled from the energy dashboard prices."""
    hass = handler.parent_handler.hass
    suggested_import: float | None = None
    suggested_export: float | None = None
    try:
        dashboard = await async_read_energy_dashboard(hass)
    except EnergyDashboardNotConfigured:
        dashboard = None
    if dashboard:
        imports = [
            p
            for g in dashboard.grids
            if (p := resolve_price(hass, g.import_price, g.import_price_entity)) is not None
        ]
        exports = [
            p
            for g in dashboard.grids
            if (p := resolve_price(hass, g.export_price, g.export_price_entity)) is not None
        ]
        if imports and len(set(imports)) == 1:
            suggested_import = round(imports[0], 5)
        if exports:
            suggested_export = round(exports[0], 5)

    def _opt(key: str, suggested: float | None) -> vol.Optional:
        if suggested is None:
            return vol.Optional(key)
        return vol.Optional(key, description={"suggested_value": suggested})

    return vol.Schema(
        {
            _opt(CONF_FIXED_IMPORT_PRICE, suggested_import): _money(),
            _opt(CONF_FIXED_EXPORT_PRICE, suggested_export): _money(),
            vol.Required(CONF_FIXED_NET_METERING, default=True): selector.BooleanSelector(),
            vol.Required(CONF_FIXED_STANDING_CHARGE, default=0.0): _money(0.01, "€/month", 0),
            vol.Required(CONF_FIXED_FEED_IN_FEE, default=0.0): _money(0.01, "€/month", 0),
        }
    )


STEP_DYNAMIC = vol.Schema(
    {
        vol.Required(CONF_DYN_MARKUP_IMPORT, default=DEFAULT_MARKUP_IMPORT): _money(),
        vol.Required(CONF_DYN_MARKUP_EXPORT, default=0.0): _money(),
        vol.Required(CONF_DYN_ENERGY_TAX, default=DEFAULT_ENERGY_TAX): _money(),
        vol.Required(CONF_DYN_NET_METERING, default=True): selector.BooleanSelector(),
        vol.Required(CONF_DYN_STANDING_CHARGE, default=0.0): _money(0.01, "€/month", 0),
        vol.Required(CONF_DYN_FEED_IN_FEE, default=0.0): _money(0.01, "€/month", 0),
    }
)

STEP_BATTERY = vol.Schema(
    {
        vol.Required(CONF_BAT_ENABLED, default=False): selector.BooleanSelector(),
        vol.Required(CONF_BAT_CAPACITY, default=10.0): _number(0, 1000, 0.1, "kWh"),
        vol.Required(CONF_BAT_CHARGE_POWER, default=5.0): _number(0, 1000, 0.1, "kW"),
        vol.Required(CONF_BAT_DISCHARGE_POWER, default=5.0): _number(0, 1000, 0.1, "kW"),
        vol.Required(CONF_BAT_EFFICIENCY, default=DEFAULT_BAT_EFFICIENCY): _number(
            50, 100, 0.5, "%"
        ),
        vol.Required(CONF_BAT_MIN_SOC, default=DEFAULT_BAT_MIN_SOC): _number(0, 90, 1, "%"),
        vol.Required(CONF_BAT_INVESTMENT, default=0.0): _number(0, 1_000_000, 1, "€"),
        vol.Required(CONF_BAT_LIFETIME, default=DEFAULT_BAT_LIFETIME): _number(1, 30, 1, "years"),
        vol.Required(CONF_BAT_GRID_CHARGING, default=True): selector.BooleanSelector(),
    }
)

CONFIG_FLOW: dict[str, SchemaFlowFormStep] = {
    "user": SchemaFlowFormStep(STEP_GENERAL, next_step="fixed"),
    "fixed": SchemaFlowFormStep(_fixed_schema, next_step="dynamic"),
    "dynamic": SchemaFlowFormStep(STEP_DYNAMIC, next_step="battery"),
    "battery": SchemaFlowFormStep(STEP_BATTERY),
}

OPTIONS_FLOW: dict[str, SchemaFlowFormStep] = {
    "init": SchemaFlowFormStep(STEP_GENERAL, next_step="fixed"),
    "fixed": SchemaFlowFormStep(_fixed_schema, next_step="dynamic"),
    "dynamic": SchemaFlowFormStep(STEP_DYNAMIC, next_step="battery"),
    "battery": SchemaFlowFormStep(STEP_BATTERY),
}


class HasimConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle the config and options flow."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        return NAME
