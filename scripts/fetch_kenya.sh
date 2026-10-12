#!/usr/bin/env bash
# Download Kenya's Public Procurement Information Portal (PPIP) data in OCDS format from the
# Open Contracting Partnership Data Registry, then load it. Publication 147, OCID prefix ocds-5whusi.
#   ./scripts/fetch_kenya.sh 2025        (one year)     ./scripts/fetch_kenya.sh full   (all years, large)
set -euo pipefail
YEAR="${1:-2025}"
URL="https://data.open-contracting.org/en/publication/147/download?name=${YEAR}.jsonl.gz"
OUT="data/kenya_${YEAR}.jsonl.gz"
mkdir -p data
echo "Downloading ${URL}"
curl -fL --retry 3 -o "${OUT}" "${URL}"
echo "Loading ${OUT} (bad rows are kept and flagged, not cleaned away)"
uv run zabuni ingest "${OUT}" --source-url "${URL}"
echo "Done. Try: uv run zabuni replay --n 8   then   uv run zabuni run workspace/inputs/replay_<...>.md"
