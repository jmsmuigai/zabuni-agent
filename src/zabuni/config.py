"""Central paths and settings. Everything is overridable by environment variable."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.getenv("ZABUNI_ROOT", Path(__file__).resolve().parents[2]))
DB_PATH = Path(os.getenv("ZABUNI_DB", ROOT / "data" / "zabuni.sqlite"))
WORKSPACE = Path(os.getenv("ZABUNI_WORKSPACE", ROOT / "workspace"))
INPUTS = WORKSPACE / "inputs"
DRAFTS = WORKSPACE / "drafts"
OUTBOX = WORKSPACE / "committee_outbox"
RUNS = Path(os.getenv("ZABUNI_RUNS", ROOT / "runs"))

# Shared secret between the human gate (CLI) and the MCP server. The LLM never sees it.
GATE_SECRET = os.getenv("ZABUNI_GATE_SECRET", "change-me-local-dev-only")

# Award values above this (in KES) are treated as data errors and excluded from benchmarks.
# The PPIP registry page documents that the top 1% of values outweigh the rest combined.
EXTREME_VALUE_KES = float(os.getenv("ZABUNI_EXTREME_VALUE_KES", 50_000_000_000))  # KES 50bn

# Procurement-method threshold used by the splitting check. Set it to the limit that applies to
# the buyer (e.g. the request-for-quotation ceiling in its procurement regulations).
SPLIT_THRESHOLD_KES = float(os.getenv("ZABUNI_SPLIT_THRESHOLD_KES", 2_000_000))
CONCENTRATION_PCT = float(os.getenv("ZABUNI_CONCENTRATION_PCT", 40))

MIN_COMPARABLES = int(os.getenv("ZABUNI_MIN_COMPARABLES", 5))
OUTLIER_Z = float(os.getenv("ZABUNI_OUTLIER_Z", 3.5))

for p in (INPUTS, DRAFTS, OUTBOX, RUNS, DB_PATH.parent):
    p.mkdir(parents=True, exist_ok=True)
