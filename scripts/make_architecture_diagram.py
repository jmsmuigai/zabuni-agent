"""Regenerate docs/architecture.svg and docs/architecture.png.

    python scripts/make_architecture_diagram.py      # PNG needs: pip install cairosvg
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs"
W, H = 1600, 1190

INK, MUTED, LINE, BG = "#1d2433", "#5a6475", "#8a93a3", "#ffffff"
ZONES = {
    "users": ("#fff6e8", "#d98a1c"),
    "agent": ("#eef3ff", "#3b62d6"),
    "mcp": ("#eaf7f0", "#1f8a57"),
    "human": ("#fdeef0", "#c4384d"),
    "data": ("#f2f0fa", "#6a52b8"),
}

parts: list[str] = []


def text(x, y, s, size=14, weight=400, color=INK, anchor="start", italic=False):
    style = ' font-style="italic"' if italic else ""
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" '
                 f'text-anchor="{anchor}"{style}>{escape(s)}</text>')


def zone(x, y, w, h, key, label):
    fill, stroke = ZONES[key]
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="1.5"/>')
    text(x + 18, y + 28, label, 13, 700, stroke)


def box(x, y, w, h, key, title, lines=(), title_size=15, line_size=12.5, center=False, dashed=False):
    _, stroke = ZONES[key]
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{BG}" '
                 f'stroke="{stroke}" stroke-width="1.6"{dash}/>')
    cx = x + w / 2 if center else x + 14
    anchor = "middle" if center else "start"
    text(cx, y + 24, title, title_size, 700, INK, anchor)
    for i, ln in enumerate(lines):
        color = MUTED
        weight = 400
        if ln.startswith("**"):
            ln, color, weight = ln[2:], INK, 600
        text(cx, y + 46 + i * (line_size + 5.5), ln, line_size, weight, color, anchor)


def arrow(points, label=None, lx=None, ly=None, dashed=False, both=False, color=LINE):
    d = "M " + " L ".join(f"{px} {py}" for px, py in points)
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    start = ' marker-start="url(#ah-start)"' if both else ""
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{dash}{start} '
                 f'marker-end="url(#ah)"/>')
    if label:
        text(lx, ly, label, 11.5, 500, MUTED, "middle", italic=True)


# --------------------------------------------------------------------------- header
text(40, 50, "Zabuni — agent architecture", 28, 800)
text(40, 80, "Agentic value-for-money review of Kenyan public tenders over OCDS data · "
     "MCP tools · open-weights model · human approval gate · never awards", 15, 400, MUTED)

# --------------------------------------------------------------------------- 1 users
zone(40, 110, 290, 680, "users", "1 · USERS")
box(58, 150, 254, 150, "users", "Procurement officer", [
    "County Supply Chain",
    "Management unit",
    "Submits a review request:",
    "buyer, item, supplier,",
    "amount, budget line"])
box(58, 330, 254, 110, "users", "Languages", [
    "English or Kiswahili request",
    "memo (free-form memo OK)",
    "Planned against English data"])
box(58, 470, 254, 140, "users", "Tender Evaluation", [
    "Committee (TEC)",
    "Receives the filed",
    "value-for-money file only",
    "after a named approval"], dashed=True)
box(58, 640, 254, 130, "users", "Interfaces", [
    "CLI: zabuni run <request>",
    "MCP: any client (Claude",
    "Desktop, Goose) can use",
    "the Zabuni server directly"])

# --------------------------------------------------------------------------- 2 agent
zone(360, 110, 710, 680, "agent", "2 · AGENT ORCHESTRATOR — LangGraph")
nodes = [(385, 120, "intake"), (535, 120, "plan"), (685, 200, "agent ↔ tool loop"), (915, 130, "verify")]
captions = {"intake": ["reads memo via", "filesystem MCP"],
            "plan": ["LLM → JSON plan,", "validated, retried"],
            "agent ↔ tool loop": ["LLM chooses tools · cap 24 steps", "arg repair · errors fed back"],
            "verify": ["deterministic code", "re-checks citations"]}
for nx, nw, label in nodes:
    box(nx, 160, nw, 80, "agent", label, captions[label], center=True, title_size=15, line_size=11)
arrow([(505, 200), (533, 200)])
arrow([(655, 200), (683, 200)])
arrow([(885, 200), (913, 200)])
arrow([(980, 160), (980, 140), (800, 140), (800, 158)], "problems found → back to agent (≤ 2 rounds)", 890, 133)

box(385, 290, 320, 220, "agent", "LLM layer (model-agnostic)", [
    "**Qwen 2.5 7B (open weights)",
    "default · local via Ollama runtime",
    "data stays in-country · KES 0 API cost",
    "**Claude (Anthropic API)",
    "optional · frontier comparison runs",
    "**Scripted rule baseline",
    "offline demo & CI · labelled, never",
    "reported as a model run"])
box(735, 290, 310, 220, "agent", "State & memory", [
    "**LangGraph InMemorySaver",
    "checkpoints run state so the graph",
    "can pause at the gate and resume",
    "**Per-run state",
    "plan · messages · tool results ·",
    "findings keyed by run_id",
    "**Prompts",
    "agent_system.md · planner.md"])
arrow([(595, 240), (595, 288)], both=True)
arrow([(695, 240), (695, 288)], both=True)

box(385, 570, 660, 200, "agent", "MCP client — langchain-mcp-adapters (MultiServerMCPClient)", [
    "**Two stdio sessions held open for the whole run (JSON-RPC 2.0)",
    "Model sees only: 4 read tools + flag_finding + draft_report + filesystem reads",
    "Calls to tools the model is not given are refused and logged",
    "**AuditInterceptor — one JSONL line per MCP call from either server",
    "args · output excerpt · output sha256 · start time · duration · error",
    "→ runs/<run>/audit.jsonl   ·   tokens, time, cost → summary.json"])
arrow([(720, 240), (720, 568)], both=True)

# officer → intake
arrow([(312, 200), (383, 200)], "zabuni run", 348, 192)

# --------------------------------------------------------------------------- 3 MCP servers
zone(1100, 110, 460, 680, "mcp", "3 · MCP SERVERS (stdio transport)")
box(1118, 150, 424, 450, "mcp", "zabuni — BUILT (Python FastMCP)", [
    "**Read tools",
    "search_awards — FTS5 + fuzzy title search",
    "price_benchmark — robust z of log(amount) vs",
    "    median/MAD of comparables (≥ 5 or no verdict)",
    "supplier_profile — merges name variants,",
    "    flags bad IDs, share of buyer's awards",
    "detect_split_awards — just-under-threshold runs",
    "**Write tools (guard-railed server-side)",
    "flag_finding — refuses findings with no source;",
    "    re-resolves every OCDS citation",
    "draft_report — refuses award-making language",
    "**Irreversible · graph-only · token-gated",
    "file_to_committee — HMAC(run, approver, sha256)",
    "**Resource",
    "zabuni://dataset — provenance & data-quality counts",
    "**Built for reuse",
    "plain arguments in, JSON out, a source citation",
    "    on every record; rules enforced in the server",
    "standalone: uv run zabuni serve (any MCP client)",
    "Server audit → runs/server_audit.jsonl"], line_size=12.2)
box(1118, 625, 424, 145, "mcp", "filesystem — BORROWED (official)", [
    "@modelcontextprotocol/server-filesystem (Node)",
    "read_text_file · list_directory",
    "Sandboxed to workspace/inputs + workspace/drafts",
    "Reused for maintained path & symlink safety"])
arrow([(1045, 600), (1116, 600)], "stdio", 1080, 592, both=True)
arrow([(1045, 700), (1116, 700)], "stdio", 1080, 692, both=True)

# --------------------------------------------------------------------------- 4 human
zone(40, 820, 1030, 330, "human", "4 · HUMAN-IN-THE-LOOP & OUTPUTS")
flow = [(60, "Verified draft", ["findings + sources", "+ draft sha256"]),
        (270, "Human gate", ["LangGraph", "interrupt() — pauses"]),
        (480, "Named reviewer", ["types name and", "approve · reject · hold"]),
        (690, "Approval token", ["HMAC over run,", "approver, draft sha256"]),
        (900, "file_to_committee", ["called by the graph,", "never by the model"])]
for fx, title, lines in flow:
    box(fx, 870, 150 if fx == 900 else 180, 92, "human", title, lines, center=True, title_size=14, line_size=11.5)
for a, b in [(240, 268), (450, 478), (660, 688), (870, 898)]:
    arrow([(a, 916), (b, 916)])
text(555, 980, "reject / hold → END (nothing filed)", 11.5, 500, ZONES["human"][1], "middle", italic=True)
box(60, 1000, 480, 132, "human", "Every run produces", [
    "workspace/drafts/<run>.md — the value-for-money file",
    "runs/<run>/audit.jsonl — every tool & model call",
    "runs/<run>/summary.json — tokens, wall time, cost",
    "workspace/committee_outbox/<run>.md — only if approved"])
box(570, 1000, 480, 132, "human", "Guarantees", [
    "Approve without a name is treated as hold",
    "Edit one byte after approval → filing refused",
    "Filed copies are read-only, never overwritten",
    "Agent never awards or recommends a winner"])

# verify → gate (route through gutter between zones)
arrow([(1045, 200), (1082, 200), (1082, 860), (150, 860), (150, 868)],
      "self-check passed (or open problems shown to the human)", 640, 852)

# --------------------------------------------------------------------------- 5 data
zone(1100, 820, 460, 330, "data", "5 · DATA & STORAGE")
box(1118, 860, 200, 272, "data", "workspace/", [
    "inputs/ — request",
    "    memos (read-only",
    "    to the model)",
    "drafts/ — report",
    "committee_outbox/",
    "    — filed copies,",
    "    read-only"], line_size=12)
box(1338, 860, 204, 78, "data", "Kenya PPIP (OCDS)", [
    "via OCP Data Registry API", "~109k awards · ocds-5whusi"], line_size=11.5)
box(1338, 958, 204, 78, "data", "ingest.py", [
    "drop PII · pseudonymise", "keep + flag bad records"], line_size=11.5)
box(1338, 1056, 204, 76, "data", "SQLite", [
    "awards + FTS5 index", "dq_flags · benchmarkable"], line_size=11.5)
arrow([(1440, 938), (1440, 956)])
arrow([(1440, 1036), (1440, 1054)])

# servers ↔ data
arrow([(1295, 770), (1295, 858)], "reads", 1322, 808)
arrow([(1542, 380), (1580, 380), (1580, 1094), (1544, 1094)], both=True)
arrow([(1050, 935), (1092, 935), (1092, 1100), (1116, 1100)], dashed=True)

# --------------------------------------------------------------------------- legend
text(40, 1178, "Solid arrows: data / control flow · Double-headed: request ↔ response · "
     "Dashed: irreversible write after human approval", 12, 400, MUTED)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
       f'font-family="Inter, Helvetica, Arial, sans-serif">'
       '<defs>'
       f'<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
       f'<path d="M0 0 L10 5 L0 10 z" fill="{LINE}"/></marker>'
       f'<marker id="ah-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
       f'<path d="M10 0 L0 5 L10 10 z" fill="{LINE}"/></marker>'
       '</defs>'
       f'<rect width="{W}" height="{H}" fill="#fafbfc"/>' + "".join(parts) + "</svg>")

OUT.mkdir(exist_ok=True)
(OUT / "architecture.svg").write_text(svg, encoding="utf-8")
try:
    import cairosvg

    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT / "architecture.png"), output_width=W * 2)
    print("wrote docs/architecture.svg and docs/architecture.png")
except ImportError:
    print("wrote docs/architecture.svg (pip install cairosvg for the PNG)")
