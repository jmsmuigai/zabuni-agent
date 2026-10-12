# Brief for Google Antigravity (agent manager task)

**Workspace:** the `zabuni-agent` repository. **Goal:** record the demo video and prove the agent on
the open-weights model, without changing what the agent is allowed to do.

## Context the agent needs
- Python 3.11+, managed with `uv`. Node.js 20+ for the borrowed MCP filesystem server.
- Ollama serves `qwen2.5:7b` locally (`ollama pull qwen2.5:7b`).
- Entry points: `make demo`, `make eval`, `make test`, `uv run zabuni run <request>`.
- Non-negotiables are listed in `prompts/claude_code_brief.md` ("Hard rules"). Apply all of them.

## Task 1 — verify the environment (artifact: terminal log)
Run `make doctor` then `make test`. All 32 tests must pass. If not, stop and report the failing test.

## Task 2 — demo rehearsal (artifact: screen recording, under 3 minutes)
In one terminal at a readable font size, run without editing:
1. `uv run zabuni run workspace/inputs/req_002_maize_overpriced.md` — show tool calls streaming,
   the plan, the self-check, the gate. Type a real name and `approve`. Open the filed file.
2. `uv run zabuni run workspace/inputs/req_007_injection.md` — show the injected instruction
   reported as a finding, not followed. Answer `hold`.
3. `uv run zabuni run workspace/inputs/req_015_large_quantity.md` — show the known failure: the
   quantity case flagged as a price outlier. Say why in one sentence.
4. `cat runs/<run>/summary.json` — tokens, seconds, API cost 0.
Do not cut the agent run. If a run fails, keep it in the video and say what failed.

## Task 3 — evals (artifact: commit)
Run `make eval`. Commit `evals/results/` and the updated EVALS.md with message
"evals: qwen2.5:7b, 3 repeats". Do not edit result numbers.

## Task 4 — browser check (artifact: screenshot)
Open the public GitHub repository page logged out (incognito). Confirm the README renders, the
licence shows MIT, and `git clone` + `make demo-offline` works in a fresh folder.
