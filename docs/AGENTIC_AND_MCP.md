# What makes Zabuni agentic, and how MCP is integrated

![Zabuni architecture](architecture.png)

*Source: [`architecture.svg`](architecture.svg) · regenerate with `python scripts/make_architecture_diagram.py`.*

## What makes Zabuni an agentic AI system

Zabuni is given a goal, not a script: "prepare the value-for-money file for this tender request."
From a free-form memo (English or Kiswahili) the model builds its own plan — which buyer, item,
supplier and amounts are involved, and which checks the case needs. It then works through a tool
loop on its own: it chooses which MCP tools to call, with what arguments, reads the results and
decides what to do next. A price that looks high leads it to profile the supplier. Several small
awards lead it to run the contract-splitting detector. When a tool returns an error, the error goes
back to the model so it can correct itself and retry.

The agent also checks its own work. A deterministic verifier compares the draft against what the
tools actually returned. Any gap — a check that never ran, a citation that does not resolve, a
budget overrun with no finding — is sent back to the agent for up to two correction rounds.

Finally, the agent knows when to stop. It pauses at a human gate, and only a named officer can
approve the one irreversible action: filing to the committee. That combination — goal-driven
planning, autonomous multi-step tool use, self-correction and a bounded authority to act — is what
makes it an agent rather than a chatbot or a fixed pipeline.

## Capabilities demonstrated

| Capability | Where it shows |
|---|---|
| **Planning** | `plan` node: the LLM turns the memo into a validated JSON plan of checks |
| **Reasoning** | Interprets benchmark statistics, supplier history and budget fit into findings |
| **Decision support** | Prepares the evidence file the Tender Evaluation Committee decides on |
| **Tool/API calling** | 6 model-visible tools on the Zabuni MCP server + 2 on the filesystem server |
| **Data retrieval** | Full-text + fuzzy search over ~109k published Kenyan OCDS awards |
| **Multi-step execution** | LangGraph loop of up to 24 steps, with error feedback and retries |
| **Workflow automation** | Intake → plan → checks → findings → draft → self-check → gate → filing |
| **Monitoring** | Every MCP and model call logged (args, output hash, timing, errors); tokens and cost per run |
| **Information synthesis** | Combines price, supplier, budget and splitting evidence into one sourced report |
| **Other** | Self-verification · human approval gate · prompt-injection detection · Kiswahili input |

Deliberately **not** claimed: *recommendation generation*. Zabuni never recommends a winner or
awards a tender; the server refuses award-making language.

## Agent architecture

- **Agent / orchestration** — a single agent implemented as a LangGraph `StateGraph` with nodes
  `intake → plan → agent ↔ tools → verify → human_gate → file`. The verify node can route back to
  the agent up to two times.
- **LLMs** — model-agnostic. Default is **Qwen 2.5 7B** (open weights) running locally through
  **Ollama**, so procurement data stays in-country at zero API cost. **Claude** (Anthropic API) can
  be run alongside for comparison. A scripted rule baseline runs offline demos and CI, and is always
  labelled as such.
- **Memory / state** — LangGraph `InMemorySaver` checkpoints each run's state (plan, messages, tool
  results, findings keyed by `run_id`). This is what lets the graph pause at the human gate with
  `interrupt()` and resume after the decision. Prompts live in `prompts/`.
- **Tools** — exposed only through MCP (next section). The model is given read tools plus two
  guarded write tools. The irreversible filing tool is called by the graph, never by the model.
- **Workflows** — one decision point in a county Supply Chain Management unit: the pre-signature
  value-for-money brief for the Tender Evaluation Committee.
- **Database** — SQLite with an FTS5 full-text index, built by `ingest.py` from OCDS JSON Lines.
  Ingest drops contact details, pseudonymises sole proprietors and keeps bad records with
  data-quality flags rather than hiding them.
- **External APIs / data** — Kenya's Public Procurement Information Portal published in OCDS via the
  Open Contracting Partnership Data Registry; Ollama's local HTTP API; optional Anthropic API.
- **Human-in-the-loop** — a named reviewer approves, rejects or holds. Approval mints an HMAC token
  over (run, approver, draft SHA-256); editing one byte afterwards makes filing fail.

**Core technology stack:** Python 3.11+ · LangGraph · LangChain Core · `langchain-mcp-adapters` ·
MCP Python SDK (FastMCP) · `@modelcontextprotocol/server-filesystem` (Node.js 20+) · Ollama with
Qwen 2.5 7B · optional `langchain-anthropic` (Claude) · SQLite + FTS5 · RapidFuzz · Pydantic ·
pytest · uv · GitHub Actions CI · data in the Open Contracting Data Standard (OCDS).

## How MCP is implemented

Zabuni uses MCP as the **only** way the model touches data or takes action. Two MCP servers run
over **stdio** (JSON-RPC 2.0) and stay open for the whole run. The agent connects to both through
`MultiServerMCPClient` from `langchain-mcp-adapters`, which turns MCP tools into LangGraph tools.

**1. `zabuni` — built for this project** (Python, FastMCP, `src/zabuni/mcp_server/server.py`)

| Kind | Name | What it does |
|---|---|---|
| Read tool | `search_awards` | Full-text + fuzzy search of published awards |
| Read tool | `price_benchmark` | Robust z-score of the proposed price against comparable awards; no verdict with fewer than 5 comparables |
| Read tool | `supplier_profile` | Merges name variants, flags broken identifiers, measures the supplier's share of the buyer's awards |
| Read tool | `detect_split_awards` | Finds runs of awards just under a quotation threshold to one supplier |
| Write tool | `flag_finding` | Records a finding; refuses it without sources and re-resolves every OCDS citation |
| Write tool | `draft_report` | Writes the draft; refuses award-making language |
| Gated tool | `file_to_committee` | Irreversible; called by the graph only, with a valid HMAC approval token |
| Resource | `zabuni://dataset` | Dataset provenance and data-quality counts |

The rules are enforced **inside the server**, not just in the prompt, so they hold for any MCP
client. The server runs standalone (`uv run zabuni serve`) under Claude Desktop, Goose or any other
client.

**2. `filesystem` — borrowed** (official `@modelcontextprotocol/server-filesystem`)

`read_text_file` and `list_directory`, sandboxed to `workspace/inputs` and `workspace/drafts`. The
agent uses it to read the request memo and its own draft. It is reused because its path sandboxing
and symlink handling are maintained by the MCP project, and a home-made file reader is a common
source of path-traversal bugs.

**How they connect to the agent.** The graph opens both stdio sessions, loads their tools and
passes only the model-visible subset to the LLM. Calls to anything else are refused and logged. An
`AuditInterceptor` on the client writes one JSONL line per MCP call from either server — arguments,
output excerpt, output SHA-256, start time, duration and error — to `runs/<run>/audit.jsonl`. The
server keeps its own `runs/server_audit.jsonl`, so the two logs can be cross-checked.
