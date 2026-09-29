"""Durable proposal review; source corrections invalidate support, never erase audit."""
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from .changes import ProposalBatch, ReviewCommand, validate_proposals, project_proposal
from .source import SourceRepository, fingerprint
from .store import StoreError, Snapshot


class ReviewRepository:
    def __init__(self, store):
        self.store=store

    def _snapshot(self,conn,batch):
        ids,eids=batch.references()
        evidence=[r['payload'] for r in conn.execute("select payload from network.item where kind='evidence' and id=ANY(%s)",(list(eids),))]
        ids|={e['author_id'] for e in evidence if e.get('author_id')}
        nodes=[r['payload'] for r in conn.execute("select payload from network.item where kind='node' and id=ANY(%s)",(list(ids),))]
        state=self.store._state(conn)
        return Snapshot(state['version'],{'nodes':nodes,'evidence':evidence,'owner_id':state['owner_id']},{})

    def _valid(self,conn,deps,*,real_source=True):
        actual=self.store._dependency_values(conn,list(deps))
        if any(actual.get(k,'absent')!=v for k,v in deps.items()):
            return False
        if real_source:
            return SourceRepository(self.store._dsn,expected_binding=self.store.binding,database=self.store.database).validate({k:v for k,v in deps.items() if not k.startswith('review:')})
        return True

    def propose(self,batch,dependencies):
        batch=ProposalBatch.model_validate(batch)
        if not batch.entities and not batch.relations and not batch.assertions:
            return {'id':None,'version':self.store.status().version,'added':0}
        with self.store.connection() as conn:
            state=self.store._state(conn,lock=True)
            snapshot=self._snapshot(conn,batch)
            validate_proposals(batch,snapshot)
            # Derive required dependencies from persisted items, not merely the caller.
            refs,eids=batch.references()
            keys=['node:'+i for i in refs if not i.startswith('new:')]+['evidence:'+e for e in eids]
            required={r['source_key']:r['fingerprint'] for r in conn.execute("select source_key,fingerprint from network.dependency where item_kind||':'||item_id=ANY(%s)",(keys,))}
            deps={**dependencies,**required}
            if any(dependencies.get(k)!=v for k,v in required.items()) or not self._valid(conn,deps):
                raise StoreError('source_changed')
            digest=fingerprint([batch.model_dump(mode='json',exclude={'model'}),deps])
            pid='proposal:'+digest[:32]
            added=conn.execute('insert into network.proposal(id,fingerprint,payload,dependencies) values (%s,%s,%s,%s) on conflict(fingerprint) do nothing',
                               (pid,digest,Jsonb({'batch':batch.model_dump(mode='json')}),Jsonb(deps))).rowcount
            version=state['version']+int(bool(added))
            conn.execute('update network.state set version=%s',(version,))
            return {'id':pid,'version':version,'added':int(bool(added))}

    def review(self,command):
        command=ReviewCommand.model_validate(command)
        with self.store.connection() as conn:
            state=self.store._state(conn,lock=True)
            if state['version']!=command.expected_version:
                raise StoreError('version_conflict')
            row=conn.execute('select * from network.proposal where id=%s for update',(command.proposal_id,)).fetchone()
            if row is None:
                raise KeyError(command.proposal_id)
            at=datetime.now(UTC).isoformat()
            payload=dict(row['payload'])
            if command.decision=='confirm':
                if not self._valid(conn,row['dependencies']):
                    raise StoreError('source_changed')
                batch=ProposalBatch.model_validate(payload['batch'])
                snapshot=self._snapshot(conn,batch)
                validate_proposals(batch,snapshot)
                bindings={}
                if set(command.entity_bindings)!={e.id for e in batch.entities}:
                    raise ValueError('entity_binding_required')
                for entity in batch.entities:
                    choice=command.entity_bindings[entity.id]
                    if choice=='create':
                        prefix='project' if entity.kind=='project' else 'org'
                        bindings[entity.id]=prefix+':proposal:'+fingerprint([row['id'],entity.id])[:28]
                    else:
                        target=conn.execute("select payload from network.item where kind='node' and id=%s",(choice,)).fetchone()
                        if not target or target['payload']['kind']!=entity.kind:
                            raise ValueError('invalid_entity_binding')
                        bindings[entity.id]=choice
                payload['bindings']=bindings
            payload['reviewed_at']=at
            status='confirmed' if command.decision=='confirm' else 'rejected'
            conn.execute('update network.proposal set status=%s,payload=%s where id=%s',(status,Jsonb(payload),row['id']))
            conn.execute('insert into network.review_event(proposal_id,decision,payload) values (%s,%s,%s)',
                         (row['id'],command.decision,Jsonb({'bindings':payload.get('bindings',{}),'source_dependencies':row['dependencies']})))
            # Includes dependent reviewed items, so rejecting a prerequisite never
            # leaves an apparently supported downstream relation visible.
            conn.execute('delete from network.item i using network.dependency d where i.kind=d.item_kind and i.id=d.item_id and d.source_key=%s',('review:'+row['id'],))
            if status=='confirmed':
                updated={**row,'status':status,'payload':payload}
                sources={e['id']:e for e in snapshot.data['evidence']}
                self.store._project(conn,project_proposal(updated,sources))
            version=state['version']+1
            conn.execute('update network.state set version=%s',(version,))
            return {'version':version,'as_of':at,'id':row['id'],'status':status}

    def list(self,focus=None,limit=100):
        if not 1<=limit<=100:
            raise ValueError('proposal_limit')
        with self.store.connection(read_only=True) as conn:
            self.store._state(conn)
            return tuple(conn.execute("select id,payload,status from network.proposal where %s::text is null or jsonb_path_exists(payload,'$.batch.** ? (@ == $focus)',jsonb_build_object('focus',%s::text)) order by created_at desc,id limit %s",(focus,focus,limit)))

    def restore_active(self,conn):
        # Base source projection may replace derived items. Reapply only proposals
        # whose ORIGINAL source and prerequisite review versions remain eligible.
        for row in conn.execute("select * from network.proposal where status='confirmed' order by created_at,id").fetchall():
            if not self._valid(conn,row['dependencies'],real_source=False):
                continue
            batch=ProposalBatch.model_validate(row['payload']['batch'])
            snapshot=self._snapshot(conn,batch)
            try:
                validate_proposals(batch,snapshot)
            except ValueError:
                continue
            self.store._project(conn,project_proposal(row,{e['id']:e for e in snapshot.data['evidence']}))
