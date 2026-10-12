"""Zabuni MCP server: value-for-money tools over OCDS award data.

Tools (read):   search_awards, price_benchmark, supplier_profile, detect_split_awards
Tools (write):  flag_finding, draft_report
Tool (gated):   file_to_committee  — irreversible; needs a human approval token

Run standalone (stdio):  zabuni-mcp      or   python -m zabuni.mcp_server.server
Any MCP client can use it; nothing here depends on the Zabuni orchestrator.
"""
from __future__ import annotations

import functools
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from zabuni import config
from zabuni.mcp_server import actions, store

mcp = FastMCP(
    "zabuni",
    log_level="WARNING",
    instructions=(
        "Value-for-money tools for public tenders, over Open Contracting (OCDS) award data. "
        "Every finding must cite sources copied from tool results. These tools prepare a file for a "
        "human committee; they never award a tender."
    ),
)


def _audit(fn):
    """Server-side audit line for every call (the orchestrator keeps its own client-side log too)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.time()
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "tool": fn.__name__,
               "args": {k: v for k, v in kwargs.items() if k != "approval_token"}}
        if "approval_token" in kwargs:
            rec["args"]["approval_token_fp"] = (kwargs["approval_token"] or "")[:12]
        try:
            out = fn(*args, **kwargs)
            rec.update(ok=True, result_sha256=hashlib.sha256(json.dumps(out, default=str).encode()).hexdigest())
            return out
        except Exception as e:  # noqa: BLE001 - logged then re-raised to the client as a tool error
            rec.update(ok=False, error=str(e))
            raise
        finally:
            rec["ms"] = round((time.time() - start) * 1000, 1)
            with (config.RUNS / "server_audit.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")

    return wrapper


class Source(BaseModel):
    """A citation. For OCDS rows, copy the `source` object from a tool result unchanged."""

    type: Literal["ocds", "input"] = Field(description="'ocds' for an award row, 'input' for the request file")
    ocid: Optional[str] = Field(None, description="OCDS contracting process ID (type ocds)")
    award_id: Optional[str] = Field(None, description="Award ID (type ocds)")
    pointer: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    path: Optional[str] = Field(None, description="Request file, e.g. inputs/req_001.md (type input)")
    quote: Optional[str] = Field(None, description="Exact text from the request file (type input)")


@mcp.tool()
@_audit
def search_awards(query: str, category: Optional[str] = None, buyer: Optional[str] = None,
                  year_from: Optional[int] = None, year_to: Optional[int] = None, limit: int = 15) -> dict:
    """Find past published awards whose tender title matches an item, e.g. 'maize seed'.

    Returns awards with amount, buyer, supplier, data-quality flags and a `source` citation.
    category: goods | works | services. buyer: exact buyer name to restrict to one institution.
    """
    return store.search_awards(query, category, buyer, year_from, year_to, limit)


@mcp.tool()
@_audit
def price_benchmark(item_query: str, proposed_amount: float, category: Optional[str] = None,
                    budget_amount: Optional[float] = None, exclude_ocid: Optional[str] = None) -> dict:
    """Compare a proposed award amount (KES) with past awards for similar items.

    Returns verdict (within_range | high_outlier | low_outlier | insufficient_comparables), median,
    quartiles, robust z-score, the cited comparables used, and rows excluded as data errors.
    If budget_amount is given, also returns the budget variance. Never flag price when the verdict
    is insufficient_comparables.
    """
    return store.price_benchmark(item_query, proposed_amount, category, exclude_ocid, budget_amount)


@mcp.tool()
@_audit
def supplier_profile(supplier_name: str, buyer: Optional[str] = None, item_query: Optional[str] = None) -> dict:
    """Award history of one supplier: name variants merged, identifier problems, buyers, totals.

    With buyer (and optionally item_query), also returns the supplier's share of that buyer's awards
    in scope, with citations. Suppliers trading under a person's name are pseudonymised.
    """
    return store.supplier_profile(supplier_name, buyer, item_query)


@mcp.tool()
@_audit
def detect_split_awards(buyer: str, item_query: Optional[str] = None, threshold_kes: Optional[float] = None,
                        window_days: int = 60) -> dict:
    """Look for possible contract splitting at one buyer: the same supplier winning several awards,
    each just under a procurement-method threshold (default KES 2m), within window_days, summing above it.

    Returns clusters with cited awards. A cluster is a question for the committee, not proof.
    """
    return store.detect_split_awards(buyer, item_query, threshold_kes, window_days)


@mcp.tool()
@_audit
def flag_finding(run_id: str, finding_type: str, severity: str, statement: str, sources: list[Source]) -> dict:
    """Record one finding for the committee file. Writes to the run's findings log.

    finding_type: price_outlier_high | price_outlier_low | price_within_range | insufficient_evidence |
    budget_overrun | supplier_concentration | possible_splitting | supplier_identity_issue | data_quality |
    instruction_in_document | other.  severity: info | low | medium | high.
    Refused if any source does not resolve, if there is no source, or if the statement awards or
    recommends awarding the tender. Price outliers need at least 3 cited comparables.
    """
    return actions.flag_finding(run_id, finding_type, severity, statement,
                                [s.model_dump(exclude_none=True) for s in sources])


@mcp.tool()
@_audit
def draft_report(run_id: str, request_path: str, summary: str, checks_performed: list[str],
                 title: Optional[str] = None) -> dict:
    """Write the draft committee file (Markdown) from this run's recorded findings.

    summary: 3-6 sentences of evidence, no award recommendation. Returns the draft path and its
    sha256. Safe to call again; it overwrites the draft (not the filed copy).
    """
    return actions.draft_report(run_id, request_path, summary, checks_performed, title)


@mcp.tool()
@_audit
def file_to_committee(run_id: str, approver: str, approval_token: str, note: str = "") -> dict:
    """IRREVERSIBLE. File the approved draft into the committee outbox (read-only, never overwritten).

    Requires an approval token minted at the human gate for this approver and this exact draft.
    """
    return actions.file_to_committee(run_id, approver, approval_token, note)


@mcp.resource("zabuni://dataset")
def dataset() -> str:
    """Which OCDS files are loaded, row counts, and the data problems found at ingest."""
    return json.dumps(store.dataset_summary(), indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
