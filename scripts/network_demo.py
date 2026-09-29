"""Local synthetic demo. Run: python -m scripts.network_demo [--port 5055]."""

import argparse
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from dotenv import dotenv_values
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from pydantic import Field, ValidationError

from adapters.network.agent import (
    AgentRequest,
    AgentUnavailable,
    ClaudeProvider,
    NetworkAgent,
    StrictModel,
)
from adapters.network.context import entity_context
from adapters.network.model import GraphQuery, timestamp
from adapters.network.profiles import profile_context
from adapters.network.scenario import ScenarioStore
from adapters.network.search import contact_tags


class ProfileReview(StrictModel):
    id: str = Field(min_length=1, max_length=160)
    status: Literal["confirmed", "rejected"]
    subject_id: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1)


class ProfileExtraction(StrictModel):
    focus: str = "person:owner"
    as_of: str = "2026-09-27T12:00:00Z"
    mode: Literal["current", "history"] = "current"


def create_app(*, testing=False, llm_config=None, agent_provider=None, network_service=None):
    if network_service is not None:
        from scripts.network_real import create_app as create_real_app
        return create_real_app(service=network_service,testing=testing,llm_config=llm_config,agent_provider=agent_provider)
    root = Path(__file__).resolve().parent / "onboarding"
    app = Flask(
        __name__, template_folder=str(root / "templates"), static_folder=str(root / "static")
    )
    app.testing = testing
    store = ScenarioStore()
    app.extensions["network_store"] = store
    app.config["MAX_CONTENT_LENGTH"] = 150000  # Includes JSON's six-byte Unicode escaping.
    app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost"]
    provider = agent_provider or ClaudeProvider(llm_config)
    if testing and agent_provider is None:
        provider.key = ""  # Ordinary tests must never spend API credits.
    agent = NetworkAgent(provider)
    app.extensions["network_agent"] = agent

    def query():
        return GraphQuery(**request.args.to_dict())

    @app.errorhandler(ValidationError)
    def invalid(error):
        return jsonify(error="Invalid graph query. Check the selected date and view."), 400

    @app.get("/")
    @app.get("/network")
    def explorer():
        origin = request.args.get("origin", "")
        back = "/inbox"
        if origin:
            back += "?" + urlencode({**request.args.to_dict(), "focus": origin})
        return render_template("network.html", return_url=back, has_origin=bool(origin))

    @app.get("/inbox")
    def inbox():
        return render_template("inbox.html", network_demo=True)

    @app.get("/network/graph.json")
    def graph():
        try:
            return jsonify(store.snapshot(query()))
        except KeyError:
            return jsonify(error="Contact or context not found."), 404

    @app.get("/network/evidence/<evidence_id>.json")
    def evidence(evidence_id):
        q = query()
        data = store.data()
        row = next(
            (
                e
                for e in [*data["evidence"], *(m for m in data["messages"] if m.get("direct"))]
                if e["id"] == evidence_id
                and all(
                    timestamp(e[field]) <= q.as_of
                    for field in ("at", "observed_at", "known_at")
                    if e.get(field)
                )
            ),
            None,
        )
        return (
            (jsonify(row), 200)
            if row
            else (jsonify(error="Evidence not available at this time."), 404)
        )

    @app.get("/network/search.json")
    def search():
        text = request.args.get("q", "").strip()
        if not text or len(text) > 2000:
            return jsonify(error="Enter a search between 1 and 2000 characters."), 400
        return jsonify(store.search(query(), text))

    @app.get("/network/context.json")
    def context():
        data, version = store.capture()
        try:
            return jsonify(**entity_context(data, query()), version=version)
        except KeyError:
            return jsonify(error="Context not found."), 404

    def mutation_error():
        if request.headers.get("Origin") and request.headers["Origin"].rstrip(
            "/"
        ) != request.host_url.rstrip("/"):
            return jsonify(error="Cross-origin changes are not allowed."), 403
        if not request.is_json:
            return jsonify(error="Send a JSON request."), 415
        return None

    @app.get("/network/profile.json")
    def profile():
        data, version = store.capture()
        try:
            q = query().model_copy(update={"include_pending": True})
            return jsonify(**profile_context(data, q), version=version)
        except KeyError:
            return jsonify(error="Profile not found."), 404

    @app.post("/network/profile/review")
    def review_profile():
        error = mutation_error()
        if error:
            return error
        payload = ProfileReview.model_validate(request.get_json())
        try:
            return jsonify(
                store.review_profile(
                    payload.id, payload.status, payload.subject_id, payload.version
                )
            )
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        except KeyError:
            return jsonify(error="Assertion not found."), 404
        except ValueError:
            return jsonify(
                error="The corrected subject is inconsistent with this source. Reject it and re-extract."
            ), 400

    @app.post("/network/profile/extract")
    def extract_profile():
        error = mutation_error()
        if error:
            return error
        payload = ProfileExtraction.model_validate(request.get_json())
        q = GraphQuery(**payload.model_dump(), include_pending=True)
        data, version = store.capture()
        if q.focus not in {n["id"] for n in data["nodes"]}:
            return jsonify(error="Profile not found."), 404
        try:
            rows, usage = agent.extract_profiles(data, q)
            saved = store.add_profile_proposals(rows, version)
            q = q.model_copy(update={"as_of": timestamp(saved["as_of"])})
            updated, current_version = store.capture()
            return jsonify(
                **profile_context(updated, q),
                version=current_version,
                added=saved["added"],
                usage=usage,
                model=provider.model,
            )
        except AgentUnavailable as exc:
            return jsonify(error=str(exc)), 503
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        except Exception:  # noqa: BLE001 - sanitize provider errors at HTTP boundary
            return jsonify(
                error="Claude could not produce valid profile proposals. No profile was changed."
            ), 502

    @app.get("/network/agent/status.json")
    def agent_status():
        return jsonify(
            configured=provider.available,
            model=provider.model if provider.available else None,
            remaining=agent.remaining,
            data_source="synthetic",
        )

    @app.post("/network/agent.json")
    def ask_agent():
        # A website visited elsewhere must not be able to spend local API credits.
        if request.headers.get("Origin") and request.headers["Origin"].rstrip(
            "/"
        ) != request.host_url.rstrip("/"):
            return jsonify(error="Cross-origin questions are not allowed."), 403
        if not request.is_json:
            return jsonify(error="Send a JSON question."), 415
        payload = AgentRequest.model_validate(request.get_json())
        if not payload.question.strip():
            return jsonify(error="Enter a question."), 400
        GraphQuery(focus=payload.focus, as_of=payload.as_of)
        data, version = store.capture()
        try:
            return jsonify(agent.answer(data, payload, version))
        except AgentUnavailable as error:
            return jsonify(error=str(error)), 503
        except Exception:  # noqa: BLE001 - sanitize all provider failures at the HTTP boundary
            # Provider errors can contain request details. Do not expose or log them.
            return jsonify(
                error="Claude could not produce a source-linked answer. Please retry; no network data was changed."
            ), 502

    @app.post("/network/demo/reply")
    def reply():
        return jsonify(version=store.reply())

    @app.post("/network/demo/reset")
    def reset():
        return jsonify(version=store.reset())

    @app.get("/network/events")
    @app.get("/inbox/events")
    def events():
        def generate():
            version = store.version
            while True:
                yield f"event: update\ndata: {json.dumps({'version': version})}\n\n"
                version = store.wait_for_version(version, 15)

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    def contact_row(node, data, tags=None):
        messages = [m for m in data["messages"] if m["contact_id"] == node["id"]]
        return {
            "person_key": node["id"],
            "name": node["name"],
            "channel": "outlook",
            "last_message_at": max((m["at"] for m in messages), default="2026-01-15T09:00:00Z"),
            "summary": node["role"],
            "topic": "Harbour finance review"
            if node["id"] in ("person:maya", "person:priya")
            else "Industry discussion",
            "tags": (tags if tags is not None else contact_tags(data, query())).get(node["id"], []),
            "urgency": 2 if node["id"] == "person:maya" else 1,
            "unread": False,
            "unanswered": False,
            "has_draft": False,
        }

    @app.get("/inbox/conversations.json")
    def conversations():
        data = store.data()
        tags = contact_tags(data, query())
        return jsonify(
            [
                contact_row(n, data, tags)
                for n in data["nodes"]
                if n["kind"] == "person" and n["id"] != data["owner_id"]
            ]
        )

    @app.get("/inbox/conversation/<person_key>.json")
    def detail(person_key):
        data = store.data()
        node = next(
            (n for n in data["nodes"] if n["id"] == person_key and n["kind"] == "person"), None
        )
        if node is None:
            return jsonify(error="Contact not found"), 404
        messages = [
            {
                "channel": m["channel"],
                "subject": "Fictional project discussion",
                "sender": "you" if m["direction"] == "out" else "them",
                "text": m["text"],
                "sent_at": m["at"],
                "to": [],
                "cc": [],
                "from_name": "Jordan Ellis" if m["direction"] == "out" else node["name"],
            }
            for m in data["messages"]
            if m["contact_id"] == person_key
        ]
        context = [
            "This is a fictional contact in Jordan Ellis's demonstration network.",
            node["role"] + ".",
            "Inspect the Network below to see separately supported roles, projects and source messages.",
        ]
        return jsonify(
            {
                **contact_row(node, data),
                "messages": sorted(messages, key=lambda m: m["sent_at"]),
                "context": context,
                "graph": {"people": []},
            }
        )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5055)
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Local .env containing Anthropic configuration; never served to the browser",
    )
    args = parser.parse_args()
    config = dotenv_values(args.env_file) if args.env_file else None
    create_app(llm_config=config).run(
        host="127.0.0.1", port=args.port, debug=False, threaded=True, use_reloader=False
    )
