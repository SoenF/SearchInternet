"""Validates the sentence-transformers/torch pinning end to end.

Requires the model weights to already be cached locally (a one-time,
network-requiring step documented in README.md -- not something CI or a fresh
clone gets for free). HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE are forced here so a
cache miss fails loudly with a clear error instead of silently reaching the
network -- belt and suspenders on top of pytest-socket's global block.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import pytest

from opportunity_engine.providers.embedding_provider import LocalE5EmbeddingProvider


@pytest.fixture(scope="module")
def provider() -> LocalE5EmbeddingProvider:
    try:
        return LocalE5EmbeddingProvider()
    except OSError as exc:  # local cache miss under forced-offline mode
        pytest.skip(f"multilingual-e5-base not cached locally yet: {exc}")


def test_dimensions_match_schema(provider: LocalE5EmbeddingProvider) -> None:
    assert provider.dimensions == 768


def test_similar_sentences_have_high_cosine_similarity(
    provider: LocalE5EmbeddingProvider,
) -> None:
    vectors = provider.embed(
        [
            "I wish there was a tool to automatically renew my SaaS SSL certificates",
            "Is there a tool that automatically renews SSL certs for my SaaS?",
            "My cat knocked a plant off the balcony this morning",
        ]
    )
    a, b, c = (np.array(v) for v in vectors)
    similar_pair = float(np.dot(a, b))
    dissimilar_pair = float(np.dot(a, c))
    assert similar_pair > 0.85
    assert similar_pair > dissimilar_pair


def test_multilingual_translation_pair_has_high_cosine_similarity(
    provider: LocalE5EmbeddingProvider,
) -> None:
    """Arbitrage detection needs to compare JP/KR/BR content against EN --
    multilingual support is a hard requirement, not a nicety."""
    vectors = provider.embed(
        [
            "How much does this app cost per month?",
            "このアプリの月額料金はいくらですか?",
        ]
    )
    en, ja = (np.array(v) for v in vectors)
    assert float(np.dot(en, ja)) > 0.75
