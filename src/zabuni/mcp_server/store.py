"""Read side: queries and statistics over the ingested OCDS awards table.

Every row returned carries a `source` citation that can be resolved back to one line of
the original OCDS file: the OCID, the award ID and a JSON pointer to the value used.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from zabuni import config
from zabuni.data.normalize import looks_like_natural_person, normalize_name, pseudonym

STOPWORDS = {
    "supply", "supplies", "delivery", "deliver", "and", "of", "the", "for", "to", "in", "at", "a", "an",
    "tender", "provision", "procurement", "proposed", "framework", "contract", "lot", "no", "various",
    "county", "government", "department", "ministry", "financial", "year", "fy", "on", "with", "by",
}

COLUMNS = (
    "row_id, ocid, award_id, award_index, source_file, source_line, title, category, method, buyer_name,"
    " buyer_name_source, supplier_key, supplier_display, natural_person, amount, currency, award_date,"
    " award_status, dq_flags, benchmarkable"
)
QCOLUMNS = ", ".join("awards." + c.strip() for c in COLUMNS.split(","))


class StoreError(ValueError):
    """Raised for bad tool input. Returned to the model as a readable error."""


@lru_cache(maxsize=4)
def _connect(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise StoreError(f"No database at {db_path}. Run `make data` (synthetic) or `make kenya` (real) first.")
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def db() -> sqlite3.Connection:
    return _connect(str(config.DB_PATH))


def citation(row: sqlite3.Row | dict) -> dict:
    return {
        "type": "ocds",
        "ocid": row["ocid"],
        "award_id": row["award_id"],
        "pointer": f"/awards/{row['award_index']}/value/amount",
        "file": row["source_file"],
        "line": row["source_line"],
    }


def _clean_title(title: str) -> str:
    return re.sub(r"\([^)]*\)", " ", title or "")


def _stem(t: str) -> str:
    """Light suffix stripping so 'gravelling' ~ 'gravel' and 'laptops' ~ 'laptop' when scoring."""
    for suf in ("ings", "ing", "ies", "es", "ed", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            t = t[: -len(suf)]
            break
    if len(t) > 4 and t[-1] == t[-2]:  # 'gravell' -> 'gravel'
        t = t[:-1]
    return t


def _terms(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", _clean_title(text).lower())
    return [_stem(t) for t in toks if t not in STOPWORDS and len(t) > 2]


def _row_out(r: sqlite3.Row, similarity: float | None = None) -> dict:
    out = {
        "title": r["title"],
        "buyer": r["buyer_name"],
        "supplier": r["supplier_display"],
        "amount": r["amount"],
        "currency": r["currency"],
        "award_date": (r["award_date"] or "")[:10],
        "category": r["category"],
        "dq_flags": [f for f in (r["dq_flags"] or "").split(",") if f],
        "benchmarkable": bool(r["benchmarkable"]),
        "source": citation(r),
    }
    if similarity is not None:
        out["similarity"] = round(similarity, 1)
    return out


def find_comparables(query: str, category: str | None = None, buyer: str | None = None,
                     year_from: int | None = None, year_to: int | None = None,
                     exclude_ocid: str | None = None, min_similarity: float = 60.0,
                     limit: int = 200) -> list[tuple[sqlite3.Row, float]]:
    terms = _terms(query)
    if not terms:
        raise StoreError("Query has no searchable words after removing generic terms like 'supply of'. "
                         "Use the item itself, e.g. 'maize seed' or 'borehole drilling'.")
    fts = " OR ".join(f'"{t}"*' for t in terms)  # prefix match on the stem (FTS also stems with porter)
    sql = (f"SELECT {QCOLUMNS} FROM awards JOIN awards_fts ON awards_fts.rowid = awards.row_id "
           "WHERE awards_fts MATCH ?")
    params: list = [fts]
    if category:
        sql += " AND lower(category) = lower(?)"
        params.append(category)
    if buyer:
        sql += " AND lower(buyer_name) = lower(?)"
        params.append(buyer)
    if year_from:
        sql += " AND substr(award_date,1,4) >= ?"
        params.append(str(year_from))
    if year_to:
        sql += " AND substr(award_date,1,4) <= ?"
        params.append(str(year_to))
    if exclude_ocid:
        sql += " AND ocid != ?"
        params.append(exclude_ocid)
    sql += " ORDER BY bm25(awards_fts) LIMIT 2000"
    rows = db().execute(sql, params).fetchall()
    q = " ".join(terms)
    qset = set(terms)
    scored = []
    for r in rows:
        tt = _terms(r["title"])
        # Coverage: most query words must appear in the title, so 'grass seed' does not match 'maize seed'.
        covered = sum(any(w.startswith(t) or t.startswith(w) for w in tt) for t in qset) / len(qset)
        if covered < 0.67:
            continue
        s = fuzz.token_set_ratio(q, " ".join(tt))
        if s >= min_similarity:
            scored.append((r, s))
    scored.sort(key=lambda x: (-x[1], x[0]["row_id"]))
    return scored[:limit]


def search_awards(query: str, category: str | None = None, buyer: str | None = None,
                  year_from: int | None = None, year_to: int | None = None, limit: int = 15) -> dict:
    limit = max(1, min(int(limit), 50))
    scored = find_comparables(query, category, buyer, year_from, year_to)
    return {
        "query": query,
        "matched": len(scored),
        "returned": min(limit, len(scored)),
        "awards": [_row_out(r, s) for r, s in scored[:limit]],
        "note": "Amounts are award totals as published. Rows with dq_flags are shown, not hidden.",
    }


def _robust(values: list[float]) -> tuple[float, float]:
    logs = [math.log(v) for v in values]
    med = statistics.median(logs)
    mad = statistics.median([abs(x - med) for x in logs])
    return med, mad


def price_benchmark(item_query: str, proposed_amount: float, category: str | None = None,
                    exclude_ocid: str | None = None, budget_amount: float | None = None,
                    min_similarity: float = 60.0) -> dict:
    if proposed_amount is None or proposed_amount <= 0:
        raise StoreError("proposed_amount must be a positive number in KES.")
    scored = find_comparables(item_query, category, exclude_ocid=exclude_ocid, min_similarity=min_similarity)
    used = [(r, s) for r, s in scored if r["benchmarkable"]]
    excluded = [(r, s) for r, s in scored if not r["benchmarkable"]]
    result: dict = {
        "item_query": item_query,
        "proposed_amount": proposed_amount,
        "currency": "KES",
        "comparables_found": len(scored),
        "comparables_used": len(used),
        "excluded_total": len(excluded),
        "excluded": [
            {"reason": r["dq_flags"], "amount": r["amount"], "currency": r["currency"], "source": citation(r)}
            for r, _ in excluded[:10]
        ],
        "caveats": [
            "Compares award totals, not unit prices: the source portal publishes no item quantities.",
            "Comparables are matched on tender title text; scope and quantity may differ between awards.",
            "Rows flagged as data errors (extreme value, non-KES, cancelled, missing value) are excluded and listed.",
        ],
    }
    if budget_amount:
        result["budget_amount"] = budget_amount
        result["budget_variance_pct"] = round((proposed_amount - budget_amount) / budget_amount * 100, 1)
        result["over_budget"] = proposed_amount > budget_amount
    if len(used) < config.MIN_COMPARABLES:
        result["verdict"] = "insufficient_comparables"
        result["explanation"] = (f"Only {len(used)} usable comparable awards (minimum {config.MIN_COMPARABLES}). "
                                 "No price judgement is made; do not flag price on this evidence.")
        result["comparables"] = [_row_out(r, s) for r, s in used]
        if len(_terms(item_query)) > 2:
            result["hint"] = ("Most query words must appear in a title to count as comparable. If the item is "
                              "common, retry with 2-3 words naming only the item (drop seasons, places, lot numbers).")
        return result
    amounts = [r["amount"] for r, _ in used]
    med, mad = _robust(amounts)
    lp = math.log(proposed_amount)
    z = 0.6745 * (lp - med) / mad if mad > 0 else (0.0 if lp == med else math.copysign(99.0, lp - med))
    pct = sum(a <= proposed_amount for a in amounts) / len(amounts) * 100
    median_amount = math.exp(med)
    if z >= config.OUTLIER_Z:
        verdict = "high_outlier"
    elif z <= -config.OUTLIER_Z:
        verdict = "low_outlier"
    else:
        verdict = "within_range"
    q = statistics.quantiles(amounts, n=4) if len(amounts) >= 4 else [min(amounts), median_amount, max(amounts)]
    result.update({
        "verdict": verdict,
        "median_amount": round(median_amount, 2),
        "p25": round(q[0], 2),
        "p75": round(q[-1], 2),
        "ratio_to_median": round(proposed_amount / median_amount, 2),
        "robust_z_log": round(z, 2),
        "percentile_rank": round(pct, 1),
        "threshold_z": config.OUTLIER_Z,
        "method": "Robust z-score of log(amount) using median and MAD of usable comparables.",
        "comparables": [_row_out(r, s) for r, s in sorted(used, key=lambda x: -x[1])[:10]],
    })
    return result


def _supplier_keys() -> list[str]:
    return [r[0] for r in db().execute("SELECT DISTINCT supplier_key FROM awards").fetchall()]


def resolve_supplier(name: str) -> tuple[str, list[str], bool]:
    """Return (key, merged display variants, is_natural_person)."""
    norm = normalize_name(name)
    if not norm:
        raise StoreError("supplier_name is empty.")
    if looks_like_natural_person(name):
        key = pseudonym(norm)
        if not db().execute("SELECT 1 FROM awards WHERE supplier_key=?", (key,)).fetchone():
            raise StoreError("No awards found for that supplier.")
        return key, [key], True
    keys = _supplier_keys()
    if norm in keys:
        key = norm
    else:
        match = process.extractOne(norm, [k for k in keys if not k.startswith("Supplier P-")],
                                   scorer=fuzz.token_sort_ratio, score_cutoff=90)
        if not match:
            close = process.extract(norm, keys, scorer=fuzz.token_sort_ratio, limit=3)
            raise StoreError(f"No supplier matching '{name}'. Closest keys: {[c[0] for c in close]}")
        key = match[0]
    variants = [r[0] for r in db().execute(
        "SELECT DISTINCT supplier_display FROM awards WHERE supplier_key=? ORDER BY 1", (key,))]
    return key, variants, False


def supplier_profile(supplier_name: str, buyer: str | None = None, item_query: str | None = None) -> dict:
    key, variants, natural = resolve_supplier(supplier_name)
    rows = db().execute(f"SELECT {COLUMNS} FROM awards WHERE supplier_key=? ORDER BY award_date", (key,)).fetchall()
    ok = [r for r in rows if r["benchmarkable"]]
    flags: dict[str, int] = {}
    for r in rows:
        for f in filter(None, (r["dq_flags"] or "").split(",")):
            flags[f] = flags.get(f, 0) + 1
    schemes = sorted({r[0] or "(none)" for r in db().execute(
        "SELECT supplier_scheme FROM awards WHERE supplier_key=?", (key,))})
    out: dict = {
        "supplier": variants[0] if natural else max(variants, key=len),
        "pseudonymised": natural,
        "name_variants_merged": [] if natural else variants,
        "identifier_schemes_seen": [] if natural else schemes,
        "awards_total": len(rows),
        "awards_usable": len(ok),
        "value_total_kes": round(sum(r["amount"] for r in ok), 2),
        "buyers": sorted({r["buyer_name"] for r in rows}),
        "first_award": (rows[0]["award_date"] or "")[:10] if rows else None,
        "last_award": (rows[-1]["award_date"] or "")[:10] if rows else None,
        "data_quality_flags": flags,
        "awards_shown": "most recent 8",
        "awards": [_row_out(r) for r in rows[-8:]],
    }
    if natural:
        out["note"] = ("This supplier appears to trade under a natural person's name. It is shown only by "
                       "pseudonym and no personal details are reported.")
    if buyer:
        scope = (find_comparables(item_query, buyer=buyer, min_similarity=60) if item_query else
                 [(r, 100.0) for r in db().execute(
                     f"SELECT {COLUMNS} FROM awards WHERE lower(buyer_name)=lower(?)", (buyer,)).fetchall()])
        scope = [(r, s) for r, s in scope if r["benchmarkable"]]
        mine = [r for r, _ in scope if r["supplier_key"] == key]
        n = len(scope)
        out["concentration"] = {
            "buyer": buyer,
            "scope": item_query or "all items",
            "buyer_awards_in_scope": n,
            "supplier_awards_in_scope": len(mine),
            "share_by_count_pct": round(len(mine) / n * 100, 1) if n else None,
            "share_by_value_pct": round(sum(r["amount"] for r in mine) /
                                        sum(r["amount"] for r, _ in scope) * 100, 1) if n else None,
            "sources_total": len(mine),
            "sources": [citation(r) for r in mine[:20]],
            "note": "A high share is a question for the committee, not evidence of wrongdoing.",
        }
    return out


def resolve_citation(src: dict) -> dict | None:
    r = db().execute(f"SELECT {COLUMNS} FROM awards WHERE ocid=? AND award_id=?",
                     (src.get("ocid"), src.get("award_id"))).fetchone()
    return _row_out(r) if r else None


def dataset_summary() -> dict:
    meta = {r["key"]: r["value"] for r in db().execute("SELECT key, value FROM meta")}
    n, usable = db().execute("SELECT COUNT(*), SUM(benchmarkable) FROM awards").fetchone()
    return {
        "files": json.loads(meta.get("files", "[]")),
        "source_url": meta.get("source_url", ""),
        "ingested_at": meta.get("ingested_at"),
        "award_rows": n,
        "usable_rows": usable,
        "ingest_stats": json.loads(meta.get("stats", "{}")),
    }


def detect_split_awards(buyer: str, item_query: str | None = None, threshold_kes: float | None = None,
                        window_days: int = 60, near_pct: float = 70.0) -> dict:
    """Find possible contract splitting: one supplier, one buyer, similar items, several awards each
    just under a procurement-method threshold, close together, whose sum exceeds the threshold."""
    from datetime import date

    threshold = float(threshold_kes or config.SPLIT_THRESHOLD_KES)
    if item_query:
        rows = [r for r, _ in find_comparables(item_query, buyer=buyer, min_similarity=60)]
    else:
        rows = db().execute(f"SELECT {COLUMNS} FROM awards WHERE lower(buyer_name)=lower(?)", (buyer,)).fetchall()
    if not rows:
        raise StoreError(f"No awards found for buyer '{buyer}'" + (f" and item '{item_query}'." if item_query else "."))
    low = threshold * near_pct / 100
    near = [r for r in rows if r["benchmarkable"] and low <= r["amount"] < threshold and r["award_date"]]
    by_sup: dict[str, list] = {}
    for r in near:
        by_sup.setdefault(r["supplier_key"], []).append(r)
    clusters = []
    for key, rs in by_sup.items():
        rs.sort(key=lambda r: r["award_date"])
        best: list = []
        for i in range(len(rs)):
            d0 = date.fromisoformat(rs[i]["award_date"][:10])
            win = [r for r in rs[i:] if (date.fromisoformat(r["award_date"][:10]) - d0).days <= window_days]
            if len(win) > len(best):
                best = win
        total = sum(r["amount"] for r in best)
        if len(best) >= 2 and total > threshold:
            clusters.append({
                "supplier": best[0]["supplier_display"],
                "awards_in_window": len(best),
                "first": best[0]["award_date"][:10],
                "last": best[-1]["award_date"][:10],
                "sum_kes": round(total, 2),
                "times_threshold": round(total / threshold, 2),
                "titles": sorted({r["title"] for r in best}),
                "sources": [citation(r) for r in best],
            })
    clusters.sort(key=lambda c: -c["awards_in_window"])
    return {
        "buyer": buyer,
        "scope": item_query or "all items",
        "threshold_kes": threshold,
        "window_days": window_days,
        "near_threshold_band": f"{near_pct:.0f}-100% of threshold",
        "awards_scanned": len(rows),
        "clusters": clusters,
        "verdict": "possible_splitting" if clusters else "no_pattern_found",
        "note": ("A cluster is a pattern for the committee to ask about, not proof: legitimate repeat orders "
                 "look the same. The threshold must match the buyer's applicable procurement-method limit."),
    }
