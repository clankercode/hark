# Hark static site

Marketing / docs landing for [ultradyn/hark](https://github.com/ultradyn/hark).

## Design system

| File | Role |
|------|------|
| `css/tokens.css` | Colors, type, space, radii — **edit first** |
| `css/base.css` | Reset, body, atmosphere |
| `css/components.css` | Buttons, cards, terminal, flow, nav, verse |
| `css/layout.css` | Hero, grids, sections |
| `js/main.js` | Nav scroll (+ optional `#wave` canvas) |
| `index.html` | Single-page composition; hero RHS = SVG architecture diagram |

Change brand colors or type scale in **tokens only**; components consume `var(--…)`.

**Product links:** wrap partner names (e.g. Herdr) in
`<a class="product-link" href="https://herdr.dev/">Herdr</a>` so they inherit local
text color and underline cleanly in body, eyebrow, and verse.

**Performance:** system font stacks only (no Google Fonts), static SVG diagram (no
canvas loop), minimal CSS/JS. Prefer editing tokens over adding dependencies.

## Open Graph / Twitter card

Source of truth: **`og-image.html`** (fixed 1200×630). Rendered PNG: **`og.png`**.

Uses the skill stack under `~/.llm-general/skills/`:

1. **`og-social-previews`** — card design + meta workflow  
2. **`headless-browser-screenshots`** — Playwright render  
3. **`visual-review-and-fix`** — vision/geometry polish before ship  

```bash
# From repo root
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
node "$HOME/.llm-general/skills/headless-browser-screenshots/scripts/screenshot.mjs" \
  --url site/og-image.html \
  --out site/og.png \
  --width 1200 --height 630
```

`index.html` points `og:image` / `twitter:image` at `https://hark.xk.io/og.png`.
Do not screenshot the live homepage for social previews — edit the HTML card and re-render.

## Local preview

```bash
cd site && python3 -m http.server 8765
# open http://127.0.0.1:8765
```

## Deploy

GitHub Actions (`.github/workflows/pages.yml`) publishes the site on **version tags only**
(`v*`, same cadence as npm releases). The artifact is:

- contents of `site/`
- plus root **`install.sh`** → served as **https://hark.xk.io/install.sh**

So the bash one-liner always matches the tagged release tree. Manual redeploy:
Actions → “Deploy site to GitHub Pages” → Run workflow.

Enable Pages → Source: **GitHub Actions** in repo settings if needed.
