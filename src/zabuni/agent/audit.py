"""Audit log: one JSON line per tool call, model call and gate decision.

Every MCP tool call from either server passes through `AuditInterceptor`, so the log covers the
borrowed filesystem server as well as Zabuni's own. Records hold inputs, an output excerpt with
the full output's sha256, start/end timestamps, duration and error state.
"""
from __future__ import annotations

import hashlib
import json
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from zabuni import config

current_run: ContextVar["AuditLog | None"] = ContextVar("current_run", default=None)

import os

# API price in USD per million tokens for frontier runs (set from your provider's price list).
# Local open-weights runs cost 0 in API fees; their cost is the wall-clock time recorded.
PRICE_IN = float(os.getenv("ZABUNI_PRICE_IN_PER_MTOK", 0))
PRICE_OUT = float(os.getenv("ZABUNI_PRICE_OUT_PER_MTOK", 0))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AuditLog:
    def __init__(self, run_id: str, model: str, provider: str):
        self.run_id, self.model, self.provider = run_id, model, provider
        self.dir = config.RUNS / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "audit.jsonl"
        self.started = time.time()
        self.tokens_in = self.tokens_out = 0
        self.tool_calls = self.tool_errors = self.llm_calls = 0
        self.recoveries: list[str] = []

    def write(self, kind: str, **rec) -> None:
        rec = {"ts": _now(), "run_id": self.run_id, "kind": kind, **rec}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        if not os.getenv("ZABUNI_QUIET"):
            _echo(rec)

    def llm(self, node: str, msg) -> None:
        usage = getattr(msg, "usage_metadata", None) or {}
        tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        self.tokens_in += tin
        self.tokens_out += tout
        self.llm_calls += 1
        calls = [{"name": c["name"], "args": c["args"]} for c in getattr(msg, "tool_calls", []) or []]
        self.write("llm", node=node, model=self.model, input_tokens=tin, output_tokens=tout,
                   tool_calls_requested=calls, text=(getattr(msg, "content", "") or "")[:600]
                   if isinstance(getattr(msg, "content", ""), str) else str(msg.content)[:600])

    def recovery(self, what: str, detail: str = "") -> None:
        self.recoveries.append(what)
        self.write("recovery", what=what, detail=detail[:800])

    def cost_usd(self) -> float:
        if self.provider == "ollama":
            return 0.0
        return round(self.tokens_in / 1e6 * PRICE_IN + self.tokens_out / 1e6 * PRICE_OUT, 4)

    def summary(self, **extra) -> dict:
        s = {
            "run_id": self.run_id, "provider": self.provider, "model": self.model,
            "seconds": round(time.time() - self.started, 1), "llm_calls": self.llm_calls,
            "input_tokens": self.tokens_in, "output_tokens": self.tokens_out,
            "tool_calls": self.tool_calls, "tool_errors": self.tool_errors,
            "recoveries": self.recoveries, "api_cost_usd": self.cost_usd(), **extra,
        }
        (self.dir / "summary.json").write_text(json.dumps(s, indent=2, default=str), encoding="utf-8")
        return s


def _result_text(result) -> tuple[str, bool]:
    """Flatten an MCP CallToolResult / ToolMessage to text and an error flag."""
    is_err = bool(getattr(result, "isError", False)) or getattr(result, "status", "") == "error"
    content = getattr(result, "content", result)
    if isinstance(content, list):
        parts = []
        for c in content:
            parts.append(getattr(c, "text", None) or (c.get("text") if isinstance(c, dict) else str(c)))
        text = "\n".join(p for p in parts if p)
    else:
        text = str(content)
    return text, is_err


class AuditInterceptor:
    """langchain-mcp-adapters tool interceptor: logs every MCP call with timing."""

    async def __call__(self, request, handler):
        log = current_run.get()
        t0, ts = time.time(), _now()
        try:
            result = await handler(request)
        except Exception as e:  # noqa: BLE001
            if log:
                log.tool_calls += 1
                log.tool_errors += 1
                log.write("tool", server=request.server_name, tool=request.name, args=_redact(request.args),
                          started=ts, ms=round((time.time() - t0) * 1000, 1), ok=False, error=str(e)[:800])
            raise
        if log:
            text, is_err = _result_text(result)
            log.tool_calls += 1
            log.tool_errors += int(is_err)
            log.write("tool", server=request.server_name, tool=request.name, args=_redact(request.args),
                      started=ts, ms=round((time.time() - t0) * 1000, 1), ok=not is_err,
                      output_excerpt=text[:1500], output_sha256=hashlib.sha256(text.encode()).hexdigest())
        return result


def _redact(args: dict) -> dict:
    out = dict(args or {})
    if "approval_token" in out:
        out["approval_token"] = (out["approval_token"] or "")[:12] + "…"
    return out


def read_log(run_id: str) -> list[dict]:
    p = Path(config.RUNS) / run_id / "audit.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _echo(rec: dict) -> None:
    """Print a one-line trace so tool calls are visible on screen during a run (and in the demo)."""
    import sys

    col = sys.stdout.isatty() and not os.getenv("NO_COLOR")
    d, g, r, y, c, x = ("\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m") if col else ("",) * 6
    t = rec["ts"][11:19]
    k = rec["kind"]
    if k == "tool":
        mark = f"{g}ok{x}" if rec.get("ok") else f"{r}ERROR{x}"
        args = json.dumps(rec.get("args"), default=str, ensure_ascii=False)
        print(f"{d}{t}{x} {c}tool{x} {rec['server']}.{rec['tool']} {d}{args[:220]}{x} → {mark} {d}{rec.get('ms')}ms{x}")
        if not rec.get("ok"):
            print(f"         {r}{(rec.get('output_excerpt') or rec.get('error') or '')[:240]}{x}")
    elif k == "plan":
        p = rec["plan"]
        print(f"{d}{t}{x} {c}plan{x} item={p['item_query']!r} amount={p['proposed_amount']:,.0f} "
              f"supplier={p.get('supplier')!r} checks={p['checks']}")
    elif k == "recovery":
        print(f"{d}{t}{x} {y}recover{x} {rec['what']}: {d}{rec.get('detail', '')[:200]}{x}")
    elif k == "verify":
        status = f"{g}passed{x}" if not rec["problems"] else f"{y}{len(rec['problems'])} problem(s){x}"
        print(f"{d}{t}{x} {c}self-check{x} round {rec['round']}: {status}")
        for pr in rec["problems"]:
            print(f"         {y}- {pr[:200]}{x}")
    elif k == "gate_decision":
        print(f"{d}{t}{x} {c}gate{x} decision={rec['decision']} approver={rec.get('approver')!r}")
    elif k == "session":
        print(f"{d}{t}{x} {c}mcp{x} connected: {', '.join(rec['servers'])}")
