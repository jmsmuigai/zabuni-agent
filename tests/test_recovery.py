"""Failure handling: a model that misbehaves on purpose. The graph must recover and stay safe."""
import json
import shutil

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from zabuni import config
from zabuni.agent.audit import read_log
from zabuni.agent.scripted import ScriptedModel

pytestmark = pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node.js")


class ChaoticModel(ScriptedModel):
    """Breaks the planner once, calls a forbidden tool, sends string-typed args and a wrong run_id."""
    turn: int = 0

    def _next(self, messages):
        system = messages[0].content if isinstance(messages[0], SystemMessage) else ""
        self.turn += 1
        if "planner prompt" in system and self.turn == 1:
            return AIMessage("Sure! Here is my plan: check the price.")  # not JSON
        if "planner prompt" not in system and self.turn == 3:
            return AIMessage("", tool_calls=[
                {"id": "bad1", "name": "file_to_committee", "args": {"run_id": "x", "approver": "me", "approval_token": "x"}},
                {"id": "bad2", "name": "price_benchmark", "args": {"item_query": "supply of", "proposed_amount": "KES 19,800,000"}},
            ])
        msg = super()._next(messages)
        for c in msg.tool_calls:
            if c["name"] == "flag_finding":
                c["args"]["run_id"] = "someone-elses-run"
                c["args"]["sources"] = json.dumps(c["args"]["sources"])
        return msg


async def test_recovers_and_never_files(monkeypatch):
    import zabuni.agent.llm as llm_mod
    from zabuni.cli import run_request
    monkeypatch.setattr(llm_mod, "make_llm", lambda p, m=None: (ChaoticModel(), "chaotic-test"))
    s = await run_request("req_002_maize_overpriced.md", "scripted", decision="hold", run_id="r-chaos", interactive=False)
    log = read_log("r-chaos")
    what = {r["what"] for r in log if r["kind"] == "recovery"}
    assert {"planner_retry", "tool_error_returned_to_model", "run_id_corrected", "arguments_repaired"} <= what
    assert any(r["kind"] == "tool_refused" and r["tool"] == "file_to_committee" for r in log)
    assert s["status"] == "held_at_gate"
    assert "price_outlier_high" in (config.RUNS / "r-chaos" / "findings.jsonl").read_text()
    assert not (config.RUNS / "someone-elses-run").exists()
