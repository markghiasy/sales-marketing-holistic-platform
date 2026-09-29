"""Untrusted extraction proposals; only explicit review can activate them."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .profiles import Candidate
from .store import Snapshot, Projection


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class ProposedEntity(Strict):
    id: str=Field(pattern=r'^new:[a-zA-Z0-9_-]+$',max_length=100)
    kind: Literal['project','organization']
    name: str=Field(min_length=1,max_length=200)
    evidence_id: str=Field(min_length=1,max_length=250)
    quote: str=Field(min_length=1,max_length=3000)


class ProposedRelation(Strict):
    source_id: str=Field(min_length=1,max_length=160)
    target_id: str=Field(min_length=1,max_length=160)
    relation: Literal['Project member','Collaborates with','Introduced','Works at','Advises','Reports to','Client of']
    evidence_id: str=Field(min_length=1,max_length=250)
    quote: str=Field(min_length=1,max_length=3000)


class ProposalBatch(Strict):
    entities: list[ProposedEntity]=Field(default_factory=list,max_length=8)
    relations: list[ProposedRelation]=Field(default_factory=list,max_length=12)
    assertions: list[Candidate]=Field(default_factory=list,max_length=12)
    model: str=Field(default='',max_length=200)

    @model_validator(mode='after')
    def unique_entities(self):
        if len({e.id for e in self.entities})!=len(self.entities):
            raise ValueError('duplicate_entity')
        return self

    def references(self):
        ids={r.source_id for r in self.relations}|{r.target_id for r in self.relations}
        ids|={a.subject_id for a in self.assertions}|{a.context_id for a in self.assertions if a.context_id}
        evidence={r.evidence_id for r in [*self.entities,*self.relations,*self.assertions]}
        return ids,evidence


class ReviewCommand(Strict):
    proposal_id: str=Field(min_length=1,max_length=160)
    expected_version: int=Field(ge=1)
    decision: Literal['confirm','reject']
    entity_bindings: dict[str,str]=Field(default_factory=dict,max_length=8)


def validate_proposals(batch: ProposalBatch, snapshot: Snapshot) -> ProposalBatch:
    batch=ProposalBatch.model_validate(batch)
    nodes={n['id']:n for n in snapshot.data['nodes']}
    evidence={e['id']:e for e in snapshot.data['evidence']}
    nodes.update({e.id:{'id':e.id,'kind':e.kind,'name':e.name} for e in batch.entities})
    refs,source_ids=batch.references()
    if not refs<=nodes.keys():
        raise ValueError('unknown_entity')
    for row in [*batch.entities,*batch.relations,*batch.assertions]:
        source=evidence.get(row.evidence_id)
        if not source or not row.quote.strip() or row.quote not in source.get('text',''):
            raise ValueError('exact_quote_required')
        if source.get('author_id') not in nodes or nodes[source['author_id']]['kind']!='person':
            raise ValueError('unknown_claimant')
    for row in batch.relations:
        if nodes[row.source_id]['kind']!='person' or row.source_id==row.target_id:
            raise ValueError('invalid_relation_subject')
        target_kind=nodes[row.target_id]['kind']
        if row.relation=='Project member' and target_kind!='project':
            raise ValueError('invalid_project_binding')
        if row.relation=='Works at' and target_kind!='organization':
            raise ValueError('invalid_organization_binding')
        if row.relation in ('Collaborates with','Introduced','Reports to','Client of') and target_kind!='person':
            raise ValueError('invalid_person_binding')
    for row in batch.assertions:
        if row.basis=='self_declared' and nodes[row.subject_id]['kind']=='person' and row.subject_id!=evidence[row.evidence_id]['author_id']:
            raise ValueError('invalid_self_declaration')
    return batch


def project_proposal(proposal: dict, evidence: dict[str,dict]) -> Projection:
    batch=ProposalBatch.model_validate(proposal['payload']['batch'])
    bindings=proposal['payload']['bindings']
    at=proposal['payload']['reviewed_at']
    pid=proposal['id']
    deps=tuple(sorted({*proposal['dependencies'],'review:'+pid}))
    dependencies={}
    def item(kind,row):
        row['proposal_id']=pid
        dependencies[kind+':'+row['id']]=deps
        return row
    nodes=[]
    for entity in batch.entities:
        if bindings[entity.id].startswith(('project:proposal:','org:proposal:')):
            nodes.append(item('node',{'id':bindings[entity.id],'kind':entity.kind,'name':entity.name}))
    claims=[]
    for index,relation in enumerate(batch.relations):
        claims.append(item('claim',{'id':f'proposal:{pid}:relation:{index}',
            'source':bindings.get(relation.source_id,relation.source_id),
            'target':bindings.get(relation.target_id,relation.target_id),
            'relation':relation.relation,'status':'confirmed','origin':'reviewed_proposal','scope':'world',
            'observed_at':at,'valid_from':None,'valid_to':None,'evidence_ids':[relation.evidence_id],
            'quote':relation.quote,'claimant_id':evidence[relation.evidence_id]['author_id']}))
    assertions=[]
    for index,assertion in enumerate(batch.assertions):
        row=assertion.model_dump(mode='json',exclude={'evidence_id'},exclude_none=True)
        row.update(id=f'proposal:{pid}:profile:{index}',subject_id=bindings.get(assertion.subject_id,assertion.subject_id),
                   context_id=bindings.get(assertion.context_id,assertion.context_id),
                   claimant_id=evidence[assertion.evidence_id]['author_id'],evidence_ids=[assertion.evidence_id],
                   observed_at=at,reviewed_at=at,status='confirmed',synthetic=False,
                   origin='reviewed_model_proposal',model=batch.model)
        assertions.append(item('strategy',row))
    return Projection(tuple(nodes),tuple(claims),(),dependencies,strategies=tuple(assertions),affected_ids=())
