"""Source-backed real graph. No name merging or capabilities inferred from prose."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .model import timestamp
from .source import SourceRecord, SourceError, fingerprint
from .store import Projection
from ..resolution.organizations import normalise_org_name


def project_records(records: tuple[SourceRecord, ...], reviews: tuple[dict, ...],
                    observed_at: datetime, *, binding: str = '') -> Projection:
    tables = defaultdict(dict)
    for r in records:
        tables[r.kind][r.id] = r.payload
    identities, people = tables['identity'], tables['person']
    mappings, identity_deps = {}, {}
    for iid, identity in identities.items():
        person, seen = identity.get('person_id'), set()
        deps = {'identity:'+iid, 'contact_hidden:'+iid}
        while person:
            if person in seen or person not in people:
                raise SourceError('invalid_identity_binding')
            seen.add(person)
            deps.update(('person:'+person, 'contact_hidden:'+person))
            target = people[person].get('merged_into')
            if not target:
                break
            person = target
        mappings[iid] = 'person:'+person if person else 'identity:'+iid
        identity_deps[iid] = deps
    self_ids = [i for i,r in identities.items() if r.get('is_self')]
    if not self_ids:
        raise SourceError('owner_unresolved')
    owners = {mappings[i] for i in self_ids}
    owner = next(iter(owners)) if len(owners)==1 else 'owner:'+binding[:24]
    for iid in mappings:
        if mappings[iid] in owners:
            mappings[iid] = owner
    # All self bindings determine the virtual owner and the direction of activity.
    owner_deps = {k for i in self_ids for k in identity_deps[i]}
    node_deps = defaultdict(set)
    aliases = defaultdict(list)
    for iid, person in mappings.items():
        node_deps[person].update(identity_deps[iid])
        aliases[person].append(iid)
    hidden = {person for person,deps in node_deps.items()
              if any(k.removeprefix('contact_hidden:') in tables['contact_hidden']
                     for k in deps if k.startswith('contact_hidden:'))}
    hidden.discard(owner)
    manual_hidden = set(hidden)
    contact_messages, senders, small_recipients = defaultdict(list), set(), set()
    for mid, source in tables['message'].items():
        parts = source.get('participants',[])
        sender = mappings.get(source.get('from_identity_id'))
        if sender:
            senders.add(sender)
        recipients = [p for p in parts if p['role'] in ('to','cc')]
        if len(recipients)<=10:
            small_recipients.update(mappings[p['identity_id']] for p in recipients if p['identity_id'] in mappings)
        participants = {mappings[p['identity_id']] for p in parts if p['identity_id'] in mappings}
        if sender:
            participants.add(sender)
        for person in participants-{owner}:
            contact_messages[person].append((mid,source))
    for person, rows in contact_messages.items():
        latest = max(rows,key=lambda pair:(pair[1]['sent_at'],pair[0]))[1]
        named = any(identities[i].get('display_name') for i in aliases[person])
        if person.startswith('person:'):
            named = named or bool(people.get(person[7:],{}).get('primary_name'))
        stale_unknown = not named and (len(rows)==1 or (observed_at-timestamp(latest['sent_at'])).days>365)
        if (latest.get('is_automated') or stale_unknown or
            not any(r.get('body_text','').strip() for _,r in rows) or
            (person not in senders and person not in small_recipients)):
            hidden.add(person)
        node_deps[person].update('message:'+mid for mid,_ in rows)
    nodes, dependencies, claims, evidence, messages, profiles = {}, {}, [], {}, [], []

    def put(kind, row, deps):
        dependencies[kind+':'+row['id']] = tuple(sorted(set(deps)))
        return row

    for person, ids in sorted(aliases.items()):
        if person in hidden:
            continue
        canonical = people.get(person.removeprefix('person:'), {}) if person.startswith('person:') else {}
        name = canonical.get('preferred_name') or canonical.get('primary_name')
        name = name or next((identities[i].get('display_name') for i in ids if identities[i].get('display_name')), None)
        nodes[person] = put('node', {'id':person,'name':name or ('You' if person==owner else 'Unnamed contact'),
                                   'kind':'person','role':'Your network' if person==owner else '',
                                   'functions':[],'coverage':'Observed source records only'},
                            node_deps[person] | owner_deps)

    direct = defaultdict(list)
    for mid, source in sorted(tables['message'].items()):
        if source.get('is_automated') or not source.get('body_text','').strip():
            continue
        sender = mappings.get(source.get('from_identity_id'))
        parts = source.get('participants',[])
        refs = {p['identity_id'] for p in parts} | {source.get('from_identity_id')}
        mapped = {mappings[i] for i in refs if i in mappings}
        if not sender or mapped & manual_hidden or sender in hidden:
            continue
        thread = tables['thread'].get(source['thread_id'])
        if not thread:
            continue
        to = {mappings[p['identity_id']] for p in parts if p['role']=='to' and p['identity_id'] in mappings}
        nonself = mapped-{owner}
        is_direct = (not thread.get('is_group') and len(nonself)==1 and
                     ((sender==owner and bool(to & nonself)) or (sender!=owner and owner in to)) and
                     all(i in mappings for i in refs if i is not None))
        # Broadcast recipients are not made into pairwise person edges.
        contact = sender if sender!=owner else (next(iter(nonself)) if len(nonself)==1 else None)
        if contact is None or contact not in nodes:
            continue
        eid = 'message:'+mid
        deps = {eid,'thread:'+source['thread_id']} | owner_deps
        for entity in mapped:
            deps.update(node_deps[entity])
        at = source['sent_at']
        row = {'id':eid,'contact_id':contact,'channel':source['channel'],
               'direction':'out' if sender==owner else 'in','direct':is_direct,
               'at':at,'known_at':source['ingested_at'],'observed_at':source['ingested_at'],
               'text':source['body_text'],'author_id':sender,'participant_ids':sorted(mapped-hidden),
               'thread_id':source['thread_id'],'source_id':mid,'synthetic':False}
        messages.append(put('message',row,deps))
        evidence[eid] = put('evidence',{**row,'entity_ids':sorted(mapped-hidden)},deps)
        if is_direct:
            direct[contact].append(row)
    for contact, rows in sorted(direct.items()):
        eid = 'contact:'+contact
        deps = {k for row in rows for k in dependencies['message:'+row['id']]}
        claims.append(put('claim', {'id':eid,'source':owner,'target':contact,'relation':'In contact',
                                   'status':'confirmed','origin':'messages','scope':'ego_relative',
                                   'observed_at':min(r['known_at'] for r in rows),
                                   'valid_from':None,'valid_to':None,
                                   'evidence_ids':[r['id'] for r in rows]}, deps))

    org_by_name = {normalise_org_name(r['canonical_name']):'org:'+i for i,r in tables['organization'].items()}
    for iid, identity in sorted(identities.items()):
        person = mappings[iid]
        if person not in nodes or identity['channel']!='linkedin':
            continue
        connection = tables['linkedin_connection'].get(identity['handle'])
        if not connection:
            continue
        cid = identity['handle']
        eid = 'linkedin_connection:'+cid
        at = connection['synced_at']
        deps = node_deps[person] | {eid} | owner_deps
        company, title = (connection.get('company') or '').strip(), (connection.get('position') or '').strip()
        evidence[eid] = put('evidence', {'id':eid,'at':at,'known_at':at,'text':'; '.join(x for x in [company,title] if x),
                                        'channel':'linkedin','author_id':person,'entity_ids':[person],
                                        'origin':'LinkedIn connection export snapshot','synthetic':False,
                                        'source_id':cid}, deps)
        if company:
            normalized = normalise_org_name(company)
            org = org_by_name.get(normalized,'org:linkedin:'+fingerprint(normalized)[:24])
            orgdeps = {eid}
            if org.startswith('org:') and org[4:] in tables['organization']:
                orgdeps.add('organization:'+org[4:])
            existing_deps = set(dependencies.get('node:'+org,()))
            nodes[org] = put('node', {'id':org,'name':company,'kind':'organization'},existing_deps|orgdeps)
            claims.append(put('claim', {'id':'employment:'+iid,'source':person,'target':org,'relation':'Works at',
                                       'status':'confirmed','origin':'linkedin_connection','scope':'world',
                                       'observed_at':at,'valid_from':None,'valid_to':None,
                                       'time_precision':'snapshot_only','evidence_ids':[eid]}, deps|orgdeps))
        if title:
            profiles.append(put('profile', {'id':'title:'+iid,'person_id':person,'kind':'function',
                                            'label':title,'status':'confirmed','observed_at':at,
                                            'valid_from':None,'valid_to':None,'evidence_ids':[eid],
                                            'time_precision':'snapshot_only'},deps))
            nodes[person]['role'] = title
            nodes[person]['functions'] = sorted(set(nodes[person]['functions']+[title]))
            dependencies['node:'+person] = tuple(sorted(set(dependencies['node:'+person])|deps))

    # Message-backed reviewed source facts can supply additional affiliations. Old
    # accumulated LinkedIn facts are never treated as concurrent current employers.
    for fid, fact in sorted(tables['fact'].items()):
        person = mappings.get(fact.get('subject_identity_id'))
        eid = 'message:'+str(fact.get('source_message_id'))
        if fact.get('status')!='confirmed' or person not in nodes or eid not in evidence:
            continue
        deps = node_deps[person] | {'fact:'+fid} | set(dependencies['evidence:'+eid])
        if fact['fact_type']=='works_at' and fact.get('object_org_id') in tables['organization']:
            oid = fact['object_org_id']; org='org:'+oid
            deps.add('organization:'+oid)
            if org not in nodes:
                nodes[org] = put('node', {'id':org,'name':tables['organization'][oid]['canonical_name'],'kind':'organization'},deps)
            else:
                dependencies['node:'+org] = tuple(sorted(set(dependencies['node:'+org])|deps))
            claims.append(put('claim', {'id':'fact:'+fid,'source':person,'target':org,'relation':'Works at',
                                       'status':'confirmed','origin':'reviewed_source_fact','scope':'world',
                                       'observed_at':fact['reviewed_at'] or fact['extracted_at'],
                                       'valid_from':None,'valid_to':None,'evidence_ids':[eid],
                                       'time_precision':'unknown'},deps))
        elif fact['fact_type']=='has_title' and fact.get('object_text'):
            profiles.append(put('profile', {'id':'fact:'+fid,'person_id':person,'kind':'function',
                                            'label':fact['object_text'],'status':'confirmed',
                                            'observed_at':fact['reviewed_at'] or fact['extracted_at'],
                                            'valid_from':None,'valid_to':None,'evidence_ids':[eid]},deps))
    return Projection(tuple(nodes.values()),tuple(claims),tuple(evidence.values()),dependencies,
                      messages=tuple(messages),profiles=tuple(profiles),owner_id=owner)


def affected_entities(before: tuple[SourceRecord,...], after: tuple[SourceRecord,...]) -> set[str]:
    """Conservative canonical IDs for a delta; metadata may fan out through dependencies."""
    result = set()
    for r in (*before,*after):
        if r.kind=='person':
            result.add('person:'+r.id)
        elif r.kind=='identity':
            result.add('identity:'+r.id)
            if r.payload.get('person_id'):
                result.add('person:'+r.payload['person_id'])
        elif r.kind=='message':
            result.update('identity:'+p['identity_id'] for p in r.payload.get('participants',[]))
            if r.payload.get('from_identity_id'):
                result.add('identity:'+r.payload['from_identity_id'])
    return result
