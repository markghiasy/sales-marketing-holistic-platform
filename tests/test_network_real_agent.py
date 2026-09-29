from datetime import UTC, datetime

import psycopg
import pytest
from test_network_index import setup_index

from adapters.network.agent import AgentRequest, Answer, NetworkAgent, RetrievalPlan


class Provider:
    available=True
    model='fake-real-agent'
    def __init__(self, after_answer=None, after_plan=None):
        self.after_answer=after_answer
        self.after_plan=after_plan
        self.catalog_size=None

    def structured(self,schema,system,payload):
        if schema is RetrievalPlan:
            self.catalog_size=len(payload['catalog'])
            result=RetrievalPlan(intent='Find security experience',lookups=[{'kind':'people','terms':['security']}],
                                 requirements=[{'id':'security','label':'Security','terms':['security']}])
            if self.after_plan:
                self.after_plan()
        else:
            assert 'All records are fictional' not in system
            assert payload['evidence']
            result=Answer(summary='Review the supplied evidence.',findings=[{'text':'Source statement','evidence_ids':[payload['evidence'][0]['id']]}])
            if self.after_answer:
                self.after_answer()
        return result,{'input_tokens':10,'output_tokens':10}


def test_real_answer_is_bounded_and_source_linked(network_database):
    from adapters.network.service import NetworkService
    source,store,_ids,_=setup_index(network_database,90)
    provider=Provider()
    result=NetworkService(store,source).answer(AgentRequest(question='Who works on security?',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(provider))
    assert result['data_source']=='real'
    assert result['evidence'] and result['strategy_graph']['nodes']
    assert provider.catalog_size<=30


def test_corrected_source_during_model_call_cannot_publish(network_database):
    from adapters.network.service import NetworkService
    source,store,_ids,_=setup_index(network_database)
    def correction():
        with psycopg.connect(network_database[0]) as conn:
            conn.execute("update message set body_text='Correction: no security experience.'")
    with pytest.raises(RuntimeError,match='source_changed'):
        NetworkService(store,source).answer(AgentRequest(question='security',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(Provider(correction)))


def test_unrelated_new_identity_does_not_discard_valid_answer(network_database):
    from adapters.network.service import NetworkService
    source,store,_ids,_=setup_index(network_database)
    def unrelated():
        with psycopg.connect(network_database[0]) as conn:
            conn.execute("insert into identity(channel,handle,display_name) values ('linkedin','new','Unrelated')")
    result=NetworkService(store,source).answer(AgentRequest(question='security',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(Provider(unrelated)))
    assert result['findings']


def test_projection_revision_during_planning_cannot_replace_used_dependencies(network_database):
    from adapters.network.service import NetworkService
    from adapters.network.worker import NetworkWorker
    source,store,_ids,_=setup_index(network_database)
    def correction():
        with psycopg.connect(network_database[0]) as conn:
            conn.execute("update message set body_text='Correction: only logistics, no security.'")
        NetworkWorker(source,store).tick(datetime(2026,10,3,tzinfo=UTC))
    with pytest.raises(RuntimeError,match='source_changed'):
        NetworkService(store,source).answer(AgentRequest(question='security',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(Provider(after_plan=correction)))


def test_hiding_contact_during_model_call_invalidates_answer(network_database):
    from adapters.network.service import NetworkService
    source,store,ids,_=setup_index(network_database)
    def hide():
        with psycopg.connect(network_database[0]) as conn:
            conn.execute('insert into contact_hidden(contact_key) values (%s)',(ids['contact'],))
    with pytest.raises(RuntimeError,match='source_changed'):
        NetworkService(store,source).answer(AgentRequest(question='security',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(Provider(hide)))


def test_merge_reversal_during_model_call_invalidates_answer(network_database):
    from adapters.network.service import NetworkService
    dsn,ids=network_database
    with psycopg.connect(dsn) as conn:
        parent=conn.execute("insert into person(primary_name) values ('Parent') returning id").fetchone()[0]
        child=conn.execute("insert into person(primary_name,merged_into) values ('Child',%s) returning id",(parent,)).fetchone()[0]
        conn.execute('update identity set person_id=%s where id=%s',(child,ids['contact']))
    source,store,ids,_=setup_index(network_database)
    def undo():
        with psycopg.connect(dsn) as conn:
            conn.execute('update person set merged_into=null where id=%s',(child,))
    with pytest.raises(RuntimeError,match='source_changed'):
        NetworkService(store,source).answer(AgentRequest(question='security',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(Provider(undo)))


def test_unrelated_new_message_during_model_call_preserves_answer(network_database):
    from adapters.network.service import NetworkService
    source,store,ids,_=setup_index(network_database)
    def unrelated_message():
        with psycopg.connect(network_database[0]) as conn:
            sender=conn.execute("insert into identity(channel,handle,display_name) values ('outlook','unrelated@example.test','Unrelated') returning id").fetchone()[0]
            thread=conn.execute("insert into thread(channel,external_id) values ('outlook','unrelated') returning id").fetchone()[0]
            message=conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) values (%s,'outlook','unrelated','inbound','2026-10-02',%s,'Unrelated update','{}','2026-10-02') returning id",(thread,sender)).fetchone()[0]
            conn.execute("insert into message_participant values (%s,%s,'to')",(message,ids['self']))
    result=NetworkService(store,source).answer(AgentRequest(question='security',focus=store.worker_state()['owner_id'],as_of='2026-10-02T00:00:00Z'),NetworkAgent(Provider(unrelated_message)))
    assert result['findings']
