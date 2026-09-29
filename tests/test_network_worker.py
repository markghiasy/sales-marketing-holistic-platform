from datetime import UTC, datetime, timedelta
from dataclasses import replace

import psycopg
import pytest

from adapters.network.source import SourceRepository
from adapters.network.store import PostgresNetworkStore

NOW=datetime(2026,9,30,12,tzinfo=UTC)


def test_worker_lease_does_not_hold_an_idle_transaction(network_database):
    worker,source,store,ids=setup(network_database)
    with worker.lease() as held:
        assert held
        with psycopg.connect(network_database[0]) as conn:
            rows=conn.execute("select a.xact_start from pg_stat_activity a where a.pid in (select pid from pg_locks where locktype='advisory' and granted) and a.pid<>pg_backend_pid() and a.datname=current_database() and a.query like '%pg_try_advisory_lock%'").fetchall()
            assert rows and all(row[0] is None for row in rows)


def setup(network_database, **kwargs):
    from adapters.network.worker import NetworkWorker
    dsn,ids=network_database
    source=SourceRepository(dsn)
    store=PostgresNetworkStore(dsn,source.audit()['binding'])
    store.initialize()
    return NetworkWorker(source,store,**kwargs),source,store,ids


def test_initial_backfill_replay_restart_and_forward_update(network_database):
    from adapters.network.worker import NetworkWorker
    worker,source,store,ids=setup(network_database)
    first=worker.tick(NOW)
    assert first.version>0
    assert len(store.capture(('identity:'+ids['contact'],),30).data['messages'])==1
    assert worker.tick(NOW+timedelta(seconds=59)).version==first.version
    with psycopg.connect(network_database[0]) as conn:
        mid=conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) select thread_id,channel,'new',direction,%s,from_identity_id,'Follow up','{}',%s from message returning id",(NOW,NOW)).fetchone()[0]
        conn.execute("insert into message_participant values (%s,%s,'to')",(mid,ids['self']))
    worker.tick(NOW+timedelta(seconds=60))
    version=store.status().version
    assert len(store.capture(('identity:'+ids['contact'],),30).data['messages'])==2
    restarted=NetworkWorker(source,store)
    assert restarted.tick(NOW+timedelta(seconds=61)).version==version
    assert restarted.tick(NOW+timedelta(seconds=120)).version==version


def test_incomplete_reconciliation_keeps_previous_graph_and_checkpoint(network_database):
    worker,source,store,ids=setup(network_database)
    worker.tick(NOW)
    version,cursor=store.status().version,store.checkpoint()
    original=source.snapshot_pages
    def interrupted(page_size=500):
        pages=original(page_size)
        yield next(pages)
        pages.close()
        raise OSError('fixture outage')
    source.snapshot_pages=interrupted
    status=worker.tick(NOW+timedelta(seconds=900))
    assert status.version==version and status.error_code=='source_unavailable'
    assert store.checkpoint()==cursor
    assert store.capture(('identity:'+ids['contact'],),30).data['messages']
    source.snapshot_pages=original
    assert worker.tick(NOW+timedelta(seconds=901)).error_code is None


def test_metadata_hide_and_full_reconciliation_delete_support(network_database):
    worker,source,store,ids=setup(network_database)
    worker.tick(NOW)
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('insert into contact_hidden(contact_key) values (%s)',(ids['contact'],))
    worker.tick(NOW+timedelta(seconds=300))
    assert not store.capture(('identity:'+ids['contact'],),30).data['messages']
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('delete from contact_hidden')
    worker.tick(NOW+timedelta(seconds=600))
    assert store.capture(('identity:'+ids['contact'],),30).data['messages']
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('delete from message_participant')
        conn.execute('delete from message')
    worker.tick(NOW+timedelta(seconds=1500))
    assert not store.capture(('identity:'+ids['contact'],),30).data['claims']


def test_worker_exclusion_and_source_failure_does_not_advance_schedule(network_database):
    worker,source,store,_=setup(network_database)
    with worker.lease() as held:
        assert held
        with worker.lease() as other:
            assert not other
    original=source.snapshot_pages
    source.snapshot_pages=lambda *_: (_ for _ in ()).throw(OSError('offline'))
    assert worker.tick(NOW).error_code=='source_unavailable'
    assert store.checkpoint() is None
    source.snapshot_pages=original
    assert worker.tick(NOW+timedelta(seconds=1)).version>0


def test_bounded_backfill_refuses_oversized_source_without_partial_publication(network_database):
    worker,source,store,_=setup(network_database,max_records=1)
    status=worker.tick(NOW)
    assert status.error_code=='source_budget_exceeded'
    assert status.version==0 and store.records()==()


def test_incremental_projection_does_not_remove_unrelated_contacts(network_database):
    dsn,ids=network_database
    with psycopg.connect(dsn) as conn:
        another=conn.execute("insert into identity(channel,handle,display_name) values ('outlook','other@test','Other') returning id").fetchone()[0]
        mid=conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) select thread_id,channel,'other',direction,sent_at,%s,'Unrelated','{}',ingested_at from message returning id",(another,)).fetchone()[0]
        conn.execute("insert into message_participant values (%s,%s,'to')",(mid,ids['self']))
    worker,source,store,_=setup(network_database)
    worker.tick(NOW)
    with psycopg.connect(dsn) as conn:
        conn.execute("update message set body_text='Updated' where id=%s",(ids['message'],))
    worker.tick(NOW+timedelta(seconds=60))
    snapshot=store.capture(('identity:'+str(another),),30)
    assert any(m['text']=='Unrelated' for m in snapshot.data['messages'])


def test_corrected_sender_reprojects_both_old_and_new_contacts(network_database):
    dsn,ids=network_database
    with psycopg.connect(dsn) as conn:
        other=conn.execute("insert into identity(channel,handle,display_name) values ('outlook','other@test','Other') returning id").fetchone()[0]
        for external,author in [('old-kept',ids['contact']),('other-kept',other)]:
            mid=conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) select thread_id,channel,%s,direction,sent_at,%s,'Retained','{}',ingested_at from message where id=%s returning id",(external,author,ids['message'])).fetchone()[0]
            conn.execute("insert into message_participant values (%s,%s,'to')",(mid,ids['self']))
    worker,source,store,_=setup(network_database)
    worker.tick(NOW)
    with psycopg.connect(dsn) as conn:
        conn.execute('update message set from_identity_id=%s where id=%s',(other,ids['message']))
    worker.tick(NOW+timedelta(seconds=60))
    snapshot=store.capture(('identity:'+ids['contact'],),30)
    assert any(c['target']=='identity:'+ids['contact'] for c in snapshot.data['claims'])
    assert all(len(c['evidence_ids'])==1 for c in snapshot.data['claims'] if c['target']=='identity:'+ids['contact'])


def test_old_late_commit_outside_lookback_recovered_by_reconciliation(network_database):
    worker,source,store,ids=setup(network_database)
    worker.tick(NOW)
    with psycopg.connect(network_database[0]) as conn:
        mid=conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) select thread_id,channel,'late',direction,sent_at,from_identity_id,'Late committed','{}','2026-09-25' from message returning id").fetchone()[0]
        conn.execute("insert into message_participant values (%s,%s,'to')",(mid,ids['self']))
    worker.tick(NOW+timedelta(seconds=60))
    assert len(store.capture(('identity:'+ids['contact'],),30).data['messages'])==1
    worker.tick(NOW+timedelta(seconds=900))
    assert len(store.capture(('identity:'+ids['contact'],),30).data['messages'])==2
