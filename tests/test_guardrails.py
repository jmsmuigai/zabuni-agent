"""The rules that make a finding defensible, enforced in code."""
import os
import stat

import pytest

from zabuni import config
from zabuni.mcp_server import actions, gate, store
from zabuni.mcp_server.store import StoreError

REQ = "inputs/req_002_maize_overpriced.md"


def _comparables(n=3):
    return [c["source"] for c in store.price_benchmark("certified maize seed", 19_800_000)["comparables"][:n]]


def test_finding_without_source_refused():
    with pytest.raises(StoreError, match="no source"):
        actions.flag_finding("t-nosrc", "other", "low", "Something the committee should look at.", [])


def test_invented_citation_refused():
    fake = {"type": "ocds", "ocid": "ocds-synth0-99999", "award_id": "made-up"}
    with pytest.raises(StoreError, match="does not resolve"):
        actions.flag_finding("t-fake", "other", "low", "A finding with an invented source.", [fake])


def test_misquoted_input_refused():
    with pytest.raises(StoreError, match="Quote not found"):
        actions.flag_finding("t-quote", "budget_overrun", "high", "Over budget by a wide margin indeed.",
                             [{"type": "input", "path": REQ, "quote": "Approved budget: KES 1"}])


def test_input_outside_inputs_folder_refused():
    with pytest.raises(StoreError):
        actions.validate_source({"type": "input", "path": "../../etc/passwd", "quote": "root"})


@pytest.mark.parametrize("text", [
    "We recommend that the tender be awarded to Shamba Seeds Ltd.",
    "Shamba Seeds Ltd should be awarded the contract.",
    "The winning bidder is Shamba Seeds Ltd.",
    "Recommend award to the lowest evaluated bidder.",
])
def test_award_language_refused(text):
    with pytest.raises(StoreError, match="award-making"):
        actions.flag_finding("t-award", "other", "low", text, _comparables(1))


def test_factual_award_history_allowed():
    r = actions.flag_finding("t-hist", "other", "low",
                             "Nine past awards were made to Kilele Traders by this buyer since 2022.", _comparables(1))
    assert r["status"] == "recorded"


def test_price_outlier_needs_three_comparables():
    with pytest.raises(StoreError, match="at least 3"):
        actions.flag_finding("t-few", "price_outlier_high", "high", "The price is far above past awards.",
                             _comparables(2))


def test_insufficient_evidence_cannot_be_severe():
    with pytest.raises(StoreError):
        actions.flag_finding("t-sev", "insufficient_evidence", "high", "Not enough comparables to judge price.",
                             [{"type": "input", "path": REQ, "quote": "Proposed award amount: KES 19,800,000"}])


def test_gate_end_to_end():
    run = "t-gate"
    actions.flag_finding(run, "price_outlier_high", "high", "The proposed amount is far above the median of past awards.",
                         _comparables(3) + [{"type": "input", "path": REQ, "quote": "Proposed award amount: KES 19,800,000"}])
    rep = actions.draft_report(run, REQ, "Evidence summary for the committee.", ["price_benchmark"])
    sha = rep["sha256"]
    with pytest.raises(StoreError, match="token invalid"):
        actions.file_to_committee(run, "Jane Reviewer", "not-a-token")
    token = gate.mint(run, sha, "Jane Reviewer")
    with pytest.raises(StoreError, match="token invalid"):  # token is bound to the approver's name
        actions.file_to_committee(run, "Someone Else", token)
    draft = config.DRAFTS / f"{run}.md"
    draft.write_text(draft.read_text() + "\ntampered\n")
    with pytest.raises(StoreError, match="token invalid"):  # and to the exact draft bytes
        actions.file_to_committee(run, "Jane Reviewer", token)
    sha = actions.draft_report(run, REQ, "Evidence summary for the committee.", ["price_benchmark"])["sha256"]
    out = actions.file_to_committee(run, "Jane Reviewer", gate.mint(run, sha, "Jane Reviewer"))
    filed = config.OUTBOX / f"{run}.md"
    assert out["status"] == "filed" and "Reviewed by: Jane Reviewer" in filed.read_text()
    assert not os.stat(filed).st_mode & stat.S_IWUSR  # read-only
    with pytest.raises(StoreError, match="Already filed"):
        actions.file_to_committee(run, "Jane Reviewer", gate.mint(run, sha, "Jane Reviewer"))


def test_gate_requires_named_approver():
    with pytest.raises(ValueError):
        gate.mint("r", "sha", "  ")
