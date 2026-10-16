# Zippyy design system (extracted from zippyy.ai)

Source: `https://zippyy.ai` homepage, analysed 2026-10-16 (HTML, the LiteSpeed CSS bundle and
14 inline `<style>` blocks). This file records the theme, tokens and every recurring layout /
component pattern so they can be rebuilt in our own frontend. The reference implementation lives
in `frontend/app/site/` and is served at `/site`.

> Copy and imagery on zippyy.ai belong to their owner. This document lists the asset URLs and what
> each one is used for; it does not vendor them. Run `scripts/fetch-zippyy-assets.sh` only if you
> own or are licensed to use them — it downloads into `frontend/public/brand/` (git-ignored).

---

## 1. Tech stack behind the page

| Layer | What zippyy.ai uses |
|---|---|
| CMS | WordPress 6.9 |
| Theme | Astra (globals `--ast-global-color-0…8`, container 1200px) |
| Page builder | Elementor 3.34 (flex containers `e-con`), Royal Elementor Addons (`wpr-*`) |
| CSS framework | Bootstrap 5.3 (header/nav, grid, dropdowns) |
| Icons | Font Awesome 7, Bootstrap Icons 1.11, Elementor `eicons` |
| Perf | LiteSpeed Cache (bundled CSS/JS, delayed JS), Smush lazyload (`data-src`, SVG placeholders) |
| Analytics | Google Analytics 4 (gtag) |
| Popups | external `popup.js` (brochure / case-study popups) |

Our rebuild drops all of that for Next.js 14 + Tailwind 3 with no extra runtime dependencies.

---

## 2. Theme

**Dark-first, single-accent brand.** Sections alternate between near-black (`#121212`/`#1E1E1E`)
and off-white (`#FAFAFA`). One warm accent — **Zippyy red `#D54029`** — carries every active
state, CTA and highlight. Depth comes from a red radial glow, faint line ornaments and soft
shadows rather than many colours.

### 2.1 Colour tokens

| Token | Hex | Where it is used |
|---|---|---|
| `brand` | `#D54029` | CTA fill, active nav link, active tab border + title, link hover, spinner, glow |
| `ink` | `#121212` | Header, dark sections, dark headings on light |
| `ink-2` | `#1E1E1E` | "Platform hub" section background |
| `ink-3` | `#2E2E2E` | Body text on light, inactive tab border on light |
| `paper` | `#FAFAFA` | Light section background, inactive tab border on dark |
| `paper-2` | `#F5F5F5` | Dropdown item hover, testimonial page background |
| `white` | `#FFFFFF` | Text on dark, cards, dropdown panels |
| `muted` | `#9E9E9E` | Dropdown descriptions, eyebrow labels, slider arrow idle |
| `muted-warm` | `#BAA0A0` | CTA sub-copy on dark (Manrope) |
| `link` | `#0C77FF` | Inline "open brochure" / "case study" links (weight 600) |
| `star` | `#FF8C00` | Testimonial rating stars |
| text greys | `#666` / `#555` | Testimonial role / body |

Astra leftovers that appear in global CSS but not in the visual design: `#046BD2`, `#045CB4`,
`#1E293B`, `#334155`, `#F0F5FA`, `#D1D5DB`. A stray tablet-only active colour `#EF4277` also exists
in the warehouse tabs — treat it as a bug and use `brand`.

### 2.2 Gradients, glows, ornaments

```css
/* footer bottom bar */
background: linear-gradient(90deg, #D54029 0%, #121212 100%);

/* red glow blob behind the CTA (500×500, bottom-left, z-index -1) */
background: radial-gradient(circle,
  rgba(213,64,41,.55) 0%, rgba(213,64,41,.35) 25%, rgba(213,64,41,.11) 50%, transparent 75%);
```

Dark sections also layer a low-contrast line ornament image (`Ornament-57.png`, `footer-line*.svg`)
on top of the colour; the hero uses a full-bleed photo with a 0.5 overlay.

### 2.3 Typography

| Role | Family | Size / line-height | Weight |
|---|---|---|---|
| All headings `h1–h6`, nav, footer menu | **Lato** | — | — |
| Body paragraphs | **Inter** | 16 / 26 | 400 |
| CTA sub-copy | **Manrope** | 15 / 20 | 400 |
| Hero H2 | Lato | 48 / 76 (mobile 36 / 1.5em) | 600 |
| Section H2 | Lato | 48 (mobile 26–28 / 1.5em) | 600–700 |
| Tab title | Lato | 24 idle → 22 bold when active | 500 → 700 |
| Tab body | Inter | 15 / 1.4–1.5 | 400 |
| Stat number | Lato | 37 | 600 |
| Stat label | Roboto/Inter | 13 | 400 |
| Nav link | Lato | 16 | 500 (active 700) |
| Button | Inter | 15–16 | 500 |
| Dropdown title / desc / eyebrow | Lato 14/500 · Inter 12/400 · 12/600 uppercase | | |
| Footer column title / link | Lato 21/700 · 14/400 | | |

Google Fonts: Lato (100–900), Inter (variable 100–900), Manrope (200–800).

### 2.4 Shape, elevation, motion

| Token | Value |
|---|---|
| Button radius | 5–6px |
| Dropdown / menu radius | 16px (10px mobile), item 10px |
| Card radius | 12–14px |
| Avatar / social / slider arrow | 50% |
| Dropdown shadow | `0 24px 56px 0 #A7AEBA29` |
| Small menu shadow | `0 7px 29px 0 rgba(100,100,111,.2)` |
| Card shadow | `0 5px 20px rgba(0,0,0,.07)` |
| Link/span transition | `all .5s` |
| Tab transition | `.3s ease` + `fadeIn .3s` for body |
| Mockup animation | `float` 4s ease-in-out infinite, `translateY(0 → -20px → 0)` |
| Logo strip | Elementor image carousel, 5 per view (3 mobile), autoplay |

### 2.5 Layout & spacing

* Container: `max-width: 1320px`, side padding 24px (Bootstrap container) — Astra content 1200px.
* Header: fixed, full-width, `padding: 0 60px`, background `ink`; nav gap 20px; nav starts 80px after logo; logo 120px wide.
* Section rhythm: 100px top/bottom on desktop (60px for split tab sections), 60px side padding;
  mobile drops to 20–40px vertical, 10–20px side.
* Grid gutter 32px (16px half), footer grid `column-gap 48px / row-gap 40px`.
* Breakpoints used: 1800, 1400, 1200, 1024, 991/992, 768/767, 600, 576, 480.

---

## 3. Page anatomy (homepage, top → bottom)

| # | Section | Background | Pattern |
|---|---|---|---|
| 1 | Header | `ink` | Fixed bar · logo · 5 nav items (Solutions mega-menu, Resources, Partners, Pricing, About) · outline "Track order" + filled "Login now" |
| 2 | Hero | photo + 50% overlay | Two-column: H2 + paragraph + red button left; floating product illustration right |
| 3 | Client logos | `paper` | Centered H2 + 5-up auto-scrolling logo carousel (two rows) |
| 4 | Story | `paper` | Long-form H2 + two Inter paragraphs |
| 5 | Transportation platform | dark | **Vertical tabs, left rail** (3 tabs) + swapping floating mockup on the right |
| 6 | 3PL platform | `paper` | **Mirrored vertical tabs, right rail, right-aligned text** + mockup on the left |
| 7 | Sectors | `ink` + ornament | Centered white H2 + one wide industries illustration |
| 8 | Testimonials | `paper` | H2 + 3-up card slider (2 at ≤992, 1 at ≤600) + round arrow buttons |
| 9 | Platform hub | `ink-2` + ornament | Centered H2 + one wide diagram |
| 10 | Advantage | `paper` | H2 + 4 staggered image cards (different bottom offsets 94–112px) |
| 11 | Stats | `paper` | H2 left + 5 stat blocks in a row (number 37px / label 13px) |
| 12 | CTA | `ink` + cta.svg + red glow | Centered 48px H2, Manrope sub-copy, two red buttons with icons |
| 13 | Footer | `ink` + line ornament | Logo · 4 link columns · social circles; bottom bar with red→black gradient, copyright + policy links |

---

## 4. Component patterns

### 4.1 Buttons
* **Filled** — `bg brand`, white text, radius 6, padding `11px 39px`, Inter 15/500.
  Hover inverts: `bg white`, `text brand` (icon recoloured to brand with a CSS filter).
* **Outline (on dark)** — transparent, `1px solid #fff`, white text, same padding/radius.
* **Text link** — `link` blue, weight 600 (brochure / case-study popups).

### 4.2 Header & mega-menu
* Bootstrap dropdowns; the "Solutions" menu is full-width (max 1200px, 24px padding) and lays
  out 3 columns of items, each with an uppercase grey **eyebrow** (12/600 `muted`).
* Each item: 24px icon + title (14/500 `ink`) + description (12/400 `muted`), padding 10px,
  radius 10px, max-width 350px.
* Icons are greyed with `filter: brightness(0) … invert(68%)` and return to full colour on hover.
  Hover: item bg `paper-2`, title turns `brand`.
* Panel: white, radius 16, big soft shadow, a 14px rotated white square as the caret.
* Mobile (≤991): menu stacks, descriptions and carets hidden, groups become accordions
  (`max-height 0 → 1000px`, 300ms).

### 4.3 Vertical tabs with swapping visual (signature pattern)
```
┌────────────────────────────┬──────────────────────────────┐
│ H2 (48/1.3, bold)          │                              │
│ ▌Tab A  ← 2px brand rail   │   mockup for active tab      │
│ │ description (fade in)    │   (float 4s infinite)        │
│ │Tab B  ← 2px paper rail   │                              │
│ │Tab C                     │                              │
└────────────────────────────┴──────────────────────────────┘
```
* `li` padding `15px 20px`, margin-bottom 15px, 2px left border.
* Idle title 24/500; active/hover title 22/700 in `brand`; only active tab shows its description.
* Clicking a tab swaps the image (`display:none` ↔ `.active`, opacity transition).
* **Mirrored variant** on light background: rail on the right (`#2E2E2E` idle), text right-aligned,
  image column on the left. ≤1024px both stack (text centred, image below/above).

### 4.4 Logo carousel
Five logos per view, grey-on-light, auto-play; reuse as a CSS marquee.

### 4.5 Testimonial card
White, radius 14, padding 25, shadow `0 5px 20px rgba(0,0,0,.07)`; profile row (55px round
avatar, name 17/700, role 14 `#666`), quote 14/1.6 `#555`, stars `#FF8C00` pinned to the bottom.
Arrows: 42px circles, 2px `muted` border → `ink-3` on hover/active.

### 4.6 Stat block
Big number (Lato 37/600, black) over a small label (13px). Five in a row, wraps on mobile.

### 4.7 CTA band
Centered column, 48/58 Lato 600 capitalised headline, Manrope 15px `muted-warm` copy (max 300px),
two filled buttons (gap 20px), red radial glow anchored bottom-left, decorative circle on the right.
Padding 133px desktop.

### 4.8 Footer
Columns with Lato 21/700 titles, 14px white links (hover `brand`), 12px row gap. Social icons in
40px circles with `1px rgba(255,255,255,.3)` border → white border + 10% white bg on hover.
Bottom bar uses the red→black gradient, 14px text.

---

## 5. Asset manifest

All under `https://zippyy.ai/wp-content/uploads/`. Largest size variant listed; WP also serves
`-300x…`, `-768x…`, `-1024x…`, `-1536x…` versions.

| File | Kind | Role |
|---|---|---|
| `2025/11/logo-1.svg` | SVG | Header logo (white) |
| `2025/11/logo.svg` | SVG | Footer logo |
| `2025/12/cropped-Favicon-24px-size-{32,180,192,270}…jpg` | JPG | Favicon / touch icons |
| `2025/11/4f835bcd-e4a3-4541-b37e-fbb3a616f6c7-2.jpeg` | JPG | Hero background photo |
| `2025/11/Group-1321314881.svg` | SVG | Hero illustration, og:image |
| `2025/11/menufirst-1.svg`, `header-menu-icon{1–6,8–12}-1.svg`, `2025/12/Delivery-notification-icon-1.svg`, `2025/12/Vector.svg` | SVG | Solutions mega-menu icons (13) |
| `2025/11/resorce-icon{1,2,3}-1.svg` | SVG | Resources menu icons |
| `2026/02/hand_package_24dp…svg`, `2026/02/handshake_24dp…svg` | SVG | Partners menu icons |
| `2025/11/about-icon{1–5}-1.svg` | SVG | About menu icons |
| `2025/11/image-6-1.png`, `image-96-1`, `image-97-1`, `image-102`, `image-103`, `image-104`, `image-106-1`, `image-107-1.png`, `tiremarketlogo-1-1.png`, `kayura_effect_llp_logo_1-removebg-preview-1-1.png` | PNG | Client logo carousel |
| `2025/11/Group-1321314902-1-scaled.png`, `Frame-1618873407-scaled.png`, `Frame-1618873408.png` | PNG | Transportation tab mockups 1–3 |
| `2025/11/Customer-2.png`, `IMG-20251127-WA0012.jpg`, `IMG-20251127-WA0011.jpg` | PNG/JPG | 3PL tab mockups 1–3 |
| `2025/12/Group-1321314964.png` | PNG | Sectors illustration |
| `2025/12/Frame-32.png` | PNG | Testimonial avatar placeholder |
| `2025/11/Frame-1618873295-2.png` | PNG | Platform hub diagram |
| `2025/11/Frame-1511128813-9.png`, `Frame-1511128814-10.png`, `Frame-1511128815-10.png`, `Frame-1511128816-7.png` | PNG | Advantage cards |
| `2025/11/Ornament-57.png`, `footer-line.svg`, `footer-line-1.svg` | PNG/SVG | Dark-section ornaments |
| `2025/11/cta.svg`, `footer-side-circle.svg` | SVG | CTA background + side circle |

---

## 6. Rebuild mapping (`frontend/`)

| Pattern | Implementation |
|---|---|
| Tokens | `tailwind.config.ts` → `colors.zy.*`, `fontFamily.{heading,body,accent}`, `boxShadow.zy-*`, `animation.float/marquee/fade-in` |
| Fonts | `<link>` to Google Fonts in `app/site/layout.tsx` |
| Header + mega-menu | `app/site/components/SiteHeader.tsx` (client; hover/click dropdown, mobile accordion) |
| Vertical tabs (+ mirrored) | `app/site/components/FeatureTabs.tsx` (`side="left" \| "right"`) |
| Logo marquee, testimonials, stats, CTA, footer | `app/site/components/*.tsx` |
| Buttons | `app/site/components/Button.tsx` (`filled` / `outline`) |
| Page | `app/site/page.tsx` |

Images are swapped for drawn placeholders (`MockPanel`) so the page renders without the
third-party assets; drop files into `public/brand/` and pass `src` to use real ones.
