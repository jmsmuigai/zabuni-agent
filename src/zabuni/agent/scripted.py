"""A scripted, rule-based stand-in for the model. NOT an LLM.

Used for two honest purposes only:
1. Integration tests and `make demo-offline`: proves the whole pipeline (both MCP servers over
   stdio, audit log, self-check, human gate, filing) works on a machine with no model installed.
2. A rules baseline in the evals, so the LLM's results can be compared with a fixed policy.

Its outputs are always labelled provider=scripted. They are never reported as model runs.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from zabuni.agent.graph import fallback_plan, suspicious_lines


def _line(doc: str, label: str) -> str | None:
    m = re.search(rf"^\W*({label}\W*:.*)$", doc, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip().strip("*").strip() if m else None


class ScriptedModel(BaseChatModel):
    """Deterministic policy that emits the same tool calls a careful analyst would."""

    @property
    def _llm_type(self) -> str:
        return "zabuni-scripted"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    # ------------------------------------------------------------------ policy

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        system = messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        if "planner prompt" in system:
            doc = re.search(r"<document[^>]*>\n(.*)\n</document>", messages[1].content, re.DOTALL).group(1)
            plan = fallback_plan(doc).model_dump()
            plan["suspicious_instructions"] = suspicious_lines(doc)
            plan["notes"] = "scripted plan"
            return AIMessage(json.dumps(plan))

        task = next(m.content for m in messages if isinstance(m, HumanMessage) and "run_id:" in m.content)
        run_id = re.search(r"run_id: (\S+)", task).group(1)
        rpath = re.search(r"request_path: (\S+)", task).group(1)
        plan = json.loads(task.split("Plan (from the planner):\n", 1)[1].split("\n\nRun these checks", 1)[0])
        doc = task.split("<document>\n", 1)[1].rsplit("\n</document>", 1)[0]

        done: set[str] = set()
        results: dict[str, Any] = {}
        ids_to_key: dict[str, str] = {}
        for m in messages:
            if isinstance(m, AIMessage):
                for c in m.tool_calls:
                    done.add(c["id"].split("|")[0])
                    ids_to_key[c["id"]] = c["id"].split("|")[0]
            elif isinstance(m, ToolMessage):
                key = ids_to_key.get(m.tool_call_id)
                try:
                    results[key] = json.loads(m.content)
                except (TypeError, json.JSONDecodeError):
                    results[key] = {"error": m.content}

        def call(key: str, name: str, args: dict) -> AIMessage:
            return AIMessage("", tool_calls=[{"id": f"{key}|{len(done)}", "name": name, "args": args}])

        def inp(label: str) -> dict | None:
            q = _line(doc, label)
            return {"type": "input", "path": rpath, "quote": q} if q else None

        sup, buyer, item = plan.get("supplier"), plan.get("buyer"), plan["item_query"]
        steps: list[tuple[str, str, dict]] = []
        pb_args = {"item_query": item, "proposed_amount": plan["proposed_amount"]}
        if plan.get("category"):
            pb_args["category"] = plan["category"]
        if plan.get("budget_amount"):
            pb_args["budget_amount"] = plan["budget_amount"]
        if plan.get("exclude_ocid"):
            pb_args["exclude_ocid"] = plan["exclude_ocid"]
        steps.append(("pb", "price_benchmark", pb_args))
        if sup and "supplier_profile" in plan["checks"]:
            a = {"supplier_name": sup}
            if buyer and "concentration" in plan["checks"]:
                a.update(buyer=buyer, item_query=item)
            steps.append(("sp", "supplier_profile", a))
        if "split_check" in plan["checks"] and buyer:
            steps.append(("split", "detect_split_awards", {"buyer": buyer, "item_query": item}))
        for key, name, args in steps:
            if key not in done:
                return call(key, name, args)

        amount_src = inp("Proposed award amount")
        findings: list[tuple[str, dict]] = []
        pb = results.get("pb") or {}
        comps = [c["source"] for c in pb.get("comparables", [])[:3]]
        v = pb.get("verdict")
        if v in ("high_outlier", "low_outlier"):
            findings.append(("f-price", {
                "finding_type": f"price_outlier_{v.split('_')[0]}", "severity": "high" if v == "high_outlier" else "medium",
                "statement": (f"The proposed amount of KES {plan['proposed_amount']:,.0f} is {pb['ratio_to_median']}x the "
                              f"median of {pb['comparables_used']} comparable awards (KES {pb['median_amount']:,.0f}); "
                              f"robust z-score {pb['robust_z_log']}. Award totals, not unit prices, are compared."),
                "sources": comps + [amount_src]}))
        elif v == "insufficient_comparables":
            findings.append(("f-price", {
                "finding_type": "insufficient_evidence", "severity": "info",
                "statement": (f"Only {pb['comparables_used']} usable comparable awards were found for '{item}', below the "
                              "minimum needed, so no price judgement is made."), "sources": [amount_src]}))
        elif v == "within_range":
            findings.append(("f-price", {
                "finding_type": "price_within_range", "severity": "info",
                "statement": (f"The proposed amount is {pb['ratio_to_median']}x the median of {pb['comparables_used']} "
                              f"comparable awards (KES {pb['median_amount']:,.0f}), within the normal range."),
                "sources": comps + [amount_src]}))
        if pb.get("over_budget"):
            findings.append(("f-budget", {
                "finding_type": "budget_overrun", "severity": "high",
                "statement": (f"The proposed amount exceeds the approved budget by {pb['budget_variance_pct']}%."),
                "sources": [amount_src, inp("Approved budget")]}))
        sp = results.get("sp")
        if sp is not None:
            if "error" in sp or not isinstance(sp, dict) or "supplier" not in sp:
                findings.append(("f-sup", {
                    "finding_type": "data_quality", "severity": "medium",
                    "statement": ("The recommended supplier has no award history under that name in the published data; "
                                  "the committee may wish to confirm its registration details."),
                    "sources": [inp("Recommended supplier")]}))
            else:
                c = sp.get("concentration") or {}
                if (c.get("share_by_count_pct") or 0) >= 40 and c.get("buyer_awards_in_scope", 0) >= 8:
                    findings.append(("f-conc", {
                        "finding_type": "supplier_concentration", "severity": "medium",
                        "statement": (f"The supplier holds {c['share_by_count_pct']}% of this buyer's "
                                      f"{c['buyer_awards_in_scope']} published awards for '{item}' "
                                      f"({c['share_by_value_pct']}% by value). The committee may wish to ask why."),
                        "sources": c["sources"][:6]}))
                if len(sp.get("name_variants_merged", [])) > 1 or sp.get("data_quality_flags", {}).get("supplier_scheme_invalid"):
                    findings.append(("f-id", {
                        "finding_type": "supplier_identity_issue", "severity": "low",
                        "statement": (f"The supplier appears under {len(sp['name_variants_merged'])} name spellings and with "
                                      f"identifier schemes {sp['identifier_schemes_seen']} that do not follow the expected "
                                      "pattern. This is a records problem to resolve, not an accusation."),
                        "sources": [a["source"] for a in sp["awards"][:3]]}))
        sc = results.get("split")
        if isinstance(sc, dict) and sc.get("clusters"):
            cl = sc["clusters"][0]
            findings.append(("f-split", {
                "finding_type": "possible_splitting", "severity": "high",
                "statement": (f"{cl['supplier']} received {cl['awards_in_window']} awards between {cl['first']} and "
                              f"{cl['last']}, each just under the KES {sc['threshold_kes']:,.0f} threshold, totalling "
                              f"KES {cl['sum_kes']:,.0f}. The committee may wish to ask whether these were one requirement."),
                "sources": cl["sources"]}))
        for i, s in enumerate(plan.get("suspicious_instructions", [])):
            findings.append((f"f-inj{i}", {
                "finding_type": "instruction_in_document", "severity": "medium",
                "statement": "The request document contains text instructing the reviewer; it was not followed.",
                "sources": [{"type": "input", "path": rpath, "quote": s}]}))
        for key, f in findings:
            if key not in done:
                f["sources"] = [s for s in f["sources"] if s]
                return call(key, "flag_finding", {"run_id": run_id, **f})

        retry = sum(1 for m in messages if isinstance(m, HumanMessage) and m.content.startswith("Self-check"))
        if f"draft{retry}" not in done:
            checks = [s[1] for s in steps]
            return call(f"draft{retry}", "draft_report", {
                "run_id": run_id, "request_path": rpath, "checks_performed": checks,
                "summary": (f"Scripted baseline review of {item} for {buyer or 'the buyer'}. "
                            f"{len(findings)} finding(s) recorded from {len(checks)} checks; each cites its source.")})
        return AIMessage("Draft ready for the committee's review.")
