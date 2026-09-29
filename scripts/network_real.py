"""Explicit real-data, loopback-only network trial; no demo fallback or source writes."""
import argparse
import atexit
from datetime import UTC, datetime
import json
from pathlib import Path

from dotenv import dotenv_values
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from pydantic import Field, ValidationError

from adapters.network.agent import AgentRequest, AgentUnavailable, ClaudeProvider, NetworkAgent, StrictModel
from adapters.network.changes import ReviewCommand
from adapters.network.service import NetworkService
from adapters.network.database import NetworkDatabase
from adapters.network.source import SourceRepository
from adapters.network.store import PostgresNetworkStore, StoreError


class SelectedExtraction(StrictModel):
    focus: str
    evidence_ids: list[str] = Field(min_length=1,max_length=12)
    as_of: str = ''
    mode: str = 'current'


def create_app(*,service:NetworkService,llm_config=None,agent_provider=None,testing=False):
    root=Path(__file__).resolve().parent/'onboarding'
    app=Flask(__name__,template_folder=str(root/'templates'),static_folder=str(root/'static'))
    app.testing=testing
    app.config.update(MAX_CONTENT_LENGTH=150000,TRUSTED_HOSTS=['localhost','127.0.0.1'])
    provider=agent_provider or ClaudeProvider(llm_config)
    if testing and agent_provider is None:
        provider.key=''
    agent=NetworkAgent(provider)
    app.extensions.update(network_store=service.store,network_service=service,network_agent=agent)

    def query():
        return service.query(request.args.to_dict())

    @app.before_request
    def protect():
        if request.method=='POST' and request.endpoint is not None:
            if request.headers.get('Origin') and request.headers['Origin'].rstrip('/')!=request.host_url.rstrip('/'):
                return jsonify(error='Cross-origin changes are not allowed.'),403
            if not request.is_json:
                return jsonify(error='Send a JSON request.'),415

    @app.errorhandler(ValidationError)
    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error='Invalid request. Check the selected context, date and sources.'),400

    @app.errorhandler(KeyError)
    def missing(error):
        return jsonify(error='Source or context not available in this view.'),404

    @app.errorhandler(StoreError)
    def changed(error):
        return jsonify(error='This source or review changed. Refresh the view and retry.'),409

    @app.errorhandler(AgentUnavailable)
    def unavailable(error):
        return jsonify(error=str(error)),503

    @app.errorhandler(Exception)
    def failed(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException):
            return error
        if isinstance(error,RuntimeError) and str(error)=='source_changed':
            return changed(error)
        return jsonify(error='Network request failed. Check local worker health and retry; source data was not changed.'),502

    def template(name,**kwargs):
        return render_template(name,network_demo=True,network_real=True,
                               network_config={'real':True,'owner_id':service.owner_id,'as_of':datetime.now(UTC).isoformat()},**kwargs)

    @app.get('/')
    @app.get('/network')
    def explorer():
        return template('network.html',return_url='/inbox',has_origin=bool(request.args.get('origin')))

    @app.get('/inbox')
    def inbox():
        return template('inbox.html')

    @app.get('/network/health.json')
    def health():
        return jsonify(service.health())

    @app.get('/network/graph.json')
    def graph():
        return jsonify(service.graph(query()))

    @app.get('/network/evidence/<evidence_id>.json')
    def evidence(evidence_id):
        version=int(request.args['version']) if request.args.get('version') else None
        return jsonify(service.evidence(evidence_id,query(),version))

    @app.get('/network/search.json')
    def search():
        text=request.args.get('q','').strip()
        if not 1<=len(text)<=2000:
            raise ValueError('query_length')
        return jsonify(service.search(query(),text))

    @app.get('/network/context.json')
    def context():
        return jsonify(service.context(query()))

    @app.get('/network/profile.json')
    def profile():
        return jsonify(service.context(query(),profile=True))

    @app.post('/network/profile/extract')
    def extract():
        payload=SelectedExtraction.model_validate(request.get_json())
        q=service.query(payload.model_dump(exclude={'evidence_ids'}))
        snapshot=service.snapshot(q)
        batch,usage=agent.extract_network(snapshot,q,payload.evidence_ids,validate_sources=lambda:service.validate(snapshot.dependencies))
        result=service.store.propose(batch,snapshot.dependencies)
        return jsonify(**result,usage=usage,model=provider.model)

    @app.post('/network/profile/review')
    def review():
        return jsonify(service.store.review(ReviewCommand.model_validate(request.get_json())))

    @app.get('/network/agent/status.json')
    def agent_status():
        return jsonify(configured=provider.available,model=provider.model if provider.available else None,remaining=agent.remaining,data_source='real')

    @app.post('/network/agent.json')
    def ask():
        values=request.get_json()
        values.setdefault('as_of',datetime.now(UTC).isoformat())
        values.setdefault('focus',service.owner_id)
        payload=AgentRequest.model_validate(values)
        if not payload.question.strip():
            raise ValueError('empty_question')
        return jsonify(service.answer(payload,agent))

    @app.get('/inbox/conversations.json')
    def conversations():
        rows,after=service.conversations(query(),int(request.args.get('limit',100)),request.args.get('after',''))
        response=jsonify(rows)
        if after:
            response.headers['X-Next-Cursor']=after
        return response

    @app.get('/inbox/conversation/<person_key>.json')
    def conversation(person_key):
        return jsonify(service.conversation(person_key,query()))

    @app.get('/network/events')
    @app.get('/inbox/events')
    def events():
        def generate():
            version=service.store.status().version
            while True:
                yield 'event: update\ndata: '+json.dumps({'version':version})+'\n\n'
                yield 'event: health\ndata: '+json.dumps(service.health())+'\n\n'
                version=service.store.wait_for_version(version,15)
        return Response(stream_with_context(generate()),mimetype='text/event-stream',headers={'Cache-Control':'no-cache'})

    return app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',required=True,type=Path)
    parser.add_argument('--port',type=int,default=5057)
    args=parser.parse_args()
    config=dotenv_values(args.env_file)
    if not config.get('DATABASE_URL'):
        parser.exit(2,'missing_database_url\n')
    try:
        database=NetworkDatabase(config['DATABASE_URL'])
        atexit.register(database.close)
        source=SourceRepository(config['DATABASE_URL'],database=database)
        store=PostgresNetworkStore(config['DATABASE_URL'],source.audit()['binding'],database=database)
        service=NetworkService(store,source)
    except Exception:
        parser.exit(2,'network_not_ready: audit source and explicitly initialize derived schema first\n')
    create_app(service=service,llm_config=config).run(host='127.0.0.1',port=args.port,debug=False,threaded=True,use_reloader=False)


if __name__=='__main__':
    main()
