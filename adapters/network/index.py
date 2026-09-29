"""Indexed candidate selection before bounded evidence materialization."""
from __future__ import annotations

from copy import deepcopy
import re

from .model import timestamp
from .retrieval import NetworkRetrieval, tokens


class IndexedRetrieval:
    def __init__(self,store,query,*,entity_limit=30):
        if not 2<=entity_limit<=100:
            raise ValueError('entity_limit')
        self.store,self.query,self.entity_limit=store,query,entity_limit
        self.data={}
        self.dependencies={}
        self.selected=[]
        self.source_ids=[]
        self.inner=None
        self.version=0
        self.truncated=False
        self.terms=[]

    def _hits(self,terms):
        self.terms=[t for t in terms[:24] if t.strip()]
        clean=[' '.join(sorted(tokens(term))) for term in terms[:24]]
        clean=[term for term in clean if term]
        if not clean:
            return [],[]
        with self.store.connection(read_only=True) as conn:
            state=self.store._state(conn)
            # PostgreSQL quotes the lexemes via plainto_tsquery. Only values,
            # never SQL fragments, come from the user's text.
            query="""with q as (
              select to_tsquery('simple',string_agg('('||plainto_tsquery('simple',term)::text||')',' | ')) as query
              from unnest(%s::text[]) term
            ) select i.kind,i.id,i.entity_ids,i.payload->'evidence_ids' as evidence_ids,
                     ts_rank_cd(i.search_vector,q.query) as score
              from network.item i cross join q
              where i.search_vector @@ q.query
                and coalesce(i.payload->>'status','confirmed')='confirmed'
                and coalesce((i.payload->>'observed_at')::timestamptz,(i.payload->>'known_at')::timestamptz,(i.payload->>'at')::timestamptz,'-infinity')<=%s
              order by score desc,i.kind,i.id limit %s"""
            rows=conn.execute(query,(clean,self.query.as_of,self.entity_limit*4+1)).fetchall()
            self.truncated=self.truncated or len(rows)>self.entity_limit*4
            rows=rows[:self.entity_limit*4]
            ids=list(dict.fromkeys(e for row in rows for e in row['entity_ids'] if e!=state['owner_id']))
            refs=list(dict.fromkeys(e for row in rows for e in ([row['id']] if row['kind'] in ('message','evidence') else (row['evidence_ids'] or []))))
            # Explicitly bounded name-only fallback for partial/non-Latin names.
            # This is not advertised as multilingual semantic retrieval.
            if not ids:
                names=conn.execute("select id from network.item where kind='node' and exists(select 1 from unnest(%s::text[]) term where position(lower(term) in lower(payload->>'name'))>0) order by payload->>'name',id limit %s",(terms[:24],self.entity_limit)).fetchall()
                ids=[r['id'] for r in names]
            self.truncated=self.truncated or len(ids)>self.entity_limit-1 or len(refs)>200
            return ids[:self.entity_limit-1],refs[:200]

    def _refresh(self,ids=(),refs=()):
        selected=list(dict.fromkeys([*self.selected,*ids]))
        source_ids=list(dict.fromkeys([*self.source_ids,*refs]))
        self.truncated=self.truncated or len(selected)>self.entity_limit-1 or len(source_ids)>200
        self.selected=selected[:self.entity_limit-1]
        self.source_ids=source_ids[:200]
        snapshot=self.store.capture(tuple(self.selected),self.entity_limit,evidence_ids=tuple(self.source_ids),as_of=self.query.as_of)
        data=deepcopy(snapshot.data)
        now=self.query.as_of
        def known(row):
            return all(timestamp(row[k])<=now for k in ('at','known_at','observed_at') if row.get(k))
        data['evidence']=[e for e in data['evidence'] if known(e)]
        data['messages']=[m for m in data['messages'] if known(m)]
        available={e['id'] for e in data['evidence']}
        claims=[]
        for c in data['claims']:
            refs=[e for e in c['evidence_ids'] if e in available]
            if not refs:
                continue
            if c['relation']=='In contact':
                # An active contact may have thousands of messages. One giant
                # evidence bundle would never fit the answer budget.
                claims.extend({**c,'id':c['id']+':source:'+e,'evidence_ids':[e]} for e in refs)
            else:
                claims.append({**c,'evidence_ids':refs})
        data['claims']=claims
        for evidence in data['evidence']:
            original=evidence['text']
            if len(original)>4000:
                positions=[original.casefold().find(t.casefold()) for t in self.terms]
                positions=[p for p in positions if p>=0]
                start=max(0,min(positions)-1000) if positions else 0
                end=min(len(original),start+4000)
                evidence.update(text=original[start:end],text_truncated=True,source_text_length=len(original),excerpt_start=start,excerpt_end=end)
        self.data.clear(); self.data.update(data)
        if any(k in self.dependencies and self.dependencies[k]!=v for k,v in snapshot.dependencies.items()):
            raise RuntimeError('source_changed')
        self.dependencies={**self.dependencies,**snapshot.dependencies}
        self.version=snapshot.version
        self.inner=NetworkRetrieval(self.data,self.query)
        represented={eid for unit in self.inner.records.values() for eid in unit['evidence_ids']}
        for evidence in data['evidence']:
            author=evidence.get('author_id')
            if evidence['id'] in represented or author not in self.inner.nodes or not evidence['id'].startswith('message:'):
                continue
            # Group participation is not a person-to-person relationship. Its
            # authored text can still be retrieved as an unverified observation.
            self.inner._add('observation',{'id':evidence['id'],'evidence_ids':[evidence['id']],
                'subject_id':author,'claimant_id':author,'observed_at':evidence.get('known_at',evidence['at']),
                'basis':'reported','status':'observed'},[author],
                'Authored source passage; not verified capability or relationship')
        self.truncated=self.truncated or data.get('truncated',False)

    def seed(self,text):
        stop={'i','a','an','the','to','for','with','and','or','who','can','help','me','my','want','need','is','are','we'}
        ids,refs=self._hits([t for t in re.findall(r'[^\W_]+',text) if t.casefold() not in stop][:24])
        ids=ids[:min(12,self.entity_limit-1)]
        focus=self.query.focus
        if focus!=self.store.worker_state()['owner_id']:
            ids=[focus,*ids]
        self._refresh(ids,refs)
        return self.data

    @property
    def records(self):
        return self.inner.records if self.inner else {}

    def people(self,terms):
        ids,refs=self._hits(terms)
        self._refresh(ids,refs)
        result=self.inner.people(terms)
        # Name substrings are name matches only, never capability claims.
        found={p['id'] for p in result['people']}
        for key in ids:
            n=self.inner.nodes.get(key)
            matched=[t for t in terms if n and t.casefold() in n['name'].casefold()]
            if n and n['kind']=='person' and key not in found and matched:
                units=list(self.inner.by_entity[key])
                result['people'].append({'id':key,'name':n['name'],'matched_terms':matched,
                                        'missing_terms':[t for t in terms if t not in matched],
                                        'unit_ids':units,'score':len(matched)})
                result['unit_ids']=list(dict.fromkeys([*result['unit_ids'],*units]))
        result.update(truncated=self.truncated,total_matches=None,candidate_count=len(result['people']))
        return result

    def context(self,entity_id):
        self._refresh([entity_id])
        result=self.inner.context(entity_id)
        result['truncated']=self.truncated
        return result

    def neighborhood(self,entity_id,depth):
        if not 1<=depth<=3:
            raise ValueError('depth')
        visited={entity_id}
        frontier=[entity_id]
        with self.store.connection(read_only=True) as conn:
            self.store._state(conn)
            for _ in range(depth):
                rows=conn.execute("select entity_ids from network.item where kind='claim' and entity_ids && %s and payload->>'status'='confirmed' order by id limit %s",(frontier,self.entity_limit*4+1)).fetchall()
                self.truncated=self.truncated or len(rows)>self.entity_limit*4
                other=list(dict.fromkeys(e for row in rows[:self.entity_limit*4] for e in row['entity_ids'] if e not in visited))
                remaining=self.entity_limit-len(visited)
                self.truncated=self.truncated or len(other)>remaining
                frontier=other[:max(0,remaining)]
                visited.update(frontier)
                if not frontier:
                    break
        self._refresh([entity_id,*sorted(visited-{entity_id})])
        result=self.inner.neighborhood(entity_id,depth)
        result['truncated']=self.truncated
        return result

    def pack(self,results,requirements,max_bytes=28000):
        available=set(self.inner.records)
        valid=[]
        for result in results:
            valid.append({**result,'unit_ids':[i for i in result.get('unit_ids',[]) if i in available],
                          'paths':[p for p in result.get('paths',[]) if set(p['unit_ids'])<=available]})
        pack=self.inner.pack(valid,requirements,max_bytes)
        if self.truncated:
            for requirement in pack['coverage']:
                if requirement['status']=='searched_no_match':
                    requirement['status']='budget_omitted'
        pack['scope'].update(data_source='real',truncated=self.truncated,
                             note='Bounded retrieval over observed source records. Matching text is not verified capability; omitted records remain unknown.')
        return pack
