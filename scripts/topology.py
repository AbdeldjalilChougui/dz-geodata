"""A small topology builder: shared arcs, per-arc simplification, TopoJSON.

All three levels come from the same OSM ways, so a border shared by two
communes (or a commune and its wilaya) has exactly the same vertices in both
polygons. We cut every ring at *junctions* (vertices where the neighbouring
vertices differ between the rings that use them), deduplicate the resulting
arcs (in either direction) and simplify each arc once. Neighbouring units
then keep identical borders after simplification: no gaps, no slivers.
"""

from __future__ import annotations

from collections import defaultdict

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.polygon import orient

Pt = tuple[float, float]


def _polygons(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    # GeometryCollection from make_valid: keep the polygonal parts.
    out = []
    for g in getattr(geom, "geoms", []):
        out.extend(_polygons(g))
    return out


def _ring(coords) -> list[Pt]:
    pts = [(round(x, 7), round(y, 7)) for x, y, *_ in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    # drop consecutive duplicates introduced by rounding
    out = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


class Topology:
    def __init__(self) -> None:
        # geometries[i] = list of polygons, polygon = list of rings, ring = list of points
        self.shapes: list[list[list[list[Pt]]]] = []
        self.arcs: list[list[Pt]] = []
        # per shape: polygons -> rings -> list of signed arc refs (~i for reversed)
        self.refs: list[list[list[list[int]]]] = []

    def add(self, geom) -> int:
        polys = []
        for p in _polygons(geom):
            p = orient(p, 1.0)  # exterior CCW, holes CW (RFC 7946)
            rings = [_ring(p.exterior.coords)] + [_ring(r.coords) for r in p.interiors]
            rings = [r for r in rings if len(r) >= 3]
            if rings:
                polys.append(rings)
        self.shapes.append(polys)
        return len(self.shapes) - 1

    def build(self) -> None:
        # 1. junctions
        neighbours: dict[Pt, set] = defaultdict(set)
        for polys in self.shapes:
            for rings in polys:
                for ring in rings:
                    n = len(ring)
                    for i, p in enumerate(ring):
                        neighbours[p].add(frozenset((ring[i - 1], ring[(i + 1) % n])))
        junctions = {p for p, s in neighbours.items() if len(s) > 1}

        # 2. cut rings into arcs and deduplicate
        index: dict[tuple[Pt, ...], int] = {}

        def arc_ref(coords: list[Pt]) -> int:
            key = tuple(coords)
            if key in index:
                return index[key]
            rkey = key[::-1]
            if rkey in index:
                return ~index[rkey]
            self.arcs.append(list(coords))
            index[key] = len(self.arcs) - 1
            return index[key]

        for polys in self.shapes:
            shape_refs = []
            for rings in polys:
                poly_refs = []
                for ring in rings:
                    cut = [i for i, p in enumerate(ring) if p in junctions]
                    if not cut:
                        # Isolated ring: start at the smallest point so identical
                        # rings (e.g. a wilaya equal to its only commune) match.
                        k = ring.index(min(ring))
                        rot = ring[k:] + ring[:k]
                        poly_refs.append([arc_ref(rot + [rot[0]])])  # arc_ref also matches the reverse
                        continue
                    k = cut[0]
                    rot = ring[k:] + ring[:k]
                    cuts = [i - k if i >= k else i - k + len(ring) for i in cut] + [len(ring)]
                    refs = []
                    for a, b in zip(cuts, cuts[1:]):
                        seg = rot[a : b + 1] if b < len(ring) else rot[a:] + [rot[0]]
                        refs.append(arc_ref(seg))
                    poly_refs.append(refs)
                shape_refs.append(poly_refs)
            self.refs.append(shape_refs)

    def simplify(self, tolerance: float, max_rounds: int = 6) -> list[int]:
        """Douglas-Peucker on each arc (endpoints are kept, so junctions stay put).

        Simplifying arcs independently can make a polygon self-intersect
        (typically along jagged coastlines). After each pass, every shape is
        validated, and the arcs of invalid shapes are re-simplified with a
        quarter of the tolerance, down to the original vertices. Returns the
        shapes that needed this treatment.
        """
        if tolerance <= 0:
            return []
        from shapely.geometry import shape as to_shape

        original = [list(a) for a in self.arcs]
        level = [tolerance] * len(self.arcs)

        def apply(i: int) -> None:
            arc = original[i]
            if len(arc) <= 2 or level[i] <= 0:
                self.arcs[i] = list(arc)
                return
            closed = arc[0] == arc[-1]
            simp = [(x, y) for x, y in LineString(arc).simplify(level[i], preserve_topology=False).coords]
            self.arcs[i] = list(arc) if closed and len(simp) < 4 else simp

        for i in range(len(self.arcs)):
            apply(i)
        fixed: set[int] = set()
        for round_ in range(max_rounds):
            bad = [k for k in range(len(self.shapes)) if not to_shape(self.geometry(k)).is_valid]
            if not bad:
                break
            fixed.update(bad)
            last = round_ == max_rounds - 1
            for k in bad:
                for poly in self.refs[k]:
                    for ring in poly:
                        for r in ring:
                            i = r if r >= 0 else ~r
                            level[i] = 0 if last or level[i] < tolerance / 60 else level[i] / 4
                            apply(i)
        return sorted(fixed)

    def _ring_coords(self, refs: list[int]) -> list[Pt]:
        out: list[Pt] = []
        for r in refs:
            arc = self.arcs[r] if r >= 0 else self.arcs[~r][::-1]
            out.extend(arc if not out else arc[1:])
        return out

    def geometry(self, shape_index: int) -> dict:
        """GeoJSON geometry for a shape, rebuilt from the (simplified) arcs."""
        polys = []
        for poly in self.refs[shape_index]:
            rings = [self._ring_coords(r) for r in poly]
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                polys.append(rings)
        if len(polys) == 1:
            return {"type": "Polygon", "coordinates": polys[0]}
        return {"type": "MultiPolygon", "coordinates": polys}

    def topojson(self, objects: dict[str, list[tuple[int, dict]]], quantization: int = 100_000) -> dict:
        """TopoJSON with quantized, delta-encoded arcs.

        ``objects`` maps an object name to a list of (shape index, properties).
        """
        xs = [x for a in self.arcs for x, _ in a]
        ys = [y for a in self.arcs for _, y in a]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        kx = (x1 - x0) / (quantization - 1) or 1.0
        ky = (y1 - y0) / (quantization - 1) or 1.0
        arcs = []
        for a in self.arcs:
            q = [(round((x - x0) / kx), round((y - y0) / ky)) for x, y in a]
            enc, px, py = [], 0, 0
            for j, (qx, qy) in enumerate(q):
                if j and (qx, qy) == (px, py) and j != len(q) - 1:
                    continue
                enc.append([qx - px, qy - py] if j else [qx, qy])
                px, py = qx, qy
            arcs.append(enc)
        out_objects = {}
        for name, items in objects.items():
            geoms = []
            for idx, props in items:
                polys = [[list(r) for r in poly] for poly in self.refs[idx]]
                if len(polys) == 1:
                    geoms.append({"type": "Polygon", "arcs": polys[0], "properties": props})
                else:
                    geoms.append({"type": "MultiPolygon", "arcs": polys, "properties": props})
            out_objects[name] = {"type": "GeometryCollection", "geometries": geoms}
        return {
            "type": "Topology",
            "bbox": [x0, y0, x1, y1],
            "transform": {"scale": [kx, ky], "translate": [x0, y0]},
            "objects": out_objects,
            "arcs": arcs,
        }


def decode_topojson(tj: dict, name: str) -> list[dict]:
    """Minimal TopoJSON -> GeoJSON features decoder (used by the tests)."""
    sx, sy = tj["transform"]["scale"]
    tx, ty = tj["transform"]["translate"]
    arcs = []
    for a in tj["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in a:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(refs):
        out = []
        for r in refs:
            arc = arcs[r] if r >= 0 else arcs[~r][::-1]
            out.extend(arc if not out else arc[1:])
        return out

    feats = []
    for g in tj["objects"][name]["geometries"]:
        if g["type"] == "Polygon":
            geom = {"type": "Polygon", "coordinates": [ring(r) for r in g["arcs"]]}
        else:
            geom = {"type": "MultiPolygon", "coordinates": [[ring(r) for r in p] for p in g["arcs"]]}
        feats.append({"type": "Feature", "properties": g.get("properties", {}), "geometry": geom})
    return feats
