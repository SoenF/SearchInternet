from __future__ import annotations

from opportunity_engine.tools.scope_classifier import classify_scope


def test_neutral_text_has_zero_score_and_no_matches() -> None:
    result = classify_scope("A subscription tool to auto-renew SaaS SSL certificates.")
    assert result.score == 0.0
    assert result.narrow_matches == []
    assert result.broad_matches == []
    assert result.integration_count == 0


def test_narrow_scope_keyword_scores_positive() -> None:
    result = classify_scope("A Chrome extension that surfaces your saved bookmarks.")
    assert result.score > 0.0
    assert "extension" in result.narrow_matches


def test_broad_scope_keyword_scores_negative() -> None:
    result = classify_scope("An all-in-one platform for managing your entire business.")
    assert result.score < 0.0
    assert "platform" in result.broad_matches
    assert "all-in-one" in result.broad_matches


def test_multi_integration_mention_scores_negative() -> None:
    """The concrete case this was built from: CloudQuell's real pitch names
    six providers in one sentence -- a checkable proxy for build scope,
    independent of adjectives."""
    result = classify_scope(
        "Puts every cloud and AI dollar on one ledger -- AWS, OpenAI, "
        "Anthropic, Snowflake (Azure & GCP in beta)."
    )
    assert result.score < 0.0
    assert result.integration_count >= 3


def test_two_named_providers_alone_does_not_trigger_the_multi_integration_penalty() -> None:
    result = classify_scope("Syncs your Stripe and Slack data into one view.")
    assert result.integration_count == 2
    assert result.score == 0.0


def test_narrow_and_broad_signals_can_offset() -> None:
    result = classify_scope("A browser extension that's part of our all-in-one platform.")
    assert "extension" in result.narrow_matches
    assert "platform" in result.broad_matches
    assert result.score == 0.0


def test_score_is_clamped_to_the_documented_range() -> None:
    result = classify_scope(
        "A CLI wrapper extension that connects AWS, Azure, GCP, Snowflake, "
        "Salesforce as an all-in-one enterprise-grade platform ecosystem."
    )
    assert -1.0 <= result.score <= 1.0


def test_empty_text_is_handled_without_error() -> None:
    assert classify_scope("").score == 0.0
    assert classify_scope(None).score == 0.0
