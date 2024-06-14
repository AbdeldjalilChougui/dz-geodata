"""Build dz-geodata from an OpenStreetMap extract.

    uv run python scripts/build.py              # downloads the Geofabrik extract if raw/ has none
    uv run python scripts/build.py --pbf path/to/algeria.osm.pbf --tolerance 0.0005

Steps
1. Extract administrative multipolygons (admin_level 4 = wilaya, 6 = daïra,
   8 = commune) with GDAL's OSM driver (`ogr2ogr`, GDAL >= 3.x).
2. Keep only units inside Algeria (wilayas tagged ISO3166-2=DZ-*, lower
   levels whose interior point falls in a wilaya), clean the names, drop
   duplicate communes.
3. Link communes -> daïra -> wilaya by point-in-polygon.
4. Simplify all three levels together as one topology (shared borders stay
   shared), then write GeoJSON, TopoJSON and attribute tables to data/.

Data © OpenStreetMap contributors, ODbL 1.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from shapely import STRtree
from shapely.geometry import shape
from shapely.validation import make_valid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology import Topology  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
PBF_URL = "https://download.geofabrik.de/africa/algeria-latest.osm.pbf"
LEVELS = {"4": "wilaya", "6": "daira", "8": "commune"}

# --------------------------------------------------------------------- names

_PREFIXES = {
    "fr": r"^(wilaya|commune|da[iï]ra|province)\s+(de\s+la\s+|de\s+l['’]\s*|de\s+|d['’]\s*|du\s+|des\s+)?",
    "en": r"^(commune|district|province)\s+(of\s+)?",
    "ar": r"^(ولاية|بلدية|دائرة)\s+",
}
_SUFFIXES = {"en": r"\s+(province|district|commune)$", "fr": r"\s+\(commune\)$", "ar": r"$^"}


def clean_name(value: str | None, lang: str) -> str:
    """Strip administrative prefixes/suffixes ("Wilaya d'", "بلدية ", " Province")."""
    if not value:
        return ""
    s = value.strip()
    s = re.sub(_PREFIXES[lang], "", s, flags=re.IGNORECASE)
    s = re.sub(_SUFFIXES[lang], "", s, flags=re.IGNORECASE)
    s = s.strip()
    if lang == "fr" and s:
        s = s[0].upper() + s[1:]
    return s


# ------------------------------------------------------------------ extract


def ensure_pbf(path: Path | None) -> Path:
    if path:
        return path
    target = RAW / "algeria-latest.osm.pbf"
    if not target.exists():
        RAW.mkdir(exist_ok=True)
        print(f"downloading {PBF_URL} (~300 MB)", file=sys.stderr)
        req = urllib.request.Request(PBF_URL, headers={"User-Agent": "dz-geodata build"})
        with urllib.request.urlopen(req) as r, open(target, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    return target


def extract(pbf: Path) -> list[dict]:
    cache = RAW / f"admin-{pbf.stat().st_size}.geojsonl"
    if not cache.exists():
        print("extracting boundaries with ogr2ogr (a few minutes)", file=sys.stderr)
        subprocess.run(
            [
                "ogr2ogr", "--config", "OSM_CONFIG_FILE", str(ROOT / "scripts" / "osmconf.ini"),
                "-f", "GeoJSONSeq", str(cache), str(pbf), "multipolygons",
                "-where", "boundary='administrative' AND admin_level IN ('4','6','8')",
            ],
            check=True,
        )
    return [json.loads(line) for line in cache.read_text().splitlines() if line.strip()]


# -------------------------------------------------------------------- build


def build_units(features: list[dict]) -> dict[str, list[dict]]:
    units: dict[str, list[dict]] = {"wilaya": [], "daira": [], "commune": []}
    for f in features:
        p = f["properties"]
        level = LEVELS.get(p.get("admin_level"))
        if level is None or not f.get("geometry"):
            continue
        geom = make_valid(shape(f["geometry"]))
        if geom.is_empty or geom.area == 0:
            continue
        units[level].append({"props": p, "geom": geom})

    def is_dz_wilaya(p: dict) -> bool:
        iso = p.get("ISO3166-2") or ""
        if iso:
            return iso.startswith("DZ-")
        # Newly created wilayas may lack ISO3166-2 in OSM; accept a numeric ref 1-69.
        ref = (p.get("ref") or "").strip()
        return ref.isdigit() and 1 <= int(ref) <= 69

    wilayas = [u for u in units["wilaya"] if is_dz_wilaya(u["props"])]
    resolve_nested(wilayas)
    dz_tree = STRtree([w["geom"] for w in wilayas])

    def wilaya_of(geom):
        pt = geom.representative_point()
        hits = [wilayas[i] for i in dz_tree.query(pt, predicate="within")]
        return hits[0] if hits else None

    out: dict[str, list[dict]] = {"wilaya": [], "daira": [], "commune": []}
    for w in wilayas:
        p = w["props"]
        code = (p.get("ISO3166-2") or "DZ-" + p["ref"]).split("-", 1)[1].zfill(2)
        out["wilaya"].append({"geom": w["geom"], "code": code, **names(p), "osm_id": int(p["osm_id"]),
                              "wikidata": p.get("wikidata") or None})
    code_of = {id(w["geom"]): o["code"] for w, o in zip(wilayas, out["wilaya"])}

    for level in ("daira", "commune"):
        for u in units[level]:
            w = wilaya_of(u["geom"])
            if w is None:
                continue  # outside Algeria (neighbouring countries in the extract)
            p = u["props"]
            rec = {"geom": u["geom"], **names(p), "osm_id": int(p["osm_id"]), "wikidata": p.get("wikidata") or None,
                   "wilaya_code": code_of[id(w["geom"])]}
            if level == "commune":
                ons = (p.get("ref_ONS") or "").strip()
                rec["ons_code"] = ons.zfill(4) if ons.isdigit() else None
                pop = (p.get("population") or "").strip()
                rec["population"] = int(pop) if pop.isdigit() else None
            out[level].append(rec)

    out["commune"] = drop_duplicates(out["commune"])
    out["daira"] = drop_duplicates(out["daira"])

    # commune -> daira
    dairas = out["daira"]
    d_tree = STRtree([d["geom"] for d in dairas])
    for c in out["commune"]:
        pt = c["geom"].representative_point()
        hits = [dairas[i] for i in d_tree.query(pt, predicate="within")]
        c["daira_osm_id"] = hits[0]["osm_id"] if hits else None
    for level in out:
        out[level].sort(key=sort_key)
    return out


def resolve_nested(units: list[dict]) -> None:
    """When OSM has not yet cut a newly created unit out of its parent (e.g. a
    new wilaya still inside the old one), subtract the nested unit."""
    for a in units:
        for b in units:
            if a is b:
                continue
            inter = a["geom"].intersection(b["geom"]).area
            if inter > 0.99 * b["geom"].area and a["geom"].area > b["geom"].area:
                print(f"  {a['props'].get('name_fr')!r} contains {b['props'].get('name_fr')!r}: subtracting",
                      file=sys.stderr)
                a["geom"] = make_valid(a["geom"].difference(b["geom"]))


def names(p: dict) -> dict:
    fr = clean_name(p.get("name_fr"), "fr")
    ar = clean_name(p.get("name_ar"), "ar")
    en = clean_name(p.get("name_en"), "en") or fr
    return {"name_ar": ar, "name_fr": fr, "name_en": en}


def drop_duplicates(units: list[dict]) -> list[dict]:
    """Two relations covering (almost) the same area: keep the better tagged one."""
    tree = STRtree([u["geom"] for u in units])
    drop = set()
    for i, u in enumerate(units):
        if i in drop:
            continue
        for j in tree.query(u["geom"], predicate="intersects"):
            if j <= i or j in drop:
                continue
            v = units[j]
            inter = u["geom"].intersection(v["geom"]).area
            if inter > 0.5 * min(u["geom"].area, v["geom"].area):
                score = lambda x: (x.get("ons_code") is not None, x.get("wikidata") is not None, -x["osm_id"])  # noqa: E731
                loser = j if score(u) >= score(v) else i
                drop.add(loser)
                print(f"  dropping duplicate {units[loser]['name_fr']!r} (osm {units[loser]['osm_id']})", file=sys.stderr)
    return [u for k, u in enumerate(units) if k not in drop]


def sort_key(u: dict):
    return (u.get("wilaya_code") or u.get("code"), u.get("ons_code") or "", u["name_fr"])


# ------------------------------------------------------------------- output

PROPS = {
    "wilaya": ["code", "name_ar", "name_fr", "name_en", "osm_id", "wikidata"],
    "daira": ["wilaya_code", "name_ar", "name_fr", "name_en", "osm_id", "wikidata"],
    "commune": ["ons_code", "wilaya_code", "daira_osm_id", "name_ar", "name_fr", "name_en", "population", "osm_id", "wikidata"],
}
PLURAL = {"wilaya": "wilayas", "daira": "dairas", "commune": "communes"}


def round_coords(obj, nd=5):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, (list, tuple)):
        return [round_coords(x, nd) for x in obj]
    return obj


def round_geometry(g: dict) -> dict:
    return {"type": g["type"], "coordinates": round_coords(g["coordinates"])}


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", type=Path)
    ap.add_argument("--tolerance", type=float, default=0.0005, help="simplification tolerance in degrees (~55 m)")
    args = ap.parse_args()
    t0 = time.time()
    pbf = ensure_pbf(args.pbf)
    units = build_units(extract(pbf))
    for level, us in units.items():
        print(f"{level}: {len(us)}", file=sys.stderr)

    print("building topology and simplifying", file=sys.stderr)
    order = ["wilaya", "daira", "commune"]
    topo = Topology()
    idx = {lvl: [topo.add(u["geom"]) for u in units[lvl]] for lvl in order}
    topo.build()
    print(f"  {len(topo.arcs)} shared arcs, {sum(len(a) for a in topo.arcs)} vertices", file=sys.stderr)
    repaired = topo.simplify(args.tolerance)
    print(f"  {len(repaired)} shapes needed finer simplification to stay valid", file=sys.stderr)
    print(f"  after simplification: {sum(len(a) for a in topo.arcs)} vertices", file=sys.stderr)
    DATA.mkdir(exist_ok=True)
    tj = topo.topojson({
        PLURAL[lvl]: [(i, {k: u[k] for k in PROPS[lvl]}) for i, u in zip(idx[lvl], units[lvl])] for lvl in order
    })
    write_json(DATA / "algeria.topojson", tj)
    for lvl in order:
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {k: u[k] for k in PROPS[lvl]},
             "geometry": round_geometry(topo.geometry(i))}
            for i, u in zip(idx[lvl], units[lvl])
        ]}
        write_json(DATA / f"{PLURAL[lvl]}.geojson", fc)
        write_json(DATA / f"{PLURAL[lvl]}.json", [{k: u[k] for k in PROPS[lvl]} for u in units[lvl]])

    fetched = time.strftime("%Y-%m-%d", time.gmtime(pbf.stat().st_mtime))
    sha = hashlib.sha256()
    with open(pbf, "rb") as f:
        while chunk := f.read(1 << 20):
            sha.update(chunk)
    write_json(DATA / "provenance.json", {
        "source": "OpenStreetMap (Geofabrik extract africa/algeria-latest.osm.pbf)",
        "source_url": PBF_URL,
        "extract_date": fetched,
        "extract_sha256": sha.hexdigest(),
        "license": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "levels": {"wilaya": "admin_level=4", "daira": "admin_level=6", "commune": "admin_level=8"},
        "counts": {PLURAL[k]: len(v) for k, v in units.items()},
        "simplification_tolerance_deg": args.tolerance,
        "coordinate_precision": "GeoJSON 5 decimals (~1 m); TopoJSON quantization 1e6",
        "built_with": "scripts/build.py",
    })
    print(f"done in {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
