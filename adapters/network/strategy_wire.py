"""Compact model proposals; source quotations and assignment bindings are code-owned."""
from copy import deepcopy

from pydantic import ValidationError

from .strategy_reasoning import Alternative, NextSearch, PendingConstraint, RequirementAssessment


def compact_schema(schema):
    value = deepcopy(schema)
    definitions = value['$defs']
    for name, fields in (('EvidenceQuote', ('quote',)),
                         ('RequirementAssessment', ('statement',)),
                         ('RequirementAssignment', ('requirement_id', 'subject_id'))):
        node = definitions[name]
        for field in fields:
            node['properties'].pop(field, None)
        node['required'] = [key for key in node.get('required', []) if key not in fields]
    evaluation = definitions.get('GapAssessment', value)
    evaluation['properties']['assessments']['maxItems'] = 8
    evaluation['properties']['alternatives']['maxItems'] = 2
    definitions['Alternative']['properties']['actions']['maxItems'] = 2
    for name, fields, limit in (
            ('RequirementAssessment', ('limitation',), 200),
            ('Comparison', tuple(definitions['Comparison']['properties']), 160),
            ('StrategyAction', ('text',), 200),
            ('PendingConstraint', ('question',), 200)):
        for field in fields:
            definitions[name]['properties'][field]['maxLength'] = limit
    if 'strategy_evaluation' in value['properties']:
        for field in ('findings', 'gaps', 'next_steps', 'clarification'):
            value['properties'].pop(field, None)
        definitions.pop('Finding', None)
    return value


def compact_previous(value):
    """Previous quotes already exist in the evidence pack; transmit references once."""
    result = deepcopy(value)
    for row in result.get('assessments', []):
        row.pop('statement', None)
        for quote in row.get('evidence', []):
            quote.pop('quote', None)
    for option in result.get('alternatives', []):
        # Keep the output shape, but omit old generated comparison prose. Pending
        # constraints and action dependencies retain the issues to resolve.
        option['comparison'] = dict.fromkeys(option.get('comparison', {}), 'Reassess from current evidence.')
        for assignment in option.get('assignments', []):
            assignment.pop('requirement_id', None)
            assignment.pop('subject_id', None)
        for action in option.get('actions', []):
            for quote in action.get('evidence', []):
                quote.pop('quote', None)
    result.pop('next_searches', None)  # Outcomes are already in the task ledger.
    return result


def compact_payload(payload):
    result = deepcopy(payload)
    sources = {e['id']: e['text'] for e in result.get('evidence', [])}
    for record in result.get('records', []):
        quote = record.get('quote')
        if quote and any(quote in sources.get(eid, '') for eid in record.get('evidence_ids', [])):
            record.pop('quote')
    result.pop('source_entities', None)  # Exact same bindings are in records.
    if 'previous_evaluation' in result:
        result['previous_evaluation'] = compact_previous(result['previous_evaluation'])
    return result


def expand_output(raw, payload):
    """Expand only supplied references, leaving semantic checks to the strict validator.

    Malformed proposals are discarded as units, not repaired with invented facts.
    Return a count so callers must visibly mark any incomplete answer.
    """
    value = deepcopy(raw)
    evaluation = value.get('strategy_evaluation', value)
    sources = {e['id']: e['text'] for e in payload.get('evidence', [])}
    dropped = 0

    def quotes(rows):
        return [{'evidence_id': row['evidence_id'], 'quote': sources[row['evidence_id']][:1000]}
                for row in rows]

    accepted = []
    rows = evaluation.get('assessments', [])
    for row in rows[:8]:
        try:
            row['evidence'] = quotes(row.get('evidence', []))
            row['statement'] = '\n'.join(q['quote'] for q in row['evidence'])[:3000] or 'No source quotation was supplied for this assessment.'
            accepted.append(RequirementAssessment.model_validate(row).model_dump())
        except (KeyError, TypeError, AttributeError, ValidationError):
            dropped += 1
    dropped += max(0, len(rows) - 8)
    evaluation['assessments'] = accepted
    assessments = {row['id']: row for row in accepted}

    accepted = []
    options = evaluation.get('alternatives', [])
    for option in options[:2]:
        try:
            option['assignments'] = [
                {'assessment_id': assignment['assessment_id'],
                 'requirement_id': assessments[assignment['assessment_id']]['requirement_id'],
                 'subject_id': assessments[assignment['assessment_id']]['subject_id']}
                for assignment in option['assignments']]
            for action in option.get('actions', []):
                action['evidence'] = quotes(action.get('evidence', []))
            # Keep dependencies intact: an over-budget action list rejects the option.
            if len(option.get('actions', [])) > 2:
                raise ValueError('action_budget')
            accepted.append(Alternative.model_validate(option).model_dump())
        except (KeyError, TypeError, AttributeError, ValueError):
            dropped += 1
    dropped += max(0, len(options) - 2)
    evaluation['alternatives'] = accepted
    for field, model, limit in (('pending_constraints', PendingConstraint, 8), ('next_searches', NextSearch, 3)):
        accepted = []
        rows = evaluation.get(field, [])
        for row in rows[:limit]:
            try:
                accepted.append(model.model_validate(row).model_dump())
            except ValidationError:
                dropped += 1
        dropped += max(0, len(rows) - limit)
        evaluation[field] = accepted
    if 'strategy_evaluation' in value:
        # These legacy fields duplicate structured constraints/actions. Derive
        # them rather than rejecting valid proposals over redundant prose shape.
        value.update(findings=[], gaps=[row['question'] for row in evaluation['pending_constraints']][:6],
                     next_steps=[], clarification='')
    return value, dropped
