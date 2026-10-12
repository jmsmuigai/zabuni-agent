"""Whole pipeline over real MCP stdio sessions (own server + borrowed filesystem server), with the
scripted policy standing in for the model. Proves plumbing, logging, self-check, gate and filing."""
import json
import shutil

import pytest

from zabuni import config

pytestmark = pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node.js for the filesystem server")


async def test_mcp_server_exposes_tools():
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from zabuni.agent.graph import mcp_connections
    client = MultiServerMCPClient({"zabuni": mcp_connections()["zabuni"]})
    names = {t.name for t in await client.get_tools()}
    assert {"search_awards", "price_benchmark", "supplier_profile", "detect_split_awards",
            "flag_finding", "draft_report", "file_to_committee"} <= names


async def test_run_holds_at_gate_and_logs_everything():
    from zabuni.cli import run_request
    s = await run_request("req_008_split_quotations.md", "scripted", decision="hold", run_id="p-hold", interactive=False)
    assert s["status"] == "held_at_gate"
    log = [json.loads(x) for x in (config.RUNS / "p-hold" / "audit.jsonl").read_text().splitlines()]
    tools = [r for r in log if r["kind"] == "tool"]
    assert len(tools) == s["tool_calls"] and all({"started", "ms", "args", "ok"} <= r.keys() for r in tools)
    assert any(r["server"] == "filesystem" for r in tools)  # borrowed server used and logged
    assert any(r["kind"] == "gate_decision" and r["decision"] == "hold" for r in log)
    assert not (config.OUTBOX / "p-hold.md").exists()
    findings = (config.RUNS / "p-hold" / "findings.jsonl").read_text()
    assert "possible_splitting" in findings


async def test_run_files_only_after_named_approval():
    from zabuni.cli import run_request
    s = await run_request("req_002_maize_overpriced.md", "scripted", approver="Amina Hassan", decision="approve",
                          run_id="p-approve", interactive=False)
    assert s["status"] == "filed"
    assert "Reviewed by: Amina Hassan" in (config.OUTBOX / "p-approve.md").read_text()


async def test_approve_without_name_does_not_file():
    from zabuni.cli import run_request
    s = await run_request("req_001_maize_clean.md", "scripted", approver="", decision="approve",
                          run_id="p-noname", interactive=False)
    assert s["status"] != "filed" and not (config.OUTBOX / "p-noname.md").exists()
