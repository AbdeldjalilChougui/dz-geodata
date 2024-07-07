export interface Names {
  name_ar: string;
  name_fr: string;
  name_en: string;
  osm_id: number;
  wikidata: string | null;
}
export interface Wilaya extends Names {
  /** Two-digit code, "01".."69". */
  code: string;
}
export interface Daira extends Names {
  wilaya_code: string;
}
export interface Commune extends Names {
  /** Four-digit ONS code as tagged in OpenStreetMap (ref:ONS), or null. */
  ons_code: string | null;
  wilaya_code: string;
  daira_osm_id: number | null;
  population: number | null;
}
export type Level = "wilaya" | "daira" | "commune";
export type SearchHit = (Wilaya | Daira | Commune) & { level: Level };

export function normalize(text: string): string;
export function wilayas(): Wilaya[];
export function wilaya(code: string | number): Wilaya | undefined;
export function dairas(wilayaCode?: string | number): Daira[];
export function daira(osmId: number): Daira | undefined;
export function communes(wilayaCode?: string | number): Commune[];
export function commune(onsCode: string | number): Commune | undefined;
export function search(query: string, options?: { level?: Level; limit?: number }): SearchHit[];
export function locate(lon: number, lat: number): { commune: Commune; daira: Daira | null; wilaya: Wilaya } | null;
