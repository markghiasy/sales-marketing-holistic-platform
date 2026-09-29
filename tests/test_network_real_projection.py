from datetime import UTC, datetime
from dataclasses import replace

import psycopg

from adapters.network.source import SourceRepository, SourceRecord, fingerprint

NOW = datetime(2026,9,30,12,tzinfo=UTC)


def test_many_messages_keep_linear_dependencies_and_visibility_proofs(source_seed):
    from adapters.network.real_projection import project_records
    dsn,ids=source_seed
    source=SourceRepository(dsn)
    records=tuple(r for batch in source.snapshot_pages(100) for r in batch.records)
    original=next(r for r in records if r.kind=='message')
    messages=[]
    for i in range(200):
        payload={**original.payload,'id':str(i)}
        messages.append(SourceRecord('message',str(i),fingerprint(payload),payload))
    projection=project_records(tuple(r for r in records if r.kind!='message')+tuple(messages),(),NOW)
    # A message depends on its own content and identity/visibility bindings, not
    # every other message from the same contact. The node retains that proof.
    assert sum(len(v) for v in projection.dependencies.values())<200*30
    assert all('message:'+str(i) in projection.dependencies['node:identity:'+ids['contact']] for i in range(200))
    assert 'contact_hidden:'+ids['contact'] in projection.dependencies['evidence:message:0']


def project(dsn):
    from adapters.network.real_projection import project_records
    source = SourceRepository(dsn)
    records = tuple(r for batch in source.snapshot_pages(100) for r in batch.records)
    return project_records(records, (), NOW, binding=source.audit()['binding'])


def test_canonical_identity_direct_message_and_exact_source(source_seed):
    dsn, ids = source_seed
    p = project(dsn)
    assert {n['id'] for n in p.entities} == {'person:'+ids['owner'], 'identity:'+ids['contact']}
    assert p.owner_id == 'person:'+ids['owner']
    assert p.messages[0]['direct'] is True
    assert p.messages[0]['direction'] == 'in'
    assert p.messages[0]['known_at'].startswith('2026-09-30')
    assert p.evidence[0]['text'] == 'Project note'
    assert len(p.assertions) == 1
    assert p.assertions[0]['relation'] == 'In contact'
    assert not p.strategies and not p.work


def test_group_and_cc_messages_do_not_make_direct_relationships(source_seed):
    dsn, ids = source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute('update thread set is_group=true')
    p = project(dsn)
    assert not any(m['direct'] for m in p.messages)
    assert not p.assertions
    with psycopg.connect(dsn) as conn:
        conn.execute('update thread set is_group=false')
        conn.execute("update message_participant set role='cc'")
    assert not project(dsn).assertions


def test_same_name_merge_undo_hidden_and_deleted_support(source_seed):
    dsn, ids = source_seed
    with psycopg.connect(dsn) as conn:
        other = str(conn.execute("insert into identity(channel,handle,display_name) values ('whatsapp','other','Morgan') returning id").fetchone()[0])
        person = str(conn.execute("insert into person(primary_name) values ('Morgan') returning id").fetchone()[0])
    assert len([n for n in project(dsn).entities if n['name']=='Morgan']) == 2
    with psycopg.connect(dsn) as conn:
        conn.execute('update identity set person_id=%s where id=ANY(%s)',(person,[ids['contact'],other]))
    assert len([n for n in project(dsn).entities if n['name']=='Morgan']) == 1
    with psycopg.connect(dsn) as conn:
        conn.execute('update identity set person_id=null where id=%s',(other,))
    assert len([n for n in project(dsn).entities if n['name']=='Morgan']) == 2
    with psycopg.connect(dsn) as conn:
        conn.execute('insert into contact_hidden(contact_key) values (%s)',(person,))
    p=project(dsn)
    assert 'person:'+person not in {n['id'] for n in p.entities}
    assert not p.messages and not p.evidence
    with psycopg.connect(dsn) as conn:
        conn.execute('delete from contact_hidden')
        conn.execute('delete from message_participant')
        conn.execute('delete from message')
    assert not project(dsn).assertions


def test_multiple_message_supports_survive_one_deletion(source_seed):
    dsn, ids = source_seed
    with psycopg.connect(dsn) as conn:
        mid=conn.execute("insert into message(thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw) select thread_id,channel,'second',direction,sent_at,from_identity_id,'Follow up','{}' from message returning id").fetchone()[0]
        conn.execute("insert into message_participant values (%s,%s,'to')",(mid,ids['self']))
    assert len(project(dsn).assertions[0]['evidence_ids'])==2
    with psycopg.connect(dsn) as conn:
        conn.execute('delete from message_participant where message_id=%s',(ids['message'],))
        conn.execute('delete from message where id=%s',(ids['message'],))
    assert len(project(dsn).assertions[0]['evidence_ids'])==1


def test_employment_uses_current_snapshot_not_accumulated_stale_facts(source_seed):
    dsn, ids=source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute("update identity set channel='linkedin',handle='https://linkedin.test/morgan' where id=%s",(ids['contact'],))
        conn.execute("insert into linkedin_connection(id,company,position) values ('https://linkedin.test/morgan','Current Ltd','Engineer')")
        org=conn.execute("insert into organization(canonical_name) values ('old') returning id").fetchone()[0]
        conn.execute("insert into fact(subject_identity_id,fact_type,object_org_id,confidence,source,status) values (%s,'works_at',%s,1,'linkedin_connection','confirmed')",(ids['contact'],org))
    p=project(dsn)
    jobs=[c for c in p.assertions if c['relation']=='Works at']
    names={n['id']:n['name'] for n in p.entities}
    assert len(jobs)==1 and names[jobs[0]['target']]=='Current Ltd'
    assert jobs[0]['valid_from'] is None
    assert any(a['label']=='Engineer' for a in p.profiles)
    assert all(n['kind']!='project' for n in p.entities)


def test_unmerged_self_aliases_and_hidden_aliases_do_not_leak(source_seed):
    dsn,ids=source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute("insert into identity(channel,handle,is_self) values ('whatsapp','self',true)")
        conn.execute('insert into contact_hidden(contact_key) values (%s)',(ids['contact'],))
    p=project(dsn)
    assert p.owner_id.startswith('owner:')
    assert len(p.entities)==1
    assert not p.evidence


def test_automated_latest_contact_and_bulk_only_recipients_are_not_exposed(source_seed):
    dsn,ids=source_seed
    with psycopg.connect(dsn) as conn:
        conn.execute('update message set is_automated=true')
    assert {n['id'] for n in project(dsn).entities}=={'person:'+ids['owner']}
    with psycopg.connect(dsn) as conn:
        conn.execute('update message set is_automated=false')
        for i in range(11):
            recipient=conn.execute("insert into identity(channel,handle,display_name) values ('outlook',%s,'Bulk only') returning id",(f'bulk{i}@example.test',)).fetchone()[0]
            conn.execute("insert into message_participant values (%s,%s,'cc')",(ids['message'],recipient))
    p=project(dsn)
    assert all(n['name']!='Bulk only' for n in p.entities)
    assert not p.assertions


def test_cached_brief_is_not_evidence_or_project(source_seed):
    from adapters.network.real_projection import project_records
    dsn,_=source_seed
    source=SourceRepository(dsn)
    records=tuple(r for p in source.snapshot_pages(100) for r in p.records)
    fake=SourceRecord('ai_brief','cached','unused',{'summary':'Morgan leads security at Secret Project','graph':{'project':'Secret Project'}})
    p=project_records((*records,fake),(),NOW,binding=source.audit()['binding'])
    assert all(n['kind']!='project' for n in p.entities)
    assert not p.strategies
