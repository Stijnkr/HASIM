"""Tests for the generated dashboard config."""

from __future__ import annotations

from custom_components.hasim.dashboard import build_dashboard_config


def _walk(node, found: set[str]) -> None:
    if isinstance(node, dict):
        if "entity" in node and isinstance(node["entity"], str):
            found.add(node["entity"])
        for item in node.get("entities", []):
            if isinstance(item, str):
                found.add(item)
        for v in node.values():
            _walk(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found)


def test_build_dashboard_uses_entity_ids_and_language() -> None:
    entities = {
        "best_scenario": "sensor.hasim_best",
        "current_price": "sensor.hasim_price",
        "price_today_average": "sensor.hasim_today",
        "price_tomorrow_average": "sensor.hasim_tomorrow",
        "cost_fixed": "sensor.hasim_cost_fixed",
        "savings_dynamic": "sensor.hasim_sav",
        "days": "number.hasim_days",
        "battery_enabled": "switch.hasim_bat",
    }
    nl = build_dashboard_config(entities, "nl")
    en = build_dashboard_config(entities, "en-GB")
    assert nl["views"][0]["title"] == "Overzicht"
    assert en["views"][0]["title"] == "Overview"
    assert [v["path"] for v in nl["views"]] == ["overview", "settings"]

    found: set[str] = set()
    _walk(nl, found)
    assert {
        "sensor.hasim_best",
        "sensor.hasim_price",
        "sensor.hasim_cost_fixed",
        "number.hasim_days",
        "switch.hasim_bat",
    } <= found
    # Entities that do not exist are left out rather than referenced.
    assert "" not in found

    price_card = nl["views"][0]["sections"][1]["cards"][1]
    assert price_card["type"] == "custom:hasim-price-card"
    assert price_card["today"] == "sensor.hasim_today"
    markdown = nl["views"][0]["sections"][0]["cards"][1]["content"]
    assert "state_translated('sensor.hasim_best')" in markdown


def test_build_dashboard_without_entities_has_no_dangling_cards() -> None:
    cfg = build_dashboard_config({}, "en")
    for view in cfg["views"]:
        for section in view["sections"]:
            for card in section["cards"]:
                assert card["type"] in {
                    "heading",
                    "markdown",
                    "custom:hasim-scenario-card",
                    "custom:hasim-price-card",
                    "history-graph",
                    "button",
                }
