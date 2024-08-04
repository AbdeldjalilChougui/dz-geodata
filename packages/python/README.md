# dz-geodata (Python)

Algeria's wilayas, daïras and communes with Arabic, French and English names,
ONS codes and simplified boundaries, plus lookup helpers. There are no
dependencies.

## Install

```sh
pip install dz-geodata
```

```python
import dz_geodata as dz

dz.wilaya(16)["name_ar"]            # 'الجزائر'
dz.commune("1601")["name_fr"]
dz.communes(wilaya_code=31)         # communes of Oran
dz.search("bejaia")[0]              # accent/diacritic-insensitive, ar/fr/en
dz.locate(3.0588, 36.7538)          # {'commune': ..., 'daira': ..., 'wilaya': ...}
dz.geojson("communes")              # full FeatureCollection (dict)
dz.data_path("algeria.topojson")    # path to the bundled file
```

Data © OpenStreetMap contributors, ODbL 1.0. Code MIT. See the
[project README](https://github.com/abdeldjalil-chougui/dz-geodata) for
provenance and limitations.
