from datetime import UTC, datetime

import psycopg
import pytest

from test_network_index import setup_index


@pytest.fixture
def real_client(network_database):
    from adapters.network.service import NetworkService
    from scripts.network_demo import create_app
    source,store,ids,_=setup_index(network_database,5)
    app=create_app(testing=True,network_service=NetworkService(store,source))
    return app.test_client(),store,ids


def test_real_routes_never_load_fixtures(real_client,monkeypatch):
    from adapters.network.service import NetworkService
    from scripts.network_demo import create_app
    from adapters.network.source import SourceRepository
    client,store,ids=real_client
    monkeypatch.setattr('scripts.network_demo.ScenarioStore',lambda:pytest.fail('fixture loaded'))
    app=create_app(testing=True,network_service=NetworkService(store,SourceRepository(store._dsn)))
    client=app.test_client()
    for path in ('/inbox','/network'):
        page=client.get(path)
        assert page.status_code==200
        assert b'Synthetic demo' not in page.data and b'Jordan Ellis' not in page.data
    for path in ('reply','reset'):
        assert client.post('/network/demo/'+path).status_code==404
    status=client.get('/network/agent/status.json').json
    assert status['data_source']=='real' and not status['configured']
    graph=client.get('/network/graph.json').json
    assert graph['backend']=='postgresql' and graph['data_source']=='real'
    assert datetime.fromisoformat(graph['as_of']).date()==datetime.now(UTC).date()
    assert graph['freshness']['version']==store.status().version


def test_real_contacts_paginate_and_source_links_are_revision_bound(real_client):
    client,store,ids=real_client
    first=client.get('/inbox/conversations.json?limit=2').json
    second=client.get('/inbox/conversations.json?limit=2&after='+first[-1]['person_key']).json
    assert len(first)==len(second)==2
    assert not {p['person_key'] for p in first}&{p['person_key'] for p in second}
    person='identity:'+ids['contact']
    detail=client.get('/inbox/conversation/'+person+'.json?as_of=2026-10-02T00:00:00Z').json
    assert detail['messages'] and detail['data_source']=='real'
    assert all('Fictional' not in m['subject'] for m in detail['messages'])
    graph=client.get('/network/graph.json?as_of=2026-10-02T00:00:00Z&focus='+person).json
    evidence_id=graph['edges'][0]['evidence_ids'][0]
    evidence=client.get('/network/evidence/'+evidence_id+'.json?as_of=2026-10-02T00:00:00Z&version='+str(graph['version']))
    assert evidence.status_code==200 and 'security' in evidence.json['text']
    assert client.get('/network/evidence/'+evidence_id+'.json?version=999999').status_code==409
    with psycopg.connect(store._dsn) as conn:
        conn.execute("update message set body_text='Corrected source'")
    assert client.get('/network/evidence/'+evidence_id+'.json?as_of=2026-10-02T00:00:00Z&version='+str(graph['version'])).status_code==409


def test_mutations_enforce_local_origin_and_selected_evidence(real_client):
    client,store,ids=real_client
    for path in ('/network/agent.json','/network/profile/extract','/network/profile/review'):
        assert client.post(path,json={},headers={'Origin':'https://other.example'}).status_code==403
        assert client.post(path,data='{}').status_code==415
    assert client.post('/network/profile/extract',json={'focus':'identity:'+ids['contact']}).status_code==400
    assert client.post('/network/agent.json',json={'question':'security'}).status_code==503


def test_context_profile_and_events_report_real_state(real_client):
    client,store,ids=real_client
    person='identity:'+ids['contact']
    for path in ('context','profile'):
        response=client.get('/network/'+path+'.json?focus='+person)
        assert response.status_code==200
        assert response.json['data_source']=='real'
        assert 'Synthetic' not in response.json['coverage']
    profile=client.get('/network/profile.json?as_of=2026-10-02T00:00:00Z&focus='+person).json
    assert profile['source_choices'] and not profile['assertions']
    response=client.get('/network/events',buffered=False)
    assert b'event: update' in next(iter(response.response))
    response.close()


def test_absent_or_future_source_never_appears_in_historical_slice(real_client):
    client,store,ids=real_client
    graph=client.get('/network/graph.json?as_of=2019-01-01T00:00:00Z').json
    assert not graph['edges']
    assert client.get('/network/evidence/unknown.json').status_code==404
    assert client.get('/inbox/conversation/unknown.json').status_code==404


def test_real_name_search_uses_bound_owner_instead_of_demo_owner(real_client):
    client,store,ids=real_client
    response=client.get('/network/search.json?q=Morgan&as_of=2026-10-02T00:00:00Z')
    assert response.status_code==200,response.json
    assert any(p['id']=='identity:'+ids['contact'] for p in response.json['results'])


def test_selected_extraction_and_confirmed_project_ui_contract(network_database):
    from test_network_changes import setup
    from scripts.network_real import create_app
    from adapters.network.service import NetworkService
    source,store,ids,snapshot,batch=setup(network_database)
    class Provider:
        available=True
        model='fake-selected'
        def structured(self,schema,system,payload):
            assert [e['id'] for e in payload['evidence']]==['message:'+ids['message']]
            return batch,{'input_tokens':10,'output_tokens':20}
    client=create_app(service=NetworkService(store,source),agent_provider=Provider(),testing=True).test_client()
    person='identity:'+ids['contact']
    response=client.post('/network/profile/extract',json={'focus':person,'as_of':'2026-10-02T00:00:00Z','evidence_ids':['message:'+ids['message']]})
    assert response.status_code==200,response.json
    saved=response.json
    profile=client.get('/network/profile.json?as_of=2026-10-02T00:00:00Z&focus='+person).json
    assert profile['proposals'][0]['status']=='pending'
    assert not profile['assertions']
    response=client.post('/network/profile/review',json={'proposal_id':saved['id'],'expected_version':saved['version'],'decision':'confirm','entity_bindings':{'new:aurora':'create'}})
    assert response.status_code==200,response.json
    profile=client.get('/network/profile.json?as_of=2026-10-02T00:00:00Z&focus='+person).json
    from adapters.network.profiles import validate_assertion
    actual=store.capture((person,),100).data
    for row in actual['strategic_assertions']:
        validate_assertion(actual,row)
    assert profile['assertions'][0]['status']=='confirmed'


def test_real_browser_graph_sources_and_model_unavailability(real_client,tmp_path):
    import threading
    from playwright.sync_api import sync_playwright,expect
    from werkzeug.serving import make_server
    client,store,ids=real_client
    server=make_server('127.0.0.1',0,client.application,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1500,'height':950})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            url=f'http://127.0.0.1:{server.server_port}'
            person='identity:'+ids['contact']
            page.goto(url+'/network?as_of=2026-10-02T00:00:00Z&focus='+person)
            expect(page.locator('#network-status')).to_contain_text('Local source')
            page.get_by_role('button',name='View evidence').first.click()
            expect(page.locator('.evidence-quote').first).to_contain_text('security')
            assert 'Fictional' not in page.locator('#inspector').inner_text()
            page.get_by_role('button',name='Focus neighborhood').click()
            expect(page.locator('#expansion-controls')).to_be_visible()
            page.get_by_role('button',name='Ask your network',exact=True).click()
            expect(page.locator('.agent-provider')).to_contain_text('not configured')
            page.screenshot(path=str(tmp_path/'real-network.png'),full_page=True)
            page.goto(url+'/inbox?as_of=2026-10-02T00:00:00Z&focus='+person)
            expect(page.get_by_role('link',name='Open full network')).to_be_visible()
            expect(page.locator('.demo-inbox-banner')).to_contain_text('Your source data')
            assert not errors
            browser.close()
    finally:
        server.shutdown()
