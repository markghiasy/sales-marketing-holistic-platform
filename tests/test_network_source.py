"""Real PostgreSQL boundary tests: never load an application .env."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest


def repository(dsn, **kwargs):
    from adapters.network.source import SourceRepository
    return SourceRepository(dsn, **kwargs)


@pytest.fixture
def source_seed(isolated_database_url):
    ids = {k: str(uuid4()) for k in ('owner', 'self', 'contact', 'thread', 'message')}
    with psycopg.connect(isolated_database_url) as conn:
        conn.execute('insert into person(id, primary_name) values (%s, %s)', (ids['owner'], 'Owner'))
        for key, name, own in [('self', 'Owner', True), ('contact', 'Morgan', False)]:
            conn.execute('insert into identity(id,channel,handle,display_name,person_id,is_self) values (%s,%s,%s,%s,%s,%s)',
                         (ids[key], 'outlook', key+'@example.test', name, ids['owner'] if own else None, own))
        conn.execute('insert into thread(id,channel,external_id) values (%s,%s,%s)', (ids['thread'], 'outlook', 't'))
        conn.execute("insert into message(id,thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) values (%s,%s,'outlook','m','inbound','2020-01-01',%s,'Project note','{\"private_raw\":true}','2026-09-30')",
                     (ids['message'], ids['thread'], ids['contact']))
        conn.execute("insert into message_participant values (%s,%s,'to')", (ids['message'], ids['self']))
    return isolated_database_url, ids


def test_source_snapshot_is_paged_complete_without_raw_and_optional_brief(source_seed):
    dsn, ids = source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute('drop table if exists ai_brief_status')
    repo = repository(dsn)
    pages = list(repo.snapshot_pages(1))
    assert all(not p.complete_kinds for p in pages[:-1])
    assert 'message' in pages[-1].complete_kinds
    rows = [r for p in pages for r in p.records if r.kind == 'message']
    assert len(rows) == 1 and rows[0].id == ids['message']
    assert 'raw' not in rows[0].payload
    assert rows[0].payload['participants'] == [{'identity_id': ids['self'], 'role': 'to'}]
    assert pages[-1].manifests['message'] == frozenset([ids['message']])
    assert repo.audit()['owner_id'] == 'person:'+ids['owner']


def test_source_transactions_reject_writes(source_seed):
    dsn, _ = source_seed
    with repository(dsn).connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("update person set primary_name='Changed'")


def test_source_binding_and_missing_required_schema_are_explicit(source_seed):
    from adapters.network.source import SourceError
    dsn, _ = source_seed
    with pytest.raises(SourceError, match='source_binding_mismatch'):
        repository(dsn, expected_binding='wrong').audit()
    with psycopg.connect(dsn) as conn:
        conn.execute('alter table message rename to unavailable_message')
    with pytest.raises(SourceError, match='missing_required_table'):
        repository(dsn).audit()


def test_equal_timestamp_pagination_and_late_old_sent_message(source_seed):
    from adapters.network.source import Cursor
    dsn, ids = source_seed
    at = datetime(2026, 9, 30, tzinfo=UTC)
    with psycopg.connect(dsn) as conn:
        for n in range(5):
            conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,body_text,raw,ingested_at) values (%s,'outlook',%s,'inbound','2019-01-01','late','{}',%s)", (ids['thread'], str(n), at))
    repo = repository(dsn)
    cursor, seen = None, set()
    for _ in range(10):
        batch = repo.incremental(cursor, lookback_seconds=300, limit=2)
        seen.update(r.id for r in batch.records)
        cursor = batch.cursor
    assert len(seen) == 6
    assert cursor.ingested_at == at
    with psycopg.connect(dsn) as conn:
        late_id = conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,body_text,raw,ingested_at) values (%s,'outlook','late-commit','inbound','2019-01-01','new','{}',%s) returning id", (ids['thread'], at-timedelta(seconds=1))).fetchone()[0]
    batch = repo.incremental(cursor, lookback_seconds=300, limit=20)
    assert str(late_id) in {r.id for r in batch.records}
    assert batch.cursor == cursor


def test_dependencies_detect_participants_identity_hide_and_deleted_message(source_seed):
    dsn, ids = source_seed
    repo = repository(dsn)
    rows = [r for p in repo.snapshot_pages(10) for r in p.records]
    dependencies = {r.key: r.fingerprint for r in rows}
    dependencies['contact_hidden:'+ids['contact']] = 'absent'
    assert repo.validate(dependencies)
    with psycopg.connect(dsn) as conn:
        conn.execute('insert into contact_hidden(contact_key) values (%s)', (ids['contact'],))
    assert not repo.validate(dependencies)
    with psycopg.connect(dsn) as conn:
        conn.execute('delete from contact_hidden')
        conn.execute("update message_participant set role='cc'")
    assert not repo.validate(dependencies)
    with psycopg.connect(dsn) as conn:
        conn.execute("update message_participant set role='to'")
        conn.execute("update identity set display_name='Changed' where id=%s", (ids['contact'],))
    assert not repo.validate(dependencies)
    with psycopg.connect(dsn) as conn:
        conn.execute("update identity set display_name='Morgan' where id=%s", (ids['contact'],))
        conn.execute('delete from message_participant')
        conn.execute('delete from message')
    assert not repo.validate(dependencies)


def test_interrupted_snapshot_never_authorizes_deletion(source_seed):
    dsn, _ = source_seed
    pages = repository(dsn).snapshot_pages(1)
    page = next(pages)
    pages.close()
    assert page.complete_kinds == frozenset()
    assert page.manifests == {}


def test_audit_without_self_reports_unresolved(source_seed):
    from adapters.network.source import SourceError
    dsn, _ = source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute('update identity set is_self=false')
    with pytest.raises(SourceError, match='owner_unresolved'):
        repository(dsn).audit()


def test_unmerged_self_aliases_have_stable_local_owner_without_merging_contacts(source_seed):
    dsn, ids = source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute("insert into identity(channel,handle,is_self) values ('whatsapp','self-alias',true)")
    audit = repository(dsn).audit()
    assert audit['owner_id'].startswith('owner:')
    assert audit['self_identity_count'] == 2
    with psycopg.connect(dsn) as conn:
        assert conn.execute('select person_id from identity where id=%s', (ids['contact'],)).fetchone()[0] is None
