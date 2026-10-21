// Browser smoke test against a running stack with the demo seed. Never run against production.
// usage: E2E_PASSWORD=<demo password> BASE_URL=http://localhost:3000 node e2e/smoke.cjs
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const OUT = process.env.OUT || '/tmp';
const BASE = process.env.BASE_URL || 'http://localhost:3000';
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', (e) => errors.push('PAGEERROR ' + e.message));
  p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
  let failed = 0;
  const ok = (name, cond) => { if (!cond) failed += 1; console.log((cond ? 'PASS ' : 'FAIL ') + name); };
  // unauthenticated redirect
  await p.goto(BASE + '/ndr?queue=urgent');
  ok('redirects to login with next', p.url().includes('/login?next=%2Fndr'));
  await p.fill('input[type=email]', 'ops.lead@demo.zippyy.test');
  await p.fill('input[autocomplete=current-password]', 'wrong-password');
  await p.click('button[type=submit]');
  await p.waitForSelector('form [role=alert]');
  ok('bad password shows error', (await p.textContent('form [role=alert]')).includes('incorrect'));
  await p.fill('input[autocomplete=current-password]', process.env.E2E_PASSWORD);
  await p.click('button[type=submit]');
  await p.waitForURL('**/ndr?queue=urgent');
  ok('returns to requested page', true);
  await p.waitForSelector('tbody tr');
  const urgentRows = await p.locator('tbody tr').count();
  // filter by carrier via URL
  await p.goto(BASE + '/ndr?queue=all&carrier=FASTSHIP');
  await p.waitForSelector('tbody tr');
  const carriers = await p.locator('tbody tr td:nth-child(6)').allTextContents();
  ok(`carrier filter (${carriers.length} rows, urgent ${urgentRows})`, carriers.every((c) => c.includes('FastShip')));
  // search
  await p.goto(BASE + '/ndr?queue=all'); await p.waitForSelector('tbody tr');
  await p.fill('input[placeholder*="Case, order"]', 'NDR-Z2CGWJ');
  await p.waitForFunction(() => document.querySelectorAll('tbody tr').length === 1, null, { timeout: 8000 }).catch(() => {});
  ok('search narrows to one case', (await p.locator('tbody tr').count()) === 1 && p.url().includes('q=NDR-Z2CGWJ'));
  // case page: conversation + agent inspector tabs
  await p.click('tbody tr');
  await p.waitForURL('**/ndr/*');
  await p.click('role=tab[name=/Conversation/]');
  await p.waitForSelector('text=Voice call');
  ok('conversation tab shows calls', true);
  await p.click('role=tab[name=/Agent inspector/]');
  await p.waitForSelector('text=sanitized');
  await p.screenshot({ path: OUT + '/flow_case_agent.png', fullPage: true });
  ok('agent inspector loads', true);
  // escalate dialog validation
  await p.click('button:has-text("Escalate")');
  ok('escalate disabled until summary', await p.locator('role=dialog >> button:has-text("Escalate")').isDisabled());
  await p.keyboard.press('Escape');
  // transcript (audited)
  await p.goto(BASE + '/calls?switched=true');
  await p.waitForSelector('tbody tr');
  await p.click('tbody tr');
  await p.click('button:has-text("Open transcript")');
  await p.waitForSelector('text=Switched');
  await p.screenshot({ path: OUT + '/flow_transcript.png', fullPage: true });
  ok('transcript shows language switch', true);
  // policy dry run (ops lead is read-only) -> check read-only
  await p.goto(BASE + '/agent-config');
  await p.waitForSelector('text=Read only for your role');
  ok('ops lead cannot edit agent config', await p.locator('role=switch').first().isDisabled());
  // workspace switch is listed
  await p.click('button[aria-haspopup=listbox]');
  const ws = await p.locator('role=option').count();
  ok(`workspace menu lists ${ws} workspaces`, ws >= 1);
  await p.keyboard.press('Escape');
  // mobile
  await p.setViewportSize({ width: 390, height: 844 });
  await p.goto(BASE + '/ndr');
  await p.waitForSelector('tbody tr');
  await p.screenshot({ path: OUT + '/flow_mobile_ndr.png' });
  await p.click('button[aria-label="Open navigation"]');
  await p.waitForTimeout(300);
  await p.screenshot({ path: OUT + '/flow_mobile_nav.png' });
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  ok('no horizontal page scroll on mobile', !overflow);
  console.log('ERRORS', JSON.stringify(errors));
  await b.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.log('CRASH', e.message); process.exit(1); });
