"""Local synthetic demo. Run: python -m scripts.network_demo [--port 5055]."""

import argparse
import json
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from pydantic import ValidationError

from adapters.network.model import GraphQuery, timestamp
from adapters.network.scenario import ScenarioStore
from adapters.network.search import contact_tags


def create_app(*, testing=False):
    root = Path(__file__).resolve().parent / "onboarding"
    app = Flask(
        __name__, template_folder=str(root / "templates"), static_folder=str(root / "static")
    )
    app.testing = testing
    store = ScenarioStore()
    app.extensions["network_store"] = store

    def query():
        return GraphQuery(**request.args.to_dict())

    @app.errorhandler(ValidationError)
    def invalid(error):
        return jsonify(error="Invalid graph query. Check the selected date and view."), 400

    @app.get("/")
    @app.get("/network")
    def explorer():
        return render_template("network.html")

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
        row = next(
            (
                e
                for e in store.data()["evidence"]
                if e["id"] == evidence_id and timestamp(e["at"]) <= q.as_of
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
        if not text or len(text) > 600:
            return jsonify(error="Enter a search between 1 and 600 characters."), 400
        return jsonify(store.search(query(), text))

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
    args = parser.parse_args()
    create_app().run(
        host="127.0.0.1", port=args.port, debug=False, threaded=True, use_reloader=False
    )
