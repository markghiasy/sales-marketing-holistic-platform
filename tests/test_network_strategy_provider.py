from types import SimpleNamespace

import anthropic
import pytest

from adapters.network.agent import ClaudeProvider, StrategyAnswer
from adapters.network.strategy_reasoning import GapAssessment


@pytest.mark.parametrize('schema', [GapAssessment, StrategyAnswer])
@pytest.mark.parametrize('invalid', [False, True])
def test_complex_strategy_tools_avoid_provider_grammar_but_keep_local_validation(monkeypatch, schema, invalid):
    calls = []
    class Client:
        def __enter__(self):
            self.messages = self
            return self
        def __exit__(self, *args):
            pass
        def count_tokens(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(input_tokens=100)
        def create(self, **kwargs):
            value = {} if schema is GapAssessment else {'summary': 'Conditional', 'strategy_evaluation': {}}
            if invalid:
                value['unexpected_field'] = 'Must be rejected locally'
            return SimpleNamespace(stop_reason='tool_use',
                content=[SimpleNamespace(type='tool_use', name='submit', input=value)],
                usage=SimpleNamespace(input_tokens=100, output_tokens=30))
    monkeypatch.setattr(anthropic, 'Anthropic', lambda **kwargs: Client())
    provider = ClaudeProvider({'ANTHROPIC_API_KEY': 'fixture'})
    if invalid:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            provider.structured(schema, 'Test', {'evidence': []})
    else:
        result, _ = provider.structured(schema, 'Test', {'evidence': []})
        assert isinstance(result, schema)
    assert calls[0]['tools'][0]['strict'] is False
    assert calls[0]['tool_choice'] == {'type': 'tool', 'name': 'submit'}


def test_uncited_or_malformed_findings_are_omitted_before_strategy_validation():
    from adapters.network.agent import parse_strategy_answer
    value = {'summary': 'Proposal', 'strategy_evaluation': {}, 'findings': [
        {'text': 'Source observation', 'evidence_ids': ['evidence:a']},
        {'text': 'Unsupported assertion', 'evidence_ids': []},
        {'text': 'Malformed assertion', 'evidence_ids': ['evidence:a'], 'unexpected': True}]}
    answer, dropped = parse_strategy_answer(value)
    assert dropped == 2
    assert len(answer.findings) == 1
    assert 'Unsupported assertion' not in str(answer)
    assert 'Malformed assertion' not in str(answer)


@pytest.mark.parametrize('schema', [GapAssessment, StrategyAnswer])
def test_wire_contract_avoids_regenerating_sources_and_duplicate_bindings(schema):
    from adapters.network.strategy_wire import compact_schema
    wire = compact_schema(schema.model_json_schema())
    assert 'quote' not in wire['$defs']['EvidenceQuote']['properties']
    assert 'statement' not in wire['$defs']['RequirementAssessment']['properties']
    assert set(wire['$defs']['RequirementAssignment']['properties']) == {'assessment_id'}
    evaluation = wire if schema is GapAssessment else wire['$defs']['GapAssessment']
    assert evaluation['properties']['assessments']['maxItems'] == 8
    if schema is StrategyAnswer:
        assert 'findings' not in wire['properties']


def test_compact_output_expands_only_from_supplied_evidence_and_assessments():
    from adapters.network.strategy_wire import expand_output
    payload = {'evidence': [{'id': 'e:a', 'text': 'I taught a workshop.'}]}
    raw = {'assessments': [{'id': 'a', 'requirement_id': 'teaching', 'subject_id': 'person:a',
            'state': 'supported', 'scope': 'historical_observation', 'limitation': 'Availability unknown.',
            'evidence': [{'evidence_id': 'e:a'}]}],
        'alternatives': [{'id': 'option', 'label': 'Provisional', 'assignments': [{'assessment_id': 'a'}],
            'comparison': dict.fromkeys(['requirement_coverage', 'complementarity', 'evidence_support',
                                        'contact_paths', 'unresolved_dependencies'], 'Check first.')}],
        'next_searches': [], 'pending_constraints': []}
    expanded, dropped = expand_output(raw, payload)
    checked = GapAssessment.model_validate(expanded)
    assert checked.assessments[0].statement == 'I taught a workshop.'
    assert checked.assessments[0].evidence[0].quote == 'I taught a workshop.'
    assert checked.alternatives[0].assignments[0].subject_id == 'person:a'
    assert checked.alternatives[0].assignments[0].requirement_id == 'teaching'
    assert dropped == 0
    assert 'quote' not in raw['assessments'][0]['evidence'][0]
    raw['assessments'][0]['evidence'][0]['evidence_id'] = 'invented'
    expanded, dropped = expand_output(raw, payload)
    assert expanded['assessments'] == [] and expanded['alternatives'] == []
    assert dropped == 2


def test_compact_input_preserves_sources_and_dependencies_without_duplicate_prose():
    from adapters.network.strategy_wire import compact_payload
    payload = {'evidence': [{'id': 'e', 'text': 'Original source.'}],
        'records': [{'id': 'r', 'subject_id': 'person:a', 'quote': 'Original source.', 'evidence_ids': ['e']}],
        'source_entities': {'e': ['person:a']},
        'previous_evaluation': {'assessments': [], 'pending_constraints': [{'question': 'Date?'}],
            'next_searches': [{'reason': 'Already executed'}], 'alternatives': [{
                'id': 'a', 'assignments': [], 'comparison': {'contact_paths': 'Old generated prose'},
                'actions': [{'id': 'next', 'depends_on': ['first'], 'evidence': []}]}]}}
    wire = compact_payload(payload)
    assert wire['evidence'] == payload['evidence']
    assert wire['records'][0]['subject_id'] == 'person:a'
    assert 'quote' not in wire['records'][0]
    assert 'source_entities' not in wire
    previous = wire['previous_evaluation']
    assert previous['pending_constraints'] == [{'question': 'Date?'}]
    assert previous['alternatives'][0]['actions'][0]['depends_on'] == ['first']
    assert previous['alternatives'][0]['comparison'] == {'contact_paths': 'Reassess from current evidence.'}
    assert 'next_searches' not in previous
    assert payload['records'][0]['quote'] == 'Original source.'


def test_final_envelope_derives_duplicate_sections_from_structured_evaluation():
    from adapters.network.strategy_wire import compact_schema, expand_output
    wire = compact_schema(StrategyAnswer.model_json_schema())
    assert set(wire['properties']) == {'summary', 'strategy_evaluation'}
    raw = {'summary': 'Conditional approach', 'gaps': 'Wrong shape from model',
        'next_steps': 'Wrong shape', 'clarification': None,
        'strategy_evaluation': {'pending_constraints': [
            {'id': 'date', 'origin': 'missing_user_detail', 'question': 'When is the workshop?'}]}}
    expanded, _ = expand_output(raw, {'evidence': []})
    result = StrategyAnswer.model_validate(expanded)
    assert result.gaps == ['When is the workshop?']
    assert result.next_steps == [] and result.clarification == ''
