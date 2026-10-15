"""Build docs/index.html: a public, no-install replay of real recorded Zabuni runs.

    uv run zabuni run workspace/inputs/req_002_maize_overpriced.md --provider scripted \
        --approver "Your Name" --decision approve --run-id demo-002_maize_overpriced
    ...
    python scripts/build_demo_page.py demo-002_maize_overpriced demo-008_split_quotations demo-007_injection

Everything shown comes from the run's own files: the request memo, runs/<run>/audit.jsonl,
runs/<run>/summary.json and the filed report. Nothing is typed by hand.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PREFIX = str(ROOT) + "/"

TITLES = {
    "demo-002_maize_overpriced": ("Overpriced maize seed", "A price 4.8× the median of 192 comparable awards is flagged high, with every source cited."),
    "demo-008_split_quotations": ("Contract splitting", "Four awards to one supplier, each just under the KES 2 million quotation threshold, are detected."),
    "demo-007_injection": ("Prompt injection in the request", "An instruction hidden in the memo is reported as a finding, not obeyed."),
}


def clean(obj):
    if isinstance(obj, str):
        return obj.replace(PREFIX, "")
    if isinstance(obj, list):
        return [clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    return obj


def load_run(run_id: str) -> dict:
    run_dir = ROOT / "runs" / run_id
    events = [json.loads(line) for line in (run_dir / "audit.jsonl").read_text().splitlines() if line.strip()]
    summary = json.loads((run_dir / "summary.json").read_text())
    steps, request_path = [], None
    seen_gate = False
    for e in events:
        k = e["kind"]
        if k == "tool":
            if e["tool"] == "read_text_file" and request_path is None:
                request_path = e["args"].get("path", "")
            steps.append({"type": "tool", "server": e["server"], "tool": e["tool"], "args": e["args"],
                          "ms": e["ms"], "ok": e["ok"], "excerpt": (e.get("output_excerpt") or "")[:1200]})
        elif k == "plan":
            steps.append({"type": "plan", "plan": e["plan"]})
        elif k == "verify":
            steps.append({"type": "verify", "round": e["round"], "problems": e["problems"], "findings": e["findings"]})
        elif k == "gate_opened" and not seen_gate:
            seen_gate = True
            p = e["payload"]
            steps.append({"type": "gate", "sha256": p["report"]["sha256"], "findings": p["findings"]})
        elif k == "gate_decision" or ("approver" in e and "decision" in e):
            steps.append({"type": "decision", "approver": e["approver"], "decision": e["decision"]})
    request_md = (ROOT / request_path).read_text() if request_path and (ROOT / request_path).exists() else ""
    filed = summary.get("filed") or {}
    report_md = ""
    if filed.get("path"):
        report_md = (ROOT / "workspace" / filed["path"]).read_text()
    title, blurb = TITLES.get(run_id, (run_id, ""))
    try:  # pre-render so the page needs no CDN; pip install markdown
        import markdown
        report_html = markdown.markdown(report_md, extensions=["extra"])
    except ImportError:
        report_html = ""
    return clean({"run_id": run_id, "title": title, "blurb": blurb, "request": request_md,
                  "steps": steps, "summary": summary, "report": report_md, "report_html": report_html})


def main(run_ids: list[str]) -> None:
    runs = [load_run(r) for r in run_ids]
    data = json.dumps(runs, ensure_ascii=False)
    (DOCS / "demo").mkdir(parents=True, exist_ok=True)
    (DOCS / "demo" / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1))
    html = (DOCS / "demo" / "template.html").read_text().replace("/*__RUNS__*/[]", data.replace("</", "<\\/"))
    (DOCS / "index.html").write_text(html)
    print(f"wrote docs/index.html with {len(runs)} runs")


if __name__ == "__main__":
    main(sys.argv[1:] or list(TITLES))
