"""Relationship scope browser contracts against the real local demo API."""

import threading
from urllib.parse import parse_qs, urlsplit

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


def params(page):
    return parse_qs(urlsplit(page.url).query, keep_blank_values=True)


def test_scope_controls_replace_distance_and_preserve_legacy_dates(page):
    page.goto(page.base_url + "/network?focus=person:maya&expand=person:maya&depth=3&min_activity=60&mode=history&as_of=2026-09-25T12%3A00%3A00Z")
    expect(page.get_by_label("Direct interaction", exact=True)).to_be_checked()
    expect(page.get_by_label("Collaboration or introduction", exact=True)).to_be_checked()
    expect(page.get_by_label("Shared project or team", exact=True)).not_to_be_checked()
    expect(page.get_by_label("Shared organization or company", exact=True)).not_to_be_checked()
    assert "depth" not in params(page)
    assert "min_activity" not in params(page)
    assert params(page)["mode"] == ["history"]
    assert params(page)["as_of"] == ["2026-09-25T12:00:00Z"]
    assert page.get_by_text("Graph distance", exact=False).count() == 0
    page.get_by_role("button", name="Expand more", exact=True).click()
    expect(page.get_by_label("Shared project or team", exact=True)).to_be_checked()
    page.get_by_role("button", name="Expand more", exact=True).click()
    expect(page.get_by_role("button", name="Expand more", exact=True)).to_be_disabled()
    page.get_by_label("Relationship event window", exact=True).select_option("90")
    page.get_by_label("Order people", exact=True).select_option("name")
    page.reload()
    expect(page.get_by_label("Relationship event window", exact=True)).to_have_value("90")
    expect(page.get_by_label("Order people", exact=True)).to_have_value("name")
    expect(page.locator("#scope-note")).to_contain_text("shared", ignore_case=True)


def test_no_scopes_is_focus_only_and_mobile_keyboard_controls_work(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(page.base_url + "/network?focus=person:maya&expand=person:maya&scopes=")
    expect(page.locator("#scope-direct")).not_to_be_checked()
    expect(page.locator("#people-count")).to_have_text("0")
    expect(page.locator("#scope-empty")).to_be_visible()
    page.locator("#scope-direct").focus()
    page.keyboard.press("Space")
    expect(page.locator("#scope-direct")).to_be_checked()
    page.wait_for_url("**scopes=direct&**")
    assert page.locator("#expansion-controls").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth")
    assert not errors


def test_scope_paths_use_real_sources_and_unknown_pair_metrics(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    query = "focus=person:maya&origin=person:maya&expand=person:maya&scopes=direct,explicit,project,organization&mode=history&scope_window=90&scope_sort=name&search=NoSuchName"
    payload = page.request.get(page.base_url + "/network/graph.json?" + query).json()
    alex = next(p for p in payload["ranked_contacts"] if p["id"] == "person:alex")
    assert set(alex["relationship_scope"]["scopes"]) == {"project", "organization"}
    assert alex["relationship_scope"]["interaction"]["sessions"] is None
    page.goto(page.base_url + "/network?" + query)
    row = page.locator('[data-person="person:alex"]')
    expect(row.locator("[data-scope]")).to_have_count(2)
    expect(row).to_contain_text("No recorded relationship event")
    assert page.locator("#people .activity-line").count() == 0
    expect(page.locator('[name="search"]')).to_be_disabled()
    row.click()
    expect(page.locator(".relationship-details dd").first).to_have_text("Unknown")
    path = page.locator(".scope-path").first
    path.locator("summary").click()
    expect(path.locator(".scope-path-nodes")).to_have_text("Maya Chen → Harbour expansion → Alex Morgan")
    expect(path.locator(".claim-item")).to_have_count(2)
    path.get_by_role("button", name="View evidence").first.click()
    expect(path.locator(".evidence-quote").first).to_be_visible()
    page.locator("#inspector").evaluate("e => e.scrollTop = 0")
    page.screenshot(path="tmp/network-scopes-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.locator("body").evaluate("e => e.scrollWidth <= innerWidth")
    page.screenshot(path="tmp/network-scopes-mobile.png", full_page=True)
    page.get_by_role("link", name="Return to conversation", exact=True).click()
    page.get_by_role("link", name="Open full network", exact=True).click()
    expect(page.locator("#scope-window")).to_have_value("90")
    expect(page.locator("#scope-sort")).to_have_value("name")
    expect(page.locator("#scope-organization")).to_be_checked()
    assert params(page)["mode"] == ["history"]
    assert not errors


@pytest.mark.parametrize("lens,entity,scope", [("project", "project:harbour", "project"), ("organization", "org:north", "organization")])
def test_context_focus_automatically_selects_its_scope(page, lens, entity, scope):
    page.goto(page.base_url + "/network?mode=history")
    page.locator("#entity-lens").select_option(lens)
    page.locator(f'[data-context="{entity}"]').click()
    expect(page.locator(f"#scope-{scope}")).to_be_checked()
    expect(page.locator("#entity-lens")).to_have_value("person")
    assert params(page)["scopes"] == [scope]
    assert params(page)["focus"] == [entity]
    expect(page.locator("#people .person-row").first).to_be_visible()


def test_unconfirmed_scope_paths_stay_separate_from_confirmed_contact(page):
    page.goto(page.base_url + "/network?focus=person:owner&expand=person:owner&scopes=direct,explicit&include_pending=true&mode=history")
    row = page.locator('[data-person="person:nora"]')
    expect(row).to_contain_text("Includes unconfirmed path")
    row.click()
    expect(page.locator(".unconfirmed-paths")).to_contain_text("do not establish an introduction or willingness")
    expect(page.locator(".unconfirmed-paths .scope-path").first).to_contain_text("Unconfirmed")
    page.locator("#hypotheses").uncheck()
    expect(page.locator(".unconfirmed-paths")).to_have_count(0)
