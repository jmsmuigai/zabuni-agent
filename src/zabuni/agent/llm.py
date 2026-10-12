"""Model factory. Default is an open-weights model served locally by Ollama, so procurement data
never leaves the machine. A frontier model can be run alongside for comparison."""
from __future__ import annotations

import os

DEFAULTS = {
    "ollama": os.getenv("ZABUNI_OLLAMA_MODEL", "qwen2.5:7b"),
    "anthropic": os.getenv("ZABUNI_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
}


def make_llm(provider: str = "ollama", model: str | None = None):
    provider = provider.lower()
    model = model or DEFAULTS.get(provider)
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            temperature=float(os.getenv("ZABUNI_TEMPERATURE", 0)),
            num_ctx=int(os.getenv("ZABUNI_NUM_CTX", 16384)),  # Ollama's 2k default truncates tool results
            base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            seed=int(os.getenv("ZABUNI_SEED", 0)) or None,
        ), model
    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:  # pragma: no cover
            raise SystemExit("pip install 'zabuni-agent[frontier]' to use the anthropic provider") from e
        return ChatAnthropic(model=model, temperature=0, max_tokens=4096), model
    if provider == "scripted":  # rule-based stand-in, NOT a model: tests and offline demo only
        from zabuni.agent.scripted import ScriptedModel

        return ScriptedModel(), "scripted-baseline"
    raise SystemExit(f"Unknown provider '{provider}'. Use 'ollama' (default), 'anthropic' or 'scripted'.")
