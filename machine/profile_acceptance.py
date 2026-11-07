"""Verify the public Agentverse profile without an authenticated ASI session."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def verify(output, executable):
    root = Path(__file__).resolve().parents[1]
    contract = json.loads((root / 'machine/contract.json').read_text())
    profile = (root / 'AGENT-PROFILE.txt').read_text()
    output.mkdir(parents=True, exist_ok=True)
    url = 'https://agentverse.ai/agents/details/' + contract['agent_address'] + '/profile'
    evidence = {'checked_at': datetime.now(timezone.utc).isoformat(), 'url': url,
                'authenticated_asi_rendering': False, 'profile_characters': len(profile), 'viewports': []}
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=executable, args=['--no-sandbox'])
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            page = context.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
            assert response.status == 200
            heading = page.get_by_role('heading', name='Tool Offer Agent — from API docs to a buyer offer', exact=True)
            heading.wait_for(state='visible', timeout=45000)
            necessary = page.get_by_role('button', name='Only necessary cookies', exact=True)
            if necessary.is_visible():
                necessary.click()
            body = page.locator('body').inner_text()
            assert 'Try it — no checkout or wallet' in body
            assert 'Send in chat' in body and 'What you receive' in body
            assert 'buyer explanation' in body and 'fresh card' in body
            assert 'JSON intake in chat' in body and 'message string' in body
            assert page.locator('table').count() >= 1
            table = page.locator('table').first
            table.scroll_into_view_if_needed()
            assert table.is_visible()
            table_screenshot = 'agentverse-table-' + str(width) + '.png'
            page.screenshot(path=str(output / table_screenshot), full_page=True)
            badges = []
            for category in ('innovationlab', 'hackathon'):
                image = page.locator('img[alt="tag:' + category + '"]')
                image.scroll_into_view_if_needed()
                page.wait_for_function('(element) => element.complete && element.naturalWidth > 0', arg=image.element_handle())
                assert image.evaluate('(element) => { const headings = [...document.querySelectorAll("h1,h2,h3")]; const title = headings.find(node => node.textContent === "Tool Offer Agent — from API docs to a buyer offer"); const intro = [...document.querySelectorAll("p")].find(node => node.textContent.startsWith("By Kingan Logic")); return !!title && !!intro && !!(title.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING) && !!(element.compareDocumentPosition(intro) & Node.DOCUMENT_POSITION_FOLLOWING); }')
                badges.append({'category': category, 'rendered': True, 'source': image.get_attribute('src')})
            badge_screenshot = 'agentverse-badges-' + str(width) + '.png'
            page.screenshot(path=str(output / badge_screenshot), full_page=True)
            links = page.locator('a').evaluate_all('links => [...new Set(links.map(link => link.href))]')
            assert not any('/api/machine/' in link for link in links), 'REST request templates must not be navigation links'
            destinations = [link for link in links if link.startswith(contract['origin']) or link.startswith('https://innovationlab.fetch.ai/events/hackathons/stranger-builds-1/hackpack')]
            checked = []
            for destination in destinations:
                result = context.request.get(destination, timeout=45000)
                protocol_endpoint = destination.rstrip('/') == contract['origin'] + '/mcp'
                assert result.status == (405 if protocol_endpoint else 200), (destination, result.status)
                if protocol_endpoint:
                    assert result.headers.get('allow') == 'POST'
                    assert result.json()['documentation'] == contract['origin'] + '/machine/'
                checked.append({'requested': destination, 'final_url': result.url, 'status': result.status})
            heading.scroll_into_view_if_needed()
            screenshot = 'agentverse-' + str(width) + '.png'
            page.screenshot(path=str(output / screenshot), full_page=True)
            evidence['viewports'].append({'width': width, 'title': page.title(), 'table_rendered': True,
                                         'badges': badges, 'links': checked, 'screenshot': screenshot,
                                         'table_screenshot': table_screenshot, 'badge_screenshot': badge_screenshot,
                                         'platform_verified_label_visible': 'Verified' in body})
            context.close()
        browser.close()
    evidence['passed'] = True
    (output / 'profile-acceptance.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'passed': True, 'viewports': len(evidence['viewports']), 'profile_characters': len(profile)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--chromium', required=True)
    arguments = parser.parse_args()
    verify(arguments.output, arguments.chromium)
