# HASIM – Energy contract & battery simulator for Home Assistant

HASIM answers one question with your **own** measured data:

> Am I better off with a fixed contract, a dynamic (day-ahead) contract, and does a home battery pay off?

It reads the grid, solar and battery sources you already configured in the **standard
Home Assistant energy dashboard**, fetches day-ahead prices for your price area
(Nord Pool, no API key needed) and replays the last *N* days through four scenarios:

| Scenario | Description |
|---|---|
| `fixed` | Fixed contract, using the prices from your energy dashboard (or an override) |
| `dynamic` | Day-ahead spot price + supplier markup + energy tax + VAT |
| `fixed_battery` | Fixed contract with a hypothetical home battery |
| `dynamic_battery` | Dynamic contract with a hypothetical home battery (self-consumption + price arbitrage) |

The battery dispatch is solved with a dynamic programme (perfect foresight over the
period), so it is the *best case* a smart battery controller could achieve.

## Installation (HACS)

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repository as *Integration*.
2. Install **HASIM Energy Simulator** and restart Home Assistant.
3. Settings → Devices & services → **Add integration** → HASIM.

Requirements: Home Assistant 2025.6 or newer with the energy dashboard configured
(at least one grid consumption source) and the recorder enabled.

## Configuration

The config flow has four steps; all values can be changed later via *Configure*:

1. **General** – price area (e.g. `NL`, `BE`, `DE-LU`), currency, simulation period
   (1–365 days) and VAT.
2. **Fixed contract** – import price (pre-filled from the energy dashboard), feed-in
   compensation, net metering, standing charges.
3. **Dynamic contract** – supplier markup on import/export, energy tax (excl. VAT),
   net metering, standing charges.
4. **Battery** – capacity, charge/discharge power, efficiency, minimum SoC, investment,
   lifetime and whether grid charging (arbitrage) is allowed.

Costs that are identical for both contracts (grid operator, tax rebate) can be left at 0.

## Entities

| Entity | Meaning |
|---|---|
| Current dynamic price | All-in import price for the current 15-minute/hour slot. Attributes hold the raw spot price, the next slot and min/max/average of today and tomorrow. |
| Average / lowest / highest price today, average price tomorrow | Day statistics of the all-in price. The *average* sensors carry the full price list (`prices` attribute: start, all-in price, spot) for charts. |
| Cost fixed / dynamic (/ with battery) | Total cost over the simulated period; attributes hold the yearly extrapolation and a cost breakdown |
| Yearly saving dynamic vs fixed | Positive = dynamic is cheaper |
| Yearly saving battery, Battery payback time | Best battery scenario vs. best scenario without battery |
| Best scenario | Enum with the cheapest scenario; attributes hold the ranking, period and data quality (hours without price/data) |
| Grid import / export, solar production, consumption in period | kWh totals of the simulated period |

## Service

`hasim.simulate` re-runs the simulation, optionally with a different number of `days`.
The simulation also refreshes automatically every hour.

## How the costs are calculated

* Hourly grid import/export and solar production are read from the long-term statistics
  of the sources in the energy dashboard. Consumption = import + solar − export.
* **Fixed**: `price × import − feed-in × export` per grid connection. With net metering:
  `price × max(0, import − export) − feed-in × max(0, export − import)`.
* **Dynamic**: `Σ import × (spot + markup) × (1+VAT) − Σ export × (spot − export markup) × (1+VAT)
  + energy tax × (1+VAT) × taxed kWh`, where taxed kWh is net import with net metering,
  otherwise all import.
* Standing charges are added per month (`days / 30.44`).
* Yearly figures are `period cost × 365 / days`; use a full year of data for the most
  reliable comparison (seasonality!).
* Hours without a known day-ahead price are excluded from **all** scenarios, so the
  comparison stays fair. The "Best scenario" attributes show how many hours were skipped.

### Price history

Nord Pool serves roughly the last two months of day-ahead prices without an account.
HASIM stores every fetched day in `.storage/hasim_prices_*`, so the usable history grows
the longer the integration runs (up to the 365-day maximum). Days that the source cannot
provide are remembered and not requested again.

## Development

```bash
pip install -r requirements_dev.txt
pytest
```

The simulation engine (`simulation.py`) has no Home Assistant dependency and is fully
unit-tested.
