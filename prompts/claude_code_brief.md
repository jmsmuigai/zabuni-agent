# Brief for Claude Code (paste as the first message in the repo)

You are working in `zabuni-agent`, a submission to the African Agentic AI Design Challenge
(Governance track, Financial services theme: value for money). Read README.md, ARCHITECTURE.md and
EVALS.md first. Then do the tasks below in order. After each one, run `make test` and stop if
anything fails.

## Hard rules from the challenge (never break these)
1. The agent prepares the file; it never awards or recommends an award. Do not add any tool or
   prompt text that names a winner.
2. Every finding cites a source that resolves. Never weaken the checks in
   `src/zabuni/mcp_server/actions.py` (`validate_source`, `_lint`, the 3-comparable rule).
3. `file_to_committee` stays out of the model's tool list and requires a token from the gate.
4. Every tool call is logged (`src/zabuni/agent/audit.py`). Do not bypass the interceptor.
5. No live tenders, no personal details of individuals. Company records are fine.
6. Never write results into EVALS.md by hand. Only `zabuni eval` writes results. Never present a
   scripted run as a model run.
7. Commits must land before the deadline timestamp; anything after it disqualifies the entry.

## Tasks
1. Run `make doctor`, then `make demo`. If the open-weights model fails to call tools, read
   `runs/<run>/audit.jsonl`, find the failing step, and fix the cause (prompt wording, argument
   repair in `Zabuni._coerce`, or a tool error message), not the symptom. Re-run.
2. Run `make eval` (qwen2.5:7b, 3 repeats). Commit the generated `evals/results/*` and EVALS.md.
   If a task fails, decide whether the agent or the test is wrong, and say which in the commit message.
3. Optional: run `make kenya`, then `uv run zabuni replay --n 8` and run 3 replays. Record in the
   README what broke on real titles. Do not commit the downloaded data file.
4. Optional, only if time allows: the E15 fix described in EVALS.md (quantity-aware downgrade).
   Keep E15 in the suite either way.

## Style
Small diffs. Plain names. Each new tool: plain arguments, JSON result with `source` on every row,
rules enforced in the server, a test in `tests/`.
