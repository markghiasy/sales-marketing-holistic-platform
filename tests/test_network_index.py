from datetime import UTC, datetime

import psycopg

from adapters.network.source import SourceRepository
from adapters.network.store import PostgresNetworkStore
from adapters.network.worker import NetworkWorker
from adapters.network.model import GraphQuery

NOW=datetime(2026,10,2,tzinfo=UTC)


def setup_index(network_database, count=0):
    from adapters.network.index import IndexedRetrieval
    dsn,ids=network_database
    with psycopg.connect(dsn) as conn:
        conn.execute("update message set body_text='I work on security testing and logistics.'")
        for i in range(count):
            conn.execute("insert into identity(channel,handle,display_name) values ('linkedin',%s,%s)",(f'unrelated:{i}',f'Unrelated {i}'))
    source=SourceRepository(dsn)
    store=PostgresNetworkStore(dsn,source.audit()['binding'])
    store.initialize()
    NetworkWorker(source,store).tick(NOW)
    query=GraphQuery(focus=store.worker_state()['owner_id'],as_of=NOW)
    return source,store,ids,IndexedRetrieval(store,query,entity_limit=30)


def test_index_selects_candidates_before_loading_catalog(network_database):
    _,store,ids,retriever=setup_index(network_database,100)
    data=retriever.seed('security testing')
    assert len(data['nodes'])<=30
    assert 'identity:'+ids['contact'] in {n['id'] for n in data['nodes']}
    assert not any(n['name'].startswith('Unrelated') for n in data['nodes'])
    result=retriever.people(['security'])
    assert any(p['id']=='identity:'+ids['contact'] for p in result['people'])
    pack=retriever.pack([result],[{'id':'r1','label':'Security','terms':['security']}])
    assert pack['evidence'] and pack['budget']['bytes']<=28000
    assert pack['scope']['data_source']=='real'


def test_hostile_search_and_non_latin_name_fallback(network_database):
    _,store,ids,retriever=setup_index(network_database)
    with psycopg.connect(network_database[0]) as conn:
        conn.execute("update identity set display_name='陈小明' where id=%s",(ids['contact'],))
    source=SourceRepository(network_database[0])
    NetworkWorker(source,store).tick(datetime(2026,10,3,tzinfo=UTC))
    assert retriever.seed("'; DROP TABLE network.item; --")['owner_id']
    assert store.status().version>0
    matches=retriever.people(['小明'])
    assert any(p['id']=='identity:'+ids['contact'] for p in matches['people'])


def test_snapshot_keeps_focus_owner_and_clips_references_to_visible_evidence(network_database):
    _,store,ids,_=setup_index(network_database,50)
    snapshot=store.capture(('identity:'+ids['contact'],store.worker_state()['owner_id']),2)
    assert {n['id'] for n in snapshot.data['nodes']}=={'identity:'+ids['contact'],snapshot.data['owner_id']}
    assert snapshot.data['claims']
    source_ids={s['id'] for s in snapshot.data['evidence']}
    assert all(set(c['evidence_ids'])<=source_ids for c in snapshot.data['claims'])


def test_hidden_contact_never_appears_in_index_results(network_database):
    source,store,ids,retriever=setup_index(network_database)
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('insert into contact_hidden(contact_key) values (%s)',(ids['contact'],))
    NetworkWorker(source,store).tick(datetime(2026,10,3,tzinfo=UTC))
    result=retriever.people(['security'])
    assert not result['people']


def test_long_source_keeps_matched_passage_in_bounded_context(network_database):
    source,store,ids,retriever=setup_index(network_database)
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('update message set body_text=%s',('Background details. '*400+'My work includes security testing.',))
    NetworkWorker(source,store).tick(datetime(2026,10,3,tzinfo=UTC))
    result=retriever.people(['security'])
    assert result['people']
    pack=retriever.pack([result],[{'id':'security','label':'Security','terms':['security']}])
    assert any('security' in e['text'] for e in pack['evidence'])
    assert all(len(e['text'])<=4000 for e in pack['evidence'])
    assert any(e.get('excerpt_start',0)>0 for e in pack['evidence'])


def test_group_message_is_retrievable_without_inventing_relationship(network_database):
    source,store,ids,retriever=setup_index(network_database)
    with psycopg.connect(network_database[0]) as conn:
        conn.execute('update thread set is_group=true')
    NetworkWorker(source,store).tick(datetime(2026,10,3,tzinfo=UTC))
    result=retriever.people(['security'])
    pack=retriever.pack([result],[{'id':'security','label':'Security','terms':['security']}])
    assert pack['evidence']
    assert any(r['kind']=='observation' for r in pack['records'])
    assert not retriever.inner.adjacency
    assert not retriever.data['claims']
