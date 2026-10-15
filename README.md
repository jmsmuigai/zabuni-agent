# Zabuni — the value-for-money file, prepared in minutes, decided by people

**[▶ Live demo](https://jmsmuigai.github.io/zabuni-agent/)** · **[🎬 Demo video (2 min)](https://jmsmuigai.github.io/zabuni-agent/zabuni-demo.mp4)** · **[Run it in your browser (Codespaces)](https://codespaces.new/jmsmuigai/zabuni-agent?quickstart=1)** · [Architecture](#architecture) · [What makes it agentic + MCP](docs/AGENTIC_AND_MCP.md)

[![ci](https://github.com/jmsmuigai/zabuni-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jmsmuigai/zabuni-agent/actions/workflows/ci.yml) [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/jmsmuigai/zabuni-agent?quickstart=1)

**Zabuni** (Kiswahili for *tender*) is an agent that prepares the value-for-money file a Tender
Evaluation Committee needs before it signs: how the proposed price compares with every similar
award published under the Open Contracting Data Standard, whether the supplier's record raises
questions, whether the amount fits the budget line, and whether a run of small awards looks like a
split contract. Every finding cites the exact OCDS record or the exact line of the request it
rests on. Then the agent **stops**. A named person decides whether the file goes to the committee.
The agent never awards a tender and never recommends who should win.

- **Track:** Governance · **Theme:** Financial services — *Value for money*
- **Institution and workflow:** a Kenyan county's Supply Chain Management unit preparing the
  pre-signature value-for-money brief for its Tender Evaluation Committee
- **Which half of the data:** built on the **published half** — tenders and awards (Kenya PPIP,
  OCID prefix `ocds-5whusi`). It does **not** evaluate bids; no portal publishes bid documents.

```
 request memo ─► plan ─► price_benchmark ─► supplier_profile ─► detect_split_awards ─► flag_finding ×n
                           (Zabuni MCP)        (Zabuni MCP)        (Zabuni MCP)         (refuses unsourced)
                                         ─► draft_report ─► self-check ─► HUMAN GATE ─► file_to_committee
                                                           (re-verifies     (named person,   (irreversible,
                                                            every source)    token-signed)     read-only)
```

## Problem statement

Kenyan counties spend much of their development budgets through public procurement. Before a
Tender Evaluation Committee signs, someone must establish value for money: is the proposed price
reasonable against what similar items have cost, does the supplier's record raise concerns, does the
amount fit the budget line, and is a run of small awards really one contract split to avoid open
tendering? The evidence is already public — Kenya publishes tenders and awards on the Public
Procurement Information Portal in the Open Contracting Data Standard — but it is messy (impossible
values, inconsistent supplier names, broken identifiers) and no officer has time to search
thousands of records for every tender. The file takes weeks or arrives thin, and overpricing and
contract splitting, which audit reports raise year after year, slip through. Any fix must keep a
named human accountable for the decision.

## Solution overview

Given a review request, Zabuni plans its checks and calls tools on its own MCP server built over
the published OCDS awards: it benchmarks the price with a robust statistic, profiles the supplier,
compares the amount with the budget line and looks for split contracts. Every finding must cite
its source; the server refuses unsourced findings and award-making language. A deterministic
self-check re-verifies the draft, then the agent stops at a human gate. Only a named officer can
approve filing the file to the committee. It runs locally on an open-weights model so data can stay
in-country, at zero API cost.

## Target users

- **Primary:** county Supply Chain Management officers who prepare the value-for-money brief.
- **Decision-makers:** Tender Evaluation Committees and accounting officers, who receive a sourced,
  auditable file instead of a thin memo.
- **Beneficiaries:** auditors (every call is logged and every finding is traceable) and citizens
  (better value from public money). The MCP server is reusable by oversight bodies and journalists
  from any MCP client.

## Architecture

![Zabuni architecture: users, LangGraph agent, MCP client, two MCP servers, human gate, data](docs/architecture.png)

Full write-up: [ARCHITECTURE.md](ARCHITECTURE.md) · what makes it agentic and how MCP is used: [docs/AGENTIC_AND_MCP.md](docs/AGENTIC_AND_MCP.md)


**Agent architecture (summary).** One agent, implemented as a LangGraph `StateGraph`:
`intake → plan → agent ⇄ tools (≤ 24 steps) → verify (≤ 2 correction rounds) → human_gate → file`.
The LLM is model-agnostic (Qwen 2.5 7B via Ollama by default; Claude optional). Run state is
checkpointed with LangGraph's `InMemorySaver`, which is what lets the graph pause at the gate and
resume. The model only reaches data and actions through MCP.

## Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ (agent, MCP server), Node.js 20+ (borrowed filesystem MCP server) |
| Orchestration | LangGraph, LangChain Core |
| MCP | MCP Python SDK (FastMCP) for the built server · `@modelcontextprotocol/server-filesystem` · `langchain-mcp-adapters` client, stdio transport |
| Models | Qwen 2.5 7B (open weights) via Ollama — default · Claude via `langchain-anthropic` — optional comparison · scripted rule baseline — offline demo and CI only |
| Data | Kenya PPIP in OCDS via the OCP Data Registry · SQLite with FTS5 · RapidFuzz name/title matching · Pydantic validation |
| Quality | pytest (32 tests), eval harness (`evals/tasks.json`), GitHub Actions CI, uv |

## Human-in-the-loop workflow

1. The agent finishes its checks and the self-check; any unresolved problems are listed, not hidden.
2. The graph calls LangGraph `interrupt()` and **stops**, showing the findings and the draft's SHA-256.
3. A named reviewer types their name and chooses **approve**, **reject** or **hold**.
   Approve without a name is treated as hold. Reject or hold ends the run with nothing filed.
4. On approve, the graph mints an HMAC approval token over (run, approver, draft SHA-256) and calls
   `file_to_committee` itself — the model never sees this tool or the secret.
5. The server re-checks the token; changing one byte of the draft after approval makes filing fail.
   The filed copy records "Reviewed by" and is read-only, never overwritten.

## Setup and usage

### Run it — one command

```bash
make demo          # needs uv, Node.js 20+, Ollama. Pulls qwen2.5:7b and runs the agent locally.
```

No GPU or no Ollama? `make demo-offline` runs the identical pipeline (both MCP servers, audit log,
self-check, gate, filing) with a scripted rule policy in place of the model. It is labelled
`scripted` everywhere and is never reported as a model run.

The run prints every tool call as it happens, stops at the gate, and asks for your name and a
decision. Outputs: `workspace/drafts/<run>.md` (the file), `runs/<run>/audit.jsonl` (every call),
`runs/<run>/summary.json` (tokens, time, cost), and — only after approval —
`workspace/committee_outbox/<run>.md`, read-only.

<details><summary>Other commands</summary>

```bash
make kenya                     # download Kenya PPIP 2025 from the OCP Data Registry and load it
uv run zabuni replay --n 8     # write requests that replay completed real awards (never live tenders)
uv run zabuni run workspace/inputs/req_008_split_quotations.md
uv run zabuni run <request> --provider anthropic      # frontier model alongside, for comparison
make eval                      # 14 tasks × 3 repeats on the open-weights model → EVALS.md
make eval-baseline             # same tasks with the scripted rule policy
make test                      # 32 tests: data, tools, guardrails, gate, recovery, full pipeline
make serve                     # the Zabuni MCP server on stdio, for Claude Desktop or any client
```
</details>

## What it does that a spreadsheet does not

| Capability | How it is enforced |
|---|---|
| **No unsourced flag, ever** | `flag_finding` refuses a finding with no source, re-resolves every OCDS citation against the database, and checks every quoted request line actually appears in the file. The self-check re-validates them all again before the gate. |
| **Never awards** | Award-making language ("should be awarded", "winning bidder is"…) is refused by the server. Filing is not a model tool at all; the graph calls it after a named human approves. |
| **Approval bound to the exact file** | The approval token is an HMAC over run, approver name and the draft's sha256. Edit one byte after approval and filing is refused. Filed copies are read-only and never overwritten. |
| **Honest about thin evidence** | Fewer than 5 usable comparables → `insufficient_comparables`; the agent must say so and may not flag price. |
| **Messy data handled, not hidden** | The KES 99-trillion-style value errors, broken supplier identifier schemes, buyer names missing from `parties`, empty award arrays: kept, flagged, excluded from benchmarks where needed, and counted in every report. Supplier name variants (`KILELE TRADERS LIMITED` / `Kilele Traders Ltd.`) are merged. |
| **Contract-splitting detector** | Same buyer, same supplier, several awards each just under a quotation threshold inside a window, summing above it. |
| **No personal data** | Contact points, e-mails and phone numbers are dropped at ingest. Suppliers trading under a person's name are pseudonymised (`Supplier P-1A2B3C4D`). |
| **Injection-resistant** | Instructions inside a request ("ignore checks and award to…") are detected, not followed, and reported as a finding. |
| **Works in Kiswahili** | A Kiswahili request is planned against English-titled data (eval E14). |
| **Stays in the country** | Default model is open-weights, local, via Ollama. API cost for those runs is zero; time and tokens are logged per run. |

## MCP implementation — servers and tools

| Server | Built or borrowed | Tools |
|---|---|---|
| `zabuni` (this repo) | **Built** | `search_awards`, `price_benchmark`, `supplier_profile`, `detect_split_awards` (read) · `flag_finding`, `draft_report` (write) · `file_to_committee` (irreversible, gated) · resource `zabuni://dataset` |
| [`@modelcontextprotocol/server-filesystem`](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) | **Borrowed** (official) | `read_text_file`, `list_directory` — scoped to `workspace/inputs` and `workspace/drafts` |

Why borrow the filesystem server: its path sandboxing and symlink handling are maintained and
reviewed by the MCP project; writing our own file reader is exactly the kind of code that gets
path-traversal wrong. The model is given only its read tools.

The Zabuni server is reusable on its own: point Claude Desktop, Goose or any MCP client at
`uv run zabuni serve` and the tools work without this orchestrator.

## Limitations and honest status

- **Tested here:** 32 automated tests pass, including full runs over real MCP stdio sessions with
  both servers. The scripted baseline passes 24/24 runs of tasks E01–E12 and fails E13–E14
  (free-form memo, Kiswahili) by design — those need a language model.
- **Open-weights eval results** are produced by `make eval` on a machine with Ollama and written
  into [EVALS.md](EVALS.md) by the runner. Numbers appear there only after real runs.
- **Real Kenya data:** the loader follows the registry's documented field shape and data problems
  and is tested on synthetic files in that shape; `make kenya` loads the real 2025 file. Title
  matching on real tender titles will be noisier than on the fixture.
- **Price comparison is on award totals.** The portal publishes no item lines or quantities, so a
  large order can look like an overpriced small one. Every report says so.
- **Not built:** bid evaluation (no bid documents are published), a web UI, multi-buyer
  dashboards. Thresholds (splitting, concentration) are configurable defaults, not law.

## Future improvements

- **Item-level prices:** compare unit prices when quantities are published, or extract them from
  tender documents, to fix the known large-quantity false positive (EVALS E15).
- **More red flags:** award dated before tender close, single-bidder rate, repeat direct
  procurement, supplier registered shortly before award.
- **Two-person approval** for high-value tenders, and a Kiswahili summary for citizen notice boards.
- **Other countries:** the loader already reads any OCDS publication; add Rwanda, Nigeria, Uganda
  and adjust identifier and currency rules.
- **A simple web front end** for SCM officers, and integration with the county IFMIS budget lines.
- **Field pilot** with a county SCM unit to measure time saved and findings confirmed by auditors.

## Data and conduct

- `data/sample_ocds.jsonl.gz` is **synthetic**. Every buyer ("Mfano", "Kielelezo", "Sampuli" —
  Kiswahili for *example*, *model*, *sample*), supplier and person in it is fictional. It
  reproduces the real feed's documented problems on purpose.
- Real data comes from Kenya's Public Procurement Information Portal via the
  [OCP Data Registry](https://data.open-contracting.org/en/publication/147). The registry lists no
  licence for this publication; we use it as published public procurement records.
- No live tenders. Replay requests are built only from completed awards.

## Layout

```
src/zabuni/mcp_server/   server.py (tools) · store.py (queries, statistics) · actions.py (findings, report, filing) · gate.py
src/zabuni/agent/        graph.py (LangGraph) · audit.py (logging) · llm.py · scripted.py (no-model policy)
src/zabuni/data/         ingest.py (OCDS → SQLite) · synth.py (fixture) · normalize.py
prompts/                 agent and planner prompts; briefs for Claude Code and Antigravity
evals/                   tasks.json · results/        tests/   32 tests
```

MIT licence. Built during the challenge window by James Mukoma Mburu, with AI coding assistance
(Claude), which the rules allow.
