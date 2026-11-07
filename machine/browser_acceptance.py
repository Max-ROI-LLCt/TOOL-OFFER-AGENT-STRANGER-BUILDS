"""Exercise the public site in Chromium without signing in or calling a model."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def verify(origin, output, executable):
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"origin": origin, "checked_at": datetime.now(timezone.utc).isoformat(), "pages": [],
                "native_asi_one_conversation": "not_exercised_no_authenticated_browser_session",
                "model_calls": 0, "payment_calls": 0}
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=executable, args=["--no-sandbox"])
        for width in (1440, 390):
            context = browser.new_context(viewport={"width": width, "height": 1000})
            page = context.new_page()
            for route in ("/", "/machine/", "/examples/"):
                response = page.goto(origin + route, wait_until="networkidle")
                assert response.status == 200, (route, response.status)
                assert "text/html" in response.headers["content-type"]
                page.locator("h1").wait_for(state="visible")
                body = page.locator("body").inner_text()
                if route == '/':
                    badge = page.get_by_alt_text('VerifyMCP report for Tool Offer Agent.', exact=True)
                    badge.scroll_into_view_if_needed()
                    page.wait_for_function('(image) => image.complete && image.naturalWidth > 0', arg=badge.element_handle())
                    assert badge.get_attribute('src') == 'https://verifymcp.io/badge/com-kinganlogic-tool-offer-agent/tooloffer.svg?variant=verified'
                    assert badge.locator('..').get_attribute('href') == 'https://verifymcp.io/servers/com-kinganlogic-tool-offer-agent/tooloffer'
                    evidence['verifymcp_badge_loaded'] = True
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (route, width, "horizontal overflow")
                if route == "/":
                    journey = page.locator('#try-it').inner_text()
                    assert 'buyer explanation' in journey and 'draft limited' in journey and 'new conversation' in journey
                    assert page.locator('#try-it caption').inner_text() == 'Send in chat | What you receive'
                    assert 'fresh card' in journey and 'not approval or purchase' in journey
                    assert page.locator('a[href="#try-it"]').first.is_visible()
                if route == "/machine/":
                    assert "private_key_jwt" in body and "500" in body and "5,000" in body
                    assert "without a human enrollment queue" in body
                if route == "/examples/":
                    assert "Inputs" in body and "Outputs" in body and "USD" in body
                    assert "pending_configuration" not in body
                    assert "application/json: {" not in body
                    assert page.locator('a[href="/examples/quickstart.json"]').count()
                local_links = set(page.locator('a[href^="/"]').evaluate_all("links => links.map(link => link.getAttribute('href').split('#')[0])"))
                for link in local_links:
                    result = context.request.get(origin + link)
                    assert result.status == 200, (route, link, result.status)
                image = (route.strip("/") or "home") + f"-{width}.png"
                page.screenshot(path=str(output / image), full_page=True)
                evidence["pages"].append({"route": route, "width": width, "status": response.status,
                    "title": page.title(), "heading": page.locator("h1").inner_text(),
                    "horizontal_overflow": False, "internal_links_checked": len(local_links), "screenshot": image,
                    "release_id": response.headers.get("x-tool-offer-release"),
                    "content_security_policy": response.headers.get("content-security-policy")})
            denied = context.request.post(origin + "/api/machine/start_session", data={"request_id": "00000000-0000-4000-8000-000000000001"})
            assert denied.status == 401
            context.add_cookies([{"name": "machine_token", "value": "not-a-bearer-credential", "url": origin}])
            denied_cookie = context.request.post(origin + "/api/machine/start_session", data={"request_id": "00000000-0000-4000-8000-000000000001"})
            assert denied_cookie.status == 401
            context.close()
        browser.close()
    evidence["anonymous_and_cookie_only_protected_calls"] = "rejected_401"
    (output / "browser-acceptance.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"pages": len(evidence["pages"]), "result": "passed", "evidence": str(output / "browser-acceptance.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--chromium", required=True)
    options = parser.parse_args()
    verify(options.origin.rstrip("/"), options.output, options.chromium)
