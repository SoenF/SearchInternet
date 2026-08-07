from __future__ import annotations

from leadbridge.tenants import in_memory_store


def test_unknown_page_id_returns_none() -> None:
    store = in_memory_store()
    assert store.get_tenant("unknown") is None


def test_upserted_tenant_is_retrievable_and_active() -> None:
    store = in_memory_store()
    store.upsert_tenant(
        page_id="page1",
        fb_page_access_token="token1",
        make_webhook_url="https://hook.example/1",
        stripe_customer_id="cus_1",
        created_at="2026-08-07T00:00:00Z",
    )
    tenant = store.get_tenant("page1")
    assert tenant is not None
    assert tenant.fb_page_access_token == "token1"
    assert tenant.make_webhook_url == "https://hook.example/1"
    assert tenant.status == "active"


def test_upsert_on_an_existing_page_id_updates_it_and_reactivates() -> None:
    store = in_memory_store()
    store.upsert_tenant(
        page_id="page1",
        fb_page_access_token="old_token",
        make_webhook_url="https://hook.example/old",
        stripe_customer_id="cus_1",
        created_at="2026-08-07T00:00:00Z",
    )
    store.deactivate_by_customer_id("cus_1")
    store.upsert_tenant(
        page_id="page1",
        fb_page_access_token="new_token",
        make_webhook_url="https://hook.example/new",
        stripe_customer_id="cus_1",
        created_at="2026-08-07T01:00:00Z",
    )
    tenant = store.get_tenant("page1")
    assert tenant is not None
    assert tenant.fb_page_access_token == "new_token"
    assert tenant.status == "active"


def test_deactivate_by_customer_id_marks_tenant_inactive() -> None:
    store = in_memory_store()
    store.upsert_tenant(
        page_id="page1",
        fb_page_access_token="token1",
        make_webhook_url="https://hook.example/1",
        stripe_customer_id="cus_1",
        created_at="2026-08-07T00:00:00Z",
    )
    store.deactivate_by_customer_id("cus_1")
    tenant = store.get_tenant("page1")
    assert tenant is not None
    assert tenant.status == "inactive"


def test_deactivate_by_unknown_customer_id_does_not_raise() -> None:
    store = in_memory_store()
    store.deactivate_by_customer_id("cus_does_not_exist")
