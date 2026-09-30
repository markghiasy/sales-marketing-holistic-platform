import psycopg

from adapters.resolution import run as runner
from tests.test_candidate_clusters import edge, identities


def test_run_attributes_new_candidates_and_keeps_failure_isolation(
    isolated_database_url, monkeypatch
):
    with psycopg.connect(isolated_database_url) as conn:
        a, b = identities(conn.cursor(), 2)
    monkeypatch.setattr(runner, "load_dotenv", lambda: None)
    monkeypatch.setattr(runner, "code_revision", lambda: "synthetic-revision", raising=False)
    monkeypatch.setattr(runner, "rule_exact_email_match", lambda cur: 0)
    monkeypatch.setattr(runner, "rule_contact_bridge", lambda cur: (edge(cur, a, b), 1)[1])
    monkeypatch.setattr(runner, "rule_signature_phone", lambda cur: 7)

    def broken(cur):
        raise ValueError("synthetic rule failure")

    monkeypatch.setattr(runner, "rule_outlook_dedupe", broken)
    monkeypatch.setattr(runner, "rule_linkedin_correlation", lambda cur: 0)
    monkeypatch.setattr(runner, "extract_structured_facts", lambda cur: 0)
    runner.run()
    with psycopg.connect(isolated_database_url) as conn:
        cur = conn.cursor()
        cur.execute("""select r.code_revision,c.rule_version,r.status,r.results
            from link_candidate c join resolution_run r on r.id=c.run_id""")
        revision, version, status, results = cur.fetchone()
        assert revision == "synthetic-revision"
        assert version
        assert status == "partial_failure"
        observations = next(r for r in results if r["rule"] == "signature phone")
        assert observations["reported_count"] == 7
        assert observations["candidates_written"] == 0
        assert observations["count_kind"] == "detections_only"


def test_legacy_candidate_provenance_is_unknown_not_invented(db_conn):
    cur = db_conn.cursor()
    a, b = identities(cur, 2)
    edge(cur, a, b)
    cur.execute("select run_id,rule_version from link_candidate")
    assert cur.fetchone() == (None, None)
