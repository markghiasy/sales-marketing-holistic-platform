from datetime import UTC, datetime

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
