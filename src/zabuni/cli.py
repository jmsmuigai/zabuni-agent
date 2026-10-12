"""zabuni — command line.

  zabuni doctor                       check database, Ollama, model and npx
  zabuni data                         build the SYNTHETIC sample database
  zabuni ingest FILE.jsonl.gz ...     load real OCDS files (e.g. Kenya PPIP) into the database
  zabuni run inputs/req_001.md        run the agent on one review request (stops at the human gate)
  zabuni replay --n 8                 write requests from completed past awards (real-data replay)
  zabuni eval                         run the evaluation suite (see EVALS.md)
  zabuni serve                        run the Zabuni MCP server on stdio for any MCP client
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from zabuni import config

B, D, G, R, Y, C, X = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m"
if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
    B = D = G = R = Y = C = X = ""


def cmd_data(_args) -> None:
    from zabuni.data import ingest, synth

    out = config.ROOT / "data" / "sample_ocds.jsonl.gz"
    synth.main([str(out)])
    stats = ingest.ingest([out], config.DB_PATH, source_url="synthetic fixture (zabuni.data.synth)")
    print(json.dumps(stats, indent=2, sort_keys=True))
    print(f"{G}Database ready:{X} {config.DB_PATH}")


def cmd_ingest(args) -> None:
    from zabuni.data import ingest

    ingest.main([*map(str, args.files), "--db", str(config.DB_PATH), "--source-url", args.source_url])


def cmd_doctor(args) -> int:
    ok = True

    def line(good: bool, text: str, fix: str = ""):
        nonlocal ok
        ok &= good
        print(f"  {G + '✓' if good else R + '✗'}{X} {text}" + (f"\n      {D}{fix}{X}" if not good and fix else ""))

    print(f"{B}Zabuni environment check{X}")
    line(config.DB_PATH.exists(), f"database {config.DB_PATH}", "run: zabuni data")
    line(shutil.which("npx") is not None, "npx (Node.js) for the borrowed filesystem MCP server", "install Node.js 20+")
    if args.provider == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        try:
            with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as r:
                models = [m["name"] for m in json.load(r).get("models", [])]
            line(True, f"Ollama reachable at {host}")
            from zabuni.agent.llm import DEFAULTS
            want = args.model or DEFAULTS["ollama"]
            have = any(m == want or m.split(":")[0] == want or m == f"{want}:latest" for m in models)
            line(have, f"model {want} pulled", f"run: ollama pull {want}")
        except OSError:
            line(False, f"Ollama reachable at {host}", "install from https://ollama.com then: ollama serve")
    return 0 if ok else 1


def _print_gate(payload: dict) -> None:
    rep = payload.get("report") or {}
    print(f"\n{B}{Y}═══ HUMAN GATE — the agent has stopped ═══{X}")
    print(f"Draft: workspace/{rep.get('path')}  (sha256 {str(rep.get('sha256'))[:16]}…)")
    for f in payload.get("findings", []):
        sev = {"high": R, "medium": Y}.get(f["severity"], D)
        print(f"  {sev}{f['id']} [{f['severity']}] {f['type']}{X}: {f['statement'][:160]} {D}({f['sources']} sources){X}")
    if not payload.get("findings"):
        print(f"  {D}(no findings recorded){X}")
    for p in payload.get("unresolved_self_check_problems", []):
        print(f"  {R}self-check unresolved:{X} {p}")
    print(f"{D}The agent never awards. A named person decides whether this file goes to the committee.{X}")


async def run_request(request: str, provider: str = "ollama", model: str | None = None,
                      approver: str | None = None, decision: str | None = None,
                      run_id: str | None = None, interactive: bool = True) -> dict:
    from langgraph.types import Command

    from zabuni.agent.graph import Zabuni
    from zabuni.agent.llm import make_llm

    req = Path(request)
    if not req.exists() and (config.INPUTS / req.name).exists():
        req = config.INPUTS / req.name
    if not req.exists():
        raise SystemExit(f"Request file not found: {request}")
    if config.INPUTS.resolve() not in req.resolve().parents:
        dest = config.INPUTS / req.name
        shutil.copy(req, dest)
        req = dest
    llm, model_name = make_llm(provider, model)
    run_id = run_id or f"{req.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"{B}Zabuni{X} run {C}{run_id}{X} · {provider}:{model_name} · request {req.name}")
    async with Zabuni(llm, model_name, provider, run_id) as z:
        cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": 120}
        state = await z.app.ainvoke({"run_id": run_id, "request_path": str(req)}, cfg)
        if "__interrupt__" in state:
            payload = state["__interrupt__"][0].value
            _print_gate(payload)
            if decision is None and interactive and sys.stdin.isatty():
                approver = input(f"{B}Your full name (approver):{X} ").strip()
                decision = input(f"{B}Decision [approve / reject / hold]:{X} ").strip().lower() or "hold"
                note = input("Note for the committee (optional): ").strip()
            else:
                note = ""
                decision = decision or "hold"
            state = await z.app.ainvoke(Command(resume={"approver": approver or "", "decision": decision,
                                                         "note": note}), cfg)
        status = state.get("status") or {"approve": "filed", "reject": "returned_by_reviewer"}.get(
            (state.get("decision") or {}).get("decision"), "held_at_gate" if state.get("report") else "no_draft")
        summary = z.log.summary(status=status, report=state.get("report"), filed=state.get("filed"),
                                decision=state.get("decision"), problems=state.get("problems", []))
    colour = G if status == "filed" else Y
    print(f"\n{colour}{B}Status: {status}{X}")
    if state.get("filed"):
        print(f"Filed: workspace/{state['filed'].get('path')}")
    print(f"{D}{summary['llm_calls']} model calls · {summary['tool_calls']} tool calls "
          f"({summary['tool_errors']} errors) · {summary['input_tokens'] + summary['output_tokens']} tokens · "
          f"{summary['seconds']}s · API cost ${summary['api_cost_usd']}{X}")
    print(f"{D}Audit log: runs/{run_id}/audit.jsonl{X}")
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="zabuni", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("data", help="build the synthetic sample database")
    p = sub.add_parser("ingest", help="load OCDS .jsonl / .jsonl.gz files")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--source-url", default="")
    p = sub.add_parser("doctor", help="check the environment")
    p.add_argument("--provider", default=os.getenv("ZABUNI_PROVIDER", "ollama"))
    p.add_argument("--model")
    p = sub.add_parser("run", help="run the agent on one request file")
    p.add_argument("request")
    p.add_argument("--provider", default=os.getenv("ZABUNI_PROVIDER", "ollama"), choices=["ollama", "anthropic", "scripted"])
    p.add_argument("--model")
    p.add_argument("--approver", help="name of the person deciding at the gate (otherwise asked interactively)")
    p.add_argument("--decision", choices=["approve", "reject", "hold"])
    p.add_argument("--run-id")
    p = sub.add_parser("eval", help="run the evaluation suite")
    p.add_argument("--provider", default=os.getenv("ZABUNI_PROVIDER", "ollama"), choices=["ollama", "anthropic", "scripted"])
    p.add_argument("--model")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--only", nargs="*")
    p = sub.add_parser("replay", help="write review requests from completed historical awards (real-data tests)")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--max-year", type=int, default=2024)
    sub.add_parser("serve", help="run the Zabuni MCP server on stdio")
    args = ap.parse_args(argv)

    if args.cmd == "data":
        cmd_data(args)
    elif args.cmd == "ingest":
        cmd_ingest(args)
    elif args.cmd == "doctor":
        sys.exit(cmd_doctor(args))
    elif args.cmd == "run":
        asyncio.run(run_request(args.request, args.provider, args.model, args.approver, args.decision, args.run_id))
    elif args.cmd == "eval":
        from zabuni.evals import run_evals

        asyncio.run(run_evals.main(args.provider, args.model, args.repeats, args.only))
    elif args.cmd == "replay":
        from zabuni.replay import make

        for name in make(args.n, args.max_year):
            print(f"workspace/inputs/{name}")
    elif args.cmd == "serve":
        from zabuni.mcp_server.server import main as serve

        serve()


if __name__ == "__main__":
    main()
