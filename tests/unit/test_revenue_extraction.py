from __future__ import annotations

from opportunity_engine.tools.revenue_extraction import extract_revenue_mentions


def test_extracts_plain_mrr_mention() -> None:
    results = extract_revenue_mentions("We just hit $5k MRR after 6 months of grinding.")
    assert len(results) == 1
    assert results[0].monthly_amount_usd == 5000.0


def test_extracts_arr_and_converts_to_monthly() -> None:
    results = extract_revenue_mentions("Proud to say we crossed $120k ARR this quarter.")
    assert len(results) == 1
    assert results[0].monthly_amount_usd == 10_000.0


def test_extracts_per_month_phrasing() -> None:
    results = extract_revenue_mentions("Currently doing about $2,500 per month in revenue.")
    assert len(results) == 1
    assert results[0].monthly_amount_usd == 2500.0


def test_extracts_slash_mo_phrasing() -> None:
    results = extract_revenue_mentions("Bootstrapped to $800/mo so far.")
    assert len(results) == 1
    assert results[0].monthly_amount_usd == 800.0


def test_no_match_returns_empty_list() -> None:
    assert extract_revenue_mentions("I wish there was a tool that did X.") == []


def test_dollar_amount_without_revenue_period_is_not_matched() -> None:
    assert extract_revenue_mentions("I paid $50 for a domain name.") == []


def test_extracts_multiple_mentions_in_one_text() -> None:
    text = "Went from $1k MRR to $8k MRR in a year."
    results = extract_revenue_mentions(text)
    assert [r.monthly_amount_usd for r in results] == [1000.0, 8000.0]
