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
const PASS = process.env.GRAFANA_PASS || 'Yash1313';
const DASHBOARD_UID = process.env.GRAFANA_DASH_UID || 'adkpn7r';
const DASHBOARD_SLUG = 'factory-oi-dashboard';

// Square aspect for the carousel slide — landscape dashboards fit a 1:1 frame more tightly than 4:5.
const BG = '#0B0E14';
const W = 1080;
const H = 1080;
const DPR = 2;

// Narrow render viewport pushes the 2×2 panel grid closer to square (panel heights are
// fixed by the dashboard config, so narrower viewport = less landscape capture aspect).
// 1000px is the best balance: dashboard fills ~63% of the square canvas while the table
// still shows the primary columns (machine_id, status, fault).
const RENDER_W = 1000;
const RENDER_H = 850;

// Dashboard time range. The dbt hourly-aggregation panel needs at least one hourly bucket
// to be in range, so 30 min is too short — 3h gives the dbt panel a real trendline while
// still keeping the live timeseries panels visually dense (~10k rows per machine).
const TIME_FROM = process.env.GRAFANA_FROM || 'now-1h';
const TIME_TO = process.env.GRAFANA_TO || 'now';

async function preflight() {
  const res = await fetch(GRAFANA + '/api/health').catch((e) => ({ ok: false, error: e }));
  if (!res || !res.ok) {
    throw new Error('Grafana not reachable at ' + GRAFANA + ' — start the stack first.');
  }
}

async function composeOnCanvas(browser, sectionPng, outPath) {
  const dataUri = 'data:image/png;base64,' + sectionPng.toString('base64');
  const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:${BG};}
  body{width:${W}px;height:${H}px;display:flex;align-items:flex-start;justify-content:center;overflow:hidden;padding-top:40px;box-sizing:border-box;}
  img{max-width:${W - 32}px;max-height:${H - 80}px;width:auto;height:auto;display:block;border-radius:6px;box-shadow:0 8px 28px rgba(0,0,0,0.45);}
</style></head>
<body><img src="${dataUri}"/></body></html>`;

  const ctx = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: DPR,
  });
  const p = await ctx.newPage();
  await p.setContent(html, { waitUntil: 'load' });
  await p.waitForFunction(() => {
    const img = document.querySelector('img');
    return img && img.complete && img.naturalWidth > 0;
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

  // Union bounding box of all visible panels, in page coords.
  const tightClip = await page.evaluate(() => {
    const sels = [
      '[data-panelid]',
      '[data-testid^="data-testid Panel"]',
      '.panel-container',
      '.react-grid-item',
    ];
    const panels = [];
    for (const s of sels) {
      document.querySelectorAll(s).forEach((el) => panels.push(el));
    }
    if (!panels.length) return null;
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    for (const el of panels) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      l = Math.min(l, rect.left + window.scrollX);
      t = Math.min(t, rect.top + window.scrollY);
      r = Math.max(r, rect.right + window.scrollX);
      b = Math.max(b, rect.bottom + window.scrollY);
    }
    if (!isFinite(l)) return null;
    const pad = 8;
    return {
      x: Math.max(0, Math.floor(l - pad)),
      y: Math.max(0, Math.floor(t - pad)),
      width: Math.ceil(r - l + pad * 2),
      height: Math.ceil(b - t + pad * 2),
    };
  });

  let dashPng;
  if (tightClip) {
    console.log('Tight panel bounds:', tightClip);
    dashPng = await page.screenshot({ type: 'png', fullPage: true, clip: tightClip });
    console.log('Captured panels (tight crop).');
  } else {
    const target = page.locator('.react-grid-layout').first();
    await target.scrollIntoViewIfNeeded({ timeout: 5000 });
    dashPng = await target.screenshot({ type: 'png' });
    console.log('Captured dashboard grid element (fallback).');
  }

  await composeOnCanvas(browser, dashPng, OUT_FILE);
  const stat = fs.statSync(OUT_FILE);
  console.log('→ wrote', OUT_FILE, '(' + Math.round(stat.size / 1024) + ' KB)');

  await browser.close();
  console.log('Done.');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
