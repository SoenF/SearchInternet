from __future__ import annotations

from opportunity_engine.tools.demand_signals import (
    DEMAND_ALTERNATIVE_REQUEST,
    DEMAND_EXISTING_SOLUTION_COMPLAINT,
    DEMAND_EXPLICIT_REQUEST,
    DEMAND_WILLINGNESS_TO_PAY,
    classify_demand,
    extract_demand_mentions,
)


def test_wish_there_was_is_an_explicit_request() -> None:
    mentions = extract_demand_mentions("I wish there was software for this.")
    assert any(m.demand_type == DEMAND_EXPLICIT_REQUEST for m in mentions)


def test_is_there_a_tool_is_an_explicit_request() -> None:
    mentions = extract_demand_mentions("Is there a tool that reconciles invoices?")
    assert any(m.demand_type == DEMAND_EXPLICIT_REQUEST for m in mentions)


def test_someone_should_build_is_an_explicit_request() -> None:
    mentions = extract_demand_mentions("Someone should build an app for this.")
    assert any(m.demand_type == DEMAND_EXPLICIT_REQUEST for m in mentions)


def test_how_can_i_automate_is_an_explicit_request() -> None:
    mentions = extract_demand_mentions("How can I automate my invoice reconciliation?")
    assert any(m.demand_type == DEMAND_EXPLICIT_REQUEST for m in mentions)


def test_alternative_to_named_product_is_an_alternative_request() -> None:
    mentions = extract_demand_mentions("Is there a good alternative to QuickBooks?")
    assert any(m.demand_type == DEMAND_ALTERNATIVE_REQUEST for m in mentions)


def test_too_expensive_is_an_existing_solution_complaint() -> None:
    mentions = extract_demand_mentions("This tool is too expensive for what it does.")
    assert any(m.demand_type == DEMAND_EXISTING_SOLUTION_COMPLAINT for m in mentions)


def test_doesnt_support_is_an_existing_solution_complaint() -> None:
    mentions = extract_demand_mentions("It doesn't support multi-currency invoices.")
    assert any(m.demand_type == DEMAND_EXISTING_SOLUTION_COMPLAINT for m in mentions)


def test_willingness_to_pay_extracts_a_dollar_amount() -> None:
    mentions = extract_demand_mentions("I would pay $50/month for something that did this.")
    willingness = [m for m in mentions if m.demand_type == DEMAND_WILLINGNESS_TO_PAY]
    assert len(willingness) == 1
    assert willingness[0].monthly_amount_usd == 50.0


def test_willingness_to_pay_handles_a_k_suffix() -> None:
    mentions = extract_demand_mentions("I'd pay $1k for the right solution.")
    willingness = [m for m in mentions if m.demand_type == DEMAND_WILLINGNESS_TO_PAY]
    assert willingness[0].monthly_amount_usd == 1000.0


def test_willingness_to_pay_without_an_amount_is_still_detected() -> None:
    mentions = extract_demand_mentions("I would pay for this if it existed.")
    willingness = [m for m in mentions if m.demand_type == DEMAND_WILLINGNESS_TO_PAY]
    assert len(willingness) == 1
    assert willingness[0].monthly_amount_usd is None


def test_i_built_a_tool_is_not_a_demand_signal() -> None:
    """The key false-positive this must avoid: narrating that you already
    built something must not be classified the same as asking for one."""
    assert extract_demand_mentions("I built a tool that does exactly this.") == []


def test_generic_positive_sentiment_is_not_willingness_to_pay() -> None:
    """Only an actual pay/would-pay statement counts -- generic praise must
    not be misread as a monetary commitment."""
    mentions = extract_demand_mentions("This app is great, I love it so much!")
    assert not any(m.demand_type == DEMAND_WILLINGNESS_TO_PAY for m in mentions)


def test_ordinary_text_has_no_demand_signal() -> None:
    assert extract_demand_mentions("A subscription tool to auto-renew SSL certificates.") == []


def test_none_and_empty_text_are_handled_without_error() -> None:
    assert extract_demand_mentions(None) == []
    assert extract_demand_mentions("") == []


def test_classify_demand_scores_an_explicit_request_highest() -> None:
    assessment = classify_demand("Is there a tool for this?")
    assert assessment.score == 0.6
    assert assessment.matched_types == [DEMAND_EXPLICIT_REQUEST]


def test_classify_demand_combines_multiple_signal_types() -> None:
    assessment = classify_demand(
        "Is there a tool for this? It's too expensive to hire someone to do it manually."
    )
    assert assessment.score == 0.9  # 0.6 (explicit request) + 0.3 (existing-solution complaint)
    assert set(assessment.matched_types) == {
        DEMAND_EXPLICIT_REQUEST,
        DEMAND_EXISTING_SOLUTION_COMPLAINT,
    }


def test_classify_demand_repeating_the_same_phrase_does_not_inflate_the_score() -> None:
    """Presence-based, not count-based: three "is there a tool" phrases in
    one post are not three times the signal."""
    assessment = classify_demand(
        "Is there a tool for X? Also is there a tool for Y? And is there a tool for Z?"
    )
    assert assessment.score == 0.6


def test_classify_demand_excludes_willingness_to_pay_from_its_own_score() -> None:
    """Willingness-to-pay feeds proof_events/market proof instead (see
    agents/scoring_agent.py) -- it must not also inflate this nudge, or the
    same piece of evidence would be double-counted across two channels."""
    assessment = classify_demand("I would pay $50/month for this.")
    assert assessment.score == 0.0
    assert DEMAND_WILLINGNESS_TO_PAY not in assessment.matched_types


def test_classify_demand_score_is_capped_at_one() -> None:
    assessment = classify_demand(
        "Is there a tool for this? I need an alternative to X. It doesn't support Y."
    )
    assert assessment.score == 1.0
