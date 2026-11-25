// E2E smoke without Playwright: headless Firefox driven over WebDriver BiDi (Node's built-in
// WebSocket, no npm dependencies, no browser download). Loads the Gazette from a running
// `sidereal serve`, then checks: the three section headings (TOP, Relevant, On the side), zero
// CSP violations (securitypolicyviolation events, recorded by a preload script) and zero
// console errors. Exit 0 = pass, 1 = check failed, 2 = setup problem.
//
// Usage: node web/e2e/smoke.mjs [url]   (default http://127.0.0.1:8472/)
// Env: FIREFOX (default /usr/bin/firefox), BIDI_PORT (default 9223), SMOKE_TIMEOUT_MS (20000).
// Normally run through web/e2e/run-smoke.sh, which starts a server on a temp demo DB.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const url = process.argv[2] ?? 'http://127.0.0.1:8472/';
const firefox = process.env.FIREFOX ?? '/usr/bin/firefox';
const port = Number(process.env.BIDI_PORT ?? 9223);
const timeoutMs = Number(process.env.SMOKE_TIMEOUT_MS ?? 20000);
const HEADINGS = ['TOP', 'Relevant', 'On the side'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), 'sidereal-smoke-'));
const browser = spawn(
  firefox,
  ['--headless', '--no-remote', '--profile', profile, `--remote-debugging-port=${port}`],
  { stdio: 'ignore' },
);

let ws;
let nextId = 1;
const pending = new Map();
const logErrors = [];

function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject, method }));
}

async function connect() {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const sock = new WebSocket(`ws://127.0.0.1:${port}/session`);
      await new Promise((resolve, reject) => {
        sock.onopen = resolve;
        sock.onerror = () => reject(new Error('connect failed'));
      });
      return sock;
    } catch {
      await sleep(250);
    }
  }
  throw new Error(`no WebDriver BiDi endpoint on port ${port}`);
}

function onMessage(event) {
  const msg = JSON.parse(event.data);
  if (msg.id !== undefined && pending.has(msg.id)) {
    const { resolve, reject, method } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.type === 'error') reject(new Error(`${method}: ${msg.error} ${msg.message ?? ''}`));
    else resolve(msg.result);
  } else if (msg.method === 'log.entryAdded' && msg.params.level === 'error') {
    logErrors.push(msg.params.text);
  }
}

async function evaluate(context, expression) {
  const res = await send('script.evaluate', {
    expression, target: { context }, awaitPromise: false, resultOwnership: 'none',
  });
  if (res.type === 'exception') throw new Error(`evaluate: ${res.exceptionDetails.text}`);
  return res.result;
}

async function main() {
  ws = await connect();
  ws.onmessage = onMessage;
  await send('session.new', { capabilities: {} });
  await send('session.subscribe', { events: ['log.entryAdded'] });
  // Runs in the page before its own scripts; BiDi scripts are not subject to the page's CSP.
  await send('script.addPreloadScript', {
    functionDeclaration: `() => {
      window.__csp = [];
      document.addEventListener('securitypolicyviolation', (e) => {
        window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || 'inline'));
      });
    }`,
  });
  const tree = await send('browsingContext.getTree', {});
  const context = tree.contexts[0].context;
  await send('browsingContext.navigate', { context, url, wait: 'complete' });

  const deadline = Date.now() + timeoutMs;
  let headings = [];
  while (Date.now() < deadline) {
    const r = await evaluate(context,
      `JSON.stringify([...document.querySelectorAll('h2.bucket-title')]
        .map((h) => h.firstChild ? h.firstChild.textContent.trim() : ''))`);
    headings = JSON.parse(r.value);
    if (headings.length >= HEADINGS.length) break;
    await sleep(200);
  }
  await sleep(300); // let late console/CSP events arrive
  const csp = JSON.parse((await evaluate(context, 'JSON.stringify(window.__csp || [])')).value);

  const failures = [];
  if (JSON.stringify(headings) !== JSON.stringify(HEADINGS)) {
    failures.push(`section headings ${JSON.stringify(headings)} != ${JSON.stringify(HEADINGS)}`);
  }
  if (csp.length) failures.push(`CSP violations: ${csp.join('; ')}`);
  if (logErrors.length) failures.push(`console errors: ${logErrors.join(' | ')}`);
  if (failures.length) {
    for (const f of failures) console.error(`FAIL ${f}`);
    return 1;
  }
  console.log(`ok: ${url} sections ${headings.join(' / ')}, 0 CSP violations, 0 console errors`);
  return 0;
}

let code = 2;
try {
  code = await main();
} catch (e) {
  console.error(`smoke setup error: ${e.message}`);
} finally {
  try { ws?.close(); } catch { /* ignore */ }
  browser.kill('SIGTERM');
  await sleep(500);
  if (browser.exitCode === null) browser.kill('SIGKILL');
  rmSync(profile, { recursive: true, force: true });
}
process.exit(code);
