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


def test_search_clarification_and_sidebar_full_graph(page):
    page.goto(page.base_url + "/inbox")
    page.locator("#searchbar").click()
    page.get_by_role("textbox", name="Search your network").fill("Find accountants in Sydney")
    page.get_by_role("button", name="Search", exact=True).click()
    page.get_by_text("Please clarify your search", exact=True).wait_for()
    assert page.locator(".discovery-result").count() == 0
    page.get_by_role("button", name="Close search").click()
    page.get_by_role("link", name="Knowledge graph", exact=True).click()
    page.get_by_role("heading", name="Your network", exact=True).wait_for()
    assert (
        page.get_by_role("link", name="Knowledge graph", exact=True).get_attribute("aria-current")
        == "page"
    )
