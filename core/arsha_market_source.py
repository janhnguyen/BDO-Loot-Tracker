import json
from typing import Any

import requests

DEFAULT_ARSHA_ENDPOINTS = (
    "https://api.arsha.io/v2/{region}/GetWorldMarketHotList",
    "https://api.arsha.io/v1/{region}/GetWorldMarketHotList",
)

DEFAULT_ARSHA_LIST_ENDPOINTS = (
    "https://api.arsha.io/v2/{region}/GetWorldMarketList",
    "https://api.arsha.io/v1/{region}/GetWorldMarketList",
)

def fetch_arsha_hotlist(region: str = "na", timeout_seconds: float = 10.0) -> dict[str, float]:
    """
    Fetch parsed item values from Arsha's public market API.
    Returns {item_name: value}.
    """
    for endpoint in DEFAULT_ARSHA_ENDPOINTS:
        url = endpoint.format(region=region.lower())
        try:
            response = requests.get(url, timeout=timeout_seconds)
            response.raise_for_status()
        except requests.RequestException:
            continue

        parsed = _parse_payload(response.text)
        if parsed:
            return parsed
    return {}


def fetch_arsha_full_catalog(
    region: str = "na",
    timeout_seconds: float = 10.0,
    max_main_category: int = 30,
    max_sub_category: int = 60,
) -> dict[str, float]:
    items: dict[str, float] = {}
    for endpoint in DEFAULT_ARSHA_LIST_ENDPOINTS:
        loaded_any = False
        for main_category in range(1, max_main_category + 1):
            empty_subcategories = 0
            for sub_category in range(1, max_sub_category + 1):
                batch = _fetch_market_list_page(
                    endpoint=endpoint,
                    region=region,
                    timeout_seconds=timeout_seconds,
                    main_category=main_category,
                    sub_category=sub_category,
                )
                if not batch:
                    empty_subcategories += 1
                    if empty_subcategories >= 6:
                        break
                    continue

                loaded_any = True
                empty_subcategories = 0
                items.update(batch)
        if loaded_any and items:
            return items
    return items

def _fetch_market_list_page(
    endpoint: str,
    region: str,
    timeout_seconds: float,
    main_category: int,
    sub_category: int,
) -> dict[str, float]:
    url = endpoint.format(region=region.lower())
    params = {"mainCategory": str(main_category), "subCategory": str(sub_category)}
    try:
        response = requests.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException:
        return {}
    return _parse_payload(response.text)

def _parse_payload(raw_text: str) -> dict[str, float]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}

    rows = _extract_rows(payload)
    items: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _first_str(row, "name", "itemName", "MainName", "item_name")
        if not name:
            continue
        price = _first_float(row, "price", "basePrice", "currentMinPrice", "value")
        items[name] = price
    return items

def _extract_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "resultData", "resultMsg", "list", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                try:
                    nested = json.loads(value)
                except json.JSONDecodeError:
                    continue
                if isinstance(nested, list):
                    return nested
    return []

def _first_str(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _first_float(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return 0.0
