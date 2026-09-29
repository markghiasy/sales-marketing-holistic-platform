"""Real network boundary: bounded retrieval and validation of actual source dependencies."""
from dataclasses import asdict
from datetime import UTC, datetime

from .context import entity_context
from .index import IndexedRetrieval
from .model import GraphQuery, timestamp
from .profiles import profile_context
from .projection import build_snapshot
from .search import contact_tags, search_contacts
from .store import Snapshot, StoreError


class NetworkService:
    def __init__(self,store,source):
        self.store,self.source=store,source
        self.owner_id=store.worker_state()['owner_id']

    def query(self,values=None):
        args=dict(values or {})
        if not args.get('focus') or args['focus']=='person:owner':
            args['focus']=self.store.worker_state()['owner_id']
        if not args.get('as_of'):
            args['as_of']=datetime.now(UTC).isoformat()
        return GraphQuery(**args)

    def snapshot(self,query,limit=100):
        ids=[query.focus]
        if query.expand:
            retriever=IndexedRetrieval(self.store,query,entity_limit=min(limit,100))
            retriever.neighborhood(query.expand,2)
            return Snapshot(retriever.version,retriever.data,retriever.dependencies)
        terms=f'{query.search} {query.function}'.strip()
        if terms:
            retriever=IndexedRetrieval(self.store,query,entity_limit=min(limit,100))
            ids.extend(retriever._hits([terms])[0])
        for context in (query.organization,query.project):
            if context:
                with self.store.connection(read_only=True) as conn:
                    rows=conn.execute("select entity_ids from network.item where kind='claim' and entity_ids @> %s and payload->>'status'='confirmed' order by id limit %s",([context],limit)).fetchall()
                ids.extend(i for row in rows for i in row['entity_ids'])
        return self._dated(self.store.capture(tuple(ids),limit,as_of=query.as_of),query)

    def _dated(self,snapshot,query):
        data=snapshot.data
        def known(row):
            return all(timestamp(row[k])<=query.as_of for k in ('at','known_at','observed_at') if row.get(k))
        for section in ('evidence','messages','strategic_assertions','work_records'):
            data[section]=[r for r in data.get(section,[]) if known(r)]
        available={e['id'] for e in data['evidence']}
        data['claims']=[{**r,'evidence_ids':[i for i in r['evidence_ids'] if i in available]} for r in data['claims'] if known(r) and any(i in available for i in r['evidence_ids'])]
        return snapshot

    def validate(self,dependencies):
        return self.store.dependencies_current(dependencies) and self.source.validate({k:v for k,v in dependencies.items() if not k.startswith('review:')})

    def graph(self,query,limit=100):
        snapshot=self.snapshot(query,limit)
        result=build_snapshot(snapshot.data,query,snapshot.version)
        result.update(data_source='real',backend='postgresql',truncated=result['truncated'] or snapshot.data.get('truncated',False),freshness=self.health(),coverage='Bounded source-backed view. Activity counts describe the loaded message slice, not complete communication history or delivery performance.')
        for person in result['ranked_contacts']:
            person['history']['coverage']='Loaded message slice only; incomplete history'
        return result

    def evidence(self,evidence_id,query,version=None):
        with self.store.connection(read_only=True) as conn:
            state=self.store._state(conn)
            if version is not None and version!=state['version']:
                raise StoreError('version_conflict')
            row=conn.execute("select payload,entity_ids from network.item where kind='evidence' and id=%s",(evidence_id,)).fetchone()
            if row is None or any(timestamp(row['payload'][k])>query.as_of for k in ('at','known_at','observed_at') if row['payload'].get(k)):
                raise KeyError(evidence_id)
            deps={r['source_key']:r['fingerprint'] for r in conn.execute("select source_key,fingerprint from network.dependency where (item_kind='evidence' and item_id=%s) or (item_kind='node' and item_id=ANY(%s))",(evidence_id,row['entity_ids']))}
        if not self.validate(deps):
            raise StoreError('source_changed')
        return {**row['payload'],'version':state['version'],'data_source':'real'}

    def context(self,query,profile=False):
        snapshot=self.snapshot(query)
        result=(profile_context if profile else entity_context)(snapshot.data,query)
        result.update(version=snapshot.version,data_source='real',truncated=snapshot.data['truncated'],coverage='Observed records in a bounded slice. Unrecorded capabilities and project delivery remain unknown. Current source identities are used; historical identity revisions are not reconstructed.')
        if profile:
            result['source_choices']=[{k:e.get(k) for k in ('id','text','channel','at','author_id')} for e in snapshot.data['evidence'] if query.focus in e.get('participant_ids',[]) or e.get('author_id')==query.focus][:24]
            result['proposals']=[{k:p[k] for k in ('id','payload','status')} for p in self.store.proposals(focus=query.focus)]
        return result

    def _contact(self,node,data,query):
        messages=[m for m in data['messages'] if m.get('contact_id')==node['id']]
        latest=max(messages,key=lambda m:m['at'],default={})
        return {'person_key':node['id'],'name':node['name'],'channel':latest.get('channel',''),
                'last_message_at':latest.get('at'),'summary':node.get('role',''),'topic':'',
                'tags':contact_tags(data,query).get(node['id'],[]),'urgency':0,'unread':False,'unanswered':False,'has_draft':False}

    def conversations(self,query,limit=100,after=''):
        if not 1<=limit<=100:
            raise ValueError('page_limit')
        with self.store.connection(read_only=True) as conn:
            state=self.store._state(conn)
            ids=[r['id'] for r in conn.execute("select id from network.item where kind='node' and payload->>'kind'='person' and id<>%s and id>%s order by id limit %s",(state['owner_id'],after,limit+1))]
        more=len(ids)>limit
        ids=ids[:limit]
        if not ids:
            return [],None
        snapshot=self._dated(self.store.capture(tuple(ids),min(1000,len(ids)+15),as_of=query.as_of),query)
        nodes={n['id']:n for n in snapshot.data['nodes']}
        return [self._contact(nodes[i],snapshot.data,query) for i in ids if i in nodes],ids[-1] if more else None

    def conversation(self,person,query):
        snapshot=self._dated(self.store.capture((person,),30,as_of=query.as_of),query)
        node=next((n for n in snapshot.data['nodes'] if n['id']==person and n['kind']=='person'),None)
        if not node:
            raise KeyError(person)
        messages=[{'id':m['id'],'channel':m['channel'],'subject':m.get('subject',''),
                   'sender':'you' if m['direction']=='out' else 'them','text':m['text'],'sent_at':m['at'],
                   'to':[],'cc':[],'from_name':'You' if m['direction']=='out' else node['name']}
                  for m in snapshot.data['messages'] if m.get('contact_id')==person]
        return {**self._contact(node,snapshot.data,query),'messages':sorted(messages,key=lambda m:m['sent_at']),
                'context':['Source-backed conversation slice. Open the network to inspect relationships and reviewed assertions.'],
                'graph':{'people':[]},'data_source':'real','version':snapshot.version,'truncated':snapshot.data['truncated']}

    def search(self,query,text,limit=30):
        retriever=IndexedRetrieval(self.store,query,entity_limit=min(100,max(2,limit)))
        data=retriever.seed(text)
        result=search_contacts(data,query,text,retriever.version)
        result.update(data_source='real',truncated=retriever.truncated)
        return result

    def answer(self,request,agent):
        query=self.query(request.model_dump())
        request=request.model_copy(update={'focus':query.focus,'as_of':query.as_of.isoformat()})
        retriever=IndexedRetrieval(self.store,query,entity_limit=30)
        data=retriever.seed(request.question)
        result=agent.answer(data,request,retriever.version,retriever=retriever,
                            validate_sources=lambda:self.validate(retriever.dependencies))
        result['version']=retriever.version
        result['freshness']=self.health()
        return result

    def health(self):
        result=asdict(self.store.status())
        checked=result['source_checked_at']
        result['stale']=checked is None or (datetime.now(UTC)-checked).total_seconds()>180
        return {k:v.isoformat() if isinstance(v,datetime) else v for k,v in result.items()} | {'data_source':'real'}
