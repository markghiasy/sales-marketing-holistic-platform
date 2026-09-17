"""Ops dashboard: connect Outlook/LinkedIn/WhatsApp through a web page,
and run the same health checks scripts/monitor.py does in a background
thread so alerts fire whether or not this page is open. See
docs/superpowers/specs/2026-08-31-onboarding-dashboard-design.md.

Run: python scripts/onboarding/app.py
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

from adapters import inbox_query
from adapters.linkedin import login as linkedin_login
from adapters.outlook import client as outlook_client
from adapters.resolution.merge import apply_merge

# scripts/ isn't an installed package (only adapters* is, see
# pyproject.toml), so import its sibling monitor.py by path — same
# Path(__file__)-relative pattern used throughout this repo's adapters.
sys.path.insert(0, str(Path(__file__).parent.parent))
import monitor

_MONITOR_INTERVAL_SECONDS = 15 * 60


_db_conn: psycopg.Connection | None = None
_db_conn_lock = threading.Lock()


@contextlib.contextmanager
def _db_cursor():
    """One persistent connection reused across `/resolution/*` requests,
    guarded by a lock — separate from monitor.run()'s own connection,
    which the background thread manages on its own schedule.

    Found 2026-09-10: the previous version opened a brand new
    `psycopg.connect()` — a real TCP+TLS handshake against Supabase's
    hosted Postgres — on every single request (every page load, every
    Confirm/Reject click), measured at ~1.5s just to connect before any
    query even ran. That's almost certainly a real contributor to how
    unresponsive the review UI felt, on top of the missing-feedback bug
    fixed the day before. Reusing one connection cuts that to near zero
    after the first request. A single serialized connection (the lock
    means only one request touches it at a time) is fine for a
    single-operator internal tool like this — no need for a connection
    pool here.

    Commits on a clean exit, rolls back and drops the held connection on
    any exception so the next call reconnects fresh rather than reusing
    a connection left in a broken/aborted-transaction state.
    """
    global _db_conn
    with _db_conn_lock:
        if _db_conn is None or _db_conn.closed:
            _db_conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
        try:
            with _db_conn.cursor() as cur:
                yield cur
            _db_conn.commit()
        except Exception:
            try:
                _db_conn.rollback()
            except Exception:  # noqa: BLE001, S110 — connection's already broken, nothing to salvage
                pass
            _db_conn = None
            raise


# in-memory only — a real device-code flow is inherently short-lived
# (expires in ~15 min), and this app has no other persistent store, so
# a restart simply means "connect again" rather than needing to survive
# a restart mid-flow
_outlook_state: dict = {"phase": "not_connected"}
_outlook_lock = threading.Lock()

# token -> used; issued fresh by /linkedin/download-helper and consumed by
# /linkedin/upload-session (single-use, in-memory only — same rationale as
# _outlook_state above: this app has no other persistent store, and a
# restart simply means "download the helper again").
#
# _linkedin_tokens_lock guards this dict the same way _outlook_lock guards
# _outlook_state above: linkedin_upload_session() does a check-then-mark
# (is the token unused? then mark it used) that must be atomic, or two
# near-simultaneous uploads with the same valid token could both pass the
# check before either marks it used — the same race Tasks 4/5 closed for
# _outlook_state/_whatsapp spawn tracking. Flask's dev server (app.run())
# defaults to threaded=True as of Flask 3.x, so concurrent requests really
# do run on separate threads here — this lock is load-bearing, not merely
# defensive.
_linkedin_tokens: dict[str, bool] = {}
_linkedin_tokens_lock = threading.Lock()
_LINKEDIN_HELPER_TEMPLATE_PATH = Path(__file__).parent / "linkedin_helper.py.tmpl"


def _token_check_delay_hook() -> None:
    """No-op in production. linkedin_upload_session() calls this between
    its "is the token unused?" check and its "mark it used" write, inside
    _linkedin_tokens_lock. Tests can monkeypatch this to a small
    time.sleep() to force multiple threads to be inside that critical
    section's check-then-mark window at the same instant, which makes the
    concurrency test in tests/test_onboarding_app.py deterministically
    discriminate locked from unlocked behavior instead of relying on a
    lucky GIL preemption inside a two-line window."""


def _onboarding_base_url() -> str:
    return os.environ.get("ONBOARDING_BASE_URL", "http://localhost:5000")

# guards whatsapp_connect()'s check-then-spawn sequence the same way
# _outlook_lock guards the Outlook flow above. ingest.js only writes its
# own .pid file after it finishes starting up (after all its require()s),
# so there's a real window where a second /whatsapp/connect call would
# otherwise see .pid as still-missing-or-stale and spawn a duplicate
# "node ingest.js" — ingest.js has no protection against being
# double-started, and two processes sharing one .auth_state would
# corrupt it.
#
# _whatsapp_spawn_started_at is set to time.monotonic() right before
# Popen() and cleared (back to None) the first of three ways: (1) a later
# call observes .pid pointing at a live process, (2) Popen() itself raises
# (node missing, bad cwd, ...) — caught in whatsapp_connect() so the flag
# never survives a spawn attempt that failed synchronously, or (3) the
# grace period below elapses without either of the above happening, which
# covers ingest.js exiting before it ever gets far enough to write .pid
# (e.g. a require() failure on a broken node_modules) — with no live pid
# and no exception, nothing else would ever clear the flag. The grace
# period only needs to comfortably exceed ingest.js's require()-to-.pid
# window (that write happens essentially immediately, before any async
# work) — 10s leaves a wide margin without meaningfully weakening the
# rapid-fire double-spawn protection this flag exists for.
_WHATSAPP_SPAWN_GRACE_SECONDS = 10.0
_whatsapp_lock = threading.Lock()
_whatsapp_spawn_started_at: float | None = None


def _whatsapp_pid_is_live() -> bool:
    pid_text = (
        monitor.WHATSAPP_PID_PATH.read_text().strip()
        if monitor.WHATSAPP_PID_PATH.exists() else ""
    )
    return bool(pid_text and pid_text.isdigit() and monitor._pid_is_alive(int(pid_text)))


def _clear_whatsapp_spawn_flag_if_live() -> None:
    """Called from /whatsapp/status (and implicitly whenever
    /whatsapp/connect re-checks liveness) so the in-progress flag doesn't
    permanently lock out future spawns after the connector it was tracking
    is confirmed alive and later dies."""
    global _whatsapp_spawn_started_at
    if _whatsapp_spawn_started_at is not None:
        with _whatsapp_lock:
            if _whatsapp_spawn_started_at is not None and _whatsapp_pid_is_live():
                _whatsapp_spawn_started_at = None


def _outlook_connect_worker() -> None:
    def on_device_code(flow: dict) -> None:
        with _outlook_lock:
            _outlook_state.update(
                phase="pending", code=flow["user_code"], url=flow["verification_uri"]
            )

    try:
        outlook_client.get_access_token(on_device_code=on_device_code)
        with _outlook_lock:
            _outlook_state.update(phase="connected")
    except Exception as e:  # noqa: BLE001 — any failure must reach a terminal
        # phase so /outlook/status can report it instead of hanging at
        # "starting" forever; only the message distinguishes "expired".
        with _outlook_lock:
            state = "expired" if "expired" in str(e) else "error"
            _outlook_state.update(phase=state, error=str(e))


def _background_monitor_loop() -> None:
    while True:
        try:
            monitor.run()
        except Exception as e:  # noqa: BLE001 — the loop must survive a bad check
            print(f"background monitor check failed: {e}", file=sys.stderr)
        time.sleep(_MONITOR_INTERVAL_SECONDS)


def create_app(testing: bool = False) -> Flask:
    load_dotenv()
    flask_app = Flask(__name__)

    @flask_app.get("/")
    def index():
        return render_template("index.html")

    @flask_app.get("/status")
    def status():
        # none of the three channel checks touch the database — each
        # reads its adapter's own liveness file — so there's no store
        # connection to degrade from here any more (see monitor.py's
        # check_all/run for where store-reachability is still checked,
        # as its own independent failure mode)
        statuses = monitor.check_all()
        return jsonify({s.channel: {"healthy": s.healthy, "detail": s.detail} for s in statuses})

    @flask_app.post("/outlook/connect")
    def outlook_connect():
        with _outlook_lock:
            if _outlook_state.get("phase") in ("starting", "pending"):
                return jsonify({"status": "already_in_progress"})
            # nothing attempted yet this process lifetime (or a prior
            # attempt already reached a terminal state) — before starting
            # a brand-new device-code flow, check whether a still-valid
            # token is already sitting on disk from a previous run of this
            # app. _outlook_state is in-memory only and resets to
            # not_connected on every restart, but the token cache survives
            # restarts, so without this check a restart would force a
            # needless re-login even though the mailbox is already
            # connected.
            if _outlook_state.get("phase", "not_connected") == "not_connected" and outlook_client.has_valid_cached_token():
                return jsonify({"status": "already_connected"})
            _outlook_state.clear()
            _outlook_state["phase"] = "starting"
        threading.Thread(target=_outlook_connect_worker, daemon=True).start()
        return jsonify({"status": "started"})

    @flask_app.get("/outlook/status")
    def outlook_status():
        with _outlook_lock:
            phase = _outlook_state.get("phase", "not_connected")
            code = _outlook_state.get("code")
            url = _outlook_state.get("url")
            error = _outlook_state.get("error")

        if phase == "not_connected" and outlook_client.has_valid_cached_token():
            # nothing attempted yet this process lifetime, but a valid
            # token is already on disk from a previous run — report the
            # same "connected" state a freshly-completed flow would,
            # rather than "not connected" just because this process
            # hasn't itself run the flow since it started.
            mailbox = os.environ.get("OUTLOOK_MAILBOX")
            return jsonify({"state": "connected", "code": None, "url": None, "mailbox": mailbox})

        if phase in ("not_connected", "starting"):
            return jsonify({"state": phase, "code": None, "url": None, "mailbox": None})
        if phase == "pending":
            return jsonify({"state": "pending", "code": code, "url": url, "mailbox": None})
        if phase == "connected":
            mailbox = os.environ.get("OUTLOOK_MAILBOX")
            return jsonify({"state": "connected", "code": None, "url": None, "mailbox": mailbox})
        # terminal failure states ("error", "expired") carry the message
        # from _outlook_connect_worker's except clause
        return jsonify({"state": phase, "code": None, "url": None, "mailbox": None, "error": error})

    @flask_app.get("/whatsapp/status")
    def whatsapp_status():
        _clear_whatsapp_spawn_flag_if_live()
        if not monitor.WHATSAPP_STATUS_PATH.exists():
            return jsonify({"state": "not_connected"})
        try:
            status = json.loads(monitor.WHATSAPP_STATUS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            # .status.json exists but is malformed — ingest.js's
            # writeStatus() does a non-atomic fs.writeFileSync, so a
            # concurrent read can catch it mid-write. Treat this the same
            # as "no status available yet" rather than 500ing the route,
            # mirroring monitor._check_whatsapp_liveness()'s handling of
            # this exact same file/failure mode.
            return jsonify({"state": "not_connected"})
        return jsonify(status)

    @flask_app.post("/whatsapp/connect")
    def whatsapp_connect():
        global _whatsapp_spawn_started_at
        with _whatsapp_lock:
            if _whatsapp_pid_is_live():
                _whatsapp_spawn_started_at = None
                return jsonify({"status": "already_running"})

            if _whatsapp_spawn_started_at is not None:
                elapsed = time.monotonic() - _whatsapp_spawn_started_at
                if elapsed < _WHATSAPP_SPAWN_GRACE_SECONDS:
                    # a spawn from a rapid-fire earlier call may still be
                    # starting up — ingest.js hasn't written .pid yet, so
                    # the liveness check above can't see it. Don't spawn a
                    # second process on top of it; it'll clear itself once
                    # .pid shows the process alive (see
                    # _whatsapp_pid_is_live/_clear_whatsapp_spawn_flag_if_live).
                    return jsonify({"status": "already_running"})
                # past the grace period with no live pid and no exception
                # from a prior Popen() — the earlier spawn's process must
                # have exited before ever writing .pid (e.g. ingest.js's
                # require()s failing outright, before its own crash
                # handlers even exist to record anything). Treat the flag
                # as stale and fall through to try a fresh spawn rather
                # than staying locked out until the app is restarted.
                _whatsapp_spawn_started_at = None

            _whatsapp_spawn_started_at = time.monotonic()
            try:
                subprocess.Popen(
                    ["node", "ingest.js"],
                    cwd=str(monitor._WHATSAPP_DIR),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as e:
                # e.g. node isn't on PATH, or cwd doesn't exist — Popen()
                # raised synchronously inside the lock, so nothing was
                # ever spawned. Clear the flag immediately rather than
                # waiting out the grace period, and report a clean error
                # instead of letting this 500.
                _whatsapp_spawn_started_at = None
                return jsonify({"status": "error", "detail": str(e)})
        return jsonify({"status": "started"})

    @flask_app.get("/whatsapp/qr.png")
    def whatsapp_qr():
        qr_path = monitor._WHATSAPP_DIR / "qr.png"
        if not qr_path.exists():
            return jsonify({"error": "no QR available yet"}), 404
        return send_file(qr_path, mimetype="image/png", max_age=0)

    @flask_app.get("/linkedin/download-helper")
    def linkedin_download_helper():
        token = secrets.token_urlsafe(24)
        with _linkedin_tokens_lock:
            _linkedin_tokens[token] = False
        template = _LINKEDIN_HELPER_TEMPLATE_PATH.read_text()
        script = template.replace("{{BASE_URL}}", _onboarding_base_url()).replace("{{TOKEN}}", token)
        return flask_app.response_class(
            script,
            mimetype="text/x-python",
            headers={"Content-Disposition": "attachment; filename=connect_linkedin.py"},
        )

    @flask_app.post("/linkedin/upload-session")
    def linkedin_upload_session():
        token = request.headers.get("X-Onboarding-Token", "")
        with _linkedin_tokens_lock:
            if token not in _linkedin_tokens or _linkedin_tokens[token]:
                return jsonify({"error": "invalid or already-used token"}), 403
            _token_check_delay_hook()
            _linkedin_tokens[token] = True
        linkedin_login.STORAGE_STATE_PATH.write_text(json.dumps(request.get_json()))
        return jsonify({"status": "connected"})

    @flask_app.get("/linkedin/status")
    def linkedin_status():
        return jsonify({"connected": linkedin_login.STORAGE_STATE_PATH.exists()})

    @flask_app.get("/resolution")
    def resolution_page():
        return render_template("resolution.html")

    @flask_app.get("/inbox")
    def inbox_page():
        return render_template("inbox.html")

    @flask_app.get("/inbox/conversations.json")
    def inbox_conversations_json():
        with _db_cursor() as cur:
            rows = inbox_query.list_conversations(cur)
        return jsonify([
            {
                "person_key": r.person_key, "name": r.name, "channel": r.channel,
                "last_message_at": r.last_message_at, "unread": r.unread, "unanswered": r.unanswered,
                "summary": r.summary, "topic": r.topic, "urgency": r.urgency, "has_draft": r.has_draft,
            }
            for r in rows
        ])

    @flask_app.get("/inbox/conversation/<person_key>.json")
    def inbox_conversation_detail_json(person_key):
        with _db_cursor() as cur:
            detail = inbox_query.get_detail(cur, person_key)
        if detail is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({
            "person_key": detail.person_key, "name": detail.name, "channel": detail.channel,
            "last_message_at": detail.last_message_at,
            "threads": [
                {
                    "channel": t.channel, "subject": t.subject,
                    "messages": [
                        {"sender": m.sender, "text": m.text, "sent_at": m.sent_at, "to": m.to, "cc": m.cc}
                        for m in t.messages
                    ],
                }
                for t in detail.threads
            ],
            "context": detail.context, "graph": detail.graph, "topic": detail.topic, "urgency": detail.urgency,
        })

    @flask_app.post("/inbox/conversation/<person_key>/read")
    def inbox_conversation_mark_read(person_key):
        with _db_cursor() as cur:
            inbox_query.mark_read(cur, person_key)
        return jsonify({"status": "ok"})

    @flask_app.get("/resolution/candidates.json")
    def resolution_candidates_json():
        with _db_cursor() as cur:
            cur.execute(
                """
                select lc.id, lc.score, lc.method, lc.reason,
                       ia.display_name, ia.channel, ia.handle,
                       ib.display_name, ib.channel, ib.handle
                from link_candidate lc
                join identity ia on ia.id = lc.identity_a_id
                join identity ib on ib.id = lc.identity_b_id
                where lc.status = 'pending'
                order by lc.score desc
                """
            )
            rows = cur.fetchall()
        return jsonify([
            {
                "id": r[0], "score": r[1], "method": r[2], "reason": r[3],
                # handle (the real email/phone/LinkedIn id) is always
                # present — a reviewer can't actually judge "same person?"
                # from a display_name alone, which is often blank. Found
                # 2026-09-09: the page previously omitted this entirely.
                "name_a": r[4] or "(no name)", "channel_a": r[5], "handle_a": r[6],
                "name_b": r[7] or "(no name)", "channel_b": r[8], "handle_b": r[9],
            }
            for r in rows
        ])

    @flask_app.post("/resolution/candidate/<candidate_id>/confirm")
    def resolution_candidate_confirm(candidate_id):
        # Claim the row with an atomic conditional UPDATE *before*
        # touching identity/person state, and check identity_a_id/
        # identity_b_id from ITS return value, not a separate SELECT —
        # a plain SELECT-then-UPDATE let concurrent requests (e.g. a
        # user double/triple-clicking a Confirm button that gives no
        # visible feedback, found 2026-09-09 against real hosted data:
        # one candidate got merged 5 times in 9 seconds) all read
        # status='pending' before any of them committed, so all of
        # them called apply_merge and each wrote its own merge_log
        # row for what should have been a single merge event. Only
        # the request whose UPDATE actually flips pending->confirmed
        # proceeds; every other concurrent or repeat request sees 0
        # rows updated and no-ops instead. _db_cursor()'s own lock now
        # serializes requests too, so this is defense in depth rather
        # than the only thing preventing a double-merge.
        with _db_cursor() as cur:
            cur.execute(
                """
                update link_candidate set status = 'confirmed'
                where id = %s and status = 'pending'
                returning identity_a_id, identity_b_id
                """,
                (candidate_id,),
            )
            row = cur.fetchone()
            if row is None:
                return jsonify({"status": "no_op"})
            identity_a_id, identity_b_id = row
            apply_merge(cur, str(identity_a_id), str(identity_b_id))
        return jsonify({"status": "confirmed"})

    @flask_app.post("/resolution/candidate/<candidate_id>/reject")
    def resolution_candidate_reject(candidate_id):
        with _db_cursor() as cur:
            cur.execute("update link_candidate set status = 'rejected' where id = %s and status = 'pending'", (candidate_id,))
        return jsonify({"status": "rejected"})

    @flask_app.get("/resolution/facts.json")
    def resolution_facts_json():
        with _db_cursor() as cur:
            cur.execute(
                """
                select f.id, f.fact_type, f.confidence, f.source, f.reason,
                       i.display_name, f.object_text, o.canonical_name
                from fact f
                join identity i on i.id = f.subject_identity_id
                left join organization o on o.id = f.object_org_id
                where f.status = 'pending'
                order by f.confidence desc
                """
            )
            rows = cur.fetchall()
        return jsonify([
            {
                "id": r[0], "fact_type": r[1], "confidence": r[2], "source": r[3], "reason": r[4],
                "subject_name": r[5] or "(no name)",
                "object_display": r[7] or r[6] or "(unknown)",
            }
            for r in rows
        ])

    @flask_app.post("/resolution/fact/<fact_id>/confirm")
    def resolution_fact_confirm(fact_id):
        with _db_cursor() as cur:
            cur.execute("update fact set status = 'confirmed', reviewed_at = now() where id = %s and status = 'pending'", (fact_id,))
        return jsonify({"status": "confirmed"})

    @flask_app.post("/resolution/fact/<fact_id>/reject")
    def resolution_fact_reject(fact_id):
        with _db_cursor() as cur:
            cur.execute("update fact set status = 'rejected', reviewed_at = now() where id = %s and status = 'pending'", (fact_id,))
        return jsonify({"status": "rejected"})

    if not testing:
        thread = threading.Thread(target=_background_monitor_loop, daemon=True)
        thread.start()

    return flask_app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
