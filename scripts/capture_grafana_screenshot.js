#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const LOCAL_LIBS = path.resolve(__dirname, '..', '.cache', 'playwright-libs', 'usr', 'lib', 'x86_64-linux-gnu');
if (fs.existsSync(LOCAL_LIBS)) {
  process.env.LD_LIBRARY_PATH = LOCAL_LIBS + (process.env.LD_LIBRARY_PATH ? ':' + process.env.LD_LIBRARY_PATH : '');
}

const { chromium } = require('playwright');

const OUT_DIR = path.resolve(__dirname, '..', 'demo', 'assets', 'linkedin');
const OUT_FILE = path.join(OUT_DIR, '05_grafana.png');

const GRAFANA = process.env.GRAFANA_URL || 'http://localhost:3000';
const USER = process.env.GRAFANA_USER || 'admin';
const PASS = process.env.GRAFANA_PASS || '';
const DASHBOARD_UID = process.env.GRAFANA_DASH_UID || 'adkpn7r';
const DASHBOARD_SLUG = 'factory-oi-dashboard';

const BG = '#0B0E14';
const W = 1080;
const H = 1080;
const DPR = 2;

// Render the dashboard at native width so panel internals (table columns, axis labels)
// render with breathing room. Each panel is half-width = ~800px → all 5 table columns fit.
const RENDER_W = 1600;
const RENDER_H = 900;

const TIME_FROM = process.env.GRAFANA_FROM || 'now-1h';
const TIME_TO = process.env.GRAFANA_TO || 'now';

// Panel titles. Grafana 12 marks each panel with
// data-testid="data-testid Panel header <Title>" on the .panel-container <section>.
// We locate the enclosing .react-grid-item so the screenshot includes the full panel.
const PRESSURE_PANEL_TITLE = 'Hydraulic Press Pressure'; // top of stacked layout
const STATUS_PANEL_TITLE = 'Live Machine Status';        // bottom of stacked layout

async function preflight() {
  const res = await fetch(GRAFANA + '/api/health').catch((e) => ({ ok: false, error: e }));
  if (!res || !res.ok) {
    throw new Error('Grafana not reachable at ' + GRAFANA + ' — start the stack first.');
  }
}

async function capturePanel(page, title) {
  const header = page.locator(`section[data-testid="data-testid Panel header ${title}"]`).first();
  await header.waitFor({ state: 'visible', timeout: 15000 });
  // Walk up to the enclosing .react-grid-item so the screenshot includes header + body.
  const panelHandle = await header.evaluateHandle((el) => el.closest('.react-grid-item') || el);
  const panel = panelHandle.asElement();
  await panel.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  return await panel.screenshot({ type: 'png' });
}

async function composeStack(browser, topPng, bottomPng, outPath) {
  const topUri = 'data:image/png;base64,' + topPng.toString('base64');
  const botUri = 'data:image/png;base64,' + bottomPng.toString('base64');

  // Vertical stack with dark background. Each panel scaled to the canvas width with
  // matching gutters; gap between them keeps the two visually distinct without crowding.
  const sidePad = 20;
  const topPad = 24;
  const gap = 20;
  const bottomPad = 24;
  const imgW = W - sidePad * 2; // 1040
  const slotH = Math.floor((H - topPad - gap - bottomPad) / 2); // ~496

  const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:${BG};}
  body{width:${W}px;height:${H}px;overflow:hidden;font-family:-apple-system,sans-serif;}
  .stack{
    display:flex;flex-direction:column;align-items:center;justify-content:flex-start;
    padding:${topPad}px ${sidePad}px ${bottomPad}px ${sidePad}px;gap:${gap}px;
    width:${W}px;height:${H}px;box-sizing:border-box;
  }
  .frame{
    width:${imgW}px;height:${slotH}px;display:flex;align-items:center;justify-content:center;
    border-radius:6px;overflow:hidden;background:#181B22;
    box-shadow:0 6px 24px rgba(0,0,0,0.40);
  }
  .frame img{max-width:100%;max-height:100%;width:auto;height:auto;display:block;}
</style></head>
<body>
  <div class="stack">
    <div class="frame"><img src="${topUri}" alt="top"/></div>
    <div class="frame"><img src="${botUri}" alt="bottom"/></div>
  </div>
</body></html>`;

  const ctx = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: DPR,
  });
  const p = await ctx.newPage();
  await p.setContent(html, { waitUntil: 'load' });
  await p.waitForFunction(() => {
    const imgs = document.querySelectorAll('img');
    return imgs.length === 2 && Array.from(imgs).every((i) => i.complete && i.naturalWidth > 0);
  });
  await p.screenshot({ path: outPath, type: 'png', clip: { x: 0, y: 0, width: W, height: H } });
  await ctx.close();
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  console.log('Pre-flight: checking', GRAFANA);
  await preflight();
  console.log('Grafana reachable. Launching browser.');

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: RENDER_W, height: RENDER_H },
    deviceScaleFactor: DPR,
  });

  console.log('Logging in via API as', USER);
  const loginResp = await context.request.post(GRAFANA + '/login', {
    headers: { 'Content-Type': 'application/json' },
    data: { user: USER, password: PASS },
  });
  if (!loginResp.ok()) {
    throw new Error('Grafana login failed: HTTP ' + loginResp.status());
  }
  const cookies = await context.cookies();
  if (!cookies.find((c) => c.name === 'grafana_session')) {
    throw new Error('No grafana_session cookie set after login');
  }
  console.log('Authenticated; grafana_session cookie set.');

  const page = await context.newPage();
  const dashUrl = `${GRAFANA}/d/${DASHBOARD_UID}/${DASHBOARD_SLUG}?orgId=1&from=${TIME_FROM}&to=${TIME_TO}&kiosk`;
  console.log('Opening dashboard:', dashUrl);
  await page.goto(dashUrl, { waitUntil: 'networkidle', timeout: 45000 });

  console.log('Waiting 10s for panels to render…');
  await page.waitForTimeout(10000);

  console.log('Capturing top panel:', PRESSURE_PANEL_TITLE);
  const pressurePng = await capturePanel(page, PRESSURE_PANEL_TITLE);
  console.log('Capturing bottom panel:', STATUS_PANEL_TITLE);
  const statusPng = await capturePanel(page, STATUS_PANEL_TITLE);

  await composeStack(browser, pressurePng, statusPng, OUT_FILE);
  const stat = fs.statSync(OUT_FILE);
  console.log('→ wrote', OUT_FILE, '(' + Math.round(stat.size / 1024) + ' KB)');

  await browser.close();
  console.log('Done.');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
