# The workflow: from 26 days to about 20 minutes, then a person decides

## Who uses it
The Supply Chain Management (SCM) unit of a Kenyan county government, preparing the brief that the
Tender Evaluation Committee reads before it signs its evaluation report, and that the head of
procurement draws on for the professional opinion to the accounting officer. Under Kenya's Public
Procurement and Asset Disposal Act, 2015, the committee evaluates and the accounting officer awards.
Zabuni sits before both and decides nothing.

## Today vs with Zabuni

| Step today | Typical effort | With Zabuni | Who still does it |
|---|---|---|---|
| Find past awards for similar items across the county and other entities | days of portal searching and phone calls | `search_awards`, `price_benchmark` over every published award | — |
| Decide whether the price is reasonable | judgement on a handful of remembered prices | median, quartiles, robust z-score, cited comparables, data errors excluded and listed | committee judges |
| Check the supplier's history and whether it dominates this buyer | rarely done | `supplier_profile`: spellings merged, identifier problems, share of buyer's awards | committee asks |
| Check against the budget line | manual | budget variance in the benchmark, flagged with both lines cited | finance confirms |
| Spot split procurement | rarely done | `detect_split_awards` | committee asks |
| Write the brief | hours | `draft_report`, every finding sourced | reviewer edits or rejects |
| Approve and send | — | named person at the gate; file is token-signed and read-only | **a person, always** |

The bid-specific work — opening bids, checking mandatory documents, technical scoring — stays with
the committee. Bid documents are not published, and this tool does not pretend otherwise.

## Field validation (fill in before submitting)

The judges ask: *did you talk to anyone who does this job?* Record real conversations only.

| Date | Role (no names needed) | Office | What they said took longest | What they said about this file | Change made |
|---|---|---|---|---|---|
| | e.g. Head of SCM | County Government of … | | | |
| | e.g. Tender Evaluation Committee member | | | | |

Questions to ask: How many days from bid opening to the committee report? Which part is lookup
and which is judgement? Would you trust a flag without seeing its source? Who would sign at the gate?
What threshold do you use for request-for-quotation? What would make you reject this file?
