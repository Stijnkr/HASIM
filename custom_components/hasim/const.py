"""Constants for HASIM."""

from __future__ import annotations

DOMAIN = "hasim"
NAME = "HASIM"

STORAGE_KEY_PRICES = f"{DOMAIN}_prices"
STORAGE_VERSION = 1

# General
CONF_PRICE_AREA = "price_area"
CONF_CURRENCY = "currency"
CONF_DAYS = "days"
CONF_VAT = "vat"

# Fixed contract
CONF_FIXED_IMPORT_PRICE = "fixed_import_price"
CONF_FIXED_EXPORT_PRICE = "fixed_export_price"
CONF_FIXED_NET_METERING = "fixed_net_metering"
CONF_FIXED_STANDING_CHARGE = "fixed_standing_charge"
CONF_FIXED_FEED_IN_FEE = "fixed_feed_in_fee"

# Dynamic contract
CONF_DYN_MARKUP_IMPORT = "dynamic_markup_import"
CONF_DYN_MARKUP_EXPORT = "dynamic_markup_export"
CONF_DYN_ENERGY_TAX = "dynamic_energy_tax"
CONF_DYN_NET_METERING = "dynamic_net_metering"
CONF_DYN_STANDING_CHARGE = "dynamic_standing_charge"
CONF_DYN_FEED_IN_FEE = "dynamic_feed_in_fee"

# Battery
CONF_BAT_ENABLED = "battery_enabled"
CONF_BAT_CAPACITY = "battery_capacity"
CONF_BAT_CHARGE_POWER = "battery_charge_power"
CONF_BAT_DISCHARGE_POWER = "battery_discharge_power"
CONF_BAT_EFFICIENCY = "battery_efficiency"
CONF_BAT_MIN_SOC = "battery_min_soc"
CONF_BAT_INVESTMENT = "battery_investment"
CONF_BAT_LIFETIME = "battery_lifetime"
CONF_BAT_GRID_CHARGING = "battery_grid_charging"

DEFAULT_PRICE_AREA = "NL"
DEFAULT_CURRENCY = "EUR"
DEFAULT_DAYS = 30
MAX_DAYS = 365
DEFAULT_VAT = 21.0
DEFAULT_ENERGY_TAX = 0.10154  # NL 2026, excl. VAT
DEFAULT_MARKUP_IMPORT = 0.02
DEFAULT_BAT_EFFICIENCY = 90.0
DEFAULT_BAT_MIN_SOC = 10.0
DEFAULT_BAT_LIFETIME = 10

# Nord Pool day-ahead delivery areas.
PRICE_AREAS = [
    "NL",
    "BE",
    "DE-LU",
    "AT",
    "FR",
    "PL",
    "DK1",
    "DK2",
    "NO1",
    "NO2",
    "NO3",
    "NO4",
    "NO5",
    "SE1",
    "SE2",
    "SE3",
    "SE4",
    "FI",
    "EE",
    "LT",
    "LV",
]
CURRENCIES = ["EUR", "DKK", "NOK", "SEK", "PLN"]

SERVICE_SIMULATE = "simulate"
ATTR_DAYS = "days"

UPDATE_INTERVAL_MINUTES = 60
