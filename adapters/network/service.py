"""Real network boundary: bounded retrieval and validation of actual source dependencies."""
from datetime import UTC, datetime
from dataclasses import asdict

from .index import IndexedRetrieval
from .model import GraphQuery
from .projection import build_snapshot
from .search import search_contacts


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
        return self.store.capture((query.focus,),limit)

    def validate(self,dependencies):
        return self.store.dependencies_current(dependencies) and self.source.validate({k:v for k,v in dependencies.items() if not k.startswith('review:')})

    def graph(self,query,limit=100):
        snapshot=self.snapshot(query,limit)
        result=build_snapshot(snapshot.data,query,snapshot.version)
        result.update(data_source='real',truncated=snapshot.data.get('truncated',False),freshness=self.health())
        return result

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
        return {k:v.isoformat() if isinstance(v,datetime) else v for k,v in result.items()} | {'data_source':'real'}
