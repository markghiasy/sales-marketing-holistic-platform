"""Behavioral acceptance using a local fixture server and headless Chromium."""

import threading

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from scripts.network_demo import create_app


@pytest.fixture
def page():
    server = make_server("127.0.0.1", 0, create_app(testing=True), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.base_url = f"http://127.0.0.1:{server.server_port}"
        yield page
        browser.close()
    server.shutdown()


def test_explorer_filters_evidence_and_reply(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(page.base_url + "/network")
    page.get_by_role("heading", name="Your network", exact=True).wait_for()
    page.get_by_role("combobox", name="Function", exact=True).select_option("Accounting")
    page.get_by_role("combobox", name="Project", exact=True).select_option("project:harbour")
    page.locator('[data-person="person:maya"]').click()
    page.get_by_role("button", name="View evidence").first.click()
    page.locator(".evidence-quote").first.wait_for()
    assert "Fictional" in page.locator("#inspector").inner_text()
    page.get_by_role("button", name="Simulate reply").click()
    page.get_by_text("Scenario updated", exact=False).wait_for()
    assert not errors


def test_embedded_slice_round_trip(page):
    page.goto(page.base_url + "/inbox?focus=person:maya&as_of=2026-09-27T12%3A00%3A00Z")
    page.get_by_role("link", name="Open full network").wait_for()
    page.get_by_role("link", name="Open full network").click()
    page.get_by_role("heading", name="Your network", exact=True).wait_for()
    assert "focus=person%3Amaya" in page.url
    page.get_by_role("link", name="Return to conversation").click()
    page.get_by_role("link", name="Open full network").wait_for()
    assert page.locator(".detail-head").inner_text().startswith("MC\nMaya Chen")


def test_many_sources_load_a_bounded_page_and_keep_successes_on_one_failure(page):
    from playwright.sync_api import expect
    page.goto(page.base_url+'/network')
    count=[]
    def evidence(route):
        count.append(route.request.url)
        if '/source-1.json' in route.request.url:
            route.fulfill(status=409,content_type='application/json',body='{}')
        else:
            route.fulfill(content_type='application/json',body='{"channel":"outlook","at":"2026-09-27T00:00:00Z","text":"Available source"}')
    page.route('**/network/evidence/source-*.json*',evidence)
    page.evaluate('''async () => {
      const {showEvidence}=await import('/static/network/client.js');
      const target=document.createElement('div');target.id='large-evidence-test';document.body.append(target);
      await showEvidence(target,{evidence_ids:Array.from({length:400},(_,i)=>`source-${i}`)},
        {as_of:'2026-09-27T12:00:00Z',version:1});
    }''')
    assert len(count)==3
    expect(page.locator('#large-evidence-test .evidence-quote')).to_have_count(2)
    expect(page.locator('#large-evidence-test')).to_contain_text('unavailable')
    page.locator('#large-evidence-test').get_by_role('button',name='Load more sources').click()
    expect(page.locator('#large-evidence-test .evidence-quote')).to_have_count(5)
    assert len(count)==6


@pytest.mark.parametrize("entry", ["explorer", "inbox"])
def test_assistant_preserves_history_and_explains_retrieval_coverage(page, entry):
    import json

    requests = []

    def answer(route):
        requests.append(route.request.post_data_json)
        route.fulfill(content_type="application/json", body=json.dumps({
            "summary": "Validate the available evidence.", "findings": [], "gaps": [],
            "next_steps": [], "clarification": "", "entities": [], "evidence": [],
            "version": 1, "model": "synthetic-test", "usage": {"input_tokens": 20, "output_tokens": 10},
            "trace": [], "retrieval": {"scope": {"scanned_people": 24},
                "budget": {"selected_records": 4, "omitted_records": 2},
                "coverage": [{"label": "Security testing", "status": "searched_no_match"},
                             {"label": "Project work", "status": "budget_omitted"}]}
        }))

    page.route("**/network/agent.json", answer)
    if entry == "explorer":
        page.goto(page.base_url + "/network?mode=history&focus=person:alex")
        page.locator("#ask-network").click()
    else:
        page.goto(page.base_url + "/inbox?mode=history")
        page.locator("#searchbar").click()
        page.locator(".discovery-agent").click()
    page.locator("#agent-question").fill("Who could help?")
    page.locator(".agent-send").click()
    page.get_by_text("How this answer was grounded").click()
    page.get_by_text("No match in searched records", exact=False).wait_for()
    assert requests[0]["mode"] == "history"
    assert "24 contacts searched" in page.locator(".agent-trace").inner_text()
    assert "Matching records found but omitted" in page.locator(".agent-coverage").inner_text()
    if entry == "explorer":
        page.screenshot(path="docs/demos/network-retrieval-coverage.png", full_page=True)


def test_compact_all_claims_and_selection_survive_round_trip(page):
    page.goto(page.base_url + "/inbox?focus=person:maya&claim=collab-maya")
    page.locator(".embed-status").filter(has_text="entities").wait_for()
    assert page.locator('[data-evidence="collab-maya"]').count() == 1
    assert page.locator('[data-evidence="client-maya"]').count() == 1
    page.locator('[data-evidence="collab-maya"]').click()
    link = page.get_by_role("link", name="Open full network")
    assert "claim=collab-maya" in link.get_attribute("href")
    link.click()
    page.get_by_role("link", name="Return to conversation").click()
    page.locator(".embed-status").filter(has_text="entities").wait_for()
    assert "claim=collab-maya" in page.get_by_role("link", name="Open full network").get_attribute(
        "href"
    )


def test_evidence_and_keyboard_focus_survive_real_revision(page):
    page.goto(page.base_url + "/network?focus=person:maya&claim=collab-maya")
    button = page.locator('[data-evidence="collab-maya"]')
    button.click()
    page.locator(".evidence-quote").wait_for()
    button.focus()
    page.request.post(page.base_url + "/network/demo/reset")
    page.get_by_text("Synthetic demo · Snapshot 2", exact=False).wait_for()
    page.locator(".evidence-quote").wait_for(timeout=3000)
    assert page.locator('[data-evidence="collab-maya"]').evaluate("(e)=>e===document.activeElement")


def test_neighborhood_focus_does_not_replace_origin_conversation(page):
    page.goto(page.base_url + "/inbox?focus=person:maya")
    page.get_by_role("link", name="Open full network").click()
    page.locator('[data-person="person:priya"]').click()
    page.get_by_role("button", name="Focus neighborhood").click()
    page.wait_for_url("**focus=person%3Apriya**")
    page.get_by_role("link", name="Return to conversation").click()
    page.get_by_role("link", name="Open full network").wait_for()
    assert page.locator(".detail-head").inner_text().startswith("MC\nMaya Chen")


def test_expand_searched_person_and_project_lens(page):
    page.goto(page.base_url + "/network?focus=person:sam&search=sam")
    page.get_by_role("button", name="Focus neighborhood").click()
    page.locator('[data-person="person:priya"]').wait_for()
    page.locator("#scope-organization").check()
    page.wait_for_url("**scopes=*organization**")
    page.get_by_label("Browse entities").select_option("project")
    page.locator('[data-context="project:harbour"]').click()
    page.get_by_role("heading", name="Work & follow-ups", exact=True).wait_for()
    page.get_by_text("Validate warehouse cost assumptions", exact=True).wait_for()
    assert "Overdue" in page.locator("#context-lens").inner_text()
    page.get_by_text("Source update", exact=True).first.click()
    page.locator("#context-lens .evidence-quote").wait_for()
    page.screenshot(path="tmp/network-project-lens.png", full_page=True)


def test_strategy_chat_carries_context_and_follow_up_history(page):
    import json

    received = []

    def answer(route):
        received.append(route.request.post_data_json)
        route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {
                    "summary": "Engineering evidence is adjacent; security expertise remains unverified.",
                    "findings": [
                        {
                            "text": "Amir lists Engineering.",
                            "entity_ids": ["person:amir"],
                            "evidence_ids": ["s1"],
                        }
                    ],
                    "gaps": [
                        "No verified adversarial AI testing experience in the retrieved evidence."
                    ],
                    "next_steps": ["Ask Amir whether he can help validate the technical scope."],
                    "clarification": "",
                    "evidence": [
                        {
                            "id": "s1",
                            "channel": "outlook",
                            "at": "2026-01-15T09:00:00Z",
                            "text": "My focus is Engineering. <script>bad()</script>",
                        }
                    ],
                    "entities": [{"id": "person:amir", "name": "Amir Khan"}],
                    "version": 1,
                    "model": "fake-test-provider",
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                    "trace": [
                        {"kind": "people", "terms": ["Engineering"], "entity_id": "person:owner"}
                    ],
                }
            ),
        )

    page.route("**/network/agent.json", answer)
    page.goto(page.base_url + "/network?focus=person:sam")
    page.get_by_role("button", name="Ask Claude about this person").click()
    page.get_by_label("Ask about a goal or this context").fill("Who can help with Cybertest?")
    page.get_by_role("button", name="Ask Claude", exact=True).click()
    page.get_by_text("What is not established yet", exact=True).wait_for()
    page.locator(".agent-finding summary").click()
    assert "<script>bad()</script>" in page.locator(".agent-finding blockquote").inner_text()
    assert page.locator(".agent-finding script").count() == 0
    assert received[0]["focus"] == "person:sam"
    page.get_by_label("Ask about a goal or this context").fill("What should I ask him first?")
    page.get_by_role("button", name="Ask Claude", exact=True).click()
    page.locator(".agent-turn").nth(1).get_by_text("Suggested next moves", exact=True).wait_for()
    assert len(received[1]["history"]) == 1
    assert "Cybertest" in received[1]["history"][0]["question"]
    page.get_by_role("button", name="Close assistant").click()
    assert page.locator(".network-assistant").count() == 0


def test_business_search_tags_evidence_and_graph_navigation(page):
    page.goto(page.base_url + "/inbox")
    page.get_by_role("link", name="Knowledge graph", exact=True).wait_for()
    maya = page.locator('.row[data-id="person:maya"]')
    assert maya.locator(".contact-tag").count() >= 2
    page.locator("#searchbar").click()
    page.get_by_role("textbox", name="Search your network").fill(
        "Find an accountant with logistics experience, preferably someone I worked with before"
    )
    page.get_by_role("button", name="Search", exact=True).click()
    page.get_by_text("2 matching contacts", exact=True).wait_for()
    first = page.locator(".discovery-result").first
    assert "Maya Chen" in first.inner_text()
    first.get_by_text("View matching evidence", exact=True).click()
    first.locator(".evidence-quote").first.wait_for()
    first.get_by_role("link", name="View in graph").click()
    page.get_by_role("heading", name="Your network", exact=True).wait_for()
    assert "focus=person%3Amaya" in page.url
    page.get_by_role("link", name="Return to conversation").click()
    page.locator(".contact-labels button").filter(has_text="Logistics").click()
    page.locator("#contact-tag-proof .evidence-quote").first.wait_for()


def test_inbox_list_labels_follow_historical_date(page):
    page.goto(page.base_url + "/inbox?as_of=2026-08-20T12:00:00Z")
    row = page.locator('.row[data-id="person:alex"]')
    row.wait_for()
    assert "Atlas Logistics" not in row.inner_text()
    assert "Northline Advisory" in row.inner_text()


def test_complex_search_handoff_and_sidebar_full_graph(page):
    page.goto(page.base_url + "/inbox")
    page.locator("#searchbar").click()
    page.get_by_role("textbox", name="Search your network").fill("Find accountants in Sydney")
    page.get_by_role("button", name="Search", exact=True).click()
    page.get_by_role("heading", name="Find people and opportunities", exact=True).wait_for()
    assert page.locator(".discovery-result").count() == 0
    page.get_by_role("button", name="Close assistant").click()
    page.get_by_role("link", name="Knowledge graph", exact=True).click()
    page.get_by_role("heading", name="Your network", exact=True).wait_for()
    assert (
        page.get_by_role("link", name="Knowledge graph", exact=True).get_attribute("aria-current")
        == "page"
    )
