import assert from "node:assert/strict";
import { test } from "node:test";
import { commune, communes, dairas, locate, normalize, search, wilaya, wilayas } from "../index.js";

test("wilayas and codes", () => {
  assert.equal(wilayas().length, 69);
  assert.equal(wilaya(16).name_fr, "Alger");
  assert.equal(wilaya("DZ-16").name_ar, "الجزائر");
  assert.equal(wilaya("9").code, "09");
  assert.equal(wilaya(99), undefined);
});

test("communes and dairas per wilaya", () => {
  const algiers = communes(16);
  assert.ok(algiers.length >= 50);
  assert.ok(algiers.every((c) => c.wilaya_code === "16"));
  assert.ok(dairas("16").length >= 10);
  assert.equal(commune(1601).wilaya_code, "16");
  assert.equal(commune("0101").name_fr, "Adrar");
});

test("normalize handles accents and Arabic variants", () => {
  assert.equal(normalize("Béjaïa"), "bejaia");
  assert.equal(normalize("أدرار"), "ادرار");
  assert.equal(normalize("بَسْكْرَة"), "بسكره");
  assert.equal(normalize("Aïn  Defla"), "ain defla");
});

test("search ranks exact matches first, across languages", () => {
  assert.equal(search("oran")[0].name_fr, "Oran");
  assert.equal(search("oran")[0].level, "wilaya");
  assert.equal(search("وهران", { level: "commune" })[0].name_fr, "Oran");
  assert.equal(search("Algiers")[0].code, "16");
  assert.equal(search("bejaia")[0].name_fr, "Béjaïa");
  assert.ok(search("bab", { limit: 3 }).length === 3);
  assert.deepEqual(search(""), []);
});

test("locate a point", () => {
  const r = locate(3.0588, 36.7538); // Grande Poste, Algiers
  assert.equal(r.wilaya.code, "16");
  assert.equal(r.commune.wilaya_code, "16");
  assert.ok(r.daira === null || r.daira.wilaya_code === "16");
  assert.equal(locate(-0.6417, 35.6971).wilaya.code, "31");
  assert.equal(locate(2.35, 48.85), null); // Paris
});
