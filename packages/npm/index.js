// dz-geodata: lookups over Algeria's administrative units.
// Attribute tables are small and loaded eagerly; the GeoJSON used by
// locate() is loaded on first use.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const WILAYAS = require("./data/wilayas.json");
const DAIRAS = require("./data/dairas.json");
const COMMUNES = require("./data/communes.json");

const TASHKEEL = /[ؐ-ًؚ-ٰٟۖ-ۭـ]/g;

/** Lowercase, strip accents and Arabic diacritics, unify common letter variants. */
export function normalize(text) {
  return String(text ?? "")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(TASHKEEL, "")
    .replace(/[أإآٱ]/g, "ا")
    .replace(/ة/g, "ه")
    .replace(/ى/g, "ي")
    .toLowerCase()
    .replace(/['’`-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function wilayaCode(code) {
  const s = String(code).replace(/^DZ-/i, "").trim();
  return /^\d{1,2}$/.test(s) ? s.padStart(2, "0") : null;
}

export const wilayas = () => WILAYAS.slice();

export function wilaya(code) {
  const c = wilayaCode(code);
  return WILAYAS.find((w) => w.code === c);
}

export function dairas(wilayaCodeFilter) {
  if (wilayaCodeFilter === undefined) return DAIRAS.slice();
  const c = wilayaCode(wilayaCodeFilter);
  return DAIRAS.filter((d) => d.wilaya_code === c);
}

export function communes(wilayaCodeFilter) {
  if (wilayaCodeFilter === undefined) return COMMUNES.slice();
  const c = wilayaCode(wilayaCodeFilter);
  return COMMUNES.filter((x) => x.wilaya_code === c);
}

export function commune(onsCode) {
  const c = String(onsCode).padStart(4, "0");
  return COMMUNES.find((x) => x.ons_code === c);
}

export function daira(osmId) {
  return DAIRAS.find((d) => d.osm_id === Number(osmId));
}

/**
 * Search names in Arabic, French and English. Exact matches rank first,
 * then prefix matches, then substring matches; ties keep wilaya < daira < commune.
 */
export function search(query, { level, limit = 10 } = {}) {
  const q = normalize(query);
  if (!q) return [];
  const levels = level ? [level] : ["wilaya", "daira", "commune"];
  const tables = { wilaya: WILAYAS, daira: DAIRAS, commune: COMMUNES };
  const hits = [];
  levels.forEach((lv, li) => {
    for (const item of tables[lv]) {
      let best = 9;
      for (const name of [item.name_fr, item.name_ar, item.name_en]) {
        const n = normalize(name);
        const score = n === q ? 0 : n.startsWith(q) ? 1 : n.includes(q) ? 2 : 9;
        best = Math.min(best, score);
      }
      if (best < 9) hits.push({ level: lv, score: best * 10 + li, item });
    }
  });
  hits.sort((a, b) => a.score - b.score || a.item.name_fr.localeCompare(b.item.name_fr));
  return hits.slice(0, limit).map(({ level: lv, item }) => ({ level: lv, ...item }));
}

// ---------------------------------------------------------------- locate

let INDEX = null;

function bbox(coords, b = [Infinity, Infinity, -Infinity, -Infinity]) {
  if (typeof coords[0] === "number") {
    b[0] = Math.min(b[0], coords[0]); b[1] = Math.min(b[1], coords[1]);
    b[2] = Math.max(b[2], coords[0]); b[3] = Math.max(b[3], coords[1]);
    return b;
  }
  for (const c of coords) bbox(c, b);
  return b;
}

function inRing(ring, x, y) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < xi + ((y - yi) * (xj - xi)) / (yj - yi)) inside = !inside;
  }
  return inside;
}

function inPolygon(rings, x, y) {
  if (!inRing(rings[0], x, y)) return false;
  for (let k = 1; k < rings.length; k++) if (inRing(rings[k], x, y)) return false;
  return true;
}

function contains(geometry, x, y) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polys.some((p) => inPolygon(p, x, y));
}

/** Administrative units containing (lon, lat), or null outside Algeria. */
export function locate(lon, lat) {
  if (!INDEX) {
    INDEX = JSON.parse(readFileSync(new URL("./data/communes.geojson", import.meta.url), "utf8")).features.map((f) => ({ f, b: bbox(f.geometry.coordinates) }));
  }
  for (const { f, b } of INDEX) {
    if (lon < b[0] || lon > b[2] || lat < b[1] || lat > b[3]) continue;
    if (contains(f.geometry, lon, lat)) {
      const c = f.properties;
      return { commune: c, daira: c.daira_osm_id ? daira(c.daira_osm_id) ?? null : null, wilaya: wilaya(c.wilaya_code) };
    }
  }
  return null;
}
