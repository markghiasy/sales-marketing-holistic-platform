from copy import deepcopy

import pytest

from adapters.network.agent import AgentRequest, NetworkAgent


def workshop_data():
    rows = {
        'a': ('Teaching', 'I taught an AI workshop last year.', 'project:previous'),
        'b': ('School employment', 'I work at the school.', 'org:school'),
        'c': ('Recruitment', 'I recruited attendees for our previous community event.', 'project:previous'),
        'd': ('Community hall', 'I booked the community hall for the previous gathering.', 'project:previous'),
        'e': ('Registration', 'I handled registration and the event checklist.', 'project:previous'),
    }
    data = {'owner_id': 'person:owner', 'claims': [], 'messages': [], 'work_records': [],
            'profile_assertions': [], 'strategic_assertions': [], 'evidence': [],
            'nodes': [{'id': 'person:owner', 'name': 'Owner', 'kind': 'person'},
                      {'id': 'project:previous', 'name': 'Previous workshop', 'kind': 'project'},
                      {'id': 'org:school', 'name': 'School', 'kind': 'organization'}]}
    for key, (label, quote, context) in rows.items():
        data['nodes'].append({'id': f'person:{key}', 'name': key.upper(), 'kind': 'person'})
        data['evidence'].append({'id': f'evidence:{key}', 'text': quote, 'channel': 'outlook',
                                 'at': '2026-01-01T00:00:00Z', 'author_id': f'person:{key}'})
        data['strategic_assertions'].append({'id': f'assertion:{key}', 'subject_id': f'person:{key}',
            'facet': 'experience', 'label': label, 'context_id': context, 'basis': 'self_declared',
            'quote': quote, 'observed_at': '2026-01-01T00:00:00Z', 'status': 'confirmed',
            'evidence_ids': [f'evidence:{key}'], 'claimant_id': f'person:{key}'})
    return data


REQUIREMENTS = [{'id': key, 'label': key.title(), 'terms': [term], 'origin': 'suggested', 'priority': 'prefer'}
                for key, term in [('teaching', 'teaching'), ('venue', 'school'),
                                  ('recruitment', 'recruitment'), ('execution', 'execution')]]


def evaluation(final=False):
    sources = {r['id']: r for r in workshop_data()['evidence']}
    rows = [('teaching', 'a', 'supported'), ('venue', 'b', 'insufficient'),
            ('recruitment', 'c', 'supported')]
    if final:
        rows += [('venue', 'd', 'supported'), ('execution', 'e', 'supported')]
    assessments = [{'id': f'assessment:{key}', 'requirement_id': requirement,
        'subject_id': f'person:{key}', 'context_id': 'org:school' if key == 'b' else 'project:previous',
        'state': state, 'statement': sources[f'evidence:{key}']['text'],
        'scope': 'historical_observation',
        'evidence': [{'evidence_id': f'evidence:{key}', 'quote': sources[f'evidence:{key}']['text']}],
        'limitation': 'Past reported activity does not establish willingness or availability now.'}
        for requirement, key, state in rows]
    def option(identifier, keys):
        selected = [a for a in assessments if a['subject_id'].split(':')[-1] in keys]
        return {'id': identifier, 'label': identifier, 'assignments': [
            {'requirement_id': a['requirement_id'], 'subject_id': a['subject_id'], 'assessment_id': a['id']}
            for a in selected], 'comparison': {
                'requirement_coverage': 'Some historical contributions are recorded.',
                'complementarity': 'Teaching and outreach are different contributions.',
                'evidence_support': 'Self reports with original quotations.',
                'contact_paths': 'No introduction willingness established.',
                'unresolved_dependencies': 'Date, cost and willingness remain unknown.'},
            'actions': [{'id': 'confirm', 'text': 'Ask about interest and availability.',
                         'subject_id': 'person:a', 'depends_on': [], 'kind': 'verify'},
                        {'id': 'recruit', 'text': 'Plan outreach only after a date and venue are confirmed.',
                         'subject_id': 'person:c', 'depends_on': ['confirm'], 'kind': 'coordinate'}]}
    return {'assessments': assessments, 'alternatives': [option('school-hosted', ['a', 'b', 'c'])] +
            ([option('community-hosted', ['a', 'd', 'c', 'e'])] if final else []),
            'pending_constraints': [{'id': name, 'question': f'Confirm {name}.', 'origin': 'missing_user_detail'}
                                    for name in ('budget', 'date', 'willingness')],
            'next_searches': [] if final else [
                {'requirement_id': 'venue', 'reason': 'School employment does not establish venue access.',
                 'kind': 'context', 'entity_id': 'project:previous'},
                {'requirement_id': 'execution', 'reason': 'Inspect who coordinated the previous workshop.',
                 'kind': 'people', 'terms': ['registration']} ]}


def test_workshop_gap_round_updates_alternatives_before_final_answer():
    events, calls = [], []

    class Provider:
        available = True
        model = 'fake-workshop'

        def structured(self, schema, system, payload):
            calls.append(schema.__name__)
            if schema.__name__ == 'RetrievalPlan':
                result = {'intent': 'Plan an AI workshop', 'requirements': REQUIREMENTS,
                          'lookups': [{'kind': 'people', 'terms': ['teaching', 'school', 'recruitment', 'execution']}]}
            elif schema.__name__ == 'GapAssessment':
                assert any(kind == 'partial' for kind, _ in events)
                assert 'evidence:d' not in {e['id'] for e in payload['evidence']}
                result = evaluation()
            else:
                assert any(kind == 'assessment' for kind, _ in events)
                assert {'evidence:d', 'evidence:e'} <= {e['id'] for e in payload['evidence']}
                result = {'summary': 'Two conditional options; verify date, cost and willingness.',
                          'findings': [], 'strategy_evaluation': evaluation(final=True)}
            return schema.model_validate(result), {'input_tokens': 10, 'output_tokens': 5}

    result = NetworkAgent(Provider()).answer(workshop_data(), AgentRequest(question='I want to run an AI workshop'), 1,
        emit=lambda kind, payload: events.append((kind, payload)), iterative=True)
    assert calls == ['RetrievalPlan', 'GapAssessment', 'StrategyAnswer']
    assessments = result['strategy_evaluation']['assessments']
    assert next(a for a in assessments if a['subject_id'] == 'person:b')['state'] == 'insufficient'
    assert {a['subject_id'] for a in assessments} >= {'person:d', 'person:e'}
    assert len(result['strategy_evaluation']['alternatives']) == 2
    assert len(result['strategy_evaluation']['pending_constraints']) == 3
    assert result['usage']['input_tokens'] == 30
    assert [payload['round'] for kind, payload in events if kind == 'assessment'] == [1, 2]
    first_assessment = next(i for i, (kind, _) in enumerate(events) if kind == 'assessment')
    assert any(kind == 'task_started' for kind, _ in events[first_assessment + 1:])


def validate(value, question='I want to run an AI workshop', final=False):
    from adapters.network.model import GraphQuery
    from adapters.network.retrieval import NetworkRetrieval
    from adapters.network.strategy_reasoning import GapAssessment, validate_assessment
    data = workshop_data()
    retriever = NetworkRetrieval(data, GraphQuery())
    pack = retriever.pack([retriever.context('project:previous'), retriever.context('org:school')], REQUIREMENTS)
    return validate_assessment(GapAssessment.model_validate(value), pack, REQUIREMENTS, question, final=final)


@pytest.mark.parametrize('mutation', ['invented_quote', 'wrong_subject', 'wrong_context', 'unbound_requirement', 'action_cycle'])
def test_assessment_rejects_unsupported_references_and_dependencies(mutation):
    result = deepcopy(evaluation())
    if mutation == 'invented_quote':
        result['assessments'][0]['evidence'][0]['quote'] = 'Guaranteed availability next Friday.'
    elif mutation == 'wrong_subject':
        result['assessments'][0]['subject_id'] = 'person:b'
    elif mutation == 'wrong_context':
        result['assessments'][0]['context_id'] = 'org:school'
    elif mutation == 'unbound_requirement':
        result['next_searches'][0]['requirement_id'] = 'invented'
    else:
        result['alternatives'][0]['actions'][0]['depends_on'] = ['recruit']
    with pytest.raises(ValueError):
        validate(result)


def test_cannot_eliminate_option_without_explicit_evidence_backed_hard_constraint():
    result = evaluation()
    result['alternatives'][0]['status'] = 'eliminated'
    with pytest.raises(ValueError):
        validate(result)


def test_fabricated_conflict_cannot_eliminate_option_from_unrelated_quote():
    from adapters.network.model import GraphQuery
    from adapters.network.retrieval import NetworkRetrieval
    from adapters.network.strategy_reasoning import GapAssessment, validate_assessment

    result = evaluation()
    result['assessments'][0].update(state='obstacle', statement='A is unavailable for this workshop.',
                                    hard_constraint_quote='AI workshop')
    result['alternatives'][0].update(status='eliminated', obstacle_assessment_ids=['assessment:a'])
    requirements = deepcopy(REQUIREMENTS)
    requirements[0].update(origin='explicit', priority='require')
    retriever = NetworkRetrieval(workshop_data(), GraphQuery())
    pack = retriever.pack([retriever.context('project:previous'), retriever.context('org:school')], requirements)
    checked = validate_assessment(GapAssessment.model_validate(result), pack, requirements, 'Plan an AI workshop')
    assert checked.alternatives[0].status == 'candidate'
    assert checked.assessments[0].state == 'insufficient'
    assert checked.assessments[0].statement == 'I taught an AI workshop last year.'
    assert 'requires confirmation' in checked.assessments[0].limitation


def test_final_evaluation_cannot_request_another_search_round():
    with pytest.raises(ValueError):
        validate(evaluation(), final=True)


def test_suggested_requirement_cannot_become_hard_constraint_obstacle():
    result = evaluation()
    result['assessments'][0].update(state='obstacle', hard_constraint_quote='AI workshop')
    with pytest.raises(ValueError, match='explicit user hard constraint'):
        validate(result)


def test_supported_observation_cannot_assert_verified_goal_fit():
    result = evaluation()
    result['assessments'][0]['scope'] = 'unverified_goal_fit'
    with pytest.raises(ValueError, match='Goal fit'):
        validate(result)


def test_supported_display_uses_actual_quotation_not_generated_assertion():
    result = evaluation()
    result['assessments'][0]['statement'] = 'A is guaranteed available and willing next week.'
    checked = validate(result)
    assert checked.assessments[0].statement == 'I taught an AI workshop last year.'


def test_followup_must_target_unresolved_requirement():
    result = evaluation()
    result['next_searches'][0]['requirement_id'] = 'teaching'
    with pytest.raises(ValueError, match='unresolved requirement'):
        validate(result)


def test_historical_support_still_allows_followup_for_pending_goal_gap():
    result = evaluation()
    result['next_searches'][0]['requirement_id'] = 'teaching'
    result['next_searches'][0]['reason'] = 'Historical teaching does not establish current availability.'
    result['pending_constraints'].append({'id': 'teaching_availability', 'question': 'Is A available for this event?',
                                         'origin': 'evidence_gap', 'requirement_id': 'teaching'})
    assert validate(result).next_searches[0].requirement_id == 'teaching'


@pytest.mark.parametrize('author', [None, 'person:owner'])
def test_conversation_endpoints_cannot_attribute_supported_capability(author):
    from adapters.network.strategy_reasoning import GapAssessment, validate_assessment
    row = deepcopy(evaluation()['assessments'][0])
    row['context_id'] = ''
    pack = {'evidence': [{'id': 'evidence:a', 'text': row['evidence'][0]['quote'], 'author_id': author}],
            'records': [{'kind': 'claim', 'relation': 'In contact', 'entity_ids': ['person:owner', 'person:a'],
                         'evidence_ids': ['evidence:a'], 'source': 'person:owner', 'target': 'person:a'}]}
    with pytest.raises(ValueError, match='subject/context'):
        validate_assessment(GapAssessment(assessments=[row]), pack, REQUIREMENTS, 'Plan an AI workshop')


def test_assessment_schema_caps_round_actions_and_combinations():
    from adapters.network.strategy_reasoning import GapAssessment
    result = evaluation()
    result['next_searches'] *= 2
    with pytest.raises(ValueError):
        GapAssessment.model_validate(result)
    result = evaluation()
    result['alternatives'] *= 4
    with pytest.raises(ValueError):
        GapAssessment.model_validate(result)


def test_cancel_from_assessment_skips_followup_and_synthesis():
    import threading
    events, calls = [], []
    cancel = threading.Event()

    class Provider:
        available = True
        model = 'fake'

        def structured(self, schema, system, payload):
            calls.append(schema.__name__)
            result = ({'intent': 'Workshop', 'requirements': REQUIREMENTS,
                       'lookups': [{'kind': 'people', 'terms': ['teaching', 'school', 'recruitment', 'execution']}]}
                      if schema.__name__ == 'RetrievalPlan' else evaluation())
            return schema.model_validate(result), {}

    def emit(kind, payload):
        events.append((kind, payload))
        if kind == 'assessment':
            cancel.set()

    with pytest.raises(RuntimeError, match='strategy_cancelled'):
        NetworkAgent(Provider()).answer(workshop_data(), AgentRequest(question='Plan an AI workshop'), 1,
                                       emit=emit, cancel=cancel, iterative=True)
    assert calls == ['RetrievalPlan', 'GapAssessment']
    assert events[-1][0] == 'assessment'


def test_all_followup_failures_remain_visible_to_final_reasoning(monkeypatch):
    from adapters.network import agent as agent_module
    from adapters.network.retrieval import NetworkRetrieval

    events, payloads = [], []

    class Branch(NetworkRetrieval):
        def context(self, entity_id):
            raise OSError('private context failure')

        def people(self, terms):
            if terms == ['registration']:
                raise OSError('private search failure')
            return super().people(terms)

    class Provider:
        available = True
        model = 'fake'

        def structured(self, schema, system, payload):
            payloads.append(payload)
            if schema.__name__ == 'RetrievalPlan':
                result = {'intent': 'Workshop', 'requirements': REQUIREMENTS,
                          'lookups': [{'kind': 'people', 'terms': ['teaching', 'school', 'recruitment', 'execution']}]}
            elif schema.__name__ == 'GapAssessment':
                result = evaluation()
            else:
                result = {'summary': 'Further search failed; keep provisional leads.', 'findings': [],
                          'strategy_evaluation': {**evaluation(), 'next_searches': []}}
            return schema.model_validate(result), {}

    monkeypatch.setattr(agent_module, 'NetworkRetrieval', Branch)
    result = NetworkAgent(Provider()).answer(workshop_data(), AgentRequest(question='Plan an AI workshop'), 1,
        emit=lambda kind, payload: events.append((kind, payload)), iterative=True)
    failures = [t for t in payloads[-1]['tasks'] if t['round'] == 2]
    assert len(failures) == 2 and all(t['status'] == 'failed' for t in failures)
    assert {tuple(t['requirement_ids']) for t in failures} == {('venue',), ('execution',)}
    coverage = {r['id']: r for r in result['retrieval']['coverage']}
    assert coverage['execution']['status'] == 'search_incomplete'
    assert coverage['venue']['search_status'] == 'incomplete'
    assert result['strategy_graph']['nodes']
    assert 'private context failure' not in str(payloads)
    assert [p for kind, p in events if kind == 'partial'][-1]['retrieval']['tasks'] == result['retrieval']['tasks']


def test_pending_user_detail_bound_to_requirement_allows_targeted_search():
    result = evaluation()
    result['next_searches'][0]['requirement_id'] = 'teaching'
    result['next_searches'][0]['reason'] = 'Find another teaching lead while availability is unknown.'
    result['pending_constraints'].append({'id': 'teacher_interest', 'question': 'Is A willing to participate?',
                                         'origin': 'missing_user_detail', 'requirement_id': 'teaching'})
    assert validate(result).next_searches[0].requirement_id == 'teaching'


def test_supported_label_without_quote_downgrades_to_explicit_unknown():
    result = evaluation()
    result['assessments'][0]['evidence'] = []
    result['assessments'][0]['statement'] = 'A is definitely available tomorrow.'
    row = validate(result).assessments[0]
    assert row.state == 'insufficient'
    assert row.scope == 'unverified_goal_fit'
    assert 'definitely available' not in row.statement
    assert 'No source quotation' in row.statement


def test_unsupported_combination_is_omitted_without_losing_valid_option():
    result = evaluation(final=True)
    result['alternatives'][1]['assignments'][0]['requirement_id'] = 'venue'
    checked = validate(result, final=True)
    assert len(checked.alternatives) == 1
    assert checked.alternatives[0].id == 'school-hosted'
    assert any('omitted' in c.question for c in checked.pending_constraints)


def checked_parts(value, *, final=False):
    from adapters.network.model import GraphQuery
    from adapters.network.retrieval import NetworkRetrieval
    from adapters.network.strategy_reasoning import GapAssessment, validate_assessment_parts
    retriever = NetworkRetrieval(workshop_data(), GraphQuery())
    pack = retriever.pack([retriever.context('project:previous'), retriever.context('org:school')], REQUIREMENTS)
    return validate_assessment_parts(GapAssessment.model_validate(value), pack, REQUIREMENTS,
                                     'Plan an AI workshop', final=final)


def test_isolated_validation_keeps_five_rows_when_one_context_is_wrong():
    value = evaluation(final=True)
    invalid = deepcopy(value['assessments'][0])
    invalid.update(id='private-invalid-id', context_id='org:school', statement='PRIVATE REJECTED ASSERTION')
    value['assessments'].append(invalid)
    checked, diagnostics = checked_parts(value, final=True)
    assert len(checked.assessments) == 5 and len(checked.alternatives) == 2
    assert diagnostics['partial'] and diagnostics['dropped']['assessments'] == 1
    assert 'PRIVATE' not in str(diagnostics) and 'private-invalid-id' not in str(diagnostics)


def test_isolated_validation_drops_whole_option_with_bad_action():
    value = evaluation(final=True)
    value['alternatives'][0]['actions'][0]['depends_on'] = ['recruit']
    checked, diagnostics = checked_parts(value, final=True)
    assert [option.id for option in checked.alternatives] == ['community-hosted']
    assert diagnostics['dropped']['alternatives'] == 1 and diagnostics['partial']


def test_isolated_final_validation_drops_requested_extra_searches():
    checked, diagnostics = checked_parts(evaluation(), final=True)
    assert not checked.next_searches and checked.alternatives
    assert diagnostics['dropped']['next_searches'] == 2 and diagnostics['partial']


def test_fastpath_omission_and_unsupported_normalization_are_incomplete():
    value = evaluation(final=True)
    value['assessments'][0]['evidence'] = []
    value['alternatives'][1]['assignments'][0]['assessment_id'] = 'missing'
    checked, diagnostics = checked_parts(value, final=True)
    assert len(checked.alternatives) == 1
    assert diagnostics['partial'] and diagnostics['normalized']['assessments'] >= 1
    assert diagnostics['dropped']['alternatives'] == 1


def test_bad_final_options_retain_revalidated_provisional_options_and_safe_summary():
    events = []

    class Provider:
        available = True
        model = 'fake'

        def structured(self, schema, system, payload):
            if schema.__name__ == 'RetrievalPlan':
                result = {'intent': 'Workshop', 'requirements': REQUIREMENTS,
                          'lookups': [{'kind': 'people', 'terms': ['teaching', 'school', 'recruitment', 'execution']}]}
            elif schema.__name__ == 'GapAssessment':
                result = evaluation()
            else:
                final = evaluation(final=True)
                for option in final['alternatives']:
                    option['actions'][0]['depends_on'] = ['recruit']
                result = {'summary': 'UNSUPPORTED FINAL PROMISE', 'clarification': 'UNSUPPORTED FINAL PROMISE', 'next_steps': ['UNSUPPORTED OUTREACH'],
                          'strategy_evaluation': final, 'findings': []}
            return schema.model_validate(result), {}

    result = NetworkAgent(Provider()).answer(workshop_data(), AgentRequest(question='Plan an AI workshop'), 1,
        emit=lambda kind, payload: events.append((kind, payload)), iterative=True)
    assert result['strategy_validation']['partial']
    assert result['strategy_validation']['previous_evaluation_retained']
    assert [option['id'] for option in result['strategy_evaluation']['alternatives']] == ['school-hosted']
    assert len(result['strategy_evaluation']['assessments']) == 5
    assert 'UNSUPPORTED' not in result['summary'] and not result['next_steps']
    assert result['clarification'] == ''
    assert [p for kind, p in events if kind == 'assessment'][-1]['validation_summary']['partial']


def test_prior_options_cannot_reappear_when_final_pack_lacks_their_sources():
    from adapters.network.model import GraphQuery
    from adapters.network.retrieval import NetworkRetrieval
    from adapters.network.strategy_reasoning import GapAssessment, retain_provisional_options

    retriever = NetworkRetrieval(workshop_data(), GraphQuery())
    pack = retriever.pack([retriever.context('project:previous'), retriever.context('org:school')], REQUIREMENTS)
    pack['evidence'] = [e for e in pack['evidence'] if e['id'] != 'evidence:a']
    prior = GapAssessment.model_validate(evaluation())
    assert retain_provisional_options(GapAssessment(), prior, pack, REQUIREMENTS, 'Plan an AI workshop') is None


@pytest.mark.parametrize('stage', ['GapAssessment', 'StrategyAnswer'])
def test_wire_omissions_are_reported_as_incomplete(stage):
    class Provider:
        available = True
        model = 'fixture'
        def structured(self, schema, system, payload):
            name = schema.__name__
            if name == 'RetrievalPlan':
                result = {'intent': 'Workshop', 'requirements': REQUIREMENTS,
                          'lookups': [{'kind': 'context', 'entity_id': 'project:previous'},
                                      {'kind': 'context', 'entity_id': 'org:school'}]}
            elif name == 'GapAssessment':
                result = evaluation(final=True)
            else:
                result = {'summary': 'UNCHECKED PROPOSAL', 'strategy_evaluation': evaluation(final=True)}
            return schema.model_validate(result), {'dropped_proposals': int(name == stage)}
    result = NetworkAgent(Provider()).answer(workshop_data(), AgentRequest(question='Plan a workshop'), 1, iterative=True)
    assert result['strategy_validation']['partial']
    assert 'UNCHECKED PROPOSAL' not in result['summary']
