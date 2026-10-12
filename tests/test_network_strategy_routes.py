import json

from adapters.network.agent import Answer, RetrievalPlan
from scripts.network_demo import create_app


class Provider:
    available=True
    model='fake-strategy-test'
    def __init__(self):
        self.calls=0
    def structured(self,schema,system,payload):
        self.calls+=1
        if schema is RetrievalPlan:
            value=RetrievalPlan(intent='Explore workshop support',
                lookups=[{'kind':'people','terms':['research']},{'kind':'people','terms':['logistics']}],
                requirements=[{'id':'teaching','label':'Teaching lead','terms':['research'],'origin':'suggested','priority':'prefer'}])
        elif schema.__name__=='GapAssessment':
            value=schema(pending_constraints=[{'id':'date','question':'What date is intended?', 'origin':'missing_user_detail'}])
        elif schema.__name__=='StrategyAnswer':
            value=schema(summary='Validate the available leads before inviting anyone.',
                         strategy_evaluation={'pending_constraints':[{'id':'date','question':'What date is intended?', 'origin':'missing_user_detail'}]})
        else:
            value=Answer(summary='Validate the available leads before inviting anyone.',gaps=['Availability is not established.'])
        return value,{'input_tokens':1,'output_tokens':1}


def test_routes_stream_partial_then_answer_and_replay_without_model_calls():
    provider=Provider()
    app=create_app(testing=True,agent_provider=provider)
    client=app.test_client()
    response=client.post('/network/strategy/runs',json={'question':'Who can help with an AI workshop?'})
    assert response.status_code==202
    run_id=response.json['run_id']
    run=app.extensions['strategy_jobs'].get(run_id)
    run.thread.join(5)
    response=client.get(f'/network/strategy/runs/{run_id}/events')
    assert response.status_code==200
    assert response.mimetype=='text/event-stream'
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    kinds=[event['type'] for event in events]
    assert kinds.index('partial')<kinds.index('completed')
    assert provider.calls==3
    assert 'assessment' in kinds
    snapshot=client.get(f'/network/strategy/runs/{run_id}')
    assert snapshot.json['status']=='completed'
    client.get(f'/network/strategy/runs/{run_id}/events?after={events[-1]["seq"]}')
    assert provider.calls==3
    assert 'no-store' in snapshot.headers['Cache-Control']


def test_invalid_cross_origin_and_unavailable_do_not_start_work():
    provider=Provider()
    app=create_app(testing=True,agent_provider=provider)
    client=app.test_client()
    assert client.post('/network/strategy/runs',json={'question':'hello'},headers={'Origin':'https://elsewhere.test'}).status_code==403
    assert client.post('/network/strategy/runs',data='question=hello').status_code==415
    assert client.post('/network/strategy/runs',json={'question':'  '}).status_code==400
    assert client.post('/network/strategy/runs',json=[]).status_code==400
    assert client.get('/network/strategy/runs/missing').status_code==404
    assert client.get('/network/strategy/runs/missing/events').status_code==404
    provider.available=False
    assert client.post('/network/strategy/runs',json={'question':'hello'}).status_code==503
    assert provider.calls==0


def test_draft_handoff_is_bounded_private_and_does_not_start_analysis():
    provider=Provider()
    app=create_app(testing=True,agent_provider=provider)
    client=app.test_client()
    response=client.post('/network/strategy/drafts',json={'question':'Private workshop goal'})
    assert response.status_code==201
    assert 'Private' not in response.text
    draft_id=response.json['draft_id']
    draft=client.get('/network/strategy/drafts/'+draft_id)
    assert draft.json=={'question':'Private workshop goal'}
    assert 'no-store' in draft.headers['Cache-Control']
    assert provider.calls==0
    assert client.post('/network/strategy/drafts',json={'question':'x'*2001}).status_code==400


def test_source_revision_withdraws_previously_completed_synthetic_result():
    app=create_app(testing=True,agent_provider=Provider())
    client=app.test_client()
    response=client.post('/network/strategy/runs',json={'question':'Find research contacts'})
    assert response.status_code==202
    run_id=response.json['run_id']
    app.extensions['strategy_jobs'].get(run_id).thread.join(5)
    app.extensions['network_store'].reply()
    snapshot=client.get('/network/strategy/runs/'+run_id).json
    assert snapshot['status']=='invalidated'
    assert [e['type'] for e in snapshot['events']]==['invalidated']


def test_sse_replay_skips_superseded_partials_and_validates_each_delivered_payload_once():
    app=create_app(testing=True,agent_provider=Provider())
    calls=[]
    def runner(run):
        for n in range(5):
            run.emit('partial',{'version':n,'evidence':[]})
        return {'summary':'Done','evidence':[]}
    run=app.extensions['strategy_jobs'].start(runner,validator=lambda _:calls.append(1) or True)
    run.thread.join(3)
    calls.clear()
    response=app.test_client().get(f'/network/strategy/runs/{run.id}/events')
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    partials=[e for e in events if e['type']=='partial']
    assert len(partials)==1 and partials[0]['data']['version']==4
    assert len(calls)==2  # latest partial and completion; no blanket duplicate check


def test_reconnect_after_last_event_still_withdraws_revoked_result():
    app=create_app(testing=True,agent_provider=Provider())
    valid=[True]
    run=app.extensions['strategy_jobs'].start(lambda run:{'summary':'Private'},validator=lambda _:valid[0])
    run.thread.join(3)
    after=run.sequence
    valid[0]=False
    response=app.test_client().get(f'/network/strategy/runs/{run.id}/events?after={after}')
    assert 'invalidated' in response.text and 'Private' not in response.text


def test_reconnect_after_plan_checks_source_derived_task_before_delivery():
    app=create_app(testing=True,agent_provider=Provider())
    valid=[True]
    def runner(run):
        run.emit('plan',{'intent':'Workshop'})
        run.emit('task_started',{'label':'Private contact name','entity_id':'person:private'})
        run.emit('partial',{'evidence':[]})
        return {'summary':'Done'}
    run=app.extensions['strategy_jobs'].start(runner,validator=lambda _:valid[0])
    run.thread.join(3)
    after=next(e['seq'] for e in run.events if e['type']=='plan')
    valid[0]=False
    response=app.test_client().get(f'/network/strategy/runs/{run.id}/events?after={after}')
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [e['type'] for e in events]==['invalidated']
    assert 'Private contact name' not in response.text
