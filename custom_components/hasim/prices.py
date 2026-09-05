"""Day-ahead price client (Nord Pool data portal) with persistent cache."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY_PRICES, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

NORDPOOL_URL = "https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices"
REQUEST_TIMEOUT = 30
MAX_PARALLEL = 4

PricePoint = tuple[datetime, float]  # (start UTC, price per kWh)


class PriceFetchError(Exception):
    """Fetching prices failed."""


class PriceUnavailableError(PriceFetchError):
    """Prices for this day are not available from the source (e.g. too old)."""


class NordPoolClient:
    """Minimal Nord Pool day-ahead client (no API key needed)."""

    def __init__(self, session: ClientSession, area: str, currency: str) -> None:
        self._session = session
        self._area = area
        self._currency = currency

    async def fetch_day(self, day: date) -> list[PricePoint] | None:
        """Fetch prices for a delivery day. Returns None when not published yet."""
        params = {
            "date": day.isoformat(),
            "market": "DayAhead",
            "deliveryArea": self._area,
            "currency": self._currency,
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(NORDPOOL_URL, params=params)
                if resp.status == 204:
                    return None
                if resp.status in (401, 403, 404):
                    raise PriceUnavailableError(
                        f"Prices for {day} not available from Nord Pool (HTTP {resp.status})"
                    )
                if resp.status != 200:
                    raise PriceFetchError(f"HTTP {resp.status} for {day}")
                data: dict[str, Any] = await resp.json()
        except (TimeoutError, ClientError) as err:
            raise PriceFetchError(f"Error fetching prices for {day}: {err}") from err

        entries = data.get("multiAreaEntries") or []
        points: list[PricePoint] = []
        for entry in entries:
            price = (entry.get("entryPerArea") or {}).get(self._area)
            start = entry.get("deliveryStart")
            if price is None or not start:
                continue
            dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC)
            points.append((dt, float(price) / 1000.0))  # MWh -> kWh
        if not points:
            return None
        return points

    @staticmethod
    def is_final(data: dict[str, Any], area: str) -> bool:
        """Whether the published data for an area is final."""
        for state in data.get("areaStates") or []:
            if area in (state.get("areas") or []):
                return state.get("state") == "Final"
        return True


class PriceStore:
    """Cache of daily price series in HA storage."""

    def __init__(self, hass: HomeAssistant, area: str, currency: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PRICES}_{area}_{currency}".lower()
        )
        self._data: dict[str, list[list[float]]] | None = None
        self.unavailable: set[str] = set()

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        self._data = dict((raw or {}).get("days", {}))
        self.unavailable = set((raw or {}).get("unavailable", []))

    def get_day(self, day: date) -> list[PricePoint] | None:
        assert self._data is not None
        raw = self._data.get(day.isoformat())
        if not raw:
            return None
        return [(datetime.fromtimestamp(ts, UTC), price) for ts, price in raw]

    def set_day(self, day: date, points: list[PricePoint]) -> None:
        assert self._data is not None
        self._data[day.isoformat()] = [[p[0].timestamp(), p[1]] for p in points]

    def is_unavailable(self, day: date) -> bool:
        return day.isoformat() in self.unavailable

    def mark_unavailable(self, day: date) -> None:
        self.unavailable.add(day.isoformat())

    def prune(self, keep_from: date) -> None:
        assert self._data is not None
        for key in list(self._data):
            if date.fromisoformat(key) < keep_from:
                del self._data[key]
        self.unavailable = {d for d in self.unavailable if date.fromisoformat(d) >= keep_from}

    async def async_save(self) -> None:
        await self._store.async_save(
            {"days": self._data or {}, "unavailable": sorted(self.unavailable)}
        )


class PriceProvider:
    """Combines the client and cache."""

    def __init__(
        self, hass: HomeAssistant, session: ClientSession, area: str, currency: str
    ) -> None:
        self.area = area
        self.currency = currency
        self._client = NordPoolClient(session, area, currency)
        self._store = PriceStore(hass, area, currency)
        self._loaded = False
        self._memory: dict[date, list[PricePoint] | None] = {}

    async def async_get_range(
        self, first_day: date, last_day: date, *, today: date
    ) -> list[PricePoint]:
        """Get all price points for [first_day, last_day] (delivery days, local)."""
        if not self._loaded:
            await self._store.async_load()
            self._loaded = True

        days = [first_day + timedelta(days=i) for i in range((last_day - first_day).days + 1)]
        missing: list[date] = []
        result: dict[date, list[PricePoint]] = {}
        skipped = 0
        for day in days:
            cached = self._store.get_day(day)
            if cached is None:
                cached = self._memory.get(day)
            if cached is not None:
                result[day] = cached
            elif self._store.is_unavailable(day):
                skipped += 1
            else:
                missing.append(day)

        if missing:
            _LOGGER.debug("Fetching %d missing price day(s)", len(missing))
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def _fetch(day: date) -> tuple[date, list[PricePoint] | None, bool]:
                async with sem:
                    try:
                        return day, await self._client.fetch_day(day), False
                    except PriceUnavailableError:
                        return day, None, True
                    except PriceFetchError as err:
                        _LOGGER.warning("%s", err)
                        return day, None, False

            fetched = await asyncio.gather(*(_fetch(d) for d in missing))
            changed = False
            for day, points, unavailable in fetched:
                if unavailable and day < today - timedelta(days=1):
                    # Permanently unavailable (source history limit); never retry.
                    self._store.mark_unavailable(day)
                    skipped += 1
                    changed = True
                if points is None:
                    continue
                result[day] = points
                if day < today:
                    self._store.set_day(day, points)
                    changed = True
                else:
                    self._memory[day] = points
            if changed:
                self._store.prune(today - timedelta(days=400))
                await self._store.async_save()

        if skipped:
            _LOGGER.info(
                "%d day(s) in the requested period have no day-ahead prices "
                "(Nord Pool only provides ~2 months of history anonymously); "
                "HASIM caches new prices daily so the available history grows over time",
                skipped,
            )

        points: list[PricePoint] = []
        for day in days:
            points.extend(result.get(day, []))
        points.sort(key=lambda p: p[0])
        return points

    def forget_future(self, today: date) -> None:
        """Drop in-memory entries for today/tomorrow so they get re-fetched."""
        for day in list(self._memory):
            if day >= today:
                del self._memory[day]
