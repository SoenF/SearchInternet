from __future__ import annotations

import pytest

from opportunity_engine.providers.llm_provider import LLMRequest, NoOpLLMProvider


def test_noop_llm_provider_always_raises() -> None:
    provider = NoOpLLMProvider()
    request = LLMRequest(
        prompt="draft an opportunity dossier",
        model="claude-haiku-4-5",
        max_tokens=1000,
        purpose="phase4_dossier",
    )
    with pytest.raises(RuntimeError, match="LLM calls are disabled"):
        provider.complete(request)
