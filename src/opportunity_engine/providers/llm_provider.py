"""LLMProvider: the only place in this codebase allowed to know about a
specific LLM vendor. Phase 1-2 makes zero LLM calls anywhere in the pipeline
(momentum, market proof, buildability/vendability, dedup, and ranking are all
plain Python/SQL/local-embeddings) -- `NoOpLLMProvider` enforces that as a
hard failure rather than a hope, and remains the provider used by every
Phase 1-2 code path.

`AnthropicProvider` (Phase 4) is the only implementation allowed to spend
money on LLM calls, and only for the on-demand single-opportunity deep-dive
dossier (agents/deep_dive_agent.py) -- never for daily ingestion/scoring.
Model policy is enforced here, not just documented: `ALLOWED_MODELS` is a
hard allowlist checked on every call, independent of the static
opus-never-mentioned test in tests/unit/test_architecture_no_llm_calls.py.
Haiku is the default; Sonnet is the absolute ceiling, used only when the
caller explicitly escalates with a written reason (see
agents/deep_dive_agent.py and the `deep-dive --escalate --reason` CLI flag).
Opus is never on the allowlist, in any phase.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import anthropic

MODEL_HAIKU = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-5"
ALLOWED_MODELS = frozenset({MODEL_HAIKU, MODEL_SONNET})

# USD per million tokens, (input, output). Standard list pricing -- not any
# time-limited introductory rate, since this table is meant to stay accurate
# as a steady-state reference. Update by hand if Anthropic's list pricing
# changes; there is no live pricing endpoint to poll.
_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    MODEL_HAIKU: (1.00, 5.00),
    MODEL_SONNET: (3.00, 15.00),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in _PRICING_USD_PER_MTOK:
        raise ValueError(f"no pricing on file for model {model!r}")
    input_rate, output_rate = _PRICING_USD_PER_MTOK[model]
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    model: str
    max_tokens: int
    purpose: str  # required -- feeds cost/reason logging
    system: str = ""  # kept separate from prompt so it can be prompt-cached
    output_schema: dict[str, Any] | None = None  # forces structured JSON output when set
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class NoOpLLMProvider(LLMProvider):
    """The provider used everywhere in Phase 1-2. Always raises: nothing in
    the daily ingest/dedup/score/rank pipeline is allowed to call an LLM,
    and this makes an accidental call a hard failure instead of a silent
    no-op."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError(
            "LLM calls are disabled in this phase of the Opportunity Engine "
            f"(model={request.model!r}, purpose={request.purpose!r}). "
            "See CLAUDE.md: the daily pipeline makes zero LLM calls by design "
            "-- only the on-demand deep-dive (Phase 4) uses AnthropicProvider."
        )


class AnthropicProvider(LLMProvider):
    """Real wiring for the Phase 4 on-demand deep-dive. Structured output via
    `output_config.format` (not text-parsing) and prompt caching on the
    stable system block, per the project's cost-discipline rules -- though
    caching only actually pays off once the system prompt clears the
    per-model minimum cacheable prefix (4096 tokens on Haiku 4.5; a short
    dossier-writer system prompt may sit under that and simply not cache,
    which is not an error, just no discount)."""

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        self._client = client if client is not None else anthropic.Anthropic(api_key=api_key)

    def complete(self, request: LLMRequest) -> LLMResponse:
        if request.model not in ALLOWED_MODELS:
            raise ValueError(
                f"model {request.model!r} is not on this project's allowed list "
                f"{sorted(ALLOWED_MODELS)} -- Opus is banned outright in any phase, "
                "and no other model may be used without deliberately adding it here."
            )

        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            create_kwargs["system"] = [
                {
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if request.output_schema is not None:
            create_kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": request.output_schema}
            }

        started = time.monotonic()
        response = self._client.messages.create(**create_kwargs)
        latency_ms = (time.monotonic() - started) * 1000.0

        text = next((block.text for block in response.content if block.type == "text"), "")
        cost_usd = compute_cost(
            request.model, response.usage.input_tokens, response.usage.output_tokens
        )
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
