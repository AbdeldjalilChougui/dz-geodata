"""Lookups over Algeria's administrative units (wilaya > daïra > commune).

Data © OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

__all__ = [
    "wilayas", "wilaya", "dairas", "daira", "communes", "commune", "search", "locate",
    "normalize", "geojson", "data_path", "provenance",
]
__version__ = "0.1.0"

Record = dict[str, Any]
_PLURAL = {"wilaya": "wilayas", "daira": "dairas", "commune": "communes"}


def data_path(name: str) -> Path:
    """Filesystem path of a bundled data file (e.g. ``"algeria.topojson"``)."""
    return Path(str(resources.files("dz_geodata").joinpath("data", name)))


@cache
def _load(name: str) -> Any:
    return json.loads(data_path(name).read_text(encoding="utf-8"))


def provenance() -> Record:
    return dict(_load("provenance.json"))


def geojson(level: str) -> Record:
    """FeatureCollection for ``"wilayas"``, ``"dairas"`` or ``"communes"``."""
    if level not in _PLURAL.values():
        raise ValueError(f"level must be one of {sorted(_PLURAL.values())}")
    return _load(f"{level}.geojson")


_TASHKEEL = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")


def normalize(text: str | None) -> str:
    """Lowercase, strip accents and Arabic diacritics, unify alef/ta marbuta/ya variants."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch) or "؀" <= ch <= "ۿ")
    s = _TASHKEEL.sub("", s)
    s = re.sub("[أإآٱ]", "ا", s).replace("ة", "ه").replace("ى", "ي")
    s = re.sub(r"['’`-]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _wcode(code: str | int) -> str | None:
    s = str(code).strip().upper().removeprefix("DZ-")
    return s.zfill(2) if s.isdigit() and len(s) <= 2 else None


def wilayas() -> list[Record]:
    return list(_load("wilayas.json"))


def wilaya(code: str | int) -> Record | None:
    c = _wcode(code)
    return next((w for w in _load("wilayas.json") if w["code"] == c), None)


def dairas(wilaya_code: str | int | None = None) -> list[Record]:
    rows = _load("dairas.json")
    if wilaya_code is None:
        return list(rows)
    c = _wcode(wilaya_code)
    return [d for d in rows if d["wilaya_code"] == c]


def daira(osm_id: int) -> Record | None:
    return next((d for d in _load("dairas.json") if d["osm_id"] == int(osm_id)), None)


def communes(wilaya_code: str | int | None = None) -> list[Record]:
    rows = _load("communes.json")
    if wilaya_code is None:
        return list(rows)
    c = _wcode(wilaya_code)
    return [x for x in rows if x["wilaya_code"] == c]


def commune(ons_code: str | int) -> Record | None:
    c = str(ons_code).zfill(4)
    return next((x for x in _load("communes.json") if x["ons_code"] == c), None)


def search(query: str, level: str | None = None, limit: int = 10) -> list[Record]:
    """Exact > prefix > substring matches on ar/fr/en names; each hit has a ``level`` key."""
    q = normalize(query)
    if not q:
        return []
    levels = [level] if level else ["wilaya", "daira", "commune"]
    hits = []
    for li, lv in enumerate(levels):
        for item in _load(f"{_PLURAL[lv]}.json"):
            best = 9
            for name in (item["name_fr"], item["name_ar"], item["name_en"]):
                n = normalize(name)
                best = min(best, 0 if n == q else 1 if n.startswith(q) else 2 if q in n else 9)
            if best < 9:
                hits.append((best * 10 + li, item["name_fr"], {"level": lv, **item}))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [h[2] for h in hits[:limit]]


# ------------------------------------------------------------------ locate

def _bbox(coords, b=None):
    b = b or [float("inf"), float("inf"), float("-inf"), float("-inf")]
    if isinstance(coords[0], (int, float)):
        b[0], b[1] = min(b[0], coords[0]), min(b[1], coords[1])
        b[2], b[3] = max(b[2], coords[0]), max(b[3], coords[1])
        return b
    for c in coords:
        _bbox(c, b)
    return b


@cache
def _index():
    return [(f, _bbox(f["geometry"]["coordinates"])) for f in geojson("communes")["features"]]


def _in_ring(ring, x, y) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < xi + (y - yi) * (xj - xi) / (yj - yi):
            inside = not inside
        j = i
    return inside


def _contains(geom, x, y) -> bool:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return any(_in_ring(p[0], x, y) and not any(_in_ring(h, x, y) for h in p[1:]) for p in polys)


def locate(lon: float, lat: float) -> dict[str, Record | None] | None:
    """Commune, daïra and wilaya containing (lon, lat), or ``None`` outside Algeria."""
    for f, b in _index():
        if b[0] <= lon <= b[2] and b[1] <= lat <= b[3] and _contains(f["geometry"], lon, lat):
            c = f["properties"]
            return {"commune": c, "daira": daira(c["daira_osm_id"]) if c["daira_osm_id"] else None,
                    "wilaya": wilaya(c["wilaya_code"])}
    return None
