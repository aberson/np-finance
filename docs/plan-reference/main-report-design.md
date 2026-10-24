# Main Report Set — one-page summary design

Status: DONE (Step 64, 2026-10-23; 96a57a5, follow-up 38efe36). This is the visual contract the shipped `render.py` and templates implement; where a row cap or label below differs from the code, the code constants win (see the as-built notes). Operator decisions are in §7.
Owner of the visual contract for the four `end-to-end-run` summaries and the index. The data
contract stays with [`cfo-main-report-set.md`](cfo-main-report-set.md); this document never
changes a fact, a total or a reconciliation rule, only how they are shown.

## 0. Why and what

`end-to-end-run` renders four summaries (`reimbursement-summary`, `budget-snapshot`,
`fundraising-summary`, `cfo-pnl-summary`) and the index `main-report-set.html` from
`pta_finance/main_reports/render.py` and `pta_finance/reports/templates/main_reports/*.j2`.
Before Step 64 each summary was a fluid audit dump that printed to 42–95 pages. Most of the
height comes from inline lists of discrepancy IDs, per-row bridge evidence, findings tables
and per-cell "Not covered" markers.

The operator has accepted a family of **one-page portrait board briefs**, built privately
outside this repo. This spec describes their visual system in public terms, with fictional
values only, and maps every element to the existing facts model. A developer who has never
seen the private briefs can implement it from this document alone.

Target per page:

| Page | Printed result |
|---|---|
| Reimbursement Summary | exactly 1 US Letter portrait page |
| Fundraising Summary | exactly 1 US Letter portrait page |
| Budget Snapshot | exactly 1 US Letter portrait page |
| CFO P&L Summary | 1 portrait brief page + a landscape appendix (1 page for ≤ 40 matrix body rows) |
| Index `main-report-set.html` | a short link page, at most 2 portrait pages |

Identity rule: the templates use only `page.organization` / `page.logo` (already read from
the bundle's private settings) for identity. No organization, person, sponsor or logo is
committed. Examples below use **Example PTA** and fictional amounts.

---

## 1. Shared design system

### 1.1 Page box and print rules

* Screen: a fixed `.sheet` 8.5 in wide (816 CSS px), `min-height:11in`, padding `.43in .45in`,
  centred on a `#e9efed` page wash with a soft shadow. Content width is therefore
  **729.6 px** (7.6 in), the same on screen and in print.
* Print: US Letter portrait, margins `.43in .45in`. The printable content box is
  **729.6 × 973.4 px** (`(11 − 0.86) in × 96`). Inside `@media print` the sheet loses its
  width, min-height, padding and shadow, so the `@page` margin is the only margin.
* The CFO P&L appendix uses a **named landscape page**:
  `@page wide{size:letter landscape;margin:.4in}` and `.appendix{page:wide;break-before:page}`.
  This was checked against the Chromium bundled with the pinned Playwright: one HTML
  document produced page 1 at 612 × 792 pt and page 2 at 792 × 612 pt with
  `prefer_css_page_size=True`. The existing `export.py` call (`page.pdf(print_background=True,
  prefer_css_page_size=True)`) needs no change.
* The `@page` rule moves from `base.html.j2` (`@page{size:…;margin:.4in}` outside media) into
  the stylesheet's `@media print` block. The `{% block page_size %}` block is removed;
  `cfo-pnl-summary.html.j2` no longer declares `letter landscape` for the whole document.
* Light only. Print forces the light tokens and `print-color-adjust:exact`.
* `export.VIEWPORT_WIDTH` stays 1100: the PNG is a full-page capture of the 816 px sheet
  centred on the wash, exactly like the accepted references (which were captured at 1100).

### 1.2 Tokens and stylesheet

Replace `style.css.j2` with the following (the colour values are the ones the current
stylesheet already uses; `--muted` is added for small text because `--ink-3` fails 4.5:1 on
white). Class names are part of the contract: tests select on them.

```css
:root{--ink:#20323f;--ink-2:#475d69;--ink-3:#71838d;--muted:#637881;--paper:#fff;--page:#e9efed;
--wash:#f4f8f7;--line:#ccd9d6;--deep:#123f4a;--sea:#147d83;--sun:#edb528;
--go:#236c48;--go-line:#80b797;--go-tint:#edf8f1;--clr:#8a5716;--clr-line:#d7ad68;--clr-tint:#fff7e7;
--stop:#922f38;--stop-line:#d5a2a8;--stop-tint:#fff1f2;color-scheme:light}
*{box-sizing:border-box}
html{background:var(--page);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px;line-height:1.4;-webkit-text-size-adjust:100%}
body{margin:0;padding:24px;background:var(--page)}
.sheet{width:8.5in;min-height:11in;margin:0 auto;padding:.43in .45in;background:var(--paper);box-shadow:0 8px 28px #1a394317}
h1,h2,h3,p,figure{margin:0}h1,h2,h3{color:var(--deep)}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
.mono{font-family:ui-monospace,"Cascadia Code",Consolas,monospace;font-size:.95em;overflow-wrap:break-word}
/* masthead */
.mast{display:grid;grid-template-columns:61px 1fr auto;gap:13px;align-items:center;padding-bottom:13px;border-bottom:5px solid var(--sun)}
.logo{width:61px;height:61px;object-fit:contain}
.brandmark{width:61px;height:61px;border-radius:50%;display:grid;place-items:center;background:var(--deep);color:#fff;font-size:22px;font-weight:800}
.eyebrow{font-size:9.7px;letter-spacing:.105em;text-transform:uppercase;color:var(--sea);font-weight:800}
h1{font-size:26px;line-height:1.1;margin:4px 0 5px;letter-spacing:-.5px}
.audience{font-size:11px;color:var(--ink-2)}
.edition{text-align:right;align-self:start;padding-top:3px;font-size:10px;color:var(--muted);line-height:1.6;white-space:nowrap}
.scope{font-size:10.5px;color:var(--muted);margin:9px 0 12px}
/* KPI tiles */
.metrics{display:grid;grid-template-columns:1fr 1fr 1fr 1.4fr;gap:8px}
.metric{border:1px solid var(--line);background:var(--wash);padding:9px 11px;min-width:0}
.metric strong{font-size:25px;line-height:1.05;letter-spacing:-.6px;display:block;color:var(--deep);font-variant-numeric:tabular-nums;white-space:nowrap}
.metric span{display:block;margin-top:5px;font-size:10px;font-weight:700;color:var(--ink-2)}
.metric small{display:block;margin-top:2px;font-size:9px;font-weight:600;color:var(--muted)}
.metric.closed{background:var(--go-tint);border-left:3px solid var(--go-line)}.metric.closed strong{color:var(--go)}
.metric.open,.metric.amount{background:var(--clr-tint);border-left:3px solid var(--clr-line)}.metric.open strong,.metric.amount strong{color:var(--clr)}
.metric.spent{background:var(--stop-tint);border-left:3px solid var(--stop-line)}.metric.spent strong{color:var(--stop)}
/* overview row: chart panel + callout */
.overview{display:grid;grid-template-columns:1.05fr 1fr;gap:16px;margin-top:15px;align-items:stretch}
.progress{display:grid;grid-template-columns:145px 1fr;gap:6px;align-items:center}
.pie{display:block;width:145px;height:145px}
.chart-copy h2,.panel h2{font-size:14px;line-height:1.22;margin-bottom:9px}
.legend{display:flex;align-items:center;gap:7px;font-size:11.5px;margin:5px 0}
.swatch{width:9px;height:9px;display:inline-block;border-radius:2px;flex:none}
.chart-note{font-size:9.5px;line-height:1.35;color:var(--muted);margin-top:8px}
.callout{background:var(--wash);border:1px solid var(--line);padding:12px 15px;display:flex;flex-direction:column;justify-content:center}
.callout h2{font-size:11px;color:var(--sea)}
.callout .value{font-size:27px;font-weight:850;color:var(--deep);letter-spacing:-.5px;line-height:1.12;margin-top:5px;font-variant-numeric:tabular-nums}
.callout .value span{font-size:11px;font-weight:600;color:var(--ink-2);letter-spacing:0}
.callout .split{font-size:11px;color:var(--ink-2);margin-top:6px}
.callout .note{font-size:9.5px;color:var(--muted);margin-top:5px;line-height:1.3}
/* bar rows (one common scale) and stacked bar */
.bars{background:var(--wash);border:1px solid var(--line);padding:8px 13px}
.bars-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.bars-head h2{font-size:11px;color:var(--sea)}.bars-head span{font-size:9.5px;color:var(--ink-2);white-space:nowrap}
.bars .sub{font-size:9.5px;line-height:1.3;color:var(--ink-2);margin:1px 0 4px}
.route{display:grid;grid-template-columns:128px 1fr 92px;align-items:center;gap:6px;font-size:10.5px;line-height:1.25}
.route .bar{display:block;height:10px;background:var(--sea);border-radius:0 4px 4px 0}
.route .val{color:var(--ink);white-space:nowrap;text-align:right;font-variant-numeric:tabular-nums}
.stack{display:flex;height:14px;border:1px solid var(--line);background:var(--wash);margin:6px 0 8px}
.stack span{display:block;height:100%}
.cat{display:grid;grid-template-columns:12px 1fr 78px 40px;gap:6px;align-items:center;font-size:10.5px;line-height:1.3;padding:2px 0}
.cat .amt,.cat .pct{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.cat .pct{color:var(--muted)}
.meter{display:block;width:100%;height:auto}
/* sections and tables */
.section{margin-top:12px}
.section-heading{display:flex;align-items:baseline;justify-content:space-between;border-left:4px solid var(--sea);padding-left:9px;margin-bottom:6px}
.section-heading h2{font-size:15px;line-height:1.2}.section-heading span{font-size:9.5px;color:var(--muted)}
table{width:100%;border-collapse:collapse;border:1px solid var(--line);table-layout:fixed}
th{background:var(--deep);color:#fff;text-align:left;padding:5px 8px;font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;font-weight:700}
td{padding:4px 8px;border-top:1px solid var(--line);vertical-align:top;font-size:10.5px;line-height:1.28;overflow-wrap:break-word}
tbody tr:nth-child(even){background:var(--wash)}
th.amt,td.amt{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td strong{display:block;color:var(--deep);font-size:10.8px}
td .meta{display:block;font-size:9.5px;color:var(--ink-2)}
tr.total td{font-weight:800;color:var(--deep);border-top:2px solid var(--line)}
tr.other td{color:var(--ink-2);font-style:italic}
.unk{color:var(--muted);font-weight:400}
.zero{color:var(--muted)}
.partial::after{content:"*";color:var(--clr);font-weight:800;margin-left:1px}
.chip{display:inline-block;padding:1px 7px;border-radius:999px;font-size:9.5px;font-weight:800;letter-spacing:.04em;white-space:nowrap;border:1px solid var(--line);background:var(--wash);color:var(--ink-2)}
.chip.ok{color:var(--go);background:var(--go-tint);border-color:var(--go-line)}
.chip.warn{color:var(--clr);background:var(--clr-tint);border-color:var(--clr-line)}
.chip.stop{color:var(--stop);background:var(--stop-tint);border-color:var(--stop-line)}
a.ref{font-size:9.5px;color:var(--muted);white-space:nowrap;text-decoration:underline;text-underline-offset:2px}
/* follow-ups, narrative, audit, footer */
.followups{display:grid;grid-template-columns:1fr 1fr;gap:0 18px;border-top:1px solid var(--line)}
.followup{padding:7px 0;border-bottom:1px solid var(--line);font-size:11px;line-height:1.4;break-inside:avoid}
.followup strong{color:var(--deep);font-size:11.3px}.followup p{margin-top:2px;color:var(--ink-2);font-size:10.5px}
.narrative{margin-top:12px;border-left:4px solid var(--sun);padding:8px 12px;background:var(--wash);font-size:11.5px;line-height:1.45}
.narrative h2{font-size:12px;display:inline;margin-right:6px}.narrative p{display:inline}
.audit{margin-top:8px;font-size:9.5px;line-height:1.35;color:var(--muted)}
.audit .warn{color:var(--clr);font-weight:700}
.foot{margin-top:10px;border-top:1px solid var(--line);padding-top:7px;font-size:9px;line-height:1.45;color:var(--muted)}
.foot .row{display:flex;justify-content:space-between;gap:15px}
.foot .row>span:last-child{white-space:nowrap;text-align:right}
.foot .id{white-space:nowrap;overflow-wrap:normal}
.foot a{text-decoration:underline;text-underline-offset:2px}
.private{font-weight:850;color:var(--stop)}
/* P&L appendix */
.appendix .tablewrap{overflow-x:auto}
table.pnl{table-layout:fixed}
table.pnl th,table.pnl td{padding:2px 4px;font-size:9.5px;line-height:1.2}
table.pnl th:first-child,table.pnl td:first-child{width:21%;text-align:left}
table.pnl tr.group td{background:var(--deep);color:#fff;font-weight:800;text-transform:uppercase;letter-spacing:.06em}
/* index */
.reports{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
.report{border:1px solid var(--line);border-top:4px solid var(--sea);padding:9px 11px;min-width:0}
.report h3{font-size:13px}.report p{font-size:10.5px;color:var(--ink-2);margin-top:3px}
.report .links{margin-top:6px;font-size:11px;display:flex;gap:10px;flex-wrap:wrap}.report .links a{color:var(--sea);text-decoration:underline}
@media(max-width:700px){
  body{padding:0}.sheet{width:100%;min-height:0;padding:20px 16px;box-shadow:none}
  .mast{grid-template-columns:48px 1fr;gap:10px}.logo,.brandmark{width:48px;height:48px}h1{font-size:23px}
  .edition{grid-column:1/-1;text-align:left;padding:0}
  .metrics{grid-template-columns:1fr 1fr}.overview{grid-template-columns:1fr}
  .followups{grid-template-columns:1fr}.section-heading{flex-wrap:wrap;row-gap:2px}
  .route{grid-template-columns:42% 1fr 76px}
  th:first-child{width:35%}td{padding:4px 6px}
  .foot .row{display:block}.foot .row>span{display:block;margin-top:4px;text-align:left}.foot .id{white-space:normal;overflow-wrap:anywhere}
  .appendix .tablewrap{overflow-x:auto}table.pnl{min-width:760px}
  table.pnl th:first-child,table.pnl td:first-child{position:sticky;left:0;background:var(--paper)}
}
@media print{
  @page{size:letter portrait;margin:.43in .45in}
  @page wide{size:letter landscape;margin:.4in}
  :root{color-scheme:light}
  *{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}
  html,body{background:#fff}body{padding:0}
  .sheet{width:auto;min-height:0;max-width:none;margin:0;padding:0;box-shadow:none}
  .appendix{page:wide;break-before:page}
  .mast,.metrics,.overview,.narrative,.followup,.bars,.callout,tr{break-inside:avoid}
  h1,h2,h3,.section-heading{break-after:avoid}thead{display:table-header-group}
  .appendix .tablewrap{overflow:visible}a{text-decoration:none!important}
}
```

Deliberate deviations from the private references (both are needed by existing tests):
`th` is 9.5 px (reference 9 px) so the existing readability floor test
(`td, th, p, li` ≥ 9.5 px) keeps passing, and brief tables use the reference's denser
`table.fund` metrics (padding 4 × 8, 10.5 px) for every table, so a row with a one-line label
plus one meta line stays ≤ 38 px.

Categorical palette (bars, stacked bar, swatches), in rank order, never more than five:
`#147d83` (sea), `#71838d` (ink-3), `#edb528` (sun), `#8a5716` (clr), then `#ccd9d6` (line)
for the "Other" remainder. Green (`--go`) is reserved for "done/received" states and is
never a category colour. Amber bold is never repeated per cell.

### 1.3 Typography scale

| Use | Size / weight | Colour |
|---|---|---|
| Root | 13 px / 1.4 | ink |
| H1 (report title) | 26 px, 700, −0.5 px tracking | deep |
| KPI value | 25 px, 700, tabular | deep / state colour |
| Callout value | 27 px, 850 | deep |
| H2 section | 15 px | deep |
| Panel H2 | 14 px (chart), 11 px (callout/bars head, sea) | |
| Body, tables | 10.5–11.5 px | ink |
| Meta, notes, legends | 9.5–10 px | ink-2 / muted |
| Footer | 9 px (spans only, never `p`/`td`/`li`) | muted |

Every `td`, `th`, `p` and `li` is ≥ 9.5 px. SVG text uses the sizes given in § 1.7.

### 1.4 Masthead and scope line (all pages)

```html
<header class="mast">
  <!-- unchanged mark slot: page.logo data URI if configured, else the $ brandmark -->
  <div>
    <p class="eyebrow">{{ page.eyebrow }} · Private Main Report Set</p>
    <h1>{{ page.title }}</h1>
    <p class="audience">For the board</p>
  </div>
  <div class="edition">As of {{ page.as_of }}</div>
</header>
<p class="scope"><strong>{{ page.period.label }} · {{ page.period.range }} · through {{ page.period.through }}</strong>{% if page.period.legacy %} · {{ page.period.legacy }}{% endif %} · {{ page.basis }}</p>
```

* No metadata cards, run ID, hash, basis box or alert boxes above the content.
* `page.eyebrow` is `page.organization` cut with an ellipsis to one line (the full name stays in `title`).
* `page.basis` becomes one short clause (replace `_BASES` in `render.py`):
  reimbursement "items by their own expense date; payments by payment date";
  budget "adopted targets beside the adjusted bank view";
  fundraising "processor activity by payment date; the bank view is shown separately";
  P&L "adjusted bank view by bank date; internal transfers excluded".
* The P&L scope line appends one more clause: "no adjustments recorded; figures equal the CFO
  workbook" when `report.applied_adjustments` is empty, else "{n} adjustment(s) applied".
* Example: `School year 2030–31 · July 1, 2030 to June 30, 2031 · through August 15, 2030 ·
  FY2031 · adopted targets beside the adjusted bank view`.

### 1.5 KPI tile row

Exactly four `.metric` tiles in `.metrics` (`1fr 1fr 1fr 1.4fr`), 65–80 px tall. Each tile:
`<div class="metric {state}"><strong>{value}</strong><span>{label}</span>[<small>{note}</small>]</div>`.
States: `closed` (green: done/received), `open`/`amount` (amber: open or needs attention),
`spent` (red tint: money out), none (neutral wash). Values are whole dollars, counts or
whole percents. A value that is unknown is the word `Unknown` (never `$0`); a partial value
carries `class="partial"` on the `strong` (renders `*`); a non-numeric value (`Unknown`, `Target reached`) gets `class="word"` (17 px).

### 1.6 Overview row

Two columns (`1.05fr 1fr`, 16 px gap): left column 365.6 px, right 348 px at print width.
Left: a chart panel (pie, meter, stacked bar or monthly bars, § 1.7) with a 14 px heading and
a 9.5 px `.chart-note`. Right: a `.callout` (one 27 px headline value, a `.split` line of 1–2
lines, a `.note` of ≤ 3 lines) or a `.bars` panel. Height ≤ 165 px.

### 1.7 Charts (inline SVG or CSS, no script, no images)

All charts are deterministic functions of the facts; colours are literal hex in SVG
attributes (no CSS variables inside SVG). Each SVG has `role="img"`,
`aria-labelledby="{id}-title {id}-desc"`, a `<title>` and a `<desc>` stating the plotted
numbers in words.

**Pie (two-part share)** — reference geometry, displayed at 145 × 145:
`viewBox="0 0 160 160"`; base `<circle cx="80" cy="80" r="68">` filled `#147d83` when the
first part > 0, else `#edb528`; the second part is a wedge from 12 o'clock clockwise:
`M 80 80 L 80 12 A 68 68 0 {large} 1 {x} {y} Z` with
`angle = −π/2 + 2π·part/total`, `x = 80 + 68·cos(angle)`, `y = 80 + 68·sin(angle)`
(4 decimals), `large = 1 if part/total > 0.5 else 0`, `fill="#edb528" stroke="#fff"
stroke-width="2.5" stroke-linejoin="round"`. No wedge when the part is 0 or equals total.
Percent shown = half-up whole percent of the first part; the second is `100 − first`.

**Meter (amount toward a target, with a time marker)** — `viewBox="0 0 365 50"`, width 100%:
track `<rect x="0" y="15" width="365" height="14" rx="4" fill="#ccd9d6"/>`;
fill width `f = 365 · min(amount/target, 1)`: none when `f ≤ 0`; a full rounded rect when
`f ≥ 365`; a plain rect when `f < 4`; otherwise
`<path d="M0 15 H{f−4} a4 4 0 0 1 4 4 v6 a4 4 0 0 1 -4 4 H0 Z"/>`; fill colour per use
(`#147d83` default, `#236c48` received income, `#8a5716` spending). Time marker at
`t = 365 · year_elapsed_pct / 100`: first a halo `<line x1=t x2=t y1="12" y2="34"
stroke="#ffffff" stroke-width="6"/>`, then `<line … stroke="#123f4a" stroke-width="2"/>`.
Top label (font-size 9.5, fill `#475d69`, `text-anchor="middle"`, y = 10):
"{Mon D} · {p}% of the year", x clamped to `min(max(t, est/2 + 1), 365 − est/2 − 1)` with
`est = len(label) · 9.5 · 0.53`. Bottom-left label (y 46, 10.5, bold, `#123f4a`):
"{amount} {verb}"; bottom-right (y 46, 10.5, `#475d69`, `text-anchor="end"`): "Target {target}".
When the target is unknown or ≤ 0 the meter is replaced by the text "No readable target".

**Bar rows (one common scale)** — `.route` rows inside a `.bars` panel: label | bar track |
value. Bar width `% = 100 · max(amount, 0) / max(amounts)` (1 decimal). Value text
"{whole dollars} · {share}%" where shares are largest-remainder whole percents summing to
100 over the plotted rows. All tracks share one width and the value column aligns (test:
track-width spread ≤ 0.5 px, value-left spread ≤ 0.5 px, bar error ≤ 1 px). A row whose
amount is unknown shows no bar and the value `–` (`.unk`).

**Stacked bar + category rows** — `.stack` (14 px) with one `<span style="width:{w}%;background:{colour}">`
per rank (top 4 + Other). `w` values are largest-remainder shares to one decimal
(`unit = 0.1`) summing to exactly 100.0. Below it, one `.cat` row per segment: swatch,
label, whole-dollar amount, whole-percent share (largest remainder to 100).

**Monthly bars (P&L)** — `viewBox="0 0 365 150"`: baseline
`<line x1="0" x2="365" y1="70" y2="70" stroke="#ccd9d6"/>`; `n` = months in
`_month_starts(period)`, slot `s = 365/n`, bar width `bw = min(12, 0.32·s)`, scale
`k = 56 / max(max income, max |expense|, 1)`. Per month `i` (centre `c = s·(i + 0.5)`):
income `<rect x=c−bw−1 y=70−income·k width=bw height=income·k fill="#147d83"/>`, expense
`<rect x=c+1 y=70 width=bw height=|expense|·k fill="#edb528"/>` (all to 1 decimal), month
label at `(c, 142)`, font-size 9.5, `text-anchor="middle"`, fill `#475d69`, text = 3-letter
month plus `*` when the month is partial. An uncovered month with no amounts gets no
bars, a label in `#637881` and a `–` at `(c, 74)`. Legend (HTML) beside: sea swatch
"Income", sun swatch "Expenses".

### 1.8 Section heading

`<div class="section-heading"><h2>{title}</h2><span>{qualifier}</span></div>`: 15 px H2 with
a 4 px sea left rule, a 9.5 px muted qualifier right-aligned on the same baseline.

### 1.9 Tables

`table-layout:fixed`, 1 px line border, deep header (9.5 px caps, .07em tracking), zebra rows,
10.5 px cells, padding 4 × 8, first column 27–31 % (set per table with `<col>` widths). A cell
holds a bold primary line plus an optional `.meta` second line rather than extra columns.
Amount columns are right-aligned, tabular and `nowrap`. Every brief table has a fixed row
cap (open requests 4, budget lines 4, P&L categories 4, income lines 7), then one "Other" row.
A total row follows where the page has one (open requests, income lines, P&L Net). The
Budget Snapshot "Other lines" row is a count, not a sum (see § 3.3 row 9). Rows are ≤ 38 px
at print width.

### 1.10 Number and date formatting

* Add `format_whole(value: Decimal | None) -> str` beside `format_money` in `render.py`:
  `None` → `Unknown`; else `Decimal(money_str(value)).quantize(Decimal(1), ROUND_HALF_UP)`
  shown as `$1,234` / `-$1,234` / `$0`. Display only: every sum is computed in exact cents
  first and rounded once at display (never sum rounded values, except the documented
  "target − received" tile, which subtracts the two displayed values so the tiles add up).
* All brief pages and the P&L appendix use `format_whole`. Exact cents remain in
  `records/*.json` and on the index's "Totals shared between reports" table
  (`format_money`, unchanged).
* Percent `pct(part, whole)`: `whole ≤ 0` or unknown → `–`; `part ≤ 0` → `0%`;
  `0 < x < 1` → `<1%`; below target → `min(half_up(x), 99)%`; at or above → `100%+` for
  "of target" uses, `half_up(x)%` for shares.
* Shares that must add to 100 use largest remainder (ties by fixed input order).
* Year elapsed: `days = (min(as_of, end_inclusive) − start).days + 1`,
  `pct = half_up(100·days / (end_exclusive − start).days)`; the marker uses the exact value.
* Dates: long `August 15, 2030` (`_long`), short `Aug 15`, month headers `Aug`.
* Labels are truncated in Python to a per-column character limit (first table column 34,
  bar-row and category labels 22) as `label[:limit−1] + "…"`, with the full label in a
  `title` attribute. Labels stay autoescaped.

### 1.11 Unknown and partial ("unknown is never zero")

* A single headline value that is unknown reads `Unknown`.
* In tables and the P&L matrix an unknown or uncovered cell is a muted en dash:
  `<td class="amt unk" data-state="uncovered" title="No declared bank coverage">–</td>`
  (`data-state` is `uncovered` or `unknown`; tests select on it; the `title` is "No readable amount" for `unknown`). An observed zero is `$0`
  in `.zero`. Never bold amber, never repeated wording per cell.
* A partial month is marked once in its column header (`Aug*`), not in each cell; a partial
  total carries `.partial`.
* One legend line, shown only when a page contains a dash or a star:
  "– Unknown: no declared coverage or no readable amount, never zero. * Partial:
  incomplete coverage or an unreadable target. $0 is an observed zero." It is the
  `chart-note marks` paragraph in the `tail` block of `base.html.j2`, directly above
  "Where things stand".

### 1.12 Narrative ("Where things stand")

`<section class="narrative"><h2>Where things stand</h2><p>{text}</p></section>`, ≤ 4 lines at
print width and ≤ 70 words. Text is generated deterministically from the per-report
templates in § 3 (pluralised with a `plural(n, one, many)` helper; whole dollars; no
judgement words such as "on track"). See open decision D1 for a later private editorial
input.

### 1.13 Audit line and reconciliation line (all summaries)

Directly above the footer, one `.audit` paragraph of at most two lines:

`Audit detail: Adjustments applied {a} · pending {p} · superseded {s} · Adjustment warnings {w}
· Unresolved discrepancies {d} · Findings {f} · Coverage flags {c} · Bridges balanced {b} of
{n}. Listed in records/facts.json and records/reconciliation.json of this run.`

Counts come from § 4. When a bridge on the page is unbalanced, append
`<span class="warn">{bridge title}: residual {whole}</span>` (one per unbalanced bridge).
The file names are **plain text, never links**: the compatibility copies of the summaries sit
beside the pointer, outside the run folder, where a relative `records/` link would break.

### 1.14 Footer (run identity in one compact line)

```html
<footer class="foot">
  <div class="row"><span>Sources: CFO workbook capture{% if page.reimbursement_backed %} and the reimbursement queue as of {{ page.bundle.as_of }}{% endif %} · {{ page.coverage }} · Amounts rounded to whole dollars; exact cents are in the run records{% for note in page.footnotes %} · {{ note }}{% endfor %} · <a href="{{ page.index }}">Main Report Set index</a> · <a href="{{ page.queue }}">Reimbursement Queue</a></span><span>{% if page.period.range %}{{ page.period.range }}{% else %}{{ page.period.label }}{% endif %}{% if page.pages_label %}<br>{{ page.pages_label }}{% endif %}</span></div>
  <div class="id"><span class="private">Private financial report.</span> Run <span class="mono">{{ page.run_id }}</span> · Input set <span class="mono">{{ page.input_sha[:16] }}</span> · Inputs captured {{ page.captured }}</div>
</footer>
```

* `page.captured`: from `context.sources[*].captured_at` in UTC: one `YYYY-MM-DD HH:MM UTC`
  when all fall in the same minute; `YYYY-MM-DD HH:MM–HH:MM UTC` within one day; otherwise
  `{first} to {last} UTC`.
* `coverage_clause`: "Bank coverage complete for the period" or "Bank coverage partial for
  {k} source(s); see the index", from `report.coverage` for the page's period; "No bank
  coverage declared; see the index" when there is no bank source; on the index, "Declared
  coverage per source is in the Inputs table". The as-of date appears once, in the masthead
  `.edition`, not in the footer id line.
* `pages_label`: `1 page` (P&L: `1 page + appendix`).
* The run ID appears once per page (footer only). The 11 metadata cards, the basis box, the
  freshness table and the findings section are removed from every summary.

### 1.15 Phone layout

At ≤ 700 px: full-width sheet with 16 px gutters, edition under the title, tiles 2 × 2,
overview one column, follow-ups one column, footer stacked, P&L appendix in a horizontal
scroll wrapper with a sticky label column. No horizontal page scroll at 390 px.

### 1.16 Height budget and the one-page fit rule

Every list on a brief is capped (§ 1.9, § 3), so page height is bounded by construction.
Budget at print width (729.6 px), in px, against the 973 px Letter content box:

| Block | Budget |
|---|---:|
| Masthead | 82 |
| Scope line | 33 |
| KPI tiles | 80 |
| Overview row | 165 + 15 gap |
| Section heading + table (capped rows + Other + total, header) | 300 + 12 gap |
| Follow-ups (≤ 4, or ≤ 2 on the Budget Snapshot; two columns) **or** second compact table | 120 + 12 gap |
| Narrative (≤ 4 lines) | 78 + 12 gap |
| Audit line (≤ 2 lines) | 34 |
| Footer | 52 |
| **Total** | **≤ 973** |

A page that needs more space drops rows into "Other", never adds a page.

**How the private reference checks fit, translated into a public test**
(`tests/test_main_report_render.py::test_chromium_every_summary_fits_its_pages`, Playwright + Chromium, fictional fixtures only):

1. Load each summary from the rendered run folder (`page.goto(file URI)`), block every
   `http(s)` request, record page errors; assert no requests other than `file:`/`data:`
   and no page errors.
2. Screen at 1100 × 1200: assert `document.documentElement.scrollWidth <= innerWidth`; assert
   no element inside `.sheet` lies outside the sheet's box (±0.5 px) and no element with a
   non-`visible` overflow has `scrollWidth > clientWidth + 1`.
3. `page.emulate_media(media="print")`, viewport width 730: measure
   `document.querySelector('.sheet').getBoundingClientRect().height` (portrait part only:
   exclude `.appendix`) and assert ≤ 973; assert every `table:not(.pnl) tbody tr` height
   ≤ 38 px; assert `.narrative` height ≤ 4.2 × its line height (+ 16 px padding).
4. Produce the PDF exactly as `export.py` does and read it with the existing `_pdf_pages`
   helper: summaries have exactly 1 page of (612, 792); the P&L has page 1 = (612, 792) and
   every later page = (792, 612), and with the standard fixture exactly 2 pages.
5. Required strings in the PDF text (pypdfium2 when installed): the H1, "Where things stand",
   every tile value, the run ID, and "1 page".
6. Phone at 390 × 844: no horizontal page overflow; `.metrics .metric` tops form exactly two
   rows; `.sheet` left padding ≥ 16 px.
7. Bar rows: the common-scale check from § 1.7.
8. **Stress fixture** (as built: the `large`, `large_uncovered` and `adversarial` worlds, which assert at least 45 P&L categories, 40 open requests and 80 budget lines): the same assertions with a fixture that maxes every cap (60 P&L
   categories, 40 open requests, 80 budget lines, 6 processors with 30 categories each,
   every month uncovered, labels of 200 characters of `W`, hostile `<script>` labels). This is
   what proves "bounded by construction"; the P&L appendix may then run to
   `1 + ceil(body rows / 40)` pages, all landscape after page 1, none header-only.

---

## 2. Render plumbing changes (where)

* `render.py`: add `format_whole`, `pct`, `largest_remainder`, `year_elapsed`, `plural`,
  `truncate_label` and `captured_label` (pure helpers, unit-tested); keep `format_money`.
  Replace `_counts`, `_findings` and `_freshness` usage on summaries with
  `_audit(report, names)` (counts, § 4) and `_followups(report, name)` (reader text, § 4). Keep
  `_freshness` for the index only. As built there is no `_bridge_line`: the per-bridge rows
  (§ 3.4) are built inline in `_pnl_summary`.
* `base.html.j2`: masthead + scope (§ 1.4), `{% block content %}`, narrative, audit line,
  footer (§ 1.12–1.14); as built it has the `scope`, `content`, `tail` and `appendix` blocks,
  and `audit` and `footer` are macros in `macros.html.j2`. Remove the meta grid, basis box,
  freshness section and findings macro.
  Keep `head.html.j2` unchanged (CSP, `run_id_meta`, `input_set_meta`, robots).
* `macros.html.j2`: replace `freshness`/`bridge`/`findings` with `tiles`, `pie`, `meter`,
  `bar_rows`, `stack`, `section_heading`, `followups`, `recon_table`, `unknown_cell`, `audit`,
  `footer`, `label`, `pct_of`, `amount`, `followup_qualifier`.
* `index.html.j2` gets its own simple body (§ 3.5) instead of the base content.

---

## 3. Per report: sections and facts mapping

Notation: `R` = `report: ReportFacts` (`models.py:2003`), `school` =
`R.view("school", "adjusted")`, `calendar` = `R.view("calendar", "adjusted")`,
`source_cal` = `R.view("calendar", "source")` (`ReportFacts.view`, `models.py:2033`;
`PnlView`, `models.py:1534`). `RF` = `R.reimbursements` (`ReimbursementFacts`,
`models.py:1784`). Bucket names come from `EXPENSE_BUCKETS` / `PAYMENT_BUCKETS`
(`"prior"`, `"current"`, `"later"`, `"undated"`, `"unpaid"`). Every path below was checked
against `models.py`, `facts.py` and `render.py` on 2026-10-22.

**GAP** marks a reference element with no facts source. Recommendations: **omit**,
**derive** (deterministic from facts, specified here) or **editorial** (a later optional
private input, see D1). No GAP may be filled with an invented or typed number.

### 3.1 Reimbursement Summary (reference: the accepted reimbursement board brief)

| # | Section / element | Content | Facts source |
|---|---|---|---|
| 1 | Masthead, scope | § 1.4; scope adds "· includes {n} prior-year carryover(s)" when n > 0 | `R.periods.school`; n = `sum(e.carryover for e in RF.queue)` (`QueueEntry.carryover`, `models.py:1715`) |
| 2 | Tile 1 "Requests tracked" | count | derive: `len({i.review_key for i in RF.items} ∪ {q.review_key for q in RF.queue})` (`ReimbursementItemFact.review_key`, `models.py:1640`) |
| 3 | Tile 2 "Closed" (`closed`) | count | derive: tracked − open |
| 4 | Tile 3 "Still open" (`open`) | count | `len(RF.queue)` |
| 5 | Tile 4 "Needs clarification" (`amount`) | whole dollars; `<small>` "{k} item(s) without an amount" when k > 0 | `sum(RF.open_amount(b, "C") for b in EXPENSE_BUCKETS)` (`models.py:1826`); k = `sum(t.unpriced for t in RF.totals if t.open and t.status == "C")` (`ReimbursementTotal`, `models.py:1687`) |
| 6 | Overview left: pie "{p}% of requests are closed" + legend `closed`/`open` counts + chart note "Share of tracked requests, by count." | § 1.7 pie, first part = closed, wedge = open | tiles 2–4 |
| 7 | Overview right: callout "Paid in the period" | value `format_whole(RF.paid("current"))` + `<span>` "across {m} request(s)"; split: "{x} matched to a bank row · {y} not yet matched"; second split line "{z} paid for prior-year expenses"; note "Payments are placed by payment date; prior-year expenses paid this year are never added to this year's expenses." | `RF.paid` (`models.py:1815`); m = `len({i.review_key for i in RF.items if i.payment_bucket == "current"})`; joins in period = `[j for j in RF.joins if R.periods.school.position(j.payment_date) == "current"]` (`PaymentJoin`, `models.py:1754`), x = state `matched`, y = the rest; z = `format_whole(RF.paid("current", "prior"))` |
| 8 | Section "Largest open requests" (qualifier "Approved and not yet paid: {format_whole(RF.outstanding)}") | ≤ 4 rows (`_OPEN_REQUEST_ROWS`) sorted by `pay_now` desc, `submitted` asc, `ticket_ref`; columns Request (bold ref, `.meta` "submitted {iso}") · Earliest expense · Undated items · Pay now · Prior-year carryover (chip `warn` "By expense date"/"By submission", else muted "No"); then `tr.other` "{n} more open request(s) in the Reimbursement Queue" (link `page.queue`) and `tr.total` "All open requests" = `RF.outstanding` | `RF.queue[*].ticket_ref, submitted, earliest_expense_date, undated_items, pay_now, carryover_basis`; `RF.outstanding` |
| 9 | Section "Data follow-ups" | ≤ 4 `.followup` cards from § 4 reader text for codes `reimbursement_*` and `bundle_as_of_outside_period`; "No data follow-ups." when none | `R.issues` (`FactIssue.code, count`, `models.py:1991`) |
| 10 | Narrative | template below | facts above |
| 11 | Audit + footer | § 1.13–1.14; bridges on this page: `school_payment_timing`, `school_expense_basis` | `R.bridge(name).balanced`, `.residual` (`models.py:1619–1623`) |

Narrative template: "{tracked} request(s) are tracked for {period label}: {closed} closed and
{open} open{, {carry} of them prior-year carryover(s)}. {paid} was paid in the period across
{m} request(s); {x} of {x+y} payment(s) match a bank row. {outstanding} is approved and not yet
paid{, and {clar} needs clarification}."

Per-request links: the queue's anchor is `(ref + "-" + form_label if form_label)`, lower-cased,
spaces → `-`. `form_label` is not in the facts; derive it from the staged bundle's ticket with
the same `review_key` (the bundle is already loaded in `write`) and link
`reimbursement-report.html#{anchor}` as `a.ref` only when the anchor is unique in the
rendered queue; otherwise print the ref as text. Never print a requester name, email or
payment reference.

GAPs (Reimbursement Summary, 9):

| GAP | Reference element | Recommendation |
|---|---|---|
| R1 | Tile note "includes an amount that appears already paid" (needs a private bank-to-item payment reconciliation) | omit |
| R2 | Chart note on returned payments | omit (later: a returned-payment fact) |
| R3 | "Latest payment update" total since the previous edition (needs the previous edition's state) | derive replacement: "Paid in the period" (row 7) |
| R4 | Payment-method split and cleared amounts | derive replacement: bank-join state counts (row 7) |
| R5 | Payment note detail (check numbers, issue dates, earlier-edition corrections) | omit |
| R6 | "For board discussion" editorial rows | derive replacement: "Largest open requests" (row 8); editorial later (D1) |
| R7 | "Other open follow-ups" editorial cards | derive replacement: data follow-ups from `R.issues` (row 9) |
| R8 | Hand-written narrative | derive template; editorial later (D1) |
| R9 | Per-request anchor links (`form_label` not in facts) | derive from the staged bundle by `review_key` |

### 3.2 Fundraising Summary (reference: the accepted fundraising board brief)

The reference counts deposits toward a yearly goal (the sum of the adopted income lines), with
a time marker, a by-month line, a payment-route panel and a per-line table. The facts support
the same shape on the **bank basis** (all income categories) plus the processor view; see D3.

| # | Section / element | Content | Facts source |
|---|---|---|---|
| 1 | Masthead, scope | § 1.4 | `R.periods.school` |
| 2 | Tile 1 "Income received since {start Mon D}" | whole dollars, `.partial` when the view is incomplete | `school.income`, `school.complete` |
| 3 | Tile 2 "Of the {target} adopted income target" | `pct(received, target)`; `Unknown` when no readable target | target = `sum(l.target for l in R.budget.lines if l.line_type == "income" and l.target is not None)` (`BudgetLine`, `models.py:1859`); partial when any income line has `target is None` |
| 4 | Tile 3 "Still to reach the target by {end Mon D}" | `display(target) − display(received)`; when reached: value "Target reached", label "Above target: {x}" | tiles 2–3 |
| 5 | Tile 4 "Processors complete" (`open` when not all) | "{c} of {n}"; `<small>` "{u} with no rows or coverage" when u > 0 | `R.fundraising[*].complete` (`models.py:1970`); u = processors with `"coverage_partial"` in `incomplete_reasons` and no rows (rule from `_fundraising_summary`) |
| 6 | Overview left: "{p} of the adopted income target" + meter (§ 1.7, fill `#236c48`, verb "received") + months line "By month: Jul $X · Aug $Y …" + chart note "The marker shows how much of the school year has passed. It is not a target." | | `school.months[*].month, .income` (`PnlMonthTotal`, `models.py:1005`); year elapsed from `R.periods.school` |
| 7 | Overview right: `.bars` "How processor money arrived" (head span "Gross · share of all processor gross"); one `.route` per processor (label = `source_alias`); sub line "Processor gross by payment date. Payouts reach the bank later and are already inside bank income; never add the two."; last line "Fees {f} · Refunds {r} · Net {n}" and "{a}% of gross attributed to a category; {k} sale(s) not attributed"; more than 4 processors (`_ROUTE_ROWS`): the 3 largest by gross plus one "Other (n processors)" row, and an unknown processor sorts last | | `R.fundraising[*].source_alias, gross, fees, refunds, net, categories[*].category, count, gross` (`FundraisingTotals` `models.py:1947`, `FundraisingCategory` `models.py:1925`); unknown processor → value `–` |
| 8 | Section "Income lines this year" (qualifier "Adopted target and bank income to date") | ≤ 7 income lines by target desc, then `tr.other` "Other income lines ({n})", `tr.total`; columns Line (category) · Target · Received to date · Can we measure it yet? | `R.budget.lines` where `line_type == "income"`: `category`, `target`, `actual` (income activity = actual), `actual_status` (`BUDGET_ACTUAL_STATUSES`, `models.py:231`) |
| 9 | Section "Data follow-ups" | ≤ 4 cards: `processor_rows_excluded` issue, processor coverage flags, per-processor `incomplete_reasons` | `R.issues`, `R.coverage_flags` (`CoverageFlag`, `models.py:1148`), `R.fundraising[*].incomplete_reasons` |
| 10 | Narrative, audit, footer | no bridges on this page ("Bridges balanced" omitted) | |

"Can we measure it yet?" text by `actual_status`: `observed` → "Yes · bank, crosswalked";
`coverage_partial` → "In part · bank coverage incomplete"; `crosswalk_missing` → "Not yet · no
category crosswalk"; `category_unmapped` → "Not yet · no source category maps here";
`ambiguous` → "Not yet · more than one adopted line". An unknown received amount is the
muted dash (§ 1.11).

Narrative template: "{received} of income has reached the bank so far this school year,
{p} of the {target} adopted income target, with {y}% of the year elapsed. Online processors
recorded {gross} gross and {net} after fees and refunds{; {k} of {n} processor(s) are
incomplete}."

GAPs (Fundraising Summary, 10):

| GAP | Reference element | Recommendation |
|---|---|---|
| F1 | "Raised" on a fundraising-only basis (interest, transfers and reversals removed by channel) | derive replacement: bank-basis income, labelled as such (D3) |
| F2 | Payment-route breakdown of deposits (website, giving platforms, checks, other) | derive replacement: processor bar rows (row 7) |
| F3 | Treasurer attribution rules (deposits counted toward a named fundraiser) | omit; editorial/policy input later (D1) |
| F4 | "Goal after planned costs" per fundraiser (paired expense lines) | omit |
| F5 | "When / status" per fundraiser | omit; editorial later (D1) |
| F6 | "Next fundraiser" tile and highlighted row | derive replacement: "Processors complete" tile |
| F7 | "For board decision" cards | omit; editorial later (D1) |
| F8 | "How you can help" / hand-written closing | derive template narrative |
| F9 | Sponsor tracker totals | omit |
| F10 | Deposits received but not yet posted | omit |

### 3.3 Budget Snapshot (reference: the accepted one-slide treasurer cash snapshot, re-laid portrait)

The operator maps the cash snapshot (balances, raised, net spent, where money went, where it
came from, progress against the budget, story) to this page. The facts carry flows, not
balances, so the balance card becomes a net-flow tile.

| # | Section / element | Content | Facts source |
|---|---|---|---|
| 1 | Masthead, scope | § 1.4 | `R.periods.school` |
| 2 | Tile 1 "Received (bank basis)" (`closed`) | whole dollars, `.partial` if incomplete | `school.income`, `school.complete` |
| 3 | Tile 2 "Spent (bank basis)" (`spent`) | `format_whole(−school.expense)` | `school.expense` (negative by contract, `month_totals_from`) |
| 4 | Tile 3 "Unknown actuals" (`open` when > 0) | count; `<small>` "of {n} adopted lines" | `sum(l.actual is None for l in R.budget.lines)`, `len(R.budget.lines)` |
| 5 | Tile 4 (1.4fr) "{label} adjusted bank net" | `format_whole(school.net)`, `.partial`; `<small>` "A change over the period, not a balance" | `school.net` (same scope as `shared.school_net`) |
| 6 | Overview left: "Where money went" — stacked bar + top 4 expense categories + Other | § 1.7 stacked bar; amounts are magnitudes | categories with net < 0 from `school.category_totals()` (`models.py:1554`), sorted by magnitude |
| 7 | Overview right: `.bars` "Where money came from" — top 4 income categories + Other on one scale | § 1.7 bar rows | categories with net > 0 from `school.category_totals()` |
| 8 | Section "Progress against the adopted budget" (qualifier "{y}% of the year has passed · income {x} · spending {z} of target") | two meters side by side (`.overview` grid): income received vs income target (fill `#236c48`, verb "received"); spending vs expense target (fill `#8a5716`, verb "spent"); under each: "{p} of target" | income target as in § 3.2 row 3; expense target = same over `line_type == "expense"`; amounts `school.income`, `−school.expense` |
| 9 | Section "Largest budget lines" (qualifier "Crosswalk version {v}" or "No category crosswalk") | ≤ 4 lines by target desc (`_BUDGET_ROWS`); columns Type · Category · Target · To date · Target less to date · Status; `tr.other` "Other lines ({n})", a count, not a sum: its amounts read "not totaled; see run records" and its status cell counts income / expense / other lines (a sum would blend income and expense targets and cover only known actuals); this table has no total row; then one `.chart-note`: "{u} line(s) outside the adopted lines: {format_whole(sum)} · {o} row(s) of other fiscal years · {t} line(s) neither income nor expense" | `R.budget.lines[*].line_type, category, target, actual, actual_status`; activity = `actual` (income) or `−actual` (expense); `R.budget.crosswalk_version`, `.unmapped`, `.unbudgeted`, `.other_year_rows` (`BudgetFacts`, `models.py:1896`) |
| 10 | Section "Data follow-ups" | ≤ 2 cards (`_BUDGET_FOLLOWUPS`; the page also carries the progress meters; the qualifier reads `N of M shown; all are in records/facts.json` when truncated, else `Counts only; details are in the run records`) from `budget_*` issue codes and `crosswalk_absent` / `school_coverage_partial` / `bank_coverage_absent` flags | `R.issues`, `R.coverage_flags` |
| 11 | Narrative, audit, footer | bridges on this page: `school_source_scope`, `school_adjustments`, `school_budget_crosswalk`; footer adds "No calendar-year budget is derived from these annual targets." | `R.bridge(...)` |

Status text per line reuses `_BUDGET_REASONS` / "Observed"; an unknown "to date" or
"target less to date" is the muted dash.

Narrative template: "So far in {label}, the bank view shows {income} received and {spent}
spent, a net of {net}{ (partial: bank coverage is incomplete)}. That is {pi} of the adopted
income target and {pe} of the adopted expense target, with {y}% of the year elapsed. {u} budget
line(s) have an unknown actual."

GAPs (Budget Snapshot, 9):

| GAP | Reference element | Recommendation |
|---|---|---|
| B1 | Opening and latest bank balances with change | derive replacement: net-flow tile (row 5); balances need a new captured fact (D4) |
| B2 | Per-account balance chips | omit |
| B3 | Prior-board obligation excluded from spending | omit; if needed, record it as a reporting adjustment so it reaches the facts |
| B4 | Pending and held deposits chip | omit |
| B5 | "Raised" scoped to fundraising only (interest excluded) | derive replacement: all bank-basis income, labelled |
| B6 | Spending split by payment rail (checks, transfers, cards, operations) | derive replacement: top expense categories (row 6) |
| B7 | "Early signal: on track" verdict | derive neutral pace text (row 8 qualifier and meters); no verdict |
| B8 | "The story so far" paragraph | derive template narrative; editorial later (D1) |
| B9 | Footer balance notes (uncleared checks, maturing deposits, accrued interest) | omit |

### 3.4 CFO P&L Summary (no reference; same visual language)

**Page 1 — portrait brief**

| # | Section / element | Content | Facts source |
|---|---|---|---|
| 1 | Masthead, scope | § 1.4 incl. the adjustments clause | `R.periods.calendar`, `R.applied_adjustments` |
| 2 | Tile 1 "Income year to date" | whole dollars, `.partial` if incomplete | `calendar.income`, `calendar.complete` |
| 3 | Tile 2 "Expenses year to date" (`spent`) | `format_whole(−calendar.expense)` | `calendar.expense` |
| 4 | Tile 3 "Net year to date" | `format_whole(calendar.net)` | `calendar.net` (same as `shared.calendar_net`) |
| 5 | Tile 4 "Months with declared bank coverage" (`open` when incomplete) | "{x} of {n}"; `<small>` "Control check: {humanized}" | `_month_covered` / `_month_starts` (`render.py:980–1006`) with `R.coverage` (`CoverageStatus`, `models.py:844`); `R.pnl_control_status` |
| 6 | Overview left: "Income and expenses by month" + monthly bars (§ 1.7) + legend | | `calendar.months[*].month, income, expense`; coverage per month as tile 4 |
| 7 | Overview right: callout "Reconciliation" | value "{b} of {n}" + span "bridges balance"; split "Control check against the CFO P&L: {status}"; note "{a} adjustment(s) applied · {p} pending after the as-of date. Uncovered months are unknown, not zero." | bridges `calendar_source_scope`, `calendar_adjustments`, `calendar_to_school`; `R.pending_adjustments` |
| 8 | Section "Largest categories year to date" (qualifier "Adjusted view") | 4 rows (`_PNL_ROWS`): the largest income and the largest expense category are always shown (`_PNL_SIDE_ROWS` = 1 each), the remaining rows fill by \|YTD\| desc then name; columns Category · Type (Income/Expense by sign; Zero for a 0 net category) · Year to date · Share of income or expenses · Months with activity; `tr.other` "Other, net ({n} categories)"; `tr.total` "Net" | `calendar.category_totals()`; months with activity = count of `calendar.cells` (`MonthlyCategoryCell`, `models.py:974`) for that category with `net != 0` |
| 9 | Section "Reconciliation" (qualifier "One line per bridge; records in the run folder") | one row per bridge: Bridge (short title) · From · Explained · Residual · Status (`chip.ok` "Balanced" / `chip.stop` "Residual") · Records (count) | `Bridge.from_amount, to_amount, rows[*].amount, residual, balanced` (`models.py:1602`); records = Σ `len(refs) + len(adjustment_ids) + len(item_keys)` over rows (`BridgeRow`, `models.py:1575`) |
| 10 | Narrative, audit, footer | footer adds "Budgets are school-year targets; see the Budget Snapshot." | |

Short bridge titles: "Source months → calendar year", "Source view → adjusted view",
"Calendar year → school year". Explained = Σ row amounts; From and Residual in whole dollars.

Narrative template: "Through {through}, the calendar year shows {income} income, {expenses}
expenses and a net of {net}. The largest income category is {ci} ({ai}); the largest expense
category is {ce} ({ae}). {x} of {n} months have declared bank coverage{; the others are unknown,
not zero}."

**Appendix — landscape (`<section class="appendix">`)**

* Heading "Appendix: monthly P&L (adjusted) and year to date" + qualifier "Whole dollars;
  exact cents in records/facts.json".
* `table.pnl` columns: Category · one column per month of `_month_starts(calendar period)`
  (header `Jan`, `Feb`…, with `*` when that month is partial) · Year to date.
* Body: `tr.group` "Income" then income categories (YTD > 0), `tr.group` "Expenses" then
  expense categories (YTD ≤ 0), each sorted by |YTD| desc then name; totals `Income`,
  `Expenses`, `Net` from `calendar.months`. Add `Source net (CFO view)` and `Adjustments`
  rows **only** when `R.applied_adjustments` is non-empty or `calendar.net != source_cal.net`.
* Cells: value → `format_whole`; no cell in a covered month → `$0` (`.zero`); no cell in an
  uncovered month → muted dash with `data-state="uncovered"`; a value in an uncovered month →
  the value (the column star says partial). YTD sums exact cents, then rounds.
* Capacity: 40 body rows per landscape page at 9.5 px (`_APPENDIX_ROWS`; the 40 counts every matrix row, including the Income/Expenses group rows, the Income/Expenses/Net total rows and the optional Source net/Adjustments rows, see `_appendix_pages`); beyond that the table continues on more
  landscape pages with the repeated header.

P&L GAPs: 1 — P1 interpretive commentary (why a category moved) → omit; the template
narrative states only facts. (Budget comparison is excluded by contract, not a gap.)

### 3.5 Index (`main-report-set.html`) — a short link page

Masthead + scope ("{school label} and {calendar label} · through {as of}"), then:

1. "The five reports": the existing link cards (HTML / PDF / PNG / copy text).
2. "Totals shared between reports": the existing exact-cents table (unchanged values and
   partial markers); this is the one place cents are shown.
3. "Inputs": one compact table — Source · Kind · Captured (UTC) · School-year coverage ·
   Calendar-year coverage — for transaction feeds only; one sentence for non-feed captures
   ("Also captured: {aliases} (not transaction feeds).").
4. "Run records": the audit counts of § 4 and links to `records/facts.json`,
   `records/reconciliation.json`, `records/adjusted-ledger.json`, `records/journal.json`
   (the index lives only in the run folder, so these relative links resolve).
5. Footer (§ 1.14 with `pages_label` omitted).

At most 2 portrait pages; no findings tables, no ID lists.

---

## 4. Audit detail policy

Summaries show **counts plus a pointer**, never lists:

| Item | Shown as | Source | Full detail |
|---|---|---|---|
| Unresolved discrepancies | count | `len(R.discrepancy_ids)` | `records/facts.json` (`discrepancy_ids`), `records/reconciliation.json` (`discrepancies`) |
| Adjustments applied / pending / superseded | counts | `len(R.applied_adjustments)`, `len(R.pending_adjustments)`, `len(R.superseded_adjustments)` | `records/facts.json`, `records/journal.json` |
| Adjustment warnings | count | `len(R.adjustment_warnings)` | `records/facts.json` |
| Findings | Σ count | `sum(i.count for i in R.issues)` | `records/facts.json` (`issues`) |
| Coverage flags | count | `len(R.coverage_flags)` | `records/facts.json` (`coverage_flags`) |
| Bridge evidence rows | count per bridge (P&L table) or "Bridges balanced b of n" | `Bridge.rows[*]` refs, adjustment IDs, item keys | `records/facts.json` (`bridges`) |
| Row-level issues (normalization warnings) | not on summaries (not in `ReportFacts`) | — | `records/reconciliation.json` (`row_warnings`) |

Rules:

* No inline discrepancy IDs, adjustment IDs, evidence lists or source row numbers on any
  summary.
* Unknown is never zero: muted dash + the one legend line (§ 1.11); `Unknown` for a single
  headline value.
* Data follow-up cards (≤ 4 per summary, chosen by the per-report code filter in § 3, ordered
  by count desc then code) use reader text. `{n}` is the issue `count` or flag `count`:

| Code | Title | Line |
|---|---|---|
| `reimbursement_item_undated` | Items without an expense date | {n} item(s) have no expense date; they stay undated and are never assigned a year. |
| `reimbursement_item_unpriced` | Items without an amount | {n} item(s) have no amount; they are counted, never shown as $0. |
| `reimbursement_payment_undated` | Payments without a date | {n} recorded payment(s) have no payment date. |
| `reimbursement_payment_unmatched` | Payments not found in the bank | {n} recorded payment(s) have no matching bank row yet. |
| `reimbursement_payment_ambiguous` | Payments with several bank matches | {n} recorded payment(s) match more than one bank row. |
| `reimbursement_payment_no_reference` | Payments without a reference | {n} recorded payment(s) carry no reference to match. |
| `bundle_as_of_outside_period` | Queue date outside the period | The reimbursement queue's as-of date falls outside this period. |
| `budget_year_unreadable` | Unreadable budget year | {n} adopted row(s) have a fiscal year that cannot be read. |
| `budget_type_unrecognized` | Line type not income or expense | {n} line(s) are in neither target total. |
| `budget_amount_missing` | Lines without a target | {n} line(s) have no target; target totals are partial. |
| `budget_amount_unreadable` | Unreadable targets | {n} target(s) cannot be read; target totals are partial. |
| `budget_line_ambiguous` | Category on more than one line | {n} category(ies) have more than one adopted line. |
| `budget_actual_unknown` | Lines with an unknown actual | {n} line(s) have no comparable bank amount yet. |
| `processor_rows_excluded` | Processor rows left out | {n} conflicting processor row(s) are left out of every total. |
| `processor_rows_excluded_reported` | Processor rows left out | {n} processor(s) left conflicting rows out of their totals. |
| `processor_coverage_partial` | Processor coverage incomplete | {n} processor(s) have no declared coverage for the whole period. |
| `school_coverage_partial` / `calendar_coverage_partial` | Bank coverage incomplete | Declared bank coverage does not span the whole period. |
| `bank_coverage_absent` | No bank coverage declared | No declared bank coverage; bank totals are partial. |
| `pnl_control_mismatched` / `_unverified` / `_absent` | CFO P&L control check | The control check against the CFO P&L is {mismatched / unverified / absent}. |
| `crosswalk_absent` | No category crosswalk | Budget actuals stay unknown until a crosswalk is configured. |
| `processor_gross_unsettled` | Processor sales not yet paid out | Some processor sales have not reached the bank yet. |
| `processor_view_inconsistent` | Processor views disagree | Two feeds of one processor disagree; its totals are incomplete. |
| any other code | `_humanize(code)` | {n} occurrence(s); see records/facts.json. |

`FactIssue.subject` is not shown on summaries.

---

## 5. Acceptance checklist

1. With the standard fictional fixtures, each of `reimbursement-summary.pdf`,
   `fundraising-summary.pdf` and `budget-snapshot.pdf` has exactly 1 page of 612 × 792 pt.
2. `cfo-pnl-summary.pdf` has page 1 at 612 × 792 pt and every later page at 792 × 612 pt; with
   the standard fixture it has exactly 2 pages. Under the stress fixture it has
   `1 + ceil(body rows / 40)` pages, none of them header-only.
3. The print-width layout test of § 1.16 passes for all four summaries with both the standard
   and the stress fixture (sheet height ≤ 973 px, rows ≤ 38 px, narrative ≤ 4 lines).
4. No horizontal page overflow and no clipped element at 1100 px, 1280 px and 390 px; tiles
   are 2 × 2 at 390 px; the existing readability floor (`td, th, p, li` ≥ 9.5 px) holds.
5. Pages make no network request and run no script (existing CSP, existing export tests).
6. Every summary and the index still carry `<meta name="pta-run-id" …>` (`RUN_ID_META_NAME`)
   and `<meta name="pta-input-set" …>` exactly as `run_id_meta` / `input_set_meta` render
   them; `runner._check_set` and `_check_pointer` pass unchanged; the run ID appears once in
   each summary's footer.
7. Privacy guard: the CSP, `noindex`, autoescaping and the "Private financial report" label
   remain; no summary or PDF text contains any token of a `requestor_name` from the fixture
   bundle, any email address, phone number or payment reference; hostile labels stay escaped.
8. No summary contains a discrepancy ID (`DISC-` prefix), an adjustment ID (`ADJ-` prefix), a
   source row reference, or the word "Not covered"; the audit line's counts equal § 4's
   sources.
9. Every money string on a summary is whole dollars (except a nonzero bridge residual that would round to $0, which prints in cents) and traces to a facts-derived value of
   § 3 (assert against a per-page allowed set built from the facts); the index's shared-total
   table still shows exact cents equal to `format_money` of the shared totals.
10. Shares on each bar or stacked chart sum to exactly 100 (or 100.0); bar rows pass the
    common-scale check.
11. Unknown is never zero: an uncovered month renders the muted dash with
    `data-state="uncovered"`, a covered empty month renders `$0`, an unknown headline renders
    `Unknown`, and the legend line appears exactly once when either marker is present.
12. The index stays a short link page: ≤ 2 portrait pages, links to all five reports and their
    exports, the shared totals table, the inputs table and the run-record links.
13. `export.VIEWPORT_WIDTH` remains 1100; each PNG is a full-page capture of that width.
14. Full suite gate per the workspace rule (all test roots, emulator modules included), ruff,
    ruff format and `mypy --strict pta_finance` pass.

## 6. Tests (as built)

Step 64 rewrote `tests/test_main_report_render.py` to this contract (86 cases). The fit gate is `test_chromium_every_summary_fits_its_pages` over four fixtures: `standard`, `large`, `large_uncovered` and `adversarial`.

## 7. Operator decisions (recorded 2026-10-23)

* **D1 Editorial text: template narratives now.** Build only the deterministic template
  narratives in this spec. An optional private editorial input (narrative, discussion rows,
  decisions) validated against the facts with no literal amounts is a later, separate step.
* **D2 Bank coverage: declared privately.** The operator declared the checking account's
  calendar-year coverage, with evidence, in the private config. The design must still render
  partial or undeclared periods per §1.11. No coverage is hard-coded here.
* **D3 Fundraising basis: bank-basis income, labelled.** Show income received on the bank
  basis (all income categories) against the adopted income targets, labelled as such. A
  fundraising-only fact is a later step.
* **D4 Balances: net flow only.** The Budget Snapshot shows money in, money out and net for
  the period. Balances wait for a captured balance source.
* **D5 Header wording: keep the defaults** ("Private Main Report Set", "For the board").
* **D6 Appendix length: accepted.** The P&L appendix may run to a second landscape page
  when the matrix has more than 40 body rows.
