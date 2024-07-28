import dz_geodata as dz


def test_wilayas():
    assert len(dz.wilayas()) == 69
    assert dz.wilaya(16)["name_fr"] == "Alger"
    assert dz.wilaya("DZ-31")["name_ar"] == "وهران"
    assert dz.wilaya("9")["code"] == "09"
    assert dz.wilaya(99) is None


def test_communes_and_dairas():
    assert all(c["wilaya_code"] == "16" for c in dz.communes(16))
    assert len(dz.communes(16)) >= 50
    assert dz.commune(1601)["wilaya_code"] == "16"
    assert dz.commune("0101")["name_fr"] == "Adrar"
    assert len(dz.dairas("16")) >= 10
    d = dz.dairas()[0]
    assert dz.daira(d["osm_id"]) == d


def test_normalize():
    assert dz.normalize("Béjaïa") == "bejaia"
    assert dz.normalize("أدرار") == "ادرار"
    assert dz.normalize("بَسْكْرَة") == "بسكره"
    assert dz.normalize("Aïn  Defla") == "ain defla"


def test_search():
    top = dz.search("oran")[0]
    assert top["name_fr"] == "Oran" and top["level"] == "wilaya"
    assert dz.search("وهران", level="commune")[0]["name_fr"] == "Oran"
    assert dz.search("Algiers")[0]["code"] == "16"
    assert len(dz.search("bab", limit=3)) == 3
    assert dz.search("") == []


def test_locate():
    r = dz.locate(3.0588, 36.7538)
    assert r["wilaya"]["code"] == "16" and r["commune"]["wilaya_code"] == "16"
    assert dz.locate(-0.6417, 35.6971)["wilaya"]["code"] == "31"
    assert dz.locate(2.35, 48.85) is None


def test_files_and_provenance():
    assert dz.data_path("algeria.topojson").exists()
    assert dz.provenance()["license"] == "ODbL-1.0"
    assert len(dz.geojson("wilayas")["features"]) == 69
