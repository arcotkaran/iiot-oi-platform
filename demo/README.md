# demo — Interactive Showcase Site

A single-page portfolio site for the IIoT OI Platform, deployed via
GitHub Pages at **arcotkaran.github.io/iiot-oi-platform**.

## What's here

`index.html` — the entire site in one file. No build step, no dependencies
beyond Google Fonts. Sections:
1. **Hero** — project framing and key metadata
2. **Architecture** — animated SVG pipeline simulation with live stats
3. **Stack** — all 9 services with role descriptions
4. **Repository** — walkthrough of the folder structure
5. **Highlights** — what the project demonstrates beyond the tech

## Deployment

Automatic via GitHub Actions — any push to `main` triggers the workflow at
`.github/workflows/deploy-pages.yml`, which publishes this folder to
GitHub Pages.

## Design

Editorial aesthetic: Fraunces (serif headings), Inter Tight (body),
JetBrains Mono (labels/code). Warm off-white background (`#F7F5F0`)
with forest green accent (`#2D4A3E`). Designed to read well on desktop
and mobile.
