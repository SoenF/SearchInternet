from __future__ import annotations

from leadbridge.dedup import in_memory_store


def test_unseen_lead_is_not_already_processed() -> None:
    store = in_memory_store()
    assert store.already_processed("123") is False


def test_marked_lead_is_reported_as_already_processed() -> None:
    store = in_memory_store()
    store.mark_processed("123", "2026-08-07T00:00:00Z")
    assert store.already_processed("123") is True


def test_marking_the_same_lead_twice_does_not_raise() -> None:
    """Facebook can redeliver the same webhook notification on timeout --
    this must be idempotent, not throw an integrity error."""
    store = in_memory_store()
    store.mark_processed("123", "2026-08-07T00:00:00Z")
    store.mark_processed("123", "2026-08-07T00:00:05Z")
    assert store.already_processed("123") is True


def test_different_leads_are_tracked_independently() -> None:
    store = in_memory_store()
    store.mark_processed("123", "2026-08-07T00:00:00Z")
    assert store.already_processed("456") is False
