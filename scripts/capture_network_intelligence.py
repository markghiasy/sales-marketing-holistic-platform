"""Capture the new views. Assistant capture replays a saved real API answer, without new API calls."""

import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from scripts.network_demo import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/demos"
    recorded = json.loads(
        (root / "docs/research/network-demo/agent-cybertest-live.json").read_text(encoding="utf-8")
    )
    server = make_server("127.0.0.1", 0, create_app(testing=True), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            base = f"http://127.0.0.1:{server.server_port}"
            page.goto(base + "/network?focus=person:sam&expand=person:sam&search=sam&depth=2")
            page.locator('[data-person="person:priya"]').wait_for()
            page.locator(".lens-context").first.wait_for()
            page.screenshot(path=str(output / "network-expansion.png"))
            page.get_by_label("Browse entities").select_option("project")
            page.locator('[data-context="project:harbour"]').click()
            page.get_by_text("Validate warehouse cost assumptions", exact=True).wait_for()
            page.locator("#inspector").evaluate("(el)=>el.scrollTop=0")
            page.screenshot(path=str(output / "network-project.png"))
            page.route(
                "**/network/agent/status.json",
                lambda route: route.fulfill(
                    json={
                        "configured": True,
                        "model": recorded["model"] + " (recorded live answer)",
                        "remaining": 20,
                    }
                ),
            )
            page.route("**/network/agent.json", lambda route: route.fulfill(json=recorded))
            page.goto(base + "/network")
            page.locator("[data-person]").first.wait_for()
            page.get_by_role("button", name="Ask your network", exact=True).click()
            page.get_by_label("Ask about a goal or this context").fill(
                "Who can help build Cybertest: authorized AI-agent security testing for vibe coding? What should I validate first?"
            )
            page.get_by_role("button", name="Ask Claude", exact=True).click()
            page.get_by_text("What is not established yet", exact=True).wait_for()
            page.locator(".agent-thread").evaluate("(el)=>el.scrollTop=0")
            page.screenshot(path=str(output / "network-assistant.png"))
            page.set_viewport_size({"width": 430, "height": 900})
            page.screenshot(path=str(output / "network-assistant-mobile.png"))
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
