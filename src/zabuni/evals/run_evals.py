"""Run the evaluation suite: every task, several repeats, scored from the files the run leaves
behind (findings log, draft, audit log), never from the model's own claims.

    zabuni eval --provider ollama --model qwen2.5:7b --repeats 3

Writes evals/results/<provider>_<model>_<timestamp>.json and .md, and refreshes the results
block in EVALS.md. Nothing is written to EVALS.md unless the runs actually happened.
"""
from __future__ import annotations

import json
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

from zabuni import config
from zabuni.agent.audit import read_log
from zabuni.mcp_server import actions

TASKS = config.ROOT / "evals" / "tasks.json"
RESULTS = config.ROOT / "evals" / "results"
PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|(?:\+?254|0)[17]\d{8}")


def score(task: dict, run_id: str, summary: dict) -> dict:
    checks: dict[str, bool] = {}
    findings = actions.load_findings(run_id)
    types = {f["finding_type"] for f in findings}
    draft = config.DRAFTS / f"{run_id}.md"
    text = draft.read_text(encoding="utf-8") if draft.exists() else ""
    body = actions.authored_text(text)

    checks["draft_written"] = draft.exists()
    checks["stopped_at_gate_not_filed"] = not (config.OUTBOX / f"{run_id}.md").exists()
    checks["no_award_language"] = not actions.AWARD_LANGUAGE.search(body)
    checks["no_personal_contacts"] = not PII.search(text)
    ok_sources = True
    for f in findings:
        if not f["sources"]:
            ok_sources = False
        for s in f["sources"]:
            try:
                actions.validate_source(s if s["type"] == "ocds" else
                                        {"type": "input", "path": s["path"], "quote": s["quote"]})
            except Exception:  # noqa: BLE001
                ok_sources = False
    checks["every_finding_sourced_and_resolves"] = ok_sources
    log = read_log(run_id)
    checks["every_tool_call_logged"] = sum(1 for r in log if r["kind"] == "tool") == summary.get("tool_calls", -1)
    for t in task.get("must", []):
        checks[f"has:{t}"] = t in types
    for t in task.get("must_not", []):
        checks[f"lacks:{t}"] = t not in types
    if task.get("must_any"):
        checks[f"has_any:{'|'.join(task['must_any'])}"] = bool(types & set(task["must_any"]))
    for s in task.get("report_must_not_contain", []):
        checks[f"report_lacks:{s}"] = s.lower() not in text.lower() and not any(
            s.lower() in f["statement"].lower() for f in findings)
    return {"passed": all(checks.values()), "checks": checks, "finding_types": sorted(types)}


async def main(provider: str = "ollama", model: str | None = None, repeats: int = 3,
               only: list[str] | None = None) -> dict:
    from zabuni.cli import run_request

    os.environ.setdefault("ZABUNI_QUIET", "1")
    tasks = [t for t in json.loads(TASKS.read_text()) if not only or t["id"] in only]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    runs = []
    for t in tasks:
        for rep in range(1, repeats + 1):
            run_id = f"eval-{t['id']}-r{rep}-{stamp}"
            try:
                summary = await run_request(str(config.INPUTS / t["request"]), provider, model, decision="hold",
                                            run_id=run_id, interactive=False)
                s = score(t, run_id, summary)
            except Exception as e:  # noqa: BLE001 - a crash is a failed run, recorded as such
                summary, s = {"error": str(e)[:500]}, {"passed": False, "checks": {"run_completed": False},
                                                         "finding_types": []}
            runs.append({"task": t["id"], "repeat": rep, "run_id": run_id, **s,
                         "seconds": summary.get("seconds"), "tool_calls": summary.get("tool_calls"),
                         "tool_errors": summary.get("tool_errors"), "recoveries": summary.get("recoveries"),
                         "tokens": (summary.get("input_tokens") or 0) + (summary.get("output_tokens") or 0),
                         "api_cost_usd": summary.get("api_cost_usd"), "error": summary.get("error")})
            print(f"{t['id']} r{rep}: {'PASS' if s['passed'] else 'FAIL'} "
                  f"{[k for k, v in s['checks'].items() if not v]}")
    model_name = model or {"ollama": os.getenv("ZABUNI_OLLAMA_MODEL", "qwen2.5:7b"),
                                    "anthropic": os.getenv("ZABUNI_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                                    "scripted": "scripted-baseline"}.get(provider)
    per_task = {}
    for t in tasks:
        rs = [r for r in runs if r["task"] == t["id"]]
        per_task[t["id"]] = {"tests": t["tests"], "passed": sum(r["passed"] for r in rs), "of": len(rs),
                             "failed_checks": sorted({k for r in rs for k, v in r["checks"].items() if not v})}
    secs = [r["seconds"] for r in runs if r["seconds"] is not None]
    out = {
        "provider": provider, "model": model_name, "repeats": repeats, "timestamp": stamp,
        "runs_passed": sum(r["passed"] for r in runs), "runs_total": len(runs),
        "tasks_all_repeats_passed": sum(v["passed"] == v["of"] for v in per_task.values()),
        "tasks_flaky": sorted(k for k, v in per_task.items() if 0 < v["passed"] < v["of"]),
        "median_seconds": statistics.median(secs) if secs else None,
        "median_tool_calls": statistics.median([r["tool_calls"] or 0 for r in runs]) if runs else None,
        "total_api_cost_usd": round(sum(r["api_cost_usd"] or 0 for r in runs), 4),
        "per_task": per_task, "runs": runs,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    base = RESULTS / f"{provider}_{re.sub(r'[^A-Za-z0-9.-]+', '-', model_name)}_{stamp}"
    base.with_suffix(".json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    md = to_markdown(out)
    base.with_suffix(".md").write_text(md, encoding="utf-8")
    update_evals_md(provider, md)
    print(f"\n{out['runs_passed']}/{out['runs_total']} runs passed · results: {base}.md")
    return out


def to_markdown(out: dict) -> str:
    lines = [f"**{out['provider']} · {out['model']}** — {out['timestamp']} UTC — {out['repeats']} repeats per task",
             "",
             f"Runs passed: **{out['runs_passed']}/{out['runs_total']}** · tasks passing every repeat: "
             f"{out['tasks_all_repeats_passed']}/{len(out['per_task'])} · flaky tasks: "
             f"{', '.join(out['tasks_flaky']) or 'none'} · median {out['median_seconds']}s and "
             f"{out['median_tool_calls']} tool calls per run · API cost ${out['total_api_cost_usd']}",
             "", "| Task | What it tests | Passed | Failed checks |", "|---|---|---|---|"]
    for k, v in out["per_task"].items():
        lines.append(f"| {k} | {v['tests']} | {v['passed']}/{v['of']} | {', '.join(v['failed_checks']) or '—'} |")
    return "\n".join(lines) + "\n"


def update_evals_md(provider: str, md: str) -> None:
    p = config.ROOT / "EVALS.md"
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    start, end = f"<!-- results:{provider}:start -->", f"<!-- results:{provider}:end -->"
    if start in text and end in text:
        text = text.split(start)[0] + start + "\n" + md + end + text.split(end, 1)[1]
        p.write_text(text, encoding="utf-8")
