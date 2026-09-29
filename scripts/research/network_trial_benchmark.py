"""Fictional real-adapter workload in an explicitly disposable local test DB."""
import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import statistics
import sys
import time
from uuid import uuid4

import psycopg

from adapters.network.source import SourceRepository
from adapters.network.store import PostgresNetworkStore
from adapters.network.worker import NetworkWorker
from adapters.network.index import IndexedRetrieval
from adapters.network.model import GraphQuery


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--messages',type=int,default=24222)
    parser.add_argument('--people',type=int,default=2000)
    parser.add_argument('--queries',type=int,default=10)
    parser.add_argument('--distribution',choices=('balanced','concentrated'),default='balanced')
    parser.add_argument('--group-size',type=int,default=1)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.people<=10000 or not 1<=args.messages<=100000 or not 2<=args.queries<=100 or not 1<=args.group_size<=min(10,args.people):
        parser.error('workload outside bounded benchmark limits')
    # Reuse the repo's strong loopback/disposable-name guard; never load app .env.
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
    from conftest import read_test_database_url, isolated_test_schema
    url=read_test_database_url()
    now=datetime.now(UTC)
    with psycopg.connect(url,autocommit=True) as guard:
        guard.execute('select pg_advisory_lock(741030)')
        if guard.execute("select to_regnamespace('network')").fetchone()[0]:
            raise RuntimeError('Existing test network schema: refusing to replace')
        try:
            with isolated_test_schema(url) as dsn:
                owner,self_id,thread=str(uuid4()),str(uuid4()),str(uuid4())
                people=[str(uuid4()) for _ in range(args.people)]
                with psycopg.connect(dsn) as conn:
                    conn.execute("insert into person(id,primary_name) values (%s,'Fictional Owner')",(owner,))
                    conn.execute("insert into identity(id,channel,handle,person_id,is_self) values (%s,'outlook','owner@example.test',%s,true)",(self_id,owner))
                    conn.execute("insert into thread(id,channel,external_id) values (%s,'outlook','benchmark')",(thread,))
                    with conn.cursor() as cur:
                        cur.executemany("insert into identity(id,channel,handle,display_name) values (%s,'outlook',%s,%s)",[(pid,f'contact-{i}@example.test',f'Fictional Contact {i:05}') for i,pid in enumerate(people)])
                        rows=[]; participants=[]
                        for i in range(args.messages):
                            mid=str(uuid4()); offset=0 if args.distribution=='concentrated' and i%5 else i%len(people); person=people[offset]
                            at=now-timedelta(minutes=args.messages-i)
                            body='Security testing experience.' if i%97==0 else 'Logistics project coordination update.'
                            rows.append((mid,thread,str(i),at,person,body,at))
                            participants.extend([(mid,self_id,'to'),(mid,person,'from')])
                            participants.extend((mid,people[(offset+j)%len(people)],'to') for j in range(1,args.group_size))
                        cur.executemany("insert into message(id,thread_id,channel,external_id,direction,sent_at,from_identity_id,body_text,raw,ingested_at) values (%s,%s,'outlook',%s,'inbound',%s,%s,%s,'{}',%s)",rows)
                        cur.executemany('insert into message_participant(message_id,identity_id,role) values (%s,%s,%s)',participants)
                source=SourceRepository(dsn)
                store=PostgresNetworkStore(dsn,source.audit()['binding'])
                store.initialize()
                start=time.perf_counter(); status=NetworkWorker(source,store).tick(now)
                backfill=time.perf_counter()-start
                if status.error_code:
                    raise RuntimeError(status.error_code)
                with psycopg.connect(dsn) as conn:
                    conn.execute('analyze network.item')
                    plan=conn.execute("explain (format json) select id from network.item where search_vector @@ plainto_tsquery('simple','security') order by id limit 30").fetchone()[0]
                    storage=conn.execute("select (select count(*) from network.dependency),pg_total_relation_size('network.dependency'),pg_total_relation_size('network.item')").fetchone()
                timings=[]; packs=[]
                query=GraphQuery(focus=store.worker_state()['owner_id'],as_of=now)
                for _ in range(args.queries):
                    start=time.perf_counter()
                    retrieval=IndexedRetrieval(store,query)
                    retrieval.seed('security testing')
                    result=retrieval.people(['security'])
                    pack=retrieval.pack([result],[{'id':'security','label':'Security','terms':['security']}])
                    if not pack['evidence']:
                        raise RuntimeError('benchmark_empty_evidence_pack: retrieval workload failed')
                    timings.append(time.perf_counter()-start)
                    packs.append(pack['budget']['bytes'])
                ordered=sorted(timings)
                report={'fictional':True,'messages':args.messages,'people':args.people,
                        'topology':'owner-centred messages, one shared thread, no inferred person clique',
                        'distribution':args.distribution,'participants_per_message':args.group_size+1,
                        'dependency_rows':storage[0],'dependency_bytes':storage[1],'item_bytes':storage[2],
                        'queries':args.queries,'initial_backfill_seconds':round(backfill,3),
                        'retrieval_first_seconds':round(timings[0],3),
                        'retrieval_p50_seconds':round(statistics.median(timings),3),
                        'retrieval_p95_seconds':round(ordered[min(len(ordered)-1,int(.95*len(ordered)))],3),
                        'max_pack_bytes':max(packs),'source_pack_limit_bytes':28000,
                        'query_plan':plan,'limitations':'Local isolated PostgreSQL; short fictional messages and one topology. Not hosted-source latency, live-model latency or a universal scalability claim.'}
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps({k:v for k,v in report.items() if k!='query_plan'},indent=2))
        finally:
            guard.execute('drop schema if exists network cascade')
            guard.execute('select pg_advisory_unlock(741030)')


if __name__=='__main__':
    main()
