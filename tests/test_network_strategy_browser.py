"""Synthetic route fixtures check UI contracts; server grounding has separate tests."""

import json
import threading

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from scripts.network_demo import create_app


@pytest.fixture
def page():
    server = make_server("127.0.0.1", 0, create_app(testing=True), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        page.base_url = f"http://127.0.0.1:{server.server_port}"
        yield page
        browser.close()
    server.shutdown()


def answer():
    return {
        "summary": "Authored UI example", "findings": [], "gaps": [], "next_steps": [],
        "clarification": "", "entities": [], "evidence": [], "trace": [], "version": 1,
        "model": "synthetic-ui-fixture", "usage": {"input_tokens": 1, "output_tokens": 1},
        "strategy_graph": {
            "nodes": [{"id": "requirement:pilot", "name": "Pilot need", "kind": "requirement"},
                      {"id": "org:atlas", "name": "Atlas Logistics", "kind": "organization"}],
            "edges": [{"id": "candidate:1", "source": "requirement:pilot", "target": "org:atlas",
                       "label": "Candidate evidence", "kind": "candidate", "evidence_ids": ["ui:e1"]}],
            "requirements": [{"id": "pilot", "label": "Pilot need", "status": "matching_evidence"},
                             {"id": "budget", "label": "Budget owner", "status": "searched_no_match"}],
            "records": [{"id": "ui:a1", "label": "Company pilot need", "entity_ids": ["org:atlas"],
                         "evidence_ids": ["ui:e1"], "quote": "<script>not executable</script>"}],
            "evidence": [{"id": "ui:e1", "channel": "email", "at": "2026-09-20T00:00:00Z",
                          "text": "<script>not executable</script>"}],
            "note": "Authored synthetic example; candidate relevance requires validation.",
        },
    }


def fulfill(route, payload):
    route.fulfill(content_type="application/json", body=json.dumps(payload))


def test_explicit_search_hands_off_once_and_renders_evidence_map(page):
    requests = []
    page.route("**/network/search.json?*", lambda r: fulfill(r, {"status": "needs_clarification", "criteria": [], "unresolved": "goal", "results": []}))
    page.route("**/network/agent.json", lambda r: (requests.append(r.request.post_data_json), fulfill(r, answer())))
    page.goto(page.base_url + "/inbox?mode=history&as_of=2026-09-25T12%3A00%3A00Z")
    page.locator("#searchbar").click()
    page.locator("#discovery-query").fill("Find a logistics AI security pilot and identify missing decision authority")
    assert requests == []
    page.get_by_role("button", name="Search", exact=True).click()
    expect(page.locator(".strategy-map")).to_be_visible()
    assert len(requests) == 1
    assert requests[0]["question"].startswith("Find a logistics")
    assert requests[0]["mode"] == "history"
    assert requests[0]["as_of"] == "2026-09-25T12:00:00Z"
    page.get_by_role("button", name="Pilot need", exact=False).click()
    expect(page.locator('[data-strategy-record="ui:a1"]')).to_have_class("strategy-record is-highlighted")
    page.locator(".strategy-record summary").click()
    expect(page.locator(".strategy-record blockquote").last).to_have_text("<script>not executable</script>")
    assert "mode=history" in page.locator(".strategy-record a").first.get_attribute("href")
    assert page.locator(".strategy-record script").count() == 0
    expect(page.get_by_text("Budget owner", exact=False)).to_be_visible()
    page.get_by_role("button", name="Close assistant").click()
    assert page.locator(".strategy-map").count() == 0


def test_profile_review_corrects_subject_and_preserves_new_review_date(page):
    requests, reads = [], []
    profile = {"entity": {"id": "person:maya", "name": "Maya Chen"}, "version": 1,
        "as_of": "2026-09-27T12:00:00Z", "mode": "history", "coverage": "Authored UI example",
        "entities": [{"id": "person:maya", "name": "Maya Chen"}, {"id": "org:atlas", "name": "Atlas Logistics"}],
        "assertions": [{"id": "ui:a1", "subject_id": "org:atlas", "facet": "need", "label": "Pilot need",
            "basis": "reported", "quote": "Atlas needs a pilot", "evidence_ids": ["ui:e1"],
            "status": "pending", "active": True, "valid_from": "2026-09-01", "valid_to": None}],
        "evidence": [{"id": "ui:e1", "channel": "email", "at": "2026-09-20T00:00:00Z", "text": "Atlas needs a pilot"}]}
    page.route("**/network/profile.json?*", lambda r: (reads.append(r.request.url), fulfill(r, profile)))
    def review(route):
        requests.append(route.request.post_data_json)
        profile["version"] += 1
        profile["assertions"][0]["status"] = "confirmed"
        profile["assertions"][0]["subject_id"] = route.request.post_data_json["subject_id"]
        fulfill(route, {"version": profile["version"], "as_of": "2026-09-28T03:00:00Z"})
    page.route("**/network/profile/review", review)
    page.goto(page.base_url + "/network?focus=person:maya&mode=history")
    expect(page.get_by_role("heading", name="Strategic profile", exact=True)).to_be_visible()
    expect(page.locator(".profile-subject")).to_contain_text("Atlas Logistics")
    page.locator(".profile-assertion summary").click()
    expect(page.locator(".profile-assertion blockquote").last).to_have_text("Atlas needs a pilot")
    page.get_by_label("Correct subject").select_option("org:atlas")
    page.get_by_role("button", name="Confirm", exact=True).click()
    expect(page.locator(".profile-status")).to_have_text("confirmed")
    assert requests == [{"id": "ui:a1", "status": "confirmed", "subject_id": "org:atlas", "version": 1}]
    assert "as_of=2026-09-28T03%3A00%3A00Z" in reads[-1]
    expect(page.get_by_role("button", name="Reject", exact=True)).to_be_visible()
    expect(page.get_by_text("resets on restart", exact=False)).to_be_visible()
    page.get_by_label("Correct subject").select_option("person:maya")
    page.get_by_role("button", name="Save correction", exact=True).click(timeout=2000)
    expect(page.locator(".profile-subject")).to_contain_text("Maya Chen")
    assert requests[-1] == {"id": "ui:a1", "status": "confirmed", "subject_id": "person:maya", "version": 2}


def test_real_strategy_payload_connects_requirements_and_is_usable_on_mobile(page):
    from adapters.network.model import GraphQuery
    from adapters.network.retrieval import NetworkRetrieval
    from adapters.network.scenario import load_scenario
    from adapters.network.strategy_map import build_strategy_map

    data = load_scenario()
    query = GraphQuery(mode="history")
    retriever = NetworkRetrieval(data, query)
    requirements = [{"id": "pilot", "label": "Security pilot", "terms": ["pilot"]},
                    {"id": "missing", "label": "Unrecorded requirement", "terms": ["quantum submarine"]}]
    pack = retriever.pack([retriever.people(["pilot", "quantum submarine"])], requirements)
    payload = answer()
    payload["strategy_graph"] = build_strategy_map(data, query, pack)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/network/agent.json", lambda r: fulfill(r, payload))
    page.goto(page.base_url + "/network?mode=history")
    page.locator("#ask-network").click()
    page.locator("#agent-question").fill("Who has a logistics security pilot need?")
    page.locator(".agent-send").click()
    page.get_by_role("button", name="Security pilot", exact=False).click()
    expect(page.locator(".strategy-record.is-highlighted").first).to_be_visible()
    assert page.locator('[data-requirement="requirement:pilot"]').count() == 1
    expect(page.get_by_role("button", name="Unrecorded requirement", exact=False)).to_contain_text("Evidence gap")
    assert page.locator(".strategy-canvas canvas").count() > 0
    page.screenshot(path="tmp/network-strategy-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    panel = page.locator(".network-assistant")
    assert panel.bounding_box()["width"] <= 390
    assert panel.evaluate("e=>e.scrollWidth<=e.clientWidth")
    page.screenshot(path="tmp/network-strategy-mobile.png", full_page=True)
    page.locator("#agent-question").fill("What remains uncertain?")
    page.locator(".agent-send").click()
    expect(page.locator(".strategy-map")).to_have_count(2)
    page.get_by_role("button", name="Close assistant").click()
    assert not errors


def test_profile_extraction_failure_is_explicit_and_never_retries_itself(page):
    requests = []
    def fail(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=503, content_type="application/json", body=json.dumps({"error": "Claude is not configured. Start the demo with its local env file."}))
    page.route("**/network/profile/extract", fail)
    page.goto(page.base_url + "/network?focus=person:alex&mode=history")
    extract = page.get_by_role("button", name="Extract draft assertions with Claude")
    expect(extract).to_be_visible()
    assert requests == []
    extract.click()
    expect(page.locator(".profile-feedback")).to_contain_text("Claude is not configured")
    expect(extract).to_be_enabled()
    assert len(requests) == 1
    assert requests[0]["focus"] == "person:alex"
    assert requests[0]["mode"] == "history"
    page.screenshot(path="tmp/network-strategic-profile.png", full_page=True)


def test_profile_mutation_updates_date_even_if_live_refresh_replaces_lens(page):
    def extract(route):
        # Reproduce the SSE race: a graph revision replaces the lens while the
        # paid request is still in flight. Its date update must survive removal.
        page.evaluate("window.originalProfile=document.querySelector('.context-profile')")
        page.request.post(page.base_url + "/network/demo/reply")
        page.wait_for_function("!window.originalProfile.isConnected")
        fulfill(route, {"version": 2, "as_of": "2026-09-28T05:00:00Z"})

    page.route("**/network/profile/extract", extract)
    page.goto(page.base_url + "/network?focus=person:alex&mode=history")
    page.get_by_role("button", name="Extract draft assertions with Claude").click()
    page.wait_for_url("**as_of=2026-09-28T05%3A00%3A00Z**")
    expect(page.get_by_role("heading", name="Strategic profile", exact=True)).to_be_visible()
    assert "mode=history" in page.url


def test_network_disconnect_keeps_question_and_explains_manual_retry(page):
    calls=[]
    def disconnect(route):
        calls.append(route.request.post_data_json)
        route.abort("connectionreset")
    page.route("**/network/agent.json", disconnect)
    page.goto(page.base_url + "/network")
    page.locator("#ask-network").click()
    page.locator("#agent-question").fill("Help me plan a cybersecurity program")
    page.locator(".agent-send").click()
    expect(page.locator(".agent-answer [role=alert]")).to_contain_text("Could not reach the local demo")
    expect(page.locator("#agent-question")).to_have_value("Help me plan a cybersecurity program")
    expect(page.locator(".agent-send")).to_be_enabled()
    assert len(calls)==1
