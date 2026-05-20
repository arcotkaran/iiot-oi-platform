#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const LOCAL_LIBS = path.resolve(__dirname, '..', '.cache', 'playwright-libs', 'usr', 'lib', 'x86_64-linux-gnu');
if (fs.existsSync(LOCAL_LIBS)) {
  process.env.LD_LIBRARY_PATH = LOCAL_LIBS + (process.env.LD_LIBRARY_PATH ? ':' + process.env.LD_LIBRARY_PATH : '');
}

const { chromium } = require('playwright');

const OUT_DIR = path.resolve(__dirname, '..', 'demo', 'assets', 'linkedin');
const URL = process.env.DEMO_URL || 'https://arcotkaran.github.io/iiot-oi-platform/';
const BG = '#F7F5F0';
const W = 1080;
const H = 1350;
const DPR = 2;

const RENDER_W = 1080;
const RENDER_H = 1400;

// preCapture: run before the screenshot to settle hover/animation state.
// clipFn: optional async (page) => page-coord clip rect, used instead of element.screenshot().
const targets = [
  {
    name: '01_hero.png',
    selector: 'header.hero',
    wait: 1500,
  },
  {
    name: '02_architecture.png',
    selector: '#architecture',
    wait: 30000,
    preCapture: async (page) => {
      // Dismiss any hover/tooltip state on the pipeline SVG.
      await page.mouse.move(2, 2);
      await page.evaluate(() => {
        for (const s of ['#pipeline-svg', '#architecture']) {
          const el = document.querySelector(s);
          if (!el) continue;
          ['mouseleave', 'mouseout'].forEach((t) => el.dispatchEvent(new MouseEvent(t, { bubbles: true })));
        }
        // Hide the static "ORCHESTRATOR · Airflow @hourly" ghosted badge sitting above the dbt block.
        // It's a <g> containing a <text>ORCHESTRATOR</text>; reads as a glitch in an isolated screenshot.
        const svg = document.querySelector('#pipeline-svg');
        if (svg) {
          svg.querySelectorAll('g').forEach((g) => {
            const t = g.querySelector('text');
            if (t && /ORCHESTRATOR/i.test(t.textContent)) {
              g.style.display = 'none';
            }
          });
        }
      });
      // Tiny scroll nudge to force redraw after DOM mutation.
      await page.evaluate(() => window.scrollBy(0, 4));
      await page.waitForTimeout(150);
      await page.evaluate(() => window.scrollBy(0, -4));
      await page.waitForTimeout(400);
    },
  },
  {
    name: '03_stack.png',
    selector: '#stack',
    wait: 1500,
    // The 2-col grid has an empty 10th cell next to the 9th (Python) item. The grid's
    // line-colour background shows through, reading as a missing card. Make Python span
    // both columns so there is no empty cell, then clip from section top → 9th item bottom.
    preCapture: async (page) => {
      await page.evaluate(() => {
        const items = document.querySelectorAll('#stack .stack-item');
        if (items.length) {
          items[items.length - 1].style.gridColumn = '1 / -1';
        }
      });
      await page.waitForTimeout(250);
    },
    clipFn: async (page) => {
      return await page.evaluate(() => {
        const section = document.querySelector('#stack');
        const items = section.querySelectorAll('.stack-item');
        const ninth = items[items.length - 1];
        const sRect = section.getBoundingClientRect();
        const nRect = ninth.getBoundingClientRect();
        const padBottom = 40;
        return {
          x: Math.max(0, Math.floor(sRect.left + window.scrollX)),
          y: Math.max(0, Math.floor(sRect.top + window.scrollY)),
          width: Math.ceil(sRect.width),
          height: Math.ceil((nRect.bottom + window.scrollY) - (sRect.top + window.scrollY) + padBottom),
        };
      });
    },
  },
  {
    name: '04_repository.png',
    selector: '#repo',
    wait: 1500,
  },
];

async function captureSection(page, target) {
  const loc = page.locator(target.selector).first();
  await loc.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -80));
  await page.waitForTimeout(target.wait);
  if (target.preCapture) {
    await target.preCapture(page);
  }
  if (target.clipFn) {
    const clip = await target.clipFn(page);
    return await page.screenshot({ type: 'png', fullPage: true, clip });
  }
  return await loc.screenshot({ type: 'png' });
}

async function composeOnCanvas(browser, sectionPng, outPath) {
  const dataUri = 'data:image/png;base64,' + sectionPng.toString('base64');
  const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:${BG};}
  body{width:${W}px;height:${H}px;display:flex;align-items:center;justify-content:center;overflow:hidden;}
  img{max-width:${W}px;max-height:${H}px;width:auto;height:auto;display:block;image-rendering:-webkit-optimize-contrast;}
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

function selectTargets() {
  const args = process.argv.slice(2).filter((a) => !a.startsWith('-'));
  if (args.length === 0) return targets;
  return targets.filter((t) => args.some((a) => t.name.startsWith(a) || t.name === a));
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const chosen = selectTargets();
  if (chosen.length === 0) {
    console.error('No targets matched arguments:', process.argv.slice(2).join(' '));
    process.exit(2);
  }
  console.log('Will capture:', chosen.map((t) => t.name).join(', '));

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: RENDER_W, height: RENDER_H },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  console.log('Loading', URL);
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1000);

  for (const t of chosen) {
    const waitNote = t.wait >= 5000 ? ' (will wait ' + Math.round(t.wait / 1000) + 's)' : '';
    console.log('Capturing', t.name, '(' + t.selector + ')' + waitNote);
    const sectionPng = await captureSection(page, t);
    const outPath = path.join(OUT_DIR, t.name);
    await composeOnCanvas(browser, sectionPng, outPath);
    const stat = fs.statSync(outPath);
    console.log('  → wrote', outPath, '(' + Math.round(stat.size / 1024) + ' KB)');
  }

  await browser.close();
  console.log('Done.');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
