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
