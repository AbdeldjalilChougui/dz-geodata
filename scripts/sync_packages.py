"""Copy the built data files into the npm and Python packages (run after build.py)."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["wilayas.json", "dairas.json", "communes.json", "wilayas.geojson", "dairas.geojson",
         "communes.geojson", "algeria.topojson", "provenance.json"]
TARGETS = [ROOT / "packages/npm/data", ROOT / "packages/python/src/dz_geodata/data"]

for target in TARGETS:
    target.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy2(ROOT / "data" / f, target / f)
    print(f"synced {len(FILES)} files -> {target.relative_to(ROOT)}")
