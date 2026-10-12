"""Run lifecycle tests use barriers rather than real providers or source data."""
import importlib.util
import threading

import pytest


def jobs(**kwargs):
    assert importlib.util.find_spec('adapters.network.strategy_jobs'), 'Strategy jobs are not implemented'
    from adapters.network.strategy_jobs import StrategyJobs
    return StrategyJobs(**kwargs)


@pytest.mark.parametrize('code', ['model_output_limit', 'model_input_limit'])
def test_budget_failure_explains_stage_without_disclosing_provider_contents(code):
    from adapters.network.strategy_jobs import StrategyBudgetError
    def runner(run):
        run.emit('partial', {'version': 1})
        raise StrategyBudgetError(code)
    run = jobs().start(runner)
    run.thread.join(3)
    snapshot = run.snapshot()
    assert snapshot['status'] == 'failed'
    assert snapshot['events'][-1]['data']['code'] == code
    assert 'Completed results remain available' in snapshot['events'][-1]['data']['message']
    assert snapshot['events'][1]['type'] == 'partial'


def test_partial_is_observable_before_synthesis_and_survives_failure():
    manager=jobs()
    ready,release=threading.Event(),threading.Event()
    def runner(run):
        run.emit('partial', {'evidence':[{'id':'e1','text':'Supported record'}]})
        ready.set()
        assert release.wait(3)
        raise RuntimeError('private provider request content')
    run=manager.start(runner)
    try:
        assert ready.wait(3)
        snapshot=manager.snapshot(run.id)
        assert snapshot['status']=='running'
        assert any(e['type']=='partial' for e in snapshot['events'])
        with pytest.raises(RuntimeError,match='strategy_busy'):
            manager.start(lambda run: {})
    finally:
        release.set()
        run.thread.join(3)
    snapshot=manager.snapshot(run.id)
    assert snapshot['status']=='failed'
    assert any(e['type']=='partial' for e in snapshot['events'])
    assert 'private provider' not in str(snapshot)


def test_replay_does_not_execute_runner_again_and_source_revocation_withdraws_events():
    manager=jobs()
    calls=[]
    valid=[True]
    def runner(run):
        calls.append(1)
        run.set_dependencies({'message:1':'fingerprint'})
        run.emit('partial',{'evidence':[{'id':'e1','text':'Private record'}]})
        return {'summary':'Retained answer','evidence':[{'id':'e1'}]}
    run=manager.start(runner,validator=lambda deps: valid[0] and deps=={'message:1':'fingerprint'})
    run.thread.join(3)
    before=manager.snapshot(run.id)
    assert before['status']=='completed'
    manager.snapshot(run.id)
    assert len(calls)==1
    valid[0]=False
    after=manager.snapshot(run.id)
    assert after['status']=='invalidated'
    assert [e['type'] for e in after['events']]==['invalidated']
    assert 'Private record' not in str(after)
    assert after['events'][0]['seq']>before['events'][-1]['seq']


def test_cancel_preserves_partial_and_discards_late_outputs():
    manager=jobs()
    ready,release=threading.Event(),threading.Event()
    def runner(run):
        run.emit('partial',{'evidence':[{'id':'e1'}]})
        ready.set()
        assert release.wait(3)
        run.emit('partial',{'late':True})
        return {'late':True}
    run=manager.start(runner)
    try:
        assert ready.wait(3)
        manager.cancel(run.id)
    finally:
        release.set()
        run.thread.join(3)
    snapshot=manager.snapshot(run.id)
    assert snapshot['status']=='cancelled'
    assert any(e['type']=='partial' for e in snapshot['events'])
    assert not any(e['data'].get('late') for e in snapshot['events'])


def test_retention_and_expiry_are_bounded_and_unknown_run_is_not_recreated():
    now=[0.0]
    manager=jobs(max_runs=2,ttl_seconds=30,clock=lambda:now[0])
    old=manager.start(lambda run: {'summary':'first'})
    old.thread.join(3)
    for _ in range(2):
        run=manager.start(lambda run: {'summary':'next'})
        run.thread.join(3)
    with pytest.raises(KeyError):
        manager.snapshot(old.id)
    now[0]=31
    with pytest.raises(KeyError):
        manager.snapshot(run.id)


def test_validation_failure_never_replays_unchecked_evidence():
    manager=jobs()
    fail=[False]
    def validator(_):
        if fail[0]:
            raise OSError('private database connection')
        return True
    run=manager.start(lambda run: {'evidence':[{'text':'Secret'}]},validator=validator)
    run.thread.join(3)
    fail[0]=True
    snapshot=manager.snapshot(run.id)
    assert snapshot['status']=='invalidated'
    assert 'Secret' not in str(snapshot)
    assert 'private database' not in str(snapshot)


def test_assessment_is_evidence_and_cannot_survive_source_revocation():
    manager=jobs()
    valid=[True]
    ready,release=threading.Event(),threading.Event()
    def runner(run):
        run.emit('assessment',{'alternatives':[{'name':'Private candidate combination'}]})
        ready.set()
        assert release.wait(3)
        return {}
    run=manager.start(runner,validator=lambda _:valid[0])
    try:
        assert ready.wait(3)
        valid[0]=False
        snapshot=manager.snapshot(run.id)
        assert snapshot['status']=='invalidated'
        assert 'Private candidate' not in str(snapshot)
    finally:
        release.set()
        run.thread.join(3)


def test_failed_plan_without_partial_is_withdrawn_if_source_contact_is_hidden():
    manager=jobs()
    valid=[True]
    def runner(run):
        run.set_dependencies({'identity:1':'visible'})
        run.emit('plan',{'tasks':[{'entity_id':'private-contact-id','label':'Private contact'}]})
        raise RuntimeError('retrieval_failed')
    run=manager.start(runner,validator=lambda _:valid[0])
    run.thread.join(3)
    valid[0]=False
    snapshot=manager.snapshot(run.id)
    assert snapshot['status']=='invalidated'
    assert 'private-contact-id' not in str(snapshot)


def test_wall_time_budget_keeps_partial_and_suppresses_late_answer():
    manager=jobs(max_seconds=.05)
    ready,release=threading.Event(),threading.Event()
    def runner(run):
        run.emit('partial',{'evidence':[{'id':'useful'}]})
        ready.set()
        assert release.wait(3)
        return {'summary':'Too late'}
    run=manager.start(runner)
    try:
        assert ready.wait(2)
        assert run.cancel.wait(2)
        snapshot=manager.snapshot(run.id)
        assert snapshot['status']=='failed'
        assert snapshot['events'][-1]['data']['code']=='strategy_time_budget'
        assert any(e['type']=='partial' for e in snapshot['events'])
    finally:
        release.set()
        run.thread.join(3)
    assert 'Too late' not in str(manager.snapshot(run.id))
