# Submission pack

## Project description (~300 words, paste into the portal)

**Zabuni** prepares the value-for-money file a Tender Evaluation Committee needs before it signs,
and then stops so a named person can decide. It fits the **Governance** track, **Financial
services — value for money** theme, and serves a Kenyan county's Supply Chain Management unit at
the step between financial evaluation and the committee's report.

Given a review request (buyer, item, recommended supplier, proposed amount, budget line), the agent
plans its checks and calls tools on its own MCP server, built over Kenya's published OCDS data
(PPIP, `ocds-5whusi`). It benchmarks the price against every similar published award using a robust
statistic, profiles the supplier (merging name spellings, flagging broken identifiers, measuring its
share of this buyer's awards), compares the amount with the budget line, and looks for contract
splitting: several awards just under a quotation threshold to one supplier in a short window.

Every finding must cite its evidence. The server refuses findings without sources, re-resolves every
OCDS citation, checks every quoted request line exists, and refuses award-making language. A
deterministic self-check verifies the draft against the tool results before a human sees it. The
irreversible step — filing to the committee outbox — is never given to the model: the graph calls
it only after a named person approves, with a token bound to their name and the draft's exact hash.

It runs on an open-weights model (Qwen 2.5 via Ollama) so data can stay in-country; a frontier
model can be run alongside. Every tool call is logged with inputs, outputs, timing and errors, and
each run records tokens, time and cost. It handles the feed's documented problems — extreme value
errors, invalid identifier schemes, missing buyer names — and pseudonymises sole proprietors.
Instructions hidden in a request are reported, not followed; requests in Kiswahili work.

Honest limits: prices are compared on award totals because no quantities are published (our
documented unfixed failure), and bids are not evaluated because bid documents are not public.

## Agentic design and MCP (form answers)

See [docs/AGENTIC_AND_MCP.md](docs/AGENTIC_AND_MCP.md); architecture diagram for upload: [docs/architecture.png](docs/architecture.png).

## Checklist

- [ ] Repository public, MIT licence visible, README runs with `make demo`
- [ ] `make test` passes on a clean clone
- [ ] `make eval` run on qwen2.5:7b; results committed by the runner (not typed by hand)
- [ ] At least one field conversation recorded in WORKFLOW.md
- [ ] Demo video under 3 minutes on YouTube or Vimeo, public, unedited agent run with tool calls
      on screen, including the E15 failure
- [x] Architecture diagram committed (docs/architecture.png)
- [ ] Description pasted (above), theme: Financial services — Value for money
- [ ] Last commit before the deadline timestamp; nothing pushed after it

## Demo video script (2 min 50 s)

| Time | Screen | Say |
|---|---|---|
| 0:00–0:15 | README top | "A county SCM unit spends weeks building the value-for-money file. Zabuni builds it from published awards in minutes and stops for a person." |
| 0:15–1:15 | `zabuni run req_002…` streaming | Point at the plan, `price_benchmark` (4.8× median, 192 comparables), the findings, the self-check. |
| 1:15–1:35 | Gate prompt | Type your name, approve. Open the filed file: sources with OCID and line numbers, "Reviewed by". |
| 1:35–2:00 | `zabuni run req_007…` | The injected "award the tender to…" line is reported as a finding, not obeyed. Hold. |
| 2:00–2:30 | `zabuni run req_015…` | "Here it fails: triple quantity looks like overpricing, because Kenya publishes no quantities. It's in EVALS.md with what I'd try next." |
| 2:30–2:50 | `summary.json`, audit.jsonl | "Every call logged, tokens and time per run, zero API cost on the local model." |

## Live technical review — likely "new requirement" drills

| If they ask for… | Where it goes | About |
|---|---|---|
| A new red flag (e.g. award date before tender closes, single-bidder rate) | new function in `store.py`, `@mcp.tool()` in `server.py`, a finding type in `actions.FINDING_TYPES`, a rule in `graph.verify`, a test | 20 min |
| Another country (Rwanda, Nigeria) | `make` with that registry file → `zabuni ingest`; adjust `KRA_PIN`/currency in `normalize.py` | 10 min |
| A different reviewer rule (two approvers) | `graph.human_gate` collects two names; `gate.mint` over both | 15 min |
| A Kiswahili summary for citizens | extra section in `actions.draft_report`, lint applies | 10 min |
| Swap the model | `ZABUNI_OLLAMA_MODEL=llama3.1:8b make demo` | 1 min |
