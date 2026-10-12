"""Human approval tokens for the one irreversible action (filing to the committee outbox).

The token is an HMAC over (run_id, sha256 of the exact draft, approver name). It is minted only
by the human-gate step in the orchestrator after a named person types their decision, and is
checked by the MCP server. The model is never given the secret or the filing tool.
Any edit to the draft after approval changes its hash and invalidates the token.
"""
from __future__ import annotations

import hashlib
import hmac

from zabuni import config


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _msg(run_id: str, report_sha: str, approver: str) -> bytes:
    return f"{run_id}|{report_sha}|{approver.strip()}".encode()


def mint(run_id: str, report_sha: str, approver: str, secret: str | None = None) -> str:
    if not approver or not approver.strip():
        raise ValueError("A named approver is required.")
    return hmac.new((secret or config.GATE_SECRET).encode(), _msg(run_id, report_sha, approver),
                    hashlib.sha256).hexdigest()


def verify(token: str, run_id: str, report_sha: str, approver: str, secret: str | None = None) -> bool:
    try:
        expected = mint(run_id, report_sha, approver, secret)
    except ValueError:
        return False
    return hmac.compare_digest(expected, token or "")
