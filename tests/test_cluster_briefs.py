from datetime import UTC, datetime

import pytest

from adapters.ai_brief import (
    _build_prompt,
    _gather_input,
    generate_brief,
    person_keys_for_identities,
)
from adapters.inbox_query import get_detail
from tests.test_ai_brief import _FakeClient
from tests.test_candidate_clusters import edge, identities
from tests.test_reply_signal import _make_message, _make_thread


def seed(cur):
    a, b = identities(cur, 2)
    t = _make_thread(cur, "outlook")
    _make_message(cur, t, "outlook", "inbound", a, [a], datetime.now(UTC))
    cid = edge(cur, a, b)
    return a, b, t, cid


def client():
    return _FakeClient(
        {
            "summary": "Synthetic brief",
            "context": ["Synthetic context"],
            "topic": "Reply",
            "graph": {"org": None, "people": []},
            "urgency": 1,
        }
    )


def test_prompt_labels_uncertain_aggregation_without_fusing_content(db_conn):
    cur = db_conn.cursor()
    a, b, t, _ = seed(cur)
    _make_message(cur, t, "outlook", "outbound", b, [b], datetime.now(UTC))
    data = _gather_input(cur, a)
    assert data["reply_signal"]["provisional"] is True
    assert len(data["messages"]) == 1
    assert "not confirmed" in _build_prompt(data)


def test_rejecting_candidate_withholds_old_brief_and_regeneration_restores_it(db_conn):
    cur = db_conn.cursor()
    a, _b, _t, cid = seed(cur)
    generate_brief(cur, a, client=client())
    assert get_detail(cur, a).context == ["Synthetic context"]
    cur.execute("update link_candidate set status='rejected' where id=%s", (cid,))
    detail = get_detail(cur, a)
    assert detail.context != ["Synthetic context"]
    assert "changed" in detail.brief_notice
    generate_brief(cur, a, client=client())
    assert get_detail(cur, a).context == ["Synthetic context"]


def test_partner_message_invalidates_and_refreshes_dependent_contact_only(db_conn):
    cur = db_conn.cursor()
    a, b, t, _ = seed(cur)
    generate_brief(cur, a, client=client())
    _make_message(cur, t, "outlook", "outbound", b, [b], datetime.now(UTC))
    assert a in person_keys_for_identities(cur, {b})
    assert get_detail(cur, a).context != ["Synthetic context"]


def test_candidate_change_during_provider_call_cannot_publish_current_cache(db_conn):
    cur = db_conn.cursor()
    a, _b, _t, cid = seed(cur)
    fake = client()
    original = fake.messages.create

    def create(**kwargs):
        cur.execute("update link_candidate set status='rejected' where id=%s", (cid,))
        return original(**kwargs)

    fake.messages.create = create
    generate_brief(cur, a, client=fake)
    assert get_detail(cur, a).context != ["Synthetic context"]


def test_contact_api_exposes_evidence_separately_from_known_handles(db_conn, monkeypatch):
    from contextlib import contextmanager

    from scripts.onboarding import app

    cur = db_conn.cursor()
    a, b, _t, _ = seed(cur)

    @contextmanager
    def cursor():
        yield cur

    monkeypatch.setattr(app, "_db_cursor", cursor)
    response = app.create_app(testing=True).test_client().get("/contact/" + a)
    payload = response.get_json()
    assert len(payload["handles"]) == 1
    assert payload["identity_suggestions"][0]["identity_id"] == b
    assert payload["identity_suggestions"][0]["evidence"] == "same normalized name"
    assert payload["reply_signal"]["provisional"] is True


@pytest.mark.parametrize("during_generation", [False, True])
def test_adding_handle_to_confirmed_person_invalidates_cached_candidate_scope(
    db_conn, during_generation
):
    from adapters.contact_editor import add_contact_handle
    from adapters.resolution.merge import apply_merge
    from tests.test_reply_signal import _make_identity

    cur = db_conn.cursor()
    a, _b, _t, _cid = seed(cur)
    confirmed = _make_identity(cur, "outlook", "confirmed@example.test")
    key = apply_merge(cur, a, confirmed, method="manual_link", decision_kind="manual")
    generate_brief(cur, key, client=client())
    assert get_detail(cur, key).context == ["Synthetic context"]
    if during_generation:
        provider = client()
        create = provider.messages.create

        def insert_handle(**kwargs):
            add_contact_handle(cur, key, "new-alias@example.test")
            return create(**kwargs)

        provider.messages.create = insert_handle
        generate_brief(cur, key, client=provider)
    else:
        add_contact_handle(cur, key, "new-alias@example.test")
    assert get_detail(cur, key).context != ["Synthetic context"]


@pytest.mark.parametrize(
    "error_code", ["provider_failed", "invalid_response", "input_budget_exceeded"]
)
def test_stale_cache_does_not_hide_refresh_failure(db_conn, error_code):
    from adapters.inbox_query import list_conversations

    cur = db_conn.cursor()
    a, _b, _t, cid = seed(cur)
    cur.execute("update identity set display_name='Synthetic Contact' where id=%s", (a,))
    generate_brief(cur, a, client=client())
    cur.execute("update link_candidate set status='rejected' where id=%s", (cid,))
    status = "skipped" if error_code == "input_budget_exceeded" else "failed"
    cur.execute(
        "update ai_brief_status set status=%s,error_code=%s where person_key=%s",
        (status, error_code, a),
    )
    detail = get_detail(cur, a)
    row = next(r for r in list_conversations(cur) if r.person_key == a)
    for result in (detail, row):
        assert result.brief_status == status
        assert status in result.brief_notice
        assert "withheld" in result.brief_notice
    assert detail.context != ["Synthetic context"]


def test_outbound_participants_refresh_candidate_dependent_briefs(db_conn):
    from adapters.envelope import Channel, Direction, Envelope
    from adapters.store_writer import upsert

    cur = db_conn.cursor()
    a, b, _t, _cid = seed(cur)
    generate_brief(cur, a, client=client())
    touched = set()
    env = Envelope(
        Channel.outlook,
        "outbound-new",
        "sent-thread",
        Direction.outbound,
        datetime.now(UTC),
        "me@example.test",
        to_handles=["p1@example.test"],
        cc_handles=["cc@example.test"],
        body_text="New reply",
    )
    upsert(db_conn, env, "me@example.test", touched_identity_ids=touched)
    assert b in touched
    assert a in person_keys_for_identities(cur, touched)
    assert get_detail(cur, a).context != ["Synthetic context"]
