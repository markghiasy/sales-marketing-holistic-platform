"""Capture the runnable demo and render its editable paper using local tools."""

import subprocess
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from scripts.network_demo import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    paper = root / "docs/papers/temporal-relationship-memory"
    figures = paper / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    server = make_server("127.0.0.1", 0, create_app(testing=True), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(
                viewport={"width": 1500, "height": 950}, device_scale_factor=1.5
            )
            base = f"http://127.0.0.1:{server.server_port}"
            page.goto(
                base + "/network?function=Accounting&project=project:harbour&focus=person:maya"
            )
            page.locator('[data-person="person:maya"]').wait_for()
            page.locator('[data-person="person:maya"]').click()
            page.get_by_role("button", name="View evidence").first.click()
            page.locator(".evidence-quote").first.wait_for()
            page.screenshot(path=str(figures / "explorer.png"))
            page.goto(base + "/inbox?focus=person:maya")
            page.locator(".embed-status").filter(has_text="entities").wait_for()
            page.locator(".network-embed").get_by_role("button", name="View evidence").first.click()
            page.locator(".evidence-quote").first.wait_for()
            page.screenshot(path=str(figures / "inbox.png"))
            subprocess.run(
                [
                    "pandoc",
                    "paper.md",
                    "--standalone",
                    "--embed-resources",
                    "--css=paper.css",
                    "-o",
                    "paper.html",
                ],
                cwd=paper,
                check=True,
            )
            page.goto((paper / "paper.html").as_uri())
            page.pdf(
                path=str(paper / "paper.pdf"),
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template='<div style="font-size:9px;width:100%;text-align:center;color:#6b7c89">Supervisor discussion draft &nbsp; | &nbsp; <span class="pageNumber"></span></div>',
                prefer_css_page_size=True,
            )
            browser.close()
    finally:
        server.shutdown()
    print(paper / "paper.pdf")


if __name__ == "__main__":
    main()
