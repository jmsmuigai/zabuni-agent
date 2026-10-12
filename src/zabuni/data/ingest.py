"""Load OCDS compiled releases (JSON Lines, optionally gzipped) into SQLite.

Usage:
    python -m zabuni.data.ingest data/kenya_2025.jsonl.gz [more files...] [--db data/zabuni.sqlite]

What it keeps: buyer, tender title/category/method/value, each award x supplier with value.
What it never keeps: `parties[].contactPoint`, any person names, e-mails or phone numbers.
What it does not clean away: bad rows stay in the table with `dq_flags`, so the agent can
report them instead of silently dropping them.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from zabuni import config
from zabuni.data.normalize import (
    check_supplier_identifier,
    looks_like_natural_person,
    normalize_name,
    parse_amount,
    pseudonym,
    strip_contacts,
)

SCHEMA = """
DROP TABLE IF EXISTS awards;
DROP TABLE IF EXISTS awards_fts;
DROP TABLE IF EXISTS meta;
CREATE TABLE awards (
    row_id INTEGER PRIMARY KEY,
    ocid TEXT NOT NULL,
    release_id TEXT,
    release_date TEXT,
    buyer_id TEXT,
    buyer_name TEXT,
    buyer_name_source TEXT,
    tender_id TEXT,
    title TEXT,
    category TEXT,
    method TEXT,
    tender_amount REAL,
    tender_status TEXT,
    award_index INTEGER,
    award_id TEXT,
    award_date TEXT,
    award_status TEXT,
    amount REAL,
    currency TEXT,
    supplier_index INTEGER,
    supplier_id TEXT,
    supplier_scheme TEXT,
    supplier_key TEXT,
    supplier_display TEXT,
    natural_person INTEGER DEFAULT 0,
    dq_flags TEXT,
    benchmarkable INTEGER DEFAULT 1,
    source_file TEXT,
    source_line INTEGER
);
CREATE INDEX idx_awards_ocid ON awards(ocid, award_id);
CREATE INDEX idx_awards_supplier ON awards(supplier_key);
CREATE INDEX idx_awards_buyer ON awards(buyer_name);
CREATE VIRTUAL TABLE awards_fts USING fts5(title, content='awards', content_rowid='row_id', tokenize='porter unicode61');
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

EXCLUDE_FROM_BENCHMARK = {
    "missing_value", "nonpositive_value", "extreme_value", "non_kes_currency", "award_not_active",
}


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _party_names(release: dict) -> dict[str, str]:
    names = {}
    for p in release.get("parties") or []:
        if isinstance(p, dict) and p.get("id") and p.get("name"):
            names[str(p["id"])] = p["name"]
    return names


def _rows_from_release(release: dict, source_file: str, line_no: int, stats: Counter):
    ocid = release.get("ocid")
    if not ocid:
        stats["skipped_no_ocid"] += 1
        return
    parties = _party_names(release)
    buyer = release.get("buyer") or {}
    buyer_id = str(buyer.get("id")) if buyer.get("id") is not None else None
    buyer_name, source = None, "missing"
    if buyer_id and parties.get(buyer_id):
        buyer_name, source = parties[buyer_id], "parties"
    elif buyer.get("name"):
        buyer_name, source = buyer["name"], "buyer"
    if source != "parties":
        stats["buyer_name_not_in_parties"] += 1
    if source == "missing":
        stats["buyer_name_missing"] += 1
    buyer_name = strip_contacts(buyer_name) or f"UNKNOWN BUYER ({ocid})"

    tender = release.get("tender") or {}
    tvalue = tender.get("value") or {}
    awards = release.get("awards") or []
    stats["releases"] += 1
    if not awards:
        stats["releases_without_awards"] += 1
        return

    for ai, award in enumerate(awards):
        if not isinstance(award, dict):
            continue
        value = award.get("value") or {}
        amount = parse_amount(value.get("amount"))
        currency = value.get("currency")
        suppliers = award.get("suppliers") or [{}]
        for si, sup in enumerate(suppliers):
            flags: list[str] = []
            if amount is None:
                flags.append("missing_value")
            elif amount <= 0:
                flags.append("nonpositive_value")
            elif amount > config.EXTREME_VALUE_KES:
                flags.append("extreme_value")
            if not currency:
                flags.append("currency_assumed_KES")
                cur = "KES"
            else:
                cur = currency
                if currency != "KES":
                    flags.append("non_kes_currency")
            status = award.get("status")
            if status and status not in ("active", "pending"):
                flags.append("award_not_active")

            sup_id = sup.get("id")
            ident = (sup.get("identifier") or {}) if isinstance(sup, dict) else {}
            scheme = ident.get("scheme")
            ident_id = ident.get("id") or sup_id
            flags += check_supplier_identifier(scheme, ident_id)

            raw_name = sup.get("name") or (parties.get(str(sup_id)) if sup_id else None)
            if not raw_name:
                flags.append("supplier_name_missing")
            elif sup_id and str(sup_id) not in parties:
                flags.append("supplier_name_not_in_parties")
            raw_name = strip_contacts(raw_name)
            key = normalize_name(raw_name) or f"unknown-{sup_id or ocid}"
            natural = looks_like_natural_person(raw_name)
            if natural:
                key = pseudonym(key)
                display = key
                sup_id = None  # an ID can identify the person too
                ident_id = None
                stats["natural_person_suppliers_pseudonymised"] += 1
            else:
                display = raw_name or "UNKNOWN SUPPLIER"

            for f in flags:
                stats[f"dq:{f}"] += 1
            benchmarkable = int(not (set(flags) & EXCLUDE_FROM_BENCHMARK))
            yield (
                ocid, release.get("id"), release.get("date"), buyer_id, buyer_name, source,
                tender.get("id"), strip_contacts(tender.get("title")) or "",
                tender.get("mainProcurementCategory"), tender.get("procurementMethod"),
                parse_amount(tvalue.get("amount")), tender.get("status"),
                ai, str(award.get("id")) if award.get("id") is not None else f"{ocid}-award-{ai}",
                award.get("date"), status, amount, cur,
                si, str(ident_id) if ident_id else None, scheme, key, display, int(natural),
                ",".join(sorted(set(flags))), benchmarkable, source_file, line_no,
            )
            stats["award_rows"] += 1


def ingest(files: list[Path], db_path: Path = config.DB_PATH, source_url: str = "") -> dict:
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    stats: Counter = Counter()
    insert = (
        "INSERT INTO awards (ocid, release_id, release_date, buyer_id, buyer_name, buyer_name_source,"
        " tender_id, title, category, method, tender_amount, tender_status, award_index, award_id,"
        " award_date, award_status, amount, currency, supplier_index, supplier_id, supplier_scheme,"
        " supplier_key, supplier_display, natural_person, dq_flags, benchmarkable, source_file, source_line)"
        " VALUES (" + ",".join(["?"] * 28) + ")"
    )
    for path in files:
        batch = []
        with _open(path) as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    stats["bad_json_lines"] += 1
                    continue
                if "compiledRelease" in obj:
                    obj = obj["compiledRelease"]
                batch.extend(_rows_from_release(obj, path.name, line_no, stats))
                if len(batch) >= 5000:
                    con.executemany(insert, batch)
                    batch.clear()
        con.executemany(insert, batch)
    # Recover missing buyer names from other releases carrying the same buyer.id.
    cur = con.execute(
        """UPDATE awards SET
               buyer_name = (SELECT a2.buyer_name FROM awards a2
                             WHERE a2.buyer_id = awards.buyer_id AND a2.buyer_name_source != 'missing'
                             GROUP BY a2.buyer_name ORDER BY COUNT(*) DESC LIMIT 1),
               buyer_name_source = 'recovered_by_id'
           WHERE buyer_name_source = 'missing' AND buyer_id IS NOT NULL
             AND EXISTS (SELECT 1 FROM awards a3 WHERE a3.buyer_id = awards.buyer_id
                         AND a3.buyer_name_source != 'missing')"""
    )
    stats["buyer_name_recovered_by_id"] = cur.rowcount
    con.execute("INSERT INTO awards_fts(awards_fts) VALUES ('rebuild')")
    meta = {
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": json.dumps([p.name for p in files]),
        "source_url": source_url,
        "stats": json.dumps(dict(stats), sort_keys=True),
        "extreme_value_kes": str(config.EXTREME_VALUE_KES),
    }
    con.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    con.commit()
    con.close()
    return dict(stats)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--source-url", default="")
    args = ap.parse_args(argv)
    missing = [f for f in args.files if not f.exists()]
    if missing:
        sys.exit(f"Not found: {', '.join(map(str, missing))}")
    stats = ingest(args.files, args.db, args.source_url)
    print(json.dumps(stats, indent=2, sort_keys=True))
    print(f"Wrote {args.db}")


if __name__ == "__main__":
    main()
