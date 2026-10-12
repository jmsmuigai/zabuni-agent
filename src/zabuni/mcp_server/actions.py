"""Write side: findings, the draft report, and the gated filing step.

Rules enforced here, in code, not in the prompt:
* A finding with no source is refused. Each OCDS source must resolve to a real row; each input
  source must quote text that actually appears in the request document.
* Text that awards or recommends awarding a tender is refused. The agent prepares; people decide.
* Filing to the committee outbox needs a valid approval token for the exact draft bytes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

from zabuni import config
from zabuni.mcp_server import gate, store
from zabuni.mcp_server.store import StoreError

FINDING_TYPES = {
    "price_outlier_high", "price_outlier_low", "price_within_range", "insufficient_evidence",
    "budget_overrun", "supplier_concentration", "possible_splitting", "supplier_identity_issue", "data_quality",
    "instruction_in_document", "other",
}
SEVERITIES = ("info", "low", "medium", "high")

AWARD_LANGUAGE = re.compile(
    r"\b(award(ed|ing|s)?\s+(the\s+)?(tender|contract|bid)\s+(is\s+|be\s+)?(given\s+)?to"
    r"|recommend\w*\s+(that\s+)?(the\s+)?(tender|contract|bid)?\s*(should\s+)?(be\s+)?award"
    r"|recommend\w*\s+(an?\s+)?award"
    r"|should\s+be\s+awarded|be\s+awarded\s+to|winning\s+bidder|successful\s+bidder\s+is"
    r"|we\s+award|hereby\s+award|is\s+awarded\s+to)",
    re.IGNORECASE,
)
PERSONAL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|(?:\+?254|0)[17]\d{8}")
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_dir(run_id: str) -> Path:
    if not RUN_ID.match(run_id or ""):
        raise StoreError("run_id must be 4-64 letters, digits, '-' or '_'.")
    d = config.RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lint(text: str, field: str) -> None:
    m = AWARD_LANGUAGE.search(text or "")
    if m:
        raise StoreError(
            f"Refused: {field} contains award-making language ('{m.group(0)}'). This agent prepares the "
            "file; the evaluation committee and accounting officer decide. Describe the evidence instead.")
    if PERSONAL.search(text or ""):
        raise StoreError(f"Refused: {field} contains an e-mail address or phone number. Remove personal details.")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _resolve_input_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = (config.WORKSPACE / p) if not str(p).startswith(str(config.WORKSPACE)) else p
        if not p.exists():
            p = config.INPUTS / Path(path).name
    p = p.resolve()
    if config.INPUTS.resolve() not in p.parents:
        raise StoreError(f"Input sources must be files in {config.INPUTS.name}/ (got {path}).")
    if not p.exists():
        raise StoreError(f"Input source file not found: {path}")
    return p


def validate_source(src: dict) -> dict:
    if not isinstance(src, dict):
        raise StoreError("Each source must be an object.")
    kind = src.get("type")
    if kind == "ocds":
        row = store.resolve_citation(src)
        if not row:
            raise StoreError(f"Source does not resolve: ocid={src.get('ocid')} award_id={src.get('award_id')}. "
                             "Copy the 'source' object from a tool result exactly.")
        return row["source"]
    if kind == "input":
        p = _resolve_input_path(src.get("path", ""))
        quote = src.get("quote", "")
        if len(quote.strip()) < 4:
            raise StoreError("Input sources need a 'quote' of the exact text relied on.")
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, start=1):
            if _norm_ws(quote) in _norm_ws(line):
                return {"type": "input", "path": f"inputs/{p.name}", "line": i, "quote": quote.strip()}
        if _norm_ws(quote) in _norm_ws(" ".join(lines)):
            return {"type": "input", "path": f"inputs/{p.name}", "line": None, "quote": quote.strip()}
        raise StoreError(f"Quote not found in {p.name}: '{quote[:80]}'. Quote the document exactly.")
    raise StoreError("Source type must be 'ocds' (from a tool result) or 'input' (quote from the request file).")


def flag_finding(run_id: str, finding_type: str, severity: str, statement: str, sources: list[dict]) -> dict:
    d = _run_dir(run_id)
    if finding_type not in FINDING_TYPES:
        raise StoreError(f"finding_type must be one of {sorted(FINDING_TYPES)}")
    if severity not in SEVERITIES:
        raise StoreError(f"severity must be one of {SEVERITIES}")
    if finding_type in {"insufficient_evidence", "price_within_range"} and severity not in ("info", "low"):
        raise StoreError(f"A {finding_type} finding cannot be more than 'low' severity.")
    if not statement or len(statement.strip()) < 15:
        raise StoreError("statement must describe the finding in a full sentence.")
    _lint(statement, "statement")
    if not sources:
        raise StoreError("Refused: a finding with no source is worse than no finding. Cite at least one source.")
    resolved = [validate_source(s) for s in sources]
    if finding_type in {"price_outlier_high", "price_outlier_low"} and sum(s["type"] == "ocds" for s in resolved) < 3:
        raise StoreError("A price outlier finding must cite at least 3 comparable awards (type 'ocds').")
    path = d / "findings.jsonl"
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for line in existing:
        prev = json.loads(line)
        if prev["finding_type"] == finding_type and _norm_ws(prev["statement"]) == _norm_ws(statement):
            return {"finding_id": prev["finding_id"], "status": "duplicate_ignored"}
    finding = {
        "finding_id": f"F{len(existing) + 1:02d}",
        "finding_type": finding_type,
        "severity": severity,
        "statement": statement.strip(),
        "sources": resolved,
        "recorded_at": _now(),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(finding) + "\n")
    return {"finding_id": finding["finding_id"], "status": "recorded", "sources_verified": len(resolved)}


def authored_text(draft: str) -> str:
    """The parts of a draft the agent wrote: everything before 'Checks performed', minus the numbered
    source lines (which quote documents verbatim, including any injected text being reported)."""
    body = draft.split("## Checks performed")[0]
    return "\n".join(ln for ln in body.splitlines() if not re.match(r"^\d+\. (OCDS|Request document) ", ln))


def load_findings(run_id: str) -> list[dict]:
    p = _run_dir(run_id) / "findings.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _fmt_source(s: dict) -> str:
    if s["type"] == "ocds":
        row = store.resolve_citation(s) or {}
        what = (f" — KES {row['amount']:,.0f}, {row['buyer']}, {row['supplier']}, {row['award_date']}"
                if row.get("amount") is not None else "")
        return f"OCDS `{s['ocid']}` award `{s['award_id']}` `{s['pointer']}` ({s['file']} line {s['line']}){what}"
    line = f" line {s['line']}" if s.get("line") else ""
    return f"Request document `{s['path']}`{line}: \"{s['quote']}\""


def draft_report(run_id: str, request_path: str, summary: str, checks_performed: list[str],
                 title: str | None = None) -> dict:
    d = _run_dir(run_id)
    _lint(summary, "summary")
    if not checks_performed:
        raise StoreError("List the checks you performed (e.g. ['price_benchmark', 'supplier_profile']).")
    req = _resolve_input_path(request_path)
    findings = load_findings(run_id)
    sev_rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (-sev_rank[f["severity"]], f["finding_id"]))
    ds = store.dataset_summary()
    stats = ds["ingest_stats"]
    synthetic = any("sample" in f or "synth" in f for f in ds["files"])

    lines = [
        f"# {title or 'Value-for-money review file'}",
        "",
        f"**Status: DRAFT — prepared by Zabuni agent for the Tender Evaluation Committee. Not a decision.**",
        "",
        f"- Run: `{run_id}`",
        f"- Request: `inputs/{req.name}`",
        f"- Prepared: {_now()}",
        f"- Data: {', '.join(ds['files'])}" + (" — **SYNTHETIC fixture, not real procurement data**" if synthetic else ""),
        "",
        "## Summary",
        "",
        summary.strip(),
        "",
        "## Findings",
        "",
    ]
    if not findings:
        lines += ["No findings were recorded. The checks below were run and raised nothing that met the "
                  "evidence bar.", ""]
    for f in findings:
        lines += [f"### {f['finding_id']} · {f['finding_type'].replace('_', ' ')} · severity {f['severity']}",
                  "", f["statement"], "", "Sources:"]
        lines += [f"{i}. {_fmt_source(s)}" for i, s in enumerate(f["sources"], start=1)]
        lines.append("")
    lines += [
        "## Checks performed",
        "",
        *[f"- {c}" for c in checks_performed],
        "",
        "## Data coverage and known data problems",
        "",
        f"- Award rows: {ds['award_rows']} (usable for price benchmarks: {ds['usable_rows']})",
        f"- Releases with no award published: {stats.get('releases_without_awards', 0)}",
        f"- Excluded as extreme values (> KES {int(config.EXTREME_VALUE_KES):,}): "
        f"{stats.get('dq:extreme_value', 0)}",
        f"- Supplier identifier schemes invalid or missing: "
        f"{stats.get('dq:supplier_scheme_invalid', 0) + stats.get('dq:supplier_scheme_missing', 0)}",
        f"- Buyer names absent from `parties`: {stats.get('buyer_name_not_in_parties', 0)} "
        f"(recovered by buyer ID: {stats.get('buyer_name_recovered_by_id', 0)})",
        f"- Sole-proprietor suppliers pseudonymised: {stats.get('natural_person_suppliers_pseudonymised', 0)}",
        "",
        "## Method and limits",
        "",
        "- Prices are compared on award totals; the portal publishes no item quantities or unit prices.",
        "- Comparable awards are matched on tender title text and may differ in scope.",
        "- Outliers use a robust z-score of log(amount) against the median and MAD of usable comparables.",
        "- Bid documents are not published, so this file does not evaluate bids.",
        "",
        "## Decision",
        "",
        "This file does not award the tender and makes no award recommendation. Under Kenya's Public "
        "Procurement and Asset Disposal Act, 2015, evaluation sits with the evaluation committee and the "
        "award decision with the accounting officer.",
        "",
        "- Reviewed by: _pending_",
        "- Decision: _pending_",
    ]
    path = config.DRAFTS / f"{run_id}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Machine-readable sidecar for audit tools and dashboards.
    (d / "findings.json").write_text(json.dumps({"run_id": run_id, "request": f"inputs/{req.name}",
                                                 "findings": findings, "dataset": ds}, indent=2), encoding="utf-8")
    return {"report_path": f"drafts/{path.name}", "sha256": gate.sha256_file(path),
            "findings_included": len(findings), "status": "draft_written"}


def file_to_committee(run_id: str, approver: str, approval_token: str, note: str = "") -> dict:
    _run_dir(run_id)
    draft = config.DRAFTS / f"{run_id}.md"
    if not draft.exists():
        raise StoreError("No draft for this run. Call draft_report first.")
    sha = gate.sha256_file(draft)
    if not gate.verify(approval_token, run_id, sha, approver):
        raise StoreError("Refused: approval token invalid for this approver and this exact draft. "
                         "Filing needs a named human's approval at the gate.")
    dest = config.OUTBOX / f"{run_id}.md"
    if dest.exists():
        raise StoreError(f"Already filed: {dest.name}. Filing is one-way; it is never overwritten.")
    _lint(note, "note")
    text = draft.read_text(encoding="utf-8")
    text = text.replace("- Reviewed by: _pending_", f"- Reviewed by: {approver.strip()}")
    text = text.replace("- Decision: _pending_",
                        f"- Decision: approved for submission to the committee at {_now()}"
                        + (f" — note: {note.strip()}" if note.strip() else ""))
    text = text.replace("**Status: DRAFT", "**Status: FILED", 1)
    text += f"\n<!-- draft sha256 {sha}; approval token fingerprint {approval_token[:12]} -->\n"
    dest.write_text(text, encoding="utf-8")
    os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    shutil.copy2(draft, _run_dir(run_id) / "approved_draft.md")
    return {"status": "filed", "path": f"committee_outbox/{dest.name}", "approver": approver.strip(),
            "draft_sha256": sha}
