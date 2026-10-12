import gzip
import json
import sqlite3

from zabuni import config
from zabuni.data.normalize import check_supplier_identifier, looks_like_natural_person, normalize_name, parse_amount


def test_fixture_is_deterministic(database, tmp_path):
    from zabuni.data import synth
    synth.main([str(tmp_path / "again.jsonl.gz")])
    assert (tmp_path / "again.jsonl.gz").read_bytes() == database["path"].read_bytes()


def test_no_personal_contact_data_stored(database):
    raw = gzip.open(database["path"], "rt").read()
    assert "@example.go.ke" in raw  # the fixture deliberately carries contact e-mails...
    con = sqlite3.connect(config.DB_PATH)
    dump = "\n".join(con.iterdump())
    assert "@example" not in dump and "0712345678" not in dump  # ...and ingest drops them
    assert "Achieng" not in dump and "Otieno" not in dump  # sole proprietors are pseudonymised


def test_documented_quality_problems_are_flagged_not_dropped(database):
    s = database["stats"]
    assert s["dq:extreme_value"] == 1
    assert s["dq:supplier_scheme_invalid"] > 0
    assert s["buyer_name_not_in_parties"] > 0
    assert s["releases_without_awards"] > 0
    assert s["buyer_name_recovered_by_id"] > 0
    con = sqlite3.connect(config.DB_PATH)
    assert con.execute("SELECT benchmarkable FROM awards WHERE dq_flags LIKE '%extreme_value%'").fetchone() == (0,)


def test_normalisation_and_identifiers():
    assert normalize_name("KILELE TRADERS LIMITED") == normalize_name("Kilele Traders Ltd.") == "kilele traders"
    assert looks_like_natural_person("Achieng Otieno")
    assert not looks_like_natural_person("Jabali Supplies Ltd")
    assert not looks_like_natural_person("Kamau and Sons")
    assert "supplier_scheme_invalid" in check_supplier_identifier("KRA", "P0123")
    assert check_supplier_identifier("KE-KRA", "P051234567X") == []
    assert parse_amount("1,250,000.50") == 1250000.5 and parse_amount("n/a") is None


def test_real_ocds_shapes_are_tolerated(tmp_path):
    """Lines the real feed contains: record packages, bad JSON, missing values, no buyer at all."""
    from zabuni.data import ingest
    lines = [
        {"compiledRelease": {"ocid": "ocds-5whusi-1", "buyer": {"id": "B1", "name": "Ministry X"},
                             "tender": {"title": "Supply of maize seed"},
                             "awards": [{"id": "A1", "value": {"amount": "1,000,000"},
                                         "suppliers": [{"name": "Acme Ltd"}]}]}},
        {"ocid": "ocds-5whusi-2", "awards": [{"id": "A2", "value": {}, "suppliers": []}]},
        {"no_ocid": True},
    ]
    f = tmp_path / "mini.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n{bad json\n")
    stats = ingest.ingest([f], tmp_path / "mini.sqlite")
    assert stats["award_rows"] == 2 and stats["bad_json_lines"] == 1 and stats["skipped_no_ocid"] == 1
    con = sqlite3.connect(tmp_path / "mini.sqlite")
    flags = dict(con.execute("SELECT ocid, dq_flags FROM awards").fetchall())
    assert "currency_assumed_KES" in flags["ocds-5whusi-1"]
    assert "missing_value" in flags["ocds-5whusi-2"]
