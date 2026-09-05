"""Tests for the price provider cache."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.hasim.prices import PriceProvider, PriceUnavailableError


def _points(day: date) -> list[tuple[datetime, float]]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return [(start + timedelta(hours=i), 0.1) for i in range(24)]


async def test_unavailable_days_are_not_retried(hass: HomeAssistant) -> None:
    today = date(2026, 9, 5)
    old = today - timedelta(days=90)

    async def fetch(day: date):
        if day < today - timedelta(days=60):
            raise PriceUnavailableError("too old")
        if day > today:
            return None  # tomorrow not published yet
        return _points(day)

    mock = AsyncMock(side_effect=fetch)
    with patch("custom_components.hasim.prices.NordPoolClient.fetch_day", mock):
        provider = PriceProvider(hass, None, "NL", "EUR")
        points = await provider.async_get_range(old, today + timedelta(days=1), today=today)
        assert len(points) == 61 * 24  # 60 past days + today
        first_calls = mock.call_count
        assert first_calls == 92

        mock.reset_mock()
        points = await provider.async_get_range(old, today + timedelta(days=1), today=today)
        assert len(points) == 61 * 24
        # Today stays in memory (the coordinator drops it via forget_future);
        # only the unpublished tomorrow is fetched again.
        fetched_days = sorted(c.args[0] for c in mock.call_args_list)
        assert fetched_days == [today + timedelta(days=1)]

        provider.forget_future(today)
        mock.reset_mock()
        await provider.async_get_range(old, today + timedelta(days=1), today=today)
        fetched_days = sorted(c.args[0] for c in mock.call_args_list)
        assert fetched_days == [today, today + timedelta(days=1)]

        # Old days stay marked unavailable after a fresh provider loads the store.
        provider2 = PriceProvider(hass, None, "NL", "EUR")
        mock.reset_mock()
        await provider2.async_get_range(old, today, today=today)
        fetched_days = sorted(c.args[0] for c in mock.call_args_list)
        assert fetched_days == [today]
