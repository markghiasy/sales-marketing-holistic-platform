"""Shared local Strategy endpoints; copied inputs outlive Flask request contexts."""
import json
import secrets
import threading
import time
from datetime import UTC, datetime

from flask import Response, jsonify, render_template, request, stream_with_context
from pydantic import ValidationError

from adapters.network.agent import AgentRequest
from adapters.network.model import GraphQuery
from adapters.network.strategy_jobs import EVIDENCE_EVENTS, TERMINAL, StrategyJobs


def register_strategy_routes(app, agent, *, service=None, store=None):
    jobs = StrategyJobs()
    app.extensions['strategy_jobs'] = jobs
    drafts = {}
    draft_lock = threading.Lock()

    @app.before_request
    def protect_strategy():
        if not request.path.startswith('/network/strategy/'):
            return None
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                return jsonify(error='Cross-origin requests are not allowed.'), 403
            if not request.is_json:
                return jsonify(error='Send a JSON request.'), 415
        return None

    @app.after_request
    def private_strategy(response):
        if request.path.startswith('/network/strategy/') or request.path == '/strategy':
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.get('/strategy')
    def strategy_workspace():
        config = {'real': bool(service), 'owner_id': service.owner_id if service else 'person:owner',
                  'as_of': datetime.now(UTC).isoformat() if service else '2026-09-27T12:00:00Z'}
        return render_template('strategy.html', network_demo=True, network_real=bool(service),
                               network_config=config, return_url='/network')

    def json_object():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise TypeError('invalid_json_object')
        return value

    @app.post('/network/strategy/drafts')
    def save_draft():
        try:
            question = json_object().get('question')
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
                raise ValueError('invalid_question')
        except (TypeError, ValueError):
            return jsonify(error='Enter a goal of 1–2000 characters.'), 400
        with draft_lock:
            now = time.monotonic()
            for key in list(drafts):
                if now - drafts[key][0] > 300:
                    del drafts[key]
            while len(drafts) >= 32:
                del drafts[next(iter(drafts))]
            key = secrets.token_urlsafe(24)
            drafts[key] = (now, question)
        return jsonify(draft_id=key), 201

    @app.get('/network/strategy/drafts/<draft_id>')
    def load_draft(draft_id):
        with draft_lock:
            value = drafts.get(draft_id)
            if value is None or time.monotonic() - value[0] > 300:
                drafts.pop(draft_id, None)
                return jsonify(error='This draft expired. Enter the goal again.'), 404
            return jsonify(question=value[1])

    @app.post('/network/strategy/runs')
    def start_strategy():
        try:
            values = json_object().copy()
            if service:
                values.setdefault('as_of', datetime.now(UTC).isoformat())
                values.setdefault('focus', service.owner_id)
            payload = AgentRequest.model_validate(values)
            if not payload.question.strip():
                raise ValueError('empty_question')
            GraphQuery(focus=payload.focus, as_of=payload.as_of, mode=payload.mode)
        except (TypeError, ValueError, ValidationError):
            return jsonify(error='Check the goal, context and knowledge date.'), 400
        if not agent.provider.available or agent.remaining <= 0:
            return jsonify(error='Strategy analysis is unavailable or this session budget is used.'), 503
        if agent.lock.locked():
            return jsonify(error='Another analysis is still finishing. Please wait.'), 409
        if service:
            def runner(run):
                return service.answer(payload, agent, emit=run.emit, cancel=run.cancel,
                                      on_dependencies=run.set_dependencies, iterative=True)
            validator = service.validate
        else:
            data, version = store.capture()
            def validator(_):
                return store.capture()[1] == version
            def runner(run):
                return agent.answer(data, payload, version, emit=run.emit, cancel=run.cancel,
                                    validate_sources=lambda: validator({}), iterative=True)
        try:
            run = jobs.start(runner, validator=validator,
                             request_data=payload.model_dump(include={'question', 'focus', 'as_of', 'mode'}))
        except RuntimeError:
            return jsonify(error='Another analysis is still finishing. Please wait.'), 409
        return jsonify(run_id=run.id, status='running'), 202

    @app.get('/network/strategy/runs/<run_id>')
    def strategy_snapshot(run_id):
        try:
            return jsonify(jobs.snapshot(run_id))
        except KeyError:
            return jsonify(error='This analysis expired or the app restarted. Start a new analysis.'), 404

    @app.post('/network/strategy/runs/<run_id>/cancel')
    def cancel_strategy(run_id):
        try:
            return jsonify(jobs.cancel(run_id))
        except KeyError:
            return jsonify(error='Analysis not found.'), 404

    @app.get('/network/strategy/runs/<run_id>/events')
    def strategy_events(run_id):
        try:
            run = jobs.get(run_id)
            after = int(request.headers.get('Last-Event-ID') or request.args.get('after', '0'))
            if after < 0 or after > run.sequence:
                raise ValueError('invalid_sequence')
        except KeyError:
            return jsonify(error='Analysis not found.'), 404
        except ValueError:
            return jsonify(error='Invalid event sequence.'), 400

        def generate():
            cursor = after
            while True:
                snapshot = run._copy_snapshot()
                events = [event for event in snapshot['events'] if event['seq'] > cursor]
                # Each partial is a complete merged view. Reconnecting clients need
                # the newest one, not repeated source checks for superseded graphs.
                latest = max((e['seq'] for e in events if e['type'] == 'partial'), default=0)
                events = [e for e in events if e['type'] != 'partial' or e['seq'] == latest]
                if not any(e['type'] in EVIDENCE_EVENTS for e in events):
                    # Even heartbeat-only/reconnected terminal views can hold revoked evidence.
                    snapshot = run.snapshot()
                    events = [e for e in snapshot['events'] if e['seq'] > cursor]
                for event in events:
                    if event['type'] in EVIDENCE_EVENTS and not run.validate():
                        invalidated = run.snapshot()['events'][-1]
                        yield f'id: {invalidated["seq"]}\ndata: {json.dumps(invalidated)}\n\n'
                        return
                    yield f'id: {event["seq"]}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
                    cursor = event['seq']
                if snapshot['status'] in TERMINAL:
                    return
                if not events:
                    yield ': heartbeat\n\n'
                with run.condition:
                    if run.sequence <= cursor and run.status not in TERMINAL:
                        run.condition.wait(10)

        return Response(stream_with_context(generate()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
