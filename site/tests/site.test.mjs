import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const site = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = resolve(site, 'public');
const html = readFileSync(resolve(publicRoot, 'index.html'), 'utf8');
test('human first use leads to a concise offer without a checkout shortcut', () => {
  const journey = html.split('id="try-it"')[1].split('</section>')[0];
  assert.ok(journey.includes('Send in chat | What you receive'));
  assert.ok(journey.includes('<code>buyer explanation</code>'));
  assert.ok(journey.includes('<code>draft limited</code>'));
  assert.ok(journey.includes('new conversation'));
  assert.ok(!journey.includes('<code>check</code>'));
  assert.ok(journey.includes('manifest is not a complete document'));
  assert.ok(html.includes('href="#try-it">Try the drafting workflow'));
});
const css = readFileSync(resolve(publicRoot, 'styles.css'), 'utf8');
const headers = readFileSync(resolve(publicRoot, '_headers'), 'utf8');
const preview = JSON.parse(readFileSync(resolve(site, 'wrangler.jsonc'), 'utf8'));
const production = JSON.parse(readFileSync(resolve(site, 'wrangler.production.jsonc'), 'utf8'));
const agentProfile = 'https://agentverse.ai/agents/details/agent1qg0p9zy9rxqz83l5p8tr7vevguk3hny963luv4pd8nu8hp87qc0syk3c88a/profile';

test('website preserves the exact public position and trust boundaries', () => {
  assert.match(html, /<head>[\s\S]*?<meta http-equiv="Content-Security-Policy" content="[^"]*script-src https:\/\/tooloffer\.kinganlogic\.com\/\.webmcp\/bridge\.js; script-src-attr 'none'; connect-src 'self'/);
  assert.match(html, /<title>Tool Offer Agent \| Kingan Logic<\/title>/);
  assert.match(html, /Turn API and MCP documentation into <span>commercial offer drafts\.<\/span>/);
  assert.match(html, /Tool Offer Agent organizes public documentation, documented capabilities, seller-supplied terms and known limitations into source-attributed offers that can be reviewed, revised and exported\./);
  assert.match(html, /wallet-approved x402 checkout purchases one Diagnose evaluation/);
  assert.match(html, /Tool Offer Agent does not independently certify sellers/);
  assert.match(html, /not claims of external execution/);
  assert.doesNotMatch(html, /<script\b|analytics\.js|api[_-]?key\s*[:=]|BEGIN PRIVATE KEY/i);
});

test('buyer onboarding links to the same agent without collecting addresses or publishing a checkout', () => {
  assert.match(html, /href="#buying-wallet">buyer authorization and prerequisites/);
  assert.match(html, /id="buying-wallet"/);
  assert.match(html, /Chat with Agent/);
  assert.match(html, /<code>wallet<\/code>/);
  assert.match(html, /<code>purchase status<\/code>/);
  assert.match(html, /Connect wallet — no payment/);
  assert.match(html, /input-format blockers can still require operator help/);
  assert.match(html, /US-based buyers/);
  assert.match(html, /dedicated, authenticated US relay/);
  assert.match(html, /UK-origin server requests/);
  assert.match(html, /Relay location does not change buyer eligibility/);
  assert.doesNotMatch(html, /Gateway eligibility currently requires US-based buyers\./);
  assert.doesNotMatch(html, /<form\b|<input\b|#access=|\/checkout\//);
});

test('all internal links resolve and external links target verified public destinations', () => {
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));
  const destinations = [...html.matchAll(/\b(?:href|src)="([^"]+)"/g)].map((match) => match[1]);
  assert.ok(destinations.includes(agentProfile));
  assert.ok(destinations.includes('https://kinganlogic.com/'));
  for (const destination of destinations) {
    if (destination.startsWith('#')) assert.ok(ids.has(destination.slice(1)), destination);
    else if (destination.startsWith('/')) {
      const [pathname, fragment] = destination.split('#');
      assert.ok(existsSync(resolve(publicRoot, '.' + pathname)), destination);
      if (fragment) {
        const target = resolve(publicRoot, '.' + pathname, ...(pathname.endsWith('/') ? ['index.html'] : []));
        assert.ok(readFileSync(target, 'utf8').includes(`id="${fragment}"`), destination);
      }
    }
    else assert.ok([agentProfile, 'https://kinganlogic.com/', 'https://tooloffer.kinganlogic.com/', 'https://tooloffer.kinganlogic.com/manifest.json', 'https://tooloffer.kinganlogic.com/mcp', 'https://tooloffer.kinganlogic.com/openapi.json', 'https://developers.cloudflare.com/monetization-gateway/eligibility/', 'https://verifymcp.io/servers/com-kinganlogic-tool-offer-agent/tooloffer', 'https://verifymcp.io/badge/com-kinganlogic-tool-offer-agent/tooloffer.svg?variant=verified'].includes(destination), destination);
  }
  assert.ok(existsSync(resolve(publicRoot, '404.html')));
  assert.ok(existsSync(resolve(publicRoot, 'robots.txt')));
  assert.ok(existsSync(resolve(publicRoot, 'sitemap.xml')));
});

test('selected public assets match audited original SHA-256 values', () => {
  const hash = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');
  for (const [source, target] of [
    ['52a386b969dff7e6727839dd2dcbc88b309e054d44c8f58d172940a9d2604a67', 'tool-offer-banner.png'],
    ['aa849170c61b617fb47baa4ee7200a8100db4f11f7ebf5f005c5007e9ea11dd2', 'tool-offer-emblem.png'],
  ]) assert.equal(source, hash(resolve(publicRoot, 'assets', target)));
});

test('preview cannot attach a domain or invoke unrelated commercial custody', () => {
  assert.equal(preview.name, 'kingan-tooloffer-site');
  assert.equal(preview.assets.directory, './public');
  assert.equal(preview.assets.not_found_handling, '404-page');
  assert.equal(preview.main, 'src/worker.mjs');
  assert.equal(preview.routes, undefined);
  assert.deepEqual(preview.durable_objects, { bindings: [{ name: 'MACHINE_GATEWAY', class_name: 'MachineGateway' }] });
  assert.deepEqual(production.durable_objects, preview.durable_objects);
  assert.equal(preview.assets.binding, 'ASSETS');
  assert.deepEqual(preview.previews, {});
  assert.deepEqual(production.routes, [{ pattern: 'tooloffer.kinganlogic.com', custom_domain: true }]);
  assert.equal(production.preview_urls, true);
  assert.deepEqual(production.previews, {});
  assert.equal(production.assets.directory, preview.assets.directory);
  assert.equal(production.name, preview.name);
});

test('static content allows only the existing WebMCP bridge and same-origin connections', () => {
  assert.match(headers, /^\/\*\n/);
  assert.match(headers, /Content-Security-Policy: [^\n]*script-src https:\/\/tooloffer\.kinganlogic\.com\/\.webmcp\/bridge\.js; script-src-attr 'none'/);
  assert.match(headers, /connect-src 'self'/);
  assert.doesNotMatch(headers, /unsafe-inline|unsafe-eval|static\.cloudflareinsights\.com|script-src 'self'/);
  assert.match(headers, /Referrer-Policy: no-referrer/);
  assert.doesNotMatch(headers, /noindex/i);
});

test('responsive and accessibility fallbacks are present', () => {
  assert.match(html, /<html lang="en">/);
  assert.match(html, /class="skip-link" href="#main"/);
  assert.match(html, /<main id="main">/);
  assert.match(html, /<nav aria-label="Main navigation">/);
  assert.match(css, /@media\(max-width:680px\)/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(css, /:focus-visible/);
});

test('live VerifyMCP badge links to the report without a fixed score or security claim', () => {
  assert.match(html, /href="https:\/\/verifymcp.io\/servers\/com-kinganlogic-tool-offer-agent\/tooloffer"><img src="https:\/\/verifymcp.io\/badge\/com-kinganlogic-tool-offer-agent\/tooloffer.svg\?variant=verified" alt="VerifyMCP report for Tool Offer Agent\."/);
  assert.match(html, /not blanket security certification/);
  assert.match(headers, /img-src 'self' https:\/\/verifymcp.io\/badge\/com-kinganlogic-tool-offer-agent\/tooloffer.svg;/);
});
