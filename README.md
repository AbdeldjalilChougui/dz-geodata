# dz-geodata

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23458096.svg)](https://doi.org/10.5281/zenodo.23458096)

Algeria's administrative boundaries, **69 wilayas → 548 daïras → 1,538
communes**, as GeoJSON and TopoJSON with **Arabic, French and English
names**, **ONS commune codes** and the hierarchy between levels. Everything is
built reproducibly from OpenStreetMap and shipped as an **npm** and a
**pip** package with lookup helpers.

| file (`data/`) | content |
|---|---|
| `wilayas.geojson` | 69 wilayas: `code` ("01"–"69"), `name_ar`, `name_fr`, `name_en`, `osm_id`, `wikidata` |
| `dairas.geojson` | 548 daïras: `wilaya_code`, names, `osm_id`, `wikidata` |
| `communes.geojson` | 1,538 communes: `ons_code`, `wilaya_code`, `daira_osm_id`, names, `population` (as tagged in OSM), `osm_id`, `wikidata` |
| `algeria.topojson` | all three levels as one topology with shared arcs (1.6 MB) |
| `*.json` | the same attributes without geometry (for dropdowns and lookups) |
| `provenance.json` | source, extract date and SHA-256, counts, simplification settings |

Geometries are simplified (Douglas–Peucker, 0.0005° ≈ 55 m) **on shared
arcs**, so neighbouring units still share identical borders: no gaps, no
slivers. GeoJSON coordinates are rounded to 5 decimals.

## Install

```sh
npm i dz-geodata          # or: pnpm add dz-geodata
pip install dz-geodata    # or: uv add dz-geodata
```

The raw files are also usable straight from a CDN once published, e.g.
`https://unpkg.com/dz-geodata/data/wilayas.geojson`.

## Packages

```js
// npm i dz-geodata
import { wilaya, communes, commune, search, locate } from "dz-geodata";
wilaya(16).name_ar;          // "الجزائر"
search("بجاية")[0].name_fr;   // "Béjaïa"
locate(-0.6417, 35.6971);    // { commune, daira, wilaya: { code: "31", ... } }
```

```python
# pip install dz-geodata
import dz_geodata as dz
dz.commune("1601"); dz.communes(wilaya_code=31); dz.search("bejaia"); dz.locate(3.0588, 36.7538)
```

Both offer the same functions: `wilayas`, `wilaya(code)` (accepts `16`,
`"16"`, `"DZ-16"`), `dairas(w)`, `daira(osm_id)`, `communes(w)`,
`commune(ons)`, `search(q, level, limit)` and `locate(lon, lat)`, plus
`normalize`. Search ignores case, accents and Arabic diacritics, and unifies
alef, ta marbuta and alef maqsura variants. It ranks exact matches above
prefix matches above substring matches.

## Rebuilding

Requirements: [uv](https://docs.astral.sh/uv/) and GDAL's `ogr2ogr` (with the OSM driver).

```sh
uv sync
uv run python scripts/build.py          # downloads the Geofabrik extract (~300 MB) into raw/ if missing
uv run python scripts/sync_packages.py  # copy data/ into packages/
uv run pytest                           # validate data/
(cd packages/npm && node --test test/)
(cd packages/python && uv run pytest)
```

The build takes about 6 minutes on a laptop, mostly `ogr2ogr` reading the
PBF. The steps are:
1. **Extract** `boundary=administrative` multipolygons at `admin_level` 4/6/8 from the
   [Geofabrik Algeria extract](https://download.geofabrik.de/africa/algeria.html) with GDAL's OSM driver
   (`scripts/osmconf.ini` selects the tags).
2. **Filter to Algeria.** Wilayas are those tagged `ISO3166-2=DZ-*`, or with a numeric `ref` 1–69 if a new
   wilaya lacks the ISO tag. A daïra or commune is kept when its interior point falls in a wilaya; this drops
   Moroccan and Tunisian units that the extract includes along the border.
3. **Fix known OSM inconsistencies.** A newly created wilaya still nested in its parent is subtracted from it
   (as of this extract, El Aricha was still inside Tlemcen). Duplicate relations covering the same area keep the
   better-tagged one.
4. **Names.** `name:ar`, `name:fr` and `name:en` with administrative prefixes stripped ("Wilaya d'", "بلدية ",
   " Province"). `name_en` falls back to `name_fr` when OSM has no English name.
5. **Hierarchy.** Commune → daïra and commune → wilaya by point-in-polygon.
6. **Topology.** Rings are cut at junctions into shared arcs (deduplicated in both directions), each arc is
   simplified once, and shapes that would self-intersect are re-simplified more finely, down to the original
   vertices if needed. Then TopoJSON (quantized, delta-encoded) and GeoJSON are written.

## Validation (`uv run pytest`, 25 tests)

- Counts:
  - 69 wilayas with codes exactly "01"–"69"
  - 500–600 daïras and 1,500–1,600 communes
  - unique 4-digit ONS codes on ≥ 99% of communes
  - for the original 48 wilayas, the ONS prefix equals the wilaya code
- Names: Arabic script in `name_ar`, none in `name_fr`, no leftover administrative prefixes, all three
  languages present.
- Geometry:
  - every geometry valid and inside Algeria's bounding box
  - communes tile their wilaya (≥ 98% coverage, ≤ 1% overlap; known exceptions below)
  - neighbouring communes do not overlap after simplification
- Hierarchy and formats:
  - every commune's daïra is in the same wilaya
  - TopoJSON decodes to the same features and areas as the GeoJSON
  - the attribute tables equal the GeoJSON properties
  - spot checks: Alger = 16, Grande Poste inside Alger, Oran = 31

The npm (5) and Python (6) package tests cover lookups, search ranking in all three languages and `locate`.

## Status and limitations

- **This is OSM data, as of the extract date in `provenance.json`.** It reflects the 2025 reorganisation into
  69 wilayas wherever OSM does. Check against official sources (ONS, Journal officiel) for legal use.
- **ONS codes are as tagged in OSM** (`ref:ONS`). They follow the historic numbering, so communes now in a
  wilaya created in 2019 or 2025 keep their old prefix (e.g. a commune of wilaya 58 may still start with 47).
  One commune (Aïn Defla) has no code in OSM.
- **Missing communes.** A few commune relations are broken in OSM and cannot be assembled, which leaves holes:
  about 3.6% of Alger's area (around 36.64°N 3.03°E) and 10.6% of Ghardaïa's. 1,538 communes are present out
  of 1,541 official ones.
- Daïras have no official code in OSM, so they are identified by `osm_id`.
- The boundaries are simplified for web maps and are not survey-grade. Rebuild with `--tolerance 0` for full
  detail.

## License

- Code (build scripts, packages): **MIT**, see [LICENSE](LICENSE).
- Data: **ODbL 1.0**, © OpenStreetMap contributors. See [DATA-LICENSE.md](DATA-LICENSE.md). Keep the
  attribution in any map or app that uses it.
