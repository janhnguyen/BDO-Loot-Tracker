from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import requests

_API_URL = "https://api.github.com/repos/janhnguyen/BDO-Loot-Tracker/releases/latest"
_TIMEOUT = 8


class UpdateResult(TypedDict):
    current: str
    latest: str
    available: bool
    url: str
    installer_url: str


def _parse(version: str) -> tuple[int, ...]:
    """Convert 'v1.2.3' or '1.2.3' to (1, 2, 3) for comparison."""
    return tuple(int(x) for x in version.lstrip("v").split("."))


def read_current_version(resource_root: Path) -> str:
    for candidate in [resource_root / "version.txt", resource_root / "helpers" / "version.txt"]:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    return "0.0.0"


def check(resource_root: Path) -> UpdateResult:
    current = read_current_version(resource_root)
    try:
        resp = requests.get(
            _API_URL,
            headers={"Accept": "application/vnd.github+json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        tag: str = data.get("tag_name", "0.0.0")
        url: str = data.get("html_url", "")
        latest = tag.lstrip("v")
        available = _parse(latest) > _parse(current)

        installer_url = ""
        for asset in data.get("assets", []):
            name: str = asset.get("name", "")
            if name.endswith(".exe"):
                installer_url = asset.get("browser_download_url", "")
                break

        return UpdateResult(
            current=current,
            latest=latest,
            available=available,
            url=url,
            installer_url=installer_url,
        )
    except Exception:
        return UpdateResult(
            current=current, latest="", available=False, url="", installer_url=""
        )
