"""Validation of the published files in data/."""

import json
import re
import sys
from collections import Counter
from functools import cache
from pathlib import Path

import pytest
from shapely import STRtree
from shapely.geometry import shape
from shapely.ops import unary_union

DATA = Path(__file__).resolve().parent.parent / "data"
sys.path.insert(0, str(DATA.parent / "scripts"))
from build import clean_name  # noqa: E402
from topology import decode_topojson  # noqa: E402

ARABIC = re.compile(r"[؀-ۿ]")


@cache
def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


@cache
def shapes(level):
    return [shape(f["geometry"]) for f in load(f"{level}.geojson")["features"]]


def props(level):
    return [f["properties"] for f in load(f"{level}.geojson")["features"]]


def test_counts():
    assert len(props("wilayas")) == 69
    assert 500 <= len(props("dairas")) <= 600
    assert 1500 <= len(props("communes")) <= 1600
    prov = load("provenance.json")
    assert prov["license"] == "ODbL-1.0"
    assert prov["counts"] == {"wilayas": 69, "dairas": len(props("dairas")), "communes": len(props("communes"))}


def test_wilaya_codes_are_complete_and_unique():
    codes = [p["code"] for p in props("wilayas")]
    assert sorted(codes) == [f"{i:02d}" for i in range(1, 70)]


def test_commune_codes_unique_and_well_formed():
    codes = [p["ons_code"] for p in props("communes") if p["ons_code"]]
    assert len(codes) == len(set(codes)), [c for c, n in Counter(codes).items() if n > 1]
    assert all(re.fullmatch(r"\d{4}", c) for c in codes)
    assert len(codes) >= 0.99 * len(props("communes"))
    # Before the 2019/2025 reforms the first two digits were the wilaya; for the
    # original 48 wilayas they still must be.
    for p in props("communes"):
        if p["ons_code"] and int(p["wilaya_code"]) <= 48:
            assert p["ons_code"][:2] == p["wilaya_code"], p


@pytest.mark.parametrize("level", ["wilayas", "dairas", "communes"])
def test_names_in_three_languages(level):
    for p in props(level):
        assert p["name_fr"] and p["name_en"] and p["name_ar"], p
        assert ARABIC.search(p["name_ar"]), p
        assert not ARABIC.search(p["name_fr"]), p
        assert not re.match(r"(?i)(wilaya|commune|da[iï]ra)\b", p["name_fr"]), p
        assert not re.match(r"^(ولاية|بلدية|دائرة)\s", p["name_ar"]), p


@pytest.mark.parametrize("level", ["wilayas", "dairas", "communes"])
def test_geometries_valid_and_inside_algeria(level):
    invalid = [p["name_fr"] for p, g in zip(props(level), shapes(level)) if not g.is_valid or g.is_empty]
    assert len(invalid) <= 0.01 * len(props(level)), invalid[:20]
    for g in shapes(level):
        w, s, e, n = g.bounds
        assert -9 < w and e < 12.5 and 18.5 < s and n < 38, g.bounds


def test_hierarchy_is_consistent():
    wilaya_codes = {p["code"] for p in props("wilayas")}
    dairas = {p["osm_id"]: p for p in props("dairas")}
    missing_daira = 0
    for p in props("communes"):
        assert p["wilaya_code"] in wilaya_codes
        if p["daira_osm_id"] is None:
            missing_daira += 1
            continue
        assert dairas[p["daira_osm_id"]]["wilaya_code"] == p["wilaya_code"], p
    assert missing_daira <= 0.02 * len(props("communes"))
    # every daira has at least one commune
    used = Counter(p["daira_osm_id"] for p in props("communes"))
    assert sum(1 for d in dairas if used[d] == 0) <= 0.02 * len(dairas)


def test_communes_tile_their_wilaya():
    """Each wilaya is covered by its communes, with little overlap.

    Known gaps (see README): a few commune relations are broken in OSM and
    cannot be built, so up to 3 wilayas may be covered at less than 98%,
    never less than 85%.
    """
    by_w = {}
    for p, g in zip(props("communes"), shapes("communes")):
        by_w.setdefault(p["wilaya_code"], []).append(g.buffer(0))
    bad = []
    for p, g in zip(props("wilayas"), shapes("wilayas")):
        parts = by_w.get(p["code"], [])
        union = unary_union(parts)
        covered = union.intersection(g.buffer(0)).area / g.area
        overlap = (sum(x.area for x in parts) - union.area) / g.area
        if covered < 0.98 or overlap > 0.01:
            bad.append((p["code"], p["name_fr"], round(covered, 3), round(overlap, 4)))
    assert len(bad) <= 3, bad
    assert all(cov >= 0.85 and ov <= 0.01 for _, _, cov, ov in bad), bad


def test_no_gaps_between_neighbouring_communes():
    """Shared borders are identical after simplification: neighbours touch, no slivers."""
    gs = [g.buffer(0) for g in shapes("communes")]
    tree = STRtree(gs)
    overlaps = 0
    for i, g in enumerate(gs):
        for j in tree.query(g, predicate="intersects"):
            if j > i and g.intersection(gs[j]).area > 1e-7 * max(g.area, gs[j].area) + 1e-9:
                overlaps += 1
    assert overlaps <= 5, overlaps


def test_topojson_matches_geojson():
    tj = load("algeria.topojson")
    assert tj["type"] == "Topology"
    for level in ("wilayas", "dairas", "communes"):
        feats = decode_topojson(tj, level)
        assert [f["properties"] for f in feats] == props(level)
        for f, g in zip(feats[::50], shapes(level)[::50]):
            t = shape(f["geometry"]).buffer(0)
            # Quantization moves vertices by < 0.0002 degrees; areas match closely.
            assert abs(t.area - g.area) <= 0.01 * g.area + 1e-6


def test_attribute_tables_match_geojson():
    for level in ("wilayas", "dairas", "communes"):
        assert load(f"{level}.json") == props(level)


def test_known_units():
    w = {p["code"]: p for p in props("wilayas")}
    assert w["16"]["name_fr"] == "Alger" and w["16"]["name_ar"] == "الجزائر"
    assert w["31"]["name_fr"] == "Oran"
    c = {p["ons_code"]: p for p in props("communes") if p["ons_code"]}
    assert c["1601"]["wilaya_code"] == "16"
    alger = shapes("wilayas")[[p["code"] for p in props("wilayas")].index("16")]
    from shapely.geometry import Point
    assert alger.contains(Point(3.0588, 36.7538))


@pytest.mark.parametrize("raw, lang, want", [
    ("Wilaya d'Alger", "fr", "Alger"), ("Commune de Bab Ezzouar", "fr", "Bab Ezzouar"), ("Daïra de Chéraga", "fr", "Chéraga"),
    ("wilaya d’El Bayadh", "fr", "El Bayadh"), ("Algiers Province", "en", "Algiers"), ("Commune of Kouba", "en", "Kouba"),
    ("ولاية الجزائر", "ar", "الجزائر"), ("بلدية القبة", "ar", "القبة"), ("Alger", "fr", "Alger"), (None, "fr", ""),
])
def test_clean_name(raw, lang, want):
    assert clean_name(raw, lang) == want
