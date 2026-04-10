import csv
import re
import sys
from pathlib import Path

# When frozen by PyInstaller, bundled resources live in sys._MEIPASS.
BASE_DIR = (
    Path(sys._MEIPASS) if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
_ITEMS_CSV_FILE = BASE_DIR / "items" / "items.csv"
_ITEMS_ARSHA_CANDIDATES = (
    BASE_DIR / "items" / "items.arsha.csv",
    BASE_DIR / "items.arsha.csv",
)

def _load_csv_items(
    csv_path: Path,
    names: list[str],
    values: dict[str, float],
    zones: dict[str, str],
    dehkia_two_tf: dict[str, bool],
    dehkia_zone_upgrade: dict[str, str],
    values_by_zone: dict[tuple[str, str], float],
    allow_overwrite: bool,
):
    if not csv_path.exists():
        return

    with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.reader(csv_file)
        for row in reader:

            if len(row) < 2:
                continue

            name = row[0].strip()
            value_raw = row[1].strip()
            zone_raw = row[2].strip() if len(row) > 2 else ""
            dehkia_two_raw = row[3].strip() if len(row) > 3 else ""
            tf_raw = row[4].strip() if len(row) > 4 else ""

            if not name:
                continue

            if name.lower() == "name" and value_raw.lower() == "value":
                continue

            if name not in names:
                names.append(name)
            elif not allow_overwrite:
                continue

            try:
                parsed_value = float(value_raw.replace(",", "")) if value_raw else 0.0
            except ValueError:
                parsed_value = 0.0

            if allow_overwrite or name not in values:
                values[name] = parsed_value

            if zone_raw and (allow_overwrite or name not in zones):
                zones[name] = zone_raw

            # tf=TRUE marks a Dehkia II exclusive indicator item
            if tf_raw.upper() == "TRUE" and (allow_overwrite or name not in dehkia_two_tf):
                dehkia_two_tf[name] = True

            # Build zone upgrade map: [Dehkia] X → [Dehkia II] X from trash loot rows
            if zone_raw.startswith("[Dehkia]") and "[Dehkia II]" in dehkia_two_raw:
                if allow_overwrite or zone_raw not in dehkia_zone_upgrade:
                    dehkia_zone_upgrade[zone_raw] = dehkia_two_raw
                
            # Zone-specific value lookup for items that appear in multiple zones
            if zone_raw and parsed_value:
                values_by_zone[(name, zone_raw)] = parsed_value

def load_items():
    names: list[str] = []
    values: dict[str, float] = {}
    zones: dict[str, str] = {}
    dehkia_two_tf: dict[str, bool] = {}
    dehkia_zone_upgrade: dict[str, str] = {}
    values_by_zone: dict[tuple[str, str], float] = {}
    _load_csv_items(_ITEMS_CSV_FILE, names, values, zones, dehkia_two_tf, dehkia_zone_upgrade, values_by_zone, allow_overwrite=True)

    for arsha_file in _ITEMS_ARSHA_CANDIDATES:
        _load_csv_items(arsha_file, names, values, zones, dehkia_two_tf, dehkia_zone_upgrade, values_by_zone, allow_overwrite=False)
        if arsha_file.exists():
            break

    names.sort(key=len, reverse=True)
    return names, values, zones, dehkia_two_tf, dehkia_zone_upgrade, values_by_zone

ITEM_NAMES, ITEM_VALUES, ITEM_ZONES, ITEM_DEHKIA_TWO_TF, DEHKIA_ZONE_UPGRADE, ITEM_VALUES_BY_ZONE = load_items()

def get_item_value(item_name: str) -> float:
    return ITEM_VALUES.get(item_name, 0.0)

def get_item_value_for_zone(item_name: str, zone: str) -> float:
    """Return the item value for a specific zone, falling back to the default value."""
    return ITEM_VALUES_BY_ZONE.get((item_name, zone), ITEM_VALUES.get(item_name, 0.0))

def get_item_zone(item_name: str) -> str | None:
    return ITEM_ZONES.get(item_name)

def is_dehkia_two_indicator(item_name: str) -> bool:
    """Return True if the item has tf=TRUE (Dehkia II exclusive drop)."""
    return ITEM_DEHKIA_TWO_TF.get(item_name, False)

def get_dehkia_two_upgrade(current_zone: str) -> str | None:
    """If current_zone is a [Dehkia] zone with a known [Dehkia II] upgrade, return it."""
    return DEHKIA_ZONE_UPGRADE.get(current_zone)

# Batch context zone resolution

_HUGE_SPEAR = "Huge Spear"
_CORRUPT_CRYSTAL = "Corrupt Crystal"
_ARMOR_FRAGMENT = "Armor Fragment"
_SAUSAN_INDICATORS = {"Robe Piece", "Sausan Supply Package"}

def resolve_batch_zone_overrides(item_names: list[str]) -> dict[str, str]:
    """
    Given all item names detected in a single OCR capture window, return a
    mapping of item_name -> zone_override for items whose zone depends on
    what else appeared in the same window.

    Mansha Forest / Cyclops Land:
      Corrupt Crystal alone → Mansha Forest (already from CSV).
      If Huge Spear is also present → override Corrupt Crystal to Cyclops Land.

    Armor Fragment (Shultz Guard vs Sausan Garrison):
      Default → Shultz Guard (CSV default, value 11050).
      If Robe Piece or Sausan Supply Package also present → Sausan Garrison (value 476).
    """
    overrides: dict[str, str] = {}
    name_set = set(item_names)

    if _HUGE_SPEAR in name_set and _CORRUPT_CRYSTAL in name_set:
        overrides[_CORRUPT_CRYSTAL] = "Cyclops Land"

    if _ARMOR_FRAGMENT in name_set and name_set & _SAUSAN_INDICATORS:
        overrides[_ARMOR_FRAGMENT] = "Sausan Garrison"

    return overrides

# Loot parser

def _clean_ocr(raw: str):
    # Hard coded text parsing
    clean = raw.replace("[Mushroom Hyphal.","[Mushroom Hypha].")
    clean = clean.replace("[Mushroom Hyphal]","[Mushroom Hypha]")
    return clean

def _norm_digits(s: str) -> str:
    return (s.replace('|', '1').replace('!', '1').replace('l', '1')
             .replace('I', '1').replace(']', '1').replace('[', '1')
             .replace('O', '0').replace('o', '0'))

def parse_loot(text: str):
    # Expected line format: You have obtained ● [Item Name] xN
    results = []
    for line in text.splitlines():
        line = _clean_ocr(line)
        line = line.strip()
        if not line:
            continue
        if '[' not in line or ']' not in line:
            continue
        line_stripped = re.sub(r'\bevent\b', '', line.replace("[", "").replace("]", ""), flags=re.IGNORECASE).strip()
        line_stripped = line_stripped.replace('\u2019', "'").replace('\u2018', "'").replace('`', "'").replace(",","")
        line_lc = line_stripped.lower()
        for name in ITEM_NAMES:
            idx = line_lc.find(name.lower())
            if idx == -1:
                continue
            # Search for quantity only in the text that follows the item name
            after = line_stripped[idx + len(name):]
            m = re.search(r'[xX×]\s*([0-9|!lI\[\]Oo]{1,6})', after)
            if m:
                try:
                    qty = int(_norm_digits(m.group(1)))
                    if qty > 0:
                        results.append((name, qty))
                        break
                except Exception:
                    pass
            else:
                # No quantity present treat as x1
                results.append((name, 1))
                break
    return results
