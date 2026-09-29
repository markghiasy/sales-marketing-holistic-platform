from dataclasses import replace
from datetime import UTC, datetime

import psycopg
import pytest

from adapters.network.source import SourceRepository


def opened(network_database):
    from adapters.network.store import PostgresNetworkStore
    dsn, _ = network_database
    source = SourceRepository(dsn)
    store = PostgresNetworkStore(dsn, source.audit()['binding'])
    store.initialize()
    return source, store


def test_explicit_initialization_binding_and_schema_version(network_database):
    from adapters.network.store import PostgresNetworkStore, StoreError
    source, store = opened(network_database)
    assert store.status().version == 0
    store.initialize()
    with pytest.raises(StoreError, match='source_binding_mismatch'):
        PostgresNetworkStore(network_database[0], 'other').status()
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('update network.state set schema_version=999')
    with pytest.raises(StoreError, match='unsupported_schema_version'):
        store.initialize()


def test_replay_restart_atomic_checkpoint_and_partial_manifest(network_database):
    from adapters.network.store import PostgresNetworkStore
    source, store = opened(network_database)
    pages = list(source.snapshot_pages(2))
    for batch in pages:
        store.apply(batch)
    before = store.status().version
    for batch in pages:
        store.apply(batch)
    assert store.status().version == before
    reopened = PostgresNetworkStore(network_database[0], source.audit()['binding'])
    assert reopened.checkpoint() == pages[-1].cursor
    assert len(reopened.records('message')) == 1
    partial = replace(pages[-1], complete_kinds=frozenset(), manifests={'message':frozenset()})
    reopened.apply(partial)
    assert len(reopened.records('message')) == 1
    complete = replace(partial, complete_kinds=frozenset({'message'}))
    reopened.apply(complete)
    assert reopened.records('message') == ()


def test_failed_transaction_rolls_back_sources_projection_version_checkpoint(network_database):
    from adapters.network.store import Projection
    source, store = opened(network_database)
    batch = next(source.snapshot_pages(20))
    invalid = Projection(entities=({'id':'bad'},), assertions=(), evidence=(), dependencies={})
    with pytest.raises((ValueError, KeyError)):
        store.apply(batch, invalid)
    assert store.status().version == 0
    assert store.records('person') == ()
    assert store.checkpoint() is None


def test_derived_writer_cannot_write_source_business_tables(network_database):
    _, store = opened(network_database)
    with psycopg.connect(network_database[0]) as conn:
        schema = conn.execute('select current_schema()').fetchone()[0]
    with store.connection() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(psycopg.sql.SQL('update {} set primary_name=%s').format(psycopg.sql.Identifier(schema,'person')), ('Wrong',))
    with psycopg.connect(network_database[0]) as conn:
        assert conn.execute('select primary_name from person').fetchone()[0] == 'Owner'


def test_dependency_versions_and_concurrent_reader(network_database):
    from adapters.network.store import Projection
    source, store = opened(network_database)
    pages = list(source.snapshot_pages(30))
    for page in pages:
        store.apply(page)
    record = store.records('message')[0]
    deps = {record.key: record.fingerprint}
    assert store.dependencies_current(deps)
    with store.connection() as conn:
        conn.execute('update network.state set version=999')
        assert store.status().version != 999
        conn.rollback()
    with psycopg.connect(network_database[0]) as conn:
        conn.execute("update message set body_text='corrected'")
    for page in source.snapshot_pages(30):
        store.apply(page)
    assert not store.dependencies_current(deps)


def test_projection_rebuild_preserves_reviews_and_read_snapshot(network_database):
    from adapters.network.store import Projection
    source, store = opened(network_database)
    for page in source.snapshot_pages(30):
        store.apply(page)
    records = store.records()
    dep = {r.key:r.fingerprint for r in records}
    projection = Projection(entities=({'id':'person:test','kind':'person','name':'Test'},),
        assertions=(), evidence=(), dependencies={'node:person:test':tuple(dep)})
    empty = replace(source.metadata(), records=(), manifests={}, complete_kinds=frozenset())
    version = store.apply(empty, projection)
    snapshot = store.capture(('person:test',), 20)
    assert snapshot.version == version
    assert snapshot.data['nodes'][0]['name'] == 'Test'
    with store.connection() as conn:
        conn.execute("insert into network.review_event(proposal_id,decision,payload) values ('p','reject','{}')")
    store.apply(empty, projection)
    assert len(store.reviews()) == 1
    assert store.capture(('person:test',), 20).data['nodes'][0]['name'] == 'Test'


def test_initialization_rejects_source_public_write_grants(network_database):
    from adapters.network.store import PostgresNetworkStore, StoreError
    dsn, _ = network_database
    with psycopg.connect(dsn) as conn:
        conn.execute('grant update on person to public')
    store = PostgresNetworkStore(dsn, SourceRepository(dsn).audit()['binding'])
    with pytest.raises(StoreError, match='writer_has_source_write_privileges'):
        store.initialize()
    with psycopg.connect(dsn) as conn:
        assert conn.execute("select to_regnamespace('network')").fetchone()[0] is None


def test_capture_transfers_shared_dependencies_once_and_rejects_conflicts(network_database, monkeypatch):
    from contextlib import contextmanager
    from adapters.network.store import Projection, StoreError
    source, store = opened(network_database)
    for page in source.snapshot_pages(30):
        store.apply(page)
    record = store.records('message')[0]
    nodes = tuple({'id':f'person:shared-{i}', 'kind':'person', 'name':f'Shared {i}'} for i in range(20))
    projection = Projection(entities=nodes, assertions=(), evidence=(),
        dependencies={'node:'+n['id']:(record.key,) for n in nodes})
    empty = replace(source.metadata(), records=(), manifests={}, complete_kinds=frozenset())
    store.apply(empty, projection)
    original = store.connection
    transferred = []
    class CountingConnection:
        def __init__(self, conn): self.conn = conn
        def __getattr__(self, key): return getattr(self.conn, key)
        def execute(self, query, *args, **kwargs):
            cursor = self.conn.execute(query, *args, **kwargs)
            if 'network.dependency' in str(query) and str(query).lower().startswith('select'):
                rows = cursor.fetchall()
                transferred.append(len(rows))
                return rows
            return cursor
    @contextmanager
    def connection(*args, **kwargs):
        with original(*args, **kwargs) as conn:
            yield CountingConnection(conn)
    monkeypatch.setattr(store, 'connection', connection)
    snapshot = store.capture(tuple(n['id'] for n in nodes), 30)
    assert snapshot.dependencies == {record.key:record.fingerprint}
    assert transferred == [1], 'Shared proof should be deduplicated before network transfer'
    with psycopg.connect(network_database[0]) as conn:
        conn.execute("update network.dependency set fingerprint='different-version' where item_id=%s", (nodes[0]['id'],))
    with pytest.raises(StoreError, match='source_changed'):
        store.capture(tuple(n['id'] for n in nodes), 30)
