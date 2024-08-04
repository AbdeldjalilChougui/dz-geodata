# dz-geodata

Algeria's **69 wilayas**, **daïras** and **communes** with Arabic, French and
English names, ONS commune codes and simplified boundaries (GeoJSON +
TopoJSON), plus lookup helpers. There are no dependencies.

## Install

```sh
npm i dz-geodata
```

```js
import { wilaya, communes, commune, search, locate } from "dz-geodata";

wilaya(16).name_ar;              // "الجزائر"
communes(31).length;             // communes of Oran
commune("1601");                 // by ONS code
search("bejaia")[0];             // accent/diacritic-insensitive, ar/fr/en
locate(3.0588, 36.7538);         // { commune, daira, wilaya }
```

Raw files: `dz-geodata/data/{wilayas,dairas,communes}.geojson`,
`dz-geodata/data/algeria.topojson` (objects `wilayas`, `dairas`, `communes`
with shared arcs) and `*.json` attribute tables.

Data © OpenStreetMap contributors, **ODbL 1.0** (see DATA-LICENSE.md). Code: MIT.
