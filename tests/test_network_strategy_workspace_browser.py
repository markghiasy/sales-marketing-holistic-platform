"""Progressive workspace contracts without live models or source databases."""
import threading

import pytest
from flask import render_template
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from scripts.network_demo import create_app


@pytest.fixture
def page():
    app = create_app(testing=True)
    if not any(rule.rule == '/strategy' for rule in app.url_map.iter_rules()):
        app.add_url_rule('/strategy', 'strategy_ui_fixture', lambda: render_template('strategy.html'))
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page.base_url = f'http://127.0.0.1:{server.server_port}'
        page.add_init_script("""
          window.streams=[];
          window.EventSource=class {
            constructor(url){this.url=url;this.listeners={};window.streams.push(this);}
            addEventListener(name,fn){this.listeners[name]=fn;}
            close(){this.closed=true;}
            emit(event){const value={data:JSON.stringify(event)};this.onmessage?.(value);}
          };
        """)
        page.route('**/network/agent/status.json', lambda r: r.fulfill(json={'configured': True, 'remaining': 20, 'model': 'fixture'}))
        yield page
        browser.close()
    server.shutdown()


def event(page, seq, kind, data):
    page.evaluate('(e)=>window.streams.at(-1).emit(e)', {'seq': seq, 'type': kind, 'data': data})


def partial(extra=False):
    nodes = [{'id': 'person:a', 'name': 'Teaching lead', 'kind': 'person'}]
    if extra:
        nodes.append({'id': 'org:b', 'name': 'Venue lead', 'kind': 'organization'})
    return {'version': 1, 'entities': nodes, 'evidence': [], 'strategy_graph': {
        'nodes': nodes, 'edges': [], 'requirements': [{'id': 'teaching', 'label': 'Teaching', 'origin': 'suggested', 'status': 'matching_evidence'}],
        'records': [{'id': 'record:a', 'label': 'Past teaching', 'quote': '<script>evidence</script>', 'entity_ids': ['person:a'], 'evidence_ids': []}],
        'evidence': [],
    }}


def start(page):
    calls = []
    page.route('**/network/strategy/runs', lambda r: (calls.append(r.request.post_data_json), r.fulfill(status=202, json={'run_id': 'run-a', 'status': 'running'})))
    page.goto(page.base_url + '/strategy?focus=person:sam&mode=history&as_of=2026-09-25T12%3A00%3A00Z')
    page.get_by_label('Your goal').fill('Plan a school AI workshop')
    assert calls == []
    page.get_by_role('button', name='Start analysis', exact=True).click()
    page.wait_for_function('window.streams.length === 1')
    return calls


def test_partial_is_visible_before_final_and_failure_keeps_it(page):
    calls = start(page)
    event(page, 1, 'plan', {'intent': 'Plan a workshop', 'requirements': [{'id': 'teaching', 'label': 'Teaching', 'origin': 'suggested'}], 'tasks': [{'id': 't1', 'label': 'Find teaching experience'}, {'id': 't2', 'label': 'Find venue leads'}]})
    event(page, 2, 'task_started', {'task_id': 't1'})
    event(page, 3, 'partial', partial())
    expect(page.locator('.strategy-record')).to_contain_text('Past teaching')
    expect(page.locator('.strategy-record script')).to_have_count(0)
    expect(page.locator('#strategy-analysis')).not_to_contain_text('What the evidence supports')
    event(page, 4, 'failed', {'message': 'The final analysis could not complete.'})
    expect(page.locator('#strategy-status')).to_contain_text('Partial results retained')
    expect(page.locator('.strategy-record')).to_be_visible()
    expect(page.get_by_role('button', name='Run again', exact=True)).to_be_enabled()
    assert len(calls) == 1
    assert calls[0]['mode'] == 'history'
    assert calls[0]['focus'] == 'person:sam'
    assert 'workshop' not in page.url


def test_failed_search_scope_is_unknown_even_with_other_matching_evidence(page):
    start(page)
    payload = {**partial(), 'summary': 'Some evidence found', 'retrieval': {
        'scope': {'scanned_people': 3}, 'budget': {'selected_records': 1},
        'coverage': [{'label': 'Teaching', 'status': 'matching_evidence', 'search_status': 'incomplete'}, {'label': 'Venue', 'status': 'search_incomplete'}],
        'tasks': [{'task_id': 'venue-check', 'kind': 'people', 'terms': ['venue'], 'status': 'failed'}],
    }}
    event(page, 1, 'completed', payload)
    page.get_by_text('Search coverage', exact=True).click()
    expect(page.locator('.agent-coverage')).to_contain_text('Search incomplete; remaining coverage is unknown')
    expect(page.locator('#strategy-tasks')).to_contain_text('Unavailable')


def test_invalidation_clears_evidence_and_stale_event_cannot_restore_it(page):
    start(page)
    event(page, 1, 'partial', partial())
    event(page, 2, 'invalidated', {'message': 'Source access changed.'})
    expect(page.locator('.strategy-record')).to_have_count(0)
    event(page, 1, 'partial', partial())
    expect(page.locator('.strategy-record')).to_have_count(0)
    expect(page.locator('#strategy-status')).to_contain_text('no longer valid')


def test_revocation_drops_old_answer_from_follow_up_context(page):
    calls = start(page)
    event(page, 1, 'completed', {**partial(), 'summary': 'Old private finding', 'findings': [], 'gaps': [], 'next_steps': []})
    event(page, 2, 'invalidated', {})
    page.get_by_role('button', name='Run again', exact=True).click()
    page.wait_for_function('window.streams.length === 2')
    assert calls[1]['history'] == []


@pytest.mark.parametrize('unavailable', [False, True])
def test_follow_up_rechecks_completed_sources_before_model_request(page, unavailable):
    calls = start(page)
    event(page, 1, 'completed', {**partial(), 'summary': 'Old private finding', 'findings': [], 'gaps': [], 'next_steps': []})
    if unavailable:
        page.route('**/network/strategy/runs/run-a', lambda r: r.fulfill(status=503, json={'error': 'Cannot validate source access.'}))
    else:
        page.route('**/network/strategy/runs/run-a', lambda r: r.fulfill(json={'run_id': 'run-a', 'status': 'invalidated', 'events': [{'seq': 2, 'type': 'invalidated', 'data': {}}]}))
    page.get_by_label('Your goal').fill('A follow-up goal')
    page.get_by_role('button', name='Run again', exact=True).click()
    expect(page.locator('#strategy-status')).to_contain_text('Retained context was cleared')
    assert len(calls) == 1
    expect(page.locator('.strategy-record')).to_have_count(0)
    expect(page.get_by_label('Your goal')).to_have_value('A follow-up goal')
    page.get_by_role('button', name='Run again', exact=True).click()
    page.wait_for_function('window.streams.length === 2')
    assert calls[1]['history'] == []


def test_reload_replays_without_create_and_cancel_keeps_partial(page):
    calls = []
    page.route('**/network/strategy/runs', lambda r: (calls.append(r.request), r.fulfill(status=500)))
    page.route('**/network/strategy/runs/run-a', lambda r: r.fulfill(json={'run_id': 'run-a', 'status': 'running', 'request': {'question': 'Original workshop goal', 'focus': 'person:sam', 'as_of': '2026-09-22T12:00:00Z', 'mode': 'history'}, 'events': [{'seq': 1, 'type': 'partial', 'data': partial()}]}))
    page.route('**/network/strategy/runs/run-a/cancel', lambda r: r.fulfill(json={'status': 'cancelling'}))
    page.goto(page.base_url + '/strategy?run=run-a')
    expect(page.locator('.strategy-record')).to_be_visible()
    expect(page.get_by_label('Your goal')).to_have_value('Original workshop goal')
    expect(page.locator('#strategy-context')).to_contain_text('2026-09-22')
    page.get_by_role('button', name='Stop analysis', exact=True).click()
    event(page, 2, 'cancelled', {})
    expect(page.locator('.strategy-record')).to_be_visible()
    expect(page.locator('#strategy-status')).to_contain_text('Stopped')
    assert calls == []


def test_search_handoff_never_auto_spends_and_preserves_draft(page):
    calls = []
    page.route('**/network/search.json?*', lambda r: r.fulfill(json={'status': 'needs_clarification', 'criteria': [], 'unresolved': 'goal', 'results': []}))
    page.route('**/network/strategy/runs', lambda r: (calls.append(r.request), r.fulfill(status=500)))
    page.route('**/network/strategy/drafts', lambda r: r.fulfill(json={'draft_id': 'draft-a'}))
    page.route('**/network/strategy/drafts/draft-a', lambda r: r.fulfill(json={'question': 'Plan my workshop'}))
    page.goto(page.base_url + '/inbox?mode=history')
    page.locator('#searchbar').click()
    page.locator('#discovery-query').fill('Plan my workshop')
    page.get_by_role('button', name='Search', exact=True).click()
    expect(page.get_by_role('button', name='Continue in Strategy', exact=True)).to_be_visible()
    assert calls == []
    page.get_by_role('button', name='Continue in Strategy', exact=True).click()
    expect(page.get_by_label('Your goal')).to_have_value('Plan my workshop')
    assert calls == []
    assert 'workshop' not in page.url


def test_map_update_preserves_positions_and_mobile_does_not_overflow(page):
    start(page)
    event(page, 1, 'partial', partial())
    before = page.locator('.strategy-canvas').evaluate('(el)=>el._cy.getElementById("person:a").position()')
    event(page, 2, 'partial', partial(extra=True))
    after = page.locator('.strategy-canvas').evaluate('(el)=>el._cy.getElementById("person:a").position()')
    assert before == after
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path='tmp/strategy-workspace-mobile.png', full_page=True)


def test_assessment_options_keep_limitations_and_dependencies_visible(page):
    start(page)
    event(page, 1, 'plan', {'intent': 'Workshop', 'requirements': [{'id': 'teaching', 'label': 'Teaching'}, {'id': 'venue', 'label': 'Venue'}], 'tasks': []})
    event(page, 2, 'partial', partial())
    evaluation = {
        'round': 1,
        'assessments': [{'id': 'a1', 'requirement_id': 'teaching', 'subject_id': 'person:a', 'state': 'supported', 'scope': 'historical_observation', 'statement': 'Taught a previous workshop', 'limitation': 'Availability this time is unknown.', 'evidence': []}, {'id': 'a2', 'requirement_id': 'venue', 'subject_id': 'org:b', 'state': 'insufficient', 'scope': 'unverified_goal_fit', 'statement': 'A possible venue lead', 'limitation': 'Employment does not establish venue authority.', 'evidence': []}],
        'alternatives': [{'id': 'school', 'label': 'School-hosted option', 'status': 'candidate', 'assignments': [{'requirement_id': 'teaching', 'subject_id': 'person:a', 'assessment_id': 'a1'}], 'comparison': {'requirement_coverage': 'Teaching experience found', 'unresolved_dependencies': 'Venue and date remain unknown'}, 'actions': [{'id': 'confirm', 'text': 'Confirm venue and date', 'kind': 'verify', 'depends_on': []}, {'id': 'invite', 'text': 'Coordinate invitations', 'kind': 'coordinate', 'depends_on': ['confirm']}]}],
        'pending_constraints': [{'question': 'What is the budget?', 'origin': 'missing_user_detail'}],
        'next_searches': [{'requirement_id': 'venue', 'reason': 'Check the previous workshop venue'}],
    }
    event(page, 3, 'assessment', evaluation)
    expect(page.locator('#strategy-evaluation')).to_contain_text('Availability this time is unknown.')
    expect(page.locator('#strategy-evaluation')).to_contain_text('Employment does not establish venue authority.')
    expect(page.locator('[data-alternative="school"]')).to_contain_text('After: Confirm venue and date')
    expect(page.locator('#strategy-evaluation')).to_contain_text('Historical evidence')
    expect(page.locator('#strategy-evaluation')).to_contain_text('What is the budget?')
    event(page, 4, 'failed', {'message': 'Further search unavailable.'})
    expect(page.locator('[data-alternative="school"]')).to_be_visible()
    page.screenshot(path='tmp/strategy-workspace-desktop.png', full_page=True)
    event(page, 5, 'invalidated', {})
    expect(page.locator('#strategy-evaluation')).to_be_hidden()


def test_real_eventsource_shows_partial_before_synthesis_and_reloads_without_spend():
    from test_network_strategy_routes import Provider

    synthesis_started, release_synthesis = threading.Event(), threading.Event()

    class PausedProvider(Provider):
        def structured(self, schema, system, payload):
            if schema.__name__ == 'StrategyAnswer':
                synthesis_started.set()
                assert release_synthesis.wait(15)
            return super().structured(schema, system, payload)

    provider = PausedProvider()
    app = create_app(testing=True, agent_provider=provider)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
            page.goto(f'http://127.0.0.1:{server.server_port}/strategy')
            page.get_by_label('Your goal').fill('Who can help with an AI workshop?')
            page.get_by_role('button', name='Start analysis', exact=True).click()
            expect(page.locator('.strategy-record').first).to_be_visible()
            assert synthesis_started.wait(5)
            assert provider.calls == 2
            expect(page.locator('#strategy-analysis .agent-summary')).to_have_count(0)
            release_synthesis.set()
            expect(page.locator('#strategy-status')).to_contain_text('Analysis complete')
            expect(page.locator('#strategy-analysis')).to_contain_text('Validate the available leads')
            assert provider.calls == 3
            page.screenshot(path='tmp/strategy-workspace-integrated.png', full_page=True)
            page.reload()
            expect(page.locator('#strategy-status')).to_contain_text('Analysis complete')
            expect(page.get_by_label('Your goal')).to_have_value('Who can help with an AI workshop?')
            assert provider.calls == 3
            browser.close()
    finally:
        release_synthesis.set()
        server.shutdown()


@pytest.mark.parametrize('retained', [False, True])
def test_partial_validation_is_visible_and_does_not_claim_complete_analysis(page, retained):
    start(page)
    event(page, 1, 'partial', partial())
    validation = {'partial': True, 'previous_evaluation_retained': retained}
    evaluation = {
        'assessments': [],
        'alternatives': [{'id': 'kept-option', 'label': 'Retained conditional option', 'status': 'candidate', 'assignments': [], 'comparison': {}, 'actions': []}],
        'pending_constraints': [], 'next_searches': [],
        'validation_summary': validation,
        'validation_note': 'Source checks do not establish semantic correctness.',
    }
    event(page, 2, 'assessment', evaluation)
    expect(page.locator('#strategy-evaluation .strategy-validation-notice')).to_contain_text('Some model suggestions were omitted')
    expect(page.locator('#strategy-evaluation .strategy-validation-notice')).to_contain_text('remain provisional')
    expect(page.locator('[data-alternative="kept-option"]')).to_be_visible()
    final_evaluation = {key: value for key, value in evaluation.items() if key not in ('validation_summary', 'validation_note')}
    event(page, 3, 'completed', {**partial(), 'summary': 'A partial assessment is available.', 'findings': [], 'gaps': [], 'next_steps': [], 'strategy_evaluation': final_evaluation, 'strategy_validation': validation})
    expect(page.locator('#strategy-status')).to_contain_text('Analysis finished with omitted suggestions')
    expect(page.locator('#strategy-status')).not_to_contain_text('Analysis complete')
    expect(page.locator('#strategy-analysis .strategy-validation-notice')).to_contain_text('remain provisional')
    expect(page.locator('#strategy-evaluation .strategy-validation-notice')).to_be_visible()
    expect(page.locator('.strategy-record')).to_be_visible()
    if retained:
        expect(page.locator('#strategy-evaluation .strategy-validation-notice')).to_contain_text('Earlier provisional options')
        expect(page.locator('#strategy-evaluation .strategy-validation-notice')).to_contain_text('rechecked')
        page.screenshot(path='tmp/strategy-workspace-partial-validation.png', full_page=True)
    else:
        expect(page.locator('#strategy-evaluation .strategy-validation-notice')).not_to_contain_text('Earlier provisional options')
