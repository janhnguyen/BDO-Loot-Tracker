import csv
import re
import sys
from pathlib import Path

# When frozen, items lives next to the .exe; in development it's at the repo root.
BASE_DIR = (
    Path(sys.executable).parent if getattr(sys, "frozen", False)
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

            # Build zone upgrade map: [Dehkia] X -> [Dehkia II] X from trash loot rows
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

# Lowercase index for fuzzy name resolution. Rebuilt whenever ITEM_NAMES changes.
_ITEM_NAMES_LC: list[str] = []
_LC_TO_CANON: dict[str, str] = {}

def _rebuild_name_index() -> None:
    global _ITEM_NAMES_LC, _LC_TO_CANON
    _LC_TO_CANON = {name.lower(): name for name in ITEM_NAMES}
    _ITEM_NAMES_LC = list(_LC_TO_CANON.keys())

_rebuild_name_index()

def reload_items() -> None:
    global ITEM_NAMES, ITEM_VALUES, ITEM_ZONES, ITEM_DEHKIA_TWO_TF, DEHKIA_ZONE_UPGRADE, ITEM_VALUES_BY_ZONE
    ITEM_NAMES, ITEM_VALUES, ITEM_ZONES, ITEM_DEHKIA_TWO_TF, DEHKIA_ZONE_UPGRADE, ITEM_VALUES_BY_ZONE = load_items()
    _rebuild_name_index()

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
      Corrupt Crystal alone -> Mansha Forest (already from CSV).
      If Huge Spear is also present -> override Corrupt Crystal to Cyclops Land.

    Armor Fragment (Shultz Guard vs Sausan Garrison):
      Default -> Shultz Guard (CSV default, value 11050).
      If Robe Piece or Sausan Supply Package also present -> Sausan Garrison (value 476).
    """
    overrides: dict[str, str] = {}
    name_set = set(item_names)

    if _HUGE_SPEAR in name_set and _CORRUPT_CRYSTAL in name_set:
        overrides[_CORRUPT_CRYSTAL] = "Cyclops Land"

    if _ARMOR_FRAGMENT in name_set and name_set & _SAUSAN_INDICATORS:
        overrides[_ARMOR_FRAGMENT] = "Sausan Garrison"

    return overrides

# Loot parser

def _norm_digits(s: str) -> str:
    return (s.replace('|', '1').replace('!', '1').replace('l', '1')
             .replace('I', '1').replace(']', '1').replace('[', '1')
             .replace('O', '0').replace('o', '0'))

_LEADING_OCR_FIXES = (
    (re.compile(r'^THAN\b'), 'HAN'),
)

def _fix_leading_ocr(s: str) -> str:
    for pattern, repl in _LEADING_OCR_FIXES:
        s = pattern.sub(repl, s, count=1)
    return s

def _clean_line(s: str) -> str:
    s = s.replace('l.', '].')
    s = s.replace('l x', '] x')
    s = re.sub(r'^[^\[]*\[', '[', s)
    s = re.sub(r'\bevent\b', '', s.replace('[', '').replace(']', ''), flags=re.IGNORECASE).strip()
    s = s.replace('‘', "'").replace('’', "'")
    s = s.replace('`', "'")
    s = s.replace(',', '')
    s = _fix_leading_ocr(s)
    return s

_QTY_RE = re.compile(r'[xX×]\s*([0-9|!lI\[\]Oo]{1,6})')

def extract_quantity(after: str) -> tuple[bool, int | None]:
    """
    Parse a trailing 'xN' quantity from the text following an item name.

    Returns (token_present, qty):
      (False, None)  no x-token at all -> caller should treat as qty 1.
      (True, qty)    a valid positive quantity was parsed.
      (True, None)   an x-token was present but unparseable (reject this match).
    Digit-confusion characters (| ! l I [ ] O o) are normalised to digits.
    """
    m = _QTY_RE.search(after)
    if not m:
        return (False, None)
    try:
        qty = int(_norm_digits(m.group(1)))
    except ValueError:
        return (True, None)
    return (True, qty if qty > 0 else None)


def fuzzy_resolve_name(text: str, threshold: float = 0.82) -> tuple[str, float] | None:
    """
    Resolve an OCR'd name fragment to its canonical item name via fuzzy match.

    Returns (canonical_name, similarity) for the best match at or above
    threshold, else None. Intended as a fallback when exact substring
    matching fails (e.g. "Ancient Solder Fragment" -> "Ancient Soldier Fragment").
    """
    from difflib import SequenceMatcher

    candidate = text.strip().lower()
    if not candidate:
        return None

    best_name: str | None = None
    best_ratio = 0.0
    matcher = SequenceMatcher()
    matcher.set_seq2(candidate)
    for name_lc in _ITEM_NAMES_LC:
        matcher.set_seq1(name_lc)
        # quick_ratio is a cheap upper bound; skip hopeless candidates early.
        if matcher.quick_ratio() < threshold:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = _LC_TO_CANON[name_lc]
    if best_name is not None and best_ratio >= threshold:
        return (best_name, best_ratio)
    return None


def _parse_single_line(line: str) -> tuple[str, int] | None:
    """Return (item_name, qty) if line contains a recognised item, else None."""
    line = _clean_line(line)
    line_lc = line.lower()
    for name in ITEM_NAMES:
        idx = line_lc.find(name.lower())
        if idx == -1:
            continue
        present, qty = extract_quantity(line[idx + len(name):])
        if not present:
            return (name, 1)
        if qty is not None:
            return (name, qty)
        # x-token present but unparseable -> keep scanning other candidates.
    return None

