import pytest

from zabuni.mcp_server import store
from zabuni.mcp_server.store import StoreError


def test_benchmark_verdicts():
    assert store.price_benchmark("certified maize seed", 4_500_000)["verdict"] == "within_range"
    hi = store.price_benchmark("certified maize seed", 19_800_000)
    assert hi["verdict"] == "high_outlier" and hi["comparables_used"] >= 30
    assert all("source" in c for c in hi["comparables"])
    assert store.price_benchmark("DAP planting fertiliser", 950_000)["verdict"] == "low_outlier"


def test_benchmark_refuses_to_judge_thin_evidence():
    r = store.price_benchmark("MRI machine", 195_000_000)
    assert r["verdict"] == "insufficient_comparables"
    assert any("non_kes_currency" in e["reason"] for e in r["excluded"])


def test_extreme_value_excluded_and_disclosed():
    r = store.price_benchmark("gravelling of rural access roads", 19_500_000)
    assert r["verdict"] == "within_range"
    assert any("extreme_value" in e["reason"] for e in r["excluded"])


def test_budget_variance():
    r = store.price_benchmark("desktop computers and laptops", 4_300_000, budget_amount=3_500_000)
    assert r["over_budget"] and r["budget_variance_pct"] == pytest.approx(22.9, abs=0.1)


def test_supplier_variants_merged_and_concentration():
    p = store.supplier_profile("Kilele Traders Ltd.", buyer="County Government of Mfano", item_query="borehole drilling")
    assert len(p["name_variants_merged"]) == 4
    assert p["concentration"]["share_by_count_pct"] >= 50


def test_sole_proprietor_pseudonymised():
    p = store.supplier_profile("Achieng Otieno")
    assert p["pseudonymised"] and p["supplier"].startswith("Supplier P-")
    assert "Achieng" not in str(p)


def test_unknown_supplier_gives_actionable_error():
    with pytest.raises(StoreError, match="No supplier matching"):
        store.supplier_profile("Nonexistent Holdings Ltd")


def test_split_detection():
    r = store.detect_split_awards("Kielelezo Level 5 Hospital", "medical and surgical consumables")
    assert r["verdict"] == "possible_splitting"
    c = r["clusters"][0]
    assert c["supplier"] == "Afya Medical Supplies Ltd" and c["awards_in_window"] == 4 and len(c["sources"]) == 4
    assert store.detect_split_awards("County Government of Mfano", "medical consumables")["verdict"] == "no_pattern_found"


def test_generic_query_rejected():
    with pytest.raises(StoreError):
        store.search_awards("supply and delivery of")
