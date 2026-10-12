"""Make review requests from COMPLETED historical awards in the loaded data (real-data replay).

    zabuni replay --n 8 --max-year 2024

Each request reproduces a past award (buyer, item, supplier, amount) and names its OCID so the
benchmark excludes the award itself. These are finished contracting processes from published
open data, never live tenders. Sole proprietors are skipped so no individual is reviewed.
"""
from __future__ import annotations

import random
import re

from zabuni import config
from zabuni.mcp_server.store import db

TEMPLATE = """# Value-for-money review request (historical replay)

> HISTORICAL REPLAY of a completed award from published OCDS data ({file}, line {line}).
> Not a live tender. Used to test the reviewer against real data.

Procuring entity: {buyer}
Historical OCID: {ocid}
Item: {title}
Category: {category}
Recommended supplier: {supplier}
Proposed award amount: KES {amount:,.0f}

## Request

Review this award as if before the committee met: compare the amount with other published awards
for similar items, and check the supplier's award history with this buyer.
"""


def make(n: int = 8, max_year: int = 2024, seed: int = 7) -> list[str]:
    rows = db().execute(
        "SELECT ocid, title, category, buyer_name, supplier_display, amount, source_file, source_line FROM awards "
        "WHERE benchmarkable=1 AND natural_person=0 AND length(title) > 15 AND buyer_name NOT LIKE 'UNKNOWN%' "
        "AND substr(award_date,1,4) <= ? ORDER BY row_id", (str(max_year),)).fetchall()
    if not rows:
        raise SystemExit("No eligible completed awards in the database. Load data first (make kenya / make data).")
    picks = random.Random(seed).sample(rows, min(n, len(rows)))
    written = []
    for r in picks:
        name = f"replay_{re.sub(r'[^A-Za-z0-9]+', '-', r['ocid'])[-40:]}.md"
        (config.INPUTS / name).write_text(TEMPLATE.format(
            file=r["source_file"], line=r["source_line"], buyer=r["buyer_name"], ocid=r["ocid"],
            title=re.sub(r"\s+", " ", r["title"]).strip(), category=r["category"] or "unknown",
            supplier=r["supplier_display"], amount=r["amount"]), encoding="utf-8")
        written.append(name)
    return written
