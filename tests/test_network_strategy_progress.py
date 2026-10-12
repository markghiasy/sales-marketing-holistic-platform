import threading

import pytest

from adapters.network.agent import AgentRequest, NetworkAgent
from adapters.network.model import GraphQuery
from adapters.network.retrieval import NetworkRetrieval
from adapters.network.scenario import load_scenario


class Provider:
    available = True
    model = 'fake'

    def __init__(self, events):
        self.events = events
        self.calls = 0

    def structured(self, schema, system, payload):
        self.calls += 1
        if schema.__name__ == 'RetrievalPlan':
            return schema.model_validate({'intent': 'Find help', 'lookups': [
                {'kind': 'people', 'terms': ['Engineering']},
                {'kind': 'people', 'terms': ['Accounting']}], 'requirements': [
                {'id': 'engineering', 'label': 'Engineering', 'terms': ['Engineering']},
                {'id': 'accounting', 'label': 'Accounting', 'terms': ['Accounting']}]}), {}
        assert any(kind == 'partial' for kind, _ in self.events)
        return schema.model_validate({'summary': 'Check these sources.', 'findings': []}), {}


def run(events, factory=None, **kwargs):
    provider = Provider(events)
    result = NetworkAgent(provider).answer(load_scenario(), AgentRequest(question='Find help'), 1,
        emit=lambda kind, data: events.append((kind, data)), retrieval_factory=factory, **kwargs)
    return result, provider


def test_tasks_overlap_and_partial_precedes_synthesis():
    events = []
    barrier = threading.Barrier(2)
    instances = []

    class Branch(NetworkRetrieval):
        def people(self, terms):
            barrier.wait(timeout=3)
            return super().people(terms)

    def factory():
        branch = Branch(load_scenario(), GraphQuery())
        instances.append(branch)
        return branch

    result, provider = run(events, factory)
    assert len(instances) == 2 and provider.calls == 2
    assert result['strategy_graph']['nodes']
    assert sum(kind == 'task_completed' for kind, _ in events) == 2
    assert [kind for kind, _ in events].index('partial') < [kind for kind, _ in events].index('synthesizing')


def test_failed_branch_preserves_success_and_unknown_coverage():
    events = []

    class Branch(NetworkRetrieval):
        def people(self, terms):
            if terms == ['Accounting']:
                raise RuntimeError('private exception secret')
            return super().people(terms)

    result, _ = run(events, lambda: Branch(load_scenario(), GraphQuery()))
    assert any(kind == 'task_failed' for kind, _ in events)
    assert 'private exception secret' not in str(events)
    coverage = {r['id']: r for r in result['retrieval']['coverage']}
    assert coverage['accounting']['status'] == 'search_incomplete'
    assert result['strategy_graph']['nodes']


def test_cancel_after_partial_does_not_synthesize_or_publish_late():
    events = []
    cancel = threading.Event()
    provider = Provider(events)

    def emit(kind, data):
        events.append((kind, data))
        if kind == 'partial':
            cancel.set()

    with pytest.raises(RuntimeError, match='strategy_cancelled'):
        NetworkAgent(provider).answer(load_scenario(), AgentRequest(question='Find help'), 1,
                                     emit=emit, cancel=cancel)
    assert provider.calls == 1
    assert events[-1][0] == 'partial'


def test_invalidated_source_never_emits_evidence():
    events = []
    checks = iter([True, False])
    with pytest.raises(RuntimeError, match='source_changed'):
        run(events, validate_sources=lambda: next(checks))
    assert not any(kind == 'partial' for kind, _ in events)


def test_final_pack_independent_of_branch_completion_order():
    def execute(first):
        events = []
        released = threading.Event()

        class Branch(NetworkRetrieval):
            def people(self, terms):
                if terms != [first]:
                    assert released.wait(3)
                return super().people(terms)

        def emit(kind, payload):
            events.append((kind, payload))
            if kind == 'partial':
                released.set()

        result = NetworkAgent(Provider(events)).answer(load_scenario(), AgentRequest(question='Find help'), 1,
            emit=emit, retrieval_factory=lambda: Branch(load_scenario(), GraphQuery()))
        return result

    forward, backward = execute('Engineering'), execute('Accounting')
    assert forward == backward


def test_cancelling_blocked_retrieval_returns_without_waiting_for_worker():
    from concurrent.futures import ThreadPoolExecutor

    events = []
    entered = threading.Event()
    release = threading.Event()
    cancel = threading.Event()
    provider = Provider(events)

    class Branch(NetworkRetrieval):
        def people(self, terms):
            entered.set()
            assert release.wait(5)
            return super().people(terms)

    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(NetworkAgent(provider).answer, load_scenario(), AgentRequest(question='Find help'), 1,
            emit=lambda kind, payload: events.append((kind, payload)), cancel=cancel,
            retrieval_factory=lambda: Branch(load_scenario(), GraphQuery()))
        try:
            assert entered.wait(3)
            cancel.set()
            with pytest.raises(RuntimeError, match='strategy_cancelled'):
                future.result(timeout=2)
            assert provider.calls == 1
            assert not any(kind in ('partial', 'synthesizing') for kind, _ in events)
        finally:
            release.set()


def test_all_failed_does_not_synthesize_or_claim_no_match():
    events = []
    provider = Provider(events)

    class Branch(NetworkRetrieval):
        def people(self, terms):
            raise OSError('unavailable')

    with pytest.raises(Exception, match='No search task could finish'):
        NetworkAgent(provider).answer(load_scenario(), AgentRequest(question='Find help'), 1,
            emit=lambda kind, payload: events.append((kind, payload)),
            retrieval_factory=lambda: Branch(load_scenario(), GraphQuery()))
    assert provider.calls == 1
    assert sum(kind == 'task_failed' for kind, _ in events) == 2
    assert not any(kind == 'partial' for kind, _ in events)


def test_change_after_early_partial_invalidates_before_synthesis():
    events = []
    changed = threading.Event()
    provider = Provider(events)

    def emit(kind, payload):
        events.append((kind, payload))
        if kind == 'partial':
            changed.set()

    with pytest.raises(RuntimeError, match='source_changed'):
        NetworkAgent(provider).answer(load_scenario(), AgentRequest(question='Find help'), 1,
            emit=emit, validate_sources=lambda: not changed.is_set())
    assert provider.calls == 1
    assert sum(kind == 'partial' for kind, _ in events) == 1


def test_real_merge_checks_fingerprints_and_global_selection():
    from adapters.network.index import IndexedRetrieval

    base = IndexedRetrieval(None, GraphQuery())
    base.data = load_scenario()
    base.dependencies = {'source:a': 'original'}
    first, second = base.fork(), base.fork()
    first.selected = [f'person:{i}' for i in range(25)]
    second.selected = [f'person:{i}' for i in range(20, 45)]
    first.source_ids = [f'evidence:{i}' for i in range(150)]
    second.source_ids = [f'evidence:{i}' for i in range(100, 250)]
    captured = []

    def capture(ids, limit, *, evidence_ids, as_of):
        from adapters.network.store import Snapshot
        captured.append((ids, evidence_ids))
        data = load_scenario()
        return Snapshot(1, data, {'source:a': 'original'})

    class Store:
        pass

    coordinator = IndexedRetrieval(Store(), GraphQuery())
    coordinator.store.capture = capture
    coordinator.merge_from(base, [first, second])
    assert len(coordinator.selected) == 29
    assert len(coordinator.source_ids) == 200
    assert captured[0][0] == tuple(f'person:{i}' for i in range(29))
    second.dependencies['source:a'] = 'changed'
    with pytest.raises(RuntimeError, match='source_changed'):
        coordinator.merge_from(base, [first, second])


def test_followup_rotates_full_candidate_and_source_budgets_for_gap_solution():
    from test_network_strategy_reasoning import workshop_data

    from adapters.network.index import IndexedRetrieval
    from adapters.network.store import Snapshot

    class Store:
        def capture(self, ids, limit, *, evidence_ids, as_of):
            data = workshop_data()
            data['evidence'] = [e for e in data['evidence'] if e['id'] in evidence_ids]
            return Snapshot(1, data, {})

    base = IndexedRetrieval(Store(), GraphQuery())
    base.data = workshop_data()
    base.selected = [f'person:old{i}' for i in range(29)]
    base.source_ids = [f'evidence:old{i}' for i in range(200)]
    branch = base.fork(fresh=True)
    branch._hits = lambda terms: (['person:d', 'person:e'], ['evidence:d', 'evidence:e'])
    result = branch.people(['community hall', 'registration'])
    assert {'person:d', 'person:e'} <= {p['id'] for p in result['people']}
    coordinator = base.fork()
    coordinator.merge_from(base, [branch], prefer_new=True)
    assert {'person:d', 'person:e'} <= set(coordinator.selected)
    assert {'evidence:d', 'evidence:e'} <= set(coordinator.source_ids)
    assert len(coordinator.selected) <= 29 and len(coordinator.source_ids) <= 200
    assert any(key.startswith('person:old') for key in coordinator.selected)
    crowded = base.fork(fresh=True)
    crowded.selected = [f'person:neighbor{i}' for i in range(29)]
    crowded.source_ids = [f'evidence:neighbor{i}' for i in range(200)]
    coordinator.merge_from(base, [crowded, branch], prefer_new=True)
    assert {'person:d', 'person:e'} <= set(coordinator.selected)
    assert {'evidence:d', 'evidence:e'} <= set(coordinator.source_ids)
    pack = coordinator.pack([result], [{'id': 'venue', 'label': 'Venue', 'terms': ['community hall']}])
    assert {'evidence:d', 'evidence:e'} <= {e['id'] for e in pack['evidence']}


def test_failed_context_scope_is_present_in_model_and_final_incomplete_coverage():
    events, payloads = [], []
    first_partial = threading.Event()

    class Provider:
        available = True
        model = 'fake'

        def structured(self, schema, system, payload):
            payloads.append(payload)
            if schema.__name__ == 'RetrievalPlan':
                result = {'intent': 'Find rare evidence', 'requirements': [
                    {'id': 'rare', 'label': 'Rare', 'terms': ['unknown-specialty']}], 'lookups': [
                    {'kind': 'people', 'terms': ['unknown-specialty']},
                    {'kind': 'context', 'entity_id': 'person:sam'}]}
            else:
                result = {'summary': 'Search incomplete.', 'findings': []}
            return schema.model_validate(result), {}

    class Branch(NetworkRetrieval):
        def context(self, entity_id):
            assert first_partial.wait(3)
            raise OSError('private database detail')

    def emit(kind, payload):
        events.append((kind, payload))
        if kind == 'partial':
            first_partial.set()

    result = NetworkAgent(Provider()).answer(load_scenario(), AgentRequest(question='Find rare evidence'), 1,
        emit=emit,
        retrieval_factory=lambda: Branch(load_scenario(), GraphQuery()))
    assert result['retrieval']['coverage'][0]['status'] == 'search_incomplete'
    assert payloads[-1]['coverage'][0]['status'] == 'search_incomplete'
    task = next(t for t in payloads[-1]['tasks'] if t['kind'] == 'context')
    assert task['status'] == 'failed' and task['requirement_ids'] == ['rare'] and task['round'] == 1
    assert result['retrieval']['tasks'] == payloads[-1]['tasks']
    assert [p for kind, p in events if kind == 'partial'][-1]['retrieval']['coverage'][0]['status'] == 'search_incomplete'
    assert 'private database detail' not in str(result)
