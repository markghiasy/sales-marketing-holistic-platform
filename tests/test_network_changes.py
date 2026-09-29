from datetime import UTC, datetime

import psycopg
import pytest

from adapters.network.source import SourceRepository
from adapters.network.store import PostgresNetworkStore
from adapters.network.worker import NetworkWorker


def setup(network_database):
    from adapters.network.changes import ProposalBatch
    dsn,ids=network_database
    with psycopg.connect(dsn) as conn:
        conn.execute("update message set body_text='I lead the security work on Project Aurora.'")
    source=SourceRepository(dsn)
    store=PostgresNetworkStore(dsn,source.audit()['binding'])
    store.initialize()
    NetworkWorker(source,store).tick(datetime.now(UTC))
    snap=store.capture(('identity:'+ids['contact'],),50)
    batch=ProposalBatch.model_validate({
        'entities':[{'id':'new:aurora','kind':'project','name':'Project Aurora',
                     'evidence_id':'message:'+ids['message'],'quote':'Project Aurora'}],
        'relations':[{'source_id':'identity:'+ids['contact'],'target_id':'new:aurora',
                      'relation':'Project member','evidence_id':'message:'+ids['message'],
                      'quote':'I lead the security work on Project Aurora.'}],
        'assertions':[{'evidence_id':'message:'+ids['message'],'subject_id':'identity:'+ids['contact'],
                       'facet':'experience','label':'Reports leading security work','context_id':'new:aurora',
                       'basis':'self_declared','quote':'I lead the security work on Project Aurora.'}]})
    return source,store,ids,snap,batch


def test_quotes_and_identity_are_validated_without_name_guessing(network_database):
    from adapters.network.changes import validate_proposals
    _,_,ids,snap,batch=setup(network_database)
    assert validate_proposals(batch,snap).relations[0].source_id=='identity:'+ids['contact']
    bad=batch.model_copy(deep=True)
    bad.relations[0].quote='I have delivered many successful products.'
    with pytest.raises(ValueError,match='exact_quote'):
        validate_proposals(bad,snap)
    bad=batch.model_copy(deep=True)
    bad.relations[0].source_id='Morgan'
    with pytest.raises(ValueError,match='unknown_entity'):
        validate_proposals(bad,snap)


def test_pending_entities_do_not_enter_graph_and_review_requires_binding(network_database):
    from adapters.network.changes import ReviewCommand
    _,store,ids,snap,batch=setup(network_database)
    result=store.propose(batch,snap.dependencies)
    assert len(store.proposals())==1
    assert not any(n['kind']=='project' for n in store.capture((),100).data['nodes'])
    with pytest.raises(ValueError,match='entity_binding_required'):
        store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='confirm'))
    saved=store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='confirm',entity_bindings={'new:aurora':'create'}))
    data=store.capture(('identity:'+ids['contact'],),50).data
    projects=[n for n in data['nodes'] if n['kind']=='project']
    assert len(projects)==1 and projects[0]['name']=='Project Aurora'
    assert any(c['relation']=='Project member' for c in data['claims'])
    assert data['strategic_assertions'][0]['status']=='confirmed'
    assert saved['version']>result['version']


def test_rejection_restart_and_replay_do_not_revive_proposal(network_database):
    from adapters.network.changes import ReviewCommand
    source,store,ids,snap,batch=setup(network_database)
    result=store.propose(batch,snap.dependencies)
    store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='reject'))
    restarted=PostgresNetworkStore(network_database[0],source.audit()['binding'])
    again=restarted.propose(batch,snap.dependencies)
    assert again['id']==result['id'] and again['added']==0
    assert restarted.proposals()[0]['status']=='rejected'
    assert len(restarted.reviews())==1
    assert not restarted.capture((),100).data['strategic_assertions']


def test_stale_source_and_stale_review_are_rejected(network_database):
    from adapters.network.changes import ReviewCommand
    from adapters.network.store import StoreError
    source,store,ids,snap,batch=setup(network_database)
    result=store.propose(batch,snap.dependencies)
    with pytest.raises(StoreError,match='version_conflict'):
        store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version']-1,decision='reject'))
    with psycopg.connect(network_database[0]) as conn:
        conn.execute("update message set body_text='That was a misunderstanding.'")
    # Real source validation must detect this even BEFORE the worker polls.
    with pytest.raises(StoreError,match='source_changed'):
        store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='confirm',entity_bindings={'new:aurora':'create'}))


def test_source_correction_retracts_confirmed_items_but_preserves_review(network_database):
    from adapters.network.changes import ReviewCommand
    source,store,ids,snap,batch=setup(network_database)
    result=store.propose(batch,snap.dependencies)
    store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='confirm',entity_bindings={'new:aurora':'create'}))
    with psycopg.connect(network_database[0]) as conn:
        conn.execute("update message set body_text='Correction: I am not on that project.'")
    worker=NetworkWorker(source,store)
    worker.tick(datetime(2026,10,2,tzinfo=UTC))
    assert not store.capture(('identity:'+ids['contact'],),50).data['strategic_assertions']
    assert len(store.reviews())==1


def test_project_mention_alone_does_not_generate_membership(network_database):
    from adapters.network.changes import ReviewCommand
    _,store,ids,snap,batch=setup(network_database)
    only_entity=batch.model_copy(update={'relations':[],'assertions':[]})
    result=store.propose(only_entity,snap.dependencies)
    store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='confirm',entity_bindings={'new:aurora':'create'}))
    assert not any(c['relation']=='Project member' for c in store.capture((),100).data['claims'])


def test_scoped_model_extraction_uses_only_selected_sources_and_stale_result_fails(network_database):
    from adapters.network.agent import NetworkAgent
    from adapters.network.model import GraphQuery
    _,store,ids,snap,batch=setup(network_database)
    class Provider:
        available=True
        model='fake-extraction'
        def structured(self,schema,system,payload):
            assert len(payload['evidence'])==1
            assert payload['evidence'][0]['id']=='message:'+ids['message']
            return batch,{'input_tokens':10,'output_tokens':10}
    agent=NetworkAgent(Provider(),max_requests=2)
    result,usage=agent.extract_network(snap,GraphQuery(focus='identity:'+ids['contact'],as_of='2026-10-02T00:00:00Z'),
                                     ['message:'+ids['message']],lambda:True)
    assert result.model=='fake-extraction' and len(result.relations)==1
    checks=iter([True,False])
    with pytest.raises(RuntimeError,match='source_changed'):
        agent.extract_network(snap,GraphQuery(focus='identity:'+ids['contact'],as_of='2026-10-02T00:00:00Z'),
                              ['message:'+ids['message']],lambda:next(checks))
    assert agent.remaining==0


def test_confirmed_project_survives_unrelated_source_reconciliation(network_database):
    from adapters.network.changes import ReviewCommand
    source,store,ids,snap,batch=setup(network_database)
    result=store.propose(batch,snap.dependencies)
    store.review(ReviewCommand(proposal_id=result['id'],expected_version=result['version'],decision='confirm',entity_bindings={'new:aurora':'create'}))
    with psycopg.connect(network_database[0]) as conn:
        conn.execute("insert into identity(channel,handle,display_name) values ('linkedin','unrelated','Unrelated')")
    NetworkWorker(source,store).tick(datetime(2026,10,2,tzinfo=UTC))
    assert any(c['relation']=='Project member' for c in store.capture(('identity:'+ids['contact'],),50).data['claims'])


def test_invalid_relation_vocabulary_and_self_declaration_rejected(network_database):
    from adapters.network.changes import ProposalBatch, validate_proposals
    _,_,ids,snap,batch=setup(network_database)
    invalid=batch.model_dump()
    invalid['relations'][0]['relation']='Definitely trusts'
    with pytest.raises(ValueError):
        ProposalBatch.model_validate(invalid)
    invalid=batch.model_copy(deep=True)
    invalid.assertions[0].subject_id='person:'+ids['owner']
    with pytest.raises(ValueError,match='invalid_self_declaration'):
        validate_proposals(invalid,snap)
