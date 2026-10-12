# Zabuni — one command to see it work:  make demo
MODEL ?= qwen2.5:7b
REQ   ?= workspace/inputs/req_002_maize_overpriced.md
RUN    = uv run --extra dev --extra frontier

.PHONY: demo demo-offline setup data kenya doctor test eval eval-baseline serve clean

demo: data            ## open-weights demo: pulls the model, runs the agent, stops at the human gate
	@command -v ollama >/dev/null || { echo "Install Ollama from https://ollama.com first"; exit 1; }
	ollama pull $(MODEL)
	ZABUNI_OLLAMA_MODEL=$(MODEL) $(RUN) zabuni run $(REQ)

demo-offline: data    ## same pipeline with the scripted rule policy instead of a model (no GPU, no Ollama)
	$(RUN) zabuni run $(REQ) --provider scripted

setup:
	@command -v uv >/dev/null || { echo "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	uv sync --extra dev --extra frontier

data: setup           ## build the synthetic sample database
	$(RUN) zabuni data

kenya: setup          ## download Kenya PPIP OCDS (2025) from the OCP Data Registry and load it
	./scripts/fetch_kenya.sh 2025

doctor:
	$(RUN) zabuni doctor --model $(MODEL)

test: data
	$(RUN) pytest -q

eval: data            ## full eval suite on the open-weights model (3 repeats per task)
	ZABUNI_OLLAMA_MODEL=$(MODEL) $(RUN) zabuni eval --provider ollama --repeats 3

eval-baseline: data   ## same suite with the scripted rule policy, for comparison
	$(RUN) zabuni eval --provider scripted --repeats 1

serve:                ## expose the Zabuni MCP server on stdio for any MCP client
	$(RUN) zabuni serve

clean:
	rm -rf runs/* workspace/drafts/* && chmod -R u+w workspace/committee_outbox && rm -f workspace/committee_outbox/*.md
