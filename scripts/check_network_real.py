"""Read-only loopback acceptance checks. Reports counts/timings, never source content."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import quote, urlsplit

import requests


def check(base_url):
    url=urlsplit(base_url)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password:
        raise ValueError('loopback_http_required')
    base_url=base_url.rstrip('/')
    timings={}
    def get(path,key=None):
        start=perf_counter()
        response=requests.get(base_url+path,timeout=60)
        if key:
            timings[key]=round(perf_counter()-start,3)
        response.raise_for_status()
        return response
    health=get('/network/health.json','health').json()
    if health.get('data_source')!='real':
        raise ValueError('real_source_required')
    graph=get('/network/graph.json','graph').json()
    if graph.get('backend')!='postgresql' or graph.get('owner_id') not in {n['id'] for n in graph['nodes']}:
        raise ValueError('graph_binding_invalid')
    if len(graph['nodes'])>50 or len(graph['edges'])>100:
        raise ValueError('unbounded_graph')
    conversations=get('/inbox/conversations.json?limit=10','contacts').json()
    for path in ('/inbox','/network','/static/network/client.js','/static/network/profiles.js','/static/vendor/cytoscape.min.js'):
        get(path)
    citations=0
    for eid in list(dict.fromkeys(e for c in graph['edges'] for e in c['evidence_ids']))[:2]:
        evidence=get('/network/evidence/'+quote(eid,safe='')+'.json?version='+str(graph['version']),'citation_'+str(citations+1)).json()
        if evidence.get('id')!=eid or evidence.get('data_source')!='real':
            raise ValueError('citation_binding_invalid')
        citations+=1
    if conversations:
        person=conversations[0]
        get('/inbox/conversation/'+quote(person['person_key'],safe='')+'.json','conversation')
        search=get('/network/search.json?q='+quote(person['name'],safe=''),'name_search').json()
        if search.get('data_source')!='real':
            raise ValueError('search_source_invalid')
    agent=get('/network/agent/status.json').json()
    if agent.get('data_source')!='real':
        raise ValueError('agent_source_invalid')
    return {'checked_at':datetime.now(UTC).isoformat(),'read_only':True,'health':health,
            'nodes_in_view':len(graph['nodes']),'edges_in_view':len(graph['edges']),
            'contacts_sampled':len(conversations),'citations_verified':citations,
            'graph_truncated':graph['truncated'],'agent_configured':agent['configured'],
            'model':agent['model'],'timings_seconds':timings,
            'ready':not health.get('error_code') and not health.get('stale'),
            'limitations':'One bounded view and up to two citations; no model call or source mutation. Mac execution and complete-source correctness require separate evidence.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        result=check(args.base_url)
    except Exception:  # noqa: BLE001 - sanitize configuration/DB failures at the CLI boundary.
        # Requests/DB errors may include URLs or content; never print their text.
        parser.exit(2,'network_check_failed: inspect local app health and retry\n')
    body=json.dumps(result,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(body+'\n',encoding='utf-8')
    print(body)
    if not result['ready']:
        parser.exit(2)


if __name__=='__main__':
    main()
