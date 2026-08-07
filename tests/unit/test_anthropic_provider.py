"""AnthropicProvider tested against an injected fake client -- no real
network calls, no API key, no spent money. This is the same dependency-
injection pattern every collector uses for its HTTP layer.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from opportunity_engine.providers.llm_provider import (
    ALLOWED_MODELS,
    MODEL_HAIKU,
    MODEL_SONNET,
    AnthropicProvider,
    LLMRequest,
    compute_cost,
)


def test_compute_cost_haiku() -> None:
    # 1M input tokens @ $1, 1M output tokens @ $5
    assert compute_cost(MODEL_HAIKU, 1_000_000, 1_000_000) == pytest.approx(6.0)


def test_compute_cost_sonnet() -> None:
    assert compute_cost(MODEL_SONNET, 1_000_000, 1_000_000) == pytest.approx(18.0)


def test_compute_cost_scales_linearly_with_tokens() -> None:
    assert compute_cost(MODEL_HAIKU, 500_000, 0) == pytest.approx(0.5)
    assert compute_cost(MODEL_HAIKU, 0, 500_000) == pytest.approx(2.5)


def test_compute_cost_rejects_unpriced_model() -> None:
    with pytest.raises(ValueError, match="no pricing on file"):
        compute_cost("claude-opus-5", 1000, 1000)


def test_allowed_models_excludes_opus() -> None:
    assert not any("opus" in model for model in ALLOWED_MODELS)
    assert ALLOWED_MODELS == {MODEL_HAIKU, MODEL_SONNET}


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeAnthropicClient:
    def __init__(self, response_text: str = "the dossier text", model: str = MODEL_HAIKU) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self._response_text = response_text
        self._model = model
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.last_kwargs = kwargs
        return SimpleNamespace(
            content=[_FakeContentBlock(self._response_text)],
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        )


def test_complete_returns_text_and_cost() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="unused", client=fake_client)

    response = provider.complete(
        LLMRequest(
            prompt="Write a dossier.",
            model=MODEL_HAIKU,
            max_tokens=1000,
            purpose="phase4_dossier",
        )
    )

    assert response.text == "the dossier text"
    assert response.model == MODEL_HAIKU
    assert response.input_tokens == 100
    assert response.output_tokens == 50
    assert response.cost_usd == pytest.approx(compute_cost(MODEL_HAIKU, 100, 50))
    assert response.latency_ms >= 0.0


def test_complete_rejects_opus() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="unused", client=fake_client)

    with pytest.raises(ValueError, match="not on this project's allowed list"):
        provider.complete(
            LLMRequest(
                prompt="Write a dossier.",
                model="claude-opus-5",
                max_tokens=1000,
                purpose="phase4_dossier",
            )
        )
    assert fake_client.last_kwargs is None  # never reached the API call


def test_complete_rejects_arbitrary_model_strings() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="unused", client=fake_client)

    with pytest.raises(ValueError, match="not on this project's allowed list"):
        provider.complete(
            LLMRequest(
                prompt="Write a dossier.",
                model="gpt-4o",
                max_tokens=1000,
                purpose="phase4_dossier",
            )
        )


def test_complete_sends_cached_system_block_when_provided() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="unused", client=fake_client)

    provider.complete(
        LLMRequest(
            prompt="Write a dossier.",
            model=MODEL_HAIKU,
            max_tokens=1000,
            purpose="phase4_dossier",
            system="You are a dossier writer.",
        )
    )

    assert fake_client.last_kwargs is not None
    system = fake_client.last_kwargs["system"]
    assert system == [
        {
            "type": "text",
            "text": "You are a dossier writer.",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_complete_omits_system_when_not_provided() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="unused", client=fake_client)

    provider.complete(
        LLMRequest(
            prompt="Write a dossier.", model=MODEL_HAIKU, max_tokens=1000, purpose="phase4_dossier"
        )
    )

    assert fake_client.last_kwargs is not None
    assert "system" not in fake_client.last_kwargs


def test_complete_requests_structured_output_when_schema_provided() -> None:
    fake_client = _FakeAnthropicClient()
    provider = AnthropicProvider(api_key="unused", client=fake_client)
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}

    provider.complete(
        LLMRequest(
            prompt="Write a dossier.",
            model=MODEL_HAIKU,
            max_tokens=1000,
            purpose="phase4_dossier",
            output_schema=schema,
        )
    )

    assert fake_client.last_kwargs is not None
    assert fake_client.last_kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": schema}
    }


def test_complete_uses_sonnet_when_requested() -> None:
    fake_client = _FakeAnthropicClient(model=MODEL_SONNET)
    provider = AnthropicProvider(api_key="unused", client=fake_client)

    response = provider.complete(
        LLMRequest(
            prompt="Write a dossier.",
            model=MODEL_SONNET,
            max_tokens=1000,
            purpose="phase4_dossier_escalated",
        )
    )

    assert response.model == MODEL_SONNET
    assert fake_client.last_kwargs is not None
    assert fake_client.last_kwargs["model"] == MODEL_SONNET
