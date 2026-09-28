"""Regression cases for the 28 September production quality report."""

import contextlib
import uuid
from pathlib import Path

import pytest

from adapters.contact_editor import link_contact
from adapters.resolution.linkedin_correlation import rule_linkedin_dedupe
from adapters.resolution.merge import apply_merge, undo_merge
from adapters.resolution.rules import _propose_and_maybe_confirm


def identity(cur, channel, name="Alex Example"):
    cur.execute(
        "insert into identity (channel, handle, display_name) values (%s, %s, %s) returning id",
        (channel, str(uuid.uuid4()), name),
    )
    return str(cur.fetchone()[0])


def test_name_only_linkedin_rule_is_retired(db_conn):
    cur = db_conn.cursor()
    a, b = identity(cur, "linkedin"), identity(cur, "linkedin")
    assert rule_linkedin_dedupe(cur) == 0
    cur.execute("select count(*) from link_candidate where identity_a_id in (%s, %s)", (a, b))
    assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("case", ["new", "one_existing", "both_existing"])
def test_merge_method_recorded_for_each_structural_case_and_undo(db_conn, case):
    cur = db_conn.cursor()
    a, b = identity(cur, "outlook"), identity(cur, "whatsapp")
    originals = []
    for key in [a, b] if case == "both_existing" else [a] if case == "one_existing" else []:
        cur.execute("insert into person (primary_name) values ('Alex Example') returning id")
        person = cur.fetchone()[0]
        cur.execute("update identity set person_id=%s where id=%s", (person, key))
    cur.execute("select id,person_id from identity where id in (%s,%s) order by id", (a, b))
    originals = cur.fetchall()
    apply_merge(cur, a, b, method="exact_email", decision_kind="automatic")
    cur.execute(
        "select id,method,decision_kind from merge_log where identity_a_id=%s and identity_b_id=%s",
        (a, b),
    )
    log_id, method, decision_kind = cur.fetchone()
    assert (method, decision_kind) == ("exact_email", "automatic")
    undo_merge(cur, str(log_id))
    cur.execute("select id,person_id from identity where id in (%s,%s) order by id", (a, b))
    assert cur.fetchall() == originals


def test_automatic_and_manual_entry_points_record_provenance(db_conn):
    cur = db_conn.cursor()
    a, b = identity(cur, "outlook"), identity(cur, "whatsapp")
    _propose_and_maybe_confirm(cur, a, b, "exact_email", "shared email", None)
    cur.execute("select method,decision_kind from merge_log where identity_a_id=%s", (a,))
    assert cur.fetchone() == ("exact_email", "automatic")
    c, d = identity(cur, "outlook"), identity(cur, "linkedin")
    link_contact(cur, c, d)
    cur.execute("select method,decision_kind from merge_log where identity_a_id=%s", (c,))
    assert cur.fetchone() == ("manual_link", "manual")


def test_review_confirm_preserves_candidate_rule(db_conn, monkeypatch):
    from scripts.onboarding import app

    cur = db_conn.cursor()
    a, b = identity(cur, "outlook"), identity(cur, "linkedin")
    cur.execute(
        "insert into link_candidate(identity_a_id,identity_b_id,score,method,status) values (%s,%s,0.5,'linkedin_name_company','pending') returning id",
        (a, b),
    )
    candidate = str(cur.fetchone()[0])

    @contextlib.contextmanager
    def cursor():
        yield cur

    monkeypatch.setattr(app, "_db_cursor", cursor)
    response = (
        app.create_app(testing=True)
        .test_client()
        .post(f"/resolution/candidate/{candidate}/confirm")
    )
    assert response.status_code == 200
    cur.execute("select method,decision_kind from merge_log where identity_a_id=%s", (a,))
    assert cur.fetchone() == ("linkedin_name_company", "review")


def test_retirement_preserves_audit_and_only_withdraws_pending(db_conn):
    cur = db_conn.cursor()
    ids = {}
    for status in ("pending", "confirmed", "rejected"):
        a, b = identity(cur, "linkedin"), identity(cur, "linkedin")
        cur.execute(
            "insert into link_candidate(identity_a_id,identity_b_id,score,method,status,reason) values (%s,%s,0.6,'linkedin_same_channel_dedupe',%s,'original name match') returning id",
            (a, b, status),
        )
        ids[status] = cur.fetchone()[0]
    path = (
        Path(__file__).resolve().parents[1] / "db/migrations/0012_retire_linkedin_name_dedupe.sql"
    )
    cur.execute(path.read_text(encoding="utf-8"))
    cur.execute(
        "select id,status,reason from link_candidate where id=any(%s::uuid[])",
        (list(ids.values()),),
    )
    rows = {key: (status, reason) for key, status, reason in cur.fetchall()}
    assert rows[ids["pending"]][0] == "retired"
    assert "original name match" in rows[ids["pending"]][1]
    assert rows[ids["confirmed"]][0] == "confirmed"
    assert rows[ids["rejected"]][0] == "rejected"


def test_legacy_merge_rows_backfill_unknown_and_remain_reversible(db_conn):
    cur = db_conn.cursor()
    a, b = identity(cur, "outlook"), identity(cur, "whatsapp")
    apply_merge(cur, a, b, method="manual_link", decision_kind="manual")
    cur.execute("select id from merge_log where identity_a_id=%s", (a,))
    log_id = cur.fetchone()[0]
    # Recreate the pre-upgrade shape only inside this test's disposable schema.
    cur.execute("alter table merge_log drop column method, drop column decision_kind")
    cur.execute(
        (Path(__file__).resolve().parents[1] / "db/migrations/0010_merge_provenance.sql").read_text(
            encoding="utf-8"
        )
    )
    cur.execute("select method,decision_kind from merge_log where id=%s", (log_id,))
    assert cur.fetchone() == ("unknown_legacy", "unknown_legacy")
    undo_merge(cur, str(log_id))
    cur.execute("select person_id from identity where id in (%s,%s)", (a, b))
    assert all(row[0] is None for row in cur.fetchall())


def test_latest_brief_failure_stays_visible_after_contact_merge(db_conn):
    cur = db_conn.cursor()
    a, b = identity(cur, "outlook"), identity(cur, "whatsapp")
    for key, status, code, when in [
        (a, "success", None, "2026-09-26"),
        (b, "failed", "invalid_response", "2026-09-27"),
    ]:
        cur.execute(
            "insert into ai_brief_status(person_key,status,error_code,model,attempted_at) values (%s,%s,%s,'test-model',%s)",
            (key, status, code, when),
        )
    person = apply_merge(cur, a, b, method="manual_link", decision_kind="manual")
    cur.execute("select status,error_code from ai_brief_status where person_key=%s", (person,))
    assert cur.fetchone() == ("failed", "invalid_response")
    cur.execute("select count(*) from ai_brief_status where person_key in (%s,%s)", (a, b))
    assert cur.fetchone()[0] == 0


def test_undo_does_not_resurrect_a_retired_rules_candidate(db_conn):
    cur = db_conn.cursor()
    a, b = identity(cur, "linkedin"), identity(cur, "linkedin")
    cur.execute(
        "insert into link_candidate(identity_a_id,identity_b_id,score,method,status) "
        "values (%s,%s,0.6,'linkedin_same_channel_dedupe','confirmed') returning id",
        (a, b),
    )
    candidate = cur.fetchone()[0]
    apply_merge(cur, a, b, method="linkedin_same_channel_dedupe", decision_kind="review")
    cur.execute("select id from merge_log where identity_a_id=%s", (a,))
    undo_merge(cur, str(cur.fetchone()[0]))
    cur.execute("select status from link_candidate where id=%s", (candidate,))
    assert cur.fetchone()[0] == "retired"
    cur.execute("select person_id from identity where id in (%s,%s)", (a, b))
    assert all(row[0] is None for row in cur.fetchall())


@pytest.mark.parametrize("newer_status,omitted", [("success", 0), ("truncated", 12)])
def test_merge_keeps_newest_brief_and_its_matching_coverage(db_conn, newer_status, omitted):
    cur = db_conn.cursor()
    a, b = identity(cur, "outlook"), identity(cur, "whatsapp")
    cur.execute("insert into person(primary_name) values ('Alex') returning id")
    survivor = str(cur.fetchone()[0])
    cur.execute("update identity set person_id=%s where id=%s", (survivor, a))
    for key, summary, status, count, when in [
        (survivor, "old partial brief", "truncated", 25, "2026-09-26"),
        (b, "newer brief", newer_status, omitted, "2026-09-27"),
    ]:
        cur.execute(
            "insert into ai_brief(person_key,summary,context,topic,graph,urgency,model,prompt_version,generated_at) "
            "values (%s,%s,'[]','General','{}',1,'test-model','v3',%s)",
            (key, summary, when),
        )
        cur.execute(
            "insert into ai_brief_status(person_key,status,model,omitted_messages,attempted_at) "
            "values (%s,%s,'test-model',%s,%s)",
            (key, status, count, when),
        )
    assert apply_merge(cur, a, b, method="manual_link", decision_kind="manual") == survivor
    cur.execute(
        "select b.summary,s.status,s.omitted_messages from ai_brief b "
        "join ai_brief_status s using(person_key) where b.person_key=%s",
        (survivor,),
    )
    assert cur.fetchone() == ("newer brief", newer_status, omitted)
